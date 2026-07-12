from __future__ import annotations

import ctypes
import json
import os
import socket
import time
from ctypes import wintypes
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Mapping
from urllib.request import urlopen


HwndPidResolver = Callable[[int], int]
TcpListenerResolver = Callable[[], Mapping[int, set[int]]]
ProcessParentResolver = Callable[[], Mapping[int, int]]
EndpointProbe = Callable[[int], bool]


_PROCESS_SNAPSHOT_LOCK = Lock()
_PROCESS_SNAPSHOT_MAX_ATTEMPTS = 3
_PROCESS_SNAPSHOT_RETRY_DELAYS = (0.05, 0.1, 0.2)


@dataclass(frozen=True)
class CdpOwnershipResult:
    status: str
    hwnd: int
    window_pid: int
    port: int = 0
    owner_pid: int = 0
    relation_mode: str = ""
    snapshot_attempts: int = 0
    snapshot_error: str = ""
    winerror: int = 0
    endpoint_status: str = "not_checked"

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def safe_message(self) -> str:
        snapshot_error = _safe_error_text(self.snapshot_error) or "none"
        return (
            f"hwnd={int(self.hwnd or 0)} pid={int(self.window_pid or 0)} "
            f"port={int(self.port or 0)} owner_pid={int(self.owner_pid or 0)} "
            f"relation_mode={self.relation_mode or 'none'} "
            f"snapshot_attempts={int(self.snapshot_attempts or 0)} "
            f"snapshot_error={snapshot_error} winerror={int(self.winerror or 0)} "
            f"endpoint_status={self.endpoint_status or 'not_checked'} final_status={self.status}"
        )


@dataclass(frozen=True)
class _ProcessParentSnapshotResult:
    parents: Mapping[int, int] | None
    attempts: int
    error: str = ""
    winerror: int = 0


class ProcessSnapshotError(RuntimeError):
    def __init__(self, message: str, *, attempts: int, winerror: int = 0) -> None:
        super().__init__(message)
        self.attempts = int(attempts or 0)
        self.winerror = int(winerror or 0)


def validate_window_cdp_endpoint(
    hwnd: int,
    window_pid: int,
    port: int,
    *,
    hwnd_pid: HwndPidResolver | None = None,
    tcp_listeners: TcpListenerResolver | None = None,
    process_parents: ProcessParentResolver | None = None,
    endpoint_probe: EndpointProbe | None = None,
) -> CdpOwnershipResult:
    clean_hwnd = int(hwnd or 0)
    clean_pid = int(window_pid or 0)
    clean_port = int(port or 0)
    hwnd_pid_func = hwnd_pid or get_window_pid
    listener_func = tcp_listeners or list_tcp_listeners_by_port
    parents_func = process_parents or _list_process_parents_once
    probe_func = endpoint_probe or probe_cdp_endpoint

    if clean_hwnd <= 0:
        return CdpOwnershipResult("hwnd_invalid", clean_hwnd, clean_pid, clean_port)
    if clean_pid <= 0:
        return CdpOwnershipResult("pid_missing", clean_hwnd, clean_pid, clean_port)
    try:
        current_pid = int(hwnd_pid_func(clean_hwnd) or 0)
    except Exception:
        current_pid = 0
    if current_pid != clean_pid:
        return CdpOwnershipResult("hwnd_pid_mismatch", clean_hwnd, clean_pid, clean_port)
    if clean_port <= 0:
        return CdpOwnershipResult("cdp_port_missing", clean_hwnd, clean_pid, clean_port)

    try:
        listeners = listener_func()
    except Exception:
        return CdpOwnershipResult("cdp_owner_unverified", clean_hwnd, clean_pid, clean_port)
    owners = {int(pid) for pid in listeners.get(clean_port, set()) if int(pid or 0) > 0}
    if not owners:
        return CdpOwnershipResult("cdp_port_missing", clean_hwnd, clean_pid, clean_port)
    if len(owners) > 1:
        return CdpOwnershipResult("cdp_owner_conflict", clean_hwnd, clean_pid, clean_port, min(owners))
    owner_pid = min(owners)
    relation_mode = "verified_same_pid"
    snapshot = _ProcessParentSnapshotResult({}, 0)
    if owner_pid != clean_pid:
        snapshot = _resolve_process_parents_with_retry(parents_func)
        if snapshot.parents is None:
            return CdpOwnershipResult(
                "cdp_owner_unverified",
                clean_hwnd,
                clean_pid,
                clean_port,
                owner_pid,
                relation_mode="process_tree_snapshot_failed",
                snapshot_attempts=snapshot.attempts,
                snapshot_error=snapshot.error,
                winerror=snapshot.winerror,
            )
        relation_mode = "verified_process_tree"
    parents = snapshot.parents or {}
    related = sorted(pid for pid in owners if _same_direct_process_tree(clean_pid, pid, parents))
    if len(related) != 1:
        return CdpOwnershipResult(
            "cdp_owner_mismatch" if not related else "cdp_owner_conflict",
            clean_hwnd,
            clean_pid,
            clean_port,
            owner_pid,
            relation_mode="process_tree_mismatch",
            snapshot_attempts=snapshot.attempts,
            snapshot_error=snapshot.error,
            winerror=snapshot.winerror,
        )
    owner_pid = related[0]
    try:
        reachable = bool(probe_func(clean_port))
    except Exception:
        reachable = False
    if not reachable:
        return CdpOwnershipResult(
            "cdp_unavailable",
            clean_hwnd,
            clean_pid,
            clean_port,
            owner_pid,
            relation_mode=relation_mode,
            snapshot_attempts=snapshot.attempts,
            snapshot_error=snapshot.error,
            winerror=snapshot.winerror,
            endpoint_status="probe_failed",
        )
    return CdpOwnershipResult(
        "verified",
        clean_hwnd,
        clean_pid,
        clean_port,
        owner_pid,
        relation_mode=relation_mode,
        snapshot_attempts=snapshot.attempts,
        snapshot_error=snapshot.error,
        winerror=snapshot.winerror,
        endpoint_status="verified",
    )


def discover_window_cdp_endpoint(
    hwnd: int,
    window_pid: int,
    *,
    hwnd_pid: HwndPidResolver | None = None,
    tcp_listeners: TcpListenerResolver | None = None,
    process_parents: ProcessParentResolver | None = None,
    endpoint_probe: EndpointProbe | None = None,
) -> CdpOwnershipResult:
    clean_hwnd = int(hwnd or 0)
    clean_pid = int(window_pid or 0)
    hwnd_pid_func = hwnd_pid or get_window_pid
    listener_func = tcp_listeners or list_tcp_listeners_by_port
    parents_func = process_parents or _list_process_parents_once
    probe_func = endpoint_probe or probe_cdp_endpoint

    if clean_hwnd <= 0:
        return CdpOwnershipResult("hwnd_invalid", clean_hwnd, clean_pid)
    if clean_pid <= 0:
        return CdpOwnershipResult("pid_missing", clean_hwnd, clean_pid)
    try:
        current_pid = int(hwnd_pid_func(clean_hwnd) or 0)
    except Exception:
        current_pid = 0
    if current_pid != clean_pid:
        return CdpOwnershipResult("hwnd_pid_mismatch", clean_hwnd, clean_pid)
    try:
        listeners = listener_func()
    except Exception:
        return CdpOwnershipResult("cdp_owner_unverified", clean_hwnd, clean_pid)

    candidates: list[CdpOwnershipResult] = []
    snapshot: _ProcessParentSnapshotResult | None = None
    for port in sorted(int(value) for value in listeners if int(value or 0) > 0):
        owners = {int(pid) for pid in listeners.get(port, set()) if int(pid or 0) > 0}
        if len(owners) != 1:
            continue
        owner_pid = min(owners)
        relation_mode = "verified_same_pid"
        current_snapshot = _ProcessParentSnapshotResult({}, 0)
        if owner_pid != clean_pid:
            if snapshot is None:
                snapshot = _resolve_process_parents_with_retry(parents_func)
            current_snapshot = snapshot
            if current_snapshot.parents is None:
                continue
            relation_mode = "verified_process_tree"
        related = sorted(
            pid for pid in owners if _same_direct_process_tree(clean_pid, pid, current_snapshot.parents or {})
        )
        if len(related) != 1:
            continue
        try:
            if probe_func(port):
                candidates.append(
                    CdpOwnershipResult(
                        "verified",
                        clean_hwnd,
                        clean_pid,
                        port,
                        related[0],
                        relation_mode=relation_mode,
                        snapshot_attempts=current_snapshot.attempts,
                        snapshot_error=current_snapshot.error,
                        winerror=current_snapshot.winerror,
                        endpoint_status="verified",
                    )
                )
        except Exception:
            continue
    if not candidates:
        if snapshot is not None and snapshot.parents is None:
            return CdpOwnershipResult(
                "cdp_owner_unverified",
                clean_hwnd,
                clean_pid,
                relation_mode="process_tree_snapshot_failed",
                snapshot_attempts=snapshot.attempts,
                snapshot_error=snapshot.error,
                winerror=snapshot.winerror,
            )
        return CdpOwnershipResult("cdp_port_missing", clean_hwnd, clean_pid)
    if len(candidates) > 1:
        return CdpOwnershipResult("cdp_owner_conflict", clean_hwnd, clean_pid)
    return candidates[0]


def _same_direct_process_tree(window_pid: int, owner_pid: int, parents: Mapping[int, int]) -> bool:
    if int(window_pid) == int(owner_pid):
        return True
    return _is_ancestor(int(window_pid), int(owner_pid), parents) or _is_ancestor(
        int(owner_pid), int(window_pid), parents
    )


def _is_ancestor(ancestor_pid: int, child_pid: int, parents: Mapping[int, int]) -> bool:
    current = int(child_pid)
    visited: set[int] = set()
    while current > 0 and current not in visited:
        visited.add(current)
        current = int(parents.get(current, 0) or 0)
        if current == int(ancestor_pid):
            return True
    return False


def _safe_error_text(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return " ".join(text.split())[:240]


def _exception_winerror(exc: BaseException) -> int:
    value = getattr(exc, "winerror", None)
    if value in (None, 0):
        value = getattr(exc, "errno", None)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _resolve_process_parents_with_retry(
    resolver: ProcessParentResolver,
    *,
    max_attempts: int = _PROCESS_SNAPSHOT_MAX_ATTEMPTS,
    retry_delays: tuple[float, ...] = _PROCESS_SNAPSHOT_RETRY_DELAYS,
) -> _ProcessParentSnapshotResult:
    attempts_limit = max(1, int(max_attempts or 1))
    last_error = ""
    last_winerror = 0
    for attempt in range(1, attempts_limit + 1):
        try:
            with _PROCESS_SNAPSHOT_LOCK:
                parents = {int(pid): int(parent or 0) for pid, parent in resolver().items()}
            return _ProcessParentSnapshotResult(parents, attempt, last_error, last_winerror)
        except Exception as exc:
            last_error = _safe_error_text(f"{type(exc).__name__}: {exc}")
            last_winerror = _exception_winerror(exc)
        if attempt < attempts_limit and retry_delays:
            delay = float(retry_delays[min(attempt - 1, len(retry_delays) - 1)])
            if delay > 0:
                time.sleep(delay)
    return _ProcessParentSnapshotResult(None, attempts_limit, last_error, last_winerror)


def probe_cdp_endpoint(port: int, timeout: float = 0.8) -> bool:
    clean_port = int(port or 0)
    if clean_port <= 0:
        return False
    try:
        with urlopen(f"http://127.0.0.1:{clean_port}/json/list", timeout=max(0.05, float(timeout))) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return False
    return bool(
        isinstance(payload, list)
        and any(isinstance(item, dict) and item.get("webSocketDebuggerUrl") for item in payload)
    )


def get_window_pid(hwnd: int) -> int:
    if os.name != "nt" or int(hwnd or 0) <= 0:
        return 0
    process_id = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(int(hwnd)), ctypes.byref(process_id))
    return int(process_id.value or 0)


def list_tcp_listeners_by_port() -> dict[int, set[int]]:
    if os.name != "nt":
        return {}

    class MIB_TCPROW_OWNER_PID(ctypes.Structure):
        _fields_ = [
            ("dwState", wintypes.DWORD),
            ("dwLocalAddr", wintypes.DWORD),
            ("dwLocalPort", wintypes.DWORD),
            ("dwRemoteAddr", wintypes.DWORD),
            ("dwRemotePort", wintypes.DWORD),
            ("dwOwningPid", wintypes.DWORD),
        ]

    size = wintypes.DWORD(0)
    iphlpapi = ctypes.windll.iphlpapi
    family_ipv4 = 2
    table_owner_pid_listener = 3
    result = iphlpapi.GetExtendedTcpTable(
        None,
        ctypes.byref(size),
        False,
        family_ipv4,
        table_owner_pid_listener,
        0,
    )
    if result not in (0, 122) or size.value <= 0:
        raise OSError(int(result), "GetExtendedTcpTable size query failed")
    buffer = ctypes.create_string_buffer(size.value)
    result = iphlpapi.GetExtendedTcpTable(
        buffer,
        ctypes.byref(size),
        False,
        family_ipv4,
        table_owner_pid_listener,
        0,
    )
    if result != 0:
        raise OSError(int(result), "GetExtendedTcpTable failed")
    count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
    row_size = ctypes.sizeof(MIB_TCPROW_OWNER_PID)
    base_address = ctypes.addressof(buffer) + ctypes.sizeof(wintypes.DWORD)
    listeners: dict[int, set[int]] = {}
    for index in range(int(count)):
        row = MIB_TCPROW_OWNER_PID.from_address(base_address + index * row_size)
        port = int(socket.ntohs(int(row.dwLocalPort) & 0xFFFF))
        pid = int(row.dwOwningPid or 0)
        if port > 0 and pid > 0:
            listeners.setdefault(port, set()).add(pid)
    return listeners


def list_process_parents() -> dict[int, int]:
    snapshot = _resolve_process_parents_with_retry(_list_process_parents_once)
    if snapshot.parents is None:
        raise ProcessSnapshotError(
            f"process snapshot failed after {snapshot.attempts} attempts: {snapshot.error}",
            attempts=snapshot.attempts,
            winerror=snapshot.winerror,
        )
    return dict(snapshot.parents)


def _list_process_parents_once() -> dict[int, int]:
    if os.name != "nt":
        return {}

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = wintypes.HANDLE(-1).value
    if snapshot == invalid_handle:
        raise ctypes.WinError()
    parents: dict[int, int] = {}
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        success = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        if not success:
            error_code = int(kernel32.GetLastError() or 0)
            raise OSError(error_code, "Process32FirstW failed")
        while success:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            success = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return parents
