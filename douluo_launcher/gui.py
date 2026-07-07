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
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import urlparse

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None

from .automation import AccountRunner
from .background_capability import build_background_capability_report, write_background_capability_report
from .background_login import (
    BackgroundSingleAccountRunner,
    check_background_runtime_dependencies,
    release_background_playwright_for_current_thread,
)
from .client_batch_store import (
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
from .client_speed_panel import ClientSpeedPanelConfig, apply_speed_rate_to_cdp
from .config import (
    AccountConfig,
    BookmarkCandidate,
    BookmarkRootCandidate,
    CSVAccount,
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
    load_csv_accounts,
    load_settings,
    scan_bookmark_root_candidates,
    select_bookmark_candidate_for_startup,
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
RUN_MODE_FOREGROUND_LABEL = "前台辅助模式"
RUN_MODE_ACCOUNT_PASSWORD_LABEL = "账号密码登录模式"
RUN_MODE_BACKGROUND_LABEL = "后台登录模式（实验）"
RUN_MODE_CLIENT_DIRECT_LABEL = "客户端直登模式"
RUN_MODE_CHOICES = (RUN_MODE_ACCOUNT_PASSWORD_LABEL, RUN_MODE_CLIENT_DIRECT_LABEL)
BACKGROUND_SERIAL_CONCURRENCY = 1
RUN_MODE_BACKGROUND_HINT = "实验功能，支持方式一单账号/当前层串行/全部串行，并发=1"
RUN_MODE_CLIENT_DIRECT_HINT = "客户端直登模式，支持单账号/当前层准备、排列、登录"
CLIENT_DIRECT_CDP_PORT = 9222
CLIENT_DIRECT_CONCURRENCY_MIN = 1
CLIENT_DIRECT_CONCURRENCY_MAX = 8
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
    clean_label = str(label or "").strip()
    if clean_label == RUN_MODE_BACKGROUND_LABEL:
        return "background"
    if clean_label == RUN_MODE_CLIENT_DIRECT_LABEL:
        return "client_direct"
    if clean_label == RUN_MODE_ACCOUNT_PASSWORD_LABEL:
        return "foreground"
    return "foreground"


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
    "window",
    "include_in_all",
    "passport",
    "url",
    "status",
    "timing",
)
ACCOUNT_TABLE_COLUMN_INDEX = {column: index for index, column in enumerate(ACCOUNT_TABLE_COLUMNS)}
ACCOUNT_TABLE_HEADINGS = {
    "level": "层级",
    "bookmark": "收藏编号",
    "window": "窗口号",
    "include_in_all": "参与全部串行",
    "passport": "本次通行证",
    "url": "链接",
    "status": "状态",
    "timing": "耗时",
}
ACCOUNT_TABLE_COLUMNS_CONFIG = {
    "level": {"width": 70, "anchor": tk.CENTER},
    "bookmark": {"width": 70, "anchor": tk.CENTER},
    "window": {"width": 65, "anchor": tk.CENTER},
    "include_in_all": {"width": 95, "anchor": tk.CENTER},
    "passport": {"width": 110, "anchor": tk.CENTER},
    "url": {"width": 390},
    "status": {"width": 130, "anchor": tk.CENTER},
    "timing": {"width": 70, "anchor": tk.CENTER},
}


def _account_table_values(
    account: AccountConfig,
    passport: str = "",
    status: str = "未开始",
    timing: str = "",
) -> tuple[object, ...]:
    return (
        account.level,
        account.bookmark_title or account.bookmark_no,
        account.game_window_no,
        "是" if account.include_in_all else "否",
        passport,
        _account_url_display_value(account.url),
        status,
        timing,
    )


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


_TK_BASE = TkinterDnD.Tk if TkinterDnD is not None else tk.Tk


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
        self.bookmark_root_path = tk.StringVar(value="")
        self.bookmark_root_display_name = tk.StringVar(value="")
        self.bookmark_file_candidate_var = tk.StringVar(value="")
        self.bookmark_root_candidate_var = tk.StringVar(value="")
        self.bookmark_file_candidates = []
        self.bookmark_root_candidates = []
        self.bookmark_file_candidate_by_label: dict[str, object] = {}
        self.bookmark_root_candidate_by_label: dict[str, object] = {}
        self.advanced_config_visible = tk.BooleanVar(value=False)
        self.level_var = tk.StringVar(value="第一层")
        self.account_var = tk.StringVar(value="")
        self.max_workers_var = tk.IntVar(value=4)
        self.batch_verify_rounds_var = tk.IntVar(value=3)
        self.notice_outside_x_var = tk.DoubleVar(value=0.08)
        self.notice_outside_y_var = tk.DoubleVar(value=0.08)
        self.method_var = tk.StringVar(value="method1")
        self.run_mode_var = tk.StringVar(value=RUN_MODE_CLIENT_DIRECT_LABEL)
        self.run_mode_hint_var = tk.StringVar(value="")
        self.account_source_summary_var = tk.StringVar(
            value="当前模式：账号密码登录模式，使用账号密码配置，通过原方式二流程登录。"
        )
        self.client_direct_auto_enter_var = tk.BooleanVar(value=True)
        self.client_direct_concurrency_var = tk.IntVar(value=CLIENT_DIRECT_CONCURRENCY_MIN)
        self.client_direct_login_scope_var = tk.StringVar(value=CLIENT_DIRECT_LOGIN_SCOPE_PENDING)
        self.client_direct_base_port_var = tk.IntVar(value=CLIENT_DIRECT_CDP_PORT)
        self.auto_replace_speed_panel_var = tk.BooleanVar(value=True)
        self.custom_speed_panel_enabled_var = tk.BooleanVar(value=True)
        self.speed_panel_debug_var = tk.BooleanVar(value=False)
        self.speed_panel_remove_original_toggle_var = tk.BooleanVar(value=True)
        self.block_browser_context_menu_var = tk.BooleanVar(value=True)
        self.speed_engine_var = tk.StringVar(value="timer_hook")
        self.default_speed_rate_var = tk.StringVar(value="1.0")
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
        self.client_speed_control_status_var = tk.StringVar(value="成功 0 / 失败 0 / 跳过 0")
        self.csv_path = tk.StringVar(value="")
        self.level_count_vars = {level: tk.IntVar(value=8) for level in LEVELS}
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
        self.csv_accounts: list[CSVAccount] = []
        self.csv_status_by_key: dict[str, str] = {}
        self.csv_passport_by_key: dict[str, str] = {}
        self.csv_timing_by_key: dict[str, str] = {}

        self._apply_settings_defaults()
        self._build_widgets()
        self._load_window_manager_settings()
        self._load_client_direct_sessions()
        self._log_bookmark_startup_state()
        self._auto_load_csv()
        self.after(100, self._drain_ui_queue)
        self._load_default_config_if_present()
        self._log_admin_status_warning()
        self._log_startup_dm_environment()
        self._log_background_capability_summary()
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
        self.bookmark_root_path.set(settings.bookmark_root_path)
        self.bookmark_root_display_name.set(settings.bookmark_root_display_name)
        self.max_workers_var.set(settings.max_workers)
        self.notice_outside_x_var.set(settings.notice_close_outside_ratio[0])
        self.notice_outside_y_var.set(settings.notice_close_outside_ratio[1])
        self.auto_replace_speed_panel_var.set(bool(settings.auto_replace_speed_panel))
        self.custom_speed_panel_enabled_var.set(bool(settings.custom_speed_panel_enabled))
        self.speed_panel_debug_var.set(bool(getattr(settings, "speed_panel_debug", False)))
        self.speed_panel_remove_original_toggle_var.set(bool(getattr(settings, "speed_panel_remove_original_toggle", True)))
        self.block_browser_context_menu_var.set(bool(getattr(settings, "block_browser_context_menu", True)))
        self.speed_engine_var.set(str(settings.speed_engine or "timer_hook"))
        self.default_speed_rate_var.set(str(float(settings.default_speed_rate or 1.0)))
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
            data["bookmark_root_path"] = self.bookmark_root_path.get().strip()
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
        ttk.Label(self.wm_game_path_row, text="游戏程序：", width=12, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 8)
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

        self.wm_hint_frame = ttk.Frame(window_frame)
        self.wm_hint_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))
        self.wm_hint_frame.columnconfigure(1, weight=1)
        ttk.Label(self.wm_hint_frame, text="提示：", width=12, anchor="e").grid(row=0, column=0, sticky="e", padx=(0, 8))
        self.wm_game_hint_label = ttk.Label(
            self.wm_hint_frame,
            textvariable=self.wm_game_hint_var,
            foreground="#006666",
        )
        self.wm_game_hint_label.grid(row=0, column=1, sticky="w")
        self.wm_game_status_label = ttk.Label(
            self.wm_hint_frame,
            textvariable=self.wm_game_status_var,
            foreground="#666666",
        )
        self.wm_game_status_label.grid(row=0, column=2, sticky="w", padx=(24, 0))

        self.wm_compact_frame = ttk.Frame(window_frame)
        self.wm_compact_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 0))
        self.wm_compact_frame.columnconfigure(0, weight=1)
        self.wm_compact_frame.columnconfigure(1, weight=1)

        self.wm_legacy_launch_frame = ttk.Frame(self.wm_compact_frame)
        self.wm_legacy_launch_frame.grid(row=1, column=1, sticky="ew", padx=(16, 0), pady=(0, 4))
        ttk.Label(self.wm_legacy_launch_frame, text="旧启动项：", width=12, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 8)
        )
        self.wm_launch_count_label = ttk.Label(self.wm_legacy_launch_frame, text="打开数量")
        self.wm_launch_count_label.grid(row=0, column=1, sticky="e", padx=(0, 4))
        self.wm_launch_count_spin = ttk.Spinbox(
            self.wm_legacy_launch_frame,
            from_=1,
            to=99,
            increment=1,
            textvariable=self.wm_launch_count_var,
            width=6,
        )
        self.wm_launch_count_spin.grid(row=0, column=2, sticky="w", padx=(0, 16))
        self.wm_launch_interval_label = ttk.Label(self.wm_legacy_launch_frame, text="启动间隔(ms)")
        self.wm_launch_interval_label.grid(row=0, column=3, sticky="e", padx=(0, 4))
        self.wm_launch_interval_spin = ttk.Spinbox(
            self.wm_legacy_launch_frame,
            from_=0,
            to=60000,
            increment=100,
            textvariable=self.wm_launch_interval_var,
            width=6,
        )
        self.wm_launch_interval_spin.grid(row=0, column=4, sticky="w", padx=(0, 16))
        self.wm_auto_tile_after_launch_check = ttk.Checkbutton(
            self.wm_legacy_launch_frame,
            text="启动后自动排列",
            variable=self.wm_auto_tile_after_launch_var,
        )
        self.wm_auto_tile_after_launch_check.grid(row=0, column=5, sticky="w")
        self.wm_legacy_launch_grid_widgets = (
            self.wm_legacy_launch_frame,
        )

        self.wm_layout_frame = ttk.Frame(self.wm_compact_frame)
        self.wm_layout_frame.grid(row=0, column=0, rowspan=2, sticky="nw", pady=(0, 2))
        self.wm_layout_frame.columnconfigure(1, minsize=88)
        self.wm_layout_frame.columnconfigure(3, minsize=88)
        ttk.Label(self.wm_layout_frame, text="布局参数：", width=12, anchor="e").grid(
            row=0, column=0, rowspan=4, sticky="ne", padx=(0, 8), pady=3
        )
        ttk.Label(self.wm_layout_frame, text="排列方式").grid(row=0, column=1, sticky="w", padx=(0, 4), pady=2)
        self.wm_tile_mode_combo = ttk.Combobox(
            self.wm_layout_frame,
            textvariable=self.wm_tile_mode_var,
            values=(WM_TILE_MODE_FIXED, WM_TILE_MODE_ROW_COUNT),
            state="readonly",
            width=14,
        )
        self.wm_tile_mode_combo.grid(row=0, column=2, sticky="w", padx=(0, 24), pady=2)
        self.wm_tile_mode_combo.bind("<<ComboboxSelected>>", lambda _: self._wm_on_tile_mode_changed())
        self.wm_fixed_param_widgets = []
        self.wm_row_param_widgets = []

        def add_widget(widget, row: int, column: int, **grid_options):
            widget.grid(row=row, column=column, **grid_options)
            return widget

        fixed_specs = (
            (0, 3, "每行数量", "spin", self.wm_per_row_var, 1, 99),
            (1, 1, "窗口宽度", "entry", self.wm_window_width_var, None, None),
            (1, 3, "窗口高度", "entry", self.wm_window_height_var, None, None),
            (2, 1, "起点X", "spin", self.wm_start_x_var, -5000, 5000),
            (2, 3, "起点Y", "spin", self.wm_start_y_var, -5000, 5000),
            (3, 1, "横向偏移", "spin", self.wm_offset_x_var, -5000, 5000),
            (3, 3, "纵向偏移", "spin", self.wm_offset_y_var, -5000, 5000),
        )
        for row, label_column, label, kind, variable, min_value, max_value in fixed_specs:
            input_column = label_column + 1
            label_widget = add_widget(
                ttk.Label(self.wm_layout_frame, text=label),
                row,
                label_column,
                sticky="w",
                padx=(0, 4),
                pady=1,
            )
            if kind == "entry":
                input_widget = add_widget(
                    ttk.Entry(self.wm_layout_frame, textvariable=variable, width=7),
                    row,
                    input_column,
                    sticky="w",
                    padx=(0, 12),
                    pady=1,
                )
            else:
                input_widget = add_widget(
                    ttk.Spinbox(self.wm_layout_frame, from_=min_value, to=max_value, increment=1,
                                textvariable=variable, width=6),
                    row,
                    input_column,
                    sticky="w",
                    padx=(0, 12),
                    pady=1,
                )
            self.wm_fixed_param_widgets.extend((label_widget, input_widget))

        self.wm_title_frame = ttk.Frame(self.wm_compact_frame)
        self.wm_title_frame.grid(row=0, column=1, sticky="new", padx=(16, 0), pady=(0, 4))
        self.wm_title_frame.columnconfigure(3, weight=1)
        ttk.Label(self.wm_title_frame, text="标题设置：", width=12, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 8)
        )
        ttk.Checkbutton(
            self.wm_title_frame,
            text="排列后自动编号标题",
            variable=self.wm_auto_rename_after_tile_var,
        ).grid(row=0, column=1, sticky="w", padx=(0, 20))
        ttk.Label(self.wm_title_frame, text="标题模板").grid(row=0, column=2, sticky="e", padx=(0, 4))
        ttk.Entry(self.wm_title_frame, textvariable=self.wm_title_template_var, width=28).grid(
            row=0, column=3, sticky="w", padx=(0, 8)
        )
        ttk.Button(self.wm_title_frame, text="重命名", width=8, command=self._wm_rename_windows).grid(
            row=0, column=4, sticky="w"
        )
        ttk.Checkbutton(
            self.wm_title_frame,
            text="禁止超出屏幕宽度",
            variable=self.wm_prevent_overflow_var,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=(4, 0))

        window_action_row = ttk.Frame(self.wm_compact_frame)
        window_action_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))
        ttk.Label(window_action_row, text="窗口操作：", width=12, anchor="e").pack(side=tk.LEFT, padx=(0, 8))
        self.wm_launch_btn = ttk.Button(window_action_row, text="批量启动窗口", width=18,
                                        command=self._wm_launch_windows)
        self.wm_launch_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.wm_identify_btn = ttk.Button(window_action_row, text="识别窗口", width=18,
                                          command=self._wm_identify_windows)
        self.wm_identify_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.wm_tile_btn = ttk.Button(window_action_row, text="排列窗口", width=18,
                                      command=self._wm_tile_windows)
        self.wm_tile_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.wm_refresh_slots_btn = ttk.Button(window_action_row, text="刷新槽位映射", width=18,
                                               command=self._wm_refresh_window_slots)
        self.wm_refresh_slots_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.wm_regenerate_slots_btn = ttk.Button(window_action_row, text="重新生成槽位", width=18,
                                                  command=self._wm_regenerate_slots)
        self.wm_regenerate_slots_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(window_action_row, text="目标槽位").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(window_action_row, from_=1, to=99, increment=1,
                    textvariable=self.wm_repair_slot_var, width=5).pack(side=tk.LEFT, padx=(0, 6))
        self.wm_repair_slot_btn = ttk.Button(window_action_row, text="修复窗口", width=12,
                                             command=self._wm_repair_window_slot)
        self.wm_repair_slot_btn.pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(window_action_row, text="关闭窗口", width=18, fg="#cc0000",
                  command=self._wm_close_windows, font=("", 9, "bold")).pack(side=tk.LEFT, padx=(0, 8))

        # ===== 2. 工作模式 =====
        work_mode_frame = ttk.LabelFrame(root, text="工作模式", padding=4)
        work_mode_frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(work_mode_frame, text="工作模式").pack(side=tk.LEFT, padx=(4, 8))
        self.run_mode_account_password_btn = tk.Radiobutton(
            work_mode_frame,
            text=RUN_MODE_ACCOUNT_PASSWORD_LABEL,
            variable=self.run_mode_var,
            value=RUN_MODE_ACCOUNT_PASSWORD_LABEL,
            indicatoron=False,
            width=18,
            padx=10,
            pady=4,
            command=self._on_account_password_run_mode_changed,
        )
        self.run_mode_account_password_btn.pack(side=tk.LEFT, padx=(0, 8))
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
        self.run_mode_foreground_btn = tk.Radiobutton(
            work_mode_frame,
            text="旧版兼容模式",
            variable=self.run_mode_var,
            value=RUN_MODE_FOREGROUND_LABEL,
            indicatoron=False,
            width=18,
            padx=10,
            pady=4,
            command=self._on_legacy_compat_run_mode_changed,
        )
        self.run_mode_foreground_btn.pack(side=tk.LEFT, padx=(0, 12))
        self.run_mode_foreground_btn.pack_forget()
        ttk.Label(work_mode_frame, textvariable=self.run_mode_hint_var, foreground="#996600").pack(side=tk.LEFT)

        # ===== 3. 读取收藏夹 / 账号配置 =====
        config_frame = ttk.LabelFrame(root, text="读取收藏夹 / 账号配置", padding=4)
        config_frame.pack(fill=tk.X, pady=(0, 6))
        config_frame.columnconfigure(1, weight=1)

        account_password_summary_text = "当前模式：账号密码登录模式，使用账号密码配置，通过原方式二流程登录。"
        try:
            self.account_source_summary_var.set(account_password_summary_text)
        except Exception:
            pass
        self.account_source_summary_row = ttk.Frame(config_frame)
        self.account_source_summary_row.grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 6))
        ttk.Label(
            self.account_source_summary_row,
            textvariable=self.account_source_summary_var,
            foreground="#666666",
        ).pack(side=tk.LEFT, padx=(4, 8))

        self.method_row = ttk.Frame(config_frame)
        self.method_row.grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 6))
        ttk.Label(self.method_row, text="上号方式").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Radiobutton(self.method_row, text="旧版通行证上号（兼容）", variable=self.method_var, value="method1",
                        command=self._on_method_changed).pack(side=tk.LEFT, padx=(0, 24))
        ttk.Radiobutton(self.method_row, text="账号密码登录模式", variable=self.method_var, value="method2",
                        command=self._on_method_changed).pack(side=tk.LEFT)
        self.method_row.grid_remove()

        self._method1_row1 = ttk.Label(config_frame, text="浏览器收藏夹", width=12, anchor="e")
        self._method1_row1.grid(row=1, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_btn_auto_bookmark = ttk.Button(
            config_frame,
            text="自动查找收藏夹",
            command=self._auto_find_bookmarks,
        )
        self._method1_btn_auto_bookmark.grid(row=1, column=1, sticky="w", padx=4, pady=3)
        self._method1_btn_load = ttk.Button(config_frame, text="读取账号", command=self._load_accounts)
        self._method1_btn_load.grid(row=1, column=2, sticky="w", padx=4, pady=3)

        self._method1_row2a = ttk.Label(config_frame, text="收藏候选", width=12, anchor="e")
        self._method1_row2a.grid(row=2, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_bookmark_candidate_combo = ttk.Combobox(
            config_frame,
            textvariable=self.bookmark_file_candidate_var,
            state="readonly",
            values=(),
        )
        self._method1_bookmark_candidate_combo.grid(row=2, column=1, columnspan=4, sticky="ew", padx=4, pady=3)
        self._method1_bookmark_candidate_combo.bind("<<ComboboxSelected>>", lambda _: self._on_bookmark_candidate_selected())

        self._method1_row3a = ttk.Label(config_frame, text="账号目录", width=12, anchor="e")
        self._method1_row3a.grid(row=3, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_root_combo = ttk.Combobox(
            config_frame,
            textvariable=self.bookmark_root_candidate_var,
            state="readonly",
            values=(),
        )
        self._method1_root_combo.grid(row=3, column=1, columnspan=4, sticky="ew", padx=4, pady=3)
        self._method1_root_combo.bind("<<ComboboxSelected>>", lambda _: self._on_bookmark_root_candidate_selected())

        self._method1_advanced_toggle_btn = ttk.Button(
            config_frame,
            text="显示高级配置",
            command=self._toggle_advanced_config,
        )
        self._method1_advanced_toggle_btn.grid(row=4, column=1, sticky="w", padx=4, pady=(4, 3))

        self._method1_advanced_frame = ttk.LabelFrame(config_frame, text="高级配置", padding=4)
        self._method1_advanced_frame.grid(row=5, column=0, columnspan=5, sticky="ew", padx=4, pady=(0, 4))
        self._method1_advanced_frame.columnconfigure(1, weight=1)

        self._method1_bookmark_path_label = ttk.Label(
            self._method1_advanced_frame, text="收藏文件路径", width=14, anchor="e"
        )
        self._method1_bookmark_path_label.grid(row=0, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_bookmark_entry = ttk.Entry(self._method1_advanced_frame, textvariable=self.bookmark_path)
        self._method1_bookmark_entry.grid(row=0, column=1, sticky="ew", padx=4, pady=3)
        self._method1_btn_pick = ttk.Button(
            self._method1_advanced_frame,
            text="手动选择 Bookmarks",
            command=self._pick_bookmark_file,
        )
        self._method1_btn_pick.grid(row=0, column=2, padx=4, pady=3)

        self._method1_root_path_label = ttk.Label(
            self._method1_advanced_frame, text="bookmark_root_path", width=14, anchor="e"
        )
        self._method1_root_path_label.grid(row=1, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_root_path_entry = ttk.Entry(self._method1_advanced_frame, textvariable=self.bookmark_root_path)
        self._method1_root_path_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=4, pady=3)

        self._method1_root_name_label = ttk.Label(
            self._method1_advanced_frame, text="兼容目录名", width=14, anchor="e"
        )
        self._method1_root_name_label.grid(row=2, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_root_name_entry = ttk.Entry(self._method1_advanced_frame, textvariable=self.bookmark_root_name)
        self._method1_root_name_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=4, pady=3)

        self._method1_row4a = ttk.Label(self._method1_advanced_frame, text="自动化设置", width=14, anchor="e")
        self._method1_row4a.grid(row=3, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_settings_entry = ttk.Entry(self._method1_advanced_frame, textvariable=self.settings_path)
        self._method1_settings_entry.grid(row=3, column=1, sticky="ew", padx=4, pady=3)
        self._method1_btn_settings = ttk.Button(
            self._method1_advanced_frame, text="选择", width=8, command=self._pick_settings
        )
        self._method1_btn_settings.grid(row=3, column=2, padx=4, pady=3)

        self._method1_level_count_label = ttk.Label(
            self._method1_advanced_frame, text="每层数量", width=14, anchor="e"
        )
        self._method1_level_count_label.grid(row=4, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_level_count_frame = ttk.Frame(self._method1_advanced_frame)
        self._method1_level_count_frame.grid(row=4, column=1, columnspan=2, sticky="w", padx=4, pady=3)
        for level in LEVELS:
            ttk.Label(self._method1_level_count_frame, text=level).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Spinbox(
                self._method1_level_count_frame,
                from_=0,
                to=99,
                increment=1,
                textvariable=self.level_count_vars[level],
                width=5,
            ).pack(side=tk.LEFT, padx=(0, 12))
        self._client_direct_port_settings_label = ttk.Label(
            self._method1_advanced_frame, text="端口设置", width=14, anchor="e"
        )
        self._client_direct_port_settings_label.grid(row=5, column=0, sticky="e", padx=(4, 6), pady=3)
        self._client_direct_port_settings_frame = ttk.Frame(self._method1_advanced_frame)
        self._client_direct_port_settings_frame.grid(row=5, column=1, columnspan=2, sticky="w", padx=4, pady=3)
        ttk.Label(self._client_direct_port_settings_frame, text="默认端口起点").pack(side=tk.LEFT, padx=(0, 4))
        self.client_direct_base_port_spin = ttk.Spinbox(
            self._client_direct_port_settings_frame,
            from_=1024,
            to=65500,
            increment=1,
            textvariable=self.client_direct_base_port_var,
            width=7,
            command=self._sync_client_direct_port_range,
        )
        self.client_direct_base_port_spin.pack(side=tk.LEFT)
        ttk.Label(self._client_direct_port_settings_frame, text="自动寻找连续可用端口").pack(
            side=tk.LEFT, padx=(10, 0)
        )

        self._client_speed_panel_label = ttk.Label(
            self._method1_advanced_frame, text="加速面板", width=14, anchor="e"
        )
        self._client_speed_panel_label.grid(row=6, column=0, sticky="e", padx=(4, 6), pady=3)
        self._client_speed_panel_frame = ttk.Frame(self._method1_advanced_frame)
        self._client_speed_panel_frame.grid(row=6, column=1, columnspan=2, sticky="w", padx=4, pady=3)
        ttk.Checkbutton(
            self._client_speed_panel_frame,
            text="替换网页加速浮层",
            variable=self.auto_replace_speed_panel_var,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            self._client_speed_panel_frame,
            text="显示自定义变速器",
            variable=self.custom_speed_panel_enabled_var,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            self._client_speed_panel_frame,
            text="原浮层诊断日志",
            variable=self.speed_panel_debug_var,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            self._client_speed_panel_frame,
            text="删除原入口按钮",
            variable=self.speed_panel_remove_original_toggle_var,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            self._client_speed_panel_frame,
            text="拦截右键菜单",
            variable=self.block_browser_context_menu_var,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(self._client_speed_panel_frame, text="默认倍率").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(self._client_speed_panel_frame, textvariable=self.default_speed_rate_var, width=6).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Label(self._client_speed_panel_frame, text="位置").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Combobox(
            self._client_speed_panel_frame,
            textvariable=self.speed_panel_position_var,
            values=("左上角",),
            width=8,
            state="readonly",
        ).pack(side=tk.LEFT)
        self._method1_advanced_frame.grid_remove()

        self._method2_row1 = ttk.Label(config_frame, text="CSV文件", width=12, anchor="e")
        self._method2_csv_entry = ttk.Entry(config_frame, textvariable=self.csv_path)
        self._method2_btn_pick = ttk.Button(config_frame, text="选择", width=8, command=self._pick_csv_file)
        self._method2_btn_import = ttk.Button(config_frame, text="导入CSV", command=self._import_csv)
        self._method2_row1.grid(row=1, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method2_csv_entry.grid(row=1, column=1, sticky="ew", padx=4, pady=3)
        self._method2_btn_pick.grid(row=1, column=2, padx=4, pady=3)
        self._method2_btn_import.grid(row=1, column=3, padx=4, pady=3)
        self._method2_row1.grid_remove()
        self._method2_csv_entry.grid_remove()
        self._method2_btn_pick.grid_remove()
        self._method2_btn_import.grid_remove()

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
            ("执行客户端登录", 16, self._login_prepared_client_direct_current_scope, 0, 4),
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

        self.foreground_run_frame = ttk.LabelFrame(run_frame, text="前台辅助模式", padding=4)
        self.foreground_run_frame.pack(fill=tk.X, pady=(0, 4))
        foreground_param_row = ttk.Frame(self.foreground_run_frame)
        foreground_param_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(foreground_param_row, text="并发").pack(side=tk.LEFT, padx=(2, 4))
        ttk.Label(foreground_param_row, text="1", relief="sunken", width=4, anchor="center", padding=2).pack(side=tk.LEFT)
        ttk.Label(foreground_param_row, text="重试次数").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Spinbox(foreground_param_row, from_=1, to=9, textvariable=self.batch_verify_rounds_var,
                    width=5).pack(side=tk.LEFT)

        foreground_action_row = ttk.Frame(self.foreground_run_frame)
        foreground_action_row.pack(fill=tk.X)
        ttk.Button(foreground_action_row, text="单账号运行", width=14, command=self._run_selected_account).pack(side=tk.LEFT, padx=2)
        ttk.Button(foreground_action_row, text="当前层串行", width=14, command=self._run_level_serial).pack(side=tk.LEFT, padx=2)
        ttk.Button(foreground_action_row, text="全部串行", width=14, command=self._run_all_serial).pack(side=tk.LEFT, padx=2)
        self.stop_btn = tk.Button(foreground_action_row, text="停止任务", width=12, fg="#cc0000",
                                   command=self._stop_tasks, font=("", 9, "bold"))
        self.stop_btn.pack(side=tk.LEFT, padx=2)

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

        # 账号列表（方式二）
        self._table_frame_m2 = ttk.LabelFrame(self._content_area, text="CSV账号列表（方式二）", padding=2)
        csv_columns = ("name", "url", "username", "password_status", "window", "passport", "status", "timing")
        self.csv_tree = ttk.Treeview(self._table_frame_m2, columns=csv_columns, show="headings", height=10)
        self.csv_tree.heading("name", text="名称")
        self.csv_tree.heading("url", text="链接")
        self.csv_tree.heading("username", text="账号")
        self.csv_tree.heading("password_status", text="密码")
        self.csv_tree.heading("window", text="窗口号")
        self.csv_tree.heading("passport", text="本次通行证")
        self.csv_tree.heading("status", text="状态")
        self.csv_tree.heading("timing", text="耗时")
        self.csv_tree.column("name", width=100)
        self.csv_tree.column("url", width=280)
        self.csv_tree.column("username", width=100, anchor=tk.CENTER)
        self.csv_tree.column("password_status", width=60, anchor=tk.CENTER)
        self.csv_tree.column("window", width=60, anchor=tk.CENTER)
        self.csv_tree.column("passport", width=110, anchor=tk.CENTER)
        self.csv_tree.column("status", width=100, anchor=tk.CENTER)
        self.csv_tree.column("timing", width=70, anchor=tk.CENTER)
        self.csv_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        csv_scrollbar = ttk.Scrollbar(self._table_frame_m2, command=self.csv_tree.yview)
        csv_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.csv_tree.configure(yscrollcommand=csv_scrollbar.set)

        self.csv_tree.tag_configure("running", foreground="#0066cc")
        self.csv_tree.tag_configure("success", foreground="#008800")
        self.csv_tree.tag_configure("failed", foreground="#cc0000")
        self.csv_tree.tag_configure("retry", foreground="#cc6600")
        self.csv_tree.tag_configure("skip", foreground="#888888")

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

    def _toggle_advanced_config(self) -> None:
        self.advanced_config_visible.set(not self.advanced_config_visible.get())
        self._sync_advanced_config_visibility()

    def _sync_advanced_config_visibility(self) -> None:
        if not hasattr(self, "_method1_advanced_frame"):
            return
        visible = bool(self.advanced_config_visible.get()) and self._account_source_uses_bookmarks()
        if visible:
            self._method1_advanced_frame.grid()
            self._method1_advanced_toggle_btn.configure(text="隐藏高级配置")
        else:
            self._method1_advanced_frame.grid_remove()
            self._method1_advanced_toggle_btn.configure(text="显示高级配置")
        foreground_btn = getattr(self, "run_mode_foreground_btn", None)
        if foreground_btn is not None:
            current_run_mode = ""
            try:
                current_run_mode = str(self.run_mode_var.get() or "")
            except Exception:
                current_run_mode = ""
            if visible or current_run_mode == RUN_MODE_FOREGROUND_LABEL:
                foreground_btn.pack(side=tk.LEFT, padx=(0, 12))
            else:
                foreground_btn.pack_forget()

    def _on_account_password_run_mode_changed(self) -> None:
        try:
            self.method_var.set("method2")
        except Exception:
            pass
        self._on_run_mode_changed()

    def _on_legacy_compat_run_mode_changed(self) -> None:
        try:
            self.method_var.set("method1")
        except Exception:
            pass
        self._on_run_mode_changed()

    def _on_run_mode_changed(self) -> None:
        if self._is_background_run_mode():
            self.run_mode_hint_var.set(RUN_MODE_BACKGROUND_HINT)
            self._status_mid.set(f"当前模式：{RUN_MODE_BACKGROUND_LABEL}")
            self._log(f"已选择{RUN_MODE_BACKGROUND_LABEL}：{RUN_MODE_BACKGROUND_HINT}。")
        elif self._is_client_direct_run_mode():
            self.run_mode_hint_var.set(RUN_MODE_CLIENT_DIRECT_HINT)
            self._status_mid.set(f"当前模式：{RUN_MODE_CLIENT_DIRECT_LABEL}")
            auto_text = "自动进入游戏" if self._client_direct_auto_enter_game() else "停在公告/进入游戏前"
            self._log(f"已选择{RUN_MODE_CLIENT_DIRECT_LABEL}：{RUN_MODE_CLIENT_DIRECT_HINT}，{auto_text}。")
        else:
            self.run_mode_hint_var.set("")
            label = RUN_MODE_ACCOUNT_PASSWORD_LABEL if self.method_var.get() == "method2" else "旧版兼容模式"
            self._status_mid.set(f"当前模式：{label}")
            self._log(f"已选择{label}。")
        self._sync_work_mode_visibility()
        self._sync_account_source_controls()
        self._sync_client_direct_controls()
        self._sync_work_mode_buttons()

    def _is_background_run_mode(self) -> bool:
        return _run_mode_key_for_owner(self) == "background"

    def _is_client_direct_run_mode(self) -> bool:
        return _run_mode_key_for_owner(self) == "client_direct"

    def _sync_client_direct_controls(self) -> None:
        check = getattr(self, "client_direct_auto_enter_check", None)
        spin = getattr(self, "client_direct_base_port_spin", None)
        if self._is_client_direct_run_mode():
            if check is not None:
                check.state(["!disabled"])
            if spin is not None:
                spin.state(["!disabled"])
        else:
            if check is not None:
                check.state(["disabled"])
            if spin is not None:
                spin.state(["disabled"])
        self._sync_client_direct_port_range()

    def _sync_work_mode_visibility(self) -> None:
        client_direct = self._is_client_direct_run_mode()
        client_frame = getattr(self, "client_direct_run_frame", None)
        foreground_frame = getattr(self, "foreground_run_frame", None)
        if client_frame is not None:
            if client_direct:
                client_frame.pack(fill=tk.X, pady=(0, 4))
            else:
                client_frame.pack_forget()
        if foreground_frame is not None:
            if client_direct:
                foreground_frame.pack_forget()
            else:
                foreground_frame.pack(fill=tk.X, pady=(0, 4))

        for widget in getattr(self, "wm_legacy_launch_grid_widgets", ()):
            if client_direct:
                widget.grid_remove()
            else:
                widget.grid()
        launch_btn = getattr(self, "wm_launch_btn", None)
        if launch_btn is not None:
            if client_direct:
                launch_btn.pack_forget()
            else:
                try:
                    launch_btn.pack(side=tk.LEFT, padx=(4, 10), before=self.wm_identify_btn)
                except Exception:
                    launch_btn.pack(side=tk.LEFT, padx=(4, 10))

    def _sync_work_mode_buttons(self) -> None:
        client_direct = self._is_client_direct_run_mode()
        account_password = (not client_direct) and self.method_var.get() == "method2"
        legacy_compat = (not client_direct) and not account_password
        pairs = (
            (getattr(self, "run_mode_account_password_btn", None), account_password),
            (getattr(self, "run_mode_client_btn", None), client_direct),
            (getattr(self, "run_mode_foreground_btn", None), legacy_compat),
        )
        for button, selected in pairs:
            if button is None:
                continue
            try:
                button.configure(
                    relief=tk.SUNKEN if selected else tk.RAISED,
                    bg="#d9edf7" if selected else self.cget("bg"),
                    activebackground="#d9edf7" if selected else self.cget("bg"),
                )
            except Exception:
                pass

    def _account_source_uses_bookmarks(self) -> bool:
        return self._is_client_direct_run_mode() or self.method_var.get() == "method1"

    def _sync_account_source_controls(self) -> None:
        client_direct = self._is_client_direct_run_mode()
        current_run_mode = ""
        try:
            current_run_mode = str(self.run_mode_var.get() or "")
        except Exception:
            current_run_mode = ""
        advanced_var = getattr(self, "advanced_config_visible", None)
        try:
            advanced_visible = bool(advanced_var.get()) if advanced_var is not None else False
        except Exception:
            advanced_visible = False
        show_legacy_method_row = (
            not client_direct
            and (
                current_run_mode == RUN_MODE_FOREGROUND_LABEL
                or advanced_visible
            )
        )
        if not client_direct and not show_legacy_method_row and self.method_var.get() != "method2":
            self.method_var.set("method2")
        use_bookmarks = self._account_source_uses_bookmarks()
        summary_row = getattr(self, "account_source_summary_row", None)
        if summary_row is not None:
            if show_legacy_method_row:
                summary_row.grid_remove()
            else:
                if client_direct:
                    self.account_source_summary_var.set("当前模式：客户端直登模式，使用收藏夹完整直登链接启动 X5Game。")
                else:
                    self.account_source_summary_var.set("当前模式：账号密码登录模式，使用账号密码配置，通过原方式二流程登录。")
                summary_row.grid()
        if hasattr(self, "method_row"):
            if show_legacy_method_row:
                self.method_row.grid()
            else:
                self.method_row.grid_remove()
        for w in (
            self._method1_row1,
            self._method1_btn_auto_bookmark,
            self._method1_btn_load,
            self._method1_row2a,
            self._method1_bookmark_candidate_combo,
            self._method1_row3a,
            self._method1_root_combo,
            self._method1_advanced_toggle_btn,
        ):
            w.grid() if use_bookmarks else w.grid_remove()
        if use_bookmarks:
            self._sync_advanced_config_visibility()
        else:
            self._method1_advanced_frame.grid_remove()
        for w in (self._method2_row1, self._method2_csv_entry, self._method2_btn_pick, self._method2_btn_import):
            w.grid() if not use_bookmarks else w.grid_remove()
        if use_bookmarks:
            self._table_frame_m2.grid_remove()
            self._table_frame_m1.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
            self._refresh_account_choices()
        else:
            self._table_frame_m1.grid_remove()
            self._table_frame_m2.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        if hasattr(self, "group_settings_btn"):
            self.group_settings_btn.configure(state=tk.NORMAL if use_bookmarks else tk.DISABLED)

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
            "block_browser_context_menu": _safe_bool_var(self, "block_browser_context_menu_var", True),
        }

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
        if status in {"pid_missing", "pid_not_x5game", "binding_invalid", "cdp_owner_mismatch", "cdp_unavailable", "hwnd_invalid"}:
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
        rate = LauncherApp._client_speed_control_rate(self, rate_override)
        if rate is None:
            return
        scope_var = getattr(self, "client_speed_control_scope_var", None)
        scope = str(scope_var.get() if scope_var is not None else CLIENT_SPEED_SCOPE_CURRENT_BATCH)
        bindings = LauncherApp._client_speed_control_scope_bindings(self, scope)
        success_count = 0
        fail_count = 0
        skipped_count = 0
        for binding in bindings:
            reason = LauncherApp._client_speed_control_skip_reason(self, binding)
            if reason:
                skipped_count += 1
                self._log(f"[加速总控] 跳过 {binding.account_name or binding.account_id}：{reason}")
                continue
            try:
                apply_func = getattr(self, "_apply_client_speed_to_binding")
                apply_func(binding, rate)
                binding.speed_rate = float(rate)
                binding.window_status = "restored"
                success_count += 1
            except Exception as exc:
                fail_count += 1
                self._log(
                    f"[加速总控] 失败 {binding.account_name or binding.account_id}："
                    f"{mask_sensitive_text(exc)}"
                )
        if hasattr(self, "client_batch_store"):
            try:
                self.client_batch_store.save()
            except Exception:
                pass
        status_text = f"成功 {success_count} / 失败 {fail_count} / 跳过 {skipped_count}"
        status_var = getattr(self, "client_speed_control_status_var", None)
        if status_var is not None:
            try:
                status_var.set(status_text)
            except Exception:
                pass
        self._log(
            f"[加速总控] 目标{len(bindings)}，成功{success_count}，失败{fail_count}，跳过{skipped_count}。"
        )
        sync = getattr(self, "_sync_client_direct_batch_status", None)
        if callable(sync):
            sync()

    def _apply_client_speed_to_binding(self, binding: ClientBatchBinding, rate: float) -> None:
        port = int(binding.cdp_port or 0)
        targets = wait_for_cdp_targets(port, timeout=3.0)
        target = select_page_target(targets)
        cdp = RawCdpClient(str(target["webSocketDebuggerUrl"]))
        try:
            cdp.connect()
            cdp.enable_default_domains()
            apply_speed_rate_to_cdp(
                cdp,
                float(rate),
                ClientSpeedPanelConfig(**LauncherApp._client_speed_panel_options(self)),
                log=self._log,
            )
        finally:
            cdp.close()

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

    def _block_background_unsupported_action(self, action_name: str) -> bool:
        if not self._is_background_run_mode():
            return False
        if action_name in ("单账号运行", "当前层串行", "全部串行"):
            return False
        message = "后台模式当前支持方式一单账号、当前层串行、全部串行；方式二未接入"
        self._log(f"阻止{action_name}：{message}")
        messagebox.showwarning("后台模式限制", message)
        return True

    def _block_client_direct_unsupported_action(self, action_name: str) -> bool:
        if _run_mode_key_for_owner(self) != "client_direct":
            return False
        if action_name in ("单账号运行", "当前层串行", "全部串行"):
            return False
        message = "客户端直登模式当前仅支持方式一单账号、当前层串行和全部串行；方式二暂未接入"
        self._log(f"阻止{action_name}：{message}")
        messagebox.showwarning("客户端直登限制", message)
        return True

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
            for widget in self.wm_fixed_param_widgets:
                widget.grid()
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
        for widget in self.wm_fixed_param_widgets:
            widget.grid()

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
                    self.bookmark_root_display_name.set(candidate.display_name)
                    self.bookmark_root_name.set(candidate.display_name.split(" / ")[-1].replace("（直接链接）", ""))
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
        if self.bookmark_path.get() and Path(self.bookmark_path.get()).exists():
            self._refresh_bookmark_root_candidates(auto_select=True)
            self._load_accounts()
        else:
            current = self.bookmark_path.get().strip()
            if current:
                self._log(f"收藏夹路径不可读，未自动读取：{current}")
            else:
                self._log("未保存收藏夹路径，未自动读取。请手动选择 Bookmarks 文件后点击“读取收藏夹”。")

    def _load_accounts(self) -> None:
        try:
            settings = load_settings(self.settings_path.get())
            bookmark_file = self.bookmark_path.get() or settings.bookmark_file
            root_name = self.bookmark_root_name.get().strip() or settings.bookmark_root_name
            root_path = self.bookmark_root_path.get().strip() or settings.bookmark_root_path
            if not bookmark_file:
                raise ValueError(
                    "未配置收藏夹路径。程序不会自动切换到 Chrome/Edge 候选，"
                    f"请手动选择 Bookmarks 文件。候选：{self._bookmark_candidates_summary()}"
                )
            level_counts = self._current_level_counts()
            self._log(f"准备读取收藏夹：{bookmark_file}")
            root_candidate = self._selected_bookmark_root_candidate_for_load(bookmark_file, root_path)
            if root_candidate is not None:
                bookmark_file = root_candidate.bookmark_file
                root_path = root_candidate.root_path
                self.accounts = load_accounts_from_bookmark_root(
                    bookmark_file,
                    root_path,
                    settings.level_names,
                    level_counts=level_counts,
                    account_group_settings=settings.account_group_settings,
                    log=lambda message: self._log(f"收藏夹读取：{message}"),
                )
            elif self.bookmark_root_candidates:
                raise ValueError("请先在账号目录下拉框中选择当前收藏夹对应的账号目录。")
            else:
                self.accounts = load_accounts_from_bookmarks(
                    bookmark_file,
                    root_name,
                    settings.level_names,
                    level_counts=level_counts,
                    account_group_settings=settings.account_group_settings,
                    log=lambda message: self._log(f"收藏夹读取：{message}"),
                )
            self._save_bookmark_settings(bookmark_file)
            self.status_by_key = {account.key: "未开始" for account in self.accounts}
            self.passport_by_key = {account.key: "" for account in self.accounts}
            self.timing_by_key = {account.key: "" for account in self.accounts}
            self._refresh_mode_account_scope()
            self._log(f"已从收藏夹读取 {len(self.accounts)} 个账号链接。{self._account_count_summary()}")
        except Exception as exc:
            self._clear_loaded_accounts("读取收藏夹失败，账号列表已清空，请重新选择收藏夹和账号目录。")
            messagebox.showerror("读取收藏夹失败", str(exc))
            self._log(f"读取收藏夹失败: {exc}")
            bookmark_file = self.bookmark_path.get().strip()
            if bookmark_file:
                top_level = list_bookmark_top_level_dirs(bookmark_file)
                top_level_text = "，".join(top_level) if top_level else "未检测到一级目录"
                self._log(f"读取失败时的 Bookmarks 路径：{bookmark_file}")
                self._log(f"检测到的一级目录：{top_level_text}")

    def _current_level_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for level in LEVELS:
            counts[level] = int(self.level_count_vars[level].get())
        return counts

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
        if self.method_var.get() != "method1":
            messagebox.showinfo("分组设置", "全部串行分组设置仅用于方式一收藏夹账号。")
            return
        group_counts = self._account_group_counts(self.accounts)
        if not group_counts:
            messagebox.showwarning("无账号分组", "请先读取收藏夹，再设置全部串行分组。")
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

    # ===== 方式二：CSV 导入 =====

    def _on_method_changed(self) -> None:
        self._sync_account_source_controls()
        self._sync_work_mode_buttons()

    def _pick_csv_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择CSV文件",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
        )
        if path:
            self.csv_path.set(path)

    def _import_csv(self) -> None:
        path = self.csv_path.get().strip()
        if not path:
            messagebox.showwarning("提示", "请先选择CSV文件")
            return
        accounts, error = load_csv_accounts(path)
        if error:
            messagebox.showerror("导入失败", error)
            self._log(f"CSV导入失败: {error}")
            return
        self.csv_accounts = accounts
        self.csv_status_by_key = {a.key: a.status for a in accounts}
        self.csv_passport_by_key = {a.key: a.passport for a in accounts}
        self._refresh_csv_table()
        valid_count = sum(1 for a in accounts if "配置缺失" not in a.status)
        self._log(f"已从CSV导入 {len(accounts)} 个账号（有效 {valid_count} 个）。")
        # 记住CSV路径，下次启动自动加载
        self._save_csv_path_memory(path)

    def _save_csv_path_memory(self, path: str) -> None:
        """保存CSV路径到记忆文件，下次启动自动加载"""
        try:
            memory_file = Path(getattr(self, "user_data_dir", project_root())) / "csv_last_path.txt"
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            memory_file.write_text(path, encoding="utf-8")
        except Exception:
            pass

    def _auto_load_csv(self) -> None:
        """启动时自动加载上次导入的CSV"""
        try:
            memory_file = Path(getattr(self, "user_data_dir", project_root())) / "csv_last_path.txt"
            if not memory_file.exists():
                return
            path = memory_file.read_text(encoding="utf-8").strip()
            if not path or not Path(path).exists():
                return
            self.csv_path.set(path)
            # 直接调用导入（绕过路径空检查）
            accounts, error = load_csv_accounts(path)
            if error:
                self._log(f"自动加载CSV失败: {error}")
                return
            self.csv_accounts = accounts
            self.csv_status_by_key = {a.key: a.status for a in accounts}
            self.csv_passport_by_key = {a.key: a.passport for a in accounts}
            self._refresh_csv_table()
            valid_count = sum(1 for a in accounts if "配置缺失" not in a.status)
            self._log(f"已自动加载上次CSV: {len(accounts)} 个账号（有效 {valid_count} 个）")
        except Exception:
            pass

    def _refresh_csv_table(self) -> None:
        for item in self.csv_tree.get_children():
            self.csv_tree.delete(item)
        for acc in self.csv_accounts:
            pwd_display = "已填写" if acc.password else "未填写"
            self.csv_tree.insert(
                "",
                tk.END,
                iid=acc.key,
                values=(
                    acc.name,
                    acc.url,
                    acc.username,
                    pwd_display,
                    acc.game_window_no,
                    self.csv_passport_by_key.get(acc.key, acc.passport),
                    self.csv_status_by_key.get(acc.key, acc.status),
                    self.csv_timing_by_key.get(acc.key, ""),
                ),
            )

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
                    passport=self.passport_by_key.get(account.key, ""),
                    status=self.status_by_key.get(account.key, "未开始"),
                    timing=self.timing_by_key.get(account.key, ""),
                ),
            )

    def _refresh_account_choices(self) -> None:
        choices = [account.display_name for account in self._filtered_accounts_for_ui()]
        self.account_box["values"] = choices
        self.account_var.set(choices[0] if choices else "")

    def _run_selected(self) -> None:
        account = self._selected_account()
        if account is None:
            messagebox.showwarning("未选择账号", "请先读取配置并选择一个账号。")
            return
        if not self._validate_accounts_for_current_mode([account]):
            return
        self._start_run([account])

    def _run_selected_account(self) -> None:
        if self.method_var.get() == "method2":
            if LauncherApp._block_client_direct_unsupported_action(self, "方式二"):
                return
            if self._block_background_unsupported_action("方式二"):
                return
            self._run_method2_single()
            return
        account = self._selected_account()
        if account is None:
            messagebox.showwarning("未选择账号", "请先在表格或下拉框中选择一个账号。")
            return
        self._log(
            f"单账号运行前校验：排列方式={self.wm_tile_mode_var.get()}，"
            f"层级={self.level_var.get()}，账号={account.display_name}，窗口号={account.game_window_no}"
        )
        if _run_mode_key_from_label(self.run_mode_var.get()) == "client_direct":
            auto_text = "自动进入游戏" if LauncherApp._client_direct_auto_enter_game(self) else "不自动进入游戏"
            self._log(f"{RUN_MODE_CLIENT_DIRECT_LABEL}：启动方式一单账号客户端直登，{auto_text}。")
            self._start_client_direct_single_run(account)
            return
        if not self._precheck_serial_run([account], "单账号运行"):
            return
        if not self._validate_accounts_for_current_mode([account]):
            return
        self._log(
            f"单账号运行: {account.display_name}。"
            f"OCR → 打开游戏页 → 关闭公告 → 通行证 → 输入 → 确认。"
        )
        if _run_mode_key_from_label(self.run_mode_var.get()) == "background":
            self._log(
                f"{RUN_MODE_BACKGROUND_LABEL}：启动方式一单账号实验流程。"
            )
            self._start_background_single_run(account)
            return
        self._start_serial_run([account], batch_fast=False)

    def _run_level_serial(self) -> None:
        if self.method_var.get() == "method2":
            if LauncherApp._block_client_direct_unsupported_action(self, "方式二"):
                return
            if self._block_background_unsupported_action("方式二"):
                return
            messagebox.showinfo("提示", "方式二没有层级概念，请使用\"单账号运行\"或\"全部串行\"。")
            return
        if LauncherApp._block_client_direct_unsupported_action(self, "当前层串行"):
            return
        background_mode = _run_mode_key_for_owner(self) == "background"
        level = self.level_var.get()
        accounts = self._filtered_accounts_for_ui()
        if not accounts:
            if level == "全部":
                message = "当前没有勾选参与全部串行的账号。"
            else:
                message = f"当前层 {level} 没有账号。"
            self._log(f"阻止当前层串行：{message}")
            messagebox.showwarning("无账号", message)
            return
        if level == "全部":
            self._log("当前层串行范围确认：层级=全部，运行当前列表中已勾选参与全部串行的账号。")
        else:
            self._log(f"当前层串行范围确认：只运行当前层级【{level}】，不读取全部串行勾选状态。")
        if _run_mode_key_for_owner(self) == "client_direct":
            self._log(
                f"客户端当前层串行: {level}，共 {len(accounts)} 个账号，并发=1，"
                f"从 CDP 端口 {CLIENT_DIRECT_CDP_PORT} 开始逐个分配。"
            )
            self._start_client_direct_serial_run(accounts, run_label="客户端当前层串行")
            return
        if not self._precheck_serial_run(accounts, "当前层串行"):
            return
        if not self._validate_accounts_for_current_mode(accounts):
            return
        if background_mode:
            self._log(f"后台当前层串行: {level}，共 {len(accounts)} 个账号，并发={BACKGROUND_SERIAL_CONCURRENCY}，逐个调用后台单账号流程。")
            self._start_background_serial_run(accounts, run_label="后台当前层串行")
            return
        self._log(f"当前层串行: {level}，共 {len(accounts)} 个账号，批量快速登录 + 统一校验。")
        self._start_serial_run(accounts, batch_fast=True)

    def _run_all_serial(self) -> None:
        if self.method_var.get() == "method2":
            if LauncherApp._block_client_direct_unsupported_action(self, "方式二"):
                return
            if self._block_background_unsupported_action("方式二"):
                return
            self._run_method2_all()
            return
        if LauncherApp._block_client_direct_unsupported_action(self, "全部串行"):
            return
        run_mode_key = _run_mode_key_for_owner(self)
        background_mode = run_mode_key == "background"
        client_direct_mode = run_mode_key == "client_direct"
        selected_level = self.level_var.get()
        if not background_mode and selected_level != "全部":
            message = (
                f"当前层级是【{selected_level}】。\n"
                "“全部串行”将运行所有已启用分组，不是只运行当前层级。\n"
                f"如果只想运行【{selected_level}】，请点击“当前层串行”。\n"
                "如需运行全部启用分组，请先切换层级为“全部”。"
            )
            self._log(
                f"阻止全部串行：当前层级={selected_level}。"
                "全部串行只代表运行 include_in_all=true 的所有分组。"
            )
            messagebox.showwarning("全部串行范围确认", message)
            return
        all_accounts = self._mode_allowed_accounts()
        if not all_accounts:
            messagebox.showwarning("无账号", "请先读取收藏夹。")
            return
        accounts = [account for account in all_accounts if account.include_in_all] if background_mode else self._filtered_accounts_for_ui()
        skipped_accounts = [account for account in all_accounts if not account.include_in_all]
        if background_mode:
            self._log("后台全部串行范围确认：使用层级=全部的 include_in_all=true 过滤逻辑。")
        if client_direct_mode:
            self._log("客户端全部串行范围确认：使用层级=全部的 include_in_all=true 过滤逻辑。")
        if accounts:
            self._log("本次全部串行将执行：")
            for group_name, count in self._account_group_counts(accounts):
                self._log(f"{group_name} {count} 个")
        if skipped_accounts:
            self._log("本次全部串行将跳过：")
            for group_name, count in self._account_group_counts(skipped_accounts):
                self._log(f"{group_name} {count} 个")
        if not accounts:
            message = "未配置任何参与全部串行的分组，请先打开“全部串行分组设置”。"
            self._log(f"阻止全部串行：{message}")
            messagebox.showwarning("全部串行未配置", message)
            return
        invalid_accounts = [account for account in accounts if not account.include_in_all]
        if invalid_accounts:
            invalid_summary = self._account_count_summary(invalid_accounts)
            message = "检测到未启用分组混入全部串行，已阻止运行。"
            self._log(f"阻止全部串行：{message}{invalid_summary}")
            messagebox.showwarning("全部串行分组异常", message)
            return
        if client_direct_mode:
            self._log(
                f"客户端全部串行: 共 {len(accounts)} 个账号，并发=1，"
                f"从 CDP 端口 {CLIENT_DIRECT_CDP_PORT} 开始逐个分配。{self._account_count_summary(accounts)}"
            )
            self._start_client_direct_serial_run(accounts, run_label="客户端全部串行")
            return
        if not self._precheck_serial_run(accounts, "全部串行"):
            return
        if not self._validate_accounts_for_current_mode(accounts):
            return
        if background_mode:
            self._log(
                f"后台全部串行: 共 {len(accounts)} 个账号，并发={BACKGROUND_SERIAL_CONCURRENCY}，"
                f"逐个调用后台单账号流程。{self._account_count_summary(accounts)}"
            )
            self._start_background_serial_run(accounts, run_label="后台全部串行")
            return
        self._log(f"全部串行: 共 {len(accounts)} 个账号，批量快速登录 + 统一校验。{self._account_count_summary(accounts)}")
        self._start_serial_run(accounts, batch_fast=True)

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
        return accounts

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
        closed_statuses = {"pid_missing", "客户端已关闭", "closed", "已关闭"}
        cdp_statuses = {"cdp_unavailable", "CDP不可用"}
        hwnd_statuses = {"hwnd_invalid", "窗口已失效"}
        binding_invalid_statuses = {"pid_not_x5game", "binding_invalid", "cdp_owner_mismatch"}
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
            pid=int(binding.pid or 0),
            hwnd=int(binding.hwnd or 0),
            cdp_port=int(binding.cdp_port or 0),
            login_url=binding.login_url,
            status=binding.status,
            error_message=binding.error_message,
        )

    def _batch_binding_from_record(self, record: ClientDirectRunRecord) -> ClientBatchBinding:
        return ClientBatchBinding(
            account_id=record.account_id,
            account_name=record.account_name,
            pid=int(record.pid or 0),
            hwnd=int(record.hwnd or 0),
            cdp_port=int(record.cdp_port or 0),
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
        LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        return [
            LauncherApp._account_for_client_direct_record(self, record)
            for record in self.client_direct_bindings.values()
        ]

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
        successful = [
            account for account in accounts
            if account.key in self.client_direct_bindings
            and self.client_direct_bindings[account.key].status == "客户端已启动/待登录"
        ]
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
        arranged = LauncherApp._arrange_prepared_client_direct_current_scope(self, successful)
        if arranged is False:
            return
        LauncherApp._login_prepared_client_direct_current_scope(self, successful)

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

    def _login_prepared_client_direct_current_scope(self, accounts_override: list[AccountConfig] | None = None) -> None:
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
        auto_text = "自动进入游戏" if LauncherApp._client_direct_auto_enter_game(self) else "不自动进入游戏"
        concurrency = LauncherApp._client_direct_concurrency(self)
        self._log(f"[客户端直登] 登录范围={scope_label}，本次登录账号数={len(accounts)}。")
        self._log("[客户端直登] 登录账号：" + "、".join(str(getattr(account, "game_window_no", "") or account.display_name) for account in accounts))
        self._log(f"执行客户端登录：层级={level}，账号数={len(accounts)}，并发={concurrency}，{auto_text}。")
        self._start_client_direct_prepared_login_run(accounts, run_label="客户端当前层登录")

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
        return [
            account
            for account in accounts
            if str(getattr(records.get(account.key), "status", "") or "").strip() in CLIENT_DIRECT_LOGIN_PENDING_STATUSES
        ]

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

    def _client_direct_candidate_ports_for_local_scan(self, windows: list[GameWindow]) -> list[int]:
        ports: list[int] = []
        try:
            for batch in getattr(self.client_batch_store, "batches", []) or []:
                batch_ports = [int(binding.cdp_port or 0) for binding in batch.bindings if int(binding.cdp_port or 0) > 0]
                ports.extend(batch_ports)
                base_port = int(batch.base_port or (min(batch_ports) if batch_ports else CLIENT_DIRECT_CDP_PORT))
                count = max(len(getattr(batch, "bindings", []) or []), 9)
                ports.extend(base_port + offset for offset in range(count))
            if not ports:
                ports.extend(CLIENT_DIRECT_CDP_PORT + offset for offset in range(max(len(windows), 1)))
        except Exception:
            ports.extend(CLIENT_DIRECT_CDP_PORT + offset for offset in range(max(len(windows), 1)))
        return [port for port in dict.fromkeys(ports) if int(port or 0) > 0]

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

        candidate_ports = LauncherApp._client_direct_candidate_ports_for_local_scan(self, windows)
        available_targets: dict[int, dict[str, str]] = {}
        for port in candidate_ports:
            try:
                targets = wait_for_cdp_targets(int(port), timeout=0.8)
                target = select_page_target(targets)
                available_targets[int(port)] = {
                    "url": str(target.get("url") or ""),
                    "title": str(target.get("title") or ""),
                }
            except Exception:
                continue

        used_ports: set[int] = set()
        scans: list[LocalClientScan] = []
        for index, window in enumerate(windows):
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

            matched_port = 0
            cdp_port_inferred = False
            try:
                for batch in getattr(self.client_batch_store, "batches", []) or []:
                    for binding in batch.bindings:
                        port = int(binding.cdp_port or 0)
                        if port <= 0 or port in used_ports:
                            continue
                        if int(binding.pid or 0) == pid or int(binding.hwnd or 0) == hwnd:
                            matched_port = port
                            break
                    if matched_port > 0:
                        break
            except Exception:
                matched_port = 0
            if matched_port <= 0 and index < len(candidate_ports):
                matched_port = int(candidate_ports[index])
                cdp_port_inferred = True
            if matched_port in used_ports:
                matched_port = 0
                cdp_port_inferred = False
            if matched_port > 0:
                used_ports.add(matched_port)

            target_info = available_targets.get(matched_port, {})
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
                    cdp_available=matched_port in available_targets,
                    cdp_port_inferred=cdp_port_inferred,
                    page_url=str(target_info.get("url") or ""),
                    page_title=str(target_info.get("title") or ""),
                    is_x5game=is_x5game,
                )
            )
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
            binding.account_id: (binding.status, binding.error_message)
            for binding in batch.bindings
        }
        probe = RepairProbe(
            pid_exists=lambda pid: LauncherApp._client_direct_pid_exists(self, pid),
            process_is_x5game=lambda pid: LauncherApp._client_direct_process_is_x5game(self, pid),
            cdp_available=lambda port: LauncherApp._client_direct_cdp_available(self, port),
            hwnd_for_pid=lambda pid: wait_for_client_hwnd_by_pid(pid, timeout=0.5),
        )
        results = self.client_batch_store.repair_current_batch_windows(probe=probe)
        missing_bindings = [binding for binding in batch.bindings if binding.status == "pid_missing"]
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
        self._log(f"修复本批窗口完成：{len(results)} 个绑定。")

    def _client_direct_restore_repaired_business_statuses(
        self,
        batch,
        pre_repair_state: dict[str, tuple[str, str]],
        results: dict[str, str],
        reopened_ids: set[str],
    ) -> None:
        for binding in getattr(batch, "bindings", []) or []:
            account_id = str(binding.account_id)
            if account_id in reopened_ids:
                continue
            if results.get(account_id) != "repaired":
                continue
            old_status, old_error_message = pre_repair_state.get(account_id, ("", ""))
            if not old_status:
                continue
            binding.status = old_status
            binding.error_message = old_error_message

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
            if value == 0:
                return 0
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
        for binding in batch.bindings:
            binding.status = "closed"
        self.client_batch_store.save()
        LauncherApp._restore_client_direct_bindings_from_active_batch(self)
        LauncherApp._sync_client_direct_batch_status(self)

    # ===== 方式二运行 =====

    def _run_method2_single(self) -> None:
        """方式二：单账号运行（选中的CSV账号）"""
        if self._block_background_unsupported_action("方式二"):
            return
        if not self.csv_accounts:
            messagebox.showwarning("无账号", "请先导入CSV文件。")
            return
        acc = self._selected_csv_account()
        if acc is None:
            messagebox.showwarning("未选择账号", "请先在CSV表格中选择一个账号。")
            return
        if "配置缺失" in acc.status:
            messagebox.showwarning("配置缺失", f"账号 {acc.name} 配置不完整，无法执行。")
            return
        self._log(f"[方式二] 单账号运行: {acc.display_name}")
        self._start_method2_serial([acc])

    def _run_method2_all(self) -> None:
        """方式二：CSV列表全部串行"""
        if self._block_background_unsupported_action("方式二"):
            return
        valid = [a for a in self.csv_accounts if "配置缺失" not in a.status]
        if not valid:
            messagebox.showwarning("无有效账号", "CSV中没有有效的账号。")
            return
        self._log(f"[方式二] 全部串行: 共 {len(valid)} 个账号，批量快速登录 + 统一校验。")
        self._start_method2_serial(valid)

    def _selected_csv_account(self) -> CSVAccount | None:
        sel = self.csv_tree.selection()
        if not sel:
            return None
        key = sel[0]
        for a in self.csv_accounts:
            if a.key == key:
                return a
        return None

    def _start_method2_serial(self, accounts: list[CSVAccount]) -> None:
        """在后台线程执行方式二账号列表：快速提交 + 统一校验 + 失败重登。"""
        if self.worker_thread is not None and self.worker_thread.is_alive():
            messagebox.showwarning("任务进行中", "当前有任务正在执行。")
            return
        self._preserve_background_windows = False
        self._setup_log_file()
        self.stop_event.clear()
        self.csv_passport_by_key.clear()
        self.csv_timing_by_key.clear()
        for a in accounts:
            self.csv_status_by_key[a.key] = "未开始"
        self._refresh_csv_table()
        verify_rounds = self._batch_verify_rounds()

        def _run():
            import time as _time
            try:
                settings = load_settings(self.settings_path.get())
            except Exception as exc:
                self._queue_log(f"[方式二] 读取设置失败: {exc}")
                return
            from .config import AccountConfig as _AC
            import subprocess as _sp
            total = len(accounts)
            start_time = _time.time()
            self._queue_log("[方式二] 批量快速登录模式：先提交全部CSV账号，再统一校验，失败账号才重登。")
            self._queue_log(f"[方式二] 重新次数：{verify_rounds}。只要全部成功就提前结束。")
            self._queue_log(f"[方式二] 第一轮登录账号数量：{total}")

            pending = list(accounts)
            success_by_key: dict[str, CSVAccount] = {}
            final_failed: list[CSVAccount] = []

            def make_runner(acc: CSVAccount) -> AccountRunner:
                return AccountRunner(
                    account=_AC(level="方式二", bookmark_no=0, game_window_no=acc.game_window_no, url=acc.url),
                    settings=settings,
                    stop_event=self.stop_event,
                    log=self._queue_log,
                    update_status=lambda a, s, _acc=acc: self._queue_status_csv(_acc, s),
                    passport_found=lambda a, p, _acc=acc: self._queue_passport_csv(_acc, p),
                )

            for round_index in range(1, verify_rounds + 1):
                if self.stop_event.is_set():
                    break
                if round_index == 1:
                    self._queue_log(f"[方式二] 第 {round_index} 轮：批量快速提交 {len(pending)} 个账号。")
                else:
                    self._queue_log(f"[方式二] 第 {round_index} 轮：只重登失败账号 {len(pending)} 个。")

                submit_failed: list[CSVAccount] = []
                submitted: list[CSVAccount] = []
                already_logged_in: list[CSVAccount] = []

                for i, acc in enumerate(pending, start=1):
                    if self.stop_event.is_set():
                        break
                    status = "登录中" if round_index == 1 else "重登中"
                    self._queue_status_csv(acc, status)
                    self._queue_log(f"[方式二 第{round_index}轮 {i}/{len(pending)}] {status}: {acc.display_name}")

                    runner = make_runner(acc)
                    result = runner.run_method2(acc, verify_after_submit=False)
                    if runner.last_timings.get("总计"):
                        self._queue_timing_csv(acc, runner.last_timings["总计"])
                    if self.stop_event.is_set():
                        self._queue_status_csv(acc, "已停止")
                        self._queue_log("[方式二] 任务已停止，不会继续执行后续账号。")
                        _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)
                        break

                    submit_result = str(runner.last_fast_submit_result or "")
                    if submit_result == "already_logged_in":
                        already_logged_in.append(acc)
                        success_by_key[acc.key] = acc
                        self._queue_status_csv(acc, "已登录")
                        self._queue_log(f"[窗口{acc.game_window_no}] 已登录，跳过提交，直接计入成功。")
                    elif result and submit_result == "submitted":
                        submitted.append(acc)
                        self._queue_status_csv(acc, "待复核")
                        self._queue_log(f"[窗口{acc.game_window_no}] 方式二提交完成，等待统一校验。")
                    elif result:
                        submitted.append(acc)
                        self._queue_status_csv(acc, "待复核")
                        self._queue_log(
                            f"[窗口{acc.game_window_no}] 方式二提交结果缺少分类，按 submitted 加入待复核。"
                        )
                    else:
                        submit_failed.append(acc)
                        self._queue_status_csv(acc, "失败")
                        self._queue_log(f"[窗口{acc.game_window_no}] 方式二提交失败，加入重登列表。")
                    _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)

                if self.stop_event.is_set():
                    break

                failed_this_round = list(submit_failed)
                self._queue_log(
                    f"[方式二] 开始统一校验：submitted={len(submitted)}, "
                    f"already_logged_in={len(already_logged_in)}, failed={len(submit_failed)}"
                )

                verify_success_count = 0
                for i, acc in enumerate(submitted, start=1):
                    if self.stop_event.is_set():
                        break
                    self._queue_status_csv(acc, "校验中")
                    self._queue_log(f"[方式二 第{round_index}次校验 {i}/{len(submitted)}] 窗口{acc.game_window_no} {acc.display_name}")
                    runner = make_runner(acc)
                    state = runner.verify_login_result()
                    if state == "logged_in":
                        success_by_key[acc.key] = acc
                        verify_success_count += 1
                        self._queue_status_csv(acc, "成功")
                        self._queue_log(f"[窗口{acc.game_window_no}] 统一校验成功。")
                    else:
                        failed_this_round.append(acc)
                        self._queue_status_csv(acc, "失败")
                        self._queue_log(f"[窗口{acc.game_window_no}] 统一校验失败：{state}，需要重登。")

                if self.stop_event.is_set():
                    break

                self._queue_log(
                    f"[方式二] 第 {round_index} 轮统一校验完成："
                    f"成功{verify_success_count}，失败{len(failed_this_round)}，"
                    f"已登录跳过{len(already_logged_in)}。"
                )
                if failed_this_round:
                    self._queue_log("[方式二] 失败账号列表：" + "、".join(a.display_name for a in failed_this_round))
                if len(success_by_key) >= total:
                    final_failed = []
                    self._queue_log("[方式二] 全部成功，提前结束，不再执行后续校验。")
                    break
                if round_index >= verify_rounds:
                    final_failed = failed_this_round
                    for acc in final_failed:
                        self._queue_status_csv(acc, "最终失败")
                    self._queue_log("[方式二] 达到重新次数仍失败，最终失败账号列表：" + "、".join(a.display_name for a in final_failed))
                    break
                pending = failed_this_round
                self._queue_log(f"[方式二] 开始下一轮失败重登：{len(pending)} 个账号。")

            elapsed = _time.time() - start_time
            if self.stop_event.is_set():
                self.ui_queue.put(("status_bar", "已停止"))
                self._queue_log(f"[方式二] 任务已停止：总{total} 成功{len(success_by_key)} 失败{len(final_failed)} 耗时{elapsed:.0f}秒")
                self._write_file_log(f"任务已停止：总{total} 成功{len(success_by_key)} 失败{len(final_failed)} 耗时{elapsed:.0f}秒")
            else:
                self.ui_queue.put(("status_bar", f"任务完成：成功{len(success_by_key)}，失败{len(final_failed)}"))
                self._queue_log(f"[方式二] 任务完成：总{total} 成功{len(success_by_key)} 失败{len(final_failed)} 耗时{elapsed:.0f}秒")
                self._write_file_log(f"任务完成：总{total} 成功{len(success_by_key)} 失败{len(final_failed)} 耗时{elapsed:.0f}秒")
            self.worker_thread = None
            if self._log_file:
                self._log_file.close()
                self._log_file = None

        self.worker_thread = threading.Thread(target=_run, daemon=True)
        self.worker_thread.start()

    def _queue_status_csv(self, account: CSVAccount, status: str) -> None:
        self.csv_status_by_key[account.key] = status
        self.ui_queue.put(("csv_status", (account, status)))

    def _set_csv_status(self, account: CSVAccount, status: str) -> None:
        self.csv_status_by_key[account.key] = status
        if self.csv_tree.exists(account.key):
            values = list(self.csv_tree.item(account.key, "values"))
            values[6] = status
            tag = ""
            if "成功" in status:
                tag = "success"
            elif "已登录" in status or "跳过" in status:
                tag = "skip"
            elif "失败" in status:
                tag = "failed"
            elif "重登" in status or "重试" in status:
                tag = "retry"
            elif status not in ("未开始",):
                tag = "running"
            self.csv_tree.item(account.key, values=values, tags=(tag,))

    def _queue_passport_csv(self, account: CSVAccount, passport: str) -> None:
        self.csv_passport_by_key[account.key] = passport
        self.ui_queue.put(("csv_passport", (account, passport)))

    def _set_csv_passport(self, account: CSVAccount, passport: str) -> None:
        self.csv_passport_by_key[account.key] = passport
        if self.csv_tree.exists(account.key):
            values = list(self.csv_tree.item(account.key, "values"))
            values[5] = passport
            self.csv_tree.item(account.key, values=values)

    def _queue_timing_csv(self, account: CSVAccount, seconds: float) -> None:
        self.csv_timing_by_key[account.key] = f"{seconds:.1f}s"
        self.ui_queue.put(("csv_timing", (account, f"{seconds:.1f}s")))

    def _set_csv_timing(self, account: CSVAccount, timing: str) -> None:
        self.csv_timing_by_key[account.key] = timing
        if self.csv_tree.exists(account.key):
            values = list(self.csv_tree.item(account.key, "values"))
            values[7] = timing
            self.csv_tree.item(account.key, values=values)

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

    def _log_background_capability_summary(self) -> None:
        report = build_background_capability_report()
        self._log(report.frontend_summary)
        try:
            report_path = write_background_capability_report()
            self._log(f"后台能力详细报告：{report_path}")
        except Exception as exc:
            self._log(f"后台能力详细报告写入失败：{exc}")

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

    def _start_serial_run(self, accounts: list[AccountConfig], batch_fast: bool = False) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return
        self._preserve_background_windows = False
        try:
            settings = load_settings(self.settings_path.get())
        except Exception as exc:
            messagebox.showerror("读取自动化设置失败", str(exc))
            return
        settings = self._settings_with_notice_ratio(settings)

        self.stop_event.clear()
        for account in accounts:
            self._set_status(account, "未开始")
        verify_rounds = self._batch_verify_rounds()
        self.worker_thread = threading.Thread(
            target=self._serial_worker,
            args=(accounts, settings, batch_fast, verify_rounds),
            daemon=True,
        )
        self.worker_thread.start()

    def _start_background_single_run(self, account: AccountConfig) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return
        dependency_check = check_background_runtime_dependencies()
        if not dependency_check.ok:
            modules = "、".join(dependency_check.missing_modules)
            commands = "\n".join(dependency_check.install_commands)
            message = f"当前 Python 环境缺少依赖：{modules}\n请执行：{commands}"
            self._setup_log_file(cleanup_old=False)
            self._set_status(account, "依赖缺失")
            self._log("后台模式依赖预检失败。")
            self._log(f"当前 Python 路径={dependency_check.python_executable}")
            self._log(f"Python 位数={dependency_check.python_bits}")
            self._log(f"缺失模块={modules}")
            self._log(f"建议安装命令={commands}")
            messagebox.showwarning("后台模式依赖缺失", message)
            return
        try:
            settings = load_settings(self.settings_path.get())
        except Exception as exc:
            messagebox.showerror("读取自动化设置失败", str(exc))
            return
        settings = self._settings_with_notice_ratio(settings)

        self._setup_log_file(cleanup_old=False)
        self.stop_event.clear()
        self._preserve_background_windows = True
        self._set_status(account, "等待中")
        self.worker_thread = threading.Thread(
            target=self._background_single_worker,
            args=(account, settings),
            daemon=True,
        )
        self.worker_thread.start()

    def _start_client_direct_single_run(self, account: AccountConfig) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return
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

    def _start_client_direct_prepared_login_run(self, accounts: list[AccountConfig], *, run_label: str) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return
        missing = [account for account in accounts if account.key not in self.client_direct_bindings]
        if missing:
            message = "当前层存在未准备的客户端，请先点击“准备客户端”。"
            self._log(f"阻止执行客户端登录：{message}")
            messagebox.showwarning("执行客户端登录", message)
            return

        self._setup_log_file(cleanup_old=False)
        self.stop_event.clear()
        self._preserve_background_windows = True
        auto_enter_game = self._client_direct_auto_enter_game()
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
                    self._log(f"排列本批客户端：重命名成功 account={account.key} hwnd={record.hwnd} title={new_title}")
                else:
                    self._log(f"排列本批客户端：account={account.key} hwnd={record.hwnd} rename_failed reason=SetWindowTextW failed")
            except Exception as exc:
                reason = mask_sensitive_text(str(exc))
                self._log(f"排列本批客户端：account={account.key} hwnd={record.hwnd} rename_failed reason={reason}")

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
            if not LauncherApp._client_direct_is_window_alive(self, int(record.hwnd or 0)):
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
        log,
    ):
        if tile_mode == WM_TILE_MODE_ROW_COUNT:
            plan = calculate_row_tile_plan(len(windows), tile_config)
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
                title_template=_safe_wm_title_template(self),
            )
        return tile_game_windows(
            tile_config,
            windows=windows,
            title_template=_safe_wm_title_template(self),
        )

    def _start_background_serial_run(self, accounts: list[AccountConfig], *, run_label: str) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("任务运行中", "已有任务正在运行，请先停止或等待完成。")
            return
        dependency_check = check_background_runtime_dependencies()
        if not dependency_check.ok:
            modules = "、".join(dependency_check.missing_modules)
            commands = "\n".join(dependency_check.install_commands)
            message = f"当前 Python 环境缺少依赖：{modules}\n请执行：{commands}"
            self._setup_log_file(cleanup_old=False)
            for account in accounts:
                self._set_status(account, "依赖缺失")
            self._log("后台串行依赖预检失败。")
            self._log(f"当前 Python 路径={dependency_check.python_executable}")
            self._log(f"Python 位数={dependency_check.python_bits}")
            self._log(f"缺失模块={modules}")
            self._log(f"建议安装命令={commands}")
            messagebox.showwarning("后台模式依赖缺失", message)
            return
        try:
            settings = load_settings(self.settings_path.get())
        except Exception as exc:
            messagebox.showerror("读取自动化设置失败", str(exc))
            return
        settings = self._settings_with_notice_ratio(settings)

        self._setup_log_file(cleanup_old=False)
        self.stop_event.clear()
        self._preserve_background_windows = True
        for account in accounts:
            self._set_status(account, "等待中")
        self.worker_thread = threading.Thread(
            target=self._background_serial_worker,
            args=(list(accounts), settings, run_label),
            daemon=True,
        )
        self.worker_thread.start()

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
        self.client_direct_bindings[account.key] = ClientDirectRunRecord(
            account_id=account.key,
            account_name=account.display_name,
            pid=int(getattr(binding, "pid", 0) or 0),
            hwnd=int(getattr(binding, "hwnd", 0) or 0),
            cdp_port=int(getattr(binding, "cdp_port", port) or port),
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

            if result.success:
                LauncherApp._update_client_direct_binding_from_result(self, account, result, port=port, status="客户端已启动/待登录")
                binding = self.client_direct_bindings[account.key]
                self._queue_status(account, "客户端已启动/待登录")
                self._queue_log(
                    f"[客户端直登][{index + 1}/{total}] 客户端已启动/待登录："
                    f"pid={binding.pid} hwnd={binding.hwnd} port={binding.cdp_port}"
                )
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "success"
            reason = mask_sensitive_text(getattr(result, "message", "") or "未知错误")
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
            if not LauncherApp._client_direct_is_window_alive(self, int(record.hwnd or 0)):
                record.status = "客户端已关闭"
                record.error_message = "客户端窗口已关闭"
                self.client_direct_bindings[account.key] = record
                self._queue_status(account, "客户端已关闭")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 客户端已关闭：{account.display_name} hwnd={record.hwnd}")
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
                record.status = "客户端直登失败"
                record.error_message = "URL 不是完整客户端直登 URL"
                self._queue_status(account, "客户端直登失败")
                self._queue_log(f"[客户端直登][{index + 1}/{total}] 客户端直登失败：URL 不是完整客户端直登 URL")
                LauncherApp._save_client_direct_bindings_to_active_batch_threadsafe(self, sync_ui=False)
                return "failed"

            result = execute_prepared_client_direct_login(
                PreparedClientDirectLoginConfig(
                    account_id=record.account_id,
                    account_name=record.account_name,
                    full_login_url=record.login_url,
                    cdp_port=port,
                    auto_enter_game=bool(auto_enter_game),
                    timeout=60.0,
                    **LauncherApp._client_speed_panel_options(self),
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

    def _background_single_worker(self, account: AccountConfig, settings) -> None:
        import time as _time

        start_time = _time.time()
        self._queue_log(f"{RUN_MODE_BACKGROUND_LABEL}：方式一单账号实验，仅运行 {account.display_name}")
        self._queue_log("后台实验流程不调用 SetForegroundWindow，不使用全局鼠标/键盘。")
        self._update_status_bar("后台模式运行中：1/1")
        runner = BackgroundSingleAccountRunner(
            account,
            settings,
            self.stop_event,
            log=self._queue_log,
            update_status=self._queue_status,
            passport_found=self._queue_passport,
        )
        result = runner.run()
        elapsed = _time.time() - start_time
        self._queue_timing(account, elapsed)
        result_status = str(getattr(result, "status", "") or "")
        result_success = bool(getattr(result, "success", bool(result)) and getattr(result, "final_verified", bool(result)))
        if self.stop_event.is_set() or result_status == "stopped":
            self._update_status_bar("已停止")
        elif result_success:
            self._queue_log(f"[后台模式] 成功: {account.display_name}")
            self._update_status_bar("后台模式完成：成功1，失败0")
        elif result_status == "skipped_logged_in":
            self._queue_log(f"[后台模式] 已进入游戏，跳过: {account.display_name}")
            self._update_status_bar("后台模式完成：成功0，跳过1，失败0")
        else:
            self._queue_log(f"[后台模式] 失败: {account.display_name}")
            self._update_status_bar("后台模式完成：成功0，失败1")
        release_background_playwright_for_current_thread()

    def _background_serial_worker(self, accounts: list[AccountConfig], settings, run_label: str) -> None:
        import time as _time

        total = len(accounts)
        start_time = _time.time()
        success_count = 0
        skip_count = 0
        fail_count = 0
        stopped_count = 0
        stopped_keys: set[str] = set()
        latest_status: dict[str, str] = {}
        passport_by_key: dict[str, str] = {}

        def queue_status(account: AccountConfig, status: str) -> None:
            latest_status[account.key] = status
            self._queue_status(account, status)

        def mark_stopped(account: AccountConfig) -> None:
            nonlocal stopped_count
            if account.key in stopped_keys:
                return
            stopped_keys.add(account.key)
            stopped_count += 1
            if latest_status.get(account.key) != "已停止":
                latest_status[account.key] = "已停止"
                self._queue_status(account, "已停止")

        def passport_found(account: AccountConfig, passport: str) -> None:
            passport_by_key[account.key] = passport
            self._queue_passport(account, passport)

        self._queue_log(
            f"{run_label}开始：总{total}，并发={BACKGROUND_SERIAL_CONCURRENCY}，逐个调用 BackgroundSingleAccountRunner。"
        )
        self._queue_log("后台串行不前置窗口，不使用全局鼠标/键盘。")
        self._update_status_bar(f"{run_label}运行中：0/{total}")

        for index, account in enumerate(accounts, start=1):
            if self.stop_event.is_set():
                for remaining in accounts[index - 1 :]:
                    mark_stopped(remaining)
                break

            self._queue_log(f"[后台串行][{index}/{total}] 窗口{account.game_window_no}：开始")
            self._update_status_bar(f"{run_label}运行中：{index}/{total}")
            account_started = _time.time()
            runner = BackgroundSingleAccountRunner(
                account,
                settings,
                self.stop_event,
                log=self._queue_log_file,
                update_status=queue_status,
                passport_found=passport_found,
            )
            result = runner.run()
            elapsed = _time.time() - account_started
            self._queue_timing(account, elapsed)
            result_status = str(getattr(result, "status", "") or "")
            result_success = bool(getattr(result, "success", bool(result)) and getattr(result, "final_verified", bool(result)))

            if self.stop_event.is_set() or result_status == "stopped":
                mark_stopped(account)
                for remaining in accounts[index:]:
                    mark_stopped(remaining)
                break

            status = latest_status.get(account.key, "")
            passport = passport_by_key.get(account.key, "")
            if result_status == "skipped_logged_in" or status == "已进入游戏，跳过":
                skip_count += 1
                self._queue_log(f"[后台串行][{index}/{total}] 窗口{account.game_window_no}：已进入游戏，跳过")
            elif result_success:
                success_count += 1
                if passport:
                    self._queue_log(f"[后台串行][{index}/{total}] 窗口{account.game_window_no}：识别通行证 {passport}")
                self._queue_log(f"[后台串行][{index}/{total}] 窗口{account.game_window_no}：成功")
            else:
                fail_count += 1
                if latest_status.get(account.key) != "失败":
                    queue_status(account, "失败")
                self._queue_log(f"[后台串行][{index}/{total}] 窗口{account.game_window_no}：失败")

        elapsed_total = _time.time() - start_time
        if self.stop_event.is_set() or stopped_count:
            self._queue_log("后台串行已停止。")
            summary = (
                f"{run_label}已停止：成功{success_count}，跳过{skip_count}，失败{fail_count}，"
                f"已停止{stopped_count}，总耗时{elapsed_total:.0f}秒"
            )
            self._update_status_bar("已停止")
        else:
            summary = (
                f"{run_label}完成：成功{success_count}，跳过{skip_count}，失败{fail_count}，"
                f"已停止{stopped_count}，总耗时{elapsed_total:.0f}秒"
            )
            self._update_status_bar(f"{run_label}完成：成功{success_count}，跳过{skip_count}，失败{fail_count}")
        self._queue_log(summary)
        self._write_file_log(summary)
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        release_background_playwright_for_current_thread()
        if hasattr(self, "worker_thread"):
            self.worker_thread = None

    def _serial_worker(self, accounts: list[AccountConfig], settings, batch_fast: bool = False, verify_rounds: int = 3) -> None:
        self._setup_log_file()
        self._queue_log(f"前台串行模式：共 {len(accounts)} 个账号，严格逐个执行。")
        self._queue_log(f"当前版本：v{APP_VERSION}")
        self._queue_log("注意：运行期间会短暂移动鼠标，请勿操作。")
        import subprocess as _sp, json, tempfile, os, sys as _sys, time as _time

        frozen = getattr(_sys, "frozen", False)
        success_count = 0
        fail_count = 0
        start_time = _time.time()
        self._update_status_bar(f"运行中：{len(accounts)} 账号")

        if batch_fast:
            self._serial_worker_batch_fast(accounts, settings, frozen, verify_rounds, start_time)
            return

        for i, account in enumerate(accounts, start=1):
            if self.stop_event.is_set():
                self._queue_log("任务已停止。")
                self._update_status_bar("已停止")
                break
            self._queue_log(f"[{i}/{len(accounts)}] {account.display_name}")
            self._update_status_bar(f"运行中：{i}/{len(accounts)}")

            if frozen:
                # exe 模式也使用子进程隔离，和源码模式保持一致，避免 Playwright/COM 状态留在 GUI 进程。
                result = self._run_account_child_process(account, "full")
                flow_result = bool(result.get("result"))
                if self.stop_event.is_set():
                    self._queue_status(account, "已停止")
                    self._queue_log("任务已停止，不会继续执行后续账号。")
                    _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)
                    break
                elif flow_result:
                    success_count += 1
                    self._queue_log(f"[{i}/{len(accounts)}] 成功: {account.display_name}")
                else:
                    fail_count += 1
                    self._queue_log(f"[{i}/{len(accounts)}] 失败: {account.display_name}")
                _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)
            else:
                # === 源码模式：子进程隔离 Playwright asyncio ===
                cfg = {
                    "level": account.level, "bookmark_no": account.bookmark_no,
                    "game_window_no": account.game_window_no, "url": account.url,
                    "settings_path": str(self.settings_path.get() or default_settings_path()),
                }
                cfg_file = Path(tempfile.gettempdir()) / f"douluo_acc_{account.game_window_no}.json"
                cfg_file.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

                project_root = str(app_root())
                proc = _sp.Popen(
                    ["python", "-X", "utf8", "-c", f"""
import sys, json, threading
sys.path.insert(0, r"{project_root}")
from douluo_launcher.automation import AccountRunner
from douluo_launcher.config import AccountConfig, load_settings
from pathlib import Path

cfg = json.loads(Path(r"{cfg_file}").read_text(encoding='utf-8'))
settings = load_settings(Path(cfg["settings_path"]))
account = AccountConfig(
    level=cfg["level"], bookmark_no=cfg["bookmark_no"],
    game_window_no=cfg["game_window_no"], url=cfg["url"]
)
stop = threading.Event()
def log(msg):
    try:
        print("[W" + str(cfg["game_window_no"]) + "] " + str(msg), flush=True)
    except Exception:
        pass

def status(acct, s):
    try:
        print("STATUS:" + str(s), flush=True)
    except Exception:
        pass

def passport_found(acct, p):
    try:
        print("PASSPORT:" + str(p), flush=True)
    except Exception:
        pass

runner = AccountRunner(account, settings, stop, log, status, passport_found=passport_found)
flow_result = runner.run_game_flow()
print("RESULT:" + str(flow_result), flush=True)
print("TIMING:" + str(runner.last_timings.get("总计", 0)), flush=True)
"""],
                    stdout=_sp.PIPE, stderr=_sp.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    cwd=project_root,
                    creationflags=_sp.CREATE_NO_WINDOW,
                )
                self._track_process(proc)
                result_seen = False
                try:
                    for line in proc.stdout:
                        if self.stop_event.is_set():
                            if proc.poll() is None:
                                proc.terminate()
                            self._queue_log(f"[{account.display_name}] 已停止，当前账号子进程正在终止。")
                            break
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("PASSPORT:"):
                            self._queue_passport(account, line[9:])
                            self._write_file_log(line)
                        elif line.startswith("TIMING:"):
                            try:
                                self._queue_timing(account, float(line[7:]))
                            except ValueError:
                                pass
                            self._write_file_log(line)
                        elif line.startswith("STATUS:"):
                            self._queue_status(account, line[7:])
                            self._queue_log(f"[{account.display_name}] → {line[7:]}")
                            self._write_file_log(line)
                        elif line.startswith("RESULT:True"):
                            result_seen = True
                            self._write_file_log(line)
                        elif line.startswith("RESULT:"):
                            self._write_file_log(line)
                        else:
                            self._write_file_log(line)
                    if self.stop_event.is_set() and proc.poll() is None:
                        proc.terminate()
                    try:
                        proc.wait(timeout=3 if self.stop_event.is_set() else 300)
                    except Exception:
                        proc.kill()
                        try:
                            proc.wait(timeout=3)
                        except Exception:
                            pass
                        self._queue_log(f"[{account.display_name}] 已强制 kill 账号运行子进程 pid={proc.pid}。")
                finally:
                    self._untrack_process(proc)

                stderr_output = proc.stderr.read()
                for line in stderr_output.splitlines():
                    line = line.strip()
                    if line:
                        self._write_file_log(f"[stderr] {line[:500]}")

                if self.stop_event.is_set():
                    self._queue_status(account, "已停止")
                    self._queue_log("任务已停止，不会继续执行后续账号。")
                    try: cfg_file.unlink()
                    except Exception: pass
                    break
                elif result_seen:
                    success_count += 1
                    self._queue_log(f"[{i}/{len(accounts)}] 成功: {account.display_name}")
                else:
                    fail_count += 1
                    self._queue_log(f"[{i}/{len(accounts)}] 失败: {account.display_name}")

                try: cfg_file.unlink()
                except Exception: pass
                _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)

        elapsed = _time.time() - start_time
        log_path = str(self._log_file_path) if self._log_file_path else ""
        if self.stop_event.is_set():
            self._queue_log("--------- 任务已停止 ---------")
            self._queue_log(f"总账号: {len(accounts)}  成功: {success_count}  失败: {fail_count}  耗时: {elapsed:.0f}秒")
            self._update_status_bar("已停止")
        else:
            self._queue_log("--------- 任务完成 ---------")
            self._queue_log(f"总账号: {len(accounts)}  成功: {success_count}  失败: {fail_count}  耗时: {elapsed:.0f}秒")
            self._update_status_bar(f"任务完成：成功{success_count}，失败{fail_count}")
        self._queue_log(f"详细日志: {log_path}")
        if self._log_file is not None:
            summary_label = "任务已停止" if self.stop_event.is_set() else "任务完成"
            self._write_file_log(f"{summary_label}：总{len(accounts)} 成功{success_count} 失败{fail_count} 耗时{elapsed:.0f}秒")
            self._log_file.close()
            self._log_file = None

    def _run_account_child_process(self, account: AccountConfig, action: str) -> dict[str, object]:
        import subprocess as _sp, json, tempfile, sys as _sys

        if getattr(_sys, "frozen", False):
            temp_dir = Path(tempfile.gettempdir())
            stem = f"douluo_acc_{account.game_window_no}_{action}_{int(time.time() * 1000)}"
            cfg_file = temp_dir / f"{stem}.json"
            event_file = temp_dir / f"{stem}.events.jsonl"
            result_file = temp_dir / f"{stem}.result.json"
            cfg = {
                "level": account.level,
                "bookmark_no": account.bookmark_no,
                "game_window_no": account.game_window_no,
                "url": account.url,
                "settings_path": str(self.settings_path.get() or default_settings_path()),
                "action": action,
                "event_path": str(event_file),
                "result_path": str(result_file),
            }
            cfg_file.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            proc = _sp.Popen(
                [_sys.executable, "--run-account-action", str(cfg_file)],
                cwd=str(app_root()),
                creationflags=_sp.CREATE_NO_WINDOW,
            )
            self._track_process(proc)
            timing = 0.0
            verify_state = ""
            submit_result = ""
            event_offset = 0

            def drain_events() -> None:
                nonlocal event_offset, timing, verify_state, submit_result
                if not event_file.exists():
                    return
                with event_file.open("r", encoding="utf-8", errors="replace") as file:
                    file.seek(event_offset)
                    for raw_line in file:
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except Exception:
                            self._write_file_log(line)
                            continue
                        kind = event.get("type")
                        value = str(event.get("value", ""))
                        if kind == "log":
                            self._queue_log(value)
                            self._write_file_log(value)
                        elif kind == "status":
                            self._queue_status(account, value)
                            self._queue_log(f"[{account.display_name}] → {value}")
                            self._write_file_log(f"STATUS:{value}")
                        elif kind == "passport":
                            self._queue_passport(account, value)
                            self._write_file_log(f"PASSPORT:{value}")
                        elif kind == "timing":
                            try:
                                timing = float(value)
                                self._queue_timing(account, timing)
                            except ValueError:
                                pass
                            self._write_file_log(f"TIMING:{value}")
                        elif kind == "verify":
                            verify_state = value
                            self._write_file_log(f"VERIFY:{value}")
                        elif kind == "submit_result":
                            submit_result = value
                            self._write_file_log(f"SUBMIT_RESULT:{value}")
                    event_offset = file.tell()

            try:
                while proc.poll() is None:
                    if self.stop_event.is_set():
                        proc.terminate()
                        self._queue_log(f"[{account.display_name}] 已停止，当前账号 exe 子进程正在终止。")
                        break
                    drain_events()
                    time.sleep(0.1)
                drain_events()
                try:
                    proc.wait(timeout=3 if self.stop_event.is_set() else 30)
                except Exception:
                    proc.kill()
                    try:
                        proc.wait(timeout=3)
                    except Exception:
                        pass
                    self._queue_log(f"[{account.display_name}] 已强制 kill 账号 exe 子进程 pid={proc.pid}。")
            finally:
                self._untrack_process(proc)

            result_data: dict[str, object] = {
                "result": False,
                "verify_state": verify_state,
                "submit_result": submit_result,
                "timing": timing,
            }
            if result_file.exists():
                try:
                    loaded = json.loads(result_file.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        result_data.update(loaded)
                except Exception as exc:
                    self._write_file_log(f"[exe-child-result-error] {exc}")
            if result_data.get("timing"):
                try:
                    self._queue_timing(account, float(result_data["timing"]))
                except Exception:
                    pass
            for path in (cfg_file, event_file, result_file):
                try:
                    path.unlink()
                except Exception:
                    pass
            return result_data

        cfg = {
            "level": account.level,
            "bookmark_no": account.bookmark_no,
            "game_window_no": account.game_window_no,
            "url": account.url,
            "settings_path": str(self.settings_path.get() or default_settings_path()),
            "action": action,
        }
        cfg_file = Path(tempfile.gettempdir()) / f"douluo_acc_{account.game_window_no}_{action}.json"
        cfg_file.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

        project_root = str(app_root())
        proc = _sp.Popen(
            ["python", "-X", "utf8", "-c", f"""
import sys, json, threading
sys.path.insert(0, r"{project_root}")
from douluo_launcher.automation import AccountRunner
from douluo_launcher.config import AccountConfig, load_settings
from pathlib import Path

cfg = json.loads(Path(r"{cfg_file}").read_text(encoding='utf-8'))
settings = load_settings(Path(cfg["settings_path"]))
account = AccountConfig(
    level=cfg["level"], bookmark_no=cfg["bookmark_no"],
    game_window_no=cfg["game_window_no"], url=cfg["url"]
)
stop = threading.Event()
def log(msg):
    try:
        print("[W" + str(cfg["game_window_no"]) + "] " + str(msg), flush=True)
    except Exception:
        pass

def status(acct, s):
    try:
        print("STATUS:" + str(s), flush=True)
    except Exception:
        pass

def passport_found(acct, p):
    try:
        print("PASSPORT:" + str(p), flush=True)
    except Exception:
        pass

runner = AccountRunner(account, settings, stop, log, status, passport_found=passport_found)
action = cfg.get("action", "full")
if action == "fast_submit":
    flow_result = runner.run_game_flow_fast_submit()
    print("SUBMIT_RESULT:" + str(runner.last_fast_submit_result), flush=True)
    print("RESULT:" + str(flow_result), flush=True)
    print("TIMING:" + str(runner.last_timings.get("总计", 0)), flush=True)
elif action == "verify":
    verify_state = runner.verify_login_result()
    print("VERIFY:" + str(verify_state), flush=True)
    print("RESULT:" + str(verify_state == "logged_in"), flush=True)
else:
    flow_result = runner.run_game_flow()
    print("RESULT:" + str(flow_result), flush=True)
    print("TIMING:" + str(runner.last_timings.get("总计", 0)), flush=True)
"""],
            stdout=_sp.PIPE, stderr=_sp.PIPE,
            text=True, encoding="utf-8", errors="replace",
            cwd=project_root,
            creationflags=_sp.CREATE_NO_WINDOW,
        )
        self._track_process(proc)
        result_seen = False
        verify_state = ""
        submit_result = ""
        timing = 0.0
        try:
            for line in proc.stdout:
                if self.stop_event.is_set():
                    if proc.poll() is None:
                        proc.terminate()
                    self._queue_log(f"[{account.display_name}] 已停止，当前账号子进程正在终止。")
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith("PASSPORT:"):
                    self._queue_passport(account, line[9:])
                    self._write_file_log(line)
                elif line.startswith("TIMING:"):
                    try:
                        timing = float(line[7:])
                        self._queue_timing(account, timing)
                    except ValueError:
                        pass
                    self._write_file_log(line)
                elif line.startswith("STATUS:"):
                    self._queue_status(account, line[7:])
                    self._queue_log(f"[{account.display_name}] → {line[7:]}")
                    self._write_file_log(line)
                elif line.startswith("VERIFY:"):
                    verify_state = line[7:]
                    self._write_file_log(line)
                elif line.startswith("SUBMIT_RESULT:"):
                    submit_result = line[14:]
                    self._write_file_log(line)
                elif line.startswith("RESULT:True"):
                    result_seen = True
                    self._write_file_log(line)
                elif line.startswith("RESULT:"):
                    self._write_file_log(line)
                else:
                    self._write_file_log(line)
            if self.stop_event.is_set() and proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=3 if self.stop_event.is_set() else 300)
            except Exception:
                proc.kill()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass
                self._queue_log(f"[{account.display_name}] 已强制 kill 账号运行子进程 pid={proc.pid}。")
        finally:
            self._untrack_process(proc)

        stderr_output = proc.stderr.read()
        for line in stderr_output.splitlines():
            line = line.strip()
            if line:
                self._write_file_log(f"[stderr] {line[:500]}")
        try:
            cfg_file.unlink()
        except Exception:
            pass

        return {
            "result": result_seen,
            "verify_state": verify_state,
            "submit_result": submit_result,
            "timing": timing,
        }

    def _run_account_action(self, account: AccountConfig, settings, action: str, frozen: bool) -> dict[str, object]:
        if frozen:
            return self._run_account_child_process(account, action)
        return self._run_account_child_process(account, action)

    def _serial_worker_batch_fast(self, accounts: list[AccountConfig], settings, frozen: bool, verify_rounds: int, start_time: float) -> None:
        import subprocess as _sp, time as _time

        self._queue_log("批量快速登录模式：先提交全部账号，再统一校验，失败账号才重登。")
        self._queue_log(f"重新次数：{verify_rounds}。只要全部成功就提前结束。")
        self._queue_log(f"第一轮登录账号数量：{len(accounts)}")

        pending = list(accounts)
        success_by_key: dict[str, AccountConfig] = {}
        final_failed: list[AccountConfig] = []

        for round_index in range(1, verify_rounds + 1):
            if self.stop_event.is_set():
                break
            if round_index == 1:
                self._queue_log(f"第 {round_index} 轮：批量快速登录 {len(pending)} 个账号。")
            else:
                self._queue_log(f"第 {round_index} 轮：只重登失败账号 {len(pending)} 个。")

            submit_failed: list[AccountConfig] = []
            submitted: list[AccountConfig] = []
            already_logged_in: list[AccountConfig] = []
            for i, account in enumerate(pending, start=1):
                if self.stop_event.is_set():
                    break
                self._queue_status(account, "登录中" if round_index == 1 else "重登中")
                self._queue_log(
                    f"[第{round_index}轮 {i}/{len(pending)}] "
                    f"{'登录中' if round_index == 1 else '重登中'}: {account.display_name}"
                )
                result = self._run_account_action(account, settings, "fast_submit", frozen)
                if self.stop_event.is_set():
                    self._queue_status(account, "已停止")
                    break
                submit_result = str(result.get("submit_result") or "")
                if submit_result == "already_logged_in":
                    already_logged_in.append(account)
                    success_by_key[account.key] = account
                    self._queue_status(account, "已登录")
                    self._queue_log(f"{account.display_name} 已登录，跳过提交，直接计入成功。")
                elif result.get("result") and submit_result == "submitted":
                    submitted.append(account)
                    self._queue_status(account, "待复核")
                    self._queue_log(f"{account.display_name} 已输入确认，加入待复核。")
                elif result.get("result"):
                    submitted.append(account)
                    self._queue_status(account, "待复核")
                    self._queue_log(
                        f"{account.display_name} 快速登录结果缺少分类，按 submitted 加入待复核。"
                    )
                else:
                    submit_failed.append(account)
                    self._queue_status(account, "失败")
                    self._queue_log(f"{account.display_name} 快速登录提交失败，加入重登列表。")
                _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)

            if self.stop_event.is_set():
                break

            verify_targets = submitted
            failed_this_round = list(submit_failed)
            self._queue_log(
                f"第 {round_index} 次统一校验开始：本轮总数 {len(pending)}，"
                f"已登录跳过 {len(already_logged_in)}，待复核 {len(verify_targets)}，"
                f"提交失败 {len(submit_failed)}。"
            )
            verify_success_count = 0
            for i, account in enumerate(verify_targets, start=1):
                if self.stop_event.is_set():
                    break
                self._queue_status(account, "校验中")
                self._queue_log(f"[第{round_index}次校验 {i}/{len(verify_targets)}] {account.display_name}")
                verify_result = self._run_account_action(account, settings, "verify", frozen)
                state = str(verify_result.get("verify_state") or "unknown")
                if state == "logged_in":
                    success_by_key[account.key] = account
                    verify_success_count += 1
                    self._queue_status(account, "成功")
                    self._queue_log(f"{account.display_name} 统一校验成功。")
                else:
                    failed_this_round.append(account)
                    self._queue_status(account, "失败")
                    self._queue_log(f"{account.display_name} 统一校验失败：{state}，需要重登。")

            if self.stop_event.is_set():
                break

            success_count = len(success_by_key)
            failed_count = len(failed_this_round)
            self._queue_log(
                f"第 {round_index} 次统一校验完成：总数 {len(pending)}，"
                f"已登录跳过 {len(already_logged_in)}，校验成功 {verify_success_count}，"
                f"失败 {failed_count}。"
            )
            if failed_this_round:
                self._queue_log("失败账号列表：" + "、".join(a.display_name for a in failed_this_round))
            if len(success_by_key) >= len(accounts):
                final_failed = []
                self._queue_log("全部成功，提前结束，不再执行后续校验。")
                break
            if round_index >= verify_rounds:
                final_failed = failed_this_round
                self._queue_log("达到重新次数仍失败，最终失败账号列表：" + "、".join(a.display_name for a in final_failed))
                break
            pending = failed_this_round
            self._queue_log(f"下一轮只重登失败账号数量：{len(pending)}")

        elapsed = _time.time() - start_time
        if self.stop_event.is_set():
            self._queue_log("--------- 任务已停止 ---------")
            self._update_status_bar("已停止")
        else:
            for account in final_failed:
                self._queue_status(account, "失败")
            self._queue_log("--------- 任务完成 ---------")
            self._update_status_bar(f"任务完成：成功{len(success_by_key)}，失败{len(final_failed)}")
        self._queue_log(f"总账号: {len(accounts)}  成功: {len(success_by_key)}  失败: {len(final_failed)}  耗时: {elapsed:.0f}秒")
        log_path = str(self._log_file_path) if self._log_file_path else ""
        self._queue_log(f"详细日志: {log_path}")
        if self._log_file is not None:
            summary_label = "任务已停止" if self.stop_event.is_set() else "任务完成"
            self._write_file_log(f"{summary_label}：总{len(accounts)} 成功{len(success_by_key)} 失败{len(final_failed)} 耗时{elapsed:.0f}秒")
            self._log_file.close()
            self._log_file = None

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

