from __future__ import annotations

import queue
import json
import os
import re
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import urlparse

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None

from .automation import AccountRunner
from .client_batch_store import (
    BUSINESS_STATUS_VALUES,
    ClientBatchBinding,
    ClientBatchStore,
    LocalClientScan,
    RepairProbe,
    check_port_range_available,
    find_next_available_port_range,
)
from .client_cdp import (
    RawCdpClient,
    cdp_port_for_index,
    is_tcp_port_available,
    mask_sensitive_text,
    select_page_target,
    wait_for_cdp_targets,
)
from .client_cdp_ownership import (
    discover_window_cdp_endpoint,
    list_process_parents,
    list_tcp_listeners_by_port,
    validate_window_cdp_endpoint,
)
from .client_direct_login import (
    ClientDirectLoginConfig,
    ClientBinding,
    ClientDirectRunRecord,
    PreparedClientDirectLoginConfig,
    execute_client_direct_login,
    execute_prepared_client_direct_login,
    is_complete_direct_login_url,
    prepare_client_direct_client,
    wait_for_client_hwnd_by_pid,
)
from .client_speed_panel import ClientSpeedPanelConfig
from .client_speed_hotkey import (
    WindowsSpeedHotkey,
    compose_speed_hotkey,
    normalize_speed_hotkey_bindings,
)
from .client_login_accounts import (
    LoginAccountRosterStore,
    build_launcher_accounts,
    logical_group_from_bookmark_path,
    stable_refresh_account_key,
)
from .client_speed_control import (
    SpeedApplyResult,
    SpeedControlSummary,
    apply_speed_rate_to_binding,
    run_speed_control_batch,
    toggle_speed_tree_for_binding,
)
from .config import (
    AccountConfig,
    BookmarkCandidate,
    BookmarkRootCandidate,
    LEVELS,
    SELECTABLE_LEVELS,
    SINGLE_LEVEL_NAME,
    STATUSES,
    app_root,
    default_settings_path,
    describe_bookmark_file,
    find_bookmark_root_candidate_by_path,
    find_bookmark_file_candidates,
    initialize_user_data_dir,
    logs_dir,
    project_root,
    list_bookmark_top_level_dirs,
    load_accounts_from_bookmark_root,
    load_accounts_from_bookmarks,
    load_settings,
    scan_bookmark_root_candidates,
    select_bookmark_candidate_for_startup,
)
from .direct_link_refresh import (
    LOGIN_ENDPOINT,
    AccountsStore,
    BookmarkBatchItem,
    BookmarkUrlUpdater,
    BookmarkWriteContext,
    CaptureFailed,
    ChannelConfig,
    DirectLinkRefreshService,
    DirectLinkStore,
    DirectLoginFields,
    LoginFailed,
    RefreshAccount,
    default_refresh_data_dir,
    delete_refresh_account_resources,
    ensure_refresh_data_dir,
    import_accounts_from_file,
    import_accounts_from_text,
    load_channels,
    merge_accounts_by_name,
    redact_sensitive_text,
    resolve_client_direct_url_for_account,
    resolve_client_direct_url_for_identity,
)
from .direct_link_login import (
    DirectLinkLoginOptions,
    create_login_capturer,
    load_http_har_for_mode,
)
from .dm_client import diagnose_dm_environment_with_32bit_python, select_login_window_by_game_no
from .path_utils import first_dropped_file_path, resolve_game_executable_path
from .version import APP_VERSION
from .window_manager import (
    GAME_TITLE_KEYWORD,
    SWP_NOACTIVATE,
    SWP_NOZORDER,
    WINDOW_DETECTION_LOG_PATH,
    GameWindow,
    RowTileConfig,
    TileConfig,
    WindowRect,
    calculate_row_tile_plan,
    calculate_tile_position,
    check_window_slots_compatibility,
    close_game_windows,
    extract_window_number,
    get_window_rect,
    get_window_process_id,
    get_process_path_by_pid,
    has_valid_window_slots,
    launch_game_process,
    layout_params_from_tile_config,
    list_game_windows,
    rename_game_windows,
    refresh_window_slots_from_current_windows,
    repair_window_slot,
    resolve_window_slot_for_repair,
    restore_windows_by_slots,
    save_current_windows_as_slots,
    tile_game_windows,
    tile_game_windows_by_row_count,
    user32,
    window_slots_profile_path,
)
from .window_manager_settings import (
    FixedModeSettings,
    RowCountModeSettings,
    TILE_MODE_FIXED,
    TILE_MODE_ROW_COUNT,
    WindowManagerSettings,
    load_window_manager_settings,
    save_window_manager_settings,
    window_manager_settings_path,
)

WM_WAIT_TIMEOUT_SECONDS = 60
WM_STABLE_CHECKS = 3
WM_POLL_INTERVAL_SECONDS = 0.5
WM_FINAL_DELAY_SECONDS = 1
WM_TILE_MODE_FIXED = "固定参数排列"
WM_TILE_MODE_ROW_COUNT = "根据行数排列"
RUN_MODE_CLIENT_DIRECT_LABEL = "客户端直登模式"
RUN_MODE_CLIENT_DIRECT_HINT = "客户端直登模式，优先读取本地直登链接库，支持单账号/当前层准备、排列、登录"
CLIENT_DIRECT_CDP_PORT = 9222
CLIENT_DIRECT_CONCURRENCY_MIN = 1
CLIENT_DIRECT_CONCURRENCY_MAX = 8
CLIENT_DIRECT_LAUNCH_INTERVAL_SECONDS = 0.15
CLIENT_DIRECT_LOGIN_SCOPE_PENDING = "待登录账号"
CLIENT_DIRECT_LOGIN_SCOPE_SELECTED = "选中账号"
CLIENT_DIRECT_LOGIN_SCOPE_FAILED = "失败账号"
CLIENT_DIRECT_LOGIN_SCOPE_ALL = "全部账号"
CLIENT_DIRECT_LOGIN_SCOPE_CHOICES = (
    CLIENT_DIRECT_LOGIN_SCOPE_PENDING,
    CLIENT_DIRECT_LOGIN_SCOPE_SELECTED,
    CLIENT_DIRECT_LOGIN_SCOPE_FAILED,
    CLIENT_DIRECT_LOGIN_SCOPE_ALL,
)
CLIENT_SPEED_SCOPE_CURRENT_BATCH = "当前批次"
CLIENT_SPEED_SCOPE_SELECTED = "选中窗口"
CLIENT_SPEED_SCOPE_ALL_LIVE = "全部存活批次"
CLIENT_SPEED_SCOPE_CDP_AVAILABLE = "CDP可用窗口"
CLIENT_SPEED_SCOPE_CHOICES = (
    CLIENT_SPEED_SCOPE_CURRENT_BATCH,
    CLIENT_SPEED_SCOPE_SELECTED,
    CLIENT_SPEED_SCOPE_ALL_LIVE,
    CLIENT_SPEED_SCOPE_CDP_AVAILABLE,
)
CLIENT_DIRECT_LOGIN_PENDING_STATUSES = {
    "客户端已启动/待登录",
    "prepared",
    "ready_to_login",
    "login_pending",
    "pending",
    "待登录",
}
CLIENT_DIRECT_LOGIN_FAILED_STATUSES = {
    "login_failed",
    "cdp_unavailable",
    "CDP不可用",
    "canvas_timeout",
    "serverMobile_failed",
    "enter_game_failed",
    "客户端直登失败",
    "启动失败",
    "URL无效",
    "端口占用",
    "客户端已关闭",
}
GUI_DEFAULT_WIDTH = 1160
GUI_DEFAULT_HEIGHT = 940
GUI_MIN_WIDTH = 1080
GUI_MIN_HEIGHT = 820
LOG_TEXT_VISIBLE_LINES = 8
LOG_PANEL_COLLAPSED_HEIGHT = 42
LOG_PANEL_EXPANDED_HEIGHT = 150
LOG_PANEL_MIN_HEIGHT = LOG_PANEL_EXPANDED_HEIGHT


def _run_mode_key_from_label(label: str) -> str:
    return "client_direct"


def _direct_login_entry_label(url: str) -> str:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return "<invalid-url>"
    host = parsed.hostname or ""
    path = parsed.path or "/"
    return f"{host}{path}"


def _account_url_display_value(url: str) -> str:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return "<invalid-url> 参数不完整"
    host = parsed.hostname or ""
    path = parsed.path or "/"
    entry = f"{host} {path}".strip()
    completeness = "参数完整" if is_complete_direct_login_url(url) else "参数不完整"
    return f"{entry} {completeness}".strip()


def _run_mode_key_for_owner(owner) -> str:
    var = getattr(owner, "run_mode_var", None)
    if var is None:
        return "foreground"
    try:
        return _run_mode_key_from_label(var.get())
    except Exception:
        return "foreground"


def _safe_bool_var(owner, name: str, default: bool) -> bool:
    var = getattr(owner, name, None)
    if var is None:
        return bool(default)
    try:
        return bool(var.get())
    except Exception:
        return bool(default)


def _safe_string_var(owner, name: str, default: str) -> str:
    var = getattr(owner, name, None)
    if var is None:
        return str(default)
    try:
        value = str(var.get()).strip()
    except Exception:
        return str(default)
    return value or str(default)


def _run_bounded_client_direct_tasks(items, concurrency: int, worker):
    queued = list(items)
    if not queued:
        return
    try:
        requested_concurrency = int(concurrency or CLIENT_DIRECT_CONCURRENCY_MIN)
    except Exception:
        requested_concurrency = CLIENT_DIRECT_CONCURRENCY_MIN
    clean_concurrency = max(
        CLIENT_DIRECT_CONCURRENCY_MIN,
        min(CLIENT_DIRECT_CONCURRENCY_MAX, requested_concurrency),
    )
    max_workers = min(clean_concurrency, len(queued))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker, item) for item in queued]
        for future in as_completed(futures):
            yield future.result()


class _ClientLaunchThrottle:
    def __init__(
        self,
        interval: float = CLIENT_DIRECT_LAUNCH_INTERVAL_SECONDS,
        *,
        clock=None,
        sleep=None,
    ) -> None:
        self.interval = max(0.0, float(interval))
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._next_launch = 0.0

    def wait(self, stop_event) -> bool:
        with self._lock:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return False
                remaining = self._next_launch - self.clock()
                if remaining <= 0:
                    break
                self.sleep(min(0.05, remaining))
            self._next_launch = self.clock() + self.interval
            return True


def _safe_wm_expected_window_size(owner) -> tuple[int, int] | None:
    getter = getattr(owner, "_wm_expected_window_size_filter", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        return None


def _safe_wm_title_template(owner) -> str | None:
    var = getattr(owner, "wm_title_template_var", None)
    if var is None:
        return None
    try:
        value = str(var.get()).strip()
    except Exception:
        return None
    return value or None


ACCOUNT_TABLE_COLUMNS = (
    "level",
    "bookmark",
    "window_title",
    "include_in_all",
    "status",
)
ACCOUNT_TABLE_COLUMN_INDEX = {column: index for index, column in enumerate(ACCOUNT_TABLE_COLUMNS)}
ACCOUNT_TABLE_HEADINGS = {
    "level": "层级",
    "bookmark": "收藏编号",
    "window_title": "窗口标题",
    "include_in_all": "参与全部串行",
    "status": "状态",
}
ACCOUNT_TABLE_COLUMNS_CONFIG = {
    "level": {"width": 70, "anchor": tk.CENTER},
    "bookmark": {"width": 70, "anchor": tk.CENTER},
    "window_title": {"width": 180, "anchor": tk.CENTER},
    "include_in_all": {"width": 95, "anchor": tk.CENTER},
    "status": {"width": 130, "anchor": tk.CENTER},
}


def _account_table_values(
    account: AccountConfig,
    window_title: str = "",
    passport: str = "",
    status: str = "未开始",
    timing: str = "",
) -> tuple[object, ...]:
    return (
        account.level,
        account.bookmark_title or account.bookmark_no,
        window_title or "未绑定",
        "是" if account.include_in_all else "否",
        status,
    )


def _bound_window_title(owner, account: AccountConfig) -> str:
    record = (getattr(owner, "client_direct_bindings", {}) or {}).get(account.key)
    if record is None or int(getattr(record, "hwnd", 0) or 0) <= 0:
        return "未绑定"
    hwnd = int(record.hwnd)
    try:
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        buffer = ctypes.create_unicode_buffer(max(2, length + 1))
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        actual = str(buffer.value or "").strip()
    except Exception:
        actual = ""
    return actual or str(getattr(record, "title", "") or "").strip() or "未绑定"


def _format_bookmark_file_candidate_label(candidate: BookmarkCandidate, root_count: int | None = None) -> str:
    if root_count is None:
        return candidate.display_name
    return f"{candidate.display_name} - 发现 {root_count} 个账号目录"


def _format_game_program_status(path: str) -> str:
    clean_path = str(path or "").strip()
    if clean_path:
        return f"已识别游戏程序：{clean_path}"
    return "未选择游戏程序"


def _game_program_display_values(path: str) -> tuple[str, str]:
    clean_path = str(path or "").strip()
    return clean_path, _format_game_program_status(clean_path)


def _should_enable_native_game_path_drag_drop() -> bool:
    """Raw WM_DROPFILES is disabled because it can crash Tk; use tkinterdnd2 instead."""
    return False


def _is_tkinterdnd2_available() -> bool:
    return DND_FILES is not None and TkinterDnD is not None


def _game_program_hint_text() -> str:
    if _is_tkinterdnd2_available():
        return "可拖入桌面游戏图标、快捷方式或 X5Game.exe，也可点击按钮选择。"
    return "点击“选择游戏图标/程序”，可选择桌面快捷方式或 X5Game.exe。"


def _account_group_order_for_accounts(accounts: list[AccountConfig] | tuple[AccountConfig, ...]) -> tuple[str, ...]:
    groups: list[str] = []
    for account in accounts:
        if account.level not in groups:
            groups.append(account.level)
    return tuple(groups)


def _allowed_level_values_for_accounts(accounts: list[AccountConfig] | tuple[AccountConfig, ...]) -> tuple[str, ...]:
    groups = _account_group_order_for_accounts(accounts)
    if not groups:
        return ("未读取",)
    return ("全部", *groups)


def _default_level_for_allowed_values(current_level: str, allowed_levels: tuple[str, ...]) -> str:
    if current_level in allowed_levels:
        return current_level
    if len(allowed_levels) == 2 and allowed_levels[0] == "全部":
        return allowed_levels[1]
    return allowed_levels[0] if allowed_levels else ""


def _normalize_path_for_compare(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path or "").strip()))


def _root_candidate_belongs_to_bookmark_file(candidate: BookmarkRootCandidate, bookmark_file: str | Path) -> bool:
    return _normalize_path_for_compare(candidate.bookmark_file) == _normalize_path_for_compare(bookmark_file)


def _replace_account_table_value(values: object, column: str, value: str) -> list[object]:
    if column not in ACCOUNT_TABLE_COLUMN_INDEX:
        return list(values if isinstance(values, (list, tuple)) else ())
    updated = list(values if isinstance(values, (list, tuple)) else ())
    if len(updated) < len(ACCOUNT_TABLE_COLUMNS):
        updated.extend([""] * (len(ACCOUNT_TABLE_COLUMNS) - len(updated)))
    updated[ACCOUNT_TABLE_COLUMN_INDEX[column]] = value
    return updated


def _merge_account_group_settings(
    existing: object,
    include_by_group: dict[str, bool],
) -> dict[str, dict[str, bool]]:
    merged: dict[str, dict[str, bool]] = {}
    if isinstance(existing, dict):
        for raw_group_name, raw_group_setting in existing.items():
            group_name = str(raw_group_name).strip()
            if not group_name:
                continue
            include_in_all = False
            if isinstance(raw_group_setting, dict):
                include_in_all = bool(raw_group_setting.get("include_in_all", False))
            elif isinstance(raw_group_setting, bool):
                include_in_all = raw_group_setting
            merged[group_name] = {"include_in_all": include_in_all}

    for group_name, include_in_all in include_by_group.items():
        clean_group_name = str(group_name).strip()
        if clean_group_name:
            merged[clean_group_name] = {"include_in_all": bool(include_in_all)}
    return merged


def _split_all_serial_accounts(
    accounts: list[AccountConfig],
) -> tuple[list[AccountConfig], list[AccountConfig]]:
    enabled = [account for account in accounts if account.include_in_all]
    skipped = [account for account in accounts if not account.include_in_all]
    return enabled, skipped


@dataclass(frozen=True)
class SerialRunPlan:
    accounts: tuple[AccountConfig, ...]
    group_counts: tuple[tuple[str, int], ...]
    required_windows: tuple[int, ...]
    visible_windows: tuple[int, ...]
    missing_windows: tuple[int, ...]
    max_window_no: int


@dataclass(frozen=True)
class ClientDirectAccountRef:
    key: str
    display_name: str
    url: str
    game_window_no: int = 0


@dataclass(frozen=True)
class ClientBatchAccountResolution:
    accounts: list[AccountConfig]
    status: str
    message: str
    mapped: int = 0


def _resolve_client_direct_batch_accounts(
    owner,
    batch,
    candidate_accounts: list[AccountConfig],
) -> ClientBatchAccountResolution:
    bindings = list(getattr(batch, "bindings", []) or [])
    if not bindings:
        return ClientBatchAccountResolution([], "empty", "当前批次没有绑定记录")

    all_accounts = list(getattr(owner, "accounts", []) or [])
    account_by_key = {account.key: account for account in all_accounts}
    slots = [int(getattr(binding, "slot_index", 0) or index + 1) for index, binding in enumerate(bindings)]
    if any(slot <= 0 for slot in slots) or len(set(slots)) != len(slots):
        return ClientBatchAccountResolution([], "slot_conflict", "批次槽位缺失或重复，已阻止账号身份猜测")

    assignments: dict[int, AccountConfig] = {}
    used_keys: set[str] = set()
    unresolved_indexes: list[int] = []
    for index, binding in enumerate(bindings):
        stable_key = str(getattr(binding, "account_key", "") or "").strip()
        if not stable_key:
            legacy_id = str(getattr(binding, "account_id", "") or "").strip()
            if legacy_id and not legacy_id.startswith("local_scan:"):
                stable_key = legacy_id
        account = account_by_key.get(stable_key)
        if account is None:
            unresolved_indexes.append(index)
            continue
        if account.key in used_keys:
            return ClientBatchAccountResolution([], "identity_conflict", "同一稳定账号被多个 binding 占用")
        assignments[index] = account
        used_keys.add(account.key)

    if unresolved_indexes:
        library_order = {account.key: index for index, account in enumerate(all_accounts)}
        candidates = [
            account
            for _source_index, account in sorted(
                enumerate(list(candidate_accounts or [])),
                key=lambda item: (library_order.get(item[1].key, len(library_order) + item[0]), item[0]),
            )
        ]
        if len(candidates) != len(bindings):
            return ClientBatchAccountResolution(
                [],
                "count_mismatch",
                f"当前分组账号数 {len(candidates)} 与批次绑定数 {len(bindings)} 不一致，已阻止槽位猜测",
            )
        if set(slots) != set(range(1, len(bindings) + 1)):
            return ClientBatchAccountResolution([], "slot_conflict", "批次槽位不是唯一连续序列，已阻止账号身份猜测")
        for index in unresolved_indexes:
            account = candidates[slots[index] - 1]
            if account.key in used_keys:
                return ClientBatchAccountResolution([], "identity_conflict", "槽位映射与已有稳定账号身份冲突")
            assignments[index] = account
            used_keys.add(account.key)

    ordered_accounts: list[AccountConfig] = []
    for index, binding in sorted(enumerate(bindings), key=lambda item: slots[item[0]]):
        account = assignments[index]
        binding.account_id = account.key
        binding.account_key = account.key
        binding.account_name = account.display_name
        binding.refresh_account_name = str(account.bookmark_title or account.bookmark_no)
        binding.slot_index = slots[index]
        binding.identity_status = "resolved"
        ordered_accounts.append(account)
    return ClientBatchAccountResolution(ordered_accounts, "resolved", "批次账号身份已解析", len(ordered_accounts))


def _group_counts_for_accounts(accounts: list[AccountConfig] | tuple[AccountConfig, ...]) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for account in accounts:
        counts[account.level] = counts.get(account.level, 0) + 1
    return tuple(counts.items())


def _compact_number_ranges(numbers: list[int] | tuple[int, ...]) -> str:
    unique_numbers = sorted({int(number) for number in numbers})
    if not unique_numbers:
        return "无"
    ranges: list[str] = []
    start = prev = unique_numbers[0]
    for number in unique_numbers[1:]:
        if number == prev + 1:
            prev = number
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = number
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return "、".join(ranges)


def _build_serial_run_plan(
    accounts: list[AccountConfig] | tuple[AccountConfig, ...],
    visible_window_numbers: list[int] | tuple[int, ...],
) -> SerialRunPlan:
    account_tuple = tuple(accounts)
    required_windows = tuple(sorted({int(account.game_window_no) for account in account_tuple}))
    visible_windows = tuple(sorted({int(number) for number in visible_window_numbers}))
    visible_set = set(visible_windows)
    missing_windows = tuple(number for number in required_windows if number not in visible_set)
    return SerialRunPlan(
        accounts=account_tuple,
        group_counts=_group_counts_for_accounts(account_tuple),
        required_windows=required_windows,
        visible_windows=visible_windows,
        missing_windows=missing_windows,
        max_window_no=max(required_windows) if required_windows else 0,
    )


def _format_group_counts(group_counts: tuple[tuple[str, int], ...]) -> str:
    return "、".join(f"{group} {count} 个" for group, count in group_counts) if group_counts else "无"


def _build_gui_refresh_login_capturer(playwright_capturer, log, fallback_confirm=None):
    options = DirectLinkLoginOptions(mode="auto")
    har_payload = load_http_har_for_mode(options, log=log)
    return create_login_capturer(
        options,
        har_payload,
        playwright_capturer=playwright_capturer,
        log=log,
        fallback_confirm=fallback_confirm,
    )


def _bookmark_write_context_from_owner(owner) -> BookmarkWriteContext | None:
    try:
        bookmark_file = Path(str(owner.bookmark_path.get() or "").strip())
        root_path = str(owner.bookmark_root_path.get() or "").strip()
        root_name = str(owner.bookmark_root_name.get() or "").strip()
        root_guid = str(getattr(owner, "bookmark_root_guid", None).get() or "").strip() if getattr(owner, "bookmark_root_guid", None) is not None else ""
        root_parent_path = str(getattr(owner, "bookmark_root_parent_path", None).get() or "").strip() if getattr(owner, "bookmark_root_parent_path", None) is not None else ""
    except Exception:
        return None
    if not bookmark_file.is_file() or not root_name or not (root_guid or root_path or root_parent_path):
        return None
    try:
        info = describe_bookmark_file(bookmark_file)
    except Exception:
        return None
    if not root_parent_path and "/children/" in root_path:
        root_parent_path = root_path.rsplit("/children/", 1)[0]
    return BookmarkWriteContext(
        bookmark_file=bookmark_file,
        browser=str(info.browser or ""),
        profile=str(info.profile or ""),
        root_path=root_path,
        root_name=root_name,
        root_guid=root_guid,
        root_parent_path=root_parent_path,
        allow_create_root=True,
    )


def _refresh_account_aliases(account: AccountConfig) -> set[str]:
    return {
        str(value or "").strip()
        for value in (
            account.key,
            account.bookmark_title,
            account.bookmark_no,
            account.display_name,
        )
        if str(value or "").strip()
    }


def _synchronize_refreshed_urls(owner, results) -> dict[str, int]:
    counts = {"accounts": 0, "bindings": 0, "conflicts": 0}
    accounts = list(getattr(owner, "accounts", []) or [])
    batch_store = getattr(owner, "client_batch_store", None)
    bindings = []
    if batch_store is not None and getattr(batch_store, "batches", None):
        try:
            bindings = list(batch_store.current_batch().bindings)
        except Exception:
            bindings = []

    for result in results:
        direct_url = str(getattr(result, "direct_url", "") or "").strip()
        result_name = str(getattr(result, "name", "") or "").strip()
        if not direct_url or not result_name:
            continue
        account_indexes = [
            index
            for index, account in enumerate(accounts)
            if result_name in _refresh_account_aliases(account)
        ]
        if len(account_indexes) > 1:
            counts["conflicts"] += 1
            continue

        matched_account = None
        if len(account_indexes) == 1:
            account_index = account_indexes[0]
            matched_account = accounts[account_index]
            if str(matched_account.url or "") != direct_url:
                accounts[account_index] = replace(matched_account, url=direct_url)
                matched_account = accounts[account_index]
                counts["accounts"] += 1

        binding_matches = []
        for binding in bindings:
            aliases = {
                str(getattr(binding, "account_id", "") or "").strip(),
                str(getattr(binding, "account_name", "") or "").strip(),
            }
            expected = {result_name}
            if matched_account is not None:
                expected.update({matched_account.key, matched_account.display_name})
            if aliases & expected:
                binding_matches.append(binding)
        if len(binding_matches) == 1:
            binding = binding_matches[0]
            if str(getattr(binding, "login_url", "") or "") != direct_url:
                binding.login_url = direct_url
                counts["bindings"] += 1
        elif len(binding_matches) > 1:
            counts["conflicts"] += 1

    owner.accounts = accounts
    if counts["accounts"]:
        refresh_table = getattr(owner, "_refresh_table", None)
        if callable(refresh_table):
            refresh_table()
        refresh_choices = getattr(owner, "_refresh_account_choices", None)
        if callable(refresh_choices):
            refresh_choices()
    if counts["bindings"] and batch_store is not None:
        batch_store.save()
    logger = getattr(owner, "_log", None)
    if callable(logger) and any(counts.values()):
        logger(
            f"[刷新地址] URL同步：账号={counts['accounts']}，批次绑定={counts['bindings']}，"
            f"冲突={counts['conflicts']}"
        )
    return counts


def _inject_latest_client_direct_urls(owner, accounts: list[AccountConfig]) -> list[AccountConfig]:
    direct_links_path = getattr(owner, "refresh_direct_links_path", None)
    if direct_links_path is None:
        direct_links_path = ensure_refresh_data_dir().direct_links_path
    resolved_accounts: list[AccountConfig] = []
    counts = {"updated": 0, "current": 0, "expired": 0, "missing": 0, "conflicts": 0, "bindings": 0}
    records = getattr(owner, "client_direct_bindings", {}) or {}
    batch_store = getattr(owner, "client_batch_store", None)
    batch_bindings = []
    batch_dirty = False
    if batch_store is not None and getattr(batch_store, "batches", None):
        try:
            batch_bindings = list(batch_store.current_batch().bindings)
        except Exception:
            batch_bindings = []

    for account in accounts:
        matches = [
            binding
            for binding in batch_bindings
            if str(getattr(binding, "account_key", "") or getattr(binding, "account_id", "")) == account.key
        ]
        record = records.get(account.key)
        identity = matches[0] if len(matches) == 1 else record
        resolved = resolve_client_direct_url_for_identity(
            account,
            direct_links_path,
            account_key=str(getattr(identity, "account_key", "") or account.key),
            refresh_account_name=str(getattr(identity, "refresh_account_name", "") or ""),
            bookmark_path=str(getattr(identity, "bookmark_path", "") or ""),
            slot_index=int(getattr(identity, "slot_index", 0) or 0),
        )
        binding_identity_conflict = len(matches) > 1
        if not binding_identity_conflict and resolved.status in {"found", "expired"} and resolved.direct_url:
            updated_account = replace(account, url=resolved.direct_url)
            resolved_accounts.append(updated_account)
            if resolved.direct_url != account.url:
                counts["updated"] += 1
            if resolved.expired:
                counts["expired"] += 1
            if record is not None:
                if str(getattr(record, "login_url", "") or "") != resolved.direct_url:
                    record.login_url = resolved.direct_url
                    counts["bindings"] += 1
                record.account_id = account.key
                record.account_key = account.key
                record.refresh_account_name = resolved.name
                record.bookmark_path = resolved.bookmark_path
                record.identity_status = "resolved"
                record.link_status = "expired" if resolved.expired else "ready"
            if len(matches) == 1:
                binding = matches[0]
                before = (
                    str(getattr(binding, "login_url", "") or ""),
                    str(getattr(binding, "account_id", "") or ""),
                    str(getattr(binding, "account_key", "") or ""),
                    str(getattr(binding, "refresh_account_name", "") or ""),
                    str(getattr(binding, "bookmark_path", "") or ""),
                    str(getattr(binding, "identity_status", "") or ""),
                    str(getattr(binding, "link_status", "") or ""),
                )
                binding.login_url = resolved.direct_url
                binding.account_id = account.key
                binding.account_key = account.key
                binding.refresh_account_name = resolved.name
                binding.bookmark_path = resolved.bookmark_path
                binding.identity_status = "resolved"
                binding.link_status = "expired" if resolved.expired else "ready"
                after = (
                    binding.login_url,
                    binding.account_id,
                    binding.account_key,
                    binding.refresh_account_name,
                    binding.bookmark_path,
                    binding.identity_status,
                    binding.link_status,
                )
                if after != before:
                    batch_dirty = True
                if before[0] != resolved.direct_url:
                    counts["bindings"] += 1
                else:
                    counts["current"] += 1
            elif len(matches) > 1:
                counts["conflicts"] += 1
            continue
        resolved_accounts.append(account)
        link_status = "link_conflict" if binding_identity_conflict or resolved.status == "conflict" else "link_missing"
        if resolved.status != "conflict" and is_complete_direct_login_url(account.url):
            link_status = "fallback_valid"
        if record is not None:
            record.link_status = link_status
            if link_status == "fallback_valid":
                record.login_url = account.url
        for binding in matches:
            before = (
                str(getattr(binding, "login_url", "") or ""),
                str(getattr(binding, "link_status", "") or ""),
            )
            binding.link_status = link_status
            if link_status == "fallback_valid":
                binding.login_url = account.url
            after = (
                str(getattr(binding, "login_url", "") or ""),
                str(getattr(binding, "link_status", "") or ""),
            )
            if after != before:
                batch_dirty = True
        if binding_identity_conflict or resolved.status == "conflict":
            counts["conflicts"] += 1
        else:
            counts["missing"] += 1

    if batch_dirty and batch_store is not None:
        batch_store.save()
    logger = getattr(owner, "_log", None) or getattr(owner, "_queue_log", None)
    if callable(logger):
        logger(
            "[客户端直登] 最新链接注入："
            f"更新={counts['updated']}，已是最新={counts['current']}，过期提示={counts['expired']}，缺失={counts['missing']}，"
            f"冲突={counts['conflicts']}，binding更新={counts['bindings']}"
        )
    return resolved_accounts


def _refresh_status_display(status: str) -> str:
    clean_status = str(status or "").strip()
    labels = {
        "local_success": "本地刷新成功",
        "bookmark_success": "收藏夹刷新成功",
        "bookmark_update_skipped": "本地成功/收藏夹未写回",
        "bookmark_not_found": "本地成功/收藏夹未找到",
        "bookmark_conflict": "本地成功/收藏夹冲突",
        "bookmark_browser_running": "本地成功/浏览器运行未写回",
        "bookmark_write_failed": "本地成功/收藏夹写入失败",
        "capture_failed": "刷新失败",
        "login_failed": "登录失败",
        "write_failed": "写入失败",
        "stopping": "停止中",
        "stopped": "已停止",
    }
    return labels.get(clean_status, clean_status or "待刷新")


def _refresh_status_tag(status: str) -> str:
    clean_status = str(status or "").strip()
    if clean_status in {"local_success", "bookmark_success", "success"}:
        return "success"
    if clean_status == "bookmark_update_skipped":
        return "skip"
    if clean_status in {
        "bookmark_not_found",
        "bookmark_conflict",
        "bookmark_browser_running",
        "bookmark_write_failed",
    } or "failed" in clean_status or "失败" in clean_status:
        return "failed"
    if clean_status in {"skipped", "stopped"}:
        return "skip"
    if clean_status == "stopping":
        return "running"
    return "running" if clean_status not in {"", "待刷新"} else ""


def _format_refresh_summary(summary) -> str:
    return (
        f"总数 {summary.total} / 成功 {summary.success} / 失败 {summary.failure} / "
        f"本地链接 {summary.local_links} / 收藏夹成功 {summary.bookmark_success} / "
        f"收藏夹未写回 {getattr(summary, 'bookmark_skipped', 0)} / 收藏夹失败 {summary.bookmark_failure}"
    )


def _refresh_password_display(password: str) -> str:
    return "******" if str(password or "") else ""


def _parse_refresh_json_or_jsonp(text: str) -> dict[str, object]:
    clean = str(text or "").strip()
    match = re.match(r"^[\w$.]+\((.*)\)\s*;?$", clean, re.S)
    if match:
        clean = match.group(1)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise CaptureFailed(f"h5sdk/login 响应不是有效 JSON/JSONP: {exc}") from exc
    if not isinstance(payload, dict):
        raise CaptureFailed("h5sdk/login 响应不是对象")
    return payload


def _extract_refresh_login_fields(payload: dict[str, object]) -> DirectLoginFields:
    state = payload.get("state")
    if str(state) not in {"1", "True", "true"}:
        raise LoginFailed(str(payload.get("msg") or "登录接口返回失败"))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise CaptureFailed("h5sdk/login 响应缺少 data 对象")
    fields = DirectLoginFields(
        token=str(data.get("token") or ""),
        time=str(data.get("time") or ""),
        sign=str(data.get("sign") or ""),
        uid=str(data.get("uid") or ""),
        uname=str(data.get("uname") or ""),
    )
    try:
        fields.validate()
    except ValueError as exc:
        raise CaptureFailed(str(exc)) from exc
    return fields


def _centered_child_position(
    owner_bounds: tuple[int, int, int, int],
    child_size: tuple[int, int],
    work_area: tuple[int, int, int, int],
) -> tuple[int, int]:
    owner_x, owner_y, owner_width, owner_height = (int(value) for value in owner_bounds)
    child_width, child_height = (max(1, int(value)) for value in child_size)
    work_left, work_top, work_right, work_bottom = (int(value) for value in work_area)
    x = owner_x + (max(1, owner_width) - child_width) // 2
    y = owner_y + (max(1, owner_height) - child_height) // 2
    max_x = max(work_left, work_right - child_width)
    max_y = max(work_top, work_bottom - child_height)
    return min(max(x, work_left), max_x), min(max(y, work_top), max_y)


def _tk_top_level_window_id(widget) -> int:
    try:
        return int(str(widget.wm_frame()), 0)
    except Exception:
        return int(widget.winfo_id())


def _native_window_bounds(widget) -> tuple[int, int, int, int] | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        get_window_rect = ctypes.windll.user32.GetWindowRect
        get_window_rect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        get_window_rect.restype = wintypes.BOOL
        if get_window_rect(wintypes.HWND(_tk_top_level_window_id(widget)), ctypes.byref(rect)):
            return (
                int(rect.left),
                int(rect.top),
                max(1, int(rect.right - rect.left)),
                max(1, int(rect.bottom - rect.top)),
            )
    except Exception:
        pass
    return None


def _monitor_work_area_for_owner(owner) -> tuple[int, int, int, int]:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class MonitorInfo(ctypes.Structure):
                _fields_ = (
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                )

            user32 = ctypes.windll.user32
            monitor_from_window = user32.MonitorFromWindow
            monitor_from_window.argtypes = (wintypes.HWND, wintypes.DWORD)
            monitor_from_window.restype = wintypes.HANDLE
            get_monitor_info = user32.GetMonitorInfoW
            get_monitor_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
            get_monitor_info.restype = wintypes.BOOL
            monitor = monitor_from_window(wintypes.HWND(_tk_top_level_window_id(owner)), 2)
            info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
            if monitor and get_monitor_info(monitor, ctypes.byref(info)):
                work = info.rcWork
                return int(work.left), int(work.top), int(work.right), int(work.bottom)
        except Exception:
            pass

    try:
        left = int(owner.winfo_vrootx())
        top = int(owner.winfo_vrooty())
        width = max(1, int(owner.winfo_vrootwidth()))
        height = max(1, int(owner.winfo_vrootheight()))
    except Exception:
        left = 0
        top = 0
        width = max(1, int(owner.winfo_screenwidth()))
        height = max(1, int(owner.winfo_screenheight()))
    return left, top, left + width, top + height


def _move_tk_window(dialog, x: int, y: int) -> None:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            set_window_pos = ctypes.windll.user32.SetWindowPos
            set_window_pos.argtypes = (
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            )
            set_window_pos.restype = wintypes.BOOL
            flags = 0x0001 | 0x0004 | 0x0010
            if set_window_pos(
                wintypes.HWND(_tk_top_level_window_id(dialog)),
                wintypes.HWND(0),
                x,
                y,
                0,
                0,
                flags,
            ):
                return
        except Exception:
            pass
    dialog.geometry(f"{int(x):+d}{int(y):+d}")


def _position_dialog_relative_to_owner(
    dialog,
    owner,
    *,
    work_area_provider=None,
    move_window=None,
) -> tuple[int, int]:
    dialog.update_idletasks()
    dialog_bounds = _native_window_bounds(dialog)
    if dialog_bounds is not None:
        width, height = dialog_bounds[2:]
    else:
        width = int(dialog.winfo_width())
        height = int(dialog.winfo_height())
        if width <= 1:
            width = int(dialog.winfo_reqwidth())
        if height <= 1:
            height = int(dialog.winfo_reqheight())
    owner_bounds = _native_window_bounds(owner)
    if owner_bounds is None:
        owner_bounds = (
            int(owner.winfo_rootx()),
            int(owner.winfo_rooty()),
            int(owner.winfo_width()),
            int(owner.winfo_height()),
        )
    provider = work_area_provider or _monitor_work_area_for_owner
    position = _centered_child_position(owner_bounds, (width, height), provider(owner))
    mover = move_window or _move_tk_window
    mover(dialog, *position)
    return position


class RefreshAddressDialog(tk.Toplevel):
    columns = ("checked", "name", "username", "password", "bookmark_path", "mode", "status", "message")

    def __init__(self, owner: "LauncherApp") -> None:
        super().__init__(owner)
        self.withdraw()
        self.owner = owner
        self.title("刷新客户端直登地址")
        self.geometry("1080x560")
        self.minsize(980, 500)
        self.transient(owner)
        self.paths = ensure_refresh_data_dir()
        self.account_store = AccountsStore(self.paths.accounts_path)
        self.channels = load_channels(self.paths.data_dir)
        self.accounts: list[RefreshAccount] = []
        self.checked_names: set[str] = set()
        self.message_by_name: dict[str, str] = {}
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self._close_when_idle = False
        self.channel_var = tk.StringVar(value=next(iter(self.channels), "正式服"))
        self.status_var = tk.StringVar(value=f"数据目录：{self.paths.data_dir}")
        self.bookmark_context_var = tk.StringVar(value=self._bookmark_context_label())
        self.backup_var = tk.StringVar(value="收藏夹备份：尚未生成")
        self.sync_bookmarks_var = tk.BooleanVar(value=self._load_sync_bookmark_preference())
        self._build_widgets()
        self._load_accounts()
        _position_dialog_relative_to_owner(self, owner)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.deiconify()
        self.lift()
        self.focus_set()

    def _build_widgets(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.rowconfigure(2, weight=1)
        root.columnconfigure(0, weight=1)

        top = ttk.Frame(root)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(top, text="登录渠道：").pack(side=tk.LEFT)
        ttk.Combobox(
            top,
            textvariable=self.channel_var,
            values=tuple(self.channels.keys()),
            width=16,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Label(top, textvariable=self.status_var, foreground="#666666").pack(side=tk.LEFT, fill=tk.X, expand=True)

        context_row = ttk.Frame(root)
        context_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(context_row, textvariable=self.bookmark_context_var).pack(side=tk.LEFT)
        ttk.Checkbutton(
            context_row,
            text="刷新成功后同步/导入收藏夹",
            variable=self.sync_bookmarks_var,
            command=self._save_sync_bookmark_preference,
        ).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(context_row, textvariable=self.backup_var, foreground="#666666").pack(side=tk.LEFT, padx=(16, 8))
        ttk.Button(context_row, text="打开备份目录", command=lambda: self._open_directory(self.paths.backups_dir)).pack(side=tk.RIGHT)
        ttk.Button(context_row, text="打开直登链接目录", command=lambda: self._open_directory(self.paths.url_dir)).pack(side=tk.RIGHT, padx=(0, 6))

        table_frame = ttk.Frame(root)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table_frame, columns=self.columns, show="headings", selectmode="extended", height=12)
        headings = {
            "checked": "勾选",
            "name": "名称",
            "username": "账号",
            "password": "密码",
            "bookmark_path": "收藏夹位置",
            "mode": "刷新方式",
            "status": "状态",
            "message": "消息",
        }
        widths = {
            "checked": 52,
            "name": 90,
            "username": 140,
            "password": 70,
            "bookmark_path": 220,
            "mode": 82,
            "status": 110,
            "message": 260,
        }
        for column in self.columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                anchor=tk.CENTER if column in {"checked", "password", "mode", "status"} else tk.W,
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", lambda _event: self._toggle_selected_checked())
        self.tree.tag_configure("success", foreground="#008800")
        self.tree.tag_configure("failed", foreground="#cc0000")
        self.tree.tag_configure("running", foreground="#0066cc")
        self.tree.tag_configure("skip", foreground="#888888")

        actions = ttk.Frame(root)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        for text, command in (
            ("新增账号", self._add_account),
            ("编辑账号", self._edit_selected_account),
            ("移除账号", self._delete_selected_accounts),
            ("导入账号", self._import_file),
            ("从剪贴板导入", self._import_clipboard),
            ("清空列表", self._clear_accounts),
            ("测试选中账号", self._test_selected),
            ("刷新选中", self._refresh_selected),
            ("刷新全部", self._refresh_all),
            ("同步现有链接到收藏夹", self._sync_existing_links_to_bookmarks),
            ("停止刷新", self._stop_refresh),
            ("关闭", self._close),
        ):
            ttk.Button(actions, text=text, command=command).pack(side=tk.LEFT, padx=(0, 6), pady=2)

    def _bookmark_context_label(self) -> str:
        context = _bookmark_write_context_from_owner(self.owner)
        if context is None:
            return "收藏夹：未配置可写入的 Bookmarks/profile"
        return f"收藏夹：{context.browser or '未知浏览器'} / {context.profile or '未知 profile'}"

    def _load_sync_bookmark_preference(self) -> bool:
        path = self.paths.data_dir / "refresh_preferences.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return bool(payload.get("sync_bookmarks_after_refresh", False))
        except Exception:
            return False

    def _save_sync_bookmark_preference(self) -> None:
        path = self.paths.data_dir / "refresh_preferences.json"
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps({"sync_bookmarks_after_refresh": bool(self.sync_bookmarks_var.get())}, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def _open_directory(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror("打开目录", redact_sensitive_text(exc), parent=self)

    def _load_accounts(self) -> None:
        self.accounts = self.account_store.load()
        self.checked_names = {account.name for account in self.accounts if account.enabled}
        self._refresh_table()

    def _save_accounts(self) -> None:
        self.account_store.save(self.accounts)

    def _refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for account in self.accounts:
            status = account.last_status or "待刷新"
            tag = "skip" if not account.enabled else _refresh_status_tag(status)
            self.tree.insert("", tk.END, iid=account.name, values=self._row_values(account), tags=(tag,))

    def _row_values(self, account: RefreshAccount) -> tuple[str, str, str, str, str, str, str, str]:
        return (
            "☑" if account.name in self.checked_names else "☐",
            account.name,
            account.username,
            _refresh_password_display(account.password),
            account.bookmark_path,
            account.refresh_mode,
            _refresh_status_display(account.last_status or "待刷新"),
            self.message_by_name.get(account.name, ""),
        )

    def _on_tree_click(self, event: object) -> None:
        row_id = self.tree.identify_row(getattr(event, "y", 0))
        column = self.tree.identify_column(getattr(event, "x", 0))
        if row_id and column == "#1":
            self._toggle_checked(row_id)

    def _toggle_checked(self, name: str) -> None:
        if name in self.checked_names:
            self.checked_names.remove(name)
        else:
            self.checked_names.add(name)
        account = self._account_by_name(name)
        if account is not None and self.tree.exists(name):
            self.tree.item(name, values=self._row_values(account))

    def _toggle_selected_checked(self) -> None:
        for name in self.tree.selection():
            self._toggle_checked(str(name))

    def _account_by_name(self, name: str) -> RefreshAccount | None:
        for account in self.accounts:
            if account.name == name:
                return account
        return None

    def _selected_names(self) -> set[str]:
        checked = {name for name in self.checked_names if self._account_by_name(name) is not None}
        if checked:
            return checked
        return {str(name) for name in self.tree.selection()}

    def _selected_accounts(self) -> list[RefreshAccount]:
        names = self._selected_names()
        return [account for account in self.accounts if account.name in names]

    def _add_account(self) -> None:
        account = self._account_editor("新增账号")
        if account is None:
            return
        self.accounts = merge_accounts_by_name([*self.accounts, account])
        self.checked_names.add(account.name)
        self._save_accounts()
        self._refresh_table()

    def _edit_selected_account(self) -> None:
        selected = self._selected_accounts()
        if len(selected) != 1:
            messagebox.showwarning("编辑账号", "请选择一个账号。", parent=self)
            return
        account = self._account_editor("编辑账号", selected[0])
        if account is None:
            return
        self.accounts = [account if item.name == selected[0].name else item for item in self.accounts]
        if selected[0].name != account.name:
            self.checked_names.discard(selected[0].name)
        self.checked_names.add(account.name)
        self._save_accounts()
        self._refresh_table()

    def _account_editor(self, title: str, account: RefreshAccount | None = None) -> RefreshAccount | None:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        name_var = tk.StringVar(value=getattr(account, "name", ""))
        username_var = tk.StringVar(value=getattr(account, "username", ""))
        password_var = tk.StringVar(value=getattr(account, "password", ""))
        bookmark_var = tk.StringVar(value=getattr(account, "bookmark_path", ""))
        bookmark_preview_var = tk.StringVar(value="")
        channel_var = tk.StringVar(value=getattr(account, "channel", self.channel_var.get()) or self.channel_var.get())
        enabled_var = tk.BooleanVar(value=bool(getattr(account, "enabled", True)))
        fields = (
            ("名称", name_var, False),
            ("账号", username_var, False),
            ("密码", password_var, True),
            ("收藏夹位置", bookmark_var, False),
        )
        for row, (label, var, secret) in enumerate(fields):
            ttk.Label(frame, text=label, width=12, anchor="e").grid(row=row, column=0, sticky="e", padx=(0, 8), pady=4)
            ttk.Entry(frame, textvariable=var, width=42, show="*" if secret else "").grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Label(frame, textvariable=bookmark_preview_var, foreground="#666666").grid(
            row=4, column=1, sticky="w", pady=(0, 4)
        )
        ttk.Label(frame, text="登录渠道", width=12, anchor="e").grid(row=5, column=0, sticky="e", padx=(0, 8), pady=4)
        ttk.Combobox(frame, textvariable=channel_var, values=tuple(self.channels.keys()), width=39, state="readonly").grid(
            row=5, column=1, sticky="ew", pady=4
        )
        ttk.Checkbutton(frame, text="启用", variable=enabled_var).grid(row=6, column=1, sticky="w", pady=4)
        result: dict[str, RefreshAccount] = {}

        def update_bookmark_preview(*_args) -> None:
            context = _bookmark_write_context_from_owner(self.owner)
            preview = BookmarkUrlUpdater(context=context, dry_run=True).preview(bookmark_var.get())
            bookmark_preview_var.set(preview.message)

        bookmark_var.trace_add("write", update_bookmark_preview)
        update_bookmark_preview()

        def save() -> None:
            name = name_var.get().strip()
            username = username_var.get().strip()
            password = password_var.get()
            missing = [field for field, value in (("名称", name), ("账号", username), ("密码", password)) if not str(value).strip()]
            if missing:
                messagebox.showwarning(title, "缺少字段：" + "、".join(missing), parent=dialog)
                return
            result["account"] = RefreshAccount(
                name=name,
                username=username,
                password=password,
                channel=channel_var.get().strip() or "正式服",
                bookmark_path=bookmark_var.get().strip(),
                enabled=bool(enabled_var.get()),
                remark=getattr(account, "remark", "") if account is not None else "",
                last_refresh_time=getattr(account, "last_refresh_time", "") if account is not None else "",
                expire_hint=getattr(account, "expire_hint", "") if account is not None else "",
                last_status=getattr(account, "last_status", "待刷新") if account is not None else "待刷新",
            )
            dialog.destroy()

        button_row = ttk.Frame(frame)
        button_row.grid(row=7, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(button_row, text="保存", command=save).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(button_row, text="取消", command=dialog.destroy).pack(side=tk.RIGHT)
        dialog.grab_set()
        dialog.wait_window()
        return result.get("account")

    def _delete_selected_accounts(self) -> None:
        names = self._selected_names()
        if not names:
            messagebox.showwarning("移除账号", "请先勾选或选择账号。", parent=self)
            return
        if not messagebox.askyesno(
            "移除账号",
            "仅从上号器本地账号库、直登链接库、生成的 .url、批次绑定和运行缓存中移除。\n"
            "不会删除原始 CSV/Excel/文本导入文件，也不会删除浏览器收藏夹。\n\n"
            f"确定移除选中的 {len(names)} 个账号吗？",
            parent=self,
        ):
            return
        results = []
        for name in sorted(names):
            account_keys = {
                account.key
                for account in list(getattr(self.owner, "accounts", []) or [])
                if name in _refresh_account_aliases(account)
            }
            result = delete_refresh_account_resources(
                self.paths,
                name,
                account_keys=account_keys,
                client_batch_store=getattr(self.owner, "client_batch_store", None),
                runtime_cache=getattr(self.owner, "client_direct_bindings", None),
            )
            results.append(result)
            if result.account_removed and account_keys:
                self.owner.accounts = [
                    account for account in list(getattr(self.owner, "accounts", []) or [])
                    if account.key not in account_keys
                ]
        self.accounts = self.account_store.load()
        self.checked_names -= names
        self._refresh_table()
        refresh_table = getattr(self.owner, "_refresh_table", None)
        if callable(refresh_table):
            refresh_table()
        refresh_choices = getattr(self.owner, "_refresh_account_choices", None)
        if callable(refresh_choices):
            refresh_choices()
        removed_files = sum(len(result.url_files_removed) for result in results)
        removed_bindings = sum(result.bindings_removed for result in results)
        removed_accounts = sum(1 for result in results if result.account_removed)
        errors = sum(len(result.errors) for result in results)
        self.status_var.set(
            f"账号记录 {removed_accounts}/{len(results)}，生成链接 {removed_files} 个，"
            f"批次关联 {removed_bindings} 个，失败 {errors} 项"
        )
        self.owner._log(
            f"[刷新地址] 移除账号：账号记录={removed_accounts}/{len(results)}，生成链接={removed_files}，"
            f"批次关联={removed_bindings}，失败={errors}"
        )
        reload_accounts = getattr(self.owner, "_load_accounts", None)
        if callable(reload_accounts):
            reload_accounts()

    def _clear_accounts(self) -> None:
        if not messagebox.askyesno("清空列表", "确定清空弹窗内账号列表吗？不会删除直登链接库。", parent=self):
            return
        self.accounts = []
        self.checked_names.clear()
        self._save_accounts()
        self._refresh_table()

    def _import_file(self) -> None:
        path = filedialog.askopenfilename(
            title="导入账号文件",
            filetypes=[("账号文件", "*.csv *.txt *.xlsx"), ("CSV", "*.csv"), ("文本", "*.txt"), ("Excel", "*.xlsx"), ("所有文件", "*.*")],
            parent=self,
        )
        if not path:
            return
        try:
            imported = import_accounts_from_file(path, channel=self.channel_var.get())
        except Exception as exc:
            messagebox.showerror("导入账号", str(exc), parent=self)
            return
        self._merge_imported_accounts(imported.accounts)
        self.status_var.set(f"导入 {len(imported.accounts)} 个，失败 {len(imported.failures)} 行")
        if imported.failures:
            self.owner._log(f"[刷新地址] 导入账号失败行数={len(imported.failures)}，未写入账号密码。")

    def _import_clipboard(self) -> None:
        try:
            text = self.clipboard_get()
            imported = import_accounts_from_text(text, channel=self.channel_var.get())
        except Exception as exc:
            messagebox.showerror("剪贴板导入", str(exc), parent=self)
            return
        self._merge_imported_accounts(imported.accounts)
        self.status_var.set(f"剪贴板导入 {len(imported.accounts)} 个，失败 {len(imported.failures)} 行")

    def _merge_imported_accounts(self, accounts: list[RefreshAccount]) -> None:
        self.accounts = merge_accounts_by_name([*self.accounts, *accounts])
        self.checked_names.update(account.name for account in accounts)
        self._save_accounts()
        self._refresh_table()

    def _test_selected(self) -> None:
        selected = self._selected_accounts()
        if not selected:
            messagebox.showwarning("测试选中账号", "请先勾选或选择账号。", parent=self)
            return
        self._start_refresh(selected[:1])

    def _refresh_selected(self) -> None:
        selected = self._selected_accounts()
        if not selected:
            messagebox.showwarning("刷新选中", "请先勾选或选择账号。", parent=self)
            return
        self._start_refresh(selected)

    def _refresh_all(self) -> None:
        self._start_refresh(list(self.accounts))

    def _start_refresh(self, accounts: list[RefreshAccount]) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("刷新地址", "已有刷新任务正在运行。", parent=self)
            return
        enabled_accounts = [account for account in accounts if account.enabled]
        if not enabled_accounts:
            messagebox.showwarning("刷新地址", "没有启用的账号可刷新。", parent=self)
            return
        try:
            import requests  # noqa: F401
        except Exception:
            messagebox.showerror("刷新地址", "当前项目解释器缺少 requests，批量刷新已停止，不会自动打开 Playwright 浏览器。", parent=self)
            return
        self._save_accounts()
        self.stop_event.clear()
        self._set_busy(True)
        for account in enabled_accounts:
            self._set_account_status(account.name, "刷新中", "")
        self._save_sync_bookmark_preference()
        bookmark_context = _bookmark_write_context_from_owner(self.owner) if self.sync_bookmarks_var.get() else None
        self.worker_thread = threading.Thread(
            target=self._refresh_worker,
            args=(enabled_accounts, bookmark_context),
            daemon=True,
        )
        self.worker_thread.start()

    def _refresh_worker(
        self,
        accounts: list[RefreshAccount],
        bookmark_context: BookmarkWriteContext | None,
    ) -> None:
        try:
            bookmark_updater = BookmarkUrlUpdater(
                context=bookmark_context,
                backups_dir=self.paths.backups_dir,
                dry_run=bookmark_context is None,
                log=lambda message: self._thread_log(message),
            )
            service = DirectLinkRefreshService(
                data_dir=self.paths.data_dir,
                login_capturer=_build_gui_refresh_login_capturer(
                    self._capture_login_fields,
                    self._thread_log,
                    self._confirm_playwright_fallback,
                ),
                bookmark_updater=bookmark_updater,
                log=lambda message: self._thread_log(message),
                root_create_confirm=self._confirm_root_creation,
                bookmark_plan_confirm=self._confirm_bookmark_plan,
            )
            summary = service.refresh_accounts(
                accounts,
                channel_name=self.channel_var.get(),
                names={account.name for account in accounts},
                retries=1,
                stop_event=self.stop_event,
                progress=lambda result: self.after(0, lambda result=result: self._apply_refresh_result(result)),
            )
            self.after(
                0,
                lambda: self._complete_refresh(summary, bookmark_updater),
            )
        except Exception as exc:
            message = redact_sensitive_text(exc)
            self.after(0, lambda message=message: messagebox.showerror("刷新地址", message, parent=self))
        finally:
            self.after(0, lambda: self._finish_refresh())

    def _complete_refresh(self, summary, bookmark_updater: BookmarkUrlUpdater) -> None:
        status = _format_refresh_summary(summary)
        self.status_var.set(f"已停止 / {status}" if self.stop_event.is_set() else status)
        _synchronize_refreshed_urls(self.owner, summary.results)
        backup_path = bookmark_updater.backup_path
        if backup_path is not None:
            self.backup_var.set(f"收藏夹备份：{backup_path}")
            self.owner._log(f"[刷新地址] 收藏夹备份：{backup_path}")
        self._persist_resolved_root_identity(bookmark_updater.last_batch_result)
        reload_accounts = getattr(self.owner, "_load_accounts", None)
        if callable(reload_accounts):
            reload_accounts()

    def _capture_login_fields(
        self,
        account: RefreshAccount,
        channel: ChannelConfig,
        _stop_event: threading.Event | None = None,
    ) -> DirectLoginFields:
        settings = load_settings(self.owner.settings_path.get())
        runner_stop_event = _stop_event or threading.Event()
        runner = AccountRunner(
            AccountConfig(
                level="刷新地址",
                bookmark_no=0,
                game_window_no=0,
                url=channel.web_login_url,
                bookmark_title=account.name,
            ),
            settings,
            runner_stop_event,
            log=lambda message, account=account: self._thread_log(self._mask_account_message(message, account)),
            update_status=lambda _account, status: self._thread_log(f"[刷新地址][{account.name}] status={status}"),
        )
        runner._prepare_playwright_runtime()
        from playwright.sync_api import sync_playwright

        playwright = None
        browser = None
        try:
            playwright = sync_playwright().start()
            browser = getattr(playwright, settings.browser).launch(
                headless=False,
                args=[
                    f"--window-size={settings.window_width},{settings.window_height}",
                    "--window-position=100,100",
                ],
            )
            page = browser.new_page(viewport={"width": settings.window_width, "height": settings.window_height})
            if runner_stop_event.is_set():
                raise InterruptedError("用户停止")
            self._thread_log(f"[刷新地址][{account.name}] 打开登录页 host={urlparse(channel.web_login_url).netloc}")
            page.goto(channel.web_login_url, wait_until="domcontentloaded", timeout=settings.page_load_timeout_ms)
            if not runner._detect_login_form(page):
                raise LoginFailed("未检测到账号密码登录界面")
            if runner_stop_event.is_set():
                raise InterruptedError("用户停止")
            with page.expect_response(lambda response: LOGIN_ENDPOINT in response.url, timeout=30000) as response_info:
                runner._fill_and_submit_login(page, account.username, account.password)
            response = response_info.value
            fields = _extract_refresh_login_fields(_parse_refresh_json_or_jsonp(response.text()))
            self._thread_log(
                f"[刷新地址][{account.name}] 捕获 h5sdk/login "
                f"uid_len={len(fields.uid)} uname_len={len(fields.uname)} "
                f"token_len={len(fields.token)} time_len={len(fields.time)} sign_len={len(fields.sign)}"
            )
            return fields
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass

    def _confirm_playwright_fallback(self, account_name: str) -> bool:
        completed = threading.Event()
        decision = {"value": False}
        def ask() -> None:
            decision["value"] = messagebox.askyesno(
                "HTTP 登录失败",
                f"账号 {account_name} 的 HTTP 登录失败。是否明确回退 Playwright 浏览器？",
                parent=self,
            )
            completed.set()
        self.after(0, ask)
        while not completed.wait(0.1):
            if self.stop_event.is_set():
                return False
        return bool(decision["value"])

    def _ask_worker_yes_no(self, title: str, message: str) -> bool:
        completed = threading.Event()
        decision = {"value": False}
        def ask() -> None:
            decision["value"] = messagebox.askyesno(title, message, parent=self)
            completed.set()
        self.after(0, ask)
        while not completed.wait(0.1):
            if self.stop_event.is_set():
                return False
        return bool(decision["value"])

    def _confirm_root_creation(self, root_name: str) -> bool:
        return self._ask_worker_yes_no(
            "创建收藏夹账号根目录",
            f"未找到收藏夹账号根目录“{root_name}”。\n"
            f"已确认父位置：{self.owner.bookmark_root_parent_path.get()}\n"
            "是否在该位置创建目录并重新绑定？",
        )

    def _confirm_bookmark_plan(self, updated: int, created: int, conflicts: int, skipped: int) -> bool:
        return self._ask_worker_yes_no(
            "确认收藏夹整批计划",
            f"更新 {updated}\n新增 {created}\n冲突 {conflicts}\n跳过 {skipped}\n\n是否执行一次整批写入？",
        )

    def _persist_resolved_root_identity(self, result) -> None:
        if result is None or not getattr(result, "root_guid", "") or not getattr(result, "root_path", ""):
            return
        self.owner.bookmark_root_guid.set(result.root_guid)
        self.owner.bookmark_root_path.set(result.root_path)
        self.owner.bookmark_root_name.set(result.root_name)
        self.owner.bookmark_root_display_name.set(result.root_name)
        parent_path = result.root_path.rsplit("/children/", 1)[0] if "/children/" in result.root_path else ""
        self.owner.bookmark_root_parent_path.set(parent_path)
        self.owner._save_bookmark_settings(self.owner.bookmark_path.get())
        self.bookmark_context_var.set(self._bookmark_context_label())

    def _sync_existing_links_to_bookmarks(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("同步现有链接", "已有任务正在运行。", parent=self)
            return
        context = _bookmark_write_context_from_owner(self.owner)
        if context is None:
            messagebox.showerror("同步现有链接", "未配置可安全绑定的 Bookmarks 文件和父目录。", parent=self)
            return
        self.stop_event.clear()
        self._set_busy(True)
        self.worker_thread = threading.Thread(target=self._sync_existing_links_worker, args=(context,), daemon=True)
        self.worker_thread.start()

    def _sync_existing_links_worker(self, context: BookmarkWriteContext) -> None:
        updater = BookmarkUrlUpdater(
            context=context, backups_dir=self.paths.backups_dir, dry_run=False,
            log=lambda message: self._thread_log(message),
        )
        try:
            accounts = self.account_store.load()
            links = DirectLinkStore(self.paths.direct_links_path)
            if links.load_error is not None:
                raise RuntimeError("现有直登链接库无法读取")
            items = []
            skipped = 0
            for account in accounts:
                record = links.links.get(account.name, {})
                direct_url = str(record.get("direct_url") or "") if isinstance(record, dict) else ""
                if not direct_url or not str(account.bookmark_path or "").strip():
                    skipped += 1
                    continue
                items.append(BookmarkBatchItem(stable_refresh_account_key(account), account.bookmark_path, direct_url))
            result = updater.apply_batch(
                items,
                root_create_confirm=self._confirm_root_creation,
                plan_confirm=lambda u, c, k, s: self._confirm_bookmark_plan(u, c, k, s + skipped),
            )
            updated_accounts = [replace(account, last_status=result.status) for account in accounts]
            self.account_store.save(updated_accounts)
            self.after(0, lambda: self._complete_existing_link_sync(result, updater))
        except Exception as exc:
            message = redact_sensitive_text(exc)
            self.after(0, lambda: messagebox.showerror("同步现有链接", message, parent=self))
        finally:
            self.after(0, self._finish_refresh)

    def _complete_existing_link_sync(self, result, updater: BookmarkUrlUpdater) -> None:
        self.status_var.set(result.message)
        self._persist_resolved_root_identity(updater.last_batch_result)
        if updater.backup_path is not None:
            self.backup_var.set(f"收藏夹备份：{updater.backup_path}")
        self.owner._log(f"[同步现有链接] {result.message}")

    def _thread_log(self, message: object) -> None:
        self.after(0, lambda: self.owner._log(f"[刷新地址] {redact_sensitive_text(message)}"))

    def _mask_account_message(self, message: object, account: RefreshAccount) -> str:
        text = str(message if message is not None else "")
        username = str(account.username or "")
        password = str(account.password or "")
        if username:
            text = text.replace(username, "***ACCOUNT***")
        if password:
            text = text.replace(password, "***PASSWORD***")
        return redact_sensitive_text(text)

    def _apply_refresh_result(self, result) -> None:
        self._set_account_status(result.name, result.status, result.message)
        self.accounts = self.account_store.load()
        self._refresh_table()

    def _set_account_status(self, name: str, status: str, message: str) -> None:
        self.message_by_name[name] = redact_sensitive_text(message)
        self.accounts = [replace(account, last_status=status) if account.name == name else account for account in self.accounts]
        account = self._account_by_name(name)
        if account is not None and self.tree.exists(name):
            tag = _refresh_status_tag(status)
            self.tree.item(name, values=self._row_values(account), tags=(tag,))

    def _set_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        for child in self.winfo_children():
            self._set_children_state(child, state)

    def _set_children_state(self, widget: object, state: str) -> None:
        for child in getattr(widget, "winfo_children", lambda: [])():
            try:
                if isinstance(child, ttk.Button) and str(child.cget("text")) not in {"停止刷新", "关闭"}:
                    child.configure(state=state)
            except Exception:
                pass
            self._set_children_state(child, state)

    def _finish_refresh(self) -> None:
        self.accounts = self.account_store.load()
        self._refresh_table()
        self._set_busy(False)
        if self._close_when_idle:
            self._save_accounts()
            self.destroy()

    def _stop_refresh(self) -> None:
        self.stop_event.set()
        self.status_var.set("正在停止刷新...")
        for account in self.accounts:
            if str(account.last_status) in {"刷新中", "running"}:
                self._set_account_status(account.name, "stopping", "正在停止")

    def _close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            self._close_when_idle = True
            self._stop_refresh()
            self.status_var.set("正在停止刷新，任务结束后关闭窗口...")
            return
        self._save_accounts()
        self.destroy()


_TK_BASE = TkinterDnD.Tk if TkinterDnD is not None else tk.Tk


class LoginAccountManagerDialog(tk.Toplevel):
    columns = ("order", "name", "group", "bookmark_path", "link_status", "direct_url", "included")

    def __init__(self, owner: "LauncherApp") -> None:
        super().__init__(owner)
        self.owner = owner
        self.paths = ensure_refresh_data_dir()
        self.roster_store = LoginAccountRosterStore(self.paths.login_accounts_path)
        self.rows = []
        self.link_records: dict[str, dict[str, object]] = {}
        self.status_filter_var = tk.StringVar(value="全部")
        self.group_filter_var = tk.StringVar(value="全部分组")
        self.title("直登账号管理")
        self.geometry("1040x560")
        self.minsize(900, 480)
        self.transient(owner)
        self._build_widgets()
        self._reload()
        _position_dialog_relative_to_owner(self, owner)

    def _build_widgets(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        filter_row = ttk.Frame(root)
        filter_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(filter_row, text="状态筛选").pack(side=tk.LEFT, padx=(0, 6))
        self.status_filter_box = ttk.Combobox(
            filter_row, textvariable=self.status_filter_var, state="readonly", width=12,
            values=("全部", "已参与", "未参与", "链接缺失", "链接过期"),
        )
        self.status_filter_box.pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(filter_row, text="分组筛选").pack(side=tk.LEFT, padx=(0, 6))
        self.group_filter_box = ttk.Combobox(
            filter_row, textvariable=self.group_filter_var, state="readonly", width=16,
        )
        self.group_filter_box.pack(side=tk.LEFT)
        for box in (self.status_filter_box, self.group_filter_box):
            box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_table())
        ttk.Label(
            filter_row,
            text="账号来源仅为“刷新地址”账号库；移出登录列表不会删除账号或链接。",
            foreground="#666666",
        ).pack(side=tk.LEFT, padx=(16, 0))

        table_frame = ttk.Frame(root)
        table_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(table_frame, columns=self.columns, show="headings", selectmode="extended")
        headings = {
            "order": "登录顺序",
            "name": "名称",
            "group": "分组",
            "bookmark_path": "收藏夹路径",
            "link_status": "直登状态",
            "direct_url": "直登链接",
            "included": "上号状态",
        }
        widths = {"order": 72, "name": 110, "group": 100, "bookmark_path": 210, "link_status": 90, "direct_url": 300, "included": 90}
        for column in self.columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor=tk.CENTER if column in {"order", "link_status", "included"} else tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(table_frame, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=(8, 0))
        for text, command in (
            ("上移", lambda: self._move_selected(-1)),
            ("下移", lambda: self._move_selected(1)),
            ("选中账号加入上号列表", lambda: self._set_selected_included(True)),
            ("选中账号移出上号列表", lambda: self._set_selected_included(False)),
            ("当前筛选全部加入", lambda: self._set_filtered_included(True)),
            ("当前筛选全部移出", lambda: self._set_filtered_included(False)),
            ("关闭", self._close),
        ):
            ttk.Button(actions, text=text, command=command).pack(side=tk.LEFT, padx=(0, 6))

    def _reload(self) -> None:
        refresh_store = AccountsStore(self.paths.accounts_path)
        refresh_accounts = refresh_store.load()
        self.rows = self.roster_store.reconcile(refresh_accounts)
        self.link_records = DirectLinkStore(self.paths.direct_links_path).links
        groups = []
        for row in self.rows:
            group = logical_group_from_bookmark_path(row.account.bookmark_path)
            if group not in groups:
                groups.append(group)
        self.group_filter_box["values"] = ("全部分组", *groups)
        if self.group_filter_var.get() not in self.group_filter_box["values"]:
            self.group_filter_var.set("全部分组")
        self._refresh_table()

    def _filtered_rows(self):
        value = self.status_filter_var.get()
        group = self.group_filter_var.get()
        rows = list(self.rows)
        if value == "已参与":
            rows = [row for row in rows if row.included]
        elif value == "未参与":
            rows = [row for row in rows if not row.included]
        elif value == "链接缺失":
            rows = [row for row in rows if not str(self.link_records.get(row.account.name, {}).get("direct_url") or "")]
        elif value == "链接过期":
            rows = [row for row in rows if self._link_status(row) == "过期"]
        if group != "全部分组":
            rows = [row for row in rows if logical_group_from_bookmark_path(row.account.bookmark_path) == group]
        return rows

    def _link_status(self, row) -> str:
        record = self.link_records.get(row.account.name, {})
        direct_url = str(record.get("direct_url") or "")
        if not direct_url:
            return "缺失"
        expire_hint = str(record.get("expire_hint") or "").strip()
        if expire_hint:
            try:
                expires_at = datetime.fromisoformat(expire_hint.replace("Z", "+00:00"))
                current = datetime.now(expires_at.tzinfo) if expires_at.tzinfo is not None else datetime.now()
                if expires_at <= current:
                    return "过期"
            except ValueError:
                pass
        return "可用"

    def _refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self._filtered_rows():
            record = self.link_records.get(row.account.name, {})
            direct_url = str(record.get("direct_url") or "")
            status = self._link_status(row)
            self.tree.insert(
                "",
                tk.END,
                iid=row.key,
                values=(
                    row.order_index + 1,
                    row.account.name,
                    logical_group_from_bookmark_path(row.account.bookmark_path),
                    row.account.bookmark_path,
                    status,
                    mask_sensitive_text(direct_url),
                    "已参与" if row.included else "未参与",
                ),
            )

    def _selected_key(self) -> str:
        selection = self.tree.selection()
        return str(selection[0]) if selection else ""

    def _move_selected(self, direction: int) -> None:
        key = self._selected_key()
        if not key:
            messagebox.showwarning("账号管理", "请先选择账号。", parent=self)
            return
        self.roster_store.move(key, direction)
        self._reload()
        if self.tree.exists(key):
            self.tree.selection_set(key)

    def _set_selected_included(self, included: bool) -> None:
        keys = [str(key) for key in self.tree.selection()]
        if not keys:
            messagebox.showwarning("账号管理", "请先选择账号。", parent=self)
            return
        self.roster_store.set_included_many(keys, included)
        self._reload()
        existing = [key for key in keys if self.tree.exists(key)]
        if existing:
            self.tree.selection_set(existing)

    def _set_filtered_included(self, included: bool) -> None:
        keys = [row.key for row in self._filtered_rows()]
        if not keys:
            messagebox.showinfo("账号管理", "当前筛选没有可处理账号。", parent=self)
            return
        action = "加入" if included else "移出"
        if not messagebox.askyesno("账号管理", f"确认将当前筛选的 {len(keys)} 个账号全部{action}上号列表？", parent=self):
            return
        self.roster_store.set_included_many(keys, included)
        self._reload()
        self.owner._log(f"[账号管理] 当前筛选批量{action}完成 count={len(keys)}")

    def _close(self) -> None:
        self.owner._load_accounts()
        self.destroy()


class LauncherApp(_TK_BASE):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"斗罗大陆H5上号器 - 客户端直登批次版 v{APP_VERSION}")
        w, h = GUI_DEFAULT_WIDTH, GUI_DEFAULT_HEIGHT
        ws = self.winfo_screenwidth()
        hs = self.winfo_screenheight()
        x = (ws - w) // 2
        y = (hs - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(GUI_MIN_WIDTH, GUI_MIN_HEIGHT)

        self.accounts: list[AccountConfig] = []
        self.status_by_key: dict[str, str] = {}
        self.passport_by_key: dict[str, str] = {}
        self.timing_by_key: dict[str, str] = {}
        self.manual_passport_cache: dict[str, str] = {}
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self._log_file = None
        self._log_file_path: Path | None = None
        self.wm_launch_thread: threading.Thread | None = None
        self.wm_action_thread: threading.Thread | None = None
        self.running_processes: list[object] = []
        self.running_processes_lock = threading.Lock()
        self._preserve_background_windows = False
        self._user_data_startup_logs: list[str] = []
        self.user_data_init_result = initialize_user_data_dir(logger=self._user_data_startup_logs.append)
        self.user_data_dir = self.user_data_init_result.user_data_dir
        self.client_batch_store = ClientBatchStore(self.user_data_init_result.sessions_path)
        self.client_direct_bindings: dict[str, ClientDirectRunRecord] = {}
        self.client_direct_bindings_lock = threading.RLock()
        self.is_closing = False

        self.settings_path = tk.StringVar(value=str(self.user_data_init_result.settings_path))
        self.bookmark_path = tk.StringVar(value="")
        self.bookmark_root_name = tk.StringVar(value="账号")
        self.bookmark_root_guid = tk.StringVar(value="")
        self.bookmark_root_path = tk.StringVar(value="")
        self.bookmark_root_parent_path = tk.StringVar(value="")
        self.bookmark_root_display_name = tk.StringVar(value="")
        self.bookmark_file_candidate_var = tk.StringVar(value="")
        self.bookmark_root_candidate_var = tk.StringVar(value="")
        self.bookmark_file_candidates = []
        self.bookmark_root_candidates = []
        self.bookmark_file_candidate_by_label: dict[str, object] = {}
        self.bookmark_root_candidate_by_label: dict[str, object] = {}
        self.level_var = tk.StringVar(value="第一层")
        self.account_var = tk.StringVar(value="")
        self.max_workers_var = tk.IntVar(value=4)
        self.batch_verify_rounds_var = tk.IntVar(value=3)
        self.notice_outside_x_var = tk.DoubleVar(value=0.08)
        self.notice_outside_y_var = tk.DoubleVar(value=0.08)
        self.run_mode_var = tk.StringVar(value=RUN_MODE_CLIENT_DIRECT_LABEL)
        self.run_mode_hint_var = tk.StringVar(value="")
        self.account_source_summary_var = tk.StringVar(
            value="刷新地址账号库尚未加载"
        )
        self.client_direct_auto_enter_var = tk.BooleanVar(value=True)
        self.client_direct_concurrency_var = tk.IntVar(value=CLIENT_DIRECT_CONCURRENCY_MIN)
        self.client_direct_login_scope_var = tk.StringVar(value=CLIENT_DIRECT_LOGIN_SCOPE_PENDING)
        self.client_direct_base_port_var = tk.IntVar(value=CLIENT_DIRECT_CDP_PORT)
        self.auto_replace_speed_panel_var = tk.BooleanVar(value=True)
        self.custom_speed_panel_enabled_var = tk.BooleanVar(value=True)
        self.speed_panel_debug_var = tk.BooleanVar(value=False)
        self.speed_panel_remove_original_toggle_var = tk.BooleanVar(value=True)
        self.block_browser_context_menu_var = tk.BooleanVar(value=False)
        self.speed_engine_var = tk.StringVar(value="timer_hook")
        self.default_speed_rate_var = tk.StringVar(value="1.0")
        self.speed_rate_hotkeys: list[dict[str, object]] = []
        self.speed_hook_stage_var = tk.StringVar(value="after_game_ready")
        self.speed_panel_position_var = tk.StringVar(value="左上角")
        self.client_direct_port_range_var = tk.StringVar(value="9222 ~ 9222")
        self.client_direct_batch_count_var = tk.StringVar(value="本批数量：1")
        self.client_direct_batch_status_var = tk.StringVar(
            value="绑定=0 | 存活=0 | 已关闭=0 | CDP不可用=0 | 窗口失效=0 | 绑定异常=0"
        )
        self.client_direct_batch_select_var = tk.StringVar(value="无可用批次")
        self.client_direct_batch_display_id_map: dict[str, str] = {}
        self.client_speed_control_rate_var = tk.StringVar(value="1.0")
        self.client_speed_control_scope_var = tk.StringVar(value=CLIENT_SPEED_SCOPE_CURRENT_BATCH)
        self.client_speed_control_status_var = tk.StringVar(value="成功 0 / 失败 0 / 跳过 0 / 停止 0")
        self._speed_hotkey_listener = WindowsSpeedHotkey(
            self._on_speed_rate_hotkey,
            log=lambda message: self._queue_log(f"[加速器快捷键] {message}"),
        )
        self._speed_hotkey_toggle_lock = threading.Lock()
        self.wm_game_path_var = tk.StringVar(value="")
        self.wm_game_status_var = tk.StringVar(value=_format_game_program_status(""))
        self.wm_game_hint_var = tk.StringVar(value=_game_program_hint_text())
        self.wm_game_path_var.trace_add("write", lambda *_: self._sync_game_program_status())
        self.wm_launch_count_var = tk.IntVar(value=31)
        self.wm_launch_interval_var = tk.IntVar(value=300)
        self.wm_auto_tile_after_launch_var = tk.BooleanVar(value=True)
        self.wm_auto_rename_after_tile_var = tk.BooleanVar(value=True)
        self.wm_title_template_var = tk.StringVar(value="斗罗大陆H5-{index}号")
        self.wm_tile_mode_var = tk.StringVar(value=WM_TILE_MODE_FIXED)
        self.wm_window_width_var = tk.StringVar(value="320")
        self.wm_window_height_var = tk.StringVar(value="540")
        self.wm_start_x_var = tk.IntVar(value=250)
        self.wm_start_y_var = tk.IntVar(value=0)
        self.wm_offset_x_var = tk.IntVar(value=320)
        self.wm_offset_y_var = tk.IntVar(value=525)
        self.wm_per_row_var = tk.IntVar(value=8)
        self.wm_prevent_overflow_var = tk.BooleanVar(value=True)
        self.wm_repair_slot_var = tk.IntVar(value=11)
        self.wm_fixed_mode_settings = FixedModeSettings()
        self.wm_row_count_mode_settings = RowCountModeSettings()
        self.wm_current_tile_mode_key = TILE_MODE_FIXED

        self._apply_settings_defaults()
        self._build_widgets()
        self._load_window_manager_settings()
        self._load_client_direct_sessions()
        self._register_saved_speed_rate_hotkeys()
        self._log_bookmark_startup_state()
        self._load_accounts()
        self.after(100, self._drain_ui_queue)
        self._load_default_config_if_present()
        self._log_admin_status_warning()
        self._log_startup_dm_environment()
        self._log_user_data_startup_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._enable_game_path_drag_drop)

    def _log_user_data_startup_state(self) -> None:
        result = getattr(self, "user_data_init_result", None)
        if result is None:
            return
        self._log(f"[配置] 当前用户数据目录：{result.user_data_dir}")
        self._log(f"[配置] automation_settings.json：{result.settings_path}")
        self._log(f"[配置] client_direct_sessions.json：{result.sessions_path}")
        if result.settings_merged_defaults:
            self._log("[配置] 已补齐模板新增字段，用户已有配置未覆盖。")
        for message in getattr(self, "_user_data_startup_logs", []) or []:
            self._log(message)

    def _log_or_defer_startup(self, message: str) -> None:
        if hasattr(self, "log_text"):
            self._log(message)
        else:
            self._user_data_startup_logs.append(str(message))

    def _apply_settings_defaults(self) -> None:
        try:
            settings = load_settings(self.settings_path.get())
        except Exception:
            return
        if settings.bookmark_file:
            self.bookmark_path.set(settings.bookmark_file)
        else:
            selection = select_bookmark_candidate_for_startup("", find_bookmark_file_candidates())
            if selection.candidate is not None:
                self.bookmark_path.set(selection.candidate.path)
        self.bookmark_root_name.set(settings.bookmark_root_name)
        self.bookmark_root_guid.set(settings.bookmark_root_guid)
        self.bookmark_root_path.set(settings.bookmark_root_path)
        self.bookmark_root_parent_path.set(settings.bookmark_root_parent_path)
        self.bookmark_root_display_name.set(settings.bookmark_root_display_name)
        self.max_workers_var.set(settings.max_workers)
        self.notice_outside_x_var.set(settings.notice_close_outside_ratio[0])
        self.notice_outside_y_var.set(settings.notice_close_outside_ratio[1])
        self.auto_replace_speed_panel_var.set(bool(settings.auto_replace_speed_panel))
        self.custom_speed_panel_enabled_var.set(bool(settings.custom_speed_panel_enabled))
        self.speed_panel_debug_var.set(bool(getattr(settings, "speed_panel_debug", False)))
        self.speed_panel_remove_original_toggle_var.set(bool(getattr(settings, "speed_panel_remove_original_toggle", True)))
        self.block_browser_context_menu_var.set(False)
        self.speed_engine_var.set(str(settings.speed_engine or "timer_hook"))
        self.default_speed_rate_var.set(str(float(settings.default_speed_rate or 1.0)))
        raw_hotkeys = getattr(settings, "speed_rate_hotkeys", [])
        try:
            self.speed_rate_hotkeys = [
                {"rate": item.rate, "hotkey": item.spec.text}
                for item in normalize_speed_hotkey_bindings(raw_hotkeys)
            ]
        except ValueError as exc:
            self.speed_rate_hotkeys = []
            self._log_or_defer_startup(f"[加速器快捷键] 已忽略无效的多倍率快捷键配置：{mask_sensitive_text(exc)}")
        if str(getattr(settings, "speed_panel_hotkey", "") or "").strip() and not self.speed_rate_hotkeys:
            self._log_or_defer_startup("[加速器快捷键] 检测到旧 speed_panel_hotkey；为避免隐藏触发，未注册旧组合，请在“快捷键设置”中重新配置。")
        self.speed_hook_stage_var.set(str(settings.speed_hook_stage or "after_game_ready"))
        self.speed_panel_position_var.set("左上角")

    def _bookmark_candidates_summary(self) -> str:
        candidates = find_bookmark_file_candidates()
        if not candidates:
            return "未检测到 Chrome / Edge Bookmarks 候选"
        return "；".join(
            candidate.display_name
            for candidate in candidates
        )

    def _log_bookmark_startup_state(self) -> None:
        try:
            settings = load_settings(self.settings_path.get())
        except Exception as exc:
            self._log(f"收藏夹配置读取失败：{self.settings_path.get()}，{exc}")
            return

        saved_path = str(settings.bookmark_file or "").strip()
        if saved_path:
            info = describe_bookmark_file(saved_path)
            if Path(saved_path).is_file():
                self._log(
                    f"已使用上次保存的收藏夹路径：{saved_path} "
                    f"({info.browser}, profile={info.profile or '未知'})"
                )
            else:
                self._log(
                    f"上次保存的收藏夹路径不存在或不可读：{saved_path}。"
                    f"请重新选择 Bookmarks 文件。候选：{self._bookmark_candidates_summary()}"
                )
            return

        candidates = find_bookmark_file_candidates()
        selection = select_bookmark_candidate_for_startup("", candidates)
        if selection.candidate is not None:
            self.bookmark_path.set(selection.candidate.path)
            self._save_bookmark_settings(selection.candidate.path)
            self._log(
                f"当前未保存收藏夹路径，已自动选择唯一候选："
                f"{selection.candidate.display_name}: {selection.candidate.path}"
            )
            return

        self._log(
            "当前未保存收藏夹路径。"
            f"请点击“自动查找收藏夹”后选择候选；检测到候选：{self._bookmark_candidates_summary()}"
        )

    def _save_bookmark_settings(self, bookmark_file: str) -> None:
        bookmark_path = str(bookmark_file or "").strip()
        if not bookmark_path:
            return
        path = Path(self.settings_path.get())
        info = describe_bookmark_file(bookmark_path)
        try:
            data = {}
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    data = {}
            data["bookmark_file"] = bookmark_path
            data["bookmark_browser"] = info.browser
            data["bookmark_profile"] = info.profile
            data["bookmark_root_name"] = self.bookmark_root_name.get().strip() or data.get("bookmark_root_name", "账号")
            data["bookmark_root_guid"] = self.bookmark_root_guid.get().strip()
            data["bookmark_root_path"] = self.bookmark_root_path.get().strip()
            data["bookmark_root_parent_path"] = self.bookmark_root_parent_path.get().strip()
            data["bookmark_root_display_name"] = self.bookmark_root_display_name.get().strip()
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._log(
                f"已保存收藏夹配置：browser={info.browser}, "
                f"profile={info.profile or '未知'}, path={bookmark_path}"
            )
        except Exception as exc:
            self._log(f"保存收藏夹配置失败：{exc}")

    def _build_widgets(self) -> None:
        root = ttk.Frame(self, padding=(10, 6, 10, 4))
        root.pack(fill=tk.BOTH, expand=True)

        # ===== 1. 窗口管理 =====
        window_frame = ttk.LabelFrame(root, text="窗口管理", padding=4)
        window_frame.pack(fill=tk.X, pady=(0, 6))
        window_frame.columnconfigure(0, weight=1)
        window_frame.columnconfigure(1, weight=1)

        self.wm_game_path_row = ttk.Frame(window_frame)
        self.wm_game_path_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))
        self.wm_game_path_row.columnconfigure(1, weight=1)
        ttk.Label(self.wm_game_path_row, text="游戏程序：", width=10, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 4)
        )
        self.wm_game_path_box = ttk.Frame(self.wm_game_path_row)
        self.wm_game_path_box.grid(row=0, column=1, sticky="ew")
        self.wm_game_path_box.columnconfigure(0, weight=1)
        self.wm_game_path_entry = ttk.Entry(self.wm_game_path_box, textvariable=self.wm_game_path_var)
        self.wm_game_path_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            self.wm_game_path_row,
            text="选择游戏图标/程序",
            width=18,
            command=self._pick_game_path,
        ).grid(row=0, column=2, sticky="ew", padx=(8, 0))
        ttk.Label(self.wm_game_path_row, text="标题模板").grid(row=0, column=3, padx=(12, 4))
        ttk.Entry(self.wm_game_path_row, textvariable=self.wm_title_template_var, width=22).grid(row=0, column=4)
        ttk.Checkbutton(self.wm_game_path_row, text="自动编号标题", variable=self.wm_auto_rename_after_tile_var).grid(row=0, column=5, padx=(8, 0))
        ttk.Checkbutton(self.wm_game_path_row, text="禁止超宽", variable=self.wm_prevent_overflow_var).grid(row=0, column=6, padx=(8, 0))

        self.wm_compact_frame = ttk.Frame(window_frame)
        self.wm_compact_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4)
        self.wm_compact_frame.columnconfigure(0, weight=1)

        self.wm_layout_frame = ttk.Frame(self.wm_compact_frame)
        self.wm_layout_frame.grid(row=0, column=0, sticky="ew")
        ttk.Label(self.wm_layout_frame, text="排列方式", width=10, anchor="w").pack(side=tk.LEFT, padx=(0, 4))
        self.wm_tile_mode_combo = ttk.Combobox(
            self.wm_layout_frame,
            textvariable=self.wm_tile_mode_var,
            values=(WM_TILE_MODE_FIXED, WM_TILE_MODE_ROW_COUNT),
            state="readonly",
            width=10,
        )
        self.wm_tile_mode_combo.pack(side=tk.LEFT, padx=(0, 8))
        self.wm_tile_mode_combo.bind("<<ComboboxSelected>>", lambda _: self._wm_on_tile_mode_changed())
        self.wm_fixed_param_widgets = []
        self.wm_row_param_widgets = []

        def add_widget(widget, row: int, column: int, **grid_options):
            widget.grid(row=row, column=column, **grid_options)
            return widget

        fixed_specs = (
            ("每行数量", "spin", self.wm_per_row_var, 1, 99),
            ("窗口宽度", "entry", self.wm_window_width_var, None, None),
            ("窗口高度", "entry", self.wm_window_height_var, None, None),
            ("起点X", "spin", self.wm_start_x_var, -5000, 5000),
            ("起点Y", "spin", self.wm_start_y_var, -5000, 5000),
            ("横向偏移", "spin", self.wm_offset_x_var, -5000, 5000),
            ("纵向偏移", "spin", self.wm_offset_y_var, -5000, 5000),
        )
        for label, kind, variable, min_value, max_value in fixed_specs:
            label_widget = ttk.Label(self.wm_layout_frame, text=label)
            label_widget.pack(side=tk.LEFT, padx=(0, 3))
            if kind == "entry":
                input_widget = ttk.Entry(self.wm_layout_frame, textvariable=variable, width=5)
            else:
                input_widget = ttk.Spinbox(self.wm_layout_frame, from_=min_value, to=max_value, increment=1,
                                           textvariable=variable, width=5)
            input_widget.pack(side=tk.LEFT, padx=(0, 7))
            self.wm_fixed_param_widgets.extend((label_widget, input_widget))

        # ===== 2. 工作模式 =====
        work_mode_frame = ttk.LabelFrame(root, text="工作模式", padding=4)
        work_mode_frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(work_mode_frame, text="工作模式").pack(side=tk.LEFT, padx=(4, 8))
        self.run_mode_client_btn = tk.Radiobutton(
            work_mode_frame,
            text=RUN_MODE_CLIENT_DIRECT_LABEL,
            variable=self.run_mode_var,
            value=RUN_MODE_CLIENT_DIRECT_LABEL,
            indicatoron=False,
            width=18,
            padx=10,
            pady=4,
            command=self._on_run_mode_changed,
        )
        self.run_mode_client_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(work_mode_frame, textvariable=self.run_mode_hint_var, foreground="#996600").pack(side=tk.LEFT)

        # ===== 3. 账号配置与快捷键 =====
        account_config_frame = ttk.LabelFrame(root, text="账号配置", padding=4)
        account_config_frame.pack(fill=tk.X, pady=(0, 6))

        account_row = ttk.Frame(account_config_frame)
        account_row.pack(fill=tk.X, pady=3)
        ttk.Label(account_row, text="账号来源：刷新地址账号库").pack(side=tk.LEFT, padx=(4, 12))
        ttk.Button(account_row, text="账号管理", width=12, command=self._open_login_account_manager).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.refresh_address_btn = ttk.Button(
            account_row, text="刷新地址", width=12, command=self._open_refresh_address_dialog
        )
        self.refresh_address_btn.pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(account_row, textvariable=self.account_source_summary_var, foreground="#666666").pack(side=tk.LEFT)

        # ===== 4. 运行 =====
        run_frame = ttk.LabelFrame(root, text="当前模式运行区", padding=4)
        run_frame.pack(fill=tk.X, pady=(0, 6))

        # 选择行
        select_row = ttk.Frame(run_frame)
        select_row.pack(fill=tk.X, pady=(0, 3))

        ttk.Label(select_row, text="层级").pack(side=tk.LEFT, padx=(2, 4))
        self.level_box = ttk.Combobox(select_row, textvariable=self.level_var,
                                       values=("全部", *SELECTABLE_LEVELS), width=10, state="readonly")
        self.level_box.pack(side=tk.LEFT, padx=(0, 4))
        self.level_box.bind("<<ComboboxSelected>>", lambda _: self._on_level_changed())
        self.group_settings_btn = ttk.Button(
            select_row,
            text="分组设置",
            width=10,
            command=self._open_account_group_settings,
        )
        self.group_settings_btn.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(select_row, text="账号").pack(side=tk.LEFT, padx=(0, 4))
        self.account_box = ttk.Combobox(select_row, textvariable=self.account_var, width=28, state="readonly")
        self.account_box.pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(
            select_row,
            text="账号范围用于决定本批客户端数量和登录账号。",
            foreground="#666666",
        ).pack(side=tk.LEFT, padx=(0, 12))

        self.client_direct_run_frame = ttk.LabelFrame(run_frame, text="客户端直登批次", padding=4)
        client_direct_frame = self.client_direct_run_frame
        client_direct_frame.pack(fill=tk.X, pady=(0, 4))
        client_direct_frame.columnconfigure(0, weight=1)

        self.client_direct_top_row = ttk.Frame(client_direct_frame)
        self.client_direct_top_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.client_direct_auto_enter_check = ttk.Checkbutton(
            self.client_direct_top_row,
            text="自动进入游戏",
            variable=self.client_direct_auto_enter_var,
        )
        self.client_direct_auto_enter_check.pack(side=tk.LEFT, padx=(0, 18))
        self.client_direct_auto_enter_check.state(["disabled"])
        ttk.Label(self.client_direct_top_row, text="并发数：").pack(side=tk.LEFT, padx=(0, 4))
        self.client_direct_concurrency_spin = ttk.Spinbox(
            self.client_direct_top_row,
            from_=CLIENT_DIRECT_CONCURRENCY_MIN,
            to=CLIENT_DIRECT_CONCURRENCY_MAX,
            increment=1,
            textvariable=self.client_direct_concurrency_var,
            width=4,
            command=self._client_direct_concurrency,
        )
        self.client_direct_concurrency_spin.pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(self.client_direct_top_row, text="登录范围：").pack(side=tk.LEFT, padx=(0, 4))
        self.client_direct_login_scope_box = ttk.Combobox(
            self.client_direct_top_row,
            textvariable=self.client_direct_login_scope_var,
            values=CLIENT_DIRECT_LOGIN_SCOPE_CHOICES,
            width=10,
            state="readonly",
        )
        self.client_direct_login_scope_box.pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(self.client_direct_top_row, text="预计端口范围：").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(self.client_direct_top_row, textvariable=self.client_direct_port_range_var, foreground="#666666").pack(
            side=tk.LEFT, padx=(0, 18)
        )
        ttk.Label(self.client_direct_top_row, textvariable=self.client_direct_batch_count_var, foreground="#666666").pack(
            side=tk.LEFT, padx=(0, 22)
        )
        ttk.Label(self.client_direct_top_row, text="当前批次：").pack(side=tk.LEFT, padx=(0, 4))
        self.client_direct_batch_box = ttk.Combobox(
            self.client_direct_top_row,
            textvariable=self.client_direct_batch_select_var,
            width=42,
            state="readonly",
        )
        self.client_direct_batch_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.client_direct_batch_box.bind("<<ComboboxSelected>>", lambda _: self._on_client_direct_batch_selected())

        self.client_direct_batch_row = ttk.Frame(client_direct_frame)
        self.client_direct_batch_row.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.client_direct_delete_batch_btn = ttk.Button(
            self.client_direct_batch_row,
            text="删除当前批次",
            width=14,
            command=self._delete_client_direct_current_batch,
        )
        self.client_direct_delete_batch_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.client_direct_cleanup_batches_btn = ttk.Button(
            self.client_direct_batch_row,
            text="清理失效批次",
            width=14,
            command=self._cleanup_dead_client_direct_batches,
        )
        self.client_direct_cleanup_batches_btn.pack(side=tk.LEFT, padx=(0, 22))
        ttk.Label(self.client_direct_batch_row, text="状态统计：").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(
            self.client_direct_batch_row,
            textvariable=self.client_direct_batch_status_var,
            foreground="#006666",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.client_direct_action_row_1 = ttk.Frame(client_direct_frame)
        self.client_direct_action_row_1.grid(row=2, column=0, sticky="ew")
        client_direct_buttons = (
            ("准备客户端", 14, self._prepare_client_direct_current_scope, 0, 0),
            ("一键准备并登录", 16, self._prepare_arrange_login_client_direct_current_scope, 0, 1),
            ("追加准备", 12, self._append_client_direct_current_scope, 0, 2),
            ("排列本批客户端", 16, self._arrange_prepared_client_direct_current_scope, 0, 3),
            ("执行登录并进入游戏", 18, self._login_prepared_client_direct_current_scope, 0, 4),
        )
        for text, width, command, row, column in client_direct_buttons:
            ttk.Button(self.client_direct_action_row_1, text=text, width=width, command=command).grid(
                row=row, column=column, sticky="ew", padx=2, pady=1
            )

        self.client_direct_action_row_2 = ttk.Frame(client_direct_frame)
        self.client_direct_action_row_2.grid(row=3, column=0, sticky="ew")
        client_direct_repair_buttons = (
            ("修复本批窗口", 14, self._repair_client_direct_current_batch, 0, 0),
            ("识别本地客户端", 16, self._identify_local_client_direct_clients, 0, 1),
            ("清空本批绑定", 14, self._clear_client_direct_current_batch, 0, 2),
            ("关闭本批客户端", 14, self._close_client_direct_current_batch, 0, 3),
        )
        for text, width, command, row, column in client_direct_repair_buttons:
            ttk.Button(self.client_direct_action_row_2, text=text, width=width, command=command).grid(
                row=row, column=column, sticky="ew", padx=2, pady=1
            )
        self.client_direct_stop_btn = tk.Button(
            self.client_direct_action_row_2,
            text="停止任务",
            width=12,
            fg="#cc0000",
            command=self._stop_tasks,
            font=("", 9, "bold"),
        )
        self.client_direct_stop_btn.grid(row=0, column=4, sticky="ew", padx=2, pady=1)

        self.client_speed_control_row = ttk.Frame(client_direct_frame)
        self.client_speed_control_row.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(self.client_speed_control_row, text="加速总控：").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(self.client_speed_control_row, text="倍率").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(self.client_speed_control_row, textvariable=self.client_speed_control_rate_var, width=8).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(
            self.client_speed_control_row,
            text="应用",
            width=8,
            command=self._apply_client_speed_control,
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            self.client_speed_control_row,
            text="恢复 1.0",
            width=10,
            command=lambda: self._apply_client_speed_control(rate_override=1.0),
        ).pack(side=tk.LEFT, padx=(0, 8))
        for preset in ("2", "5", "50", "500"):
            ttk.Button(
                self.client_speed_control_row,
                text=preset,
                width=5,
                command=lambda value=preset: self._apply_client_speed_control(rate_override=float(value)),
            ).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(
            self.client_speed_control_row,
            text="快捷键设置",
            width=12,
            command=self._open_speed_hotkey_settings,
        ).pack(side=tk.LEFT, padx=(5, 3))
        ttk.Label(self.client_speed_control_row, text="作用范围").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Combobox(
            self.client_speed_control_row,
            textvariable=self.client_speed_control_scope_var,
            values=CLIENT_SPEED_SCOPE_CHOICES,
            width=12,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(
            self.client_speed_control_row,
            textvariable=self.client_speed_control_status_var,
            foreground="#006666",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._content_area = ttk.Frame(root)
        self._content_area.pack(fill=tk.BOTH, expand=True)
        self._content_area.columnconfigure(0, weight=1)
        self._content_area.rowconfigure(0, weight=1)
        self._content_area.rowconfigure(1, weight=0, minsize=LOG_PANEL_COLLAPSED_HEIGHT)

        # ===== 4. 账号列表 =====
        self._table_frame_m1 = ttk.LabelFrame(self._content_area, text="账号列表 / 当前账号来源", padding=2)
        self.tree = ttk.Treeview(self._table_frame_m1, columns=ACCOUNT_TABLE_COLUMNS, show="headings", height=10, selectmode="extended")
        for column in ACCOUNT_TABLE_COLUMNS:
            self.tree.heading(column, text=ACCOUNT_TABLE_HEADINGS[column])
            self.tree.column(column, **ACCOUNT_TABLE_COLUMNS_CONFIG[column])
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self._table_frame_m1, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.tag_configure("running", foreground="#0066cc")
        self.tree.tag_configure("success", foreground="#008800")
        self.tree.tag_configure("failed", foreground="#cc0000")
        self.tree.tag_configure("retry", foreground="#cc6600")
        self.tree.tag_configure("skip", foreground="#888888")

        # 初始显示方式一表格
        self._table_frame_m1.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

        # ===== 5. 日志 =====
        self.log_panel_expanded = tk.BooleanVar(value=False)
        self._log_outer = ttk.Frame(self._content_area, padding=2)
        self._log_outer.configure(height=LOG_PANEL_COLLAPSED_HEIGHT)
        self._log_outer.grid_propagate(False)
        self._log_outer.columnconfigure(0, weight=1)
        self._log_outer.rowconfigure(0, weight=0)
        self._log_outer.rowconfigure(1, weight=1)
        self._log_outer.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        log_header = ttk.Frame(self._log_outer)
        log_header.grid(row=0, column=0, sticky="ew")
        ttk.Label(log_header, text="日志").pack(side=tk.LEFT, padx=(2, 8))
        self.log_dir_btn = ttk.Button(log_header, text="打开日志目录", command=self._open_log_dir)
        self.log_dir_btn.pack(side=tk.RIGHT, padx=2)
        self.log_clear_btn = ttk.Button(log_header, text="清空日志", command=self._clear_log_text)
        self.log_clear_btn.pack(side=tk.RIGHT, padx=2)
        self.log_copy_btn = ttk.Button(log_header, text="复制日志", command=self._copy_log_text)
        self.log_copy_btn.pack(side=tk.RIGHT, padx=2)
        self.log_toggle_btn = ttk.Button(log_header, text="展开日志", command=self._toggle_log_panel)
        self.log_toggle_btn.pack(side=tk.RIGHT, padx=2)

        self._log_text_frame = ttk.Frame(self._log_outer)
        self._log_text_frame.grid(row=1, column=0, sticky="nsew")
        self._log_text_frame.columnconfigure(0, weight=1)
        self._log_text_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(self._log_text_frame, height=LOG_TEXT_VISIBLE_LINES, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self._sync_log_panel_visibility()

        # ===== 6. 底部状态栏 =====
        status_frame = ttk.Frame(root, relief="sunken", padding=(8, 3))
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_left = tk.StringVar(value="就绪")
        self._status_mid = tk.StringVar(value=f"当前模式：{RUN_MODE_CLIENT_DIRECT_LABEL}")
        self._status_right = tk.StringVar(value="并发：1")
        ttk.Label(status_frame, textvariable=self._status_left).pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self._status_mid).pack(side=tk.LEFT, padx=(40, 0))
        ttk.Label(status_frame, textvariable=self._status_right).pack(side=tk.RIGHT)
        self._on_run_mode_changed()

    def _toggle_debug(self) -> None:
        if not hasattr(self, "debug_frame") or not hasattr(self, "_debug_visible"):
            return
        if self._debug_visible.get():
            self.debug_frame.pack_forget()
            self._debug_visible.set(False)
            self._debug_toggle_btn.configure(text="▸ 调试")
        else:
            self.debug_frame.pack(fill=tk.X, pady=(0, 8), before=self._debug_toggle_btn)
            self._debug_visible.set(True)
            self._debug_toggle_btn.configure(text="▾ 调试")

    def _toggle_log_panel(self) -> None:
        self.log_panel_expanded.set(not bool(self.log_panel_expanded.get()))
        self._sync_log_panel_visibility()

    def _sync_log_panel_visibility(self) -> None:
        if not hasattr(self, "_log_outer") or not hasattr(self, "_log_text_frame"):
            return
        expanded = bool(self.log_panel_expanded.get())
        height = LOG_PANEL_EXPANDED_HEIGHT if expanded else LOG_PANEL_COLLAPSED_HEIGHT
        self._content_area.rowconfigure(1, weight=0, minsize=height)
        self._log_outer.configure(height=height)
        if expanded:
            self._log_text_frame.grid(row=1, column=0, sticky="nsew")
            self.log_toggle_btn.configure(text="收起日志")
            self.log_text.see(tk.END)
        else:
            self._log_text_frame.grid_remove()
            self.log_toggle_btn.configure(text="展开日志")

    def _copy_log_text(self) -> None:
        try:
            text = self.log_text.get("1.0", tk.END).strip()
            self.clipboard_clear()
            self.clipboard_append(text)
            self._status_left.set("日志已复制")
        except Exception as exc:
            messagebox.showwarning("复制日志", f"复制日志失败：{exc}")

    def _clear_log_text(self) -> None:
        try:
            self.log_text.delete("1.0", tk.END)
            self._status_left.set("日志已清空")
        except Exception as exc:
            messagebox.showwarning("清空日志", f"清空日志失败：{exc}")

    def _on_run_mode_changed(self) -> None:
        self.run_mode_var.set(RUN_MODE_CLIENT_DIRECT_LABEL)
        self.run_mode_hint_var.set(RUN_MODE_CLIENT_DIRECT_HINT)
        self._status_mid.set(f"当前模式：{RUN_MODE_CLIENT_DIRECT_LABEL}")
        auto_text = "自动进入游戏" if self._client_direct_auto_enter_game() else "停在公告/进入游戏前"
        self._log(f"已选择{RUN_MODE_CLIENT_DIRECT_LABEL}：{RUN_MODE_CLIENT_DIRECT_HINT}，{auto_text}。")
        self._sync_work_mode_visibility()
        self._sync_account_source_controls()
        self._sync_client_direct_controls()
        self._sync_work_mode_buttons()

    def _open_refresh_address_dialog(self) -> None:
        dialog = getattr(self, "_refresh_address_dialog", None)
        try:
            if dialog is not None and bool(dialog.winfo_exists()):
                dialog.lift()
                dialog.focus_set()
                return
        except Exception:
            pass
        self._refresh_address_dialog = RefreshAddressDialog(self)
        self._log(f"[刷新地址] 已打开弹窗，数据目录：{default_refresh_data_dir()}")

    def _open_login_account_manager(self) -> None:
        dialog = getattr(self, "_login_account_manager_dialog", None)
        try:
            if dialog is not None and bool(dialog.winfo_exists()):
                dialog.lift()
                dialog.focus_set()
                return
        except Exception:
            pass
        self._login_account_manager_dialog = LoginAccountManagerDialog(self)
        self._log("[账号管理] 已打开直登账号管理。")

    def _client_direct_account_with_local_link(self, account: AccountConfig) -> AccountConfig:
        try:
            resolved = resolve_client_direct_url_for_account(account, ensure_refresh_data_dir().direct_links_path)
        except Exception as exc:
            self._log(f"[客户端直登] 读取本地直登链接库失败：{mask_sensitive_text(redact_sensitive_text(exc))}")
            return account
        if resolved.status == "found":
            self._log(f"[客户端直登] {account.display_name} 使用本地直登链接库：name={resolved.name}")
            return replace(account, url=resolved.direct_url)
        if resolved.status == "expired" and resolved.direct_url:
            self._log(f"[客户端直登] {account.display_name} {resolved.message}：name={resolved.name}，允许继续尝试。")
            return replace(account, url=resolved.direct_url)
        self._log(f"[客户端直登] {account.display_name} {resolved.message}；将保留当前收藏夹链接。")
        return account

    def _client_direct_accounts_with_local_links(self, accounts: list[AccountConfig]) -> list[AccountConfig]:
        return [LauncherApp._client_direct_account_with_local_link(self, account) for account in accounts]

    def _is_client_direct_run_mode(self) -> bool:
        return True

    def _sync_client_direct_controls(self) -> None:
        check = getattr(self, "client_direct_auto_enter_check", None)
        if check is not None:
            check.state(["!disabled"])
        self._sync_client_direct_port_range()

    def _sync_work_mode_visibility(self) -> None:
        client_frame = getattr(self, "client_direct_run_frame", None)
        if client_frame is not None:
            client_frame.pack(fill=tk.X, pady=(0, 4))
        foreground_frame = getattr(self, "foreground_run_frame", None)
        if foreground_frame is not None:
            foreground_frame.pack_forget()
        for widget in getattr(self, "wm_legacy_launch_grid_widgets", ()):
            widget.grid_remove()
        launch_btn = getattr(self, "wm_launch_btn", None)
        if launch_btn is not None:
            launch_btn.pack_forget()

    def _sync_work_mode_buttons(self) -> None:
        button = getattr(self, "run_mode_client_btn", None)
        if button is None:
            return
        try:
            button.configure(relief=tk.SUNKEN, bg="#d9edf7", activebackground="#d9edf7")
        except Exception:
            pass

    def _sync_account_source_controls(self) -> None:
        if hasattr(self, "group_settings_btn"):
            self.group_settings_btn.configure(state=tk.NORMAL)
    def _client_direct_auto_enter_game(self) -> bool:
        var = getattr(self, "client_direct_auto_enter_var", None)
        if var is None:
            return True
        try:
            return bool(var.get())
        except Exception:
            return True

    def _client_direct_concurrency(self) -> int:
        var = getattr(self, "client_direct_concurrency_var", None)
        if var is None:
            return CLIENT_DIRECT_CONCURRENCY_MIN
        try:
            value = int(var.get())
        except Exception:
            value = CLIENT_DIRECT_CONCURRENCY_MIN
        value = max(CLIENT_DIRECT_CONCURRENCY_MIN, min(CLIENT_DIRECT_CONCURRENCY_MAX, value))
        try:
            var.set(value)
        except Exception:
            pass
        return value

    def _client_direct_base_port(self) -> int:
        try:
            value = int(self.client_direct_base_port_var.get())
        except Exception:
            value = CLIENT_DIRECT_CDP_PORT
        value = max(1024, min(65500, value))
        try:
            self.client_direct_base_port_var.set(value)
        except Exception:
            pass
        return value

    def _client_speed_panel_options(self) -> dict[str, object]:
        try:
            default_rate = float(self.default_speed_rate_var.get())
        except Exception:
            default_rate = 1.0
        if default_rate <= 0:
            default_rate = 1.0
        try:
            self.default_speed_rate_var.set(str(default_rate))
        except Exception:
            pass
        return {
            "auto_replace_speed_panel": _safe_bool_var(self, "auto_replace_speed_panel_var", True),
            "custom_speed_panel_enabled": _safe_bool_var(self, "custom_speed_panel_enabled_var", True),
            "speed_engine": _safe_string_var(self, "speed_engine_var", "timer_hook"),
            "default_speed_rate": default_rate,
            "speed_hook_stage": _safe_string_var(self, "speed_hook_stage_var", "after_game_ready"),
            "speed_panel_position": "left_top",
            "speed_panel_left": 12,
            "speed_panel_top": 12,
            "speed_panel_debug": _safe_bool_var(self, "speed_panel_debug_var", False),
            "speed_panel_remove_original_toggle": _safe_bool_var(self, "speed_panel_remove_original_toggle_var", True),
            "block_browser_context_menu": False,
        }

    def _save_speed_rate_hotkeys(self, rows: list[dict[str, object]]) -> None:
        path = Path(self.settings_path.get())
        data: dict[str, object] = {}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                data = loaded
        data["speed_rate_hotkeys"] = rows
        data["speed_panel_hotkey"] = ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _register_saved_speed_rate_hotkeys(self) -> None:
        rows = list(getattr(self, "speed_rate_hotkeys", []) or [])
        if not rows:
            return
        ok, message = self._speed_hotkey_listener.replace(rows)
        self._log(f"[加速器快捷键] {message}")
        if not ok:
            self.after(0, lambda: messagebox.showerror("加速器快捷键", message))

    def _open_speed_hotkey_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.withdraw()
        dialog.title("多倍率快捷键设置")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="目标倍率").grid(row=0, column=0, padx=5, pady=(0, 6))
        ttk.Label(frame, text="修饰键").grid(row=0, column=1, padx=5, pady=(0, 6))
        ttk.Label(frame, text="主键").grid(row=0, column=3, padx=5, pady=(0, 6))
        defaults = list(getattr(self, "speed_rate_hotkeys", []) or [])
        fallback = ((3.0, "Alt", "2"), (6.0, "Alt", "3"), (20.0, "Alt", "4"), (50.0, "Alt", "5"))
        variables = []
        modifiers = ("无", "Ctrl", "Alt", "Shift", "Ctrl+Alt", "Ctrl+Shift", "Alt+Shift", "Ctrl+Alt+Shift")
        main_keys = tuple(chr(value) for value in range(ord("A"), ord("Z") + 1)) + tuple(str(value) for value in range(10)) + tuple(f"F{value}" for value in range(1, 13))
        for index in range(4):
            rate, modifier, main_key = fallback[index]
            if index < len(defaults):
                rate = float(defaults[index]["rate"])
                parts = str(defaults[index]["hotkey"]).split("+")
                main_key = parts[-1]
                modifier = "+".join(parts[:-1]) or "无"
            rate_var, modifier_var, main_var = tk.StringVar(value=str(rate)), tk.StringVar(value=modifier), tk.StringVar(value=main_key)
            variables.append((rate_var, modifier_var, main_var))
            ttk.Entry(frame, textvariable=rate_var, width=10).grid(row=index + 1, column=0, padx=5, pady=4)
            ttk.Combobox(frame, textvariable=modifier_var, values=modifiers, width=16, state="readonly").grid(row=index + 1, column=1, padx=5, pady=4)
            ttk.Label(frame, text="+").grid(row=index + 1, column=2, padx=2, pady=4)
            ttk.Combobox(frame, textvariable=main_var, values=main_keys, width=8, state="normal").grid(row=index + 1, column=3, padx=5, pady=4)
        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=4, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="确定", command=lambda: LauncherApp._confirm_speed_hotkey_settings(self, dialog, variables)).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=4)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        _position_dialog_relative_to_owner(dialog, self)
        dialog.deiconify()
        dialog.lift()
        dialog.focus_set()
        dialog.grab_set()
        dialog.wait_window()

    def _confirm_speed_hotkey_settings(self, dialog, variables) -> bool:
        try:
            rows = [
                {"rate": float(rate_var.get()), "hotkey": compose_speed_hotkey(modifier_var.get(), main_var.get())}
                for rate_var, modifier_var, main_var in variables
            ]
            normalized = normalize_speed_hotkey_bindings(rows)
            rows = [{"rate": item.rate, "hotkey": item.spec.text} for item in normalized]
        except (TypeError, ValueError) as exc:
            messagebox.showerror("多倍率快捷键设置", str(exc), parent=dialog)
            return False
        old_rows = list(getattr(self, "speed_rate_hotkeys", []) or [])
        ok, message = self._speed_hotkey_listener.replace(rows)
        if not ok:
            self._log(f"[加速器快捷键] {message}")
            messagebox.showerror("多倍率快捷键设置", message, parent=dialog)
            return False
        try:
            LauncherApp._save_speed_rate_hotkeys(self, rows)
        except Exception as exc:
            rollback_ok, rollback_message = self._speed_hotkey_listener.replace(old_rows)
            message = f"保存配置失败：{mask_sensitive_text(exc)}；" + ("已恢复旧快捷键" if rollback_ok else f"旧快捷键恢复失败：{rollback_message}")
            self._log(f"[加速器快捷键] {message}")
            messagebox.showerror("多倍率快捷键设置", message, parent=dialog)
            return False
        self.speed_rate_hotkeys = rows
        self._log(f"[加速器快捷键] {message}，已保存并立即生效。")
        dialog.destroy()
        return True

    def _on_speed_rate_hotkey(self, rate: float) -> None:
        threading.Thread(target=LauncherApp._speed_rate_hotkey_worker, args=(self, float(rate)), daemon=True).start()

    def _speed_rate_hotkey_worker(self, configured_rate: float) -> None:
        lock = getattr(self, "_speed_hotkey_toggle_lock", None)
        if lock is None or not lock.acquire(blocking=False):
            return
        try:
            scope_var = getattr(self, "client_speed_control_scope_var", None)
            scope = str(scope_var.get() if scope_var is not None else CLIENT_SPEED_SCOPE_CURRENT_BATCH)
            candidates = LauncherApp._client_speed_control_scope_bindings(self, scope)
            matches_by_runtime = {
                (
                    int(getattr(binding, "pid", 0) or 0),
                    int(getattr(binding, "hwnd", 0) or 0),
                    int(getattr(binding, "cdp_port", 0) or 0),
                ): binding
                for binding in candidates
            }
            matches = list(matches_by_runtime.values())
            target_rate = 1.0 if matches and all(abs(float(getattr(binding, "speed_rate", 1.0) or 1.0) - float(configured_rate)) < 1e-9 for binding in matches) else float(configured_rate)
            config = ClientSpeedPanelConfig(**LauncherApp._client_speed_panel_options(self))
            self._queue_log(f"[加速器快捷键] 范围={scope}，目标={len(matches)}，倍率={target_rate}。")
            summary = run_speed_control_batch(
                matches, float(target_rate),
                stop_event=getattr(self, "stop_event", None),
                skip_reason=lambda binding: LauncherApp._client_speed_control_skip_reason(self, binding),
                apply_binding=lambda binding, value: LauncherApp._apply_client_speed_to_binding(self, binding, value, config),
                log=self._queue_log,
            )
            if summary.success and hasattr(self, "client_batch_store"):
                self.client_batch_store.save()
            self._queue_log(
                f"[加速器快捷键] 完成：成功={summary.success}，失败={summary.failed}，"
                f"跳过={summary.skipped}，倍率={target_rate}。"
            )
        finally:
            lock.release()

    def _client_speed_control_rate(self, rate_override: float | None = None) -> float | None:
        if rate_override is not None:
            raw_value = str(rate_override)
        else:
            var = getattr(self, "client_speed_control_rate_var", None)
            raw_value = str(var.get() if var is not None else "")
        try:
            rate = float(raw_value)
        except Exception:
            rate = 0.0
        if rate <= 0:
            self._log(f"[加速总控] 倍率输入无效：{mask_sensitive_text(raw_value)}")
            try:
                messagebox.showwarning("加速总控", f"倍率输入无效：{raw_value}")
            except Exception:
                pass
            return None
        if rate_override is not None:
            var = getattr(self, "client_speed_control_rate_var", None)
            if var is not None:
                try:
                    var.set(str(rate))
                except Exception:
                    pass
        return rate

    def _client_speed_control_scope_bindings(self, scope: str) -> list[ClientBatchBinding]:
        if not hasattr(self, "client_batch_store") or not self.client_batch_store.batches:
            return []
        scope = str(scope or CLIENT_SPEED_SCOPE_CURRENT_BATCH)
        if scope == CLIENT_SPEED_SCOPE_CURRENT_BATCH:
            LauncherApp._ensure_client_direct_selected_batch_current(self)
            return list(self.client_batch_store.current_batch().bindings)
        if scope == CLIENT_SPEED_SCOPE_SELECTED:
            LauncherApp._ensure_client_direct_selected_batch_current(self)
            selected_ids: set[str] = set()
            tree = getattr(self, "tree", None)
            if tree is not None:
                try:
                    selected_ids = {str(item) for item in tree.selection()}
                except Exception:
                    selected_ids = set()
            return [
                binding
                for binding in self.client_batch_store.current_batch().bindings
                if str(binding.account_id) in selected_ids
            ]
        bindings = [
            binding
            for batch in self.client_batch_store.batches
            for binding in batch.bindings
        ]
        if scope == CLIENT_SPEED_SCOPE_CDP_AVAILABLE:
            return [binding for binding in bindings if int(binding.cdp_port or 0) > 0]
        return bindings

    def _client_speed_control_skip_reason(self, binding: ClientBatchBinding) -> str:
        status = str(getattr(binding, "window_status", "") or binding.status or "")
        if int(binding.cdp_port or 0) <= 0:
            return "cdp_unavailable"
        if status in {
            "pid_missing",
            "pid_not_x5game",
            "binding_invalid",
            "cdp_owner_mismatch",
            "cdp_unavailable",
            "hwnd_invalid",
            "scan_missing",
            "未找到",
            "已失联",
        }:
            return status
        pid = int(binding.pid or 0)
        if pid <= 0:
            return "pid_missing"
        try:
            if not LauncherApp._client_direct_pid_exists(self, pid):
                return "pid_missing"
            if not LauncherApp._client_direct_process_is_x5game(self, pid):
                return "pid_not_x5game"
            if not LauncherApp._client_direct_cdp_available(self, int(binding.cdp_port or 0)):
                return "cdp_unavailable"
        except Exception:
            return ""
        return ""

    def _apply_client_speed_control(self, *, rate_override: float | None = None) -> None:
        worker_thread = getattr(self, "worker_thread", None)
        if worker_thread is not None and worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return
        rate = LauncherApp._client_speed_control_rate(self, rate_override)
        if rate is None:
            return
        scope_var = getattr(self, "client_speed_control_scope_var", None)
        scope = str(scope_var.get() if scope_var is not None else CLIENT_SPEED_SCOPE_CURRENT_BATCH)
        bindings = LauncherApp._client_speed_control_scope_bindings(self, scope)
        config = ClientSpeedPanelConfig(**LauncherApp._client_speed_panel_options(self))
        stop_event = getattr(self, "stop_event", None)
        if stop_event is None:
            stop_event = threading.Event()
            self.stop_event = stop_event
        stop_event.clear()
        self._preserve_background_windows = True
        status_var = getattr(self, "client_speed_control_status_var", None)
        if status_var is not None:
            try:
                status_var.set(f"执行中 0/{len(bindings)}")
            except Exception:
                pass
        self._log(f"[加速总控] 已启动后台任务：范围={scope}，目标={len(bindings)}，倍率={rate}。")
        self.worker_thread = threading.Thread(
            target=LauncherApp._client_speed_control_worker,
            args=(self, list(bindings), float(rate), config),
            daemon=True,
        )
        self.worker_thread.start()

    def _client_speed_control_worker(
        self,
        bindings: list[ClientBatchBinding],
        rate: float,
        config: ClientSpeedPanelConfig,
    ) -> None:
        try:
            summary = run_speed_control_batch(
                bindings,
                float(rate),
                stop_event=getattr(self, "stop_event", None),
                skip_reason=lambda binding: LauncherApp._client_speed_control_skip_reason(self, binding),
                apply_binding=lambda binding, value: LauncherApp._apply_client_speed_to_binding(
                    self,
                    binding,
                    value,
                    config,
                ),
                log=self._queue_log,
            )
            if summary.success and hasattr(self, "client_batch_store"):
                try:
                    self.client_batch_store.save()
                except Exception as exc:
                    self._queue_log(f"[加速总控] 保存成功倍率失败：{mask_sensitive_text(exc)}")
            self._queue_log(
                f"[加速总控] 目标{summary.total}，成功{summary.success}，失败{summary.failed}，"
                f"跳过{summary.skipped}，停止{summary.stopped}。"
            )
            self._update_status_bar(
                "加速总控已停止" if summary.stopped else f"加速总控完成：成功{summary.success}，失败{summary.failed}"
            )
        except Exception as exc:
            summary = SpeedControlSummary(total=len(bindings), failed=len(bindings))
            self._queue_log(f"[加速总控] 后台任务失败：{mask_sensitive_text(exc)}")
        finish = lambda: LauncherApp._finish_client_speed_control(self, summary)
        try:
            self.after(0, finish)
        except Exception:
            finish()

    def _finish_client_speed_control(self, summary: SpeedControlSummary) -> None:
        status_text = (
            f"成功 {summary.success} / 失败 {summary.failed} / "
            f"跳过 {summary.skipped} / 停止 {summary.stopped}"
        )
        status_var = getattr(self, "client_speed_control_status_var", None)
        if status_var is not None:
            try:
                status_var.set(status_text)
            except Exception:
                pass
        sync = getattr(self, "_sync_client_direct_batch_status", None)
        if callable(sync):
            sync()
        self.worker_thread = None

    def _apply_client_speed_to_binding(
        self,
        binding: ClientBatchBinding,
        rate: float,
        config: ClientSpeedPanelConfig,
    ) -> SpeedApplyResult:
        return apply_speed_rate_to_binding(
            binding,
            float(rate),
            config,
            log=self._queue_log,
        )

    def _sync_client_direct_port_range(self) -> None:
        var = getattr(self, "client_direct_port_range_var", None)
        if var is None:
            return
        try:
            count = len(self._filtered_accounts_for_ui()) if _run_mode_key_for_owner(self) == "client_direct" else 1
        except Exception:
            count = 1
        count = max(1, int(count or 1))
        base = LauncherApp._client_direct_base_port(self)
        var.set(f"{base} ~ {base + count - 1}")
        count_var = getattr(self, "client_direct_batch_count_var", None)
        if count_var is not None:
            count_var.set(f"本批数量：{count}")
        try:
            return bool(var.get())
        except Exception:
            return True

    def _confirm_client_direct_new_batch_if_live(self, accounts: list[AccountConfig], action_name: str) -> bool:
        if not hasattr(self, "client_batch_store") or not self.client_batch_store.batches:
            return True
        LauncherApp._ensure_client_direct_selected_batch_current(self)
        try:
            LauncherApp._refresh_client_direct_sessions_for_precheck(self)
        except Exception:
            pass
        batch = self.client_batch_store.current_batch()
        live_count = self.client_batch_store.batch_live_count(
            batch,
            pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
            process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
        )
        if live_count <= 0:
            return True
        message = f"当前批次已有 {live_count} 个存活客户端，是否创建新批次准备本次 {len(accounts)} 个账号？"
        confirmed = messagebox.askyesno(action_name, message)
        if confirmed:
            self._log(f"[客户端批次] 用户确认创建新批次：旧批次={batch.batch_name}，存活={live_count}，本次数={len(accounts)}。")
            return True
        self._log(f"[客户端批次] 用户取消创建新批次：保留旧批次={batch.batch_name}，未启动客户端。")
        return False

    def _set_game_program_path(self, path: str) -> None:
        entry_value, status_text = _game_program_display_values(path)
        self.wm_game_path_var.set(entry_value)
        self.wm_game_status_var.set(status_text)

    def _sync_game_program_status(self) -> None:
        if not hasattr(self, "wm_game_status_var"):
            return
        self.wm_game_status_var.set(_format_game_program_status(self.wm_game_path_var.get()))

    def _pick_game_path(self) -> None:
        path = filedialog.askopenfilename(
            title="选择游戏程序或快捷方式",
            filetypes=[
                ("游戏程序或快捷方式", "*.exe *.lnk"),
                ("游戏程序", "*.exe"),
                ("快捷方式", "*.lnk"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            folder = filedialog.askdirectory(title="或选择游戏安装目录")
            path = folder
        if path:
            self._apply_game_path_input(path)

    def _enable_game_path_drag_drop(self) -> None:
        self.wm_game_hint_var.set(_game_program_hint_text())
        if not _is_tkinterdnd2_available():
            self._log("[窗口管理] tkinterdnd2 不可用，拖拽未启用；可点击“选择游戏图标/程序”选择 exe 或 lnk。")
            return

        registered = 0
        targets = [
            getattr(self, "wm_game_path_box", None),
            getattr(self, "wm_game_path_entry", None),
            getattr(self, "wm_game_hint_label", None),
            getattr(self, "wm_game_status_label", None),
        ]
        for widget in targets:
            if widget is None:
                continue
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_game_path_drop)
                registered += 1
            except Exception as exc:
                self._log(f"[窗口管理] 注册游戏路径拖拽目标失败：{exc}")

        if registered:
            self._log("[窗口管理] 已启用游戏程序拖拽：支持桌面快捷方式、exe、游戏安装目录。")
        else:
            self.wm_game_hint_var.set("点击“选择游戏图标/程序”，可选择桌面快捷方式或 X5Game.exe。")
            self._log("[窗口管理] 游戏路径拖拽启用失败；请点击“选择游戏图标/程序”选择 exe 或 lnk。")

    def _on_game_path_drop(self, event: object) -> str:
        raw_data = str(getattr(event, "data", "") or "")
        path = first_dropped_file_path(raw_data, splitlist=self.tk.splitlist)
        if not path:
            self._log("[窗口管理] 未识别到拖入路径。")
            return str(getattr(event, "action", "copy") or "copy")
        self._log(f"[窗口管理] 拖入游戏路径：{path}")
        self._apply_game_path_input(path, source="drop")
        return str(getattr(event, "action", "copy") or "copy")

    def _apply_game_path_input(self, raw_path: str, source: str = "select") -> bool:
        def customer_message(message: str) -> str:
            clean_message = message or "请选择游戏程序 exe、游戏快捷方式或游戏安装目录。"
            if source == "drop" and clean_message.startswith("请选择"):
                return clean_message.replace("请选择", "请拖入", 1)
            return clean_message

        try:
            result = resolve_game_executable_path(raw_path)
        except Exception as exc:
            message = customer_message(str(exc))
            self._log(f"[窗口管理] 游戏路径无效：{message}")
            messagebox.showwarning("游戏路径无效", message)
            return False
        self._set_game_program_path(result.path)
        self._save_window_manager_settings()
        if result.message:
            self._log(f"[窗口管理] {result.message}")
        if source == "drop":
            self._log(f"[窗口管理] 已通过拖拽识别游戏程序：{result.path}")
        return True

    def _load_window_manager_settings(self) -> None:
        settings, error = load_window_manager_settings()
        self.wm_fixed_mode_settings = settings.fixed_mode
        self.wm_row_count_mode_settings = settings.row_count_mode
        self._set_game_program_path(settings.game_path)
        self.wm_launch_interval_var.set(settings.launch_interval)
        self.wm_auto_tile_after_launch_var.set(settings.auto_tile_after_launch)
        self.wm_auto_rename_after_tile_var.set(settings.auto_rename_after_tile)
        self.wm_title_template_var.set(settings.title_template)
        self.wm_current_tile_mode_key = settings.last_tile_mode
        self.wm_tile_mode_var.set(self._wm_mode_label_from_key(settings.last_tile_mode))
        self.wm_prevent_overflow_var.set(settings.prevent_overflow)
        self._wm_apply_current_mode_settings()
        self._refresh_mode_account_scope()

        if error:
            self._log(f"[窗口管理] 读取参数配置失败，已使用默认值：{error}")
        elif window_manager_settings_path().exists():
            self._log(f"[窗口管理] 已加载参数配置：{window_manager_settings_path()}")

    def _wm_on_tile_mode_changed(self) -> None:
        self._wm_store_current_mode_values(self.wm_current_tile_mode_key)
        self.wm_current_tile_mode_key = self._wm_mode_key_from_label()
        self._wm_apply_current_mode_settings()
        self._refresh_mode_account_scope(log_change=True)

    def _wm_mode_key_from_label(self, label: str | None = None) -> str:
        mode_label = (label or self.wm_tile_mode_var.get()).strip()
        if mode_label == WM_TILE_MODE_ROW_COUNT:
            return TILE_MODE_ROW_COUNT
        return TILE_MODE_FIXED

    def _wm_mode_label_from_key(self, key: str) -> str:
        if key == TILE_MODE_ROW_COUNT:
            return WM_TILE_MODE_ROW_COUNT
        return WM_TILE_MODE_FIXED

    def _wm_apply_current_mode_settings(self) -> None:
        if self._wm_mode_key_from_label() == TILE_MODE_ROW_COUNT:
            self.wm_launch_count_var.set(self.wm_row_count_mode_settings.launch_count)
            self.wm_per_row_var.set(self.wm_row_count_mode_settings.per_row)
            return

        fixed = self.wm_fixed_mode_settings
        self.wm_launch_count_var.set(fixed.launch_count)
        self.wm_window_width_var.set(fixed.window_width)
        self.wm_window_height_var.set(fixed.window_height)
        self.wm_start_x_var.set(fixed.start_x)
        self.wm_start_y_var.set(fixed.start_y)
        self.wm_offset_x_var.set(fixed.offset_x)
        self.wm_offset_y_var.set(fixed.offset_y)
        self.wm_per_row_var.set(fixed.per_row)

    def _wm_store_current_mode_values(self, mode_key: str | None = None) -> None:
        try:
            launch_count = int(self.wm_launch_count_var.get())
            per_row = int(self.wm_per_row_var.get())
            target_mode_key = mode_key or self._wm_mode_key_from_label()
            if target_mode_key == TILE_MODE_ROW_COUNT:
                self.wm_row_count_mode_settings = RowCountModeSettings(
                    launch_count=launch_count,
                    per_row=per_row,
                )
            else:
                self.wm_fixed_mode_settings = FixedModeSettings(
                    launch_count=launch_count,
                    window_width=self.wm_window_width_var.get().strip(),
                    window_height=self.wm_window_height_var.get().strip(),
                    start_x=int(self.wm_start_x_var.get()),
                    start_y=int(self.wm_start_y_var.get()),
                    offset_x=int(self.wm_offset_x_var.get()),
                    offset_y=int(self.wm_offset_y_var.get()),
                    per_row=per_row,
                )
        except Exception as exc:
            self._log(f"[窗口管理] 当前模式参数缓存失败：{exc}")

    def _current_window_manager_settings(self) -> WindowManagerSettings | None:
        try:
            self._wm_store_current_mode_values(self.wm_current_tile_mode_key)
            self.wm_current_tile_mode_key = self._wm_mode_key_from_label()
            return WindowManagerSettings(
                game_path=self.wm_game_path_var.get().strip().strip('"'),
                launch_count=int(self.wm_launch_count_var.get()),
                launch_interval=int(self.wm_launch_interval_var.get()),
                auto_tile_after_launch=bool(self.wm_auto_tile_after_launch_var.get()),
                auto_rename_after_tile=bool(self.wm_auto_rename_after_tile_var.get()),
                title_template=self.wm_title_template_var.get().strip(),
                last_tile_mode=self._wm_mode_key_from_label(),
                prevent_overflow=bool(self.wm_prevent_overflow_var.get()),
                fixed_mode=self.wm_fixed_mode_settings,
                row_count_mode=self.wm_row_count_mode_settings,
            )
        except Exception as exc:
            self._log(f"[窗口管理] 当前参数读取失败，未保存配置：{exc}")
            return None

    def _save_window_manager_settings(self) -> bool:
        settings = self._current_window_manager_settings()
        if settings is None:
            return False
        try:
            save_window_manager_settings(settings)
            return True
        except Exception as exc:
            self._log(f"[窗口管理] 保存参数配置失败：{exc}")
            return False

    def _wm_excluded_hwnds(self) -> list[int]:
        try:
            return [int(self.winfo_id())]
        except Exception:
            return []

    def _wm_game_exe_path_filter(self) -> str:
        return self.wm_game_path_var.get().strip().strip('"')

    def _wm_expected_window_size_filter(self) -> tuple[int, int] | None:
        try:
            width = int(str(self.wm_window_width_var.get()).strip())
            height = int(str(self.wm_window_height_var.get()).strip())
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return (width, height)

    def _wm_detection_log_path(self) -> Path:
        return logs_dir(getattr(self, "user_data_dir", None)) / WINDOW_DETECTION_LOG_PATH.name

    def _wm_log_zero_detection_hint(self) -> None:
        self._log(
            "窗口管理：识别窗口失败：未识别到游戏窗口。"
            f"如果桌面已有疑似斗罗大陆H5标题窗口，请查看详细日志：{self._wm_detection_log_path()}"
        )

    def _wm_action_buttons(self) -> list[object]:
        buttons = []
        for name in (
            "wm_launch_btn",
            "wm_tile_btn",
            "wm_refresh_slots_btn",
            "wm_regenerate_slots_btn",
            "wm_repair_slot_btn",
        ):
            button = getattr(self, name, None)
            if button is not None:
                buttons.append(button)
        return buttons

    def _wm_set_actions_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        for button in self._wm_action_buttons():
            try:
                button.configure(state=state)
            except Exception:
                pass

    def _wm_has_running_action(self) -> bool:
        return bool(
            (self.wm_launch_thread and self.wm_launch_thread.is_alive())
            or (self.wm_action_thread and self.wm_action_thread.is_alive())
        )

    def _wm_start_action_worker(self, name: str, target, args: tuple = ()) -> bool:
        if self._wm_has_running_action():
            self._log(f"[窗口管理] {name} 已阻止：已有窗口管理任务正在执行。")
            messagebox.showwarning("窗口管理", "已有窗口管理任务正在执行，请等待完成。")
            return False

        def _run() -> None:
            try:
                target(*args)
            finally:
                self.after(0, lambda: self._wm_set_actions_busy(False))

        self._wm_set_actions_busy(True)
        self.wm_action_thread = threading.Thread(target=_run, daemon=True)
        self.wm_action_thread.start()
        return True

    def _wm_current_window_count(self) -> int:
        return len(
            list_game_windows(
                title_template=_safe_wm_title_template(self),
                exclude_hwnds=self._wm_excluded_hwnds(),
                game_exe_path=self._wm_game_exe_path_filter(),
                expected_window_size=_safe_wm_expected_window_size(self),
            )
        )

    def _wm_require_complete_windows(
        self,
        action_name: str,
        current_count: int,
        target_count: int | None,
    ) -> bool:
        if target_count is None or current_count == int(target_count):
            return True
        message = (
            f"当前窗口数量不完整：目标 {int(target_count)}，当前 {current_count}。\n"
            f"禁止{action_name}，避免覆盖原有完整槽位。\n"
            "请先修复缺失窗口，或关闭全部窗口后重新批量启动。"
        )
        self._log(f"[窗口管理] {message.replace(chr(10), ' ')}")
        messagebox.showwarning(action_name, message)
        return False

    def _wm_parse_positive_dimension(self, value: str, label: str) -> int:
        text = str(value).strip()
        if not text or text.lower() == "auto":
            raise ValueError(
                "固定参数排列需要填写窗口宽度和窗口高度；"
                "如果想用当前窗口尺寸，请切换为“根据行数排列”。"
            )
        try:
            parsed = int(text)
        except Exception as exc:
            raise ValueError(
                f"{label}必须是大于 0 的整数；"
                "如果想用当前窗口尺寸，请切换为“根据行数排列”。"
            ) from exc
        if parsed <= 0:
            raise ValueError(
                f"{label}必须大于 0；"
                "如果想用当前窗口尺寸，请切换为“根据行数排列”。"
            )
        return parsed

    def _wm_parse_auto_dimension(self, value: str, label: str) -> int | None:
        text = str(value).strip()
        if not text or text.lower() == "auto":
            return None
        try:
            parsed = int(text)
        except Exception as exc:
            raise ValueError(f"{label}请填写大于 0 的整数、留空，或填写 Auto。") from exc
        if parsed <= 0:
            raise ValueError(f"{label}请填写大于 0 的整数、留空，或填写 Auto。")
        return parsed

    def _wm_read_tile_config(self) -> TileConfig | None:
        try:
            config = TileConfig(
                width=self._wm_parse_positive_dimension(self.wm_window_width_var.get(), "窗口宽度"),
                height=self._wm_parse_positive_dimension(self.wm_window_height_var.get(), "窗口高度"),
                start_x=int(self.wm_start_x_var.get()),
                start_y=int(self.wm_start_y_var.get()),
                offset_x=int(self.wm_offset_x_var.get()),
                offset_y=int(self.wm_offset_y_var.get()),
                per_row=int(self.wm_per_row_var.get()),
            )
        except Exception as exc:
            self._log(f"窗口管理：参数读取失败：{exc}")
            messagebox.showerror("窗口管理参数错误", str(exc))
            return None

        if config.width <= 0 or config.height <= 0 or config.per_row <= 0:
            message = "窗口宽度、窗口高度、每行数量必须大于 0。"
            self._log(f"窗口管理：参数无效：{message}")
            messagebox.showerror("窗口管理参数错误", message)
            return None
        return config

    def _wm_read_row_tile_config(self) -> RowTileConfig | None:
        try:
            config = RowTileConfig(
                width=None,
                height=None,
                start_x=0,
                start_y=0,
                per_row=int(self.wm_per_row_var.get()),
                prevent_overflow=bool(self.wm_prevent_overflow_var.get()),
            )
        except Exception as exc:
            self._log(f"窗口管理：按行数排列参数读取失败：{exc}")
            messagebox.showerror("窗口管理参数错误", str(exc))
            return None

        if config.per_row <= 0:
            message = "单行数量必须大于 0。"
            self._log(f"窗口管理：参数无效：{message}")
            messagebox.showerror("窗口管理参数错误", message)
            return None
        return config

    def _wm_read_arrangement_config(self) -> tuple[str, TileConfig | RowTileConfig] | None:
        mode = self.wm_tile_mode_var.get().strip() or WM_TILE_MODE_FIXED
        if mode == WM_TILE_MODE_ROW_COUNT:
            config = self._wm_read_row_tile_config()
        else:
            mode = WM_TILE_MODE_FIXED
            config = self._wm_read_tile_config()
        if config is None:
            return None
        return mode, config

    def _wm_read_title_template(self) -> str | None:
        title_template = self.wm_title_template_var.get().strip()
        if not title_template:
            message = "标题模板不能为空。"
            self._log(f"[窗口管理] {message}")
            messagebox.showwarning("窗口标题模板", message)
            return None
        return title_template

    def _wm_launch_windows(self) -> None:
        if self._wm_has_running_action():
            self._log("[窗口管理] 批量启动已阻止：已有窗口管理任务正在执行。")
            messagebox.showwarning("批量启动窗口", "已有窗口管理任务正在执行，请等待完成。")
            return

        game_path = self.wm_game_path_var.get().strip().strip('"')
        if not game_path:
            message = "请先填写游戏路径。"
            self._log(f"[窗口管理] {message}")
            messagebox.showwarning("批量启动窗口", message)
            return
        if not Path(game_path).exists():
            message = f"游戏路径不存在：{game_path}"
            self._log(f"[窗口管理] {message}")
            messagebox.showwarning("批量启动窗口", message)
            return

        try:
            launch_count = int(self.wm_launch_count_var.get())
            launch_interval = int(self.wm_launch_interval_var.get())
        except Exception as exc:
            self._log(f"[窗口管理] 启动参数读取失败：{exc}")
            messagebox.showwarning("批量启动窗口", str(exc))
            return

        if launch_count < 1:
            message = "打开数量必须大于等于 1。"
            self._log(f"[窗口管理] {message}")
            messagebox.showwarning("批量启动窗口", message)
            return
        if launch_interval < 0:
            message = "启动间隔不能小于 0。"
            self._log(f"[窗口管理] {message}")
            messagebox.showwarning("批量启动窗口", message)
            return

        excluded_hwnds = self._wm_excluded_hwnds()
        try:
            existing_count = len(
                list_game_windows(
                    title_template=_safe_wm_title_template(self),
                    exclude_hwnds=excluded_hwnds,
                    game_exe_path=game_path,
                    expected_window_size=_safe_wm_expected_window_size(self),
                )
            )
        except Exception as exc:
            self._log(f"[窗口管理] 批量启动前识别窗口失败：{exc}")
            existing_count = 0
        if existing_count >= launch_count:
            message = (
                f"当前已检测到 {existing_count} 个窗口，目标打开数量为 {launch_count}。\n"
                "如需重新启动，请先关闭窗口。\n"
                "如需重新排列，请使用“排列窗口”或“重新生成槽位”。"
            )
            self._log(f"[窗口管理] 已阻止批量追加启动：当前={existing_count}，目标={launch_count}")
            messagebox.showwarning("批量启动窗口", message)
            return

        self._save_window_manager_settings()
        auto_tile = bool(self.wm_auto_tile_after_launch_var.get())
        auto_rename = bool(self.wm_auto_rename_after_tile_var.get())
        arrangement = self._wm_read_arrangement_config() if auto_tile else None
        if auto_tile and arrangement is None:
            return
        tile_mode = arrangement[0] if arrangement else WM_TILE_MODE_FIXED
        tile_config = arrangement[1] if arrangement else None
        layout_params = (
            self._wm_slot_layout_params(
                tile_mode,
                tile_config,
                self.wm_title_template_var.get().strip(),
                target_window_count=launch_count,
            )
            if tile_config is not None
            else None
        )
        title_template = None
        if auto_tile and auto_rename:
            title_template = self._wm_read_title_template()
            if title_template is None:
                return

        self._wm_set_actions_busy(True)
        self.wm_launch_thread = threading.Thread(
            target=self._wm_launch_windows_worker,
            args=(
                game_path,
                launch_count,
                launch_interval,
                auto_tile,
                auto_rename,
                tile_mode,
                tile_config,
                title_template,
                layout_params,
                excluded_hwnds,
            ),
            daemon=True,
        )
        self.wm_launch_thread.start()

    def _wm_launch_windows_worker(
        self,
        game_path: str,
        launch_count: int,
        launch_interval: int,
        auto_tile: bool,
        auto_rename: bool,
        tile_mode: str,
        tile_config: TileConfig | RowTileConfig | None,
        title_template: str | None,
        layout_params,
        excluded_hwnds: list[int],
    ) -> None:
        def log(message: str) -> None:
            self._queue_log(f"[窗口管理] {message}")

        try:
            log(f"准备批量启动：路径={game_path}，数量={launch_count}，间隔={launch_interval}ms")
            try:
                before_windows = list_game_windows(
                    title_template=_safe_wm_title_template(self),
                    exclude_hwnds=excluded_hwnds,
                    game_exe_path=game_path,
                    expected_window_size=_safe_wm_expected_window_size(self),
                )
                before_count = len(before_windows)
                log(f"启动前识别到 {before_count} 个 H5 窗口")
            except Exception as exc:
                before_count = 0
                log(f"启动前识别窗口失败：{exc}")
            new_session = before_count == 0
            if new_session:
                log("启动前没有旧 H5 窗口，本次按当前窗口管理参数重新生成槽位")
                log("本次不使用旧 hwnd 槽位快照，不按旧 window_slots.json 恢复")
            if before_count >= launch_count:
                log(
                    f"已阻止批量追加启动：当前已检测到 {before_count} 个窗口，"
                    f"目标打开数量为 {launch_count}。如需重新启动请先关闭窗口。"
                )
                return

            launch_missing = max(0, launch_count - before_count)
            if before_count > 0:
                log(f"当前已有 {before_count} 个窗口，本次只补齐启动 {launch_missing} 个，目标总数 {launch_count}。")

            for index in range(1, launch_missing + 1):
                log(f"正在启动第 {index}/{launch_missing} 个窗口")
                result = launch_game_process(game_path)
                if result.success:
                    log(f"第 {index} 个窗口启动命令已发送")
                else:
                    log(f"第 {index} 个窗口启动命令发送失败：{result.error}")

                if launch_interval > 0:
                    time.sleep(launch_interval / 1000)

                try:
                    current_windows = list_game_windows(
                        title_template=_safe_wm_title_template(self),
                        exclude_hwnds=excluded_hwnds,
                        game_exe_path=game_path,
                        expected_window_size=_safe_wm_expected_window_size(self),
                    )
                    current_count = len(current_windows)
                    expected_count = before_count + index
                    log(f"当前识别到 {current_count} 个 H5 窗口")
                    if current_count >= expected_count:
                        log(f"已达到当前目标数量：{current_count}/{expected_count}")
                    else:
                        log(f"尚未达到当前目标数量：{current_count}/{expected_count}")
                except Exception as exc:
                    log(f"启动后识别窗口失败：{exc}")

            try:
                final_count = len(
                    list_game_windows(
                        title_template=_safe_wm_title_template(self),
                        exclude_hwnds=excluded_hwnds,
                        game_exe_path=game_path,
                        expected_window_size=_safe_wm_expected_window_size(self),
                    )
                )
            except Exception as exc:
                final_count = -1
                log(f"批量启动完成后识别窗口失败：{exc}")

            target_count = launch_count
            if final_count >= 0:
                log(f"批量启动完成，目标 {target_count} 个，当前识别到 {final_count} 个")

            if auto_tile and tile_config is not None:
                is_stable, stable_count = self._wm_wait_for_windows_stable(
                    target_count=target_count,
                    excluded_hwnds=excluded_hwnds,
                    game_exe_path=game_path,
                    log=log,
                )
                if not is_stable:
                    if stable_count < target_count:
                        log(
                            f"目标 {target_count} 个，当前识别到 {stable_count} 个，"
                            "未达到目标数量，已跳过自动排列，请手动点击“排列窗口”。"
                        )
                    else:
                        log(
                            f"目标 {target_count} 个，当前识别到 {stable_count} 个，"
                            "但窗口数量未连续稳定，已跳过自动排列，请手动点击“排列窗口”。"
                        )
                    return

                log(f"已勾选启动后自动排列，开始排列窗口，排列方式={tile_mode}")
                if tile_mode == WM_TILE_MODE_ROW_COUNT:
                    log(
                        f"按行数排列参数：单行数量={tile_config.per_row}，"
                        "自动缩放窗口=True，"
                        f"禁止超出屏幕宽度={tile_config.prevent_overflow}"
                    )
                try:
                    if self._wm_has_saved_slots(layout_params) and not new_session:
                        current_count = len(
                            list_game_windows(
                                title_template=_safe_wm_title_template(self),
                                exclude_hwnds=excluded_hwnds,
                                game_exe_path=game_path,
                                expected_window_size=_safe_wm_expected_window_size(self),
                            )
                        )
                        if not self._wm_validate_slot_profile(
                            layout_params=layout_params,
                            current_window_count=current_count,
                            log=log,
                            show_error=False,
                        ):
                            log("槽位 profile 不一致，已阻止按旧槽位恢复。请点击“重新生成槽位”。")
                            return
                        slots_path = self._wm_slots_path(layout_params)
                        log(f"检测到当前 profile 槽位文件：{slots_path.name}，启动后自动排列改为按已保存槽位恢复布局")
                        log("本次不会按 hwnd / 枚举顺序重新排序，不会覆盖其它 profile 槽位")
                        slot_results = restore_windows_by_slots(
                            slots_path=slots_path,
                            title_template=title_template,
                            exclude_hwnds=excluded_hwnds,
                            game_exe_path=game_path,
                            move_windows=True,
                            rename_windows=True,
                        )
                        self._wm_log_slot_restore_results(slot_results, log)
                        success_count = sum(1 for result in slot_results if result.success)
                        failed_count = len(slot_results) - success_count
                        log(f"自动按槽位恢复完成：成功 {success_count}，失败 {failed_count}")
                        return

                    if not new_session and not self._wm_has_saved_slots(layout_params):
                        log("未检测到当前 profile 的有效槽位文件，本次排列后保存新的槽位快照")

                    results = self._wm_run_tile(
                        tile_mode=tile_mode,
                        tile_config=tile_config,
                        exclude_hwnds=excluded_hwnds,
                        game_exe_path=game_path,
                        log=log,
                    )
                    log(f"自动排列完成，结果 {len(results)} 个")
                    self._wm_log_tile_results(results, log)
                    failed_results = [result for result in results if not result.success]
                    if failed_results:
                        error = (
                            f"排列窗口失败：{len(failed_results)} 个窗口移动失败，本次未写入槽位。"
                            f"首个错误：{failed_results[0].error}"
                        )
                        log(error)
                        self.after(0, lambda message=error: messagebox.showerror("排列窗口失败", message))
                        return
                    if auto_rename:
                        self._wm_rename_windows_after_tile(
                            log=log,
                            exclude_hwnds=excluded_hwnds,
                            title_template=title_template,
                            force_global=new_session,
                        )
                        log("自动编号标题完成")
                    slots = save_current_windows_as_slots(
                        slots_path=self._wm_slots_path(layout_params),
                        exclude_hwnds=excluded_hwnds,
                        game_exe_path=game_path,
                        title_template=layout_params.title_template,
                        layout_params=layout_params,
                        expected_count=target_count,
                    )
                    log(f"已按当前 profile 保存槽位快照：{len(slots)} 个，路径={self._wm_slots_path(layout_params)}")
                except Exception as exc:
                    log(f"启动后自动排列失败：{exc}")
        finally:
            self.after(0, lambda: self._wm_set_actions_busy(False))

    def _wm_wait_for_windows_stable(
        self,
        target_count: int,
        excluded_hwnds: list[int],
        game_exe_path: str,
        log,
    ) -> tuple[bool, int]:
        log("批量启动命令发送完成，等待窗口稳定")
        last_count: int | None = None
        stable_count = 0
        current_count = 0
        deadline = time.monotonic() + WM_WAIT_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            try:
                current_count = len(
                    list_game_windows(
                        title_template=_safe_wm_title_template(self),
                        exclude_hwnds=excluded_hwnds,
                        game_exe_path=game_exe_path,
                        expected_window_size=_safe_wm_expected_window_size(self),
                    )
                )
            except Exception as exc:
                stable_count = 0
                log(f"等待窗口稳定时识别窗口失败：{exc}")
                time.sleep(WM_POLL_INTERVAL_SECONDS)
                continue

            if current_count >= target_count:
                if current_count == last_count:
                    stable_count += 1
                else:
                    stable_count = 1
                log(
                    f"当前识别到：{current_count} / {target_count}，"
                    f"稳定检测 {stable_count}/{WM_STABLE_CHECKS}"
                )
                if stable_count >= WM_STABLE_CHECKS:
                    log(f"窗口数量已稳定，等待 {WM_FINAL_DELAY_SECONDS} 秒后开始自动排列")
                    time.sleep(WM_FINAL_DELAY_SECONDS)
                    return True, current_count
            else:
                stable_count = 0
                log(f"目标窗口数：{target_count}，当前识别到：{current_count}")

            last_count = current_count
            time.sleep(WM_POLL_INTERVAL_SECONDS)

        return False, current_count

    def _wm_run_tile(
        self,
        tile_mode: str,
        tile_config: TileConfig | RowTileConfig,
        exclude_hwnds: list[int],
        game_exe_path: str | None = None,
        log=None,
    ):
        if tile_mode == WM_TILE_MODE_ROW_COUNT:
            windows = list_game_windows(
                title_template=_safe_wm_title_template(self),
                exclude_hwnds=exclude_hwnds,
                game_exe_path=game_exe_path,
                expected_window_size=_safe_wm_expected_window_size(self),
            )
            plan = calculate_row_tile_plan(len(windows), tile_config)
            if log is not None:
                work = plan.work_area
                log(
                    "按行数排列诊断："
                    f"screen_width={plan.screen_width}，screen_height={plan.screen_height}，"
                    f"work_area_left={work.left}，work_area_top={work.top}，"
                    f"work_area_right={work.right}，work_area_bottom={work.bottom}，"
                    f"work_area_width={plan.work_area_width}，work_area_height={plan.work_area_height}"
                )
                log(
                    "按行数排列诊断："
                    f"使用工作区=True，gap_x={plan.gap_x}，gap_y={plan.gap_y}，"
                    f"width_gap_total={plan.width_gap_total}，height_gap_total={plan.height_gap_total}，"
                    f"padding={plan.padding}，safe_margin={plan.safe_margin}，"
                    f"禁止超出屏幕宽度={tile_config.prevent_overflow}，额外边距=0"
                )
                log(
                    "按行数排列诊断："
                    f"usable_width={plan.usable_width}，usable_height={plan.usable_height}，"
                    f"cols={plan.cols}，rows={plan.rows}，窗口数量={plan.window_count}"
                )
                log(
                    "按行数排列诊断："
                    f"target_width=floor(({plan.usable_width}-{plan.width_gap_total})/{plan.cols})"
                    f"=floor({plan.raw_target_width:.4f})={plan.target_width}，"
                    f"target_height=floor(({plan.usable_height}-{plan.height_gap_total})/{max(1, plan.rows)})"
                    f"=floor({plan.raw_target_height:.4f})={plan.target_height}"
                )
            return tile_game_windows_by_row_count(
                tile_config,
                exclude_hwnds=exclude_hwnds,
                game_exe_path=game_exe_path,
                title_template=_safe_wm_title_template(self),
                windows=windows,
            )
        return tile_game_windows(
            tile_config,
            exclude_hwnds=exclude_hwnds,
            game_exe_path=game_exe_path,
            title_template=_safe_wm_title_template(self),
        )

    def _wm_target_window_count(self) -> int | None:
        try:
            value = int(self.wm_launch_count_var.get())
            return value if value > 0 else None
        except Exception:
            return None

    def _wm_slots_path(self, layout_params=None) -> Path:
        params = layout_params or self._wm_current_slot_layout_params()
        if params is None:
            return Path(getattr(self, "user_data_dir", app_root())) / "slots" / "invalid_profile.json"
        return window_slots_profile_path(Path(getattr(self, "user_data_dir", app_root())), params)

    def _wm_has_saved_slots(self, layout_params=None) -> bool:
        return has_valid_window_slots(self._wm_slots_path(layout_params))

    def _wm_slot_layout_params(
        self,
        tile_mode: str,
        tile_config: TileConfig | RowTileConfig,
        title_template: str | None = None,
        target_window_count: int | None = None,
    ):
        mode = "row_count" if tile_mode == WM_TILE_MODE_ROW_COUNT else "fixed"
        return layout_params_from_tile_config(
            tile_config,
            title_template=title_template if title_template is not None else self.wm_title_template_var.get().strip(),
            mode=mode,
            target_window_count=target_window_count if target_window_count is not None else self._wm_target_window_count(),
        )

    def _wm_current_slot_layout_params(self):
        arrangement = self._wm_read_arrangement_config()
        if arrangement is None:
            return None
        tile_mode, tile_config = arrangement
        return self._wm_slot_layout_params(tile_mode, tile_config)

    def _wm_log_slot_compatibility(self, layout_params, log, current_window_count: int | None = None) -> None:
        try:
            result = check_window_slots_compatibility(
                self._wm_slots_path(layout_params),
                layout_params,
                current_window_count=current_window_count,
            )
        except Exception as exc:
            log(f"槽位环境校验失败：{exc}")
            return

        log(f"当前槽位 profile 文件：{self._wm_slots_path(layout_params)}")
        current = result.current_environment
        log(
            "当前槽位环境："
            f"screen={current.screen_width}x{current.screen_height} "
            f"dpi={current.dpi} scale={current.scale:g} profile={current.profile}"
        )
        if result.slot_environment is not None:
            saved = result.slot_environment
            log(
                "保存槽位环境："
                f"screen={saved.screen_width}x{saved.screen_height} "
                f"dpi={saved.dpi} scale={saved.scale:g} profile={saved.profile}"
            )
        for warning in result.warnings:
            log(f"槽位校验提醒：{warning}")

    def _wm_validate_slot_profile(
        self,
        layout_params,
        current_window_count: int | None,
        log,
        show_error: bool = True,
    ) -> bool:
        slots_path = self._wm_slots_path(layout_params)
        if not has_valid_window_slots(slots_path):
            message = (
                f"当前 profile 尚未生成槽位：{slots_path.name}。\n"
                "请先执行“重新生成槽位”。"
            )
            log(message.replace("\n", " "))
            if show_error:
                messagebox.showwarning("槽位 profile 不存在", message)
            return False

        try:
            result = check_window_slots_compatibility(
                slots_path,
                layout_params,
                current_window_count=current_window_count,
            )
        except Exception as exc:
            message = f"槽位 profile 校验失败：{exc}"
            log(message)
            if show_error:
                messagebox.showerror("槽位 profile 校验失败", message)
            return False

        self._wm_log_slot_compatibility(layout_params, log, current_window_count=current_window_count)
        if result.compatible:
            return True

        reason = "；".join(result.warnings)
        message = (
            "当前窗口数量 / 排列参数与槽位文件不一致，禁止使用旧槽位恢复。\n"
            f"{reason}\n\n"
            "如需按当前参数重排，请点击“重新生成槽位”。"
        )
        log(f"槽位 profile 不一致，已阻止恢复：{reason}")
        if show_error:
            messagebox.showwarning("槽位 profile 不一致", message)
        return False

    def _wm_read_fixed_slot_config(self) -> TileConfig | None:
        self._wm_store_current_mode_values(self.wm_current_tile_mode_key)
        fixed = self.wm_fixed_mode_settings
        try:
            return TileConfig(
                width=self._wm_parse_positive_dimension(fixed.window_width, "窗口宽度"),
                height=self._wm_parse_positive_dimension(fixed.window_height, "窗口高度"),
                start_x=int(fixed.start_x),
                start_y=int(fixed.start_y),
                offset_x=int(fixed.offset_x),
                offset_y=int(fixed.offset_y),
                per_row=int(fixed.per_row),
            )
        except Exception as exc:
            self._log(f"[窗口管理] 固定参数不足，无法推导缺失槽位：{exc}")
            return None

    def _wm_log_refresh_slot_results(self, slots) -> None:
        self._log(f"[窗口管理] 已扫描当前窗口并刷新槽位映射：{len(slots)} 个")
        for slot in slots:
            self._log(
                f"[窗口管理] slot {slot.slot_no} 已记录："
                f"hwnd={slot.hwnd} x={slot.x} y={slot.y} "
                f"w={slot.width} h={slot.height} 标题={slot.title}"
            )

    def _wm_refresh_window_slots(self) -> None:
        self._save_window_manager_settings()
        layout_params = self._wm_current_slot_layout_params()
        if layout_params is None:
            return
        try:
            current_count = len(
                list_game_windows(
                    title_template=_safe_wm_title_template(self),
                    exclude_hwnds=self._wm_excluded_hwnds(),
                    game_exe_path=self._wm_game_exe_path_filter(),
                    expected_window_size=_safe_wm_expected_window_size(self),
                )
            )
        except Exception as exc:
            self._log(f"[窗口管理] 刷新槽位前识别窗口失败：{exc}")
            messagebox.showerror("刷新槽位映射失败", str(exc))
            return
        target_count = layout_params.target_window_count
        if not self._wm_require_complete_windows("刷新槽位映射", current_count, target_count):
            return

        self._wm_start_action_worker(
            "刷新槽位映射",
            self._wm_refresh_window_slots_worker,
            (layout_params, target_count),
        )

    def _wm_refresh_window_slots_worker(self, layout_params, target_count: int | None) -> None:
        try:
            self._queue_log("[窗口管理] 开始刷新槽位映射：只扫描当前完整窗口，不移动、不重命名。")
            slots_path = self._wm_slots_path(layout_params)
            self._queue_log(f"[窗口管理] 当前 profile 槽位文件：{slots_path}")
            slots = refresh_window_slots_from_current_windows(
                slots_path=slots_path,
                exclude_hwnds=self._wm_excluded_hwnds(),
                game_exe_path=self._wm_game_exe_path_filter(),
                title_template=layout_params.title_template,
                layout_params=layout_params,
                expected_count=target_count,
            )
        except Exception as exc:
            error = str(exc)
            self._queue_log(f"[窗口管理] 刷新槽位映射失败：{error}")
            self.after(0, lambda: messagebox.showerror("刷新槽位映射失败", error))
            return

        self.after(0, lambda: self._wm_log_refresh_slot_results(slots))
        self._queue_log(f"[窗口管理] 当前 profile 槽位文件：{self._wm_slots_path(layout_params)}")
        if not slots:
            self._queue_log("[窗口管理] 未识别到带编号标题的斗罗大陆H5窗口，未刷新任何槽位。")

    def _wm_log_slot_restore_results(self, results, log) -> None:
        for result in results:
            slot = result.slot
            if result.window is None:
                log(f"slot {slot.slot_no} 恢复失败：{result.error}")
                continue
            if result.success:
                log(
                    f"slot {slot.slot_no} 恢复成功 hwnd={result.window.hwnd} "
                    f"x={result.x} y={result.y} w={result.width} h={result.height} "
                    f"标题={result.new_title}"
                )
            else:
                log(
                    f"slot {slot.slot_no} 恢复失败 hwnd={result.window.hwnd} "
                    f"x={result.x} y={result.y} w={result.width} h={result.height} "
                    f"目标标题={result.new_title} 错误={result.error}"
                )

    def _wm_restore_windows_by_slots(
        self,
        move_windows: bool,
        rename_windows: bool,
        log,
        layout_params=None,
        current_window_count: int | None = None,
    ) -> bool:
        layout_params = layout_params or self._wm_current_slot_layout_params()
        if layout_params is None:
            return False
        slots_path = self._wm_slots_path(layout_params)
        if not self._wm_validate_slot_profile(
            layout_params=layout_params,
            current_window_count=current_window_count,
            log=log,
        ):
            return False
        title_template = self.wm_title_template_var.get().strip() or None
        log(f"检测到当前 profile 槽位文件 {slots_path.name}，按已保存槽位恢复布局")
        log("本次不会按 hwnd / 枚举顺序重新排序，不会覆盖其它 profile 槽位文件")
        try:
            results = restore_windows_by_slots(
                slots_path=slots_path,
                title_template=title_template,
                exclude_hwnds=self._wm_excluded_hwnds(),
                game_exe_path=self._wm_game_exe_path_filter(),
                move_windows=move_windows,
                rename_windows=rename_windows,
            )
        except Exception as exc:
            log(f"按槽位恢复失败：{exc}")
            messagebox.showerror("槽位恢复失败", str(exc))
            return False

        self._wm_log_slot_restore_results(results, log)
        success_count = sum(1 for result in results if result.success)
        failed_count = len(results) - success_count
        log(f"按槽位恢复完成：成功 {success_count}，失败 {failed_count}")
        return failed_count == 0

    def _wm_log_tile_results(self, results, log) -> None:
        for index, result in enumerate(results, start=1):
            window = result.window
            number = window.number if window.number is not None else "无编号"
            rect = window.rect
            wrap_text = "，因屏幕宽度自动换行" if result.wrapped_by_screen else ""
            if result.success:
                log(
                    f"窗口 {index} 排列成功 hwnd={window.hwnd} 编号={number} "
                    f"原始rect=({rect.left},{rect.top},{rect.right},{rect.bottom}) "
                    f"目标x={result.x} y={result.y} "
                    f"SetWindowPos width={result.width} SetWindowPos height={result.height}"
                    f"{wrap_text} 标题={window.title}"
                )
            else:
                log(
                    f"窗口 {index} 排列失败 hwnd={window.hwnd} 编号={number} "
                    f"原始rect=({rect.left},{rect.top},{rect.right},{rect.bottom}) "
                    f"目标x={result.x} y={result.y} "
                    f"SetWindowPos width={result.width} SetWindowPos height={result.height} "
                    f"错误={result.error}{wrap_text} 标题={window.title}"
                )

    def _wm_rename_windows_after_tile(
        self,
        log,
        exclude_hwnds: list[int],
        title_template: str | None = None,
        force_global: bool = False,
    ) -> None:
        if title_template is None:
            title_template = self._wm_read_title_template()
        if title_template is None:
            return
        layout_params = self._wm_current_slot_layout_params()
        if layout_params is not None and self._wm_has_saved_slots(layout_params) and not force_global:
            self._wm_restore_windows_by_slots(
                move_windows=False,
                rename_windows=True,
                log=log,
                layout_params=layout_params,
            )
            return
        log(f"开始自动编号标题：模板={title_template}")
        try:
            results = rename_game_windows(
                title_template,
                exclude_hwnds=exclude_hwnds,
                game_exe_path=self._wm_game_exe_path_filter(),
            )
        except Exception as exc:
            log(f"自动编号标题失败：{exc}")
            return

        for index, result in enumerate(results, start=1):
            window = result.window
            if result.success:
                log(f"窗口 {index} 重命名成功 hwnd={window.hwnd} 新标题={result.new_title}")
            else:
                log(
                    f"窗口 {index} 重命名失败 hwnd={window.hwnd} "
                    f"目标标题={result.new_title} 错误={result.error}"
                )

    def _wm_rename_windows(self) -> None:
        self._save_window_manager_settings()
        layout_params = self._wm_current_slot_layout_params()
        if layout_params is not None and self._wm_has_saved_slots(layout_params):
            self._wm_restore_windows_by_slots(
                move_windows=False,
                rename_windows=True,
                log=lambda message: self._log(f"[窗口管理] {message}"),
                layout_params=layout_params,
            )
            return
        self._wm_rename_windows_after_tile(
            log=lambda message: self._log(f"[窗口管理] {message}"),
            exclude_hwnds=self._wm_excluded_hwnds(),
        )

    def _wm_identify_windows(self) -> None:
        try:
            windows = list_game_windows(
                title_template=_safe_wm_title_template(self),
                exclude_hwnds=self._wm_excluded_hwnds(),
                game_exe_path=self._wm_game_exe_path_filter(),
                expected_window_size=_safe_wm_expected_window_size(self),
            )
        except Exception as exc:
            self._log(f"窗口管理：识别登录窗口失败：{exc}")
            messagebox.showerror("识别登录窗口失败", str(exc))
            return

        self._log(f"窗口管理：识别到 {len(windows)} 个斗罗大陆H5登录窗口。")
        if not windows:
            self._wm_log_zero_detection_hint()
        for index, window in enumerate(windows, start=1):
            number = window.number if window.number is not None else "无编号"
            rect = window.rect
            self._log(
                f"窗口管理：窗口 {index} hwnd={window.hwnd} 标题={window.title} 编号={number} "
                f"rect=({rect.left},{rect.top},{rect.right},{rect.bottom})"
            )

    def _wm_tile_windows(self) -> None:
        self._save_window_manager_settings()
        arrangement = self._wm_read_arrangement_config()
        if arrangement is None:
            return
        tile_mode, config = arrangement
        layout_params = self._wm_slot_layout_params(
            tile_mode,
            config,
            self.wm_title_template_var.get().strip(),
        )
        try:
            current_count = len(
                list_game_windows(
                    title_template=_safe_wm_title_template(self),
                    exclude_hwnds=self._wm_excluded_hwnds(),
                    game_exe_path=self._wm_game_exe_path_filter(),
                    expected_window_size=_safe_wm_expected_window_size(self),
                )
            )
        except Exception as exc:
            self._log(f"窗口管理：排列前识别窗口失败：{exc}")
            messagebox.showerror("排列登录窗口失败", str(exc))
            return
        if not self._wm_require_complete_windows("排列窗口", current_count, layout_params.target_window_count):
            return

        if self._wm_has_saved_slots(layout_params):
            if not self._wm_validate_slot_profile(
                layout_params=layout_params,
                current_window_count=current_count,
                log=lambda message: self._log(f"窗口管理：{message}"),
            ):
                return
            self._wm_start_action_worker(
                "排列窗口",
                self._wm_tile_windows_worker,
                (layout_params,),
            )
            return

        message = (
            f"当前 profile 尚未生成槽位：{self._wm_slots_path(layout_params).name}。\n"
            "普通“排列窗口”不会按 hwnd / 枚举顺序重新排序。\n"
            "如需按当前参数重排并保存槽位，请点击“重新生成槽位”。"
        )
        self._log(f"窗口管理：{message.replace(chr(10), ' ')}")
        messagebox.showwarning("当前 profile 无槽位", message)
        return

    def _wm_tile_windows_worker(self, layout_params) -> None:
        def log(message: str) -> None:
            self._queue_log(f"窗口管理：{message}")

        slots_path = self._wm_slots_path(layout_params)
        title_template = self.wm_title_template_var.get().strip() or None
        try:
            log(f"检测到当前 profile 槽位文件 {slots_path.name}，按已保存槽位恢复布局")
            log("本次不会按 hwnd / 枚举顺序重新排序，不会覆盖其它 profile 槽位文件")
            results = restore_windows_by_slots(
                slots_path=slots_path,
                title_template=title_template,
                exclude_hwnds=self._wm_excluded_hwnds(),
                game_exe_path=self._wm_game_exe_path_filter(),
                move_windows=True,
                rename_windows=True,
            )
        except Exception as exc:
            error = str(exc)
            log(f"按槽位恢复失败：{error}")
            self.after(0, lambda: messagebox.showerror("槽位恢复失败", error))
            return

        self._wm_log_slot_restore_results(results, log)
        success_count = sum(1 for result in results if result.success)
        failed_count = len(results) - success_count
        log(f"按槽位恢复完成：成功 {success_count}，失败 {failed_count}")

    def _wm_regenerate_slots(self) -> None:
        self._save_window_manager_settings()
        arrangement = self._wm_read_arrangement_config()
        if arrangement is None:
            return
        tile_mode, config = arrangement
        excluded_hwnds = self._wm_excluded_hwnds()
        layout_params = self._wm_slot_layout_params(
            tile_mode,
            config,
            self.wm_title_template_var.get().strip(),
        )
        try:
            current_count = len(
                list_game_windows(
                    title_template=_safe_wm_title_template(self),
                    exclude_hwnds=excluded_hwnds,
                    game_exe_path=self._wm_game_exe_path_filter(),
                    expected_window_size=_safe_wm_expected_window_size(self),
                )
            )
        except Exception as exc:
            self._log(f"窗口管理：重新生成槽位前识别窗口失败：{exc}")
            messagebox.showerror("重新生成槽位失败", str(exc))
            return
        target_count = layout_params.target_window_count
        if not self._wm_require_complete_windows("重新生成槽位", current_count, target_count):
            return

        confirmed = messagebox.askyesno(
            "重新生成槽位",
            "此操作会按当前 UI 参数重新排列并重新编号全部窗口，"
            "并覆盖当前 profile 的槽位文件。\n\n"
            f"当前检测到 {current_count} 个窗口，目标数量 {target_count}，数量一致。\n"
            "其它 profile 槽位文件不会被覆盖。\n\n是否继续？",
            parent=self,
        )
        if not confirmed:
            self._log("窗口管理：已取消重新生成槽位。")
            return

        self._wm_start_action_worker(
            "重新生成槽位",
            self._wm_regenerate_slots_worker,
            (tile_mode, config, excluded_hwnds, layout_params, target_count, self._wm_game_exe_path_filter()),
        )

    def _wm_regenerate_slots_worker(
        self,
        tile_mode: str,
        config: TileConfig | RowTileConfig,
        excluded_hwnds: list[int],
        layout_params,
        target_count: int | None,
        game_exe_path: str,
    ) -> None:
        try:
            self._queue_log(f"窗口管理：开始全局重新排列，排列方式={tile_mode}")
            self._queue_log(f"窗口管理：当前 profile 槽位文件={self._wm_slots_path(layout_params)}")
            results = self._wm_run_tile(
                tile_mode=tile_mode,
                tile_config=config,
                exclude_hwnds=excluded_hwnds,
                game_exe_path=game_exe_path,
                log=lambda message: self._queue_log(f"窗口管理：{message}"),
            )
        except Exception as exc:
            error = str(exc)
            self._queue_log(f"窗口管理：重新生成槽位失败：{error}")
            self.after(0, lambda: messagebox.showerror("重新生成槽位失败", error))
            return

        self._wm_log_tile_results(results, lambda message: self._queue_log(f"窗口管理：{message}"))
        failed_results = [result for result in results if not result.success]
        if failed_results:
            error = (
                f"排列窗口失败：{len(failed_results)} 个窗口移动失败，本次未写入槽位。"
                f"首个错误：{failed_results[0].error}"
            )
            self._queue_log(f"窗口管理：{error}")
            self.after(0, lambda message=error: messagebox.showerror("重新生成槽位失败", message))
            return
        if self.wm_auto_rename_after_tile_var.get():
            self._wm_rename_windows_after_tile(
                log=lambda message: self._queue_log(f"[窗口管理] {message}"),
                exclude_hwnds=excluded_hwnds,
                force_global=True,
            )

        try:
            slots = save_current_windows_as_slots(
                slots_path=self._wm_slots_path(layout_params),
                exclude_hwnds=excluded_hwnds,
                game_exe_path=game_exe_path,
                title_template=layout_params.title_template,
                layout_params=layout_params,
                expected_count=target_count,
            )
        except Exception as exc:
            error = str(exc)
            self._queue_log(f"窗口管理：排列完成，但保存当前 profile 槽位失败：{error}")
            self.after(0, lambda: messagebox.showerror("保存槽位失败", error))
            return

        self._queue_log(f"窗口管理：已重新生成并保存 {len(slots)} 个槽位到 {self._wm_slots_path(layout_params)}。")

    def _wm_repair_window_slot(self) -> None:
        self._save_window_manager_settings()
        game_path = self.wm_game_path_var.get().strip().strip('"')
        if not game_path:
            messagebox.showwarning("修复窗口", "请先填写游戏路径。")
            self._log("[窗口管理] 修复窗口失败：游戏路径为空。")
            return
        if not Path(game_path).exists():
            messagebox.showwarning("修复窗口", f"游戏路径不存在：{game_path}")
            self._log(f"[窗口管理] 修复窗口失败：游戏路径不存在：{game_path}")
            return

        try:
            slot_no = int(self.wm_repair_slot_var.get())
        except Exception:
            messagebox.showwarning("修复窗口", "目标槽位必须是整数。")
            return
        if slot_no < 1:
            messagebox.showwarning("修复窗口", "目标槽位必须大于 0。")
            return

        layout_params = self._wm_current_slot_layout_params()
        if layout_params is None:
            return
        target_count = layout_params.target_window_count
        if target_count is not None and slot_no > int(target_count):
            message = f"目标槽位 {slot_no} 超出当前目标窗口数 {target_count}。"
            self._log(f"[窗口管理] 修复窗口失败：{message}")
            messagebox.showwarning("修复窗口", message)
            return
        slots_path = self._wm_slots_path(layout_params)
        title_template = self.wm_title_template_var.get().strip() or None
        excluded_hwnds = self._wm_excluded_hwnds()
        fixed_config = self._wm_read_fixed_slot_config() if layout_params.mode == "fixed" else None
        try:
            slot, slot_source, resolve_error = resolve_window_slot_for_repair(
                slot_no=slot_no,
                slots_path=slots_path,
                title_template=title_template,
                fixed_config=fixed_config,
                exclude_hwnds=excluded_hwnds,
                game_exe_path=game_path,
                layout_params=layout_params,
            )
        except Exception as exc:
            self._log(f"[窗口管理] 解析 slot {slot_no} 失败：{exc}")
            messagebox.showerror("修复窗口", str(exc))
            return
        if slot is None:
            self._log(f"[窗口管理] {resolve_error}")
            messagebox.showwarning("修复窗口", resolve_error)
            return
        if slot_source == "slot_file":
            self._log(f"[窗口管理] slot {slot_no} 已从当前 profile 槽位文件读取：{slots_path.name}")
        elif slot_source == "slot_backup":
            self._log(f"[窗口管理] slot {slot_no} 已从当前 profile 最近备份槽位文件读取。")
        elif slot_source == "legacy_slot_file":
            self._log(f"[窗口管理] slot {slot_no} 已从 legacy window_slots.json 读取。")
        elif slot_source == "current_title":
            self._log(
                f"[窗口管理] slot {slot_no} 已从当前窗口标题补齐："
                f"hwnd={slot.hwnd} x={slot.x} y={slot.y} w={slot.width} h={slot.height}"
            )
        elif slot_source == "fixed_config":
            self._log(
                f"[窗口管理] slot {slot_no} 已根据固定排列参数推导："
                f"x={slot.x} y={slot.y} w={slot.width} h={slot.height}"
            )

        close_existing = False
        if slot.hwnd is not None and user32.IsWindow(int(slot.hwnd)):
            close_existing = messagebox.askyesno(
                "修复窗口",
                f"slot {slot_no} 的旧窗口仍存在 hwnd={slot.hwnd}。\n\n是否只关闭该旧窗口并启动 1 个新窗口补位？",
                parent=self,
            )
            if not close_existing:
                self._log(f"[窗口管理] 已取消修复 slot {slot_no}。")
                return

        self._wm_start_action_worker(
            "修复窗口",
            self._wm_repair_window_slot_worker,
            (slot_no, game_path, close_existing, title_template, excluded_hwnds, fixed_config, layout_params),
        )

    def _wm_repair_window_slot_worker(
        self,
        slot_no: int,
        game_path: str,
        close_existing: bool,
        title_template: str | None,
        excluded_hwnds: list[int],
        fixed_config: TileConfig | None,
        layout_params,
    ) -> None:
        def log(message: str) -> None:
            self._queue_log(f"[窗口管理] {message}")

        log(f"开始修复 slot {slot_no}")
        try:
            result = repair_window_slot(
                slot_no=slot_no,
                game_path=game_path,
                slots_path=self._wm_slots_path(layout_params),
                title_template=title_template,
                close_existing=close_existing,
                exclude_hwnds=excluded_hwnds,
                game_exe_path=game_path,
                fixed_config=fixed_config,
                layout_params=layout_params,
            )
        except Exception as exc:
            log(f"slot {slot_no} 修复异常：{exc}")
            return

        slot = result.slot
        source_text = {
            "slot_file": "当前 profile 槽位文件",
            "slot_backup": "当前 profile 最近备份槽位文件",
            "legacy_slot_file": "legacy window_slots.json",
            "current_title": "当前窗口标题",
            "fixed_config": "固定排列参数推导",
        }.get(result.slot_source, result.slot_source or "未知")
        log(f"slot {slot_no} 位置来源：{source_text}")
        log(f"读取 slot {slot_no}：x={slot.x} y={slot.y} w={slot.width} h={slot.height}")
        log(f"旧 hwnd={result.old_hwnd if result.old_hwnd else '无'}")
        if result.success:
            if result.slot.status == "已存在":
                log(f"当前桌面已存在窗口 {slot_no}，未启动新窗口，只更新 slot {slot_no} 映射")
            else:
                log("仅启动 1 个新窗口")
                log(f"检测到新 hwnd={result.new_hwnd}")
                log(f"新窗口已移动到 slot {slot_no}")
                log(f"新窗口已重命名为窗口 {slot_no}：{result.new_title}")
            log(f"slot {slot_no} 补位完成")
        elif result.requires_close_confirmation:
            log(f"slot {slot_no} 旧窗口仍存在，需确认后关闭旧窗口再补位：{result.error}")
        else:
            log(f"slot {slot_no} 修复失败：{result.error}")

    def _wm_close_windows(self) -> None:
        try:
            results = close_game_windows(
                exclude_hwnds=self._wm_excluded_hwnds(),
                game_exe_path=self._wm_game_exe_path_filter(),
                title_template=_safe_wm_title_template(self),
            )
        except Exception as exc:
            self._log(f"窗口管理：关闭登录窗口失败：{exc}")
            messagebox.showerror("关闭登录窗口失败", str(exc))
            return

        self._log(f"窗口管理：已向 {len(results)} 个斗罗大陆H5登录窗口发送关闭消息。")
        for index, result in enumerate(results, start=1):
            window = result.window
            number = window.number if window.number is not None else "无编号"
            if result.success:
                self._log(
                    f"窗口管理：窗口 {index} 关闭消息已发送 hwnd={window.hwnd} "
                    f"编号={number} 标题={window.title}"
                )
            else:
                self._log(
                    f"窗口管理：窗口 {index} 关闭消息发送失败 hwnd={window.hwnd} "
                    f"编号={number} 错误={result.error} 标题={window.title}"
                )

    def _track_process(self, proc: object) -> None:
        with self.running_processes_lock:
            self.running_processes.append(proc)

    def _untrack_process(self, proc: object) -> None:
        with self.running_processes_lock:
            if proc in self.running_processes:
                self.running_processes.remove(proc)

    def _terminate_running_processes(self) -> int:
        with self.running_processes_lock:
            processes = list(self.running_processes)

        terminated = 0
        for proc in processes:
            pid = getattr(proc, "pid", None)
            try:
                if proc.poll() is not None:
                    self._untrack_process(proc)
                    continue
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                    self._log(f"已终止账号运行子进程 pid={pid}。")
                except Exception:
                    proc.kill()
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        pass
                    self._log(f"账号运行子进程 terminate 超时，已强制 kill pid={pid}。")
                terminated += 1
            except Exception as exc:
                self._log(f"终止账号运行子进程失败 pid={pid}: {exc}")
            finally:
                self._untrack_process(proc)
        return terminated

    def _cleanup_dm_click_helper_processes(self) -> int:
        import subprocess as _sp

        script = r"""
$selfPid = $PID
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $selfPid -and (
        $_.CommandLine -like '*dm_click_helper.py*' -or
        $_.CommandLine -like '*dm_click_helper.exe*'
    )
}
$count = 0
foreach ($p in $procs) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        $count += 1
    } catch {
    }
}
Write-Output $count
"""
        try:
            result = _sp.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_sp.CREATE_NO_WINDOW,
                timeout=8,
            )
            output = (result.stdout or "").strip().splitlines()
            count = int(output[-1]) if output else 0
            self._log(f"已清理 dm_click_helper 子进程 {count} 个。")
            if result.stderr:
                self._write_file_log(f"清理 dm_click_helper stderr: {result.stderr.strip()[:500]}")
            return count
        except Exception as exc:
            self._log(f"清理 dm_click_helper 子进程失败：{exc}")
            return 0

    def _cleanup_chromium_processes(self) -> None:
        import subprocess as _sp

        try:
            result = _sp.run(
                ["taskkill", "/f", "/im", "chromium.exe"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_sp.CREATE_NO_WINDOW,
                timeout=8,
            )
            if result.returncode == 0:
                self._log("已清理 chromium.exe。")
            else:
                detail = (result.stdout or result.stderr or "").strip()
                self._log(f"chromium.exe 清理命令已执行：{detail or '未发现进程'}")
        except Exception as exc:
            self._log(f"清理 chromium.exe 失败：{exc}")

    def _cleanup_external_processes(self) -> None:
        self._cleanup_dm_click_helper_processes()
        self._cleanup_chromium_processes()

    def _pick_bookmark_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Bookmarks", "Bookmarks"), ("JSON", "*.json"), ("All files", "*.*")])
        if path:
            self._clear_bookmark_root_selection(clear_legacy=True)
            self._clear_loaded_accounts("收藏夹文件已切换，请重新选择账号目录并读取账号。")
            self.bookmark_path.set(path)
            self._refresh_bookmark_root_candidates(auto_select=True, allow_legacy_migration=False)
            self._save_bookmark_settings(path)

    def _auto_find_bookmarks(self) -> None:
        candidates = find_bookmark_file_candidates()
        self.bookmark_file_candidates = candidates
        self.bookmark_file_candidate_by_label = {}
        for candidate in candidates:
            root_count = len(scan_bookmark_root_candidates(candidate.path, candidate.browser, candidate.profile))
            base_label = _format_bookmark_file_candidate_label(candidate, root_count=root_count)
            label = base_label
            suffix = 2
            while label in self.bookmark_file_candidate_by_label:
                label = f"{base_label} ({suffix})"
                suffix += 1
            self.bookmark_file_candidate_by_label[label] = candidate
        labels = list(self.bookmark_file_candidate_by_label)
        self._method1_bookmark_candidate_combo["values"] = labels
        self._log(f"已自动查找收藏夹：发现 {len(candidates)} 个浏览器收藏夹候选")
        if not candidates:
            message = "未自动找到可用收藏夹账号目录，请手动选择 Bookmarks 文件。"
            self._log(message)
            messagebox.showinfo("自动查找收藏夹", message)
            return

        saved_path = self.bookmark_path.get().strip()
        selection = select_bookmark_candidate_for_startup(saved_path, candidates)
        if selection.candidate is not None:
            label = next(
                label for label, candidate in self.bookmark_file_candidate_by_label.items()
                if candidate == selection.candidate
            )
            self.bookmark_file_candidate_var.set(label)
            self._clear_bookmark_root_selection(clear_legacy=True)
            self._clear_loaded_accounts("收藏夹候选已自动选择，请重新读取账号。")
            self.bookmark_path.set(selection.candidate.path)
            self._log(f"已自动选择唯一收藏夹候选：{selection.candidate.display_name}")
            self._refresh_bookmark_root_candidates(auto_select=True, allow_legacy_migration=False)
            self._save_bookmark_settings(selection.candidate.path)
            return

        if saved_path:
            for label, candidate in self.bookmark_file_candidate_by_label.items():
                if str(candidate.path).lower() == saved_path.lower():
                    self.bookmark_file_candidate_var.set(label)
                    break
            self._log("已保留当前保存的收藏夹路径，自动扫描不会静默覆盖。")
            self._refresh_bookmark_root_candidates(auto_select=True)
        elif len(candidates) > 1:
            self._log("检测到多个收藏夹候选，请在下拉框中选择。")

    def _on_bookmark_candidate_selected(self) -> None:
        candidate = self.bookmark_file_candidate_by_label.get(self.bookmark_file_candidate_var.get())
        if candidate is None:
            return
        current_path = self.bookmark_path.get().strip()
        if _normalize_path_for_compare(current_path) != _normalize_path_for_compare(candidate.path):
            self._clear_bookmark_root_selection(clear_legacy=True)
            self._clear_loaded_accounts("收藏夹候选已切换，请重新选择账号目录并读取账号。")
        self.bookmark_path.set(candidate.path)
        self._log(f"已选择收藏夹：{candidate.display_name}")
        self._refresh_bookmark_root_candidates(auto_select=True, allow_legacy_migration=False)
        self._save_bookmark_settings(candidate.path)

    def _clear_bookmark_root_selection(self, clear_legacy: bool = False) -> None:
        self.bookmark_root_candidates = []
        self.bookmark_root_candidate_by_label = {}
        self.bookmark_root_candidate_var.set("")
        self.bookmark_root_path.set("")
        self.bookmark_root_guid.set("")
        self.bookmark_root_parent_path.set("")
        self.bookmark_root_display_name.set("")
        if clear_legacy:
            self.bookmark_root_name.set("")
        if hasattr(self, "_method1_root_combo"):
            self._method1_root_combo["values"] = ()

    def _clear_loaded_accounts(self, reason: str) -> None:
        self.accounts = []
        self.status_by_key.clear()
        self.passport_by_key.clear()
        self.timing_by_key.clear()
        if hasattr(self, "level_box"):
            self._refresh_mode_account_scope()
        if reason:
            self._status_left.set(reason)
            self._log(reason)

    def _refresh_bookmark_root_candidates(
        self,
        auto_select: bool = False,
        allow_legacy_migration: bool = True,
    ) -> None:
        bookmark_file = self.bookmark_path.get().strip()
        if not bookmark_file or not Path(bookmark_file).exists():
            self._clear_bookmark_root_selection(clear_legacy=False)
            return

        info = describe_bookmark_file(bookmark_file)
        candidates = scan_bookmark_root_candidates(bookmark_file, browser=info.browser, profile=info.profile)
        self.bookmark_root_candidates = candidates
        self.bookmark_root_candidate_by_label = {
            candidate.display_label: candidate
            for candidate in candidates
        }
        labels = list(self.bookmark_root_candidate_by_label)
        self._method1_root_combo["values"] = labels
        self._log(f"已扫描账号目录：发现 {len(candidates)} 个可用目录")
        if not candidates:
            self._clear_bookmark_root_selection(clear_legacy=False)
            return

        saved_root_path = self.bookmark_root_path.get().strip()
        if saved_root_path:
            for label, candidate in self.bookmark_root_candidate_by_label.items():
                if candidate.root_path == saved_root_path:
                    self.bookmark_root_candidate_var.set(label)
                    self._apply_bookmark_root_candidate(candidate, save=True)
                    return
            self._log("保存的账号目录路径已不存在，请重新选择账号目录。")
            self.bookmark_root_path.set("")

        legacy_root_name = self.bookmark_root_name.get().strip() if allow_legacy_migration else ""
        if legacy_root_name:
            matches = [
                candidate for candidate in candidates
                if candidate.display_name.split(" / ")[-1].replace("（直接链接）", "") == legacy_root_name
            ]
            if len(matches) == 1:
                candidate = matches[0]
                self.bookmark_root_candidate_var.set(candidate.display_label)
                self._apply_bookmark_root_candidate(candidate, save=True)
                self._log(f"已将旧目录名配置迁移为账号目录：{candidate.display_label}")
                return
            if len(matches) > 1:
                self._log(f"旧目录名“{legacy_root_name}”匹配到多个账号目录，请手动选择。")

        if auto_select and len(candidates) == 1:
            candidate = candidates[0]
            label = candidate.display_label
            self.bookmark_root_candidate_var.set(label)
            self._apply_bookmark_root_candidate(candidate, save=False)
            self._log(f"已选择账号目录：{candidate.display_name}，{candidate.link_count}个账号")
        elif auto_select:
            self._log("检测到多个账号目录候选，请在账号目录下拉框中选择。")

    def _on_bookmark_root_candidate_selected(self) -> None:
        candidate = self.bookmark_root_candidate_by_label.get(self.bookmark_root_candidate_var.get())
        if candidate is None:
            return
        bookmark_file = self.bookmark_path.get().strip()
        if not _root_candidate_belongs_to_bookmark_file(candidate, bookmark_file):
            self._clear_bookmark_root_selection(clear_legacy=True)
            self._clear_loaded_accounts("当前账号目录候选不属于当前收藏夹文件，请重新选择账号目录。")
            messagebox.showwarning("账号目录不匹配", "当前账号目录候选不属于当前收藏夹文件，请重新选择账号目录。")
            return
        self._clear_loaded_accounts("账号目录已切换，请点击“读取账号”。")
        self._apply_bookmark_root_candidate(candidate, save=True)
        self._log(f"已选择账号目录：{candidate.display_name}，{candidate.link_count}个账号")

    def _apply_bookmark_root_candidate(self, candidate, save: bool) -> None:
        self.bookmark_root_path.set(candidate.root_path)
        self.bookmark_root_guid.set(str(getattr(candidate, "guid", "") or ""))
        self.bookmark_root_parent_path.set(str(getattr(candidate, "parent_path", "") or ""))
        self.bookmark_root_display_name.set(candidate.display_name)
        self.bookmark_root_name.set(candidate.display_name.split(" / ")[-1].replace("（直接链接）", ""))
        if save:
            self._save_bookmark_settings(candidate.bookmark_file)

    def _selected_bookmark_root_candidate_for_load(
        self,
        bookmark_file: str,
        root_path: str,
    ) -> BookmarkRootCandidate | None:
        selected_label = self.bookmark_root_candidate_var.get().strip()
        if selected_label:
            candidate = self.bookmark_root_candidate_by_label.get(selected_label)
            if candidate is None:
                raise ValueError("当前账号目录候选已失效，请重新选择账号目录。")
            if not _root_candidate_belongs_to_bookmark_file(candidate, bookmark_file):
                raise ValueError("当前账号目录候选不属于当前收藏夹文件，请重新选择账号目录。")
            return candidate

        if root_path:
            candidate = find_bookmark_root_candidate_by_path(bookmark_file, root_path)
            if candidate is None:
                self._refresh_bookmark_root_candidates(auto_select=False, allow_legacy_migration=False)
                raise ValueError("保存的账号目录路径不存在，请在账号目录下拉框中重新选择。")
            return candidate

        return None

    def _pick_settings(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if path:
            self.settings_path.set(path)

    def _load_default_config_if_present(self) -> None:
        self._load_accounts()

    def _load_accounts(self) -> None:
        try:
            paths = ensure_refresh_data_dir()
            refresh_store = AccountsStore(paths.accounts_path)
            refresh_accounts = refresh_store.load()
            if refresh_store.load_error is not None:
                raise RuntimeError("刷新地址账号库无法读取")
            self.login_account_roster_store = LoginAccountRosterStore(paths.login_accounts_path)
            rows = self.login_account_roster_store.reconcile(refresh_accounts)
            links = DirectLinkStore(paths.direct_links_path)
            settings = load_settings(self.settings_path.get())
            previous_status = dict(getattr(self, "status_by_key", {}) or {})
            previous_passport = dict(getattr(self, "passport_by_key", {}) or {})
            previous_timing = dict(getattr(self, "timing_by_key", {}) or {})
            self.accounts = build_launcher_accounts(rows, links.links, settings.account_group_settings)
            self.status_by_key = {account.key: previous_status.get(account.key, "未开始") for account in self.accounts}
            self.passport_by_key = {account.key: previous_passport.get(account.key, "") for account in self.accounts}
            self.timing_by_key = {account.key: previous_timing.get(account.key, "") for account in self.accounts}
            self._refresh_mode_account_scope()
            self.account_source_summary_var.set(
                f"账号库 {len(refresh_accounts)} 个 / 参与上号 {len(self.accounts)} 个"
            )
            self._log(f"已从刷新地址账号库加载 {len(self.accounts)} 个参与上号账号。{self._account_count_summary()}")
        except Exception as exc:
            self._clear_loaded_accounts("刷新地址账号库读取失败，账号列表已清空。")
            self.account_source_summary_var.set("刷新地址账号库读取失败")
            self._log(f"读取刷新地址账号库失败: {mask_sensitive_text(str(exc))}")

    def _account_count_summary(self, accounts: list[AccountConfig] | None = None) -> str:
        source = accounts if accounts is not None else self.accounts
        parts = []
        for level in self._account_group_order(source):
            count = sum(1 for account in source if account.level == level)
            if count:
                parts.append(f"{level} {count} 个")
        return "分类：" + "，".join(parts) if parts else "分类：无账号"

    def _account_group_order(self, accounts: list[AccountConfig] | None = None) -> tuple[str, ...]:
        source = accounts if accounts is not None else self.accounts
        return _account_group_order_for_accounts(tuple(source))

    def _account_group_counts(self, accounts: list[AccountConfig]) -> list[tuple[str, int]]:
        return [
            (level, sum(1 for account in accounts if account.level == level))
            for level in self._account_group_order(accounts)
        ]

    def _format_group_names(self, group_names: list[str]) -> str:
        return "、".join(group_names) if group_names else "无"

    def _open_account_group_settings(self) -> None:
        group_counts = self._account_group_counts(self.accounts)
        if not group_counts:
            messagebox.showwarning("无账号分组", "刷新地址账号库中没有参与上号的账号。")
            return

        include_by_group = {
            group_name: any(account.include_in_all for account in self.accounts if account.level == group_name)
            for group_name, _ in group_counts
        }
        dialog = tk.Toplevel(self)
        dialog.title("全部串行分组设置")
        dialog.transient(self)
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="勾选后，该分组会参与“全部串行”；未勾选分组仍可单独选择运行。",
            foreground="#555555",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(frame, text="分组名", font=("", 9, "bold")).grid(row=1, column=0, sticky="w", padx=(0, 18))
        ttk.Label(frame, text="账号数", font=("", 9, "bold")).grid(row=1, column=1, sticky="e", padx=(0, 18))
        ttk.Label(frame, text="参与全部串行", font=("", 9, "bold")).grid(row=1, column=2, sticky="w")

        vars_by_group: dict[str, tk.BooleanVar] = {}
        for row_index, (group_name, count) in enumerate(group_counts, start=2):
            ttk.Label(frame, text=group_name).grid(row=row_index, column=0, sticky="w", pady=4, padx=(0, 18))
            ttk.Label(frame, text=f"{count} 个").grid(row=row_index, column=1, sticky="e", pady=4, padx=(0, 18))
            var = tk.BooleanVar(value=include_by_group.get(group_name, False))
            vars_by_group[group_name] = var
            ttk.Checkbutton(frame, variable=var).grid(row=row_index, column=2, sticky="w", pady=4)

        button_row = ttk.Frame(frame)
        button_row.grid(row=len(group_counts) + 2, column=0, columnspan=3, sticky="e", pady=(12, 0))

        def _save() -> None:
            selected = {group_name: bool(var.get()) for group_name, var in vars_by_group.items()}
            try:
                self._save_account_group_settings(selected)
            except Exception as exc:
                messagebox.showerror("保存失败", str(exc), parent=dialog)
                self._log(f"保存全部串行分组设置失败：{exc}")
                return
            dialog.destroy()
            messagebox.showinfo("已保存", "全部串行分组设置已保存并立即生效。", parent=self)

        ttk.Button(button_row, text="保存", width=10, command=_save).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(button_row, text="取消", width=10, command=dialog.destroy).pack(side=tk.RIGHT)

        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dialog.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.grab_set()
        dialog.focus_set()

    def _save_account_group_settings(self, include_by_group: dict[str, bool]) -> None:
        settings_path = Path(self.settings_path.get())
        data: dict[str, object] = {}
        if settings_path.exists():
            raw_data = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            if isinstance(raw_data, dict):
                data = raw_data

        current_settings = load_settings(settings_path).account_group_settings
        merged = _merge_account_group_settings(current_settings, include_by_group)
        data["account_group_settings"] = merged
        settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        self.accounts = [
            replace(
                account,
                include_in_all=bool(merged.get(account.level, {}).get("include_in_all", False)),
            )
            for account in self.accounts
        ]
        self._refresh_table()
        self._refresh_account_choices()

        enabled = [group_name for group_name, enabled_flag in include_by_group.items() if enabled_flag]
        disabled = [group_name for group_name, enabled_flag in include_by_group.items() if not enabled_flag]
        self._log("已保存全部串行分组设置：")
        self._log(f"启用：{self._format_group_names(enabled)}")
        self._log(f"未启用：{self._format_group_names(disabled)}")
        self._log("说明：层级=全部只影响账号列表显示；全部串行只执行已勾选分组。")

    def _is_row_count_account_mode(self) -> bool:
        return self._wm_mode_key_from_label() == TILE_MODE_ROW_COUNT

    def _allowed_level_values(self) -> tuple[str, ...]:
        return _allowed_level_values_for_accounts(tuple(self._mode_allowed_accounts()))

    def _is_account_allowed_in_current_mode(self, account: AccountConfig) -> bool:
        return True

    def _mode_allowed_accounts(self) -> list[AccountConfig]:
        return [account for account in self.accounts if self._is_account_allowed_in_current_mode(account)]

    def _filtered_accounts_for_ui(self) -> list[AccountConfig]:
        mode_accounts = self._mode_allowed_accounts()
        level = self.level_var.get()
        if level == "全部":
            return [account for account in mode_accounts if account.include_in_all]
        return [account for account in mode_accounts if account.level == level]

    def _on_level_changed(self) -> None:
        self._refresh_table()
        self._refresh_account_choices()
        self._sync_client_direct_port_range()
        self._log(
            f"层级已切换：排列方式={self.wm_tile_mode_var.get()}，"
            f"层级={self.level_var.get()}，当前账号列表 {len(self._filtered_accounts_for_ui())} 个。"
        )
        if self.level_var.get() == "全部":
            filtered = self._filtered_accounts_for_ui()
            if filtered:
                self._log("层级=全部：只显示并运行已勾选参与全部串行的账号。")
            else:
                self._log("层级=全部：当前没有勾选参与全部串行的账号。")
                self._status_left.set("当前没有勾选参与全部串行的账号")

    def _refresh_mode_account_scope(self, log_change: bool = False) -> None:
        allowed_levels = self._allowed_level_values()
        self.level_box["values"] = allowed_levels
        if self.level_var.get() not in allowed_levels:
            self.level_var.set(_default_level_for_allowed_values(self.level_var.get(), allowed_levels))
        self.account_var.set("")
        self.account_box["values"] = ()
        for item in self.tree.selection():
            self.tree.selection_remove(item)
        self._refresh_table()
        self._refresh_account_choices()
        self._sync_client_direct_port_range()
        if log_change:
            self._log(
                f"排列方式已切换：{self.wm_tile_mode_var.get()}；"
                f"允许层级={', '.join(allowed_levels)}；"
                f"当前账号列表 {len(self._filtered_accounts_for_ui())} 个。"
            )

    def _validate_accounts_for_current_mode(self, accounts: list[AccountConfig]) -> bool:
        for account in accounts:
            if not self._is_account_allowed_in_current_mode(account):
                message = "当前账号不属于当前排列模式，请重新选择层级和账号。"
                self._log(
                    f"阻止运行：{message} 排列方式={self.wm_tile_mode_var.get()}，"
                    f"层级={account.level}，账号={account.display_name}"
                )
                messagebox.showwarning("账号模式不匹配", message)
                return False

        for account in accounts:
            selected, candidates = select_login_window_by_game_no(account.game_window_no)
            if selected is None:
                h5_candidates = [window for window in candidates if window.title.strip() == GAME_TITLE_KEYWORD]
                numbered_candidates = [
                    window for window in h5_candidates
                    if extract_window_number(window.title, title_template=_safe_wm_title_template(self)) is not None
                ]
                if h5_candidates and not numbered_candidates:
                    message = (
                        "当前检测到 H5 窗口，但窗口未编号。\n"
                        "请先点击“重命名”或“排列窗口 + 重命名”。"
                    )
                    self._log(
                        f"阻止运行：当前桌面存在 {len(h5_candidates)} 个未编号 H5 窗口，"
                        f"目标窗口={account.game_window_no}，账号={account.display_name}"
                    )
                    messagebox.showwarning("窗口未编号", message)
                    return False
                message = f"未在当前桌面找到窗口 {account.game_window_no}，已停止，避免跨桌面运行。"
                self._log(
                    f"阻止运行：{message} 排列方式={self.wm_tile_mode_var.get()}，"
                    f"层级={account.level}，账号={account.display_name}"
                )
                messagebox.showwarning("当前桌面窗口不存在", message)
                return False
        return True

    def _visible_h5_window_numbers(self) -> tuple[int, ...]:
        windows = list_game_windows(
            title_template=_safe_wm_title_template(self),
            exclude_hwnds=self._wm_excluded_hwnds(),
            game_exe_path=self._wm_game_exe_path_filter(),
            expected_window_size=_safe_wm_expected_window_size(self),
        )
        return tuple(
            sorted(
                {
                    int(window.number)
                    for window in windows
                    if window.number is not None
                }
            )
        )

    def _precheck_serial_run(self, accounts: list[AccountConfig], run_label: str) -> bool:
        try:
            visible_window_numbers = self._visible_h5_window_numbers()
        except Exception as exc:
            message = f"{run_label}预检失败：无法读取当前桌面 H5 窗口：{exc}"
            self._log(message)
            messagebox.showwarning("运行前预检失败", message)
            return False

        plan = _build_serial_run_plan(accounts, visible_window_numbers)
        group_summary = _format_group_counts(plan.group_counts)
        required_summary = _compact_number_ranges(plan.required_windows)
        visible_summary = _compact_number_ranges(plan.visible_windows)
        missing_summary = _compact_number_ranges(plan.missing_windows)

        self._log(
            f"{run_label} run_plan：分组={group_summary}；账号数={len(plan.accounts)}；"
            f"需要窗口={required_summary}；最大窗口号={plan.max_window_no}；"
            f"当前桌面窗口={visible_summary}。"
        )

        if not plan.missing_windows:
            return True

        lines = [
            f"{run_label}预检失败：",
            f"本次将执行分组：{group_summary}",
            f"本次需要窗口：{required_summary}",
            f"当前桌面只有窗口：{visible_summary}",
            f"缺少窗口：{missing_summary}",
        ]
        if run_label == "全部串行":
            lines.extend(
                [
                    "",
                    "如需只运行当前层级，请选择“当前层串行”。",
                    "如需运行全部串行，请先打开足够窗口，或在“全部串行分组设置”中取消不需要的分组。",
                ]
            )
        message = "\n".join(lines)
        for line in lines:
            if line:
                self._log(line)
        messagebox.showwarning("运行前预检失败", message)
        return False

    def _refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for account in self._filtered_accounts_for_ui():
            self.tree.insert(
                "",
                tk.END,
                iid=account.key,
                values=_account_table_values(
                    account,
                    window_title=_bound_window_title(self, account),
                    passport=self.passport_by_key.get(account.key, ""),
                    status=self.status_by_key.get(account.key, "未开始"),
                    timing=self.timing_by_key.get(account.key, ""),
                ),
            )

    def _refresh_account_choices(self) -> None:
        choices = [account.display_name for account in self._filtered_accounts_for_ui()]
        self.account_box["values"] = choices
        self.account_var.set(choices[0] if choices else "")

    def _client_direct_current_scope_accounts(self, action_name: str) -> list[AccountConfig] | None:
        if _run_mode_key_for_owner(self) != "client_direct":
            message = "请先切换到客户端直登模式。"
            self._log(f"阻止{action_name}：{message}")
            messagebox.showwarning(action_name, message)
            return None
        accounts = self._filtered_accounts_for_ui()
        if not accounts:
            level = self.level_var.get()
            message = "当前没有可运行账号。" if level == "全部" else f"当前层 {level} 没有账号。"
            self._log(f"阻止{action_name}：{message}")
            messagebox.showwarning(action_name, message)
            return None
        return LauncherApp._client_direct_accounts_with_local_links(self, accounts)

    def _load_client_direct_sessions(self) -> None:
        try:
            self.client_batch_store.load()
        except Exception as exc:
            self._log(f"[客户端批次] 读取批次文件失败：{mask_sensitive_text(str(exc))}")
            return
        if not self.client_batch_store.batches:
            self._sync_client_direct_batch_status()
            return
        kept_count = len(self.client_batch_store.batches)
        try:
            self.client_batch_store.refresh_all_batch_statuses(
                pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
                process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
                cdp_available=lambda port: LauncherApp._client_direct_cdp_available(self, port),
                hwnd_valid=lambda hwnd: LauncherApp._client_direct_is_window_alive(self, hwnd),
            )
            kept_count = len(self.client_batch_store.batches)
            self.client_batch_store.save()
        except Exception as exc:
            self._log(f"[批次恢复] 刷新批次状态失败：{mask_sensitive_text(str(exc))}")
        LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        self._sync_client_direct_batch_status()
        self._log(f"[批次恢复] 已刷新历史批次 {kept_count} 个；仅标记异常绑定，不自动清理批次。")
        if not self.client_batch_store.batches:
            return
        batch = self.client_batch_store.current_batch()
        self._log(
            f"[客户端批次] 已恢复当前批次：{batch.batch_name}，"
            f"绑定数={len(batch.bindings)}，base_port={batch.base_port}"
        )

    def _client_direct_batch_short_id(self, batch_id: str) -> str:
        text = str(batch_id or "")
        return text[-10:] if len(text) > 10 else text

    def _client_direct_batch_display(self, batch) -> str:
        counts = LauncherApp._client_direct_batch_counts(self, batch)
        return (
            f"{batch.batch_name} | 绑定{counts['bound']} | 存活{counts['alive']} | "
            f"端口{LauncherApp._client_direct_batch_port_range_text(self, batch)}"
        )

    def _client_direct_selected_batch_id(self) -> str:
        var = getattr(self, "client_direct_batch_select_var", None)
        if var is None:
            return ""
        try:
            text = str(var.get() or "")
        except Exception:
            return ""
        display_map = getattr(self, "client_direct_batch_display_id_map", {})
        if text in display_map:
            return str(display_map[text] or "")
        if "|" not in text:
            return ""
        return text.rsplit("|", 1)[-1].strip()

    def _ensure_client_direct_selected_batch_current(self) -> None:
        if not hasattr(self, "client_batch_store") or not self.client_batch_store.batches:
            return
        selected_batch_id = LauncherApp._client_direct_selected_batch_id(self)
        if selected_batch_id and selected_batch_id != self.client_batch_store.active_batch_id:
            self.client_batch_store.switch_batch(selected_batch_id)
            LauncherApp._restore_client_direct_bindings_from_active_batch(self)

    def _sync_client_direct_batch_options(self) -> None:
        box = getattr(self, "client_direct_batch_box", None)
        var = getattr(self, "client_direct_batch_select_var", None)
        if box is None or var is None or not hasattr(self, "client_batch_store"):
            return
        displays = [LauncherApp._client_direct_batch_display(self, batch) for batch in self.client_batch_store.batches]
        self.client_direct_batch_display_id_map = {
            display: batch.batch_id
            for display, batch in zip(displays, self.client_batch_store.batches)
        }
        try:
            box.configure(values=displays if displays else ("无可用批次",))
        except Exception:
            pass
        if not displays:
            try:
                var.set("无可用批次")
            except Exception:
                pass
            return
        current = self.client_batch_store.current_batch()
        current_display = LauncherApp._client_direct_batch_display(self, current)
        try:
            if var.get() != current_display:
                var.set(current_display)
        except Exception:
            pass

    def _on_client_direct_batch_selected(self) -> None:
        if not hasattr(self, "client_batch_store") or not self.client_batch_store.batches:
            return
        selected_batch_id = LauncherApp._client_direct_selected_batch_id(self)
        if selected_batch_id:
            self.client_batch_store.switch_batch(selected_batch_id)
            LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        LauncherApp._sync_client_direct_batch_status(self)

    def _client_direct_batch_port_range_text(self, batch) -> str:
        ports = sorted(int(binding.cdp_port or 0) for binding in batch.bindings if int(binding.cdp_port or 0) > 0)
        if ports:
            return f"{ports[0]}~{ports[-1]}"
        base = int(batch.base_port or CLIENT_DIRECT_CDP_PORT)
        count = len(batch.bindings)
        if count > 0:
            return f"{base}~{base + count - 1}"
        return f"{base}~{base}"

    def _client_direct_batch_counts(self, batch) -> dict[str, int]:
        closed_statuses = {"pid_missing", "scan_missing", "未找到", "已失联", "客户端已关闭", "closed", "已关闭"}
        cdp_statuses = {"cdp_port_missing", "cdp_unavailable", "CDP不可用"}
        hwnd_statuses = {"hwnd_invalid", "窗口已失效"}
        binding_invalid_statuses = {
            "pid_not_x5game",
            "binding_invalid",
            "hwnd_pid_mismatch",
            "cdp_owner_unverified",
            "cdp_owner_mismatch",
            "cdp_owner_conflict",
        }
        counts = {
            "bound": len(batch.bindings),
            "closed": 0,
            "cdp_unavailable": 0,
            "hwnd_invalid": 0,
            "binding_invalid": 0,
            "alive": 0,
        }
        for binding in batch.bindings:
            status = str(getattr(binding, "window_status", "") or binding.status or "")
            if status in closed_statuses:
                counts["closed"] += 1
            elif status in cdp_statuses:
                counts["cdp_unavailable"] += 1
            elif status in hwnd_statuses:
                counts["hwnd_invalid"] += 1
            elif status in binding_invalid_statuses:
                counts["binding_invalid"] += 1
            else:
                counts["alive"] += 1
        return counts

    def _client_direct_batch_status_text(self, batch) -> str:
        counts = LauncherApp._client_direct_batch_counts(self, batch)
        return (
            f"当前批次：{batch.batch_name} "
            f"id={LauncherApp._client_direct_batch_short_id(self, batch.batch_id)} "
            f"绑定={counts['bound']} 存活={counts['alive']} 已关闭={counts['closed']} "
            f"CDP不可用={counts['cdp_unavailable']} 窗口失效={counts['hwnd_invalid']} "
            f"绑定异常={counts['binding_invalid']} "
            f"端口={LauncherApp._client_direct_batch_port_range_text(self, batch)}"
        )

    def _client_direct_batch_stats_text(self, batch=None) -> str:
        if batch is None:
            counts = {"bound": 0, "alive": 0, "closed": 0, "cdp_unavailable": 0, "hwnd_invalid": 0, "binding_invalid": 0}
        else:
            counts = LauncherApp._client_direct_batch_counts(self, batch)
        return (
            f"绑定={counts['bound']} | 存活={counts['alive']} | 已关闭={counts['closed']} | "
            f"CDP不可用={counts['cdp_unavailable']} | 窗口失效={counts['hwnd_invalid']} | "
            f"绑定异常={counts['binding_invalid']}"
        )

    def _sync_client_direct_batch_status(self) -> None:
        var = getattr(self, "client_direct_batch_status_var", None)
        if var is None:
            return
        try:
            if not self.client_batch_store.batches:
                var.set(LauncherApp._client_direct_batch_stats_text(self))
                if hasattr(self, "_status_right"):
                    self._status_right.set("当前批次：无")
                delete_btn = getattr(self, "client_direct_delete_batch_btn", None)
                if delete_btn is not None:
                    delete_btn.configure(state=tk.DISABLED)
                LauncherApp._sync_client_direct_batch_options(self)
                return
            batch = self.client_batch_store.current_batch()
            status_text = LauncherApp._client_direct_batch_status_text(self, batch)
            var.set(LauncherApp._client_direct_batch_stats_text(self, batch))
            if hasattr(self, "_status_right"):
                self._status_right.set(status_text)
            delete_btn = getattr(self, "client_direct_delete_batch_btn", None)
            if delete_btn is not None:
                delete_btn.configure(state=tk.NORMAL)
            self.client_direct_base_port_var.set(int(batch.base_port or CLIENT_DIRECT_CDP_PORT))
            LauncherApp._sync_client_direct_batch_options(self)
        except Exception:
            var.set(LauncherApp._client_direct_batch_stats_text(self))
            if hasattr(self, "_status_right"):
                self._status_right.set("当前批次：无")
            delete_btn = getattr(self, "client_direct_delete_batch_btn", None)
            if delete_btn is not None:
                delete_btn.configure(state=tk.DISABLED)

    def _record_from_batch_binding(self, binding: ClientBatchBinding) -> ClientDirectRunRecord:
        return ClientDirectRunRecord(
            account_id=binding.account_id,
            account_name=binding.account_name,
            account_key=binding.account_key,
            refresh_account_name=binding.refresh_account_name,
            bookmark_path=binding.bookmark_path,
            slot_index=binding.slot_index,
            identity_status=binding.identity_status,
            link_status=binding.link_status,
            window_status=binding.window_status,
            pid=int(binding.pid or 0),
            hwnd=int(binding.hwnd or 0),
            title=str(getattr(binding, "title", "") or ""),
            cdp_port=int(binding.cdp_port or 0),
            cdp_owner_pid=int(getattr(binding, "cdp_owner_pid", 0) or 0),
            cdp_ownership_status=str(getattr(binding, "cdp_ownership_status", "") or ""),
            speed_rate=float(getattr(binding, "speed_rate", 1.0) or 1.0),
            login_url=binding.login_url,
            status=binding.status,
            error_message=binding.error_message,
        )

    def _batch_binding_from_record(self, record: ClientDirectRunRecord) -> ClientBatchBinding:
        return ClientBatchBinding(
            account_id=record.account_id,
            account_name=record.account_name,
            account_key=record.account_key or record.account_id,
            refresh_account_name=record.refresh_account_name,
            bookmark_path=record.bookmark_path,
            slot_index=record.slot_index,
            identity_status=record.identity_status or "resolved",
            link_status=record.link_status,
            window_status=record.window_status,
            pid=int(record.pid or 0),
            hwnd=int(record.hwnd or 0),
            title=str(getattr(record, "title", "") or ""),
            cdp_port=int(record.cdp_port or 0),
            cdp_owner_pid=int(getattr(record, "cdp_owner_pid", 0) or 0),
            cdp_ownership_status=str(getattr(record, "cdp_ownership_status", "") or ""),
            speed_rate=float(getattr(record, "speed_rate", 1.0) or 1.0),
            login_url=record.login_url,
            status=record.status,
            error_message=record.error_message,
        )

    def _restore_client_direct_bindings_from_active_batch(self) -> None:
        if not hasattr(self, "client_batch_store") or not self.client_batch_store.batches:
            self.client_direct_bindings = {}
            return
        try:
            batch = self.client_batch_store.current_batch()
        except Exception:
            self.client_direct_bindings = {}
            return
        self.client_direct_bindings = {
            binding.account_id: LauncherApp._record_from_batch_binding(self, binding)
            for binding in batch.bindings
        }

    def _save_client_direct_bindings_to_active_batch(self, *, sync_ui: bool = True) -> None:
        if not hasattr(self, "client_batch_store"):
            return
        batch_bindings = [
            LauncherApp._batch_binding_from_record(self, record)
            for record in self.client_direct_bindings.values()
        ]
        for index, binding in enumerate(batch_bindings, start=1):
            if int(binding.slot_index or 0) <= 0:
                binding.slot_index = index
        self.client_batch_store.replace_current_bindings(batch_bindings)
        self.client_batch_store.save()
        if sync_ui:
            self._sync_client_direct_batch_status()

    def _save_client_direct_bindings_to_active_batch_threadsafe(self, *, sync_ui: bool = True) -> None:
        lock = getattr(self, "client_direct_bindings_lock", None)
        if lock is None:
            lock = threading.RLock()
            try:
                self.client_direct_bindings_lock = lock
            except Exception:
                lock = None
        if lock is None:
            LauncherApp._save_client_direct_bindings_to_active_batch(self, sync_ui=sync_ui)
            return
        with lock:
            LauncherApp._save_client_direct_bindings_to_active_batch(self, sync_ui=sync_ui)

    def _account_for_client_direct_record(self, record: ClientDirectRunRecord) -> AccountConfig:
        for account in getattr(self, "accounts", []):
            if account.key == record.account_id:
                return account
        return ClientDirectAccountRef(
            key=record.account_id,
            display_name=record.account_name or record.account_id,
            url=record.login_url,
        )

    def _client_direct_accounts_from_active_batch(self) -> list[AccountConfig]:
        if not hasattr(self, "client_batch_store") or not self.client_batch_store.batches:
            if getattr(self, "client_direct_bindings", None):
                return [
                    LauncherApp._account_for_client_direct_record(self, record)
                    for record in self.client_direct_bindings.values()
                ]
            try:
                accounts = LauncherApp._client_direct_current_scope_accounts(self, "客户端批次")
                return accounts or []
            except Exception:
                return []
        LauncherApp._ensure_client_direct_selected_batch_current(self)
        batch = self.client_batch_store.current_batch()
        try:
            candidates = list(self._filtered_accounts_for_ui())
        except Exception:
            candidates = []
        resolution = _resolve_client_direct_batch_accounts(self, batch, candidates)
        if resolution.status != "resolved":
            self._client_direct_identity_error = resolution.message
            logger = getattr(self, "_log", None)
            if callable(logger):
                logger(f"[客户端直登] 账号身份解析失败：{resolution.message}")
            return []
        self._client_direct_identity_error = ""
        self.client_batch_store.save()
        LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        return resolution.accounts

    def _client_direct_scope_label(self) -> str:
        level = self.level_var.get()
        return "全部串行" if level == "全部" else f"当前层:{level}"

    def _client_direct_auto_batch_name(self, accounts: list[AccountConfig]) -> str:
        level = self.level_var.get()
        scope_name = "全部" if level == "全部" else (level or "当前层")
        base_name = f"{scope_name}-{len(accounts)}号"
        existing_names = {
            str(batch.batch_name or "")
            for batch in getattr(self.client_batch_store, "batches", [])
        }
        if base_name not in existing_names:
            return base_name
        suffix = 2
        while f"{base_name}-{suffix}" in existing_names:
            suffix += 1
        return f"{base_name}-{suffix}"

    def _create_client_direct_batch_for_accounts(self, accounts: list[AccountConfig], *, append: bool) -> None:
        base_port = LauncherApp._client_direct_base_port(self)
        if append and self.client_batch_store.batches:
            batch = self.client_batch_store.current_batch()
            batch.base_port = base_port
            batch.auto_enter_game = LauncherApp._client_direct_auto_enter_game(self)
            batch.scope = self._client_direct_scope_label()
        else:
            name = LauncherApp._client_direct_auto_batch_name(self, accounts)
            batch = self.client_batch_store.create_batch(
                name,
                scope=self._client_direct_scope_label(),
                base_port=base_port,
                auto_enter_game=LauncherApp._client_direct_auto_enter_game(self),
            )
            log = getattr(self, "_log", None)
            if callable(log):
                log(f"[批次] 自动创建批次：{name}，batch_id={batch.batch_id}")
            if not append:
                self.client_direct_bindings = {}
        self.client_batch_store.save()
        self._sync_client_direct_batch_status()

    def _precheck_client_direct_prepare_ports(self, accounts: list[AccountConfig], *, append: bool) -> bool:
        LauncherApp._ensure_client_direct_selected_batch_current(self)
        base_port = LauncherApp._client_direct_base_port(self)
        count = len(accounts)
        live_binding_ports = LauncherApp._refresh_client_direct_sessions_for_precheck(self)
        system_ports = check_port_range_available(base_port, count)
        range_ports = {base_port + index for index in range(count)}
        live_conflicts = sorted(range_ports & live_binding_ports)
        if system_ports or live_conflicts:
            blocked_ports = set(live_binding_ports)
            recommended = find_next_available_port_range(
                base_port,
                count,
                blocked_ports=blocked_ports,
            )
            parts = [f"当前端口范围不可用：{base_port}~{base_port + count - 1}"]
            if system_ports:
                parts.append("系统真实占用端口：" + "、".join(str(port) for port in system_ports))
            if live_conflicts:
                parts.append("存活批次绑定端口：" + "、".join(str(port) for port in live_conflicts))
            if recommended is not None:
                self.client_direct_base_port_var.set(int(recommended))
                LauncherApp._sync_client_direct_port_range(self)
                system_text = "、".join(str(port) for port in system_ports) if system_ports else "无"
                live_text = "、".join(str(port) for port in live_conflicts) if live_conflicts else "无"
                self._log(
                    f"[端口预检] 原端口 {base_port}~{base_port + count - 1} 不可用，"
                    f"系统占用={system_text}，存活批次绑定={live_text}，"
                    f"自动改用推荐端口 {recommended}~{recommended + count - 1}。"
                )
                return True
            message = "端口范围不可用，请更换起始端口。\n" + "\n".join(parts)
            self._log(f"[客户端批次] 阻止准备：{message.replace(chr(10), ' ')}")
            messagebox.showwarning("客户端直登端口占用", message)
            return False
        return True

    def _prepare_client_direct_current_scope(self) -> None:
        accounts = LauncherApp._client_direct_current_scope_accounts(self, "准备客户端")
        if not accounts:
            return
        level = self.level_var.get()
        concurrency = LauncherApp._client_direct_concurrency(self)
        self._log(f"准备客户端：层级={level}，账号数={len(accounts)}，并发={concurrency}。")
        self._start_client_direct_prepare_run(accounts, run_label="客户端准备当前层", append=False)

    def _append_client_direct_current_scope(self) -> None:
        accounts = LauncherApp._client_direct_current_scope_accounts(self, "追加准备")
        if not accounts:
            return
        if not self.client_batch_store.batches:
            message = "当前没有可追加的客户端批次，请先点击“准备客户端”。"
            self._log(f"阻止追加准备：{message}")
            messagebox.showwarning("追加准备", message)
            return
        existing = self.client_batch_store.binding_account_ids()
        new_accounts = [account for account in accounts if account.key not in existing]
        skipped = [account for account in accounts if account.key in existing]
        if skipped:
            self._log("追加准备跳过已在当前批次的账号：" + "、".join(account.display_name for account in skipped))
        if not new_accounts:
            message = "当前层账号都已经在当前批次中。"
            self._log(f"阻止追加准备：{message}")
            messagebox.showwarning("追加准备", message)
            return
        concurrency = LauncherApp._client_direct_concurrency(self)
        self._log(f"追加准备：新增账号数={len(new_accounts)}，并发={concurrency}。")
        self._start_client_direct_prepare_run(new_accounts, run_label="客户端追加准备", append=True)

    def _prepare_arrange_login_client_direct_current_scope(self) -> None:
        accounts = LauncherApp._client_direct_current_scope_accounts(self, "一键准备并登录")
        if not accounts:
            return
        auto_enter = LauncherApp._client_direct_auto_enter_game(self)
        self._log(
            f"[一键准备并登录] 开始：账号数={len(accounts)}，"
            f"auto_enter_game={'true' if auto_enter else 'false'}。"
        )
        started = LauncherApp._start_client_direct_prepare_run(
            self,
            accounts,
            run_label="客户端一键准备",
            append=False,
            skip_port_precheck=False,
        )
        if not started:
            return
        self._client_direct_one_click_accounts = list(accounts)
        self._client_direct_one_click_auto_enter_game = bool(auto_enter)
        after = getattr(self, "after", None)
        if callable(after):
            after(500, self._continue_client_direct_one_click_after_prepare)

    def _continue_client_direct_one_click_after_prepare(self) -> None:
        worker_thread = getattr(self, "worker_thread", None)
        if worker_thread and worker_thread.is_alive():
            self.after(500, self._continue_client_direct_one_click_after_prepare)
            return
        accounts = list(getattr(self, "_client_direct_one_click_accounts", []) or [])
        if not accounts:
            return
        successful = []
        for account in accounts:
            record = self.client_direct_bindings.get(account.key)
            if record is not None and LauncherApp._client_direct_binding_ready_for_arrange(self, record):
                successful.append(account)
            elif record is not None and record.status == "客户端已启动/待登录":
                record.status = "binding_invalid"
                record.error_message = "准备完成后的 binding 复核失败"
        if not successful:
            messagebox.showwarning("一键准备并登录", "准备阶段没有成功启动的客户端，已停止后续排列和登录。")
            return
        if len(successful) < len(accounts):
            failed_accounts = [account for account in accounts if account not in successful]
            failed_lines = []
            for account in failed_accounts:
                record = self.client_direct_bindings.get(account.key)
                reason = ""
                if record is not None:
                    reason = str(record.error_message or record.status or "")
                if not reason:
                    reason = str(getattr(self, "status_by_key", {}).get(account.key, "") or "准备失败")
                failed_lines.append(f"- {account.display_name}：{reason}")
            detail = "\n".join(failed_lines)
            if not messagebox.askyesno(
                "一键准备并登录",
                f"成功：{len(successful)}\n失败：{len(accounts) - len(successful)}\n\n"
                f"失败账号：\n{detail}\n\n是否继续排列并登录成功的 {len(successful)} 个？",
            ):
                self._log("[一键准备并登录] 准备部分失败，用户取消后续排列和登录。")
                return
        arranged = LauncherApp._arrange_prepared_client_direct_current_scope(self, accounts)
        if arranged is False:
            return
        login_accounts = [
            account
            for account in successful
            if LauncherApp._client_direct_binding_ready_for_arrange(
                self,
                self.client_direct_bindings.get(account.key),
            )
        ]
        skipped_after_arrange = len(successful) - len(login_accounts)
        if skipped_after_arrange:
            self._log(f"[一键准备并登录] 排列后 binding 再次失效，已从登录集合剔除 {skipped_after_arrange} 个。")
        if not login_accounts:
            messagebox.showwarning("一键准备并登录", "排列后没有仍然有效的客户端 binding，已停止登录。")
            return
        LauncherApp._login_prepared_client_direct_current_scope(
            self,
            login_accounts,
            auto_enter_game=bool(getattr(self, "_client_direct_one_click_auto_enter_game", True)),
        )

    def _arrange_prepared_client_direct_current_scope(self, accounts_override: list[AccountConfig] | None = None) -> bool:
        accounts = accounts_override if accounts_override is not None else LauncherApp._client_direct_accounts_from_active_batch(self)
        if not accounts:
            messagebox.showwarning("排列本批客户端", "当前批次没有绑定记录，请先准备客户端。")
            return False
        worker_thread = getattr(self, "worker_thread", None)
        if worker_thread and worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return False

        arrangement = self._wm_read_arrangement_config()
        if arrangement is None:
            return False
        tile_mode, tile_config = arrangement
        windows = LauncherApp._client_direct_collect_binding_windows(self, accounts)
        if not windows:
            LauncherApp._save_client_direct_bindings_to_active_batch(self)
            message = "当前层没有可排列的已准备客户端窗口。"
            self._log(f"排列本批客户端：{message}")
            messagebox.showwarning("排列本批客户端", message)
            return False

        self._save_window_manager_settings()
        self._log(
            f"排列本批客户端：层级={self.level_var.get()}，"
            f"绑定窗口数={len(windows)}，排列方式={tile_mode}。"
        )
        try:
            results = LauncherApp._client_direct_tile_binding_windows(
                self,
                windows,
                tile_mode,
                tile_config,
                layout_window_count=len(accounts),
                log=lambda message: self._log(f"排列本批客户端：{message}"),
            )
        except Exception as exc:
            error = str(exc)
            self._log(f"排列本批客户端失败：{error}")
            messagebox.showerror("排列本批客户端失败", error)
            return False

        self._wm_log_tile_results(results, lambda message: self._log(f"排列本批客户端：{message}"))
        auto_rename_var = getattr(self, "wm_auto_rename_after_tile_var", None)
        try:
            auto_rename_enabled = bool(auto_rename_var.get()) if auto_rename_var is not None else False
        except Exception:
            auto_rename_enabled = False
        if auto_rename_enabled:
            LauncherApp._rename_client_direct_bound_windows_after_tile(self, accounts, results)
        account_by_hwnd = {
            int(record.hwnd): account
            for account in accounts
            for record in [self.client_direct_bindings.get(account.key)]
            if record is not None and int(record.hwnd or 0) > 0
        }
        for result in results:
            if not result.success:
                continue
            account = account_by_hwnd.get(int(result.window.hwnd))
            if account is None:
                continue
            record = self.client_direct_bindings.get(account.key)
            if record is None:
                continue
            record.status = "已排列"
            self.client_direct_bindings[account.key] = record
            self._set_status(account, "已排列")
        LauncherApp._save_client_direct_bindings_to_active_batch(self)
        success_count = sum(1 for result in results if result.success)
        fail_count = len(results) - success_count
        self._log(f"排列本批客户端完成：成功 {success_count}，失败 {fail_count}。")
        return True

    def _login_prepared_client_direct_current_scope(
        self,
        accounts_override: list[AccountConfig] | None = None,
        *,
        auto_enter_game: bool = True,
    ) -> None:
        scope_label = "本次准备账号"
        if accounts_override is not None:
            accounts = accounts_override
        else:
            scope_label = LauncherApp._client_direct_login_scope(self)
            accounts = LauncherApp._client_direct_accounts_for_login_scope(self, scope_label)
            if accounts is None:
                return
        if not accounts:
            messagebox.showwarning("执行客户端登录", f"登录范围={scope_label} 下没有可登录账号。")
            return
        if hasattr(self, "client_batch_store") and self.client_batch_store.batches:
            level = self.client_batch_store.current_batch().scope
        else:
            level = self.level_var.get()
        auto_text = "进入游戏" if auto_enter_game else "停在公告/进入游戏前"
        concurrency = LauncherApp._client_direct_concurrency(self)
        self._log(f"[客户端直登] 登录范围={scope_label}，本次登录账号数={len(accounts)}。")
        self._log("[客户端直登] 登录账号：" + "、".join(str(getattr(account, "game_window_no", "") or account.display_name) for account in accounts))
        self._log(f"执行客户端登录：层级={level}，账号数={len(accounts)}，并发={concurrency}，{auto_text}。")
        self._start_client_direct_prepared_login_run(
            accounts,
            run_label="客户端当前层登录",
            auto_enter_game=bool(auto_enter_game),
        )

    def _client_direct_login_scope(self) -> str:
        var = getattr(self, "client_direct_login_scope_var", None)
        try:
            value = str(var.get() if var is not None else "").strip()
        except Exception:
            value = ""
        if value not in CLIENT_DIRECT_LOGIN_SCOPE_CHOICES:
            value = CLIENT_DIRECT_LOGIN_SCOPE_PENDING
            try:
                if var is not None:
                    var.set(value)
            except Exception:
                pass
        return value

    def _client_direct_accounts_for_login_scope(self, scope: str) -> list[AccountConfig] | None:
        accounts = LauncherApp._client_direct_accounts_from_active_batch(self)
        if not accounts:
            return []
        if not getattr(getattr(self, "client_batch_store", None), "batches", None):
            return accounts
        records = getattr(self, "client_direct_bindings", {}) or {}
        if scope == CLIENT_DIRECT_LOGIN_SCOPE_ALL:
            return accounts
        if scope == CLIENT_DIRECT_LOGIN_SCOPE_SELECTED:
            tree = getattr(self, "tree", None)
            try:
                selected_ids = {str(item) for item in tree.selection()} if tree is not None else set()
            except Exception:
                selected_ids = set()
            if not selected_ids:
                messagebox.showwarning("执行客户端登录", "请先在账号列表中选择要登录的账号。")
                return None
            current_ids = {str(key) for key in records.keys()}
            return [account for account in accounts if str(account.key) in selected_ids and str(account.key) in current_ids]
        if scope == CLIENT_DIRECT_LOGIN_SCOPE_FAILED:
            return [
                account
                for account in accounts
                if str(getattr(records.get(account.key), "status", "") or "").strip() in CLIENT_DIRECT_LOGIN_FAILED_STATUSES
            ]
        pending: list[AccountConfig] = []
        for account in accounts:
            record = records.get(account.key)
            status = str(getattr(record, "status", "") or "").strip()
            if status in {"客户端登录成功", "已登录", "登录成功"}:
                continue
            if LauncherApp._client_direct_binding_ready_for_arrange(self, record):
                pending.append(account)
        return pending

    def _client_direct_pid_exists(self, pid: int) -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid or 0))
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))
            return True
        except Exception:
            return False

    def _client_direct_process_is_x5game(self, pid: int) -> bool:
        path = get_process_path_by_pid(int(pid or 0))
        return Path(path).name.lower() == "x5game.exe"

    def _client_direct_cdp_available(self, port: int) -> bool:
        return not is_tcp_port_available(int(port or 0))

    def _refresh_client_direct_sessions_for_precheck(self) -> set[int]:
        if not hasattr(self, "client_batch_store") or not self.client_batch_store.batches:
            return set()
        try:
            self.client_batch_store.refresh_all_batch_statuses(
                pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
                process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
                cdp_available=lambda port: LauncherApp._client_direct_cdp_available(self, port),
                hwnd_valid=lambda hwnd: LauncherApp._client_direct_is_window_alive(self, hwnd),
            )
            if self.client_batch_store.path.exists():
                self.client_batch_store.save()
            LauncherApp._restore_client_direct_bindings_from_active_batch(self)
            LauncherApp._sync_client_direct_batch_status(self)
        except Exception as exc:
            self._log(f"[客户端批次] 刷新批次状态失败：{mask_sensitive_text(str(exc))}")
        try:
            return self.client_batch_store.live_binding_ports(
                pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
                process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
            )
        except Exception as exc:
            self._log(f"[客户端批次] 读取存活绑定端口失败：{mask_sensitive_text(str(exc))}")
            return set()

    def _rename_client_direct_current_batch(self) -> None:
        if not self.client_batch_store.batches:
            messagebox.showwarning("重命名批次", "当前没有客户端批次。")
            return
        LauncherApp._ensure_client_direct_selected_batch_current(self)
        batch = self.client_batch_store.current_batch()
        new_name = simpledialog.askstring("重命名批次", "请输入新的批次名称：", initialvalue=batch.batch_name)
        if new_name is None:
            return
        clean_name = new_name.strip()
        if not clean_name:
            messagebox.showwarning("重命名批次", "批次名称不能为空。")
            return
        batch.batch_name = clean_name
        batch.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.client_batch_store.save()
        LauncherApp._sync_client_direct_batch_status(self)
        self._log(f"[客户端批次] 已重命名当前批次：{clean_name}")

    def _delete_client_direct_current_batch(self) -> None:
        if not self.client_batch_store.batches:
            messagebox.showwarning("删除当前批次", "当前没有客户端批次。")
            return
        LauncherApp._ensure_client_direct_selected_batch_current(self)
        LauncherApp._refresh_client_direct_sessions_for_precheck(self)
        batch = self.client_batch_store.current_batch()
        live_count = self.client_batch_store.batch_live_count(
            batch,
            pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
            process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
        )
        if live_count > 0:
            message = (
                f"当前批次仍有存活客户端 {live_count} 个。\n"
                "删除批次只会删除绑定记录，不会关闭客户端。\n"
                "如需关闭客户端，请先点击“关闭本批客户端”。\n"
                "是否仍然删除批次记录？"
            )
        else:
            message = f"确定删除当前批次“{batch.batch_name}”的绑定记录吗？\n不会关闭任何客户端。"
        if not messagebox.askyesno("删除当前批次", message):
            self._log("[客户端批次] 用户取消删除当前批次。")
            return
        batch_id = batch.batch_id
        batch_name = batch.batch_name
        self.client_batch_store.delete_batch(batch_id)
        self.client_batch_store.save()
        LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        LauncherApp._sync_client_direct_batch_status(self)
        self._log(f"[客户端批次] 已删除当前批次记录：{batch_name} batch_id={batch_id}")

    def _cleanup_dead_client_direct_batches(self) -> None:
        if not self.client_batch_store.batches:
            messagebox.showinfo("清理失效批次", "当前没有客户端批次。")
            return
        LauncherApp._refresh_client_direct_sessions_for_precheck(self)
        dead_batches = [
            batch
            for batch in self.client_batch_store.batches
            if self.client_batch_store.batch_live_count(
                batch,
                pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
                process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
            ) == 0
        ]
        if not dead_batches:
            messagebox.showinfo("清理失效批次", "没有存活数量为 0 的失效批次。")
            return
        names = "\n".join(f"- {batch.batch_name}" for batch in dead_batches)
        if not messagebox.askyesno(
            "清理失效批次",
            f"将清理 {len(dead_batches)} 个失效批次记录：\n{names}\n\n不会关闭任何 X5Game.exe，也不会删除 sessions 文件。是否继续？",
        ):
            self._log("[客户端批次] 用户取消清理失效批次。")
            return
        removed = self.client_batch_store.cleanup_dead_batches(
            pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
            process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
        )
        self.client_batch_store.save()
        LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        LauncherApp._sync_client_direct_batch_status(self)
        self._log(
            "[客户端批次] 已清理失效批次："
            + "、".join(batch.batch_name for batch in removed)
        )

    def _scan_client_direct_historical_hwnd(
        self,
        hwnd: int,
        *,
        listener_snapshot=None,
        process_parent_snapshot=None,
    ) -> LocalClientScan | None:
        clean_hwnd = int(hwnd or 0)
        if clean_hwnd <= 0:
            return None
        try:
            if not bool(user32.IsWindow(clean_hwnd)):
                return None
        except Exception:
            return None
        try:
            pid = int(get_window_process_id(clean_hwnd) or 0)
        except Exception:
            pid = 0
        if pid <= 0:
            return None
        try:
            process_path = get_process_path_by_pid(pid)
        except Exception:
            process_path = ""
        try:
            is_x5game = Path(process_path).name.lower() == "x5game.exe"
        except Exception:
            is_x5game = False
        try:
            rect = get_window_rect(clean_hwnd)
        except Exception:
            rect = WindowRect(0, 0, 0, 0)
        try:
            import ctypes

            title_length = int(user32.GetWindowTextLengthW(clean_hwnd) or 0)
            title_buffer = ctypes.create_unicode_buffer(max(2, title_length + 1))
            user32.GetWindowTextW(clean_hwnd, title_buffer, len(title_buffer))
            title = str(title_buffer.value or "")
        except Exception:
            title = ""
        ownership_kwargs = {}
        if listener_snapshot is not None and process_parent_snapshot is not None:
            ownership_kwargs = {
                "tcp_listeners": lambda snapshot=listener_snapshot: snapshot,
                "process_parents": lambda snapshot=process_parent_snapshot: snapshot,
            }
        try:
            ownership = discover_window_cdp_endpoint(clean_hwnd, pid, **ownership_kwargs)
        except Exception:
            ownership = None
        matched_port = int(getattr(ownership, "port", 0) or 0)
        ownership_status = str(getattr(ownership, "status", "cdp_owner_unverified") or "cdp_owner_unverified")
        owner_pid = int(getattr(ownership, "owner_pid", 0) or 0)
        target_info: dict[str, str] = {}
        if ownership_status == "verified" and matched_port > 0:
            try:
                target = select_page_target(wait_for_cdp_targets(matched_port, timeout=0.8))
                target_info = {
                    "url": str(target.get("url") or ""),
                    "title": str(target.get("title") or ""),
                }
            except Exception:
                ownership_status = "cdp_unavailable"
        return LocalClientScan(
            pid=pid,
            hwnd=clean_hwnd,
            title=title,
            window_left=int(getattr(rect, "left", 0) or 0),
            window_top=int(getattr(rect, "top", 0) or 0),
            window_width=int(getattr(rect, "width", 0) or 0),
            window_height=int(getattr(rect, "height", 0) or 0),
            process_path=process_path,
            cdp_port=matched_port,
            cdp_owner_pid=owner_pid,
            cdp_ownership_status=ownership_status,
            cdp_available=ownership_status == "verified",
            cdp_port_inferred=False,
            page_url=str(target_info.get("url") or ""),
            page_title=str(target_info.get("title") or ""),
            is_x5game=is_x5game,
        )

    def _scan_local_client_direct_clients(self) -> list[LocalClientScan]:
        try:
            game_path = self._wm_game_exe_path_filter()
        except Exception:
            game_path = ""
        try:
            windows = list_game_windows(
                GAME_TITLE_KEYWORD,
                game_exe_path=game_path or None,
                allow_unnumbered=True,
            )
        except Exception as exc:
            self._log(f"[识别本地客户端] 扫描窗口失败：{mask_sensitive_text(str(exc))}")
            return []

        try:
            listener_snapshot = list_tcp_listeners_by_port()
            process_parent_snapshot = list_process_parents()
        except Exception as exc:
            self._log(f"[CDP归属] 读取端口/进程快照失败：{mask_sensitive_text(str(exc))}")
            listener_snapshot = None
            process_parent_snapshot = None

        scans: list[LocalClientScan] = []
        for window in windows:
            hwnd = int(window.hwnd or 0)
            try:
                pid = int(get_window_process_id(hwnd) or 0)
            except Exception:
                pid = 0
            try:
                process_path = get_process_path_by_pid(pid) if pid > 0 else ""
            except Exception:
                process_path = ""
            try:
                is_x5game = Path(process_path).name.lower() == "x5game.exe"
            except Exception:
                is_x5game = False
            rect = getattr(window, "rect", None)
            if rect is None:
                try:
                    rect = get_window_rect(hwnd)
                except Exception:
                    rect = WindowRect(0, 0, 0, 0)

            try:
                ownership_kwargs = {}
                if listener_snapshot is not None and process_parent_snapshot is not None:
                    ownership_kwargs = {
                        "tcp_listeners": lambda snapshot=listener_snapshot: snapshot,
                        "process_parents": lambda snapshot=process_parent_snapshot: snapshot,
                    }
                ownership = discover_window_cdp_endpoint(hwnd, pid, **ownership_kwargs)
            except Exception:
                ownership = None
            matched_port = int(getattr(ownership, "port", 0) or 0)
            ownership_status = str(getattr(ownership, "status", "cdp_owner_unverified") or "cdp_owner_unverified")
            owner_pid = int(getattr(ownership, "owner_pid", 0) or 0)
            target_info: dict[str, str] = {}
            if ownership_status == "verified" and matched_port > 0:
                try:
                    target = select_page_target(wait_for_cdp_targets(matched_port, timeout=0.8))
                    target_info = {
                        "url": str(target.get("url") or ""),
                        "title": str(target.get("title") or ""),
                    }
                except Exception:
                    ownership_status = "cdp_unavailable"
            scans.append(
                LocalClientScan(
                    pid=pid,
                    hwnd=hwnd,
                    title=str(window.title or ""),
                    window_left=int(getattr(rect, "left", 0) or 0),
                    window_top=int(getattr(rect, "top", 0) or 0),
                    window_width=int(getattr(rect, "width", 0) or 0),
                    window_height=int(getattr(rect, "height", 0) or 0),
                    process_path=process_path,
                    cdp_port=matched_port,
                    cdp_owner_pid=owner_pid,
                    cdp_ownership_status=ownership_status,
                    cdp_available=ownership_status == "verified",
                    cdp_port_inferred=False,
                    page_url=str(target_info.get("url") or ""),
                    page_title=str(target_info.get("title") or ""),
                    is_x5game=is_x5game,
                )
            )
        port_counts: dict[int, int] = {}
        for scan in scans:
            if scan.cdp_ownership_status == "verified" and int(scan.cdp_port or 0) > 0:
                port_counts[int(scan.cdp_port)] = port_counts.get(int(scan.cdp_port), 0) + 1
        scans = [
            replace(scan, cdp_port=0, cdp_available=False, cdp_ownership_status="cdp_owner_conflict")
            if int(scan.cdp_port or 0) > 0 and port_counts.get(int(scan.cdp_port), 0) > 1
            else scan
            for scan in scans
        ]
        return scans

    def _identify_local_client_direct_clients(self) -> None:
        LauncherApp._ensure_client_direct_selected_batch_current(self)
        scans = LauncherApp._scan_local_client_direct_clients(self)
        result = self.client_batch_store.identify_local_clients(scans)
        self.client_batch_store.save()
        LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        LauncherApp._sync_client_direct_batch_status(self)
        for note in result.get("notes", []) or []:
            self._log(f"[识别本地客户端] {note}")
        for index, scan in enumerate(scans, start=1):
            self._log(
                f"[CDP归属] 窗口{index} hwnd={int(scan.hwnd or 0)} pid={int(scan.pid or 0)} "
                f"port={int(scan.cdp_port or 0)} owner_pid={int(getattr(scan, 'cdp_owner_pid', 0) or 0)} "
                f"status={str(getattr(scan, 'cdp_ownership_status', '') or '')}"
            )
        self._log(
            f"[识别本地客户端] 扫描到 {result['scanned']} 个 X5Game，"
            f"恢复历史批次 {result['restored_batches']} 个，"
            f"新建批次 {result['created_batches']} 个，"
            f"未归属 {result['unassigned']} 个。"
        )
        for batch in getattr(self.client_batch_store, "batches", []) or []:
            counts = LauncherApp._client_direct_batch_counts(self, batch)
            self._log(
                f"[识别本地客户端] {batch.batch_name}："
                f"绑定{counts['bound']}，端口{LauncherApp._client_direct_batch_port_range_text(self, batch)}。"
            )

    def _repair_client_direct_current_batch(self) -> None:
        if not self.client_batch_store.batches:
            messagebox.showwarning("修复本批窗口", "当前没有客户端批次。")
            return
        LauncherApp._ensure_client_direct_selected_batch_current(self)
        batch = self.client_batch_store.current_batch()
        if not batch.bindings:
            messagebox.showwarning("修复本批窗口", "当前批次没有绑定记录。")
            return
        counts = LauncherApp._client_direct_batch_counts(self, batch)
        port_range = LauncherApp._client_direct_batch_port_range_text(self, batch)
        confirm_message = (
            "即将修复当前批次：\n"
            f"批次名称：{batch.batch_name}\n"
            f"绑定数量：{counts['bound']}\n"
            f"端口范围：{port_range}\n"
            f"存活数量：{counts['alive']}\n"
            f"已关闭数量：{counts['closed']}\n"
            "是否继续？"
        )
        if not messagebox.askyesno("修复本批窗口", confirm_message):
            self._log("[修复本批窗口] 用户取消。")
            return
        self._log(
            f"[修复本批窗口] 当前批次={batch.batch_name} batch_id={batch.batch_id} "
            f"绑定数量={counts['bound']} 端口范围={port_range}"
        )
        pre_repair_state = {
            binding.account_id: (
                binding.status,
                binding.display_status,
                binding.login_status,
                binding.error_message,
            )
            for binding in batch.bindings
        }
        historical_scan_cache: dict[int, LocalClientScan | None] = {}
        historical_probe_hits: set[int] = set()
        historical_binding_by_hwnd = {
            int(binding.hwnd): binding
            for binding in batch.bindings
            if int(binding.hwnd or 0) > 0
        }
        historical_snapshot_state = {
            "loaded": False,
            "listeners": None,
            "parents": None,
        }

        def scan_historical_hwnd(hwnd: int) -> LocalClientScan | None:
            clean_hwnd = int(hwnd or 0)
            if clean_hwnd in historical_scan_cache:
                return historical_scan_cache[clean_hwnd]
            if not historical_snapshot_state["loaded"]:
                historical_snapshot_state["loaded"] = True
                try:
                    historical_snapshot_state["listeners"] = list_tcp_listeners_by_port()
                    historical_snapshot_state["parents"] = list_process_parents()
                except Exception as exc:
                    self._log(f"[修复本批窗口] 历史 HWND 回查读取端口/进程快照失败：{mask_sensitive_text(str(exc))}")
            scan = LauncherApp._scan_client_direct_historical_hwnd(
                self,
                clean_hwnd,
                listener_snapshot=historical_snapshot_state["listeners"],
                process_parent_snapshot=historical_snapshot_state["parents"],
            )
            historical_scan_cache[clean_hwnd] = scan
            if scan is not None:
                historical_probe_hits.add(clean_hwnd)
                old_binding = historical_binding_by_hwnd.get(clean_hwnd)
                old_pid = int(getattr(old_binding, "pid", 0) or 0)
                exe_name = Path(str(scan.process_path or "")).name or "unknown"
                self._log(
                    f"[修复本批窗口] 历史 HWND 回查 hwnd={clean_hwnd} old_pid={old_pid} "
                    f"current_pid={int(scan.pid or 0)} exe={exe_name} port={int(scan.cdp_port or 0)} "
                    f"owner_status={scan.cdp_ownership_status or 'unknown'}"
                )
            else:
                self._log(f"[修复本批窗口] 历史 HWND 回查 hwnd={clean_hwnd} 无有效窗口。")
            return scan

        probe = RepairProbe(
            pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
            process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
            cdp_available=lambda port: LauncherApp._client_direct_cdp_available(self, port),
            hwnd_for_pid=lambda pid: wait_for_client_hwnd_by_pid(pid, timeout=0.5),
            scan_for_hwnd=scan_historical_hwnd,
        )
        current_scans = LauncherApp._scan_local_client_direct_clients(self)
        if len(current_scans) != len(batch.bindings):
            self._log(
                f"[修复本批窗口] 当前扫描 {len(current_scans)} 个，"
                f"历史绑定 {len(batch.bindings)} 个。"
            )
        results = self.client_batch_store.repair_current_batch_windows(probe=probe, local_scans=current_scans)
        historical_recovered_count = sum(
            1
            for binding in batch.bindings
            if int(binding.hwnd or 0) in historical_probe_hits and results.get(binding.account_id) == "repaired"
        )
        if historical_recovered_count:
            self._log(
                f"[修复本批窗口] 常规扫描未匹配后，历史 HWND 回查 {historical_recovered_count} 个，"
                "已重新校验并更新真实 PID/CDP 绑定。"
            )
        recently_closed = getattr(self, "_recently_closed_client_bindings", {})
        missing_bindings = []
        for binding in batch.bindings:
            if binding.status == "pid_missing":
                missing_bindings.append(binding)
                continue
            marker = recently_closed.get((str(batch.batch_id), str(binding.account_id)))
            if binding.status != "pid_not_x5game" or not marker:
                continue
            if LauncherApp._client_direct_recently_closed_safe_to_reopen(self, binding, marker):
                binding.status = "pid_missing"
                missing_bindings.append(binding)
                self._log(f"[修复本批窗口] 刚关闭 binding 已确认 HWND/CDP 失效，安全转入补开：{binding.account_name}")
        reopened_ids: set[str] = set()
        if missing_bindings:
            reopened_ids = LauncherApp._repair_client_direct_missing_processes(self, batch, missing_bindings)
        LauncherApp._client_direct_restore_repaired_business_statuses(self, batch, pre_repair_state, results, reopened_ids)
        self.client_batch_store.save()
        LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        LauncherApp._sync_client_direct_batch_status(self)
        for binding in batch.bindings:
            account = LauncherApp._account_for_client_direct_record(self, LauncherApp._record_from_batch_binding(self, binding))
            self._set_status(account, binding.status)
            self._log(
                f"修复本批窗口：{binding.account_name} status={binding.status} "
                f"pid={binding.pid} hwnd={binding.hwnd} port={binding.cdp_port}"
            )
        ready_count = sum(1 for binding in batch.bindings if str(getattr(binding, "window_status", "")) == "restored")
        abnormal_count = max(0, len(batch.bindings) - ready_count)
        self._log(
            f"修复本批窗口完成：常规扫描 {len(current_scans)} 个，历史 HWND 回查 {historical_recovered_count} 个，"
            f"历史绑定 {len(batch.bindings)} 个，就绪={ready_count}，异常={abnormal_count}，绑定总数={len(results)}。"
        )

    def _client_direct_recently_closed_safe_to_reopen(self, binding, marker) -> bool:
        try:
            old_pid, closed_at = marker
            if int(old_pid) != int(binding.pid or 0) or time.monotonic() - float(closed_at) > 30:
                return False
            hwnd = int(binding.hwnd or 0)
            hwnd_invalid = hwnd <= 0 or not bool(user32.IsWindow(hwnd))
            port = int(binding.cdp_port or 0)
            cdp_gone = port <= 0 or not LauncherApp._client_direct_cdp_available(self, port)
            return hwnd_invalid and cdp_gone
        except Exception:
            return False

    def _client_direct_restore_repaired_business_statuses(
        self,
        batch,
        pre_repair_state: dict[str, tuple[str, str, str, str]],
        results: dict[str, str],
        reopened_ids: set[str],
    ) -> None:
        preservable_statuses = set(BUSINESS_STATUS_VALUES) | {
            "已排列",
            "客户端已启动/待登录",
            "已登录",
            "登录成功",
        }
        for binding in getattr(batch, "bindings", []) or []:
            account_id = str(binding.account_id)
            if account_id in reopened_ids:
                continue
            if results.get(account_id) != "repaired":
                continue
            old_status, old_display_status, old_login_status, old_error_message = pre_repair_state.get(
                account_id,
                ("", "", "", ""),
            )
            preserved_status = next(
                (
                    value
                    for value in (old_status, old_display_status, old_login_status)
                    if value in preservable_statuses
                ),
                "",
            )
            if preserved_status:
                binding.status = preserved_status
                binding.error_message = old_error_message if preserved_status == old_status else ""
            else:
                binding.status = "客户端已就绪"
                binding.error_message = ""

    def _repair_client_direct_missing_processes(self, batch, missing_bindings: list[ClientBatchBinding]) -> set[str]:
        lines = "\n".join(
            f"- {binding.account_name or binding.account_id}：pid_missing"
            for binding in missing_bindings
        )
        message = (
            f"当前批次有 {len(missing_bindings)} 个客户端进程已不存在：\n"
            f"{lines}\n\n"
            "是否重新启动这些缺失客户端？"
        )
        if not messagebox.askyesno("修复本批窗口", message):
            self._log(f"[修复本批窗口] 用户取消补开 {len(missing_bindings)} 个 pid_missing 客户端。")
            return set()

        game_path = self._wm_game_exe_path_filter()
        if not game_path:
            self._log("[修复本批窗口] 游戏程序路径为空，无法补开 pid_missing 客户端。")
            messagebox.showwarning("修复本批窗口", "请先选择 X5Game.exe。")
            return set()
        if not Path(game_path).exists():
            self._log(f"[修复本批窗口] 游戏程序路径不存在：{game_path}")
            messagebox.showwarning("修复本批窗口", f"游戏程序路径不存在：{game_path}")
            return set()

        used_ports: set[int] = set()
        reopened_ids: set[str] = set()
        for binding in missing_bindings:
            account = LauncherApp._account_for_client_direct_record(self, LauncherApp._record_from_batch_binding(self, binding))
            port = LauncherApp._client_direct_repair_port_for_binding(self, batch, binding, used_ports)
            if port is None:
                binding.status = "端口占用"
                binding.error_message = "没有可用 CDP 端口"
                self._set_status(account, "端口占用")
                self._log(f"[修复本批窗口] 补开失败：{binding.account_name} 没有可用 CDP 端口")
                continue
            used_ports.add(port)
            self._log(f"[修复本批窗口] 补开缺失客户端：{binding.account_name} port={port}")
            result = prepare_client_direct_client(
                ClientDirectLoginConfig(
                    account_id=binding.account_id,
                    account_name=binding.account_name,
                    full_login_url=binding.login_url,
                    x5game_path=game_path,
                    cdp_port=port,
                    auto_enter_game=False,
                    timeout=60.0,
                ),
                stop_event=getattr(self, "stop_event", None),
                log=lambda text, key=binding.account_id: self._log(f"[客户端直登][{key}] {mask_sensitive_text(text)}"),
            )
            result_binding = getattr(result, "binding", None)
            binding.pid = int(getattr(result_binding, "pid", 0) or 0)
            binding.hwnd = int(getattr(result_binding, "hwnd", 0) or 0)
            binding.cdp_port = int(getattr(result_binding, "cdp_port", port) or port)
            if result.success:
                binding.status = "客户端已启动/待登录"
                binding.window_status = "restored"
                binding.repair_status = "reopened"
                binding.error_message = ""
                self._set_status(account, "客户端已启动/待登录")
                self._log(
                    f"[修复本批窗口] 补开成功：{binding.account_name} "
                    f"pid={binding.pid} hwnd={binding.hwnd} port={binding.cdp_port}"
                )
                reopened_ids.add(str(binding.account_id))
                self._log(f"[修复本批窗口] {binding.account_name} pid_missing，已重新启动。")
                LauncherApp._client_direct_move_repaired_binding_to_slot(self, batch, binding)
            else:
                reason = mask_sensitive_text(getattr(result, "message", "") or "未知错误")
                binding.status = "启动失败"
                binding.error_message = reason
                self._set_status(account, "启动失败")
                self._log(f"[修复本批窗口] 补开失败：{binding.account_name} reason={reason}")
            binding.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        batch.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        return reopened_ids

    def _client_direct_binding_slot_index(self, batch, binding: ClientBatchBinding) -> int:
        for attr_name in ("slot_index", "window_index"):
            raw_value = getattr(binding, attr_name, None)
            if raw_value is None:
                continue
            try:
                value = int(raw_value)
            except Exception:
                continue
            if value > 0:
                return value - 1
        for index, item in enumerate(getattr(batch, "bindings", []) or []):
            if str(getattr(item, "account_id", "")) == str(binding.account_id):
                return index
        return 0

    def _client_direct_single_slot_rect(
        self,
        slot_index: int,
        window_count: int,
        tile_mode: str,
        tile_config: TileConfig | RowTileConfig,
    ) -> tuple[int, int, int, int]:
        if tile_mode == WM_TILE_MODE_ROW_COUNT:
            plan = calculate_row_tile_plan(max(1, window_count), tile_config)
            row = slot_index // max(1, plan.cols)
            col = slot_index % max(1, plan.cols)
            x = int(tile_config.start_x + col * (plan.target_width + plan.gap_x))
            y = int(tile_config.start_y + row * (plan.target_height + plan.gap_y))
            return x, y, int(plan.target_width), int(plan.target_height)
        x, y = calculate_tile_position(slot_index, tile_config)
        return int(x), int(y), int(tile_config.width), int(tile_config.height)

    def _client_direct_move_repaired_binding_to_slot(self, batch, binding: ClientBatchBinding) -> bool:
        hwnd = int(binding.hwnd or 0)
        if hwnd <= 0:
            return False
        if not hasattr(self, "_wm_read_arrangement_config"):
            return False
        arrangement = self._wm_read_arrangement_config()
        if arrangement is None:
            return False
        tile_mode, tile_config = arrangement
        slot_index = LauncherApp._client_direct_binding_slot_index(self, batch, binding)
        slot_no = slot_index + 1
        try:
            x, y, width, height = LauncherApp._client_direct_single_slot_rect(
                self,
                slot_index,
                len(getattr(batch, "bindings", []) or []),
                tile_mode,
                tile_config,
            )
            ok = bool(user32.SetWindowPos(hwnd, 0, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE))
        except Exception as exc:
            ok = False
            self._log(f"[修复本批窗口] {binding.account_name} 移动到第{slot_no}槽位失败：{mask_sensitive_text(str(exc))}")
        if not ok:
            self._log(f"[修复本批窗口] {binding.account_name} 移动到第{slot_no}槽位失败。")
            try:
                if messagebox.askyesno("修复本批窗口", "单独移动补开的窗口失败，是否执行“排列本批客户端”？"):
                    LauncherApp._arrange_prepared_client_direct_current_scope(self)
            except Exception:
                pass
            return False

        self._log(f"[修复本批窗口] {binding.account_name} 已移动到第{slot_no}槽位。")
        auto_rename_var = getattr(self, "wm_auto_rename_after_tile_var", None)
        try:
            auto_rename_enabled = bool(auto_rename_var.get()) if auto_rename_var is not None else False
        except Exception:
            auto_rename_enabled = False
        if auto_rename_enabled:
            try:
                record = LauncherApp._record_from_batch_binding(self, binding)
                account = LauncherApp._account_for_client_direct_record(self, record)
                title_template = _safe_wm_title_template(self) or "斗罗大陆H5-{account_id}号"
                new_title = LauncherApp._client_direct_binding_title_from_template(
                    title_template,
                    slot_no,
                    record,
                    account,
                )
                if user32.SetWindowTextW(hwnd, new_title):
                    self._log(f"[修复本批窗口] {binding.account_name} 已重命名为 {new_title}。")
                else:
                    self._log(f"[修复本批窗口] {binding.account_name} 重命名失败：SetWindowTextW failed。")
            except Exception as exc:
                self._log(f"[修复本批窗口] {binding.account_name} 重命名失败：{mask_sensitive_text(str(exc))}")
        return True

    def _client_direct_repair_port_for_binding(self, batch, binding: ClientBatchBinding, used_ports: set[int]) -> int | None:
        try:
            live_ports = self.client_batch_store.live_binding_ports(
                pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
                process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
            )
        except Exception:
            live_ports = set()
        blocked_ports = {int(port) for port in live_ports | set(used_ports) if int(port or 0) > 0}
        original_port = int(binding.cdp_port or 0)
        if original_port > 0 and original_port not in blocked_ports and is_tcp_port_available(original_port):
            return original_port

        current_ports = [
            int(item.cdp_port or 0)
            for item in getattr(batch, "bindings", [])
            if int(item.cdp_port or 0) > 0
        ]
        base_port = max(current_ports or [int(getattr(batch, "base_port", CLIENT_DIRECT_CDP_PORT) or CLIENT_DIRECT_CDP_PORT)])
        return find_next_available_port_range(
            base_port,
            1,
            blocked_ports=blocked_ports,
        )

    def _clear_client_direct_current_batch(self) -> None:
        if not self.client_batch_store.batches:
            messagebox.showwarning("清空本批绑定", "当前没有客户端批次。")
            return
        LauncherApp._ensure_client_direct_selected_batch_current(self)
        if not messagebox.askyesno("清空本批绑定", "只清空当前批次绑定记录，不关闭 X5Game.exe。确定继续？"):
            return
        self.client_batch_store.clear_current_batch()
        self.client_batch_store.save()
        self.client_direct_bindings = {}
        LauncherApp._sync_client_direct_batch_status(self)
        self._log("清空本批绑定完成：未关闭任何 X5Game.exe。")

    def _close_client_direct_current_batch(self) -> None:
        if not self.client_batch_store.batches:
            messagebox.showwarning("关闭本批客户端", "当前没有客户端批次。")
            return
        LauncherApp._ensure_client_direct_selected_batch_current(self)
        batch = self.client_batch_store.current_batch()
        pids = [int(binding.pid or 0) for binding in batch.bindings if int(binding.pid or 0) > 0]
        if not pids:
            messagebox.showwarning("关闭本批客户端", "当前批次没有可关闭的 pid。")
            return
        if not messagebox.askyesno("关闭本批客户端", f"只关闭当前批次记录中的 {len(pids)} 个 X5Game.exe，确定继续？"):
            return
        import subprocess as _sp

        for pid in pids:
            _sp.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
            self._log(f"关闭本批客户端：已请求关闭 pid={pid}")
        deadline = time.monotonic() + 5.0
        pending = set(pids)
        while pending and time.monotonic() < deadline:
            pending = {pid for pid in pending if LauncherApp._client_direct_pid_exists(self, pid)}
            if pending:
                time.sleep(0.1)
        closed_at = time.monotonic()
        recent = getattr(self, "_recently_closed_client_bindings", {})
        for binding in batch.bindings:
            binding.status = "closed"
            recent[(str(batch.batch_id), str(binding.account_id))] = (int(binding.pid or 0), closed_at)
        self._recently_closed_client_bindings = recent
        if pending:
            self._log(f"关闭本批客户端：等待退出超时 pid数量={len(pending)}，修复时将继续执行 HWND/CDP 安全复核。")
        self.client_batch_store.save()
        LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        LauncherApp._sync_client_direct_batch_status(self)

    def _run_first_account_dm_test(self) -> None:
        messagebox.showinfo("已暂停", "当前不执行大漠点击流程，只测试大漠环境是否可用。")

    def _run_dm_environment_test(self) -> None:
        try:
            settings = load_settings(self.settings_path.get())
        except Exception as exc:
            messagebox.showerror("读取自动化设置失败", str(exc))
            return
        self._log("测试2：大漠环境诊断")
        for line in diagnose_dm_environment_with_32bit_python(settings.dm_prog_id):
            self._log(line)
        self._log("测试2结束：不执行任何大漠点击流程。")

    def _setup_log_file(self, *, cleanup_old: bool = True) -> None:
        import time as _time
        log_dir = logs_dir(getattr(self, "user_data_dir", None))
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = _time.strftime("%Y%m%d_%H%M%S")
        self._log_file_path = log_dir / f"run_{ts}.log"
        self._log_file = open(str(self._log_file_path), "w", encoding="utf-8")
        self._write_file_log(f"=== 斗罗大陆H5上号器 运行日志 {ts} ===")
        self._write_file_log(f"版本号: {APP_VERSION}")

    def _write_file_log(self, msg: str) -> None:
        if self._log_file is not None:
            import time as _time
            ts = _time.strftime("%H:%M:%S")
            self._log_file.write(f"[{ts}] {mask_sensitive_text(msg)}\n")
            self._log_file.flush()

    def _queue_log_file(self, message: str) -> None:
        """仅写文件，不显示在 GUI。"""
        self._write_file_log(message)

    def _open_log_dir(self) -> None:
        import os
        log_dir = str(logs_dir(getattr(self, "user_data_dir", None)))
        os.makedirs(log_dir, exist_ok=True)
        os.startfile(log_dir)

    def _log_startup_dm_environment(self) -> None:
        import sys as _sys
        if getattr(_sys, "frozen", False):
            self._log("exe 模式：跳过 32 位大漠诊断（Dm 点击走 dm_click_helper.py 子进程）")
            return
        try:
            settings = load_settings(self.settings_path.get())
            self._log("启动环境检查：大漠（方案A：32 位 Python）")
            for line in diagnose_dm_environment_with_32bit_python(settings.dm_prog_id):
                self._log(line)
        except Exception as exc:
            self._log(f"启动环境检查失败: {exc}")

    def _log_admin_status_warning(self) -> None:
        try:
            import ctypes

            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_admin = False

        if is_admin:
            self._log("启动权限检查：当前以管理员权限运行。")
            return

        restart_result = os.environ.get("DOULUO_ADMIN_RESTART_RESULT", "")
        if restart_result:
            self._log(
                "启动权限检查：管理员重启未完成或被取消，"
                f"ShellExecuteW 返回码 {restart_result}。"
            )
        self._log("启动权限检查：当前非管理员运行，可能无法排列/关闭管理员权限窗口。")

    def _batch_verify_rounds(self) -> int:
        try:
            return max(1, int(self.batch_verify_rounds_var.get()))
        except Exception:
            self.batch_verify_rounds_var.set(3)
            return 3

    def _start_client_direct_single_run(self, account: AccountConfig) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return
        account = _inject_latest_client_direct_urls(self, [account])[0]
        if not is_complete_direct_login_url(account.url):
            self._setup_log_file(cleanup_old=False)
            self._set_status(account, "客户端直登失败")
            self._log("[客户端直登] 账号收藏夹 URL 不是完整客户端直登 URL，已阻止。")
            self._log("[客户端直登] 需要 gid、pid、token、time、sign、isPcLauncher=true，且入口为已知斗罗 H5 地址。")
            messagebox.showwarning("客户端直登失败", "当前账号链接不是完整客户端直登 URL。")
            return
        game_path = self._wm_game_exe_path_filter()
        if not game_path:
            self._setup_log_file(cleanup_old=False)
            self._set_status(account, "客户端直登失败")
            self._log("[客户端直登] 游戏程序路径为空，请先选择 X5Game.exe。")
            messagebox.showwarning("客户端直登失败", "请先选择 X5Game.exe。")
            return
        if not Path(game_path).exists():
            self._setup_log_file(cleanup_old=False)
            self._set_status(account, "客户端直登失败")
            self._log(f"[客户端直登] 游戏程序路径不存在：{game_path}")
            messagebox.showwarning("客户端直登失败", f"游戏程序路径不存在：{game_path}")
            return
        if not is_tcp_port_available(CLIENT_DIRECT_CDP_PORT):
            self._setup_log_file(cleanup_old=False)
            self._set_status(account, "客户端直登失败")
            self._log(f"[客户端直登] CDP 端口 {CLIENT_DIRECT_CDP_PORT} 已被占用。")
            messagebox.showwarning("客户端直登失败", f"CDP 端口 {CLIENT_DIRECT_CDP_PORT} 已被占用。")
            return

        self._setup_log_file(cleanup_old=False)
        self.stop_event.clear()
        self._preserve_background_windows = True
        self._set_status(account, "客户端直登中")
        self.client_direct_bindings = {
            account.key: ClientDirectRunRecord(
                account_id=account.key,
                account_name=account.display_name,
                cdp_port=CLIENT_DIRECT_CDP_PORT,
                login_url=account.url,
                status="客户端直登中",
            )
        }
        auto_enter_game = self._client_direct_auto_enter_game()
        self.worker_thread = threading.Thread(
            target=self._client_direct_single_worker,
            args=(account, game_path, auto_enter_game),
            daemon=True,
        )
        self.worker_thread.start()

    def _start_client_direct_serial_run(self, accounts: list[AccountConfig], *, run_label: str) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return
        accounts = _inject_latest_client_direct_urls(self, list(accounts))
        if not LauncherApp._precheck_client_direct_prepare_ports(self, accounts, append=False):
            for account in accounts:
                self._set_status(account, "端口占用")
            return
        game_path = self._wm_game_exe_path_filter()
        if not game_path:
            self._setup_log_file(cleanup_old=False)
            for account in accounts:
                self._set_status(account, "客户端直登失败")
            self._log("[客户端直登] 游戏程序路径为空，请先选择 X5Game.exe。")
            messagebox.showwarning("客户端直登失败", "请先选择 X5Game.exe。")
            return
        if not Path(game_path).exists():
            self._setup_log_file(cleanup_old=False)
            for account in accounts:
                self._set_status(account, "客户端直登失败")
            self._log(f"[客户端直登] 游戏程序路径不存在：{game_path}")
            messagebox.showwarning("客户端直登失败", f"游戏程序路径不存在：{game_path}")
            return

        self._setup_log_file(cleanup_old=False)
        self.stop_event.clear()
        self._preserve_background_windows = True
        LauncherApp._create_client_direct_batch_for_accounts(self, accounts, append=False)
        base_port = LauncherApp._client_direct_base_port(self)
        self.client_direct_bindings = {
            account.key: ClientDirectRunRecord(
                account_id=account.key,
                account_name=account.display_name,
                cdp_port=cdp_port_for_index(index, base_port=base_port),
                login_url=account.url,
                status="等待中",
            )
            for index, account in enumerate(accounts)
        }
        LauncherApp._save_client_direct_bindings_to_active_batch(self)
        for account in accounts:
            self._set_status(account, "等待中")
        auto_enter_game = self._client_direct_auto_enter_game()
        self.worker_thread = threading.Thread(
            target=self._client_direct_serial_worker,
            args=(list(accounts), game_path, auto_enter_game, run_label, base_port),
            daemon=True,
        )
        self.worker_thread.start()

    def _start_client_direct_prepare_run(
        self,
        accounts: list[AccountConfig],
        *,
        run_label: str,
        append: bool = False,
        skip_port_precheck: bool = False,
    ) -> bool:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return False
        accounts = _inject_latest_client_direct_urls(self, list(accounts))
        if not append and not LauncherApp._confirm_client_direct_new_batch_if_live(self, accounts, run_label):
            return False
        if not skip_port_precheck and not LauncherApp._precheck_client_direct_prepare_ports(self, accounts, append=append):
            return False
        game_path = self._wm_game_exe_path_filter()
        if not game_path:
            self._setup_log_file(cleanup_old=False)
            for account in accounts:
                self._set_status(account, "启动失败")
            self._log("[客户端直登] 游戏程序路径为空，请先选择 X5Game.exe。")
            messagebox.showwarning("准备客户端失败", "请先选择 X5Game.exe。")
            return False
        if not Path(game_path).exists():
            self._setup_log_file(cleanup_old=False)
            for account in accounts:
                self._set_status(account, "启动失败")
            self._log(f"[客户端直登] 游戏程序路径不存在：{game_path}")
            messagebox.showwarning("准备客户端失败", f"游戏程序路径不存在：{game_path}")
            return False

        self._setup_log_file(cleanup_old=False)
        self.stop_event.clear()
        self._preserve_background_windows = True
        LauncherApp._create_client_direct_batch_for_accounts(self, accounts, append=append)
        base_port = LauncherApp._client_direct_base_port(self)
        if not append:
            self.client_direct_bindings = {}
        for index, account in enumerate(accounts):
            self.client_direct_bindings[account.key] = ClientDirectRunRecord(
                account_id=account.key,
                account_name=account.display_name,
                cdp_port=cdp_port_for_index(index, base_port=base_port),
                login_url=account.url,
                status="待准备",
            )
        for account in accounts:
            self._set_status(account, "待准备")
        LauncherApp._save_client_direct_bindings_to_active_batch(self)
        concurrency = LauncherApp._client_direct_concurrency(self)
        self._log(f"[客户端直登] 本次并发数={concurrency}")
        self.worker_thread = threading.Thread(
            target=self._client_direct_prepare_worker,
            args=(list(accounts), game_path, run_label, base_port, concurrency),
            daemon=True,
        )
        self.worker_thread.start()
        return True

    def _start_client_direct_prepared_login_run(
        self,
        accounts: list[AccountConfig],
        *,
        run_label: str,
        auto_enter_game: bool = True,
    ) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return
        accounts = _inject_latest_client_direct_urls(self, list(accounts))
        missing = [account for account in accounts if account.key not in self.client_direct_bindings]
        if missing:
            message = "当前层存在未准备的客户端，请先点击“准备客户端”。"
            self._log(f"阻止执行客户端登录：{message}")
            messagebox.showwarning("执行客户端登录", message)
            return

        self._setup_log_file(cleanup_old=False)
        self.stop_event.clear()
        self._preserve_background_windows = True
        concurrency = LauncherApp._client_direct_concurrency(self)
        self._log(f"[客户端直登] 本次并发数={concurrency}")
        self.worker_thread = threading.Thread(
            target=self._client_direct_prepared_login_worker,
            args=(list(accounts), auto_enter_game, run_label, concurrency),
            daemon=True,
        )
        self.worker_thread.start()

    def _client_direct_is_window_alive(self, hwnd: int) -> bool:
        if int(hwnd or 0) <= 0:
            return False
        try:
            return bool(user32.IsWindow(int(hwnd)))
        except Exception:
            return False

    def _client_direct_binding_ready_for_arrange(self, record: ClientDirectRunRecord | None) -> bool:
        if record is None:
            return False
        pid = int(record.pid or 0)
        hwnd = int(record.hwnd or 0)
        port = int(record.cdp_port or 0)
        if pid <= 0 or hwnd <= 0 or port <= 0:
            return False
        if str(record.cdp_ownership_status or "") != "verified":
            return False
        if not LauncherApp._client_direct_pid_exists(self, pid):
            return False
        if not LauncherApp._client_direct_process_is_x5game(self, pid):
            return False
        if not LauncherApp._client_direct_is_window_alive(self, hwnd):
            return False
        try:
            return int(get_window_process_id(hwnd) or 0) == pid
        except Exception:
            return False

    def _client_direct_mark_window_invalid(self, account: AccountConfig, record: ClientDirectRunRecord) -> None:
        record.status = "窗口已失效"
        self.client_direct_bindings[account.key] = record
        self._set_status(account, "窗口已失效")
        self._log(f"排列本批客户端：跳过 {account.display_name}，窗口已失效 hwnd={record.hwnd}")

    @staticmethod
    def _client_direct_binding_title_from_template(
        title_template: str,
        index: int,
        record: ClientDirectRunRecord,
        account: AccountConfig | None = None,
    ) -> str:
        account_id_value = getattr(account, "game_window_no", None) if account is not None else None
        raw_account_id = str(record.account_id or "").strip()
        if not account_id_value and raw_account_id:
            match = re.search(r"(\d+)$", raw_account_id)
            account_id_value = match.group(1) if match else raw_account_id
        account_id = str(account_id_value or "").strip() or str(index)
        account_name = str(record.account_name or "").strip() or account_id
        return str(title_template or "斗罗大陆H5-{account_id}号").format(
            index=index,
            number=index,
            account_id=account_id,
            account_name=account_name,
            old_title=record.account_name or "",
            hwnd=record.hwnd or "",
        )

    def _rename_client_direct_bound_windows_after_tile(self, accounts: list[AccountConfig], results) -> None:
        title_template = _safe_wm_title_template(self) or "斗罗大陆H5-{account_id}号"
        successful_hwnds = {int(result.window.hwnd) for result in results if getattr(result, "success", False)}
        records: list[tuple[int, AccountConfig, ClientDirectRunRecord]] = []
        for index, account in enumerate(accounts, start=1):
            record = self.client_direct_bindings.get(account.key)
            if record is None:
                continue
            hwnd = int(record.hwnd or 0)
            if hwnd > 0 and hwnd in successful_hwnds:
                records.append((index, account, record))
        if not records:
            return
        self._log(f"排列本批客户端：开始重命名当前批次窗口，模板={title_template}")
        for index, account, record in records:
            try:
                new_title = LauncherApp._client_direct_binding_title_from_template(title_template, index, record, account)
                ok = bool(user32.SetWindowTextW(int(record.hwnd), new_title))
                if ok:
                    record.title = new_title
                    self.client_direct_bindings[account.key] = record
                    self._log(f"排列本批客户端：重命名成功 account={account.key} hwnd={record.hwnd} title={new_title}")
                else:
                    self._log(f"排列本批客户端：account={account.key} hwnd={record.hwnd} rename_failed reason=SetWindowTextW failed")
            except Exception as exc:
                reason = mask_sensitive_text(str(exc))
                self._log(f"排列本批客户端：account={account.key} hwnd={record.hwnd} rename_failed reason={reason}")
        LauncherApp._save_client_direct_bindings_to_active_batch(self)
        if hasattr(self, "tree"):
            LauncherApp._refresh_table(self)

    def _client_direct_queue_progress_log(self, account: AccountConfig, message: str) -> None:
        masked = mask_sensitive_text(message)
        status = ""
        if "client window bound" in masked:
            status = "客户端已启动/待登录"
        elif "Page.navigate sent" in masked:
            status = "登录中"
        elif "importServer success" in masked:
            status = "importServer成功"
        elif "enterGame called" in masked:
            status = "进入游戏中"
        if status:
            record = self.client_direct_bindings.get(account.key) if hasattr(self, "client_direct_bindings") else None
            if record is not None:
                record.status = status
                self.client_direct_bindings[account.key] = record
                try:
                    LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                except Exception:
                    pass
            self._queue_status(account, status)
        self._queue_log(f"[客户端直登][{account.key}] {masked}")

    def _client_direct_collect_binding_windows(self, accounts: list[AccountConfig]) -> list[GameWindow]:
        windows: list[GameWindow] = []
        if not hasattr(self, "client_direct_bindings"):
            self.client_direct_bindings = {}

        for index, account in enumerate(accounts, start=1):
            record = self.client_direct_bindings.get(account.key)
            if record is None:
                self._log(f"排列本批客户端：跳过 {account.display_name}，缺少准备阶段绑定")
                continue
            if not LauncherApp._client_direct_binding_ready_for_arrange(self, record):
                LauncherApp._client_direct_mark_window_invalid(self, account, record)
                continue
            try:
                rect = get_window_rect(int(record.hwnd))
            except Exception:
                rect = WindowRect(0, 0, 0, 0)
            windows.append(
                GameWindow(
                    hwnd=int(record.hwnd),
                    title=record.account_name or account.display_name,
                    number=index,
                    rect=rect,
                )
            )
        return windows

    def _client_direct_tile_binding_windows(
        self,
        windows: list[GameWindow],
        tile_mode: str,
        tile_config: TileConfig | RowTileConfig,
        layout_window_count: int | None,
        log,
    ):
        slot_indexes = [max(0, int(window.number or index) - 1) for index, window in enumerate(windows, start=1)]
        planned_count = max(int(layout_window_count or 0), max(slot_indexes, default=-1) + 1, len(windows))
        if tile_mode == WM_TILE_MODE_ROW_COUNT:
            plan = calculate_row_tile_plan(planned_count, tile_config)
            work = plan.work_area
            log(
                "按行数排列诊断："
                f"screen_width={plan.screen_width}，screen_height={plan.screen_height}，"
                f"work_area_left={work.left}，work_area_top={work.top}，"
                f"work_area_right={work.right}，work_area_bottom={work.bottom}，"
                f"work_area_width={plan.work_area_width}，work_area_height={plan.work_area_height}"
            )
            log(
                "按行数排列诊断："
                f"cols={plan.cols}，rows={plan.rows}，窗口数量={plan.window_count}，"
                f"target_width={plan.target_width}，target_height={plan.target_height}"
            )
            return tile_game_windows_by_row_count(
                tile_config,
                windows=windows,
                slot_indexes=slot_indexes,
                layout_window_count=planned_count,
                title_template=_safe_wm_title_template(self),
            )
        return tile_game_windows(
            tile_config,
            windows=windows,
            slot_indexes=slot_indexes,
            layout_window_count=planned_count,
            title_template=_safe_wm_title_template(self),
        )

    def _update_client_direct_binding_from_result(
        self,
        account: AccountConfig,
        result,
        *,
        port: int,
        status: str,
        error_message: str = "",
    ) -> None:
        binding = getattr(result, "binding", None)
        if not hasattr(self, "client_direct_bindings"):
            self.client_direct_bindings = {}
        reason = error_message
        if not reason and not getattr(result, "success", False):
            reason = mask_sensitive_text(getattr(result, "message", "") or "")
        existing = self.client_direct_bindings.get(account.key)
        ownership = getattr(result, "ownership", None)
        self.client_direct_bindings[account.key] = ClientDirectRunRecord(
            account_id=account.key,
            account_name=account.display_name,
            account_key=account.key,
            refresh_account_name=str(getattr(existing, "refresh_account_name", "") or account.bookmark_title or account.bookmark_no),
            bookmark_path=str(getattr(existing, "bookmark_path", "") or ""),
            slot_index=int(getattr(existing, "slot_index", 0) or 0),
            identity_status=str(getattr(existing, "identity_status", "") or "resolved"),
            link_status=str(getattr(existing, "link_status", "") or ""),
            window_status=str(getattr(existing, "window_status", "") or ""),
            pid=int(getattr(binding, "pid", 0) or 0),
            hwnd=int(getattr(binding, "hwnd", 0) or 0),
            cdp_port=int(getattr(binding, "cdp_port", port) or port),
            cdp_owner_pid=int(getattr(ownership, "owner_pid", 0) or getattr(existing, "cdp_owner_pid", 0) or 0),
            cdp_ownership_status=str(getattr(ownership, "status", "") or getattr(existing, "cdp_ownership_status", "") or ""),
            speed_rate=float(getattr(existing, "speed_rate", 1.0) or 1.0),
            login_url=account.url,
            status=status,
            error_message=reason,
        )

    def _client_direct_record_to_binding(self, record: ClientDirectRunRecord) -> ClientBinding:
        return ClientBinding(
            account_id=record.account_id,
            account_name=record.account_name,
            pid=int(record.pid or 0),
            hwnd=int(record.hwnd or 0),
            cdp_port=int(record.cdp_port or 0),
            login_url=record.login_url,
            status=record.status,
        )

    def _client_direct_prepare_worker(
        self,
        accounts: list[AccountConfig],
        game_path: str,
        run_label: str,
        base_port: int = CLIENT_DIRECT_CDP_PORT,
        concurrency: int = CLIENT_DIRECT_CONCURRENCY_MIN,
    ) -> None:
        import time as _time

        total = len(accounts)
        success_count = 0
        fail_count = 0
        stopped_count = 0
        start_time = _time.time()
        concurrency = max(CLIENT_DIRECT_CONCURRENCY_MIN, min(CLIENT_DIRECT_CONCURRENCY_MAX, int(concurrency or 1)))
        launch_throttle = _ClientLaunchThrottle()
        self._queue_log(f"[客户端直登] {run_label}开始：总{total}，并发={concurrency}，只启动客户端，不执行登录。")
        self._queue_log(f"[客户端直登] 本次并发数={concurrency}")
        self._update_status_bar(f"{run_label}运行中：0/{total}")

        def run_prepare(item):
            index, account = item
            if self.stop_event.is_set():
                if account.key in self.client_direct_bindings:
                    self.client_direct_bindings[account.key].status = "已停止"
                self._queue_status(account, "已停止")
                return "stopped"

            port = cdp_port_for_index(index, base_port=base_port)
            record = self.client_direct_bindings.get(account.key) or ClientDirectRunRecord(
                account_id=account.key,
                account_name=account.display_name,
                cdp_port=port,
                login_url=account.url,
            )
            record.cdp_port = port
            record.login_url = account.url
            record.status = "客户端启动中"
            record.error_message = ""
            self.client_direct_bindings[account.key] = record
            self._queue_status(account, "客户端启动中")
            self._update_status_bar(f"{run_label}运行中：{index + 1}/{total}")
            entry = _direct_login_entry_label(account.url)
            self._queue_log(f"[客户端直登][{index + 1}/{total}] 准备客户端：{account.display_name}，入口={entry}，端口={port}")

            if not is_complete_direct_login_url(account.url):
                record.status = "URL无效"
                record.error_message = "URL 不是完整客户端直登 URL"
                self._queue_status(account, "URL无效")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] URL无效：入口={entry} 不是完整客户端直登 URL")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "failed"
            if not is_tcp_port_available(port):
                record.status = "端口占用"
                record.error_message = f"CDP 端口 {port} 已被占用"
                self._queue_status(account, "端口占用")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 端口占用：CDP 端口 {port} 已被占用")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "failed"

            if not launch_throttle.wait(self.stop_event):
                record.status = "已停止"
                self._queue_status(account, "已停止")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "stopped"

            result = prepare_client_direct_client(
                ClientDirectLoginConfig(
                    account_id=account.key,
                    account_name=account.display_name,
                    full_login_url=account.url,
                    x5game_path=game_path,
                    cdp_port=port,
                    auto_enter_game=False,
                    timeout=60.0,
                ),
                stop_event=self.stop_event,
                log=lambda message, key=account.key: self._queue_log(f"[客户端直登][{key}] {mask_sensitive_text(message)}"),
            )

            if self.stop_event.is_set() or str(getattr(result, "message", "")) == "用户停止":
                LauncherApp._update_client_direct_binding_from_result(self, account, result, port=port, status="已停止")
                self._queue_status(account, "已停止")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "stopped"

            ownership = getattr(result, "ownership", None)
            prepared_binding = getattr(result, "binding", None)
            binding_verified = bool(
                getattr(result, "success", False)
                and prepared_binding is not None
                and int(getattr(prepared_binding, "pid", 0) or 0) > 0
                and int(getattr(prepared_binding, "hwnd", 0) or 0) > 0
                and int(getattr(prepared_binding, "cdp_port", 0) or 0) == port
                and ownership is not None
                and bool(getattr(ownership, "verified", False))
                and int(getattr(ownership, "hwnd", 0) or 0) == int(getattr(prepared_binding, "hwnd", 0) or 0)
                and int(getattr(ownership, "window_pid", 0) or 0) == int(getattr(prepared_binding, "pid", 0) or 0)
                and int(getattr(ownership, "port", 0) or 0) == port
            )
            if binding_verified:
                LauncherApp._update_client_direct_binding_from_result(self, account, result, port=port, status="客户端已启动/待登录")
                binding = self.client_direct_bindings[account.key]
                self._queue_status(account, "客户端已启动/待登录")
                self._queue_log(
                    f"[客户端直登][{index + 1}/{total}] 客户端已启动/待登录："
                    f"pid={binding.pid} hwnd={binding.hwnd} port={binding.cdp_port}"
                )
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "success"
            reason = mask_sensitive_text(
                getattr(result, "message", "")
                or ("准备结果缺少有效 HWND/PID/CDP 归属" if getattr(result, "success", False) else "未知错误")
            )
            LauncherApp._update_client_direct_binding_from_result(self, account, result, port=port, status="启动失败", error_message=reason)
            self._queue_status(account, "启动失败")
            self._queue_log(f"[客户端直登][{index + 1}/{total}] 启动失败：{reason}")
            LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
            return "failed"

        for outcome in _run_bounded_client_direct_tasks(list(enumerate(accounts)), concurrency, run_prepare):
            if outcome == "success":
                success_count += 1
            elif outcome == "stopped":
                stopped_count += 1
            else:
                fail_count += 1

        elapsed_total = _time.time() - start_time
        if self.stop_event.is_set() or stopped_count:
            summary = f"{run_label}已停止：成功{success_count}，失败{fail_count}，已停止{stopped_count}，总耗时{elapsed_total:.0f}秒"
            self._update_status_bar("已停止")
        else:
            summary = f"{run_label}完成：成功{success_count}，失败{fail_count}，已停止{stopped_count}，总耗时{elapsed_total:.0f}秒"
            self._update_status_bar(f"{run_label}完成：成功{success_count}，失败{fail_count}")
        self._queue_log(summary)
        self._write_file_log(summary)
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        if hasattr(self, "worker_thread"):
            self.worker_thread = None

    def _client_direct_prepared_login_worker(
        self,
        accounts: list[AccountConfig],
        auto_enter_game: bool,
        run_label: str,
        concurrency: int = CLIENT_DIRECT_CONCURRENCY_MIN,
    ) -> None:
        import time as _time

        total = len(accounts)
        success_count = 0
        fail_count = 0
        stopped_count = 0
        start_time = _time.time()
        mode_text = "自动进入游戏" if auto_enter_game else "不自动进入游戏"
        concurrency = max(CLIENT_DIRECT_CONCURRENCY_MIN, min(CLIENT_DIRECT_CONCURRENCY_MAX, int(concurrency or 1)))
        self._queue_log(f"[客户端直登] {run_label}开始：总{total}，并发={concurrency}，使用已准备客户端，{mode_text}。")
        self._queue_log(f"[客户端直登] 本次并发数={concurrency}")
        self._update_status_bar(f"{run_label}运行中：0/{total}")

        def run_login(item):
            index, account = item
            if self.stop_event.is_set():
                if account.key in self.client_direct_bindings:
                    self.client_direct_bindings[account.key].status = "已停止"
                self._queue_status(account, "已停止")
                return "stopped"

            record = self.client_direct_bindings.get(account.key)
            if record is None or not record.pid or not record.hwnd or not record.cdp_port:
                self._queue_status(account, "客户端直登失败")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 客户端直登失败：缺少准备阶段绑定")
                return "failed"
            if record.link_status in {"link_missing", "link_conflict"}:
                record.status = record.link_status
                record.error_message = "最新直登链接缺失" if record.link_status == "link_missing" else "最新直登链接身份冲突"
                self._queue_status(account, record.link_status)
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 已阻止登录：{record.link_status}")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "failed"
            if record.window_status == "cdp_unavailable":
                record.status = "cdp_unavailable"
                record.error_message = "客户端 CDP 当前不可用"
                self._queue_status(account, "cdp_unavailable")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 已阻止登录：cdp_unavailable")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "failed"
            if not LauncherApp._client_direct_is_window_alive(self, int(record.hwnd or 0)):
                record.status = "客户端已关闭"
                record.error_message = "客户端窗口已关闭"
                self.client_direct_bindings[account.key] = record
                self._queue_status(account, "客户端已关闭")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 客户端已关闭：{account.display_name} hwnd={record.hwnd}")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "failed"

            ownership = validate_window_cdp_endpoint(int(record.hwnd), int(record.pid), int(record.cdp_port))
            record.cdp_owner_pid = int(ownership.owner_pid or 0)
            record.cdp_ownership_status = ownership.status
            self._queue_log(f"[客户端直登][{index + 1}/{total}][CDP归属] {ownership.safe_message()}")
            if not ownership.verified:
                record.status = ownership.status
                record.error_message = f"登录前 binding 校验失败: {ownership.status}"
                self._queue_status(account, ownership.status)
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 已阻止登录：{ownership.status}")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "failed"

            port = int(record.cdp_port)
            record.status = "登录中"
            record.error_message = ""
            self.client_direct_bindings[account.key] = record
            self._queue_status(account, "登录中")
            self._update_status_bar(f"{run_label}运行中：{index + 1}/{total}")
            entry = _direct_login_entry_label(record.login_url)
            self._queue_log(
                f"[客户端直登][{index + 1}/{total}] 执行登录："
                f"{account.display_name}，入口={entry}，pid={record.pid} hwnd={record.hwnd} port={port}"
            )

            if not is_complete_direct_login_url(record.login_url):
                record.status = "link_missing"
                record.link_status = "link_missing"
                record.error_message = "URL 不是完整客户端直登 URL"
                self._queue_status(account, "link_missing")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 已阻止登录：link_missing")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "failed"

            speed_options = LauncherApp._client_speed_panel_options(self)
            speed_options["default_speed_rate"] = float(getattr(record, "speed_rate", 1.0) or 1.0)
            result = execute_prepared_client_direct_login(
                PreparedClientDirectLoginConfig(
                    account_id=record.account_id,
                    account_name=record.account_name,
                    full_login_url=record.login_url,
                    cdp_port=port,
                    auto_enter_game=bool(auto_enter_game),
                    timeout=60.0,
                    **speed_options,
                ),
                LauncherApp._client_direct_record_to_binding(self, record),
                stop_event=self.stop_event,
                log=lambda message, current=account: LauncherApp._client_direct_queue_progress_log(self, current, message),
            )

            if self.stop_event.is_set() or str(getattr(result, "message", "")) == "用户停止":
                LauncherApp._update_client_direct_binding_from_result(self, account, result, port=port, status="已停止")
                self._queue_status(account, "已停止")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "stopped"

            if result.success:
                status = "客户端登录成功" if auto_enter_game else "客户端已就绪"
                LauncherApp._update_client_direct_binding_from_result(self, account, result, port=port, status=status)
                self._queue_status(account, status)
                self._queue_log(f"[客户端直登][{index + 1}/{total}] {status}：pid={record.pid} hwnd={record.hwnd} port={port}")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "success"
            reason = mask_sensitive_text(getattr(result, "message", "") or "未知错误")
            LauncherApp._update_client_direct_binding_from_result(self, account, result, port=port, status="客户端直登失败", error_message=reason)
            self._queue_status(account, "客户端直登失败")
            self._queue_log(f"[客户端直登][{index + 1}/{total}] 客户端直登失败：{reason}")
            LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
            return "failed"

        for outcome in _run_bounded_client_direct_tasks(list(enumerate(accounts)), concurrency, run_login):
            if outcome == "success":
                success_count += 1
            elif outcome == "stopped":
                stopped_count += 1
            else:
                fail_count += 1

        elapsed_total = _time.time() - start_time
        if self.stop_event.is_set() or stopped_count:
            summary = f"{run_label}已停止：成功{success_count}，失败{fail_count}，已停止{stopped_count}，总耗时{elapsed_total:.0f}秒"
            self._update_status_bar("已停止")
        else:
            summary = f"{run_label}完成：成功{success_count}，失败{fail_count}，已停止{stopped_count}，总耗时{elapsed_total:.0f}秒"
            self._update_status_bar(f"{run_label}完成：成功{success_count}，失败{fail_count}")
        self._queue_log(summary)
        self._write_file_log(summary)
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        if hasattr(self, "worker_thread"):
            self.worker_thread = None

    def _client_direct_single_worker(self, account: AccountConfig, game_path: str, auto_enter_game: bool) -> None:
        import time as _time

        start_time = _time.time()
        mode_text = "自动进入游戏" if auto_enter_game else "不自动进入游戏"
        self._queue_log(f"[客户端直登] 方式一单账号开始：{account.display_name}，{mode_text}。")
        self._queue_log(f"[客户端直登] 使用 X5Game.exe + CDP 端口 {CLIENT_DIRECT_CDP_PORT}。")
        self._update_status_bar("客户端直登运行中：1/1")
        result = execute_client_direct_login(
            ClientDirectLoginConfig(
                account_id=account.key,
                account_name=account.display_name,
                full_login_url=account.url,
                x5game_path=game_path,
                cdp_port=CLIENT_DIRECT_CDP_PORT,
                auto_enter_game=bool(auto_enter_game),
                timeout=60.0,
                **LauncherApp._client_speed_panel_options(self),
            ),
            stop_event=self.stop_event,
            log=lambda message: LauncherApp._client_direct_queue_progress_log(self, account, message),
        )
        elapsed = _time.time() - start_time
        self._queue_timing(account, elapsed)

        if self.stop_event.is_set():
            self._queue_status(account, "已停止")
            self._queue_log("[客户端直登] 已停止。")
            self._update_status_bar("已停止")
            return

        if result.success:
            status = "客户端登录成功" if auto_enter_game else "客户端已就绪"
            LauncherApp._update_client_direct_binding_from_result(
                self,
                account,
                result,
                port=CLIENT_DIRECT_CDP_PORT,
                status=status,
            )
            self._queue_status(account, status)
            self._queue_log(f"[客户端直登] {status}: {account.display_name}")
            self._update_status_bar(f"客户端直登完成：{status}")
        else:
            reason = mask_sensitive_text(result.message or "未知错误")
            LauncherApp._update_client_direct_binding_from_result(
                self,
                account,
                result,
                port=CLIENT_DIRECT_CDP_PORT,
                status="客户端直登失败",
            )
            self._queue_status(account, "客户端直登失败")
            self._queue_log(f"[客户端直登] 客户端直登失败: {account.display_name}，原因={reason}")
            self._update_status_bar("客户端直登完成：失败1")

        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        if hasattr(self, "worker_thread"):
            self.worker_thread = None

    def _client_direct_serial_worker(
        self,
        accounts: list[AccountConfig],
        game_path: str,
        auto_enter_game: bool,
        run_label: str,
        base_port: int = CLIENT_DIRECT_CDP_PORT,
    ) -> None:
        import time as _time

        total = len(accounts)
        success_count = 0
        fail_count = 0
        stopped_count = 0
        start_time = _time.time()
        mode_text = "自动进入游戏" if auto_enter_game else "不自动进入游戏"
        self._queue_log(f"[客户端直登] {run_label}开始：总{total}，并发=1，{mode_text}。")
        self._update_status_bar(f"{run_label}运行中：0/{total}")

        for index, account in enumerate(accounts):
            if self.stop_event.is_set():
                for remaining in accounts[index:]:
                    self.client_direct_bindings[remaining.key].status = "已停止"
                    self._queue_status(remaining, "已停止")
                    stopped_count += 1
                break

            port = cdp_port_for_index(index, base_port=base_port)
            record = self.client_direct_bindings.get(account.key) or ClientDirectRunRecord(
                account_id=account.key,
                account_name=account.display_name,
                cdp_port=port,
                login_url=account.url,
            )
            record.cdp_port = port
            record.login_url = account.url
            record.status = "客户端启动中"
            self.client_direct_bindings[account.key] = record
            self._queue_status(account, "客户端启动中")
            self._update_status_bar(f"{run_label}运行中：{index + 1}/{total}")
            entry = _direct_login_entry_label(account.url)
            self._queue_log(f"[客户端直登][{index + 1}/{total}] {account.display_name}：入口={entry}，端口={port}")

            if not is_complete_direct_login_url(account.url):
                fail_count += 1
                record.status = "URL无效"
                self._queue_status(account, "URL无效")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] URL无效：入口={entry} 不是完整客户端直登 URL")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                continue
            if not is_tcp_port_available(port):
                fail_count += 1
                record.status = "端口占用"
                self._queue_status(account, "端口占用")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 端口占用：CDP 端口 {port} 已被占用")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                continue

            account_started = _time.time()
            result = execute_client_direct_login(
                ClientDirectLoginConfig(
                    account_id=account.key,
                    account_name=account.display_name,
                    full_login_url=account.url,
                    x5game_path=game_path,
                    cdp_port=port,
                    auto_enter_game=bool(auto_enter_game),
                    timeout=60.0,
                    **LauncherApp._client_speed_panel_options(self),
                ),
                stop_event=self.stop_event,
                log=lambda message, current=account: LauncherApp._client_direct_queue_progress_log(self, current, message),
            )
            self._queue_timing(account, _time.time() - account_started)

            if self.stop_event.is_set() or str(getattr(result, "message", "")) == "用户停止":
                record.status = "已停止"
                self._update_client_direct_binding_from_result(account, result, port=port, status="已停止")
                self._queue_status(account, "已停止")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 已停止。")
                stopped_count += 1
                for remaining in accounts[index + 1:]:
                    self.client_direct_bindings[remaining.key].status = "已停止"
                    self._queue_status(remaining, "已停止")
                    stopped_count += 1
                break

            if result.success:
                success_count += 1
                status = "客户端登录成功" if auto_enter_game else "客户端已就绪"
                self._update_client_direct_binding_from_result(account, result, port=port, status=status)
                binding = self.client_direct_bindings[account.key]
                self._queue_status(account, status)
                self._queue_log(
                    f"[客户端直登][{index + 1}/{total}] {status}："
                    f"pid={binding.pid} hwnd={binding.hwnd} port={binding.cdp_port}"
                )
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
            else:
                fail_count += 1
                reason = mask_sensitive_text(getattr(result, "message", "") or "未知错误")
                self._update_client_direct_binding_from_result(account, result, port=port, status="客户端直登失败")
                self._queue_status(account, "客户端直登失败")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 客户端直登失败：{reason}")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)

        elapsed_total = _time.time() - start_time
        if self.stop_event.is_set() or stopped_count:
            summary = (
                f"{run_label}已停止：成功{success_count}，失败{fail_count}，"
                f"已停止{stopped_count}，总耗时{elapsed_total:.0f}秒"
            )
            self._update_status_bar("已停止")
        else:
            summary = (
                f"{run_label}完成：成功{success_count}，失败{fail_count}，"
                f"已停止{stopped_count}，总耗时{elapsed_total:.0f}秒"
            )
            self._update_status_bar(f"{run_label}完成：成功{success_count}，失败{fail_count}")
        self._queue_log(summary)
        self._write_file_log(summary)
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        if hasattr(self, "worker_thread"):
            self.worker_thread = None

    def _stop_tasks(self) -> None:
        self.stop_event.set()
        self._log("已请求停止任务，正在强制清理子进程。")
        terminated = self._terminate_running_processes()
        if terminated == 0:
            self._log("当前没有需要终止的账号运行子进程。")
        if self._preserve_background_windows:
            self._log("后台任务停止：保留已打开窗口，跳过 chromium.exe 清理。")
        else:
            self._cleanup_external_processes()
        self._log("任务已停止，不会继续执行后续账号。")
        self._update_status_bar("已停止")

    def _on_close(self) -> None:
        if self.is_closing:
            return
        self.is_closing = True
        try:
            listener = getattr(self, "_speed_hotkey_listener", None)
            if listener is not None:
                listener.unregister()
            self._save_window_manager_settings()
            self._log("程序关闭：开始停止任务和清理子进程。")
            self.stop_event.set()
            self._terminate_running_processes()
            self._cleanup_external_processes()
            self._log("程序关闭：清理完成，退出。")
        finally:
            try:
                if self._log_file is not None:
                    self._log_file.close()
                    self._log_file = None
            except Exception:
                pass
            self.destroy()

    def _selected_account(self) -> AccountConfig | None:
        display = self.account_var.get()
        for account in self._filtered_accounts_for_ui():
            if account.display_name == display:
                return account
        return None

    def _update_status_bar(self, text: str) -> None:
        self.ui_queue.put(("status_bar", text))

    def _queue_log(self, message: str) -> None:
        self.ui_queue.put(("log", message))

    def _queue_status(self, account: AccountConfig, status: str) -> None:
        self.ui_queue.put(("status", (account, status)))

    def _queue_passport(self, account: AccountConfig, passport: str) -> None:
        self.ui_queue.put(("passport", (account, passport)))

    def _queue_timing(self, account: AccountConfig, seconds: float) -> None:
        self.timing_by_key[account.key] = f"{seconds:.1f}s"
        self.ui_queue.put(("timing", (account, f"{seconds:.1f}s")))

    def _request_passport(self, account: AccountConfig) -> str | None:
        cached = self.manual_passport_cache.get(account.key)
        if cached:
            return cached
        done = threading.Event()
        result: dict[str, str | None] = {"passport": None}
        self.ui_queue.put(("passport_prompt", (account, done, result)))
        done.wait()
        passport = result["passport"]
        if passport:
            self.manual_passport_cache[account.key] = passport
        return passport

    def _drain_ui_queue(self) -> None:
        if self.is_closing:
            return
        while True:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._log(str(payload))
            elif kind == "status":
                account, status = payload
                self._set_status(account, status)
            elif kind == "passport":
                account, passport = payload
                self._set_passport(account, passport)
            elif kind == "timing":
                account, timing = payload
                self._set_timing(account, timing)
            elif kind == "status_bar":
                self._status_left.set(str(payload))
            elif kind == "passport_prompt":
                account, done, result = payload
                result["passport"] = simpledialog.askstring(
                    "手动确认通行证",
                    f"{account.display_name}\n自动提取失败，请输入当前页面显示的“本次通行证”：",
                    parent=self,
                )
                done.set()
            elif kind == "csv_status":
                account, status = payload
                self._set_csv_status(account, status)
            elif kind == "csv_passport":
                account, passport = payload
                self._set_csv_passport(account, passport)
            elif kind == "csv_timing":
                account, timing = payload
                self._set_csv_timing(account, timing)
        if not self.is_closing:
            self.after(100, self._drain_ui_queue)

    def _set_status(self, account: AccountConfig, status: str) -> None:
        self.status_by_key[account.key] = status
        if self.tree.exists(account.key):
            values = _replace_account_table_value(self.tree.item(account.key, "values"), "status", status)
            # 颜色标签
            tag = ""
            if "成功" in status or "就绪" in status:
                tag = "success"
            elif "已登录" in status or "跳过" in status:
                tag = "skip"
            elif "失败" in status or "错误" in status:
                tag = "failed"
            elif "重试" in status:
                tag = "retry"
            elif status not in ("未开始",):
                tag = "running"
            self.tree.item(account.key, values=values, tags=(tag,))

    def _set_passport(self, account: AccountConfig, passport: str) -> None:
        self.passport_by_key[account.key] = passport
        if self.tree.exists(account.key):
            values = _replace_account_table_value(self.tree.item(account.key, "values"), "passport", passport)
            self.tree.item(account.key, values=values)

    def _set_timing(self, account: AccountConfig, timing: str) -> None:
        self.timing_by_key[account.key] = timing
        if self.tree.exists(account.key):
            values = _replace_account_table_value(self.tree.item(account.key, "values"), "timing", timing)
            self.tree.item(account.key, values=values)

    def _log(self, message: str) -> None:
        message = mask_sensitive_text(message)
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self._write_file_log(message)

    def _settings_with_notice_ratio(self, settings):
        return settings.__class__(
            **{
                **settings.__dict__,
                "notice_close_outside_ratio": (
                    float(self.notice_outside_x_var.get()),
                    float(self.notice_outside_y_var.get()),
                ),
            }
        )

    def _save_notice_outside_ratio(self) -> None:
        path = Path(self.settings_path.get())
        try:
            data = {}
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            data.pop("notice_close_ratio", None)
            data["notice_close_outside_ratio"] = [
                float(self.notice_outside_x_var.get()),
                float(self.notice_outside_y_var.get()),
            ]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._log(f"已保存公告外点击坐标: {data['notice_close_outside_ratio']}")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

