from __future__ import annotations

import queue
import json
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .automation import AccountRunner
from .config import (
    AccountConfig,
    CSVAccount,
    LEVELS,
    STATUSES,
    app_root,
    project_root,
    filter_accounts,
    find_default_bookmark_file,
    load_accounts_from_bookmarks,
    load_csv_accounts,
    load_settings,
)
from .dm_client import diagnose_dm_environment_with_32bit_python


class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("斗罗大陆H5上号器 — 前台串行模式")
        w, h = 1120, 720
        ws = self.winfo_screenwidth()
        hs = self.winfo_screenheight()
        x = (ws - w) // 2
        y = (hs - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(980, 620)

        self.accounts: list[AccountConfig] = []
        self.status_by_key: dict[str, str] = {}
        self.passport_by_key: dict[str, str] = {}
        self.manual_passport_cache: dict[str, str] = {}
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self._log_file = None
        self._log_file_path: Path | None = None

        self.settings_path = tk.StringVar(value=str(app_root() / "automation_settings.json"))
        self.bookmark_path = tk.StringVar(value=find_default_bookmark_file())
        self.bookmark_root_name = tk.StringVar(value="账号")
        self.level_var = tk.StringVar(value="第一层")
        self.account_var = tk.StringVar(value="")
        self.max_workers_var = tk.IntVar(value=4)
        self.notice_outside_x_var = tk.DoubleVar(value=0.08)
        self.notice_outside_y_var = tk.DoubleVar(value=0.08)
        self.method_var = tk.StringVar(value="method1")
        self.csv_path = tk.StringVar(value="")
        self.csv_accounts: list[CSVAccount] = []
        self.csv_status_by_key: dict[str, str] = {}
        self.csv_passport_by_key: dict[str, str] = {}

        self._apply_settings_defaults()
        self._build_widgets()
        self.after(100, self._drain_ui_queue)
        self._load_default_config_if_present()
        self._log_startup_dm_environment()

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

        # ===== 1. 配置区 =====
        config_frame = ttk.LabelFrame(root, text="配置", padding=6)
        config_frame.pack(fill=tk.X, pady=(0, 8))
        config_frame.columnconfigure(1, weight=1)

        # 上号方式选择
        method_row = ttk.Frame(config_frame)
        method_row.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        ttk.Label(method_row, text="上号方式").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Radiobutton(method_row, text="方式一：通行证上号", variable=self.method_var, value="method1",
                        command=self._on_method_changed).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Radiobutton(method_row, text="方式二：账号密码 + 通行证上号", variable=self.method_var, value="method2",
                        command=self._on_method_changed).pack(side=tk.LEFT)

        # 方式一控件（收藏夹相关）
        self._method1_row1 = ttk.Label(config_frame, text="收藏文件", width=12, anchor="e")
        self._method1_row1.grid(row=1, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method1_bookmark_entry = ttk.Entry(config_frame, textvariable=self.bookmark_path)
        self._method1_bookmark_entry.grid(row=1, column=1, sticky="ew", padx=4, pady=3)
        self._method1_btn_pick = ttk.Button(config_frame, text="选择", width=6, command=self._pick_bookmark_file)
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
        self._method1_btn_settings = ttk.Button(config_frame, text="选择", width=6, command=self._pick_settings)
        self._method1_btn_settings.grid(row=3, column=2, padx=4, pady=3)

        # 方式二控件（CSV 导入）
        self._method2_row1 = ttk.Label(config_frame, text="CSV文件", width=12, anchor="e")
        self._method2_csv_entry = ttk.Entry(config_frame, textvariable=self.csv_path)
        self._method2_btn_pick = ttk.Button(config_frame, text="选择", width=6, command=self._pick_csv_file)
        self._method2_btn_import = ttk.Button(config_frame, text="导入CSV", command=self._import_csv)
        # 方式二控件网格位置（初始隐藏）
        self._method2_row1.grid(row=1, column=0, sticky="e", padx=(4, 6), pady=3)
        self._method2_csv_entry.grid(row=1, column=1, sticky="ew", padx=4, pady=3)
        self._method2_btn_pick.grid(row=1, column=2, padx=4, pady=3)
        self._method2_btn_import.grid(row=1, column=3, padx=4, pady=3)
        self._method2_row1.grid_remove()
        self._method2_csv_entry.grid_remove()
        self._method2_btn_pick.grid_remove()
        self._method2_btn_import.grid_remove()

        # ===== 2. 运行区 =====
        run_frame = ttk.LabelFrame(root, text="运行", padding=6)
        run_frame.pack(fill=tk.X, pady=(0, 8))

        # 选择行
        select_row = ttk.Frame(run_frame)
        select_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(select_row, text="层级").pack(side=tk.LEFT, padx=(2, 4))
        self.level_box = ttk.Combobox(select_row, textvariable=self.level_var,
                                       values=("全部", *LEVELS), width=8, state="readonly")
        self.level_box.pack(side=tk.LEFT, padx=(0, 16))
        self.level_box.bind("<<ComboboxSelected>>", lambda _: self._refresh_account_choices())

        ttk.Label(select_row, text="账号").pack(side=tk.LEFT, padx=(0, 4))
        self.account_box = ttk.Combobox(select_row, textvariable=self.account_var, width=28, state="readonly")
        self.account_box.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(select_row, text="模式").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(select_row, text="前台串行", relief="sunken", width=10, anchor="center", padding=2).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(select_row, text="并发").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(select_row, text="1", relief="sunken", width=4, anchor="center", padding=2).pack(side=tk.LEFT)

        # 操作行
        action_row = ttk.Frame(run_frame)
        action_row.pack(fill=tk.X)

        ttk.Button(action_row, text="单账号运行", width=14, command=self._run_selected_account).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_row, text="当前层串行", width=14, command=self._run_level_serial).pack(side=tk.LEFT, padx=2)
        ttk.Button(action_row, text="全部串行", width=14, command=self._run_all_serial).pack(side=tk.LEFT, padx=2)
        self.stop_btn = tk.Button(action_row, text="停止任务", width=12, fg="#cc0000",
                                   command=self._stop_tasks, font=("", 9, "bold"))
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        # ===== 3. 调试区 =====
        self.debug_frame = ttk.LabelFrame(root, text="调试", padding=4)
        self.debug_frame.pack(fill=tk.X, pady=(0, 8))
        debug_row = ttk.Frame(self.debug_frame)
        debug_row.pack(fill=tk.X)
        ttk.Label(debug_row, text="公告外点击坐标 X").pack(side=tk.LEFT, padx=(2, 4))
        ttk.Spinbox(debug_row, from_=0, to=1, increment=0.01, textvariable=self.notice_outside_x_var, width=6).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(debug_row, text="Y").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(debug_row, from_=0, to=1, increment=0.01, textvariable=self.notice_outside_y_var, width=6).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(debug_row, text="保存坐标", command=self._save_notice_outside_ratio).pack(side=tk.LEFT, padx=2)

        # 折叠按钮
        self._debug_visible = tk.BooleanVar(value=True)
        self._debug_toggle_btn = ttk.Button(root, text="▾ 调试", width=8,
                                             command=self._toggle_debug)
        self._debug_toggle_btn.pack(anchor="w", pady=(0, 4))

        # ===== 4. 账号列表区（方式一） =====
        self._table_frame_m1 = ttk.LabelFrame(root, text="账号列表（方式一）", padding=2)
        columns = ("level", "bookmark", "window", "passport", "url", "status")
        self.tree = ttk.Treeview(self._table_frame_m1, columns=columns, show="headings", height=10)
        self.tree.heading("level", text="层级")
        self.tree.heading("bookmark", text="收藏编号")
        self.tree.heading("window", text="窗口号")
        self.tree.heading("passport", text="本次通行证")
        self.tree.heading("url", text="链接")
        self.tree.heading("status", text="状态")
        self.tree.column("level", width=70, anchor=tk.CENTER)
        self.tree.column("bookmark", width=70, anchor=tk.CENTER)
        self.tree.column("window", width=65, anchor=tk.CENTER)
        self.tree.column("passport", width=110, anchor=tk.CENTER)
        self.tree.column("url", width=500)
        self.tree.column("status", width=130, anchor=tk.CENTER)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self._table_frame_m1, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.tag_configure("running", foreground="#0066cc")
        self.tree.tag_configure("success", foreground="#008800")
        self.tree.tag_configure("failed", foreground="#cc0000")
        self.tree.tag_configure("retry", foreground="#cc6600")
        self.tree.tag_configure("skip", foreground="#888888")

        # ===== 4b. 账号列表区（方式二） =====
        self._table_frame_m2 = ttk.LabelFrame(root, text="CSV账号列表（方式二）", padding=2)
        csv_columns = ("name", "url", "username", "password_status", "window", "passport", "status")
        self.csv_tree = ttk.Treeview(self._table_frame_m2, columns=csv_columns, show="headings", height=10)
        self.csv_tree.heading("name", text="名称")
        self.csv_tree.heading("url", text="链接")
        self.csv_tree.heading("username", text="账号")
        self.csv_tree.heading("password_status", text="密码")
        self.csv_tree.heading("window", text="窗口号")
        self.csv_tree.heading("passport", text="本次通行证")
        self.csv_tree.heading("status", text="状态")
        self.csv_tree.column("name", width=100)
        self.csv_tree.column("url", width=280)
        self.csv_tree.column("username", width=100, anchor=tk.CENTER)
        self.csv_tree.column("password_status", width=60, anchor=tk.CENTER)
        self.csv_tree.column("window", width=60, anchor=tk.CENTER)
        self.csv_tree.column("passport", width=110, anchor=tk.CENTER)
        self.csv_tree.column("status", width=100, anchor=tk.CENTER)
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

        # ===== 5. 日志区 =====
        log_outer = ttk.LabelFrame(root, text="日志", padding=2)
        log_outer.pack(fill=tk.X, pady=(0, 4))
        log_header = ttk.Frame(log_outer)
        log_header.pack(fill=tk.X, pady=(0, 2))
        ttk.Button(log_header, text="打开日志目录", command=self._open_log_dir).pack(side=tk.RIGHT, padx=2)

        self.log_text = tk.Text(log_outer, height=8, wrap=tk.WORD, font=("Consolas", 9))
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
        if self._debug_visible.get():
            self.debug_frame.pack_forget()
            self._debug_visible.set(False)
            self._debug_toggle_btn.configure(text="▸ 调试")
        else:
            self.debug_frame.pack(fill=tk.X, pady=(0, 8), before=self._debug_toggle_btn)
            self._debug_visible.set(True)
            self._debug_toggle_btn.configure(text="▾ 调试")

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
            self.accounts = load_accounts_from_bookmarks(bookmark_file, root_name, settings.level_names)
            self.status_by_key = {account.key: "未开始" for account in self.accounts}
            self.passport_by_key = {account.key: "" for account in self.accounts}
            self._refresh_table()
            self._refresh_account_choices()
            self._log(f"已从收藏夹读取 {len(self.accounts)} 个账号链接。")
        except Exception as exc:
            messagebox.showerror("读取收藏夹失败", str(exc))
            self._log(f"读取收藏夹失败: {exc}")

    # ===== 方式二：CSV 导入 =====

    def _on_method_changed(self) -> None:
        mode = self.method_var.get()
        is_m1 = (mode == "method1")
        # 方式一控件
        for w in (self._method1_row1, self._method1_bookmark_entry, self._method1_btn_pick,
                  self._method1_btn_load, self._method1_row2a, self._method1_root_entry,
                  self._method1_row3a, self._method1_settings_entry, self._method1_btn_settings):
            w.grid() if is_m1 else w.grid_remove()
        # 方式二控件
        for w in (self._method2_row1, self._method2_csv_entry, self._method2_btn_pick,
                  self._method2_btn_import):
            w.grid() if not is_m1 else w.grid_remove()
        # 表格
        if is_m1:
            self._table_frame_m2.pack_forget()
            self._table_frame_m1.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        else:
            self._table_frame_m1.pack_forget()
            self._table_frame_m2.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
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
                ),
            )

    def _refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for account in self.accounts:
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
                ),
            )

    def _refresh_account_choices(self) -> None:
        choices = [account.display_name for account in filter_accounts(self.accounts, self.level_var.get())]
        self.account_box["values"] = choices
        self.account_var.set(choices[0] if choices else "")

    def _run_selected(self) -> None:
        account = self._selected_account()
        if account is None:
            messagebox.showwarning("未选择账号", "请先读取配置并选择一个账号。")
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
            f"单账号运行: {account.display_name}。"
            f"OCR → 打开游戏页 → 关闭公告 → 通行证 → 输入 → 确认。"
        )
        self._start_serial_run([account])

    def _run_level_serial(self) -> None:
        level = self.level_var.get()
        if level == "全部":
            messagebox.showwarning("请选择层级", "当前层串行需要选择一个具体层级。")
            return
        accounts = [a for a in self.accounts if a.level == level]
        if not accounts:
            messagebox.showwarning("无账号", f"当前层 {level} 没有账号。")
            return
        self._log(f"当前层串行: {level}，共 {len(accounts)} 个账号，严格逐个执行。")
        self._start_serial_run(accounts)

    def _run_all_serial(self) -> None:
        if self.method_var.get() == "method2":
            self._run_method2_all()
            return
        if not self.accounts:
            messagebox.showwarning("无账号", "请先读取收藏夹。")
            return
        self._log(f"全部串行: 共 {len(self.accounts)} 个账号，严格逐个执行。")
        self._start_serial_run(self.accounts)

    # ===== 方式二运行 =====

    def _run_method2_single(self) -> None:
        """方式二：单账号测试（阶段3：只测账号密码登录）"""
        if not self.csv_accounts:
            messagebox.showwarning("无账号", "请先导入CSV文件。")
            return
        # 取 CSV 列表中第一个有效账号
        valid = [a for a in self.csv_accounts if "配置缺失" not in a.status]
        if not valid:
            messagebox.showwarning("无有效账号", "CSV中没有有效的账号。")
            return
        acc = valid[0]
        self._log(f"[方式二] 单账号测试: {acc.display_name}")
        self._start_method2_run(acc)

    def _run_method2_all(self) -> None:
        """方式二：CSV列表串行（阶段5实现）"""
        messagebox.showinfo("提示", "方式二全部串行将在阶段5实现")

    def _start_method2_run(self, csv_account: CSVAccount) -> None:
        """在后台线程执行方式二单账号登录。"""
        if self.worker_thread is not None and self.worker_thread.is_alive():
            messagebox.showwarning("任务进行中", "当前有任务正在执行。")
            return
        self._setup_log_file()
        self.stop_event.clear()
        self.csv_status_by_key[csv_account.key] = "OCR中"
        self._refresh_csv_table()

        def _run():
            try:
                settings = load_settings(self.settings_path.get())
            except Exception as exc:
                self._queue_log(f"[方式二] 读取设置失败: {exc}")
                self._queue_status_csv(csv_account, "失败")
                return
            from .config import AccountConfig as _AC
            runner = AccountRunner(
                account=_AC(level="方式二", bookmark_no=0, game_window_no=csv_account.game_window_no, url=csv_account.url),
                settings=settings,
                stop_event=self.stop_event,
                log=self._queue_log,
                update_status=lambda a, s: self._queue_status_csv(csv_account, s),
                request_passport=lambda a: self._request_passport(a),
            )
            result = runner.run_method2(csv_account)
            self._queue_status_csv(csv_account, "成功" if result else "失败")
            self.ui_queue.put(("status_bar", "就绪"))
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
            values[-1] = status
            tag = ""
            if "成功" in status:
                tag = "success"
            elif "失败" in status:
                tag = "failed"
            elif status not in ("未开始",):
                tag = "running"
            self.csv_tree.item(account.key, values=values, tags=(tag,))

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

    def _start_serial_run(self, accounts: list[AccountConfig]) -> None:
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
        self.worker_thread = threading.Thread(
            target=self._serial_worker,
            args=(accounts, settings),
            daemon=True,
        )
        self.worker_thread.start()

    def _serial_worker(self, accounts: list[AccountConfig], settings) -> None:
        self._setup_log_file()
        self._queue_log(f"前台串行模式：共 {len(accounts)} 个账号，严格逐个执行。")
        self._queue_log("注意：运行期间会短暂移动鼠标，请勿操作。")
        import subprocess as _sp, json, tempfile, os, sys as _sys, time as _time

        frozen = getattr(_sys, "frozen", False)
        success_count = 0
        fail_count = 0
        start_time = _time.time()
        self._update_status_bar(f"运行中：{len(accounts)} 账号")

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
                if flow_result:
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
"""],
                    stdout=_sp.PIPE, stderr=_sp.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    cwd=project_root,
                    creationflags=_sp.CREATE_NO_WINDOW,
                )
                result_seen = False
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("PASSPORT:"):
                        self._queue_passport(account, line[9:])
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
                proc.wait(timeout=300)
                stderr_output = proc.stderr.read()
                for line in stderr_output.splitlines():
                    line = line.strip()
                    if line:
                        self._write_file_log(f"[stderr] {line[:500]}")

                if result_seen:
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
        self._queue_log("--------- 任务完成 ---------")
        self._queue_log(f"总账号: {len(accounts)}  成功: {success_count}  失败: {fail_count}  耗时: {elapsed:.0f}秒")
        self._update_status_bar(f"任务完成：成功{success_count}，失败{fail_count}")
        self._queue_log(f"详细日志: {log_path}")
        if self._log_file is not None:
            self._write_file_log(f"任务完成：总{len(accounts)} 成功{success_count} 失败{fail_count} 耗时{elapsed:.0f}秒")
            self._log_file.close()
            self._log_file = None

    def _stop_tasks(self) -> None:
        self.stop_event.set()
        self._log("已请求停止任务，正在等待当前步骤结束。")
        self._update_status_bar("已停止")

    def _selected_account(self) -> AccountConfig | None:
        display = self.account_var.get()
        for account in self.accounts:
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
        self.after(100, self._drain_ui_queue)

    def _set_status(self, account: AccountConfig, status: str) -> None:
        self.status_by_key[account.key] = status
        if self.tree.exists(account.key):
            values = list(self.tree.item(account.key, "values"))
            values[-1] = status
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
