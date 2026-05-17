from __future__ import annotations

import queue
import json
import os
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .automation import AccountRunner
from .config import (
    AccountConfig,
    CSVAccount,
    LEVELS,
    SELECTABLE_LEVELS,
    SINGLE_LEVEL_NAME,
    STATUSES,
    app_root,
    project_root,
    find_default_bookmark_file,
    load_accounts_from_bookmarks,
    load_csv_accounts,
    load_settings,
)
from .dm_client import diagnose_dm_environment_with_32bit_python, select_login_window_by_game_no
from .window_manager import (
    RowTileConfig,
    TileConfig,
    calculate_row_tile_plan,
    close_game_windows,
    launch_game_process,
    list_game_windows,
    rename_game_windows,
    tile_game_windows,
    tile_game_windows_by_row_count,
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


class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("上号器 — 前台串行模式")
        w, h = 1160, 820
        ws = self.winfo_screenwidth()
        hs = self.winfo_screenheight()
        x = (ws - w) // 2
        y = (hs - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(1080, 760)

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
        self.running_processes: list[object] = []
        self.running_processes_lock = threading.Lock()
        self.is_closing = False

        self.settings_path = tk.StringVar(value=str(app_root() / "automation_settings.json"))
        self.bookmark_path = tk.StringVar(value=find_default_bookmark_file())
        self.bookmark_root_name = tk.StringVar(value="账号")
        self.level_var = tk.StringVar(value="第一层")
        self.account_var = tk.StringVar(value="")
        self.max_workers_var = tk.IntVar(value=4)
        self.batch_verify_rounds_var = tk.IntVar(value=3)
        self.notice_outside_x_var = tk.DoubleVar(value=0.08)
        self.notice_outside_y_var = tk.DoubleVar(value=0.08)
        self.method_var = tk.StringVar(value="method1")
        self.csv_path = tk.StringVar(value="")
        self.level_count_vars = {level: tk.IntVar(value=8) for level in LEVELS}
        self.wm_game_path_var = tk.StringVar(value="")
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
        self._auto_load_csv()
        self.after(100, self._drain_ui_queue)
        self._load_default_config_if_present()
        self._log_admin_status_warning()
        self._log_startup_dm_environment()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_settings_defaults(self) -> None:
        try:
            settings = load_settings(self.settings_path.get())
        except Exception:
            return
        if settings.bookmark_file:
            self.bookmark_path.set(settings.bookmark_file)
        self.bookmark_root_name.set(settings.bookmark_root_name)
        self.max_workers_var.set(settings.max_workers)
        self.notice_outside_x_var.set(settings.notice_close_outside_ratio[0])
        self.notice_outside_y_var.set(settings.notice_close_outside_ratio[1])

    def _build_widgets(self) -> None:
        root = ttk.Frame(self, padding=(12, 8, 12, 4))
        root.pack(fill=tk.BOTH, expand=True)

        # ===== 1. 窗口管理 =====
        window_frame = ttk.LabelFrame(root, text="窗口管理", padding=6)
        window_frame.pack(fill=tk.X, pady=(0, 8))
        window_frame.columnconfigure(1, weight=1)

        # 第1行：游戏路径
        ttk.Label(window_frame, text="游戏路径", width=10, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(4, 6), pady=3
        )
        ttk.Entry(window_frame, textvariable=self.wm_game_path_var).grid(
            row=0, column=1, columnspan=12, sticky="ew", padx=4, pady=3
        )
        ttk.Button(window_frame, text="选择", width=8, command=self._pick_game_path).grid(
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
        ttk.Button(window_action_row, text="识别窗口", width=18,
                   command=self._wm_identify_windows).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(window_action_row, text="排列窗口", width=18,
                   command=self._wm_tile_windows).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(window_action_row, text="关闭窗口", width=18, fg="#cc0000",
                  command=self._wm_close_windows, font=("", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))

        # ===== 2. 配置上号器 =====
        config_frame = ttk.LabelFrame(root, text="配置上号器", padding=6)
        config_frame.pack(fill=tk.X, pady=(0, 8))
        config_frame.columnconfigure(1, weight=1)

        method_row = ttk.Frame(config_frame)
        method_row.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        ttk.Label(method_row, text="上号方式").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Radiobutton(method_row, text="方式一：通行证上号", variable=self.method_var, value="method1",
                        command=self._on_method_changed).pack(side=tk.LEFT, padx=(0, 24))
        ttk.Radiobutton(method_row, text="方式二：账号密码 + 通行证上号", variable=self.method_var, value="method2",
                        command=self._on_method_changed).pack(side=tk.LEFT)

        self._method1_row1 = ttk.Label(config_frame, text="收藏文件", width=12, anchor="e")
        self._method1_row1.grid(row=1, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_bookmark_entry = ttk.Entry(config_frame, textvariable=self.bookmark_path)
        self._method1_bookmark_entry.grid(row=1, column=1, sticky="ew", padx=4, pady=3)
        self._method1_btn_pick = ttk.Button(config_frame, text="选择", width=8, command=self._pick_bookmark_file)
        self._method1_btn_pick.grid(row=1, column=2, padx=4, pady=3)
        self._method1_btn_load = ttk.Button(config_frame, text="读取收藏夹", command=self._load_accounts)
        self._method1_btn_load.grid(row=1, column=3, padx=4, pady=3)

        self._method1_row2a = ttk.Label(config_frame, text="根目录名", width=12, anchor="e")
        self._method1_row2a.grid(row=2, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_root_entry = ttk.Entry(config_frame, textvariable=self.bookmark_root_name)
        self._method1_root_entry.grid(row=2, column=1, sticky="ew", padx=4, pady=3)

        self._method1_row3a = ttk.Label(config_frame, text="自动化设置", width=12, anchor="e")
        self._method1_row3a.grid(row=3, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_settings_entry = ttk.Entry(config_frame, textvariable=self.settings_path)
        self._method1_settings_entry.grid(row=3, column=1, sticky="ew", padx=4, pady=3)
        self._method1_btn_settings = ttk.Button(config_frame, text="选择", width=8, command=self._pick_settings)
        self._method1_btn_settings.grid(row=3, column=2, padx=4, pady=3)

        self._method1_level_count_label = ttk.Label(config_frame, text="每层数量", width=12, anchor="e")
        self._method1_level_count_label.grid(row=4, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_level_count_frame = ttk.Frame(config_frame)
        self._method1_level_count_frame.grid(row=4, column=1, columnspan=3, sticky="w", padx=4, pady=3)
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
        self.level_box.pack(side=tk.LEFT, padx=(0, 16))
        self.level_box.bind("<<ComboboxSelected>>", lambda _: self._on_level_changed())

        ttk.Label(select_row, text="账号").pack(side=tk.LEFT, padx=(0, 4))
        self.account_box = ttk.Combobox(select_row, textvariable=self.account_var, width=28, state="readonly")
        self.account_box.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(select_row, text="模式").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(select_row, text="前台串行", relief="sunken", width=10, anchor="center", padding=2).pack(side=tk.LEFT, padx=(0, 16))

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
        columns = ("level", "bookmark", "window", "passport", "url", "status", "timing")
        self.tree = ttk.Treeview(self._table_frame_m1, columns=columns, show="headings", height=7)
        self.tree.heading("level", text="层级")
        self.tree.heading("bookmark", text="收藏编号")
        self.tree.heading("window", text="窗口号")
        self.tree.heading("passport", text="本次通行证")
        self.tree.heading("url", text="链接")
        self.tree.heading("status", text="状态")
        self.tree.heading("timing", text="耗时")
        self.tree.column("level", width=70, anchor=tk.CENTER)
        self.tree.column("bookmark", width=70, anchor=tk.CENTER)
        self.tree.column("window", width=65, anchor=tk.CENTER)
        self.tree.column("passport", width=110, anchor=tk.CENTER)
        self.tree.column("url", width=450)
        self.tree.column("status", width=130, anchor=tk.CENTER)
        self.tree.column("timing", width=70, anchor=tk.CENTER)
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
        self._log_outer.pack(fill=tk.X, pady=(0, 4))
        log_header = ttk.Frame(self._log_outer)
        log_header.pack(fill=tk.X, pady=(0, 2))
        ttk.Button(log_header, text="打开日志目录", command=self._open_log_dir).pack(side=tk.RIGHT, padx=2)

        self.log_text = tk.Text(self._log_outer, height=6, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ===== 6. 底部状态栏 =====
        status_frame = ttk.Frame(root, relief="sunken", padding=(8, 3))
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_left = tk.StringVar(value="就绪")
        self._status_mid = tk.StringVar(value="当前模式：前台串行")
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

    def _pick_game_path(self) -> None:
        path = filedialog.askopenfilename(
            title="选择游戏程序或快捷方式",
            filetypes=[("程序或快捷方式", "*.exe *.lnk"), ("EXE", "*.exe"), ("Shortcut", "*.lnk"), ("All files", "*.*")],
        )
        if path:
            self.wm_game_path_var.set(path)
            self._save_window_manager_settings()

    def _load_window_manager_settings(self) -> None:
        settings, error = load_window_manager_settings()
        self.wm_fixed_mode_settings = settings.fixed_mode
        self.wm_row_count_mode_settings = settings.row_count_mode
        self.wm_game_path_var.set(settings.game_path)
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
        if self.wm_launch_thread and self.wm_launch_thread.is_alive():
            self._log("[窗口管理] 批量启动正在进行中。")
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

        self._save_window_manager_settings()
        auto_tile = bool(self.wm_auto_tile_after_launch_var.get())
        auto_rename = bool(self.wm_auto_rename_after_tile_var.get())
        arrangement = self._wm_read_arrangement_config() if auto_tile else None
        if auto_tile and arrangement is None:
            return
        tile_mode = arrangement[0] if arrangement else WM_TILE_MODE_FIXED
        tile_config = arrangement[1] if arrangement else None
        title_template = None
        if auto_tile and auto_rename:
            title_template = self._wm_read_title_template()
            if title_template is None:
                return

        excluded_hwnds = self._wm_excluded_hwnds()
        self.wm_launch_btn.configure(state=tk.DISABLED)
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
        excluded_hwnds: list[int],
    ) -> None:
        def log(message: str) -> None:
            self._queue_log(f"[窗口管理] {message}")

        try:
            log(f"准备批量启动：路径={game_path}，数量={launch_count}，间隔={launch_interval}ms")
            try:
                before_windows = list_game_windows(exclude_hwnds=excluded_hwnds)
                before_count = len(before_windows)
                log(f"启动前识别到 {before_count} 个 H5 窗口")
            except Exception as exc:
                before_count = 0
                log(f"启动前识别窗口失败：{exc}")

            for index in range(1, launch_count + 1):
                log(f"正在启动第 {index}/{launch_count} 个窗口")
                result = launch_game_process(game_path)
                if result.success:
                    log(f"第 {index} 个窗口启动命令已发送")
                else:
                    log(f"第 {index} 个窗口启动命令发送失败：{result.error}")

                if launch_interval > 0:
                    time.sleep(launch_interval / 1000)

                try:
                    current_windows = list_game_windows(exclude_hwnds=excluded_hwnds)
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
                final_count = len(list_game_windows(exclude_hwnds=excluded_hwnds))
            except Exception as exc:
                final_count = -1
                log(f"批量启动完成后识别窗口失败：{exc}")

            target_count = before_count + launch_count
            if final_count >= 0:
                log(f"批量启动完成，目标 {target_count} 个，当前识别到 {final_count} 个")

            if auto_tile and tile_config is not None:
                is_stable, stable_count = self._wm_wait_for_windows_stable(
                    target_count=target_count,
                    excluded_hwnds=excluded_hwnds,
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
                    results = self._wm_run_tile(
                        tile_mode=tile_mode,
                        tile_config=tile_config,
                        exclude_hwnds=excluded_hwnds,
                        log=log,
                    )
                    log(f"自动排列完成，结果 {len(results)} 个")
                    self._wm_log_tile_results(results, log)
                    if auto_rename:
                        self._wm_rename_windows_after_tile(
                            log=log,
                            exclude_hwnds=excluded_hwnds,
                            title_template=title_template,
                        )
                        log("自动编号标题完成")
                except Exception as exc:
                    log(f"启动后自动排列失败：{exc}")
        finally:
            self.after(0, lambda: self.wm_launch_btn.configure(state=tk.NORMAL))

    def _wm_wait_for_windows_stable(
        self,
        target_count: int,
        excluded_hwnds: list[int],
        log,
    ) -> tuple[bool, int]:
        log("批量启动命令发送完成，等待窗口稳定")
        last_count: int | None = None
        stable_count = 0
        current_count = 0
        deadline = time.monotonic() + WM_WAIT_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            try:
                current_count = len(list_game_windows(exclude_hwnds=excluded_hwnds))
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
        log=None,
    ):
        if tile_mode == WM_TILE_MODE_ROW_COUNT:
            windows = list_game_windows(exclude_hwnds=exclude_hwnds)
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
                windows=windows,
            )
        return tile_game_windows(tile_config, exclude_hwnds=exclude_hwnds)

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
    ) -> None:
        if title_template is None:
            title_template = self._wm_read_title_template()
        if title_template is None:
            return
        log(f"开始自动编号标题：模板={title_template}")
        try:
            results = rename_game_windows(title_template, exclude_hwnds=exclude_hwnds)
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
        self._wm_rename_windows_after_tile(
            log=lambda message: self._log(f"[窗口管理] {message}"),
            exclude_hwnds=self._wm_excluded_hwnds(),
        )

    def _wm_identify_windows(self) -> None:
        try:
            windows = list_game_windows(exclude_hwnds=self._wm_excluded_hwnds())
        except Exception as exc:
            self._log(f"窗口管理：识别登录窗口失败：{exc}")
            messagebox.showerror("识别登录窗口失败", str(exc))
            return

        self._log(f"窗口管理：识别到 {len(windows)} 个斗罗大陆H5登录窗口。")
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

        try:
            results = self._wm_run_tile(
                tile_mode=tile_mode,
                tile_config=config,
                exclude_hwnds=self._wm_excluded_hwnds(),
                log=lambda message: self._log(f"窗口管理：{message}"),
            )
        except Exception as exc:
            self._log(f"窗口管理：排列登录窗口失败：{exc}")
            messagebox.showerror("排列登录窗口失败", str(exc))
            return

        if tile_mode == WM_TILE_MODE_ROW_COUNT:
            self._log(
                "窗口管理：排列完成，"
                f"排列方式={tile_mode}，单行数量={config.per_row}，"
                f"自动缩放窗口=True，禁止超出屏幕宽度={config.prevent_overflow}，"
                f"结果 {len(results)} 个。"
            )
        else:
            self._log(
                "窗口管理：排列完成，"
                f"排列方式={tile_mode}，目标大小={config.width}x{config.height}，"
                f"每行={config.per_row}，结果 {len(results)} 个。"
            )
        self._log(
            f"窗口管理：当前排列方式={tile_mode}，识别到 {len(results)} 个窗口。"
        )
        self._wm_log_tile_results(results, lambda message: self._log(f"窗口管理：{message}"))
        if self.wm_auto_rename_after_tile_var.get():
            self._wm_rename_windows_after_tile(
                log=lambda message: self._log(f"[窗口管理] {message}"),
                exclude_hwnds=self._wm_excluded_hwnds(),
            )

    def _wm_close_windows(self) -> None:
        try:
            results = close_game_windows(exclude_hwnds=self._wm_excluded_hwnds())
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
    $_.ProcessId -ne $selfPid -and $_.CommandLine -like '*dm_click_helper.py*'
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
            self._log(f"已清理 dm_click_helper.py 子进程 {count} 个。")
            if result.stderr:
                self._write_file_log(f"清理 dm_click_helper.py stderr: {result.stderr.strip()[:500]}")
            return count
        except Exception as exc:
            self._log(f"清理 dm_click_helper.py 子进程失败：{exc}")
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
            self.bookmark_path.set(path)

    def _pick_settings(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if path:
            self.settings_path.set(path)

    def _load_default_config_if_present(self) -> None:
        if self.bookmark_path.get() and Path(self.bookmark_path.get()).exists():
            self._load_accounts()
        else:
            self._log("未自动找到浏览器收藏夹文件，请手动选择 Bookmarks 文件后点击“读取收藏夹”。")

    def _load_accounts(self) -> None:
        try:
            settings = load_settings(self.settings_path.get())
            bookmark_file = self.bookmark_path.get() or settings.bookmark_file
            root_name = self.bookmark_root_name.get().strip() or settings.bookmark_root_name
            level_counts = self._current_level_counts()
            self.accounts = load_accounts_from_bookmarks(
                bookmark_file,
                root_name,
                settings.level_names,
                level_counts=level_counts,
                log=lambda message: self._log(f"收藏夹读取：{message}"),
            )
            self.status_by_key = {account.key: "未开始" for account in self.accounts}
            self.passport_by_key = {account.key: "" for account in self.accounts}
            self._refresh_mode_account_scope()
            self._log(f"已从收藏夹读取 {len(self.accounts)} 个账号链接。{self._account_count_summary()}")
        except Exception as exc:
            messagebox.showerror("读取收藏夹失败", str(exc))
            self._log(f"读取收藏夹失败: {exc}")

    def _current_level_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for level in LEVELS:
            counts[level] = int(self.level_count_vars[level].get())
        return counts

    def _account_count_summary(self, accounts: list[AccountConfig] | None = None) -> str:
        source = accounts if accounts is not None else self.accounts
        parts = []
        single_count = sum(1 for account in source if account.level == SINGLE_LEVEL_NAME)
        if single_count:
            parts.append(f"{SINGLE_LEVEL_NAME} {single_count} 个")
        for level in LEVELS:
            count = sum(1 for account in source if account.level == level)
            if count:
                parts.append(f"{level} {count} 个")
        return "分类：" + "，".join(parts) if parts else "分类：无账号"

    def _is_row_count_account_mode(self) -> bool:
        return self._wm_mode_key_from_label() == TILE_MODE_ROW_COUNT

    def _allowed_level_values(self) -> tuple[str, ...]:
        if self._is_row_count_account_mode():
            return (SINGLE_LEVEL_NAME,)
        return ("全部", *LEVELS)

    def _is_account_allowed_in_current_mode(self, account: AccountConfig) -> bool:
        if self._is_row_count_account_mode():
            return account.level == SINGLE_LEVEL_NAME
        return account.level in LEVELS

    def _mode_allowed_accounts(self) -> list[AccountConfig]:
        return [account for account in self.accounts if self._is_account_allowed_in_current_mode(account)]

    def _filtered_accounts_for_ui(self) -> list[AccountConfig]:
        mode_accounts = self._mode_allowed_accounts()
        level = self.level_var.get()
        if self._is_row_count_account_mode():
            return [account for account in mode_accounts if account.level == SINGLE_LEVEL_NAME]
        if level == "全部":
            return mode_accounts
        return [account for account in mode_accounts if account.level == level]

    def _on_level_changed(self) -> None:
        self._refresh_table()
        self._refresh_account_choices()
        self._log(
            f"层级已切换：排列方式={self.wm_tile_mode_var.get()}，"
            f"层级={self.level_var.get()}，当前账号列表 {len(self._filtered_accounts_for_ui())} 个。"
        )

    def _refresh_mode_account_scope(self, log_change: bool = False) -> None:
        allowed_levels = self._allowed_level_values()
        self.level_box["values"] = allowed_levels
        if self.level_var.get() not in allowed_levels:
            self.level_var.set(allowed_levels[0] if allowed_levels else "")
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
            selected, _ = select_login_window_by_game_no(account.game_window_no)
            if selected is None:
                message = f"未在当前桌面找到窗口 {account.game_window_no}，已停止，避免跨桌面运行。"
                self._log(
                    f"阻止运行：{message} 排列方式={self.wm_tile_mode_var.get()}，"
                    f"层级={account.level}，账号={account.display_name}"
                )
                messagebox.showwarning("当前桌面窗口不存在", message)
                return False
        return True

    # ===== 方式二：CSV 导入 =====

    def _on_method_changed(self) -> None:
        mode = self.method_var.get()
        is_m1 = (mode == "method1")
        # 方式一控件
        for w in (self._method1_row1, self._method1_bookmark_entry, self._method1_btn_pick,
                  self._method1_btn_load, self._method1_row2a, self._method1_root_entry,
                  self._method1_row3a, self._method1_settings_entry, self._method1_btn_settings,
                  self._method1_level_count_label, self._method1_level_count_frame):
            w.grid() if is_m1 else w.grid_remove()
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
                values=(
                    account.level,
                    account.bookmark_no,
                    account.game_window_no,
                    self.passport_by_key.get(account.key, ""),
                    account.url,
                    self.status_by_key.get(account.key, "未开始"),
                    self.timing_by_key.get(account.key, ""),
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
        if not self._validate_accounts_for_current_mode([account]):
            return
        self._log(
            f"单账号运行: {account.display_name}。"
            f"OCR → 打开游戏页 → 关闭公告 → 通行证 → 输入 → 确认。"
        )
        self._start_serial_run([account], batch_fast=False)

    def _run_level_serial(self) -> None:
        if self.method_var.get() == "method2":
            messagebox.showinfo("提示", "方式二没有层级概念，请使用\"单账号运行\"或\"全部串行\"。")
            return
        level = self.level_var.get()
        if level == "全部":
            messagebox.showwarning("请选择层级", "当前层串行需要选择一个具体层级。")
            return
        accounts = self._filtered_accounts_for_ui()
        if not accounts:
            messagebox.showwarning("无账号", f"当前层 {level} 没有账号。")
            return
        if not self._validate_accounts_for_current_mode(accounts):
            return
        self._log(f"当前层串行: {level}，共 {len(accounts)} 个账号，批量快速登录 + 统一校验。")
        self._start_serial_run(accounts, batch_fast=True)

    def _run_all_serial(self) -> None:
        if self.method_var.get() == "method2":
            self._run_method2_all()
            return
        accounts = self._mode_allowed_accounts()
        if not accounts:
            messagebox.showwarning("无账号", "请先读取收藏夹。")
            return
        if not self._validate_accounts_for_current_mode(accounts):
            return
        self._log(f"全部串行: 共 {len(accounts)} 个账号，批量快速登录 + 统一校验。{self._account_count_summary(accounts)}")
        self._start_serial_run(accounts, batch_fast=True)

    # ===== 方式二运行 =====

    def _run_method2_single(self) -> None:
        """方式二：单账号运行（选中的CSV账号）"""
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
        valid = [a for a in self.csv_accounts if "配置缺失" not in a.status]
        if not valid:
            messagebox.showwarning("无有效账号", "CSV中没有有效的账号。")
            return
        self._log(f"[方式二] 全部串行: 共 {len(valid)} 个账号，严格逐个执行。")
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
        """在后台线程串行执行方式二账号列表。"""
        if self.worker_thread is not None and self.worker_thread.is_alive():
            messagebox.showwarning("任务进行中", "当前有任务正在执行。")
            return
        self._setup_log_file()
        self.stop_event.clear()
        self.csv_passport_by_key.clear()
        self.csv_timing_by_key.clear()
        for a in accounts:
            self.csv_status_by_key[a.key] = "未开始"
        self._refresh_csv_table()

        def _run():
            import time as _time
            try:
                settings = load_settings(self.settings_path.get())
            except Exception as exc:
                self._queue_log(f"[方式二] 读取设置失败: {exc}")
                return
            from .config import AccountConfig as _AC
            import subprocess as _sp
            success_count = 0
            fail_count = 0
            total = len(accounts)
            start_time = _time.time()
            for i, acc in enumerate(accounts, start=1):
                if self.stop_event.is_set():
                    self._queue_log("[方式二] 已停止")
                    break
                self._queue_log(f"[{i}/{total}] {acc.display_name}")
                self._queue_status_csv(acc, "OCR中")

                runner = AccountRunner(
                    account=_AC(level="方式二", bookmark_no=0, game_window_no=acc.game_window_no, url=acc.url),
                    settings=settings,
                    stop_event=self.stop_event,
                    log=self._queue_log,
                    update_status=lambda a, s, _acc=acc: self._queue_status_csv(_acc, s),
                    passport_found=lambda a, p, _acc=acc: self._queue_passport_csv(_acc, p),
                )
                result = runner.run_method2(acc)
                if self.stop_event.is_set():
                    self._queue_status_csv(acc, "已停止")
                    self._queue_log("[方式二] 任务已停止，不会继续执行后续账号。")
                    _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)
                    break
                elif result:
                    success_count += 1
                    self._queue_status_csv(acc, "成功")
                    self._queue_timing_csv(acc, runner.last_timings.get("总计", 0))
                else:
                    fail_count += 1
                    self._queue_status_csv(acc, "失败")
                _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)
            elapsed = _time.time() - start_time
            if self.stop_event.is_set():
                self.ui_queue.put(("status_bar", "已停止"))
                self._queue_log(f"[方式二] 任务已停止：总{total} 成功{success_count} 失败{fail_count} 耗时{elapsed:.0f}秒")
                self._write_file_log(f"任务已停止：总{total} 成功{success_count} 失败{fail_count} 耗时{elapsed:.0f}秒")
            else:
                self.ui_queue.put(("status_bar", f"任务完成：成功{success_count}，失败{fail_count}"))
                self._queue_log(f"[方式二] 任务完成：总{total} 成功{success_count} 失败{fail_count} 耗时{elapsed:.0f}秒")
                self._write_file_log(f"任务完成：总{total} 成功{success_count} 失败{fail_count} 耗时{elapsed:.0f}秒")
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
            elif "失败" in status:
                tag = "failed"
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

    def _setup_log_file(self) -> None:
        import time as _time
        log_dir = project_root() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
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

    def _serial_worker(self, accounts: list[AccountConfig], settings, batch_fast: bool = False, verify_rounds: int = 3) -> None:
        self._setup_log_file()
        self._queue_log(f"前台串行模式：共 {len(accounts)} 个账号，严格逐个执行。")
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
                # === exe 模式：同进程直接调用（无子进程隔离） ===
                import os as _os
                _os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                    str(Path(_os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"))
                from .automation import AccountRunner
                runner = AccountRunner(
                    account, settings, self.stop_event,
                    log=lambda msg: self._queue_log(str(msg)),
                    update_status=lambda a, s: self._queue_status(a, s),
                    passport_found=lambda a, p: self._queue_passport(a, p),
                )
                flow_result = runner.run_game_flow()
                if self.stop_event.is_set():
                    self._queue_status(account, "已停止")
                    self._queue_log("任务已停止，不会继续执行后续账号。")
                    _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)
                    break
                elif flow_result:
                    success_count += 1
                    self._queue_timing(account, runner.last_timings.get("总计", 0))
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
            runner = AccountRunner(
                account, settings, self.stop_event,
                log=lambda msg: self._queue_log(str(msg)),
                update_status=lambda a, s: self._queue_status(a, s),
                passport_found=lambda a, p: self._queue_passport(a, p),
            )
            if action == "fast_submit":
                result = runner.run_game_flow_fast_submit()
                self._queue_timing(account, runner.last_timings.get("总计", 0))
                return {
                    "result": result,
                    "verify_state": "",
                    "submit_result": runner.last_fast_submit_result,
                    "timing": runner.last_timings.get("总计", 0),
                }
            if action == "verify":
                state = runner.verify_login_result()
                return {"result": state == "logged_in", "verify_state": state, "timing": 0.0}
            result = runner.run_game_flow()
            self._queue_timing(account, runner.last_timings.get("总计", 0))
            return {"result": result, "verify_state": "", "timing": runner.last_timings.get("总计", 0)}
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
            values = list(self.tree.item(account.key, "values"))
            values[5] = status
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
            values = list(self.tree.item(account.key, "values"))
            values[3] = passport
            self.tree.item(account.key, values=values)

    def _set_timing(self, account: AccountConfig, timing: str) -> None:
        self.timing_by_key[account.key] = timing
        if self.tree.exists(account.key):
            values = list(self.tree.item(account.key, "values"))
            values[6] = timing
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
