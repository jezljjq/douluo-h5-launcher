from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .client_cdp import is_tcp_port_available
from .config import app_root


SCHEMA_VERSION = 1
DEFAULT_BASE_PORT = 9222
SESSION_DIR_NAME = "debug_client_direct"
SESSION_FILE_NAME = "client_direct_sessions.json"


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def default_sessions_path(root: str | Path | None = None) -> Path:
    base = Path(root) if root is not None else app_root()
    return base / SESSION_DIR_NAME / SESSION_FILE_NAME


def make_batch_id() -> str:
    return "batch_" + time.strftime("%Y%m%d_%H%M%S")


def check_port_range_available(
    base_port: int,
    count: int,
    *,
    port_available: Callable[[int], bool] = is_tcp_port_available,
) -> list[int]:
    clean_base = int(base_port)
    clean_count = max(0, int(count))
    occupied: list[int] = []
    for offset in range(clean_count):
        port = clean_base + offset
        if not port_available(port):
            occupied.append(port)
    return occupied


def find_next_available_port_range(
    base_port: int,
    count: int,
    *,
    port_available: Callable[[int], bool] = is_tcp_port_available,
    blocked_ports: set[int] | None = None,
    max_port: int = 65535,
) -> int | None:
    clean_base = int(base_port)
    clean_count = max(0, int(count))
    blocked = {int(port) for port in (blocked_ports or set())}
    if clean_count <= 0:
        return clean_base
    last_start = int(max_port) - clean_count + 1
    for candidate in range(clean_base + 1, last_start + 1):
        ports = range(candidate, candidate + clean_count)
        if any(port in blocked for port in ports):
            continue
        if all(port_available(port) for port in ports):
            return candidate
    return None


@dataclass
class ClientBatchBinding:
    account_id: str
    account_name: str
    pid: int = 0
    hwnd: int = 0
    cdp_port: int = 0
    login_url: str = ""
    status: str = "pending"
    error_message: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        timestamp = now_text()
        if not self.created_at:
            self.created_at = timestamp
        if not self.updated_at:
            self.updated_at = self.created_at
        self.pid = int(self.pid or 0)
        self.hwnd = int(self.hwnd or 0)
        self.cdp_port = int(self.cdp_port or 0)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "pid": self.pid,
            "hwnd": self.hwnd,
            "cdp_port": self.cdp_port,
            "login_url": self.login_url,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClientBatchBinding":
        return cls(
            account_id=str(data.get("account_id") or ""),
            account_name=str(data.get("account_name") or ""),
            pid=int(data.get("pid") or 0),
            hwnd=int(data.get("hwnd") or 0),
            cdp_port=int(data.get("cdp_port") or 0),
            login_url=str(data.get("login_url") or ""),
            status=str(data.get("status") or "pending"),
            error_message=str(data.get("error_message") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass
class ClientBatch:
    batch_id: str
    batch_name: str
    scope: str
    base_port: int = DEFAULT_BASE_PORT
    auto_enter_game: bool = True
    virtual_desktop_note: str = ""
    bindings: list[ClientBatchBinding] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        timestamp = now_text()
        if not self.created_at:
            self.created_at = timestamp
        if not self.updated_at:
            self.updated_at = self.created_at
        self.base_port = int(self.base_port or DEFAULT_BASE_PORT)

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "batch_name": self.batch_name,
            "scope": self.scope,
            "base_port": self.base_port,
            "auto_enter_game": bool(self.auto_enter_game),
            "virtual_desktop_note": self.virtual_desktop_note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "bindings": [binding.to_dict() for binding in self.bindings],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClientBatch":
        return cls(
            batch_id=str(data.get("batch_id") or make_batch_id()),
            batch_name=str(data.get("batch_name") or "默认批次"),
            scope=str(data.get("scope") or "当前层"),
            base_port=int(data.get("base_port") or DEFAULT_BASE_PORT),
            auto_enter_game=bool(data.get("auto_enter_game", True)),
            virtual_desktop_note=str(data.get("virtual_desktop_note") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            bindings=[ClientBatchBinding.from_dict(item) for item in data.get("bindings") or []],
        )


@dataclass(frozen=True)
class RepairProbe:
    pid_exists: Callable[[int], bool]
    process_is_x5game: Callable[[int], bool]
    cdp_available: Callable[[int], bool]
    hwnd_for_pid: Callable[[int], int | None]


class ClientBatchStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_sessions_path()
        self.schema_version = SCHEMA_VERSION
        self.active_batch_id = ""
        self.default_base_port = DEFAULT_BASE_PORT
        self.last_base_port = DEFAULT_BASE_PORT
        self.restore_on_startup = True
        self.batches: list[ClientBatch] = []

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.schema_version = int(data.get("schema_version") or SCHEMA_VERSION)
        self.active_batch_id = str(data.get("active_batch_id") or "")
        settings = data.get("settings") or {}
        self.default_base_port = int(settings.get("default_base_port") or DEFAULT_BASE_PORT)
        self.last_base_port = int(settings.get("last_base_port") or self.default_base_port)
        self.restore_on_startup = bool(settings.get("restore_on_startup", True))
        self.batches = [ClientBatch.from_dict(item) for item in data.get("batches") or []]
        if self.batches and not self.active_batch_id:
            self.active_batch_id = self.batches[-1].batch_id

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": SCHEMA_VERSION,
            "active_batch_id": self.active_batch_id,
            "settings": {
                "default_base_port": int(self.default_base_port),
                "last_base_port": int(self.last_base_port),
                "restore_on_startup": bool(self.restore_on_startup),
            },
            "batches": [batch.to_dict() for batch in self.batches],
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def create_batch(
        self,
        batch_name: str,
        *,
        scope: str,
        base_port: int = DEFAULT_BASE_PORT,
        auto_enter_game: bool = True,
        virtual_desktop_note: str = "",
    ) -> ClientBatch:
        batch = ClientBatch(
            batch_id=self._unique_batch_id(),
            batch_name=batch_name or "默认批次",
            scope=scope,
            base_port=int(base_port),
            auto_enter_game=bool(auto_enter_game),
            virtual_desktop_note=virtual_desktop_note,
        )
        self.batches.append(batch)
        self.active_batch_id = batch.batch_id
        self.last_base_port = int(base_port)
        return batch

    def _unique_batch_id(self) -> str:
        base = make_batch_id()
        existing = {batch.batch_id for batch in self.batches}
        if base not in existing:
            return base
        suffix = 2
        while f"{base}_{suffix}" in existing:
            suffix += 1
        return f"{base}_{suffix}"

    def switch_batch(self, batch_id: str) -> ClientBatch:
        for batch in self.batches:
            if batch.batch_id == batch_id:
                self.active_batch_id = batch.batch_id
                return batch
        raise KeyError(f"未知客户端批次: {batch_id}")

    def current_batch(self) -> ClientBatch:
        if not self.batches:
            return self.create_batch("默认批次", scope="当前层", base_port=self.last_base_port)
        for batch in self.batches:
            if batch.batch_id == self.active_batch_id:
                return batch
        self.active_batch_id = self.batches[-1].batch_id
        return self.batches[-1]

    def delete_batch(self, batch_id: str) -> bool:
        target_id = str(batch_id or "")
        before = len(self.batches)
        self.batches = [batch for batch in self.batches if batch.batch_id != target_id]
        if len(self.batches) == before:
            return False
        if not self.batches:
            self.active_batch_id = ""
        elif self.active_batch_id == target_id or not any(batch.batch_id == self.active_batch_id for batch in self.batches):
            self.active_batch_id = self.batches[0].batch_id
        return True

    def batch_live_count(
        self,
        batch: ClientBatch,
        *,
        pid_exists: Callable[[int], bool],
        process_is_x5game: Callable[[int], bool],
    ) -> int:
        count = 0
        for binding in batch.bindings:
            pid = int(binding.pid or 0)
            if pid > 0 and pid_exists(pid) and process_is_x5game(pid):
                count += 1
        return count

    def cleanup_dead_batches(
        self,
        *,
        pid_exists: Callable[[int], bool],
        process_is_x5game: Callable[[int], bool],
    ) -> list[ClientBatch]:
        removed: list[ClientBatch] = []
        kept: list[ClientBatch] = []
        for batch in self.batches:
            if self.batch_live_count(batch, pid_exists=pid_exists, process_is_x5game=process_is_x5game) == 0:
                removed.append(batch)
            else:
                kept.append(batch)
        self.batches = kept
        if not self.batches:
            self.active_batch_id = ""
        elif not any(batch.batch_id == self.active_batch_id for batch in self.batches):
            self.active_batch_id = self.batches[0].batch_id
        return removed

    def append_binding(self, binding: ClientBatchBinding, *, allow_existing_account: bool = False) -> None:
        batch = self.current_batch()
        if not allow_existing_account and any(item.account_id == binding.account_id for item in batch.bindings):
            raise ValueError(f"账号已存在于当前批次: {binding.account_id}")
        if any(int(item.cdp_port or 0) == int(binding.cdp_port or 0) for item in batch.bindings):
            raise ValueError(f"CDP 端口已存在于当前批次: {binding.cdp_port}")
        binding.updated_at = now_text()
        batch.bindings.append(binding)
        batch.updated_at = now_text()

    def replace_current_bindings(self, bindings: list[ClientBatchBinding]) -> None:
        batch = self.current_batch()
        batch.bindings = list(bindings)
        batch.updated_at = now_text()

    def clear_current_batch(self) -> None:
        batch = self.current_batch()
        batch.bindings = []
        batch.updated_at = now_text()

    def binding_account_ids(self) -> set[str]:
        return {binding.account_id for binding in self.current_batch().bindings}

    def binding_ports(self) -> set[int]:
        return {int(binding.cdp_port or 0) for binding in self.current_batch().bindings if int(binding.cdp_port or 0) > 0}

    def live_binding_ports(
        self,
        *,
        pid_exists: Callable[[int], bool],
        process_is_x5game: Callable[[int], bool],
    ) -> set[int]:
        ports: set[int] = set()
        for batch in self.batches:
            for binding in batch.bindings:
                port = int(binding.cdp_port or 0)
                pid = int(binding.pid or 0)
                if port <= 0 or pid <= 0:
                    continue
                if pid_exists(pid) and process_is_x5game(pid):
                    ports.add(port)
        return ports

    def _refreshed_binding_status(
        self,
        binding: ClientBatchBinding,
        *,
        pid_exists: Callable[[int], bool],
        process_is_x5game: Callable[[int], bool] | None = None,
        cdp_available: Callable[[int], bool],
        hwnd_valid: Callable[[int], bool],
    ) -> str:
        if not pid_exists(binding.pid):
            return "pid_missing"
        if process_is_x5game is not None and not process_is_x5game(binding.pid):
            return "pid_not_x5game"
        if not cdp_available(binding.cdp_port):
            return "cdp_unavailable"
        if not hwnd_valid(binding.hwnd):
            return "hwnd_invalid"
        return "restored"

    def refresh_current_batch_status(
        self,
        *,
        pid_exists: Callable[[int], bool],
        cdp_available: Callable[[int], bool],
        hwnd_valid: Callable[[int], bool],
    ) -> dict[str, str]:
        statuses: dict[str, str] = {}
        batch = self.current_batch()
        for binding in batch.bindings:
            status = self._refreshed_binding_status(
                binding,
                pid_exists=pid_exists,
                cdp_available=cdp_available,
                hwnd_valid=hwnd_valid,
            )
            binding.status = status
            binding.updated_at = now_text()
            statuses[binding.account_id] = status
        batch.updated_at = now_text()
        return statuses

    def refresh_all_batch_statuses(
        self,
        *,
        pid_exists: Callable[[int], bool],
        process_is_x5game: Callable[[int], bool],
        cdp_available: Callable[[int], bool],
        hwnd_valid: Callable[[int], bool],
    ) -> dict[str, dict[str, str]]:
        all_statuses: dict[str, dict[str, str]] = {}
        for batch in self.batches:
            statuses: dict[str, str] = {}
            for binding in batch.bindings:
                status = self._refreshed_binding_status(
                    binding,
                    pid_exists=pid_exists,
                    process_is_x5game=process_is_x5game,
                    cdp_available=cdp_available,
                    hwnd_valid=hwnd_valid,
                )
                binding.status = status
                binding.updated_at = now_text()
                statuses[binding.account_id] = status
            batch.updated_at = now_text()
            all_statuses[batch.batch_id] = statuses
        return all_statuses

    def repair_current_batch_windows(self, *, probe: RepairProbe) -> dict[str, str]:
        results: dict[str, str] = {}
        batch = self.current_batch()
        for binding in batch.bindings:
            if not probe.pid_exists(binding.pid):
                status = "pid_missing"
            elif not probe.process_is_x5game(binding.pid):
                status = "pid_not_x5game"
            elif not probe.cdp_available(binding.cdp_port):
                status = "cdp_unavailable"
            else:
                hwnd = int(probe.hwnd_for_pid(binding.pid) or 0)
                if hwnd <= 0:
                    status = "hwnd_invalid"
                else:
                    binding.hwnd = hwnd
                    status = "repaired"
            binding.status = status
            binding.updated_at = now_text()
            results[binding.account_id] = status
        batch.updated_at = now_text()
        return results
