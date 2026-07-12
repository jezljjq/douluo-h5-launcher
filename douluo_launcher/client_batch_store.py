from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .client_cdp import is_tcp_port_available
from .config import default_client_direct_sessions_path


SCHEMA_VERSION = 2
DEFAULT_BASE_PORT = 9222
SESSION_DIR_NAME = "debug_client_direct"
SESSION_FILE_NAME = "client_direct_sessions.json"
BUSINESS_STATUS_VALUES = {
    "客户端登录成功",
    "已进入游戏",
    "客户端已就绪",
    "登录失败",
    "进入游戏失败",
    "login_success",
    "game_entered",
    "ready",
    "running",
    "login_failed",
    "enter_game_failed",
}
SCAN_MISSING_STATUS = "scan_missing"
SCAN_MISSING_DISPLAY_STATUS = "未找到"


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def default_sessions_path(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root) / SESSION_FILE_NAME
    return default_client_direct_sessions_path()


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
    account_key: str = ""
    refresh_account_name: str = ""
    bookmark_path: str = ""
    slot_index: int = 0
    identity_status: str = ""
    link_status: str = ""
    pid: int = 0
    hwnd: int = 0
    cdp_port: int = 0
    cdp_owner_pid: int = 0
    cdp_ownership_status: str = ""
    login_url: str = ""
    status: str = "pending"
    display_status: str = ""
    login_status: str = ""
    window_status: str = ""
    repair_status: str = ""
    source: str = ""
    title: str = ""
    process_path: str = ""
    window_left: int = 0
    window_top: int = 0
    window_width: int = 0
    window_height: int = 0
    page_url: str = ""
    page_title: str = ""
    speed_rate: float = 1.0
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
        self.cdp_owner_pid = int(self.cdp_owner_pid or 0)
        self.window_left = int(self.window_left or 0)
        self.window_top = int(self.window_top or 0)
        self.window_width = int(self.window_width or 0)
        self.window_height = int(self.window_height or 0)
        self.speed_rate = float(self.speed_rate or 1.0)
        self.slot_index = int(self.slot_index or 0)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "account_key": self.account_key,
            "refresh_account_name": self.refresh_account_name,
            "bookmark_path": self.bookmark_path,
            "slot_index": self.slot_index,
            "identity_status": self.identity_status,
            "link_status": self.link_status,
            "pid": self.pid,
            "hwnd": self.hwnd,
            "cdp_port": self.cdp_port,
            "cdp_owner_pid": self.cdp_owner_pid,
            "cdp_ownership_status": self.cdp_ownership_status,
            "login_url": self.login_url,
            "status": self.status,
            "display_status": self.display_status,
            "login_status": self.login_status,
            "window_status": self.window_status,
            "repair_status": self.repair_status,
            "source": self.source,
            "title": self.title,
            "process_path": self.process_path,
            "window_left": self.window_left,
            "window_top": self.window_top,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "speed_rate": self.speed_rate,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClientBatchBinding":
        return cls(
            account_id=str(data.get("account_id") or ""),
            account_name=str(data.get("account_name") or ""),
            account_key=str(data.get("account_key") or ""),
            refresh_account_name=str(data.get("refresh_account_name") or ""),
            bookmark_path=str(data.get("bookmark_path") or ""),
            slot_index=int(data.get("slot_index") or 0),
            identity_status=str(data.get("identity_status") or ""),
            link_status=str(data.get("link_status") or ""),
            pid=int(data.get("pid") or 0),
            hwnd=int(data.get("hwnd") or 0),
            cdp_port=int(data.get("cdp_port") or 0),
            cdp_owner_pid=int(data.get("cdp_owner_pid") or 0),
            cdp_ownership_status=str(data.get("cdp_ownership_status") or ""),
            login_url=str(data.get("login_url") or ""),
            status=str(data.get("status") or "pending"),
            display_status=str(data.get("display_status") or ""),
            login_status=str(data.get("login_status") or ""),
            window_status=str(data.get("window_status") or ""),
            repair_status=str(data.get("repair_status") or ""),
            source=str(data.get("source") or ""),
            title=str(data.get("title") or ""),
            process_path=str(data.get("process_path") or ""),
            window_left=int(data.get("window_left") or 0),
            window_top=int(data.get("window_top") or 0),
            window_width=int(data.get("window_width") or 0),
            window_height=int(data.get("window_height") or 0),
            page_url=str(data.get("page_url") or ""),
            page_title=str(data.get("page_title") or ""),
            speed_rate=float(data.get("speed_rate") or 1.0),
            error_message=str(data.get("error_message") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class LocalClientScan:
    pid: int = 0
    hwnd: int = 0
    title: str = ""
    window_left: int = 0
    window_top: int = 0
    window_width: int = 0
    window_height: int = 0
    process_path: str = ""
    cdp_port: int = 0
    cdp_owner_pid: int = 0
    cdp_ownership_status: str = ""
    cdp_available: bool = False
    cdp_port_inferred: bool = False
    page_url: str = ""
    page_title: str = ""
    is_x5game: bool = True


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
    hwnd_valid: Callable[[int], bool] | None = None
    scan_for_hwnd: Callable[[int], LocalClientScan | None] | None = None


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

    def _has_business_status(self, binding: ClientBatchBinding) -> bool:
        values = {
            str(binding.status or ""),
            str(binding.display_status or ""),
            str(binding.login_status or ""),
        }
        return any(value in BUSINESS_STATUS_VALUES for value in values)

    def _apply_window_status(
        self,
        binding: ClientBatchBinding,
        status: str,
        *,
        update_status: str | None = None,
        force_status: bool = False,
    ) -> None:
        binding.window_status = "restored" if status in {"restored", "repaired"} else status
        if force_status or not self._has_business_status(binding):
            binding.status = update_status or status
        binding.updated_at = now_text()

    def _mark_binding_scan_missing(self, binding: ClientBatchBinding) -> None:
        binding.repair_status = SCAN_MISSING_STATUS
        binding.error_message = "本次扫描未找到对应 X5Game 窗口"
        self._apply_window_status(
            binding,
            SCAN_MISSING_STATUS,
            update_status=SCAN_MISSING_DISPLAY_STATUS,
            force_status=True,
        )

    def _local_scan_status(self, scan: LocalClientScan) -> str:
        if not bool(scan.is_x5game):
            return "pid_not_x5game"
        if int(scan.hwnd or 0) <= 0:
            return "hwnd_invalid"
        ownership_status = str(getattr(scan, "cdp_ownership_status", "") or "")
        if ownership_status and ownership_status != "verified":
            return ownership_status
        if int(scan.cdp_port or 0) <= 0:
            return "cdp_port_missing"
        if not bool(scan.cdp_available):
            return "cdp_unavailable"
        return "restored"

    def _binding_matches_local_scan(self, binding: ClientBatchBinding, scan: LocalClientScan, batch: ClientBatch) -> bool:
        scan_pid = int(scan.pid or 0)
        if scan_pid > 0 and int(binding.pid or 0) == scan_pid:
            return True
        scan_hwnd = int(scan.hwnd or 0)
        if scan_hwnd > 0 and int(binding.hwnd or 0) == scan_hwnd:
            return True
        return False

    def _find_local_scan_match(
        self,
        scan: LocalClientScan,
        batch: ClientBatch,
        used_binding_ids: set[int],
    ) -> ClientBatchBinding | None:
        for binding in batch.bindings:
            if id(binding) in used_binding_ids:
                continue
            if self._binding_matches_local_scan(binding, scan, batch):
                return binding
        return None

    def _binding_strongly_matches_local_scan(self, binding: ClientBatchBinding, scan: LocalClientScan) -> bool:
        scan_pid = int(scan.pid or 0)
        if scan_pid > 0 and int(binding.pid or 0) == scan_pid:
            return True
        scan_hwnd = int(scan.hwnd or 0)
        if scan_hwnd > 0 and int(binding.hwnd or 0) == scan_hwnd:
            return True
        return False

    def _local_scan_value_sets(self, scans: list[LocalClientScan]) -> tuple[set[int], set[int], set[int]]:
        ports = {int(scan.cdp_port or 0) for scan in scans if int(scan.cdp_port or 0) > 0}
        pids = {int(scan.pid or 0) for scan in scans if int(scan.pid or 0) > 0}
        hwnds = {int(scan.hwnd or 0) for scan in scans if int(scan.hwnd or 0) > 0}
        return ports, pids, hwnds

    def _batch_value_sets(self, batch: ClientBatch) -> tuple[set[int], set[int], set[int]]:
        ports = {int(binding.cdp_port or 0) for binding in batch.bindings if int(binding.cdp_port or 0) > 0}
        pids = {int(binding.pid or 0) for binding in batch.bindings if int(binding.pid or 0) > 0}
        hwnds = {int(binding.hwnd or 0) for binding in batch.bindings if int(binding.hwnd or 0) > 0}
        return ports, pids, hwnds

    def _large_collection_gap(self, scan_count: int, batch_count: int) -> bool:
        smaller = min(scan_count, batch_count)
        if smaller <= 0:
            return False
        allowed_gap = max(2, (smaller + 3) // 4)
        return abs(batch_count - scan_count) > allowed_gap

    def _scan_is_large_subset_of_batch(self, scans: list[LocalClientScan], batch: ClientBatch) -> bool:
        scan_count = len(scans)
        batch_count = len(batch.bindings)
        if scan_count <= 0 or batch_count <= scan_count:
            return False
        if not self._large_collection_gap(scan_count, batch_count):
            return False
        for scan_values, batch_values in zip(self._local_scan_value_sets(scans), self._batch_value_sets(batch)):
            if not scan_values or not batch_values:
                continue
            overlap = scan_values & batch_values
            if scan_values <= batch_values:
                return True
            if len(overlap) / max(1, len(scan_values)) >= 0.8:
                return True
        return False

    def _complete_positive_set(self, values: set[int], expected_count: int) -> bool:
        return expected_count > 0 and len(values) == expected_count

    def _history_batch_matches_scan_collection(
        self,
        batch: ClientBatch,
        scans: list[LocalClientScan],
        result: dict[str, Any],
    ) -> bool:
        scan_count = len(scans)
        batch_count = len(batch.bindings)
        if scan_count <= 0 or batch_count <= 0:
            return False

        _scan_ports, scan_pids, scan_hwnds = self._local_scan_value_sets(scans)
        _batch_ports, batch_pids, batch_hwnds = self._batch_value_sets(batch)
        hwnd_complete = self._complete_positive_set(scan_hwnds, scan_count) and self._complete_positive_set(batch_hwnds, batch_count)
        pid_complete = self._complete_positive_set(scan_pids, scan_count) and self._complete_positive_set(batch_pids, batch_count)
        hwnd_conflict = hwnd_complete and scan_count == batch_count and scan_hwnds != batch_hwnds
        pid_conflict = pid_complete and scan_count == batch_count and scan_pids != batch_pids

        if self._large_collection_gap(scan_count, batch_count):
            result["notes"].append(
                f"当前扫描 {scan_count} 个，历史批次“{batch.batch_name}”{batch_count} 个，数量差距较大，不拆分当前扫描集合。"
            )
            return False

        if hwnd_complete and scan_hwnds == batch_hwnds:
            return True
        if pid_complete and scan_pids == batch_pids:
            return True

        if hwnd_conflict or pid_conflict:
            result["notes"].append(f"历史批次“{batch.batch_name}”的 pid/hwnd 集合不同，不合并。")
            return False

        pid_overlap = len(scan_pids & batch_pids) if scan_pids and batch_pids else 0
        hwnd_overlap = len(scan_hwnds & batch_hwnds) if scan_hwnds and batch_hwnds else 0
        identity_overlap = max(pid_overlap, hwnd_overlap)
        if identity_overlap > 0 and not (hwnd_conflict or pid_conflict):
            return True

        return False

    def _matching_history_batch_for_scan_collection(
        self,
        scans: list[LocalClientScan],
        result: dict[str, Any],
    ) -> ClientBatch | None:
        for batch in self.batches:
            if self._history_batch_matches_scan_collection(batch, scans, result):
                return batch
        return None

    def _copy_local_scan_to_binding(self, binding: ClientBatchBinding, scan: LocalClientScan, status: str) -> None:
        if int(scan.pid or 0) > 0:
            binding.pid = int(scan.pid)
        if int(scan.hwnd or 0) > 0:
            binding.hwnd = int(scan.hwnd)
        if int(scan.cdp_port or 0) > 0:
            binding.cdp_port = int(scan.cdp_port)
        binding.cdp_owner_pid = int(getattr(scan, "cdp_owner_pid", 0) or 0)
        binding.cdp_ownership_status = str(getattr(scan, "cdp_ownership_status", "") or status)
        binding.title = str(scan.title or binding.title or "")
        binding.process_path = str(scan.process_path or binding.process_path or "")
        binding.window_left = int(scan.window_left or binding.window_left or 0)
        binding.window_top = int(scan.window_top or binding.window_top or 0)
        binding.window_width = int(scan.window_width or binding.window_width or 0)
        binding.window_height = int(scan.window_height or binding.window_height or 0)
        binding.page_url = str(scan.page_url or binding.page_url or "")
        binding.page_title = str(scan.page_title or binding.page_title or "")
        binding.repair_status = "restored" if status == "restored" else status
        binding.window_status = "restored" if status == "restored" else status
        binding.updated_at = now_text()

    def _local_scan_binding_id(self, scan: LocalClientScan, batch: ClientBatch) -> str:
        base = f"local_scan:{int(scan.cdp_port or 0)}:{int(scan.pid or 0)}:{int(scan.hwnd or 0)}"
        existing = {str(binding.account_id) for binding in batch.bindings}
        if base not in existing:
            return base
        suffix = 2
        while f"{base}:{suffix}" in existing:
            suffix += 1
        return f"{base}:{suffix}"

    def _binding_from_local_scan(self, scan: LocalClientScan, batch: ClientBatch) -> ClientBatchBinding:
        status = self._local_scan_status(scan)
        binding = ClientBatchBinding(
            account_id=self._local_scan_binding_id(scan, batch),
            account_name=str(scan.title or f"本地客户端 {int(scan.hwnd or 0)}").strip(),
            slot_index=len(batch.bindings) + 1,
            identity_status="unresolved",
            link_status="unknown",
            pid=int(scan.pid or 0),
            hwnd=int(scan.hwnd or 0),
            cdp_port=int(scan.cdp_port or 0),
            cdp_owner_pid=int(getattr(scan, "cdp_owner_pid", 0) or 0),
            cdp_ownership_status=str(getattr(scan, "cdp_ownership_status", "") or status),
            login_url="",
            status="pending",
            source="local_scan",
            title=str(scan.title or ""),
            process_path=str(scan.process_path or ""),
            window_left=int(scan.window_left or 0),
            window_top=int(scan.window_top or 0),
            window_width=int(scan.window_width or 0),
            window_height=int(scan.window_height or 0),
            page_url=str(scan.page_url or ""),
            page_title=str(scan.page_title or ""),
        )
        binding.window_status = "restored" if status == "restored" else status
        binding.repair_status = "restored" if status == "restored" else status
        binding.updated_at = now_text()
        return binding

    def _create_local_scan_batch(self, scans: list[LocalClientScan], index: int) -> ClientBatch:
        ports = sorted(int(scan.cdp_port or 0) for scan in scans if int(scan.cdp_port or 0) > 0)
        if ports:
            name = f"当前桌面识别-{len(scans)}窗-端口{ports[0]}~{ports[-1]}"
            base_port = ports[0]
        else:
            name = f"当前桌面识别-{len(scans)}窗-批次{index}"
            base_port = DEFAULT_BASE_PORT
        existing_names = {batch.batch_name for batch in self.batches}
        clean_name = name
        suffix = 2
        while clean_name in existing_names:
            clean_name = f"{name}-{suffix}"
            suffix += 1
        return self.create_batch(clean_name, scope="本地识别", base_port=base_port)

    def _unassigned_local_batch(self) -> ClientBatch:
        for batch in self.batches:
            if batch.batch_name == "未归属本地客户端":
                return batch
        return self.create_batch("未归属本地客户端", scope="本地识别", base_port=DEFAULT_BASE_PORT)

    def _empty_current_batch_for_local_scan(self) -> ClientBatch | None:
        if not self.batches:
            return None
        try:
            batch = self.current_batch()
        except Exception:
            return None
        return batch if not batch.bindings else None

    def _add_scan_to_batch(self, scan: LocalClientScan, batch: ClientBatch, result: dict[str, Any]) -> ClientBatchBinding:
        binding = self._binding_from_local_scan(scan, batch)
        batch.bindings.append(binding)
        batch.updated_at = now_text()
        result["added"] += 1
        return binding

    def identify_local_clients(self, scans: list[LocalClientScan]) -> dict[str, Any]:
        active_batch_id = self.active_batch_id
        existing_count = sum(len(batch.bindings) for batch in self.batches)
        result = {
            "scanned": len(scans),
            "existing": existing_count,
            "added": 0,
            "cdp_unavailable": 0,
            "binding_invalid": 0,
            "restored_batches": 0,
            "created_batches": 0,
            "unassigned": 0,
            "notes": [],
        }
        for scan in scans:
            status = self._local_scan_status(scan)
            if status == "cdp_unavailable":
                result["cdp_unavailable"] += 1
            elif status in {"pid_not_x5game", "hwnd_invalid"}:
                result["binding_invalid"] += 1

        if not scans:
            if active_batch_id and any(batch.batch_id == active_batch_id for batch in self.batches):
                self.active_batch_id = active_batch_id
            return result

        matched_batch = self._matching_history_batch_for_scan_collection(scans, result)
        if matched_batch is None:
            if len(scans) >= 2:
                batch = self._empty_current_batch_for_local_scan()
                if batch is None:
                    batch = self._create_local_scan_batch(scans, 1)
                    result["created_batches"] += 1
                    result["notes"].append(f"新建当前桌面批次：{batch.batch_name}，绑定{len(scans)}。")
                for scan in scans:
                    self._add_scan_to_batch(scan, batch, result)
                self.active_batch_id = batch.batch_id
                return result
            batch = self._unassigned_local_batch()
            result["unassigned"] = len(scans)
            for scan in scans:
                self._add_scan_to_batch(scan, batch, result)
            self.active_batch_id = batch.batch_id
            return result

        used_binding_ids: set[int] = set()
        ready_count = 0
        for scan in scans:
            status = self._local_scan_status(scan)
            binding = self._find_local_scan_match(scan, matched_batch, used_binding_ids)
            if binding is None:
                binding = self._add_scan_to_batch(scan, matched_batch, result)
                used_binding_ids.add(id(binding))
                if status == "restored":
                    ready_count += 1
                continue
            used_binding_ids.add(id(binding))
            self._copy_local_scan_to_binding(binding, scan, status)
            if status == "restored":
                ready_count += 1
        for binding in matched_batch.bindings:
            if id(binding) not in used_binding_ids:
                self._mark_binding_scan_missing(binding)
        binding_count = len(matched_batch.bindings)
        abnormal_count = max(0, binding_count - ready_count)
        result["ready"] = ready_count
        result["abnormal"] = abnormal_count
        result["history_bindings"] = binding_count
        if len(scans) != binding_count:
            result["notes"].append(
                f"当前扫描 {len(scans)} 个，历史绑定 {binding_count} 个，就绪 {ready_count} 个，异常 {abnormal_count} 个。"
            )
        matched_batch.updated_at = now_text()
        result["restored_batches"] = 1
        self.active_batch_id = matched_batch.batch_id
        return result

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
            self._apply_window_status(binding, status)
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
                self._apply_window_status(binding, status)
                statuses[binding.account_id] = status
            batch.updated_at = now_text()
            all_statuses[batch.batch_id] = statuses
        return all_statuses

    def repair_current_batch_windows(
        self,
        *,
        probe: RepairProbe,
        local_scans: list[LocalClientScan] | None = None,
    ) -> dict[str, str]:
        results: dict[str, str] = {}
        batch = self.current_batch()
        used_scan_ids: set[int] = set()
        for binding in batch.bindings:
            matched_scan = None
            matched_from_historical_hwnd = False
            if local_scans is not None:
                for scan in local_scans:
                    if id(scan) in used_scan_ids:
                        continue
                    if self._binding_strongly_matches_local_scan(binding, scan):
                        matched_scan = scan
                        used_scan_ids.add(id(scan))
                        break
            if matched_scan is None and probe.scan_for_hwnd is not None and int(binding.hwnd or 0) > 0:
                try:
                    recovered_scan = probe.scan_for_hwnd(int(binding.hwnd))
                except Exception:
                    recovered_scan = None
                historical_scan_ready = (
                    recovered_scan is not None
                    and self._local_scan_status(recovered_scan) == "restored"
                )
                same_historical_port = (
                    recovered_scan is not None
                    and int(binding.cdp_port or 0) > 0
                    and int(recovered_scan.cdp_port or 0) == int(binding.cdp_port or 0)
                )
                if (
                    recovered_scan is not None
                    and historical_scan_ready
                    and same_historical_port
                    and id(recovered_scan) not in used_scan_ids
                    and self._binding_strongly_matches_local_scan(binding, recovered_scan)
                ):
                    matched_scan = recovered_scan
                    matched_from_historical_hwnd = True
                    used_scan_ids.add(id(recovered_scan))
            if local_scans is not None and matched_scan is None:
                if not probe.pid_exists(binding.pid):
                    status = "pid_missing"
                elif not probe.process_is_x5game(binding.pid):
                    status = "pid_not_x5game"
                elif not probe.cdp_available(binding.cdp_port):
                    status = "cdp_unavailable"
                elif probe.hwnd_valid is not None and not probe.hwnd_valid(binding.hwnd):
                    status = "hwnd_invalid"
                else:
                    status = SCAN_MISSING_STATUS
                if status == SCAN_MISSING_STATUS:
                    self._mark_binding_scan_missing(binding)
                else:
                    binding.repair_status = status
                    self._apply_window_status(binding, status, update_status=status, force_status=True)
                results[binding.account_id] = status
                continue
            if matched_scan is not None:
                self._copy_local_scan_to_binding(binding, matched_scan, self._local_scan_status(matched_scan))

            if not probe.pid_exists(binding.pid):
                status = "pid_missing"
            elif not probe.process_is_x5game(binding.pid):
                status = "pid_not_x5game"
            elif not probe.cdp_available(binding.cdp_port):
                status = "cdp_unavailable"
            elif probe.hwnd_valid is not None and not probe.hwnd_valid(binding.hwnd):
                status = "hwnd_invalid"
            else:
                hwnd = int(binding.hwnd or 0) if matched_from_historical_hwnd else int(probe.hwnd_for_pid(binding.pid) or 0)
                if hwnd <= 0:
                    status = "hwnd_invalid"
                else:
                    binding.hwnd = hwnd
                    status = "repaired"
            binding.repair_status = status
            force_status = status not in {"repaired", "restored"}
            self._apply_window_status(binding, status, update_status=status, force_status=force_status)
            results[binding.account_id] = status
        batch.updated_at = now_text()
        return results
