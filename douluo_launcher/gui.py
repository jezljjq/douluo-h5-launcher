from __future__ import annotations

import queue
import json
import os
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None

from .automation import AccountRunner
from .background_capability import build_background_capability_report, write_background_capability_report
from .background_login import BackgroundSingleAccountRunner, check_background_runtime_dependencies
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
    describe_bookmark_file,
    find_bookmark_root_candidate_by_path,
    find_bookmark_file_candidates,
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
    WINDOW_DETECTION_LOG_PATH,
    RowTileConfig,
    TileConfig,
    calculate_row_tile_plan,
    check_window_slots_compatibility,
    close_game_windows,
    extract_window_number,
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
RUN_MODE_BACKGROUND_LABEL = "后台登录模式（实验）"
BACKGROUND_SERIAL_CONCURRENCY = 1
RUN_MODE_BACKGROUND_HINT = "实验功能，支持方式一单账号/当前层串行/全部串行，并发=1"
GUI_DEFAULT_WIDTH = 1160
GUI_DEFAULT_HEIGHT = 820
GUI_MIN_WIDTH = 1080
GUI_MIN_HEIGHT = 760
LOG_TEXT_VISIBLE_LINES = 8
LOG_PANEL_MIN_HEIGHT = 170


def _run_mode_key_from_label(label: str) -> str:
    if str(label or "").strip() == RUN_MODE_BACKGROUND_LABEL:
        return "background"
    return "foreground"


def _run_mode_key_for_owner(owner) -> str:
    var = getattr(owner, "run_mode_var", None)
    if var is None:
        return "foreground"
    try:
        return _run_mode_key_from_label(var.get())
    except Exception:
        return "foreground"


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
        account.url,
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
        self.title(f"上号器 — 前台串行模式 v{APP_VERSION}")
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
        self.is_closing = False

        self.settings_path = tk.StringVar(value=str(app_root() / "automation_settings.json"))
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
        self.run_mode_var = tk.StringVar(value=RUN_MODE_FOREGROUND_LABEL)
        self.run_mode_hint_var = tk.StringVar(value="")
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
        self._log_bookmark_startup_state()
        self._auto_load_csv()
        self.after(100, self._drain_ui_queue)
        self._load_default_config_if_present()
        self._log_admin_status_warning()
        self._log_startup_dm_environment()
        self._log_background_capability_summary()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._enable_game_path_drag_drop)

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
        root = ttk.Frame(self, padding=(12, 8, 12, 4))
        root.pack(fill=tk.BOTH, expand=True)

        # ===== 1. 窗口管理 =====
        window_frame = ttk.LabelFrame(root, text="窗口管理", padding=6)
        window_frame.pack(fill=tk.X, pady=(0, 8))
        window_frame.columnconfigure(1, weight=1)

        # 第1行：游戏路径
        ttk.Label(window_frame, text="游戏程序", width=10, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(4, 6), pady=3
        )
        self.wm_game_path_box = ttk.Frame(window_frame)
        self.wm_game_path_box.grid(
            row=0, column=1, columnspan=12, sticky="ew", padx=4, pady=3
        )
        self.wm_game_path_box.columnconfigure(0, weight=1)
        self.wm_game_path_entry = ttk.Entry(self.wm_game_path_box, textvariable=self.wm_game_path_var)
        self.wm_game_path_entry.grid(row=0, column=0, sticky="ew")
        self.wm_game_hint_label = ttk.Label(
            self.wm_game_path_box,
            textvariable=self.wm_game_hint_var,
            foreground="#006666",
        )
        self.wm_game_hint_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.wm_game_status_label = ttk.Label(
            self.wm_game_path_box,
            textvariable=self.wm_game_status_var,
            foreground="#666666",
        )
        self.wm_game_status_label.grid(row=2, column=0, sticky="w", pady=(2, 0))
        ttk.Button(window_frame, text="选择游戏图标/程序", width=16, command=self._pick_game_path).grid(
            row=0, column=13, sticky="ew", padx=4, pady=3
        )

        # 第2行：启动参数、自动编号、标题模板、重命名
        ttk.Label(window_frame, text="打开数量").grid(row=1, column=0, sticky="e", padx=(4, 6), pady=3)
        ttk.Spinbox(window_frame, from_=1, to=99, increment=1,
                    textvariable=self.wm_launch_count_var, width=6).grid(row=1, column=1, sticky="w", padx=(0, 12), pady=3)
        ttk.Label(window_frame, text="启动间隔(ms)").grid(row=1, column=2, sticky="e", padx=(0, 6), pady=3)
        ttk.Spinbox(window_frame, from_=0, to=60000, increment=100,
                    textvariable=self.wm_launch_interval_var, width=6).grid(row=1, column=3, sticky="w", padx=(0, 12), pady=3)
        ttk.Checkbutton(window_frame, text="启动后自动排列",
                        variable=self.wm_auto_tile_after_launch_var).grid(row=1, column=4, sticky="w", padx=(0, 12), pady=3)
        ttk.Checkbutton(window_frame, text="排列后自动编号标题",
                        variable=self.wm_auto_rename_after_tile_var).grid(row=1, column=5, sticky="w", padx=(0, 12), pady=3)
        ttk.Label(window_frame, text="标题模板").grid(row=1, column=6, sticky="e", padx=(0, 6), pady=3)
        ttk.Entry(window_frame, textvariable=self.wm_title_template_var, width=24).grid(
            row=1, column=7, columnspan=5, sticky="ew", padx=(0, 8), pady=3
        )
        ttk.Button(window_frame, text="重命名", width=8,
                   command=self._wm_rename_windows).grid(row=1, column=12, sticky="ew", padx=(0, 6), pady=3)

        # 第3行：排列方式和保护选项
        ttk.Label(window_frame, text="排列方式").grid(row=2, column=0, sticky="e", padx=(4, 6), pady=3)
        self.wm_tile_mode_combo = ttk.Combobox(
            window_frame,
            textvariable=self.wm_tile_mode_var,
            values=(WM_TILE_MODE_FIXED, WM_TILE_MODE_ROW_COUNT),
            state="readonly",
            width=14,
        )
        self.wm_tile_mode_combo.grid(row=2, column=1, columnspan=2, sticky="w", padx=(0, 12), pady=3)
        self.wm_tile_mode_combo.bind("<<ComboboxSelected>>", lambda _: self._wm_on_tile_mode_changed())
        ttk.Label(window_frame, text="根据行数排列会自动缩放窗口").grid(
            row=2, column=3, columnspan=2, sticky="w", padx=(0, 12), pady=3
        )
        ttk.Checkbutton(
            window_frame,
            text="禁止超出屏幕宽度",
            variable=self.wm_prevent_overflow_var,
        ).grid(row=2, column=5, columnspan=3, sticky="w", padx=(0, 12), pady=3)

        # 第4行：窗口尺寸和排列参数
        self.wm_fixed_param_widgets = []
        self.wm_row_param_widgets = []

        def add_widget(widget, row: int, column: int, **grid_options):
            widget.grid(row=row, column=column, **grid_options)
            return widget

        fixed_specs = (
            ("窗口宽度", "entry", self.wm_window_width_var, None, None),
            ("窗口高度", "entry", self.wm_window_height_var, None, None),
            ("每行数量", "spin", self.wm_per_row_var, 1, 99),
            ("起点X", "spin", self.wm_start_x_var, -5000, 5000),
            ("起点Y", "spin", self.wm_start_y_var, -5000, 5000),
            ("横向偏移", "spin", self.wm_offset_x_var, -5000, 5000),
            ("纵向偏移", "spin", self.wm_offset_y_var, -5000, 5000),
        )
        for index, (label, kind, variable, min_value, max_value) in enumerate(fixed_specs):
            label_column = index * 2
            input_column = label_column + 1
            label_widget = add_widget(
                ttk.Label(window_frame, text=label),
                3,
                label_column,
                sticky="e",
                padx=(4 if index == 0 else 8, 4),
                pady=3,
            )
            if kind == "entry":
                input_widget = add_widget(
                    ttk.Entry(window_frame, textvariable=variable, width=7),
                    3,
                    input_column,
                    sticky="w",
                    padx=(0, 4),
                    pady=3,
                )
            else:
                input_widget = add_widget(
                    ttk.Spinbox(window_frame, from_=min_value, to=max_value, increment=1,
                                textvariable=variable, width=6),
                    3,
                    input_column,
                    sticky="w",
                    padx=(0, 4),
                    pady=3,
                )
            self.wm_fixed_param_widgets.extend((label_widget, input_widget))

        row_label = add_widget(
            ttk.Label(window_frame, text="每行数量"),
            3,
            0,
            sticky="e",
            padx=(4, 4),
            pady=3,
        )
        row_input = add_widget(
            ttk.Spinbox(window_frame, from_=1, to=99, increment=1,
                        textvariable=self.wm_per_row_var, width=6),
            3,
            1,
            sticky="w",
            padx=(0, 4),
            pady=3,
        )
        self.wm_row_param_widgets.extend((row_label, row_input))

        # 第5行：窗口操作按钮
        window_action_row = ttk.Frame(window_frame)
        window_action_row.grid(row=4, column=0, columnspan=14, sticky="w", pady=(6, 0))
        self.wm_launch_btn = ttk.Button(window_action_row, text="批量启动窗口", width=18,
                                        command=self._wm_launch_windows)
        self.wm_launch_btn.pack(side=tk.LEFT, padx=(4, 10))
        self.wm_identify_btn = ttk.Button(window_action_row, text="识别窗口", width=18,
                                          command=self._wm_identify_windows)
        self.wm_identify_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.wm_tile_btn = ttk.Button(window_action_row, text="排列窗口", width=18,
                                      command=self._wm_tile_windows)
        self.wm_tile_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.wm_refresh_slots_btn = ttk.Button(window_action_row, text="刷新槽位映射", width=18,
                                               command=self._wm_refresh_window_slots)
        self.wm_refresh_slots_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.wm_regenerate_slots_btn = ttk.Button(window_action_row, text="重新生成槽位", width=18,
                                                  command=self._wm_regenerate_slots)
        self.wm_regenerate_slots_btn.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(window_action_row, text="目标槽位").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(window_action_row, from_=1, to=99, increment=1,
                    textvariable=self.wm_repair_slot_var, width=5).pack(side=tk.LEFT, padx=(0, 6))
        self.wm_repair_slot_btn = ttk.Button(window_action_row, text="修复窗口", width=12,
                                             command=self._wm_repair_window_slot)
        self.wm_repair_slot_btn.pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(window_action_row, text="关闭窗口", width=18, fg="#cc0000",
                  command=self._wm_close_windows, font=("", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))

        # ===== 2. 配置上号器 =====
        config_frame = ttk.LabelFrame(root, text="配置上号器", padding=6)
        config_frame.pack(fill=tk.X, pady=(0, 8))
        config_frame.columnconfigure(1, weight=1)

        method_row = ttk.Frame(config_frame)
        method_row.grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 6))
        ttk.Label(method_row, text="上号方式").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Radiobutton(method_row, text="方式一：通行证上号", variable=self.method_var, value="method1",
                        command=self._on_method_changed).pack(side=tk.LEFT, padx=(0, 24))
        ttk.Radiobutton(method_row, text="方式二：账号密码 + 通行证上号", variable=self.method_var, value="method2",
                        command=self._on_method_changed).pack(side=tk.LEFT)

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

        # ===== 3. 运行 =====
        run_frame = ttk.LabelFrame(root, text="运行", padding=6)
        run_frame.pack(fill=tk.X, pady=(0, 8))

        # 选择行
        select_row = ttk.Frame(run_frame)
        select_row.pack(fill=tk.X, pady=(0, 6))

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

        ttk.Label(select_row, text="模式").pack(side=tk.LEFT, padx=(0, 4))
        self.run_mode_box = ttk.Combobox(
            select_row,
            textvariable=self.run_mode_var,
            values=(RUN_MODE_FOREGROUND_LABEL, RUN_MODE_BACKGROUND_LABEL),
            width=18,
            state="readonly",
        )
        self.run_mode_box.pack(side=tk.LEFT, padx=(0, 6))
        self.run_mode_box.bind("<<ComboboxSelected>>", lambda _: self._on_run_mode_changed())
        ttk.Label(select_row, textvariable=self.run_mode_hint_var, foreground="#996600").pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(select_row, text="并发").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(select_row, text="1", relief="sunken", width=4, anchor="center", padding=2).pack(side=tk.LEFT)

        ttk.Label(select_row, text="重新次数").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Spinbox(select_row, from_=1, to=9, textvariable=self.batch_verify_rounds_var,
                    width=5).pack(side=tk.LEFT)

        # 操作行
        action_row = ttk.Frame(run_frame)
        action_row.pack(fill=tk.X)

        ttk.Button(action_row, text="单账号运行", width=14, command=self._run_selected_account).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_row, text="当前层串行", width=14, command=self._run_level_serial).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_row, text="全部串行", width=14, command=self._run_all_serial).pack(side=tk.LEFT, padx=2)
        self.stop_btn = tk.Button(action_row, text="停止任务", width=12, fg="#cc0000",
                                   command=self._stop_tasks, font=("", 9, "bold"))
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        # ===== 4. 账号列表 =====
        self._table_frame_m1 = ttk.LabelFrame(root, text="账号列表（方式一）", padding=2)
        self.tree = ttk.Treeview(self._table_frame_m1, columns=ACCOUNT_TABLE_COLUMNS, show="headings", height=7)
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
        self._table_frame_m2 = ttk.LabelFrame(root, text="CSV账号列表（方式二）", padding=2)
        csv_columns = ("name", "url", "username", "password_status", "window", "passport", "status", "timing")
        self.csv_tree = ttk.Treeview(self._table_frame_m2, columns=csv_columns, show="headings", height=7)
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
        self._table_frame_m1.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # ===== 5. 日志 =====
        self._log_outer = ttk.LabelFrame(root, text="日志", padding=2)
        self._log_outer.configure(height=LOG_PANEL_MIN_HEIGHT)
        self._log_outer.pack_propagate(False)
        self._log_outer.pack(fill=tk.X, pady=(0, 4))
        log_header = ttk.Frame(self._log_outer)
        log_header.pack(fill=tk.X, pady=(0, 2))
        ttk.Button(log_header, text="打开日志目录", command=self._open_log_dir).pack(side=tk.RIGHT, padx=2)

        self.log_text = tk.Text(self._log_outer, height=LOG_TEXT_VISIBLE_LINES, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ===== 6. 底部状态栏 =====
        status_frame = ttk.Frame(root, relief="sunken", padding=(8, 3))
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_left = tk.StringVar(value="就绪")
        self._status_mid = tk.StringVar(value=f"当前模式：{RUN_MODE_FOREGROUND_LABEL}")
        self._status_right = tk.StringVar(value="并发：1")
        ttk.Label(status_frame, textvariable=self._status_left).pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self._status_mid).pack(side=tk.LEFT, padx=(40, 0))
        ttk.Label(status_frame, textvariable=self._status_right).pack(side=tk.RIGHT)

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

    def _toggle_advanced_config(self) -> None:
        self.advanced_config_visible.set(not self.advanced_config_visible.get())
        self._sync_advanced_config_visibility()

    def _sync_advanced_config_visibility(self) -> None:
        if not hasattr(self, "_method1_advanced_frame"):
            return
        is_method1 = self.method_var.get() == "method1"
        visible = bool(self.advanced_config_visible.get()) and is_method1
        if visible:
            self._method1_advanced_frame.grid()
            self._method1_advanced_toggle_btn.configure(text="隐藏高级配置")
        else:
            self._method1_advanced_frame.grid_remove()
            self._method1_advanced_toggle_btn.configure(text="显示高级配置")

    def _on_run_mode_changed(self) -> None:
        if self._is_background_run_mode():
            self.run_mode_hint_var.set(RUN_MODE_BACKGROUND_HINT)
            self._status_mid.set(f"当前模式：{RUN_MODE_BACKGROUND_LABEL}")
            self._log(f"已选择{RUN_MODE_BACKGROUND_LABEL}：{RUN_MODE_BACKGROUND_HINT}。")
        else:
            self.run_mode_hint_var.set("")
            self._status_mid.set(f"当前模式：{RUN_MODE_FOREGROUND_LABEL}")
            self._log(f"已选择{RUN_MODE_FOREGROUND_LABEL}。")

    def _is_background_run_mode(self) -> bool:
        return _run_mode_key_for_owner(self) == "background"

    def _block_background_unsupported_action(self, action_name: str) -> bool:
        if not self._is_background_run_mode():
            return False
        if action_name in ("单账号运行", "当前层串行", "全部串行"):
            return False
        message = "后台模式当前支持方式一单账号、当前层串行、全部串行；方式二未接入"
        self._log(f"阻止{action_name}：{message}")
        messagebox.showwarning("后台模式限制", message)
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
                widget.grid_remove()
            for widget in self.wm_row_param_widgets:
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
        for widget in self.wm_row_param_widgets:
            widget.grid_remove()
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
        return project_root() / WINDOW_DETECTION_LOG_PATH

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
            return app_root() / "slots" / "invalid_profile.json"
        return window_slots_profile_path(app_root(), params)

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
        mode = self.method_var.get()
        is_m1 = (mode == "method1")
        # 方式一控件
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
            w.grid() if is_m1 else w.grid_remove()
        if is_m1:
            self._sync_advanced_config_visibility()
        else:
            self._method1_advanced_frame.grid_remove()
        # 方式二控件
        for w in (self._method2_row1, self._method2_csv_entry, self._method2_btn_pick,
                  self._method2_btn_import):
            w.grid() if not is_m1 else w.grid_remove()
        # 表格
        if is_m1:
            self._table_frame_m2.pack_forget()
            self._table_frame_m1.pack(fill=tk.BOTH, expand=True, pady=(0, 8), before=self._log_outer)
        else:
            self._table_frame_m1.pack_forget()
            self._table_frame_m2.pack(fill=tk.BOTH, expand=True, pady=(0, 8), before=self._log_outer)
        # 账号下拉框
        if is_m1:
            self._refresh_account_choices()
        if hasattr(self, "group_settings_btn"):
            self.group_settings_btn.configure(state=tk.NORMAL if is_m1 else tk.DISABLED)

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
            memory_file = project_root() / "csv_last_path.txt"
            memory_file.write_text(path, encoding="utf-8")
        except Exception:
            pass

    def _auto_load_csv(self) -> None:
        """启动时自动加载上次导入的CSV"""
        try:
            memory_file = project_root() / "csv_last_path.txt"
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
            if self._block_background_unsupported_action("方式二"):
                return
            messagebox.showinfo("提示", "方式二没有层级概念，请使用\"单账号运行\"或\"全部串行\"。")
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
            if self._block_background_unsupported_action("方式二"):
                return
            self._run_method2_all()
            return
        background_mode = _run_mode_key_for_owner(self) == "background"
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
        log_dir = project_root() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        if cleanup_old:
            # 清理旧日志，仅保留最新2份
            existing_logs = sorted(log_dir.glob("run_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in existing_logs[2:]:
                try:
                    old.unlink()
                except Exception:
                    pass
        ts = _time.strftime("%Y%m%d_%H%M%S")
        self._log_file_path = log_dir / f"run_{ts}.log"
        self._log_file = open(str(self._log_file_path), "w", encoding="utf-8")
        self._write_file_log(f"=== 斗罗大陆H5上号器 运行日志 {ts} ===")
        self._write_file_log(f"版本号: {APP_VERSION}")

    def _write_file_log(self, msg: str) -> None:
        if self._log_file is not None:
            import time as _time
            ts = _time.strftime("%H:%M:%S")
            self._log_file.write(f"[{ts}] {msg}\n")
            self._log_file.flush()

    def _queue_log_file(self, message: str) -> None:
        """仅写文件，不显示在 GUI。"""
        self._write_file_log(message)

    def _open_log_dir(self) -> None:
        import os
        log_dir = str(project_root() / "logs")
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
        if self.stop_event.is_set():
            self._update_status_bar("已停止")
        elif result:
            self._queue_log(f"[后台模式] 成功: {account.display_name}")
            self._update_status_bar("后台模式完成：成功1，失败0")
        else:
            self._queue_log(f"[后台模式] 失败: {account.display_name}")
            self._update_status_bar("后台模式完成：成功0，失败1")

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

            if self.stop_event.is_set():
                mark_stopped(account)
                for remaining in accounts[index:]:
                    mark_stopped(remaining)
                break

            status = latest_status.get(account.key, "")
            passport = passport_by_key.get(account.key, "")
            if result and status == "已进入游戏，跳过":
                skip_count += 1
                self._queue_log(f"[后台串行][{index}/{total}] 窗口{account.game_window_no}：已进入游戏，跳过")
            elif result:
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
                    "settings_path": str(app_root() / "automation_settings.json"),
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
                "settings_path": str(app_root() / "automation_settings.json"),
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
            "settings_path": str(app_root() / "automation_settings.json"),
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
            if "成功" in status:
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
