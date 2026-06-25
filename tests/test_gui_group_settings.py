import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from douluo_launcher.config import AccountConfig
from douluo_launcher.background_login import BackgroundDependencyCheck
from douluo_launcher.gui import (
    ACCOUNT_TABLE_COLUMN_INDEX,
    ACCOUNT_TABLE_COLUMNS,
    RUN_MODE_BACKGROUND_LABEL,
    RUN_MODE_FOREGROUND_LABEL,
    BACKGROUND_SERIAL_CONCURRENCY,
    GUI_DEFAULT_HEIGHT,
    GUI_DEFAULT_WIDTH,
    GUI_MIN_HEIGHT,
    GUI_MIN_WIDTH,
    LOG_PANEL_MIN_HEIGHT,
    LOG_TEXT_VISIBLE_LINES,
    _account_table_values,
    _allowed_level_values_for_accounts,
    _build_serial_run_plan,
    _compact_number_ranges,
    _default_level_for_allowed_values,
    _format_bookmark_file_candidate_label,
    _format_game_program_status,
    _game_program_display_values,
    _game_program_hint_text,
    _is_tkinterdnd2_available,
    _merge_account_group_settings,
    _root_candidate_belongs_to_bookmark_file,
    _run_mode_key_from_label,
    _should_enable_native_game_path_drag_drop,
    _split_all_serial_accounts,
    LauncherApp,
)
from douluo_launcher.config import BookmarkCandidate, BookmarkRootCandidate
from douluo_launcher.path_utils import ResolvedGamePath


class GuiGroupSettingsTests(unittest.TestCase):
    def test_merge_account_group_settings_preserves_existing_and_updates_current_groups(self) -> None:
        existing = {
            "第一层": {"include_in_all": True},
            "存钻": {"include_in_all": False},
            "旧分组": {"include_in_all": True},
        }

        merged = _merge_account_group_settings(
            existing,
            {
                "存钻": True,
                "备用": False,
            },
        )

        self.assertTrue(merged["第一层"]["include_in_all"])
        self.assertTrue(merged["存钻"]["include_in_all"])
        self.assertFalse(merged["备用"]["include_in_all"])
        self.assertTrue(merged["旧分组"]["include_in_all"])

    def test_split_all_serial_accounts_only_enables_include_in_all_groups(self) -> None:
        accounts = [
            AccountConfig("单层账号", 1, 1, "https://example.com/root", include_in_all=False),
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("存钻", 1, 1, "https://example.com/z1", include_in_all=False),
        ]

        enabled, skipped = _split_all_serial_accounts(accounts)

        self.assertEqual([account.level for account in enabled], ["第一层"])
        self.assertEqual([account.level for account in skipped], ["单层账号", "存钻"])

    def test_run_mode_labels_map_to_stable_keys(self) -> None:
        self.assertEqual(_run_mode_key_from_label(RUN_MODE_FOREGROUND_LABEL), "foreground")
        self.assertEqual(_run_mode_key_from_label(RUN_MODE_BACKGROUND_LABEL), "background")
        self.assertEqual(_run_mode_key_from_label("未知"), "foreground")

    def test_background_run_mode_starts_experimental_single_account_runner(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True)
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_BACKGROUND_LABEL),
            wm_tile_mode_var=SimpleNamespace(get=lambda: "固定参数排列"),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            logs=[],
        )
        fake._selected_account = mock.Mock(return_value=account)
        fake._precheck_serial_run = mock.Mock(return_value=True)
        fake._validate_accounts_for_current_mode = mock.Mock(return_value=True)
        fake._start_serial_run = mock.Mock()
        fake._start_background_single_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._run_selected_account(fake)

        fake._start_serial_run.assert_not_called()
        fake._start_background_single_run.assert_called_once_with(account)
        self.assertTrue(any("后台登录模式" in line and "方式一单账号" in line for line in fake.logs))

    def test_background_run_mode_allows_current_level_serial(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("第一层", 2, 2, "https://example.com/l2", include_in_all=True),
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_BACKGROUND_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            logs=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=accounts)
        fake._precheck_serial_run = mock.Mock(return_value=True)
        fake._validate_accounts_for_current_mode = mock.Mock(return_value=True)
        fake._start_serial_run = mock.Mock()
        fake._start_background_serial_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._run_level_serial(fake)

        fake._start_serial_run.assert_not_called()
        fake._start_background_serial_run.assert_called_once_with(accounts, run_label="后台当前层串行")

    def test_background_current_level_serial_with_all_uses_current_all_view(self) -> None:
        enabled = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("第二层", 1, 9, "https://example.com/l2", include_in_all=True),
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_BACKGROUND_LABEL),
            level_var=SimpleNamespace(get=lambda: "全部"),
            logs=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=enabled)
        fake._precheck_serial_run = mock.Mock(return_value=True)
        fake._validate_accounts_for_current_mode = mock.Mock(return_value=True)
        fake._start_serial_run = mock.Mock()
        fake._start_background_serial_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._run_level_serial(fake)

        fake._filtered_accounts_for_ui.assert_called_once()
        fake._start_serial_run.assert_not_called()
        fake._start_background_serial_run.assert_called_once_with(enabled, run_label="后台当前层串行")
        self.assertTrue(any("层级=全部" in line for line in fake.logs))

    def test_background_current_level_serial_specific_unchecked_group_still_runs(self) -> None:
        cunduan = [
            AccountConfig("存钻", index, index, f"https://example.com/z{index}", include_in_all=False)
            for index in range(1, 3)
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_BACKGROUND_LABEL),
            level_var=SimpleNamespace(get=lambda: "存钻"),
            logs=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=cunduan)
        fake._precheck_serial_run = mock.Mock(return_value=True)
        fake._validate_accounts_for_current_mode = mock.Mock(return_value=True)
        fake._start_serial_run = mock.Mock()
        fake._start_background_serial_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._run_level_serial(fake)

        fake._start_serial_run.assert_not_called()
        fake._start_background_serial_run.assert_called_once_with(cunduan, run_label="后台当前层串行")
        self.assertTrue(any("不读取全部串行勾选状态" in line for line in fake.logs))

    def test_background_run_mode_allows_all_serial(self) -> None:
        enabled = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("第二层", 1, 9, "https://example.com/l2", include_in_all=True),
        ]
        disabled = AccountConfig("存钻", 1, 1, "https://example.com/z1", include_in_all=False)
        all_accounts = [enabled[0], disabled, enabled[1]]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_BACKGROUND_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            logs=[],
        )
        fake._mode_allowed_accounts = mock.Mock(return_value=all_accounts)
        fake._precheck_serial_run = mock.Mock(return_value=True)
        fake._validate_accounts_for_current_mode = mock.Mock(return_value=True)
        fake._account_group_counts = lambda accounts: [("第一层", 1), ("第二层", 1)]
        fake._account_count_summary = lambda accounts: "第一层 1 个，第二层 1 个"
        fake._start_serial_run = mock.Mock()
        fake._start_background_serial_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._run_all_serial(fake)

        fake._start_serial_run.assert_not_called()
        fake._start_background_serial_run.assert_called_once_with(enabled, run_label="后台全部串行")

    def test_background_run_mode_blocks_method2_single(self) -> None:
        fake = SimpleNamespace(
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_BACKGROUND_LABEL),
            csv_accounts=[object()],
        )
        fake._block_background_unsupported_action = mock.Mock(return_value=True)
        fake._selected_csv_account = mock.Mock()

        LauncherApp._run_method2_single(fake)

        fake._block_background_unsupported_action.assert_called_once_with("方式二")
        fake._selected_csv_account.assert_not_called()

    def test_background_unsupported_action_uses_required_prompt(self) -> None:
        fake = SimpleNamespace(
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_BACKGROUND_LABEL),
            logs=[],
        )
        fake._is_background_run_mode = lambda: True
        fake._log = lambda message: fake.logs.append(message)

        with mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning:
            blocked = LauncherApp._block_background_unsupported_action(fake, "方式二")

        self.assertTrue(blocked)
        warning.assert_called_once_with(
            "后台模式限制",
            "后台模式当前支持方式一单账号、当前层串行、全部串行；方式二未接入",
        )
        self.assertEqual(
            fake.logs,
            ["阻止方式二：后台模式当前支持方式一单账号、当前层串行、全部串行；方式二未接入"],
        )

    def test_background_serial_worker_calls_single_runner_in_table_order_and_continues_after_failure(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("第一层", 2, 2, "https://example.com/l2", include_in_all=True),
            AccountConfig("第一层", 3, 3, "https://example.com/l3", include_in_all=True),
        ]
        calls: list[int] = []
        max_active = 0
        active = 0

        class FakeRunner:
            def __init__(self, account, settings, stop_event, log, update_status, passport_found):
                self.account = account
                self.update_status = update_status
                self.passport_found = passport_found

            def run(self) -> bool:
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                calls.append(self.account.game_window_no)
                if self.account.game_window_no == 1:
                    self.passport_found(self.account, "fd829a15")
                    self.update_status(self.account, "成功")
                    active -= 1
                    return True
                if self.account.game_window_no == 2:
                    self.update_status(self.account, "失败")
                    active -= 1
                    return False
                self.update_status(self.account, "已进入游戏，跳过")
                active -= 1
                return True

        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            ui_queue=SimpleNamespace(put=lambda _item: None),
            timing_by_key={},
            passports=[],
            statuses=[],
            logs=[],
            file_logs=[],
            bars=[],
            _log_file=None,
            _log_file_path=None,
        )
        fake._queue_status = lambda account, status: fake.statuses.append((account.game_window_no, status))
        fake._queue_passport = lambda account, passport: fake.passports.append((account.game_window_no, passport))
        fake._queue_timing = lambda account, seconds: None
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_log_file = lambda message: fake.file_logs.append(message)
        fake._update_status_bar = lambda message: fake.bars.append(message)
        fake._write_file_log = lambda message: fake.file_logs.append(message)

        with mock.patch("douluo_launcher.gui.BackgroundSingleAccountRunner", FakeRunner):
            LauncherApp._background_serial_worker(fake, accounts, object(), "后台当前层串行")

        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual(max_active, BACKGROUND_SERIAL_CONCURRENCY)
        self.assertEqual(fake.passports, [(1, "fd829a15")])
        self.assertIn((2, "失败"), fake.statuses)
        self.assertIn((3, "已进入游戏，跳过"), fake.statuses)
        self.assertTrue(any("后台当前层串行完成：成功1，跳过1，失败1，已停止0" in line for line in fake.logs))

    def test_background_serial_worker_marks_remaining_accounts_stopped(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("第一层", 2, 2, "https://example.com/l2", include_in_all=True),
            AccountConfig("第一层", 3, 3, "https://example.com/l3", include_in_all=True),
        ]
        stop_state = {"stopped": False}
        calls: list[int] = []

        class FakeRunner:
            def __init__(self, account, settings, stop_event, log, update_status, passport_found):
                self.account = account
                self.update_status = update_status

            def run(self) -> bool:
                calls.append(self.account.game_window_no)
                stop_state["stopped"] = True
                self.update_status(self.account, "已停止")
                return False

        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: stop_state["stopped"]),
            ui_queue=SimpleNamespace(put=lambda _item: None),
            timing_by_key={},
            statuses=[],
            logs=[],
            file_logs=[],
            bars=[],
            _log_file=None,
            _log_file_path=None,
        )
        fake._queue_status = lambda account, status: fake.statuses.append((account.game_window_no, status))
        fake._queue_passport = lambda account, passport: None
        fake._queue_timing = lambda account, seconds: None
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_log_file = lambda message: fake.file_logs.append(message)
        fake._update_status_bar = lambda message: fake.bars.append(message)
        fake._write_file_log = lambda message: fake.file_logs.append(message)

        with mock.patch("douluo_launcher.gui.BackgroundSingleAccountRunner", FakeRunner):
            LauncherApp._background_serial_worker(fake, accounts, object(), "后台当前层串行")

        self.assertEqual(calls, [1])
        self.assertEqual(fake.statuses.count((1, "已停止")), 1)
        self.assertIn((2, "已停止"), fake.statuses)
        self.assertIn((3, "已停止"), fake.statuses)
        self.assertTrue(any("后台串行已停止。" in line for line in fake.logs))

    def test_background_serial_source_does_not_use_foreground_or_global_input(self) -> None:
        source = inspect.getsource(LauncherApp._background_serial_worker)

        for forbidden in (
            "SetForegroundWindow",
            "SetCursorPos",
            "mouse_event",
            "keybd_event",
            "ThreadPoolExecutor",
            "ProcessPoolExecutor",
            "_run_account_child_process",
            "taskkill",
        ):
            self.assertNotIn(forbidden, source)

    def test_stop_tasks_preserves_background_windows(self) -> None:
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(set=mock.Mock()),
            logs=[],
            bars=[],
            _preserve_background_windows=True,
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._terminate_running_processes = mock.Mock(return_value=0)
        fake._cleanup_external_processes = mock.Mock()
        fake._update_status_bar = lambda message: fake.bars.append(message)

        LauncherApp._stop_tasks(fake)

        fake.stop_event.set.assert_called_once()
        fake._terminate_running_processes.assert_called_once()
        fake._cleanup_external_processes.assert_not_called()
        self.assertTrue(any("保留已打开窗口" in line for line in fake.logs))

    def test_background_single_run_missing_cv2_dependency_does_not_start_worker(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True)
        fake = SimpleNamespace(
            worker_thread=None,
            logs=[],
            statuses=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda _account, status: fake.statuses.append(status)
        fake._setup_log_file = mock.Mock()

        dependency_check = BackgroundDependencyCheck(
            ok=False,
            missing_modules=("cv2",),
            python_executable=r"D:\Dev\Python\Python314\python.exe",
            python_bits=64,
            install_commands=("py -3.14-32 -m pip install opencv-python",),
        )
        with mock.patch(
            "douluo_launcher.gui.check_background_runtime_dependencies",
            return_value=dependency_check,
        ), mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning:
            LauncherApp._start_background_single_run(fake, account)

        self.assertIsNone(fake.worker_thread)
        self.assertEqual(fake.statuses, ["依赖缺失"])
        fake._setup_log_file.assert_called_once_with(cleanup_old=False)
        warning.assert_called_once_with(
            "后台模式依赖缺失",
            "当前 Python 环境缺少依赖：cv2\n请执行：py -3.14-32 -m pip install opencv-python",
        )
        self.assertTrue(any(r"D:\Dev\Python\Python314\python.exe" in line for line in fake.logs))
        self.assertTrue(any("Python 位数=64" in line for line in fake.logs))
        self.assertTrue(any("缺失模块=cv2" in line for line in fake.logs))

    def test_all_level_ui_scope_only_contains_include_in_all_accounts(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("第二层", 1, 9, "https://example.com/l2", include_in_all=True),
            AccountConfig("存钻", 1, 1, "https://example.com/z1", include_in_all=False),
        ]
        fake = SimpleNamespace(
            _mode_allowed_accounts=lambda: accounts,
            level_var=SimpleNamespace(get=lambda: "全部"),
        )

        filtered = LauncherApp._filtered_accounts_for_ui(fake)

        self.assertEqual([account.level for account in filtered], ["第一层", "第二层"])

    def test_specific_level_ui_scope_ignores_include_in_all(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("存钻", 1, 1, "https://example.com/z1", include_in_all=False),
        ]
        fake = SimpleNamespace(
            _mode_allowed_accounts=lambda: accounts,
            level_var=SimpleNamespace(get=lambda: "存钻"),
        )

        filtered = LauncherApp._filtered_accounts_for_ui(fake)

        self.assertEqual([account.level for account in filtered], ["存钻"])

    def test_current_level_serial_with_all_runs_filtered_all_scope(self) -> None:
        enabled = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("第二层", 1, 9, "https://example.com/l2", include_in_all=True),
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            level_var=SimpleNamespace(get=lambda: "全部"),
            logs=[],
        )
        fake._block_background_unsupported_action = mock.Mock(return_value=False)
        fake._filtered_accounts_for_ui = mock.Mock(return_value=enabled)
        fake._precheck_serial_run = mock.Mock(return_value=True)
        fake._validate_accounts_for_current_mode = mock.Mock(return_value=True)
        fake._start_serial_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._run_level_serial(fake)

        fake._start_serial_run.assert_called_once_with(enabled, batch_fast=True)
        self.assertTrue(any("当前层串行范围确认" in line for line in fake.logs))

    def test_current_level_serial_specific_unchecked_group_still_runs(self) -> None:
        cunduan = [
            AccountConfig("存钻", index, index, f"https://example.com/z{index}", include_in_all=False)
            for index in range(1, 3)
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            level_var=SimpleNamespace(get=lambda: "存钻"),
            logs=[],
        )
        fake._block_background_unsupported_action = mock.Mock(return_value=False)
        fake._filtered_accounts_for_ui = mock.Mock(return_value=cunduan)
        fake._precheck_serial_run = mock.Mock(return_value=True)
        fake._validate_accounts_for_current_mode = mock.Mock(return_value=True)
        fake._start_serial_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._run_level_serial(fake)

        fake._start_serial_run.assert_called_once_with(cunduan, batch_fast=True)

    def test_all_level_empty_scope_logs_no_checked_accounts(self) -> None:
        fake = SimpleNamespace(
            _mode_allowed_accounts=lambda: [
                AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=False),
            ],
            level_var=SimpleNamespace(get=lambda: "全部"),
        )

        self.assertEqual(LauncherApp._filtered_accounts_for_ui(fake), [])

    def test_main_window_dimensions_are_explicit_layout_constants(self) -> None:
        self.assertEqual((GUI_DEFAULT_WIDTH, GUI_DEFAULT_HEIGHT), (1160, 820))
        self.assertEqual((GUI_MIN_WIDTH, GUI_MIN_HEIGHT), (1080, 760))
        source = inspect.getsource(LauncherApp.__init__)

        self.assertIn("GUI_DEFAULT_WIDTH", source)
        self.assertIn("GUI_DEFAULT_HEIGHT", source)
        self.assertIn("self.minsize(GUI_MIN_WIDTH, GUI_MIN_HEIGHT)", source)

    def test_log_panel_keeps_minimum_height_and_visible_lines(self) -> None:
        self.assertEqual(LOG_TEXT_VISIBLE_LINES, 8)
        self.assertGreaterEqual(LOG_PANEL_MIN_HEIGHT, 160)
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertIn("self._log_outer.configure(height=LOG_PANEL_MIN_HEIGHT)", source)
        self.assertIn("self._log_outer.pack_propagate(False)", source)
        self.assertIn("height=LOG_TEXT_VISIBLE_LINES", source)

    def test_log_directory_button_stays_in_log_header_right_side(self) -> None:
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertIn('text="打开日志目录"', source)
        self.assertIn("pack(side=tk.RIGHT", source)

    def test_log_append_scrolls_to_bottom(self) -> None:
        source = inspect.getsource(LauncherApp._log)

        self.assertIn("self.log_text.insert(tk.END", source)
        self.assertIn("self.log_text.see(tk.END)", source)

    def test_account_table_values_match_declared_column_order(self) -> None:
        account = AccountConfig(
            "存钻",
            3,
            3,
            "https://example.com/passport",
            bookmark_title="Z3",
            include_in_all=False,
        )

        values = _account_table_values(account, passport="d40786fa", status="成功", timing="8.1s")

        self.assertEqual(len(values), len(ACCOUNT_TABLE_COLUMNS))
        self.assertEqual(values[ACCOUNT_TABLE_COLUMN_INDEX["include_in_all"]], "否")
        self.assertEqual(values[ACCOUNT_TABLE_COLUMN_INDEX["passport"]], "d40786fa")
        self.assertEqual(values[ACCOUNT_TABLE_COLUMN_INDEX["status"]], "成功")
        self.assertEqual(values[ACCOUNT_TABLE_COLUMN_INDEX["timing"]], "8.1s")

    def test_bookmark_file_candidate_label_hides_raw_path(self) -> None:
        candidate = BookmarkCandidate(
            "Edge",
            "Default",
            r"C:\Users\Someone\AppData\Local\Microsoft\Edge\User Data\Default\Bookmarks",
        )

        label = _format_bookmark_file_candidate_label(candidate, root_count=3)

        self.assertEqual(label, "Edge - Default - 发现 3 个账号目录")
        self.assertNotIn("C:\\Users", label)
        self.assertNotIn("Bookmarks", label)

    def test_game_program_status_uses_customer_text(self) -> None:
        self.assertEqual(
            _format_game_program_status(r"E:\Program Files\DLH5\X5Game.exe"),
            r"已识别游戏程序：E:\Program Files\DLH5\X5Game.exe",
        )
        self.assertEqual(
            _format_game_program_status(""),
            "未选择游戏程序",
        )

    def test_game_program_input_and_status_share_same_saved_path(self) -> None:
        entry_value, status_text = _game_program_display_values(r"E:\Program Files\DLH5\X5Game.exe")

        self.assertEqual(entry_value, r"E:\Program Files\DLH5\X5Game.exe")
        self.assertEqual(status_text, r"已识别游戏程序：E:\Program Files\DLH5\X5Game.exe")

    def test_game_program_empty_path_has_empty_input_and_unselected_status(self) -> None:
        entry_value, status_text = _game_program_display_values("")

        self.assertEqual(entry_value, "")
        self.assertEqual(status_text, "未选择游戏程序")

    def test_button_label_does_not_claim_drag_when_drag_is_not_guaranteed(self) -> None:
        self.assertNotIn(
            "拖入",
            _format_game_program_status(""),
        )

    def test_raw_native_game_path_drag_drop_is_disabled_to_avoid_tk_crash(self) -> None:
        self.assertFalse(_should_enable_native_game_path_drag_drop())

    def test_game_program_hint_reflects_tkinterdnd2_drag_support(self) -> None:
        hint = _game_program_hint_text()
        if _is_tkinterdnd2_available():
            self.assertIn("可拖入桌面游戏图标", hint)
            self.assertIn("X5Game.exe", hint)
        else:
            self.assertNotIn("可拖入", hint)

    def test_apply_game_path_input_saves_resolved_exe_not_lnk(self) -> None:
        values = {}
        fake = SimpleNamespace(
            wm_game_path_var=SimpleNamespace(
                set=lambda value: values.__setitem__("entry", value),
                get=lambda: values.get("entry", ""),
            ),
            wm_game_status_var=SimpleNamespace(set=lambda value: values.__setitem__("status", value)),
            logs=[],
        )
        fake._set_game_program_path = lambda value: (
            values.__setitem__("entry", value),
            values.__setitem__("status", f"已识别游戏程序：{value}"),
        )
        fake._save_window_manager_settings = mock.Mock(return_value=True)
        fake._log = lambda message: fake.logs.append(message)

        with mock.patch(
            "douluo_launcher.gui.resolve_game_executable_path",
            return_value=ResolvedGamePath(
                path=r"E:\Program Files\DLH5\X5Game.exe",
                source="shortcut",
                message=r"已解析快捷方式：斗罗大陆.lnk -> E:\Program Files\DLH5\X5Game.exe",
            ),
        ):
            result = LauncherApp._apply_game_path_input(fake, r"C:\Users\Desktop\斗罗大陆.lnk")

        self.assertTrue(result)
        self.assertEqual(values["entry"], r"E:\Program Files\DLH5\X5Game.exe")
        self.assertNotEqual(values["entry"], r"C:\Users\Desktop\斗罗大陆.lnk")
        fake._save_window_manager_settings.assert_called_once()

    def test_game_path_drop_uses_first_dropped_path_and_drop_source(self) -> None:
        fake = SimpleNamespace(
            tk=SimpleNamespace(splitlist=lambda text: (r"C:\桌面\斗罗大陆.lnk", r"D:\Other\X5Game.exe")),
            logs=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._apply_game_path_input = mock.Mock(return_value=True)
        event = SimpleNamespace(data=r"{C:\桌面\斗罗大陆.lnk} {D:\Other\X5Game.exe}", action="copy")

        result = LauncherApp._on_game_path_drop(fake, event)

        self.assertEqual(result, "copy")
        fake._apply_game_path_input.assert_called_once_with(r"C:\桌面\斗罗大陆.lnk", source="drop")

    def test_drop_invalid_file_uses_drag_wording(self) -> None:
        fake = SimpleNamespace(logs=[])
        fake._log = lambda message: fake.logs.append(message)
        fake._set_game_program_path = mock.Mock()
        fake._save_window_manager_settings = mock.Mock()

        with mock.patch(
            "douluo_launcher.gui.resolve_game_executable_path",
            side_effect=ValueError("请选择游戏程序 exe、游戏快捷方式或游戏安装目录。"),
        ), mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning:
            result = LauncherApp._apply_game_path_input(fake, r"C:\bad.txt", source="drop")

        self.assertFalse(result)
        self.assertIn("请拖入游戏程序 exe", warning.call_args.args[1])
        fake._save_window_manager_settings.assert_not_called()

    def test_empty_accounts_do_not_show_hardcoded_first_layer(self) -> None:
        self.assertEqual(_allowed_level_values_for_accounts([]), ("未读取",))

    def test_single_loaded_group_defaults_to_that_group(self) -> None:
        accounts = [
            AccountConfig("存钻", index, index, f"https://example.com/z{index}", bookmark_title=f"z{index}")
            for index in range(1, 10)
        ]

        allowed = _allowed_level_values_for_accounts(accounts)
        selected = _default_level_for_allowed_values("第一层", allowed)

        self.assertEqual(allowed, ("全部", "存钻"))
        self.assertEqual(selected, "存钻")

    def test_bookmark_root_candidate_must_belong_to_current_bookmark_file(self) -> None:
        candidate = BookmarkRootCandidate(
            bookmark_file=r"C:\Edge\User Data\Default\Bookmarks",
            browser="Edge",
            profile="Default",
            root_path="roots/bookmark_bar/children/0",
            display_name="收藏栏 / 账号 / 存钻",
            link_count=9,
            child_group_count=0,
            order=1,
        )

        self.assertTrue(
            _root_candidate_belongs_to_bookmark_file(candidate, r"C:\Edge\User Data\Default\Bookmarks")
        )
        self.assertFalse(
            _root_candidate_belongs_to_bookmark_file(candidate, r"C:\Chrome\User Data\Default\Bookmarks")
        )

    def test_current_group_plan_for_cunduan_uses_windows_1_to_9_only(self) -> None:
        accounts = [
            AccountConfig("存钻", index, index, f"https://example.com/z{index}", bookmark_title=f"z{index}")
            for index in range(1, 10)
        ]

        plan = _build_serial_run_plan(accounts, visible_window_numbers=list(range(1, 10)))

        self.assertEqual(plan.group_counts, (("存钻", 9),))
        self.assertEqual(plan.required_windows, tuple(range(1, 10)))
        self.assertEqual(plan.max_window_no, 9)
        self.assertEqual(plan.missing_windows, ())

    def test_all_serial_plan_reports_all_missing_windows_before_running(self) -> None:
        accounts = [
            AccountConfig("单层账号", index, index, f"https://example.com/root{index}", include_in_all=True)
            for index in range(1, 10)
        ] + [
            AccountConfig("第一层", index, 9 + index, f"https://example.com/l1-{index}", include_in_all=True)
            for index in range(1, 9)
        ] + [
            AccountConfig("第二层", index, 17 + index, f"https://example.com/l2-{index}", include_in_all=True)
            for index in range(1, 9)
        ] + [
            AccountConfig("第三层", index, 25 + index, f"https://example.com/l3-{index}", include_in_all=True)
            for index in range(1, 9)
        ] + [
            AccountConfig("第四层", index, 33 + index, f"https://example.com/l4-{index}", include_in_all=True)
            for index in range(1, 8)
        ] + [
            AccountConfig("存钻", index, 40 + index, f"https://example.com/z{index}", include_in_all=True)
            for index in range(1, 10)
        ]

        enabled, _skipped = _split_all_serial_accounts(accounts)
        plan = _build_serial_run_plan(enabled, visible_window_numbers=list(range(1, 10)))

        self.assertEqual(plan.max_window_no, 49)
        self.assertEqual(_compact_number_ranges(plan.required_windows), "1-49")
        self.assertEqual(_compact_number_ranges(plan.visible_windows), "1-9")
        self.assertEqual(_compact_number_ranges(plan.missing_windows), "10-49")


if __name__ == "__main__":
    unittest.main()
