import inspect
import threading
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import douluo_launcher.gui as gui_module
from douluo_launcher.config import AccountConfig
from douluo_launcher.client_direct_login import ClientDirectRunRecord
from douluo_launcher.client_batch_store import ClientBatchBinding, ClientBatchStore
from douluo_launcher.background_login import BackgroundDependencyCheck, BackgroundLoginResult
from douluo_launcher.gui import (
    ACCOUNT_TABLE_COLUMN_INDEX,
    ACCOUNT_TABLE_COLUMNS,
    RUN_MODE_BACKGROUND_LABEL,
    RUN_MODE_CLIENT_DIRECT_LABEL,
    RUN_MODE_FOREGROUND_LABEL,
    BACKGROUND_SERIAL_CONCURRENCY,
    CLIENT_DIRECT_LOGIN_SCOPE_PENDING,
    GUI_DEFAULT_HEIGHT,
    GUI_DEFAULT_WIDTH,
    GUI_MIN_HEIGHT,
    GUI_MIN_WIDTH,
    LOG_PANEL_MIN_HEIGHT,
    LOG_PANEL_COLLAPSED_HEIGHT,
    LOG_PANEL_EXPANDED_HEIGHT,
    LOG_TEXT_VISIBLE_LINES,
    _account_url_display_value,
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
from douluo_launcher.window_manager import TileConfig, WindowRect


class GuiGroupSettingsTests(unittest.TestCase):
    def test_work_mode_choices_only_include_client_direct_and_foreground(self) -> None:
        self.assertEqual(
            gui_module.RUN_MODE_CHOICES,
            (RUN_MODE_CLIENT_DIRECT_LABEL, RUN_MODE_FOREGROUND_LABEL),
        )
        self.assertNotIn(RUN_MODE_BACKGROUND_LABEL, gui_module.RUN_MODE_CHOICES)
        source = inspect.getsource(LauncherApp._build_widgets)
        self.assertIn("text=\"工作模式\"", source)
        self.assertIn("indicatoron=False", source)
        self.assertIn("self.run_mode_client_btn", source)
        self.assertIn("self.run_mode_foreground_btn", source)
        self.assertNotIn("self.run_mode_box = ttk.Combobox", source)
        self.assertLess(
            source.index('text="工作模式"'),
            source.index('text="读取收藏夹 / 账号配置"'),
        )

    def test_window_manager_layout_uses_aligned_sections(self) -> None:
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertIn('text="游戏程序："', source)
        self.assertIn('self.wm_game_path_row', source)
        self.assertIn('self.wm_compact_frame', source)
        self.assertIn('text="提示："', source)
        self.assertIn('text="布局参数："', source)
        self.assertIn('text="标题设置："', source)
        self.assertIn('text="窗口操作："', source)
        self.assertIn('self.wm_legacy_launch_frame', source)

    def test_account_table_height_shows_rows_not_only_header(self) -> None:
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertIn('text="读取收藏夹 / 账号配置"', source)
        self.assertIn('text="账号范围用于决定本批客户端数量和登录账号。"', source)
        self.assertIn('text="账号列表 / 当前账号来源"', source)
        self.assertIn("height=10", source)

    def test_client_direct_actions_are_split_into_two_rows(self) -> None:
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertIn("client_direct_buttons = (", source)
        self.assertIn('("准备客户端", 14, self._prepare_client_direct_current_scope, 0, 0)', source)
        self.assertIn('("执行客户端登录", 16, self._login_prepared_client_direct_current_scope, 0, 4)', source)
        self.assertIn('("修复本批窗口", 14, self._repair_client_direct_current_batch, 0, 0)', source)
        self.assertIn('("关闭本批客户端", 14, self._close_client_direct_current_batch, 0, 2)', source)
        self.assertIn("self.client_direct_stop_btn.grid(row=0, column=3", source)
        self.assertNotIn('"重命名批次"', source)

    def test_client_direct_batch_area_removes_manual_name_and_main_port_inputs(self) -> None:
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertNotIn('text="批次名称"', source)
        self.assertNotIn("textvariable=self.client_direct_batch_name_var", source)
        self.assertNotIn('text="起始端口"', source)
        self.assertIn('text="并发数："', source)
        self.assertIn("self.client_direct_concurrency_spin", source)
        self.assertIn('text="预计端口范围："', source)
        self.assertIn('textvariable=self.client_direct_batch_count_var', source)
        self.assertIn("self.client_direct_top_row", source)
        self.assertIn("self.client_direct_batch_row", source)
        self.assertIn("self.client_direct_action_row_1", source)
        self.assertIn("self.client_direct_action_row_2", source)
        self.assertIn('text="删除当前批次"', source)
        self.assertIn('text="清理失效批次"', source)

    def test_client_direct_batch_area_uses_compact_horizontal_rows(self) -> None:
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertNotIn("self.client_direct_batch_panel.grid(row=0, column=1", source)
        self.assertIn('text="当前批次："', source)
        self.assertIn('text="状态统计："', source)
        self.assertIn("textvariable=self.client_direct_batch_status_var", source)
        self.assertIn("self.client_direct_delete_batch_btn", source)
        self.assertIn("self.client_direct_cleanup_batches_btn", source)

    def test_client_direct_port_setting_lives_in_advanced_config(self) -> None:
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertIn('text="端口设置"', source)
        self.assertIn("self.client_direct_base_port_spin", source)
        self.assertIn("self._method1_advanced_frame", source)

    def test_client_speed_panel_settings_live_in_advanced_config(self) -> None:
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertIn('text="加速面板"', source)
        self.assertIn('text="替换网页加速浮层"', source)
        self.assertIn('text="显示自定义变速器"', source)
        self.assertIn('text="原浮层诊断日志"', source)
        self.assertIn('text="删除原入口按钮"', source)
        self.assertIn("self.default_speed_rate_var", source)
        self.assertIn("self.speed_panel_position_var", source)
        self.assertIn("self._method1_advanced_frame", source)

    def test_client_speed_panel_options_default_rate_falls_back_to_one(self) -> None:
        class Var:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        fake = SimpleNamespace(
            auto_replace_speed_panel_var=Var(True),
            custom_speed_panel_enabled_var=Var(False),
            speed_panel_debug_var=Var(True),
            speed_panel_remove_original_toggle_var=Var(False),
            default_speed_rate_var=Var("-5"),
        )

        options = LauncherApp._client_speed_panel_options(fake)

        self.assertTrue(options["auto_replace_speed_panel"])
        self.assertFalse(options["custom_speed_panel_enabled"])
        self.assertEqual(options["default_speed_rate"], 1.0)
        self.assertEqual(options["speed_engine"], "timer_hook")
        self.assertEqual(options["speed_hook_stage"], "after_game_ready")
        self.assertTrue(options["speed_panel_debug"])
        self.assertFalse(options["speed_panel_remove_original_toggle"])
        self.assertEqual(fake.default_speed_rate_var.value, "1.0")

    def test_client_direct_batch_dropdown_uses_summary_without_extra_status_label(self) -> None:
        store = ClientBatchStore()
        batch = store.create_batch("全部-2号", scope="全部串行", base_port=9222)
        store.append_binding(ClientBatchBinding("a1", "账号1", pid=1, hwnd=11, cdp_port=9222, login_url="https://example.com/a1"))
        store.append_binding(
            ClientBatchBinding("a2", "账号2", pid=0, hwnd=0, cdp_port=9223, login_url="https://example.com/a2", status="pid_missing")
        )
        fake = SimpleNamespace(client_batch_store=store)

        display = LauncherApp._client_direct_batch_display(fake, batch)

        self.assertEqual(display, "全部-2号 | 绑定2 | 存活1 | 端口9222~9223")

    def test_client_direct_empty_batch_status_disables_delete_button(self) -> None:
        states: list[str] = []
        fake = SimpleNamespace(
            client_batch_store=ClientBatchStore(),
            client_direct_batch_status_var=SimpleNamespace(set=lambda value: states.append(value)),
            client_direct_batch_select_var=SimpleNamespace(set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
            client_direct_delete_batch_btn=SimpleNamespace(configure=lambda **kwargs: states.append(kwargs["state"])),
        )

        LauncherApp._sync_client_direct_batch_status(fake)

        self.assertIn("绑定=0 | 存活=0 | 已关闭=0 | CDP不可用=0 | 窗口失效=0", states[0])
        self.assertIn("disabled", states)

    def test_client_direct_auto_batch_name_uses_scope_count_and_deduplicates(self) -> None:
        store = ClientBatchStore()
        store.create_batch("全部-2号", scope="全部串行", base_port=9222)
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/a1", include_in_all=True),
            AccountConfig("第二层", 1, 2, "https://example.com/a2", include_in_all=True),
        ]
        fake = SimpleNamespace(
            client_batch_store=store,
            level_var=SimpleNamespace(get=lambda: "全部"),
            logs=[],
        )
        fake._log = lambda message: fake.logs.append(message)

        name = LauncherApp._client_direct_auto_batch_name(fake, accounts)

        self.assertEqual(name, "全部-2号-2")

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
        self.assertEqual(_run_mode_key_from_label(RUN_MODE_CLIENT_DIRECT_LABEL), "client_direct")
        self.assertEqual(_run_mode_key_from_label("未知"), "foreground")

    def test_client_direct_auto_enter_reads_boolean_var(self) -> None:
        fake = SimpleNamespace(client_direct_auto_enter_var=SimpleNamespace(get=lambda: True))
        self.assertTrue(LauncherApp._client_direct_auto_enter_game(fake))

        fake.client_direct_auto_enter_var = SimpleNamespace(get=lambda: False)
        self.assertFalse(LauncherApp._client_direct_auto_enter_game(fake))

    def test_client_direct_concurrency_defaults_to_one_and_clamps_to_eight(self) -> None:
        class Var:
            def __init__(self, value) -> None:
                self.value = value

            def get(self):
                return self.value

            def set(self, value) -> None:
                self.value = value

        self.assertEqual(LauncherApp._client_direct_concurrency(SimpleNamespace()), 1)

        high = SimpleNamespace(client_direct_concurrency_var=Var(31))
        self.assertEqual(LauncherApp._client_direct_concurrency(high), 8)
        self.assertEqual(high.client_direct_concurrency_var.value, 8)

        low = SimpleNamespace(client_direct_concurrency_var=Var(0))
        self.assertEqual(LauncherApp._client_direct_concurrency(low), 1)
        self.assertEqual(low.client_direct_concurrency_var.value, 1)

    def test_bounded_client_direct_task_runner_honors_concurrency_limit(self) -> None:
        active = 0
        max_seen = 0
        lock = threading.Lock()

        def worker(value: int) -> int:
            nonlocal active, max_seen
            with lock:
                active += 1
                max_seen = max(max_seen, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return value

        results = list(gui_module._run_bounded_client_direct_tasks([1, 2, 3, 4, 5], 2, worker))

        self.assertEqual(sorted(results), [1, 2, 3, 4, 5])
        self.assertLessEqual(max_seen, 2)

    def test_live_current_batch_prepare_asks_to_create_new_batch_and_preserves_old_batch(self) -> None:
        accounts = [
            AccountConfig(
                "全部",
                index,
                index,
                "https://dldl.50pk.com/login.php?gid=1&pid=1&token=t&time=1&sign=s&isPcLauncher=true",
            )
            for index in range(1, 32)
        ]
        store = ClientBatchStore()
        old_batch = store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        for offset in range(9):
            store.append_binding(
                ClientBatchBinding(
                    f"单层账号-{offset + 1}",
                    f"单层账号-{offset + 1}",
                    pid=1000 + offset,
                    hwnd=2000 + offset,
                    cdp_port=9222 + offset,
                    login_url="u",
                    status="restored",
                )
            )
        fake = SimpleNamespace(client_batch_store=store, logs=[])
        fake._ensure_client_direct_selected_batch_current = lambda: None
        fake._refresh_client_direct_sessions_for_precheck = lambda: set(range(9222, 9231))
        fake._log = lambda message: fake.logs.append(message)

        with (
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch("douluo_launcher.gui.messagebox.askyesno", return_value=True) as askyesno,
        ):
            result = LauncherApp._confirm_client_direct_new_batch_if_live(fake, accounts, "准备客户端")

        self.assertTrue(result)
        askyesno.assert_called_once()
        self.assertIn("已有 9 个存活客户端", askyesno.call_args.args[1])
        self.assertEqual([batch.batch_id for batch in store.batches], [old_batch.batch_id])
        self.assertEqual(len(store.current_batch().bindings), 9)

    def test_cancel_new_client_direct_batch_keeps_old_batch_and_blocks_prepare(self) -> None:
        accounts = [
            AccountConfig(
                "第一层",
                1,
                1,
                "https://dldl.50pk.com/login.php?gid=1&pid=1&token=t&time=1&sign=s&isPcLauncher=true",
            )
        ]
        store = ClientBatchStore()
        old_batch = store.create_batch("第一层-1号", scope="当前层:第一层", base_port=9222)
        store.append_binding(
            ClientBatchBinding("第一层-1", "第一层-1", pid=100, hwnd=200, cdp_port=9222, login_url="u", status="restored")
        )
        fake = SimpleNamespace(client_batch_store=store, logs=[])
        fake._ensure_client_direct_selected_batch_current = lambda: None
        fake._refresh_client_direct_sessions_for_precheck = lambda: {9222}
        fake._log = lambda message: fake.logs.append(message)

        with (
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch("douluo_launcher.gui.messagebox.askyesno", return_value=False),
        ):
            result = LauncherApp._confirm_client_direct_new_batch_if_live(fake, accounts, "一键准备并登录")

        self.assertFalse(result)
        self.assertEqual(store.active_batch_id, old_batch.batch_id)
        self.assertEqual(len(store.batches), 1)
        self.assertEqual(len(store.current_batch().bindings), 1)

    def test_one_click_prepare_starts_without_normal_confirmation(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://dldl.50pk.com/login.php?gid=1&pid=1&token=t&time=1&sign=s&isPcLauncher=true",
        )
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            client_direct_batch_name_var=SimpleNamespace(get=lambda: "测试批次"),
            client_direct_base_port_var=SimpleNamespace(get=lambda: 9222),
            client_direct_auto_enter_var=SimpleNamespace(get=lambda: True),
            after=lambda *_args: None,
            logs=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=[account])
        fake._precheck_client_direct_prepare_ports = mock.Mock(return_value=True)
        fake._continue_client_direct_one_click_after_prepare = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        with mock.patch("douluo_launcher.gui.messagebox.askyesno") as askyesno, mock.patch.object(
            LauncherApp,
            "_start_client_direct_prepare_run",
            return_value=True,
        ) as start_prepare:
            LauncherApp._prepare_arrange_login_client_direct_current_scope(fake)

        askyesno.assert_not_called()
        start_prepare.assert_called_once()
        self.assertTrue(any("auto_enter_game=true" in line for line in fake.logs))

    def test_port_recommendation_auto_switches_without_confirmation(self) -> None:
        class Var:
            def __init__(self, value: int) -> None:
                self.value = value

            def get(self) -> int:
                return self.value

            def set(self, value: int) -> None:
                self.value = int(value)

        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/a1"),
            AccountConfig("第一层", 2, 2, "https://example.com/a2"),
        ]
        fake = SimpleNamespace(
            client_direct_base_port_var=Var(9222),
            logs=[],
        )
        fake._ensure_client_direct_selected_batch_current = lambda: None
        fake._refresh_client_direct_sessions_for_precheck = lambda: {9230}
        fake._sync_client_direct_port_range = lambda: None
        fake._log = lambda message: fake.logs.append(message)

        with (
            mock.patch("douluo_launcher.gui.check_port_range_available", return_value=[9222]),
            mock.patch("douluo_launcher.gui.find_next_available_port_range", return_value=9231),
            mock.patch("douluo_launcher.gui.messagebox.askyesno") as askyesno,
        ):
            result = LauncherApp._precheck_client_direct_prepare_ports(fake, accounts, append=False)

        self.assertTrue(result)
        self.assertEqual(fake.client_direct_base_port_var.get(), 9231)
        askyesno.assert_not_called()
        self.assertTrue(any("自动改用推荐端口 9231~9232" in line for line in fake.logs))

    def test_client_direct_run_mode_starts_single_account_runner_without_serial_precheck(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            client_direct_auto_enter_var=SimpleNamespace(get=lambda: False),
            wm_tile_mode_var=SimpleNamespace(get=lambda: "固定参数排列"),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            logs=[],
        )
        fake._selected_account = mock.Mock(return_value=account)
        fake._precheck_serial_run = mock.Mock(return_value=True)
        fake._validate_accounts_for_current_mode = mock.Mock(return_value=True)
        fake._start_serial_run = mock.Mock()
        fake._start_background_single_run = mock.Mock()
        fake._start_client_direct_single_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._run_selected_account(fake)

        fake._precheck_serial_run.assert_not_called()
        fake._validate_accounts_for_current_mode.assert_not_called()
        fake._start_serial_run.assert_not_called()
        fake._start_background_single_run.assert_not_called()
        fake._start_client_direct_single_run.assert_called_once_with(account)
        self.assertTrue(any("客户端直登模式" in line and "不自动进入游戏" in line for line in fake.logs))

    def test_client_direct_mode_allows_current_layer_and_all_serial_but_blocks_method2(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("第一层", 2, 2, "https://example.com/l2", include_in_all=True),
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            logs=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._filtered_accounts_for_ui = mock.Mock(return_value=accounts)
        fake._start_serial_run = mock.Mock()
        fake._start_client_direct_serial_run = mock.Mock()

        LauncherApp._run_level_serial(fake)

        fake._filtered_accounts_for_ui.assert_called_once()
        fake._start_serial_run.assert_not_called()
        fake._start_client_direct_serial_run.assert_called_once_with(accounts, run_label="客户端当前层串行")
        self.assertTrue(any("客户端当前层串行" in line for line in fake.logs))

        fake_all = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "全部"),
            logs=[],
        )
        fake_all._log = lambda message: fake_all.logs.append(message)
        skipped = AccountConfig("存钻", 1, 9, "https://example.com/z1", include_in_all=False)
        fake_all._mode_allowed_accounts = mock.Mock(return_value=accounts + [skipped])
        fake_all._filtered_accounts_for_ui = mock.Mock(return_value=accounts)
        fake_all._start_client_direct_serial_run = mock.Mock()
        fake_all._account_group_counts = lambda items: [("第一层", len([item for item in items if item.level == "第一层"]))]
        fake_all._account_count_summary = lambda items: f"{len(items)} 个"

        with mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning:
            LauncherApp._run_all_serial(fake_all)

        fake_all._mode_allowed_accounts.assert_called_once()
        fake_all._filtered_accounts_for_ui.assert_called_once()
        fake_all._start_client_direct_serial_run.assert_called_once_with(accounts, run_label="客户端全部串行")
        warning.assert_not_called()
        self.assertTrue(any("客户端全部串行" in line for line in fake_all.logs))

        fake_method2 = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method2"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            logs=[],
        )
        fake_method2._log = lambda message: fake_method2.logs.append(message)
        fake_method2._run_method2_single = mock.Mock()

        with mock.patch("douluo_launcher.gui.messagebox.showwarning"):
            LauncherApp._run_selected_account(fake_method2)

        fake_method2._run_method2_single.assert_not_called()
        self.assertTrue(any("方式二" in line and "当前层串行" in line for line in fake_method2.logs))

    def test_client_direct_all_serial_requires_all_level(self) -> None:
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            logs=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._mode_allowed_accounts = mock.Mock()
        fake._start_client_direct_serial_run = mock.Mock()

        with mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning:
            LauncherApp._run_all_serial(fake)

        fake._mode_allowed_accounts.assert_not_called()
        fake._start_client_direct_serial_run.assert_not_called()
        warning.assert_called_once()
        self.assertTrue(any("include_in_all=true" in line for line in fake.logs))

    def test_client_direct_single_start_rejects_incomplete_url_before_worker(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://7tu7tu.com/dldl?genCode=true", include_in_all=True)
        fake = SimpleNamespace(worker_thread=None, logs=[], statuses=[])
        fake._setup_log_file = mock.Mock()
        fake._set_status = lambda _account, status: fake.statuses.append(status)
        fake._log = lambda message: fake.logs.append(message)

        with mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning:
            LauncherApp._start_client_direct_single_run(fake, account)

        fake._setup_log_file.assert_called_once_with(cleanup_old=False)
        self.assertEqual(fake.statuses, ["客户端直登失败"])
        self.assertTrue(any("不是完整客户端直登 URL" in line for line in fake.logs))
        warning.assert_called_once()

    def test_client_direct_prepare_and_login_buttons_use_current_scope(self) -> None:
        accounts = [
            AccountConfig(
                "存钻",
                1,
                1,
                "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
                include_in_all=False,
            )
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "存钻"),
            client_direct_auto_enter_var=SimpleNamespace(get=lambda: True),
            logs=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=accounts)
        fake._start_client_direct_prepare_run = mock.Mock()
        fake._start_client_direct_prepared_login_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._prepare_client_direct_current_scope(fake)
        LauncherApp._login_prepared_client_direct_current_scope(fake)

        fake._start_client_direct_prepare_run.assert_called_once_with(accounts, run_label="客户端准备当前层", append=False)
        fake._start_client_direct_prepared_login_run.assert_called_once_with(accounts, run_label="客户端当前层登录")
        self.assertTrue(any("准备客户端" in line and "存钻" in line for line in fake.logs))
        self.assertTrue(any("执行客户端登录" in line and "自动进入游戏" in line for line in fake.logs))

    def test_client_direct_three_step_buttons_use_all_level_filtered_accounts(self) -> None:
        accounts = [
            AccountConfig(
                "第一层",
                1,
                1,
                "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
                include_in_all=True,
            ),
            AccountConfig(
                "第二层",
                1,
                9,
                "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t2&time=123&sign=s2&isPcLauncher=true",
                include_in_all=True,
            ),
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "全部"),
            client_direct_auto_enter_var=SimpleNamespace(get=lambda: False),
            worker_thread=None,
            client_direct_bindings={},
            logs=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=accounts)
        fake._start_client_direct_prepare_run = mock.Mock()
        fake._start_client_direct_prepared_login_run = mock.Mock()
        fake._wm_read_arrangement_config = mock.Mock(return_value=None)
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._prepare_client_direct_current_scope(fake)
        LauncherApp._login_prepared_client_direct_current_scope(fake)

        fake._start_client_direct_prepare_run.assert_called_once_with(accounts, run_label="客户端准备当前层", append=False)
        fake._start_client_direct_prepared_login_run.assert_called_once_with(accounts, run_label="客户端当前层登录")
        self.assertTrue(any("层级=全部" in line for line in fake.logs))

    def test_client_direct_prepare_cancel_keeps_live_batch_and_does_not_start_worker(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        store = ClientBatchStore()
        store.create_batch("第一层-1号", scope="当前层:第一层", base_port=9222)
        store.append_binding(
            ClientBatchBinding(
                account.key,
                account.display_name,
                pid=2001,
                hwnd=3001,
                cdp_port=9222,
                login_url=account.url,
                status="待登录",
            )
        )
        fake = SimpleNamespace(
            worker_thread=None,
            client_batch_store=store,
            client_direct_bindings={
                account.key: ClientDirectRunRecord(
                    account_id=account.key,
                    account_name=account.display_name,
                    pid=2001,
                    hwnd=3001,
                    cdp_port=9222,
                    login_url=account.url,
                    status="待登录",
                )
            },
            logs=[],
        )
        fake._ensure_client_direct_selected_batch_current = lambda: None
        fake._refresh_client_direct_sessions_for_precheck = lambda: {9222}
        fake._wm_game_exe_path_filter = mock.Mock(return_value=r"E:\Program Files\DLH5\X5Game.exe")
        fake._setup_log_file = mock.Mock()
        fake._set_status = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        with (
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch("douluo_launcher.gui.messagebox.askyesno", return_value=False),
        ):
            LauncherApp._start_client_direct_prepare_run(fake, [account], run_label="客户端准备当前层")

        fake._setup_log_file.assert_not_called()
        fake._set_status.assert_not_called()
        self.assertEqual(store.current_batch().batch_name, "第一层-1号")
        self.assertTrue(any("用户取消创建新批次" in line for line in fake.logs))

    def test_client_direct_prepare_prechecks_configured_port_range(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            worker_thread=None,
            client_direct_bindings={},
            client_batch_store=ClientBatchStore(),
            logs=[],
        )
        fake.client_direct_base_port_var = SimpleNamespace(get=lambda: 9231, set=lambda value: None)
        fake._setup_log_file = mock.Mock()
        fake._set_status = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        with mock.patch("douluo_launcher.gui.check_port_range_available", return_value=[9231]), mock.patch(
            "douluo_launcher.gui.find_next_available_port_range",
            return_value=None,
        ), mock.patch(
            "douluo_launcher.gui.messagebox.showwarning"
        ) as warning:
            LauncherApp._start_client_direct_prepare_run(fake, [account], run_label="客户端准备当前层")

        fake._setup_log_file.assert_not_called()
        warning.assert_called_once()
        self.assertTrue(any("端口范围不可用" in line for line in fake.logs))

    def test_client_direct_prepare_recommends_next_continuous_port_range_without_confirmation(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        selected_ports = []
        fake = SimpleNamespace(
            client_batch_store=ClientBatchStore(),
            logs=[],
        )
        fake.client_direct_base_port_var = SimpleNamespace(
            get=lambda: selected_ports[-1] if selected_ports else 9222,
            set=lambda value: selected_ports.append(int(value)),
        )
        fake._log = lambda message: fake.logs.append(message)

        def occupied_range(base_port, count, **_kwargs):
            if int(base_port) == 9222:
                return list(range(9222, 9231))
            return []

        with mock.patch("douluo_launcher.gui.check_port_range_available", side_effect=occupied_range), mock.patch(
            "douluo_launcher.gui.find_next_available_port_range",
            return_value=9231,
        ), mock.patch("douluo_launcher.gui.messagebox.askyesno") as ask:
            allowed = LauncherApp._precheck_client_direct_prepare_ports(fake, [account] * 31, append=False)

        self.assertTrue(allowed)
        self.assertEqual(selected_ports[-1], 9231)
        ask.assert_not_called()
        self.assertTrue(any("自动改用推荐端口 9231~9261" in line for line in fake.logs))

    def test_client_direct_prepare_stops_when_no_recommended_port_exists(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(client_batch_store=ClientBatchStore(), logs=[])
        fake.client_direct_base_port_var = SimpleNamespace(get=lambda: 9222, set=mock.Mock())
        fake._log = lambda message: fake.logs.append(message)

        with mock.patch("douluo_launcher.gui.check_port_range_available", return_value=[9222]), mock.patch(
            "douluo_launcher.gui.find_next_available_port_range",
            return_value=None,
        ), mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning:
            allowed = LauncherApp._precheck_client_direct_prepare_ports(fake, [account], append=False)

        self.assertFalse(allowed)
        warning.assert_called_once()
        self.assertNotIn(mock.call(9231), fake.client_direct_base_port_var.set.call_args_list)

    def test_client_direct_prepare_ignores_stale_session_ports_and_marks_pid_missing(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            store.create_batch("旧批次", scope="当前层", base_port=9222)
            store.append_binding(ClientBatchBinding("old", "旧账号", pid=100, hwnd=111, cdp_port=9222, login_url="u1", status="prepared"))
            store.save()
            fake = SimpleNamespace(client_batch_store=store, logs=[], client_direct_bindings={})
            fake.client_direct_base_port_var = SimpleNamespace(get=lambda: 9222, set=lambda _value: None)
            fake.client_direct_batch_select_var = SimpleNamespace(get=lambda: "")
            fake._log = lambda message: fake.logs.append(message)

            with mock.patch("douluo_launcher.gui.check_port_range_available", return_value=[]), mock.patch(
                "douluo_launcher.gui.messagebox.showwarning"
            ) as warning, mock.patch.object(LauncherApp, "_client_direct_pid_exists", return_value=False), mock.patch.object(
                LauncherApp,
                "_client_direct_process_is_x5game",
                return_value=False,
            ), mock.patch.object(LauncherApp, "_client_direct_cdp_available", return_value=False), mock.patch.object(
                LauncherApp,
                "_client_direct_is_window_alive",
                return_value=False,
            ):
                allowed = LauncherApp._precheck_client_direct_prepare_ports(fake, [account], append=False)

            self.assertTrue(allowed)
            warning.assert_not_called()
            self.assertEqual(store.current_batch().bindings[0].status, "pid_missing")

    def test_client_direct_prepare_blocks_only_real_listening_system_ports(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(client_batch_store=ClientBatchStore(), logs=[])
        fake.client_direct_base_port_var = SimpleNamespace(get=lambda: 9222, set=lambda _value: None)
        fake.client_direct_batch_select_var = SimpleNamespace(get=lambda: "")
        fake._log = lambda message: fake.logs.append(message)

        with mock.patch("douluo_launcher.gui.check_port_range_available", return_value=[9222]), mock.patch(
            "douluo_launcher.gui.find_next_available_port_range",
            return_value=None,
        ), mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning:
            allowed = LauncherApp._precheck_client_direct_prepare_ports(fake, [account], append=False)

        self.assertFalse(allowed)
        self.assertIn("系统真实占用端口：9222", warning.call_args.args[1])
        self.assertNotIn("存活批次绑定端口", warning.call_args.args[1])

    def test_client_direct_prepare_blocks_live_x5game_binding_ports(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            store.create_batch("桌面1", scope="当前层", base_port=9222)
            store.append_binding(ClientBatchBinding("alive", "活账号", pid=200, hwnd=111, cdp_port=9222, login_url="u1", status="prepared"))
            store.save()
            fake = SimpleNamespace(client_batch_store=store, logs=[], client_direct_bindings={})
            fake.client_direct_base_port_var = SimpleNamespace(get=lambda: 9222, set=lambda _value: None)
            fake.client_direct_batch_select_var = SimpleNamespace(get=lambda: "")
            fake._log = lambda message: fake.logs.append(message)

            with mock.patch("douluo_launcher.gui.check_port_range_available", return_value=[]), mock.patch(
                "douluo_launcher.gui.find_next_available_port_range",
                return_value=None,
            ), mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning, mock.patch.object(
                LauncherApp,
                "_client_direct_pid_exists",
                return_value=True,
            ), mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True), mock.patch.object(
                LauncherApp,
                "_client_direct_cdp_available",
                return_value=False,
            ), mock.patch.object(LauncherApp, "_client_direct_is_window_alive", return_value=True):
                allowed = LauncherApp._precheck_client_direct_prepare_ports(fake, [account], append=False)

            self.assertFalse(allowed)
            self.assertIn("存活批次绑定端口：9222", warning.call_args.args[1])
            self.assertEqual(store.current_batch().bindings[0].status, "cdp_unavailable")

    def test_client_direct_append_prepare_keeps_existing_batch_bindings(self) -> None:
        existing = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        new_account = AccountConfig(
            "第一层",
            2,
            2,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t2&time=123&sign=s2&isPcLauncher=true",
            include_in_all=True,
        )
        store = ClientBatchStore()
        store.create_batch("桌面2", scope="当前层", base_port=9231)
        store.append_binding(ClientBatchBinding(existing.key, existing.display_name, pid=1, hwnd=11, cdp_port=9231, login_url=existing.url))
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            client_batch_store=store,
            client_direct_bindings={
                existing.key: ClientDirectRunRecord(existing.key, existing.display_name, pid=1, hwnd=11, cdp_port=9231, login_url=existing.url)
            },
            logs=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=[existing, new_account])
        fake._start_client_direct_prepare_run = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        LauncherApp._append_client_direct_current_scope(fake)

        fake._start_client_direct_prepare_run.assert_called_once_with([new_account], run_label="客户端追加准备", append=True)
        self.assertIn(existing.key, fake.client_direct_bindings)

    def test_client_direct_restore_active_batch_for_arrange_and_login(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        store = ClientBatchStore()
        store.create_batch("桌面2", scope="全部串行", base_port=9231)
        store.append_binding(ClientBatchBinding(account.key, account.display_name, pid=10, hwnd=20, cdp_port=9231, login_url=account.url))
        fake = SimpleNamespace(
            accounts=[account],
            client_batch_store=store,
            client_direct_bindings={},
        )

        accounts = LauncherApp._client_direct_accounts_from_active_batch(fake)

        self.assertEqual([item.key for item in accounts], [account.key])
        self.assertEqual(fake.client_direct_bindings[account.key].cdp_port, 9231)
        self.assertEqual(fake.client_direct_bindings[account.key].login_url, account.url)

    def test_client_direct_batch_dropdown_switch_syncs_active_batch_and_bindings(self) -> None:
        first = AccountConfig("第一层", 1, 1, "https://example.com/a1")
        second = AccountConfig("第二层", 1, 2, "https://example.com/a2")
        store = ClientBatchStore()
        batch_a = store.create_batch("桌面1", scope="当前层", base_port=9222)
        store.append_binding(ClientBatchBinding(first.key, first.display_name, pid=1, hwnd=11, cdp_port=9222, login_url=first.url))
        batch_b = store.create_batch("桌面2", scope="全部串行", base_port=9231)
        store.append_binding(ClientBatchBinding(second.key, second.display_name, pid=2, hwnd=22, cdp_port=9231, login_url=second.url))
        fake = SimpleNamespace(
            accounts=[first, second],
            client_batch_store=store,
            client_direct_bindings={},
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"桌面1 | {batch_a.batch_id}", set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
            client_direct_batch_status_var=SimpleNamespace(set=lambda _value: None),
            client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
            client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
        )

        LauncherApp._on_client_direct_batch_selected(fake)

        self.assertEqual(store.active_batch_id, batch_a.batch_id)
        self.assertEqual(list(fake.client_direct_bindings), [first.key])
        self.assertEqual(fake.client_direct_bindings[first.key].hwnd, 11)

    def test_client_direct_login_uses_selected_batch_without_touching_other_batch(self) -> None:
        first = AccountConfig("第一层", 1, 1, "https://example.com/a1")
        second = AccountConfig("第二层", 1, 2, "https://example.com/a2")
        store = ClientBatchStore()
        batch_a = store.create_batch("桌面1", scope="当前层", base_port=9222)
        store.append_binding(ClientBatchBinding(first.key, first.display_name, pid=1, hwnd=11, cdp_port=9222, login_url=first.url))
        batch_b = store.create_batch("桌面2", scope="全部串行", base_port=9231)
        store.append_binding(ClientBatchBinding(second.key, second.display_name, pid=2, hwnd=22, cdp_port=9231, login_url=second.url))
        fake = SimpleNamespace(
            accounts=[first, second],
            client_batch_store=store,
            client_direct_bindings={},
            client_direct_auto_enter_var=SimpleNamespace(get=lambda: False),
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"桌面2 | {batch_b.batch_id}", set=lambda _value: None),
            logs=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._start_client_direct_prepared_login_run = mock.Mock()

        LauncherApp._login_prepared_client_direct_current_scope(fake)

        called_accounts = fake._start_client_direct_prepared_login_run.call_args.args[0]
        self.assertEqual([account.key for account in called_accounts], [second.key])
        self.assertEqual(store.active_batch_id, batch_b.batch_id)
        store.switch_batch(batch_a.batch_id)
        self.assertEqual(store.current_batch().bindings[0].status, "pending")

    def test_client_direct_close_uses_selected_batch_without_touching_other_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = AccountConfig("第一层", 1, 1, "https://example.com/a1")
            second = AccountConfig("第二层", 1, 2, "https://example.com/a2")
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            batch_a = store.create_batch("桌面1", scope="当前层", base_port=9222)
            store.append_binding(ClientBatchBinding(first.key, first.display_name, pid=101, hwnd=11, cdp_port=9222, login_url=first.url, status="prepared"))
            batch_b = store.create_batch("桌面2", scope="全部串行", base_port=9231)
            store.append_binding(ClientBatchBinding(second.key, second.display_name, pid=202, hwnd=22, cdp_port=9231, login_url=second.url, status="prepared"))
            fake = SimpleNamespace(
                accounts=[first, second],
                client_batch_store=store,
                client_direct_bindings={},
                client_direct_batch_select_var=SimpleNamespace(get=lambda: f"桌面2 | {batch_b.batch_id}", set=lambda _value: None),
                client_direct_batch_status_var=SimpleNamespace(set=lambda _value: None),
                client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
                client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
                client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
                logs=[],
            )
            fake._log = lambda message: fake.logs.append(message)

            with mock.patch("douluo_launcher.gui.messagebox.askyesno", return_value=True), mock.patch(
                "subprocess.run"
            ) as run:
                LauncherApp._close_client_direct_current_batch(fake)

            self.assertEqual([call.args[0] for call in run.call_args_list], [["taskkill", "/PID", "202", "/T", "/F"]])
            store.switch_batch(batch_b.batch_id)
            self.assertEqual(store.current_batch().bindings[0].status, "closed")
            store.switch_batch(batch_a.batch_id)
            self.assertEqual(store.current_batch().bindings[0].status, "prepared")

    def test_client_direct_arrange_uses_only_prepared_binding_hwnds(self) -> None:
        accounts = [
            AccountConfig(
                "第一层",
                index,
                index,
                f"https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t{index}&time=123&sign=s{index}&isPcLauncher=true",
                include_in_all=True,
            )
            for index in range(1, 3)
        ]
        unrelated = AccountConfig(
            "第二层",
            1,
            9,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t9&time=123&sign=s9&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            worker_thread=None,
            client_direct_bindings={
                accounts[0].key: ClientDirectRunRecord(
                    account_id=accounts[0].key,
                    account_name=accounts[0].display_name,
                    pid=2001,
                    hwnd=111,
                    cdp_port=9222,
                    login_url=accounts[0].url,
                    status="待登录",
                ),
                accounts[1].key: ClientDirectRunRecord(
                    account_id=accounts[1].key,
                    account_name=accounts[1].display_name,
                    pid=2002,
                    hwnd=222,
                    cdp_port=9223,
                    login_url=accounts[1].url,
                    status="待登录",
                ),
                unrelated.key: ClientDirectRunRecord(
                    account_id=unrelated.key,
                    account_name=unrelated.display_name,
                    pid=2009,
                    hwnd=999,
                    cdp_port=9230,
                    login_url=unrelated.url,
                    status="待登录",
                ),
            },
            logs=[],
            statuses=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=accounts)
        fake._wm_read_arrangement_config = mock.Mock(
            return_value=("固定参数排列", TileConfig(width=800, height=600, start_x=0, start_y=0, offset_x=20, offset_y=20, per_row=2))
        )
        fake._save_window_manager_settings = mock.Mock(return_value=True)
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._wm_log_tile_results = mock.Mock()

        def tile_windows(_self, windows, *_args, **_kwargs):
            fake.arranged_hwnds = [window.hwnd for window in windows]
            return [
                SimpleNamespace(success=True, window=window, x=0, y=0, width=800, height=600, wrapped_by_screen=False)
                for window in windows
            ]

        with mock.patch("douluo_launcher.gui.user32.IsWindow", side_effect=lambda hwnd: int(hwnd) in {111, 222}), mock.patch(
            "douluo_launcher.gui.get_window_rect",
            return_value=WindowRect(10, 20, 810, 620),
        ), mock.patch.object(LauncherApp, "_client_direct_tile_binding_windows", side_effect=tile_windows):
            LauncherApp._arrange_prepared_client_direct_current_scope(fake)

        self.assertEqual(fake.arranged_hwnds, [111, 222])
        fake._filtered_accounts_for_ui.assert_not_called()
        fake._save_window_manager_settings.assert_called_once()
        self.assertIn((accounts[0].key, "已排列"), fake.statuses)
        self.assertEqual(fake.client_direct_bindings[accounts[0].key].status, "已排列")
        self.assertEqual(fake.client_direct_bindings[unrelated.key].hwnd, 999)

    def test_client_direct_arrange_renames_only_current_batch_bindings_with_account_template(self) -> None:
        accounts = [
            AccountConfig(
                "第一层",
                index,
                index,
                f"https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t{index}&time=123&sign=s{index}&isPcLauncher=true",
                include_in_all=True,
            )
            for index in range(10, 12)
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            worker_thread=None,
            client_direct_bindings={
                accounts[0].key: ClientDirectRunRecord(accounts[0].key, accounts[0].display_name, pid=1, hwnd=111, cdp_port=9231, login_url=accounts[0].url),
                accounts[1].key: ClientDirectRunRecord(accounts[1].key, accounts[1].display_name, pid=2, hwnd=222, cdp_port=9232, login_url=accounts[1].url),
                "other": ClientDirectRunRecord("other", "其他", pid=9, hwnd=999, cdp_port=9300, login_url="https://example.com"),
            },
            wm_auto_rename_after_tile_var=SimpleNamespace(get=lambda: True),
            wm_title_template_var=SimpleNamespace(get=lambda: "斗罗大陆H5-{account_id}号"),
            logs=[],
            statuses=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=accounts)
        fake._wm_read_arrangement_config = mock.Mock(
            return_value=("固定参数排列", TileConfig(width=800, height=600, start_x=0, start_y=0, offset_x=20, offset_y=20, per_row=2))
        )
        fake._save_window_manager_settings = mock.Mock(return_value=True)
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._wm_log_tile_results = mock.Mock()

        def tile_windows(_self, windows, *_args, **_kwargs):
            return [
                SimpleNamespace(success=True, window=window, x=0, y=0, width=800, height=600, wrapped_by_screen=False)
                for window in windows
            ]

        renamed = []
        with mock.patch("douluo_launcher.gui.user32.IsWindow", side_effect=lambda hwnd: int(hwnd) in {111, 222}), mock.patch(
            "douluo_launcher.gui.get_window_rect",
            return_value=WindowRect(10, 20, 810, 620),
        ), mock.patch.object(LauncherApp, "_client_direct_tile_binding_windows", side_effect=tile_windows), mock.patch(
            "douluo_launcher.gui.user32.SetWindowTextW",
            side_effect=lambda hwnd, title: renamed.append((int(hwnd), title)) or True,
        ):
            LauncherApp._arrange_prepared_client_direct_current_scope(fake)

        self.assertEqual(renamed, [(111, "斗罗大陆H5-10号"), (222, "斗罗大陆H5-11号")])
        self.assertNotIn(999, [hwnd for hwnd, _title in renamed])

    def test_client_direct_title_template_falls_back_to_index_when_account_id_missing(self) -> None:
        record = ClientDirectRunRecord("", "账号", pid=1, hwnd=111, cdp_port=9231, login_url="")

        title = LauncherApp._client_direct_binding_title_from_template("斗罗大陆H5-{account_id}号", 3, record)

        self.assertEqual(title, "斗罗大陆H5-3号")

    def test_repair_current_batch_requires_confirmation_and_logs_batch_first(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com/login.php?token=secret")
        store = ClientBatchStore()
        batch = store.create_batch("桌面2-31号", scope="全部串行", base_port=9231)
        store.append_binding(ClientBatchBinding(account.key, account.display_name, pid=10, hwnd=20, cdp_port=9231, login_url=account.url))
        fake = SimpleNamespace(
            accounts=[account],
            client_batch_store=store,
            client_direct_bindings={},
            logs=[],
            statuses=[],
            client_direct_batch_status_var=SimpleNamespace(set=lambda _value: None),
            client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
            client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"桌面2-31号 | {batch.batch_id}", set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))

        with mock.patch("douluo_launcher.gui.messagebox.askyesno", return_value=True) as ask, mock.patch.object(
            LauncherApp,
            "_client_direct_pid_exists",
            return_value=True,
        ), mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True), mock.patch.object(
            LauncherApp,
            "_client_direct_cdp_available",
            return_value=True,
        ), mock.patch("douluo_launcher.gui.wait_for_client_hwnd_by_pid", return_value=30):
            LauncherApp._repair_client_direct_current_batch(fake)

        self.assertIn("批次名称：桌面2-31号", ask.call_args.args[1])
        self.assertTrue(fake.logs[0].startswith("[修复本批窗口] 当前批次=桌面2-31号"))
        self.assertIn(f"batch_id={batch.batch_id}", fake.logs[0])
        self.assertIn("绑定数量=1", fake.logs[0])
        self.assertIn("端口范围=9231~9231", fake.logs[0])
        self.assertEqual(store.current_batch().bindings[0].hwnd, 30)

    def test_repair_current_batch_reopens_pid_missing_binding_reusing_original_port(self) -> None:
        accounts = [
            AccountConfig(
                "单层账号",
                index,
                index,
                f"https://dldl.50pk.com/login.php?gid=1&pid=1&token=t{index}&time=1&sign=s{index}&isPcLauncher=true",
            )
            for index in range(1, 10)
        ]
        store = ClientBatchStore()
        batch = store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        for index, account in enumerate(accounts, start=1):
            store.append_binding(
                ClientBatchBinding(
                    account.key,
                    account.display_name,
                    pid=1000 + index if index < 9 else 9009,
                    hwnd=2000 + index if index < 9 else 0,
                    cdp_port=9221 + index,
                    login_url=account.url,
                    status="restored" if index < 9 else "pid_missing",
                )
            )
        fake = SimpleNamespace(
            accounts=accounts,
            client_batch_store=store,
            client_direct_bindings={},
            logs=[],
            statuses=[],
            stop_event=SimpleNamespace(is_set=lambda: False),
            _log_file=None,
            client_direct_batch_status_var=SimpleNamespace(set=lambda value: fake.status_texts.append(value)),
            client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
            client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"单层账号-9号 | {batch.batch_id}", set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
            status_texts=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._wm_game_exe_path_filter = mock.Mock(return_value=r"E:\Program Files\DLH5\X5Game.exe")

        def pid_exists(_self, pid: int) -> bool:
            return int(pid) != 9009

        def prepare_result(config, **_kwargs):
            return SimpleNamespace(
                success=True,
                message="客户端已启动，待登录",
                binding=SimpleNamespace(pid=3009, hwnd=4009, cdp_port=config.cdp_port),
            )

        with (
            mock.patch("douluo_launcher.gui.messagebox.askyesno", side_effect=[True, True]) as ask,
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", side_effect=pid_exists),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_cdp_available", return_value=True),
            mock.patch("douluo_launcher.gui.wait_for_client_hwnd_by_pid", side_effect=lambda pid, timeout=0.5: 2000 + int(pid) - 1000),
            mock.patch("douluo_launcher.gui.is_tcp_port_available", return_value=True),
            mock.patch("douluo_launcher.gui.Path.exists", return_value=True),
            mock.patch("douluo_launcher.gui.prepare_client_direct_client", side_effect=prepare_result) as prepare,
        ):
            LauncherApp._repair_client_direct_current_batch(fake)

        self.assertEqual(len(store.batches), 1)
        self.assertEqual(store.active_batch_id, batch.batch_id)
        prepare.assert_called_once()
        self.assertEqual(prepare.call_args.args[0].account_id, accounts[8].key)
        self.assertEqual(prepare.call_args.args[0].cdp_port, 9230)
        self.assertIn("当前批次有 1 个客户端进程已不存在", ask.call_args_list[1].args[1])
        repaired = store.current_batch().bindings[8]
        self.assertEqual((repaired.pid, repaired.hwnd, repaired.cdp_port), (3009, 4009, 9230))
        self.assertEqual(repaired.status, "客户端已启动/待登录")
        self.assertEqual(store.current_batch().bindings[0].pid, 1001)
        self.assertTrue(any("存活=9" in value and "已关闭=0" in value for value in fake.status_texts))

    def test_repair_current_batch_moves_and_renames_only_reopened_missing_window(self) -> None:
        accounts = [
            AccountConfig(
                "单层账号",
                index,
                index,
                f"https://dldl.50pk.com/login.php?gid=1&pid=1&token=t{index}&time=1&sign=s{index}&isPcLauncher=true",
            )
            for index in range(1, 10)
        ]
        store = ClientBatchStore()
        batch = store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        for index, account in enumerate(accounts, start=1):
            store.append_binding(
                ClientBatchBinding(
                    account.key,
                    account.display_name,
                    pid=1000 + index if index < 9 else 9009,
                    hwnd=2000 + index if index < 9 else 0,
                    cdp_port=9221 + index,
                    login_url=account.url,
                    status="restored" if index < 9 else "pid_missing",
                )
            )
        fake = SimpleNamespace(
            accounts=accounts,
            client_batch_store=store,
            client_direct_bindings={},
            logs=[],
            statuses=[],
            stop_event=SimpleNamespace(is_set=lambda: False),
            _log_file=None,
            wm_auto_rename_after_tile_var=SimpleNamespace(get=lambda: True),
            client_direct_batch_status_var=SimpleNamespace(set=lambda _value: None),
            client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
            client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"单层账号-9号 | {batch.batch_id}", set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._wm_game_exe_path_filter = mock.Mock(return_value=r"E:\Program Files\DLH5\X5Game.exe")
        fake._wm_read_arrangement_config = mock.Mock(
            return_value=("固定参数排列", TileConfig(width=320, height=540, start_x=10, start_y=20, offset_x=30, offset_y=40, per_row=8))
        )

        def prepare_result(config, **_kwargs):
            return SimpleNamespace(
                success=True,
                message="客户端已启动，待登录",
                binding=SimpleNamespace(pid=3009, hwnd=4009, cdp_port=config.cdp_port),
            )

        moved: list[tuple] = []
        renamed: list[tuple[int, str]] = []
        with (
            mock.patch("douluo_launcher.gui.messagebox.askyesno", side_effect=[True, True]),
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", side_effect=lambda _self, pid: int(pid) != 9009),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_cdp_available", return_value=True),
            mock.patch("douluo_launcher.gui.wait_for_client_hwnd_by_pid", return_value=2001),
            mock.patch("douluo_launcher.gui.is_tcp_port_available", return_value=True),
            mock.patch("douluo_launcher.gui.Path.exists", return_value=True),
            mock.patch("douluo_launcher.gui.prepare_client_direct_client", side_effect=prepare_result),
            mock.patch("douluo_launcher.gui.user32.SetWindowPos", side_effect=lambda *args: moved.append(args) or True),
            mock.patch("douluo_launcher.gui.user32.SetWindowTextW", side_effect=lambda hwnd, title: renamed.append((int(hwnd), title)) or True),
        ):
            LauncherApp._repair_client_direct_current_batch(fake)

        self.assertEqual(len(moved), 1)
        self.assertEqual(int(moved[0][0]), 4009)
        self.assertEqual(moved[0][2:6], (10, 60, 320, 540))
        self.assertEqual(renamed, [(4009, "斗罗大陆H5-9号")])
        self.assertTrue(any("已移动到第9槽位" in line for line in fake.logs))
        self.assertTrue(any("已重命名为 斗罗大陆H5-9号" in line for line in fake.logs))

    def test_repair_current_batch_keeps_success_status_for_repaired_live_bindings(self) -> None:
        accounts = [
            AccountConfig("单层账号", index, index, f"https://example.com/{index}")
            for index in range(1, 9)
        ]
        store = ClientBatchStore()
        batch = store.create_batch("单层账号-8号", scope="当前层:单层账号", base_port=9222)
        for index, account in enumerate(accounts, start=1):
            store.append_binding(
                ClientBatchBinding(
                    account.key,
                    account.display_name,
                    pid=1000 + index,
                    hwnd=0,
                    cdp_port=9221 + index,
                    login_url=account.url,
                    status="客户端登录成功",
                    error_message="already ok",
                )
            )
        fake = SimpleNamespace(
            accounts=accounts,
            client_batch_store=store,
            client_direct_bindings={},
            logs=[],
            statuses=[],
            client_direct_batch_status_var=SimpleNamespace(set=lambda _value: None),
            client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
            client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"单层账号-8号 | {batch.batch_id}", set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))

        with (
            mock.patch("douluo_launcher.gui.messagebox.askyesno", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_cdp_available", return_value=True),
            mock.patch("douluo_launcher.gui.wait_for_client_hwnd_by_pid", side_effect=lambda pid, **_kwargs: int(pid) + 1000),
        ):
            LauncherApp._repair_client_direct_current_batch(fake)

        self.assertEqual([binding.status for binding in store.current_batch().bindings], ["客户端登录成功"] * 8)
        self.assertEqual([binding.error_message for binding in store.current_batch().bindings], ["already ok"] * 8)
        self.assertNotIn("客户端已启动/待登录", [status for _key, status in fake.statuses])

    def test_repair_current_batch_keeps_success_status_except_reopened_pid_missing(self) -> None:
        accounts = [
            AccountConfig("单层账号", index, index, f"https://example.com/{index}")
            for index in range(1, 10)
        ]
        store = ClientBatchStore()
        batch = store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        for index, account in enumerate(accounts, start=1):
            store.append_binding(
                ClientBatchBinding(
                    account.key,
                    account.display_name,
                    pid=1000 + index if index < 9 else 9009,
                    hwnd=2000 + index if index < 9 else 0,
                    cdp_port=9221 + index,
                    login_url=account.url,
                    status="客户端登录成功" if index < 9 else "pid_missing",
                )
            )
        fake = SimpleNamespace(
            accounts=accounts,
            client_batch_store=store,
            client_direct_bindings={},
            logs=[],
            statuses=[],
            stop_event=SimpleNamespace(is_set=lambda: False),
            _log_file=None,
            client_direct_batch_status_var=SimpleNamespace(set=lambda _value: None),
            client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
            client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"单层账号-9号 | {batch.batch_id}", set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._wm_game_exe_path_filter = mock.Mock(return_value=r"E:\Program Files\DLH5\X5Game.exe")

        def prepare_result(config, **_kwargs):
            return SimpleNamespace(
                success=True,
                message="客户端已启动，待登录",
                binding=SimpleNamespace(pid=3009, hwnd=4009, cdp_port=config.cdp_port),
            )

        with (
            mock.patch("douluo_launcher.gui.messagebox.askyesno", side_effect=[True, True]),
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", side_effect=lambda _self, pid: int(pid) != 9009),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_cdp_available", return_value=True),
            mock.patch("douluo_launcher.gui.wait_for_client_hwnd_by_pid", return_value=2001),
            mock.patch("douluo_launcher.gui.is_tcp_port_available", return_value=True),
            mock.patch("douluo_launcher.gui.Path.exists", return_value=True),
            mock.patch("douluo_launcher.gui.prepare_client_direct_client", side_effect=prepare_result),
        ):
            LauncherApp._repair_client_direct_current_batch(fake)

        statuses = [binding.status for binding in store.current_batch().bindings]
        self.assertEqual(statuses[:8], ["客户端登录成功"] * 8)
        self.assertEqual(statuses[8], "客户端已启动/待登录")

        pending_accounts = LauncherApp._client_direct_accounts_for_login_scope(fake, CLIENT_DIRECT_LOGIN_SCOPE_PENDING)
        self.assertEqual([account.key for account in pending_accounts], [accounts[8].key])

    def test_repair_current_batch_cancel_reopen_keeps_pid_missing_and_does_not_start_client(self) -> None:
        account = AccountConfig(
            "单层账号",
            9,
            9,
            "https://dldl.50pk.com/login.php?gid=1&pid=1&token=t&time=1&sign=s&isPcLauncher=true",
        )
        store = ClientBatchStore()
        batch = store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        store.append_binding(
            ClientBatchBinding(account.key, account.display_name, pid=9009, hwnd=0, cdp_port=9230, login_url=account.url, status="pid_missing")
        )
        fake = SimpleNamespace(
            accounts=[account],
            client_batch_store=store,
            client_direct_bindings={},
            logs=[],
            statuses=[],
            client_direct_batch_status_var=SimpleNamespace(set=lambda _value: None),
            client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
            client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"单层账号-9号 | {batch.batch_id}", set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))

        with (
            mock.patch("douluo_launcher.gui.messagebox.askyesno", side_effect=[True, False]),
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", return_value=False),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_cdp_available", return_value=True),
            mock.patch("douluo_launcher.gui.prepare_client_direct_client") as prepare,
        ):
            LauncherApp._repair_client_direct_current_batch(fake)

        prepare.assert_not_called()
        binding = store.current_batch().bindings[0]
        self.assertEqual(binding.status, "pid_missing")
        self.assertEqual(binding.pid, 9009)

    def test_repair_current_batch_reopens_pid_missing_with_new_port_when_original_is_occupied(self) -> None:
        account = AccountConfig(
            "单层账号",
            9,
            9,
            "https://dldl.50pk.com/login.php?gid=1&pid=1&token=t&time=1&sign=s&isPcLauncher=true",
        )
        store = ClientBatchStore()
        batch = store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        store.append_binding(ClientBatchBinding("alive", "活账号", pid=1001, hwnd=2001, cdp_port=9222, login_url="u", status="restored"))
        store.append_binding(
            ClientBatchBinding(account.key, account.display_name, pid=9009, hwnd=0, cdp_port=9230, login_url=account.url, status="pid_missing")
        )
        fake = SimpleNamespace(
            accounts=[account],
            client_batch_store=store,
            client_direct_bindings={},
            logs=[],
            statuses=[],
            stop_event=SimpleNamespace(is_set=lambda: False),
            _log_file=None,
            client_direct_batch_status_var=SimpleNamespace(set=lambda _value: None),
            client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
            client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"单层账号-9号 | {batch.batch_id}", set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._wm_game_exe_path_filter = mock.Mock(return_value=r"E:\Program Files\DLH5\X5Game.exe")

        def prepare_result(config, **_kwargs):
            return SimpleNamespace(
                success=True,
                message="客户端已启动，待登录",
                binding=SimpleNamespace(pid=3010, hwnd=4010, cdp_port=config.cdp_port),
            )

        with (
            mock.patch("douluo_launcher.gui.messagebox.askyesno", side_effect=[True, True]),
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", side_effect=lambda _self, pid: int(pid) != 9009),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_cdp_available", return_value=True),
            mock.patch("douluo_launcher.gui.wait_for_client_hwnd_by_pid", return_value=2001),
            mock.patch("douluo_launcher.gui.is_tcp_port_available", side_effect=lambda port: int(port) != 9230),
            mock.patch("douluo_launcher.gui.find_next_available_port_range", return_value=9231),
            mock.patch("douluo_launcher.gui.Path.exists", return_value=True),
            mock.patch("douluo_launcher.gui.prepare_client_direct_client", side_effect=prepare_result) as prepare,
        ):
            LauncherApp._repair_client_direct_current_batch(fake)

        self.assertEqual(prepare.call_args.args[0].cdp_port, 9231)
        binding = store.current_batch().bindings[1]
        self.assertEqual((binding.pid, binding.hwnd, binding.cdp_port), (3010, 4010, 9231))
        self.assertEqual(binding.status, "客户端已启动/待登录")

    def test_repair_current_batch_reopen_failure_logs_are_masked(self) -> None:
        login_url = "https://dldl.50pk.com/login.php?gid=1&pid=1&token=secret-token&time=1&sign=secret-sign&isPcLauncher=true"
        account = AccountConfig("单层账号", 9, 9, login_url)
        store = ClientBatchStore()
        batch = store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        store.append_binding(
            ClientBatchBinding(account.key, account.display_name, pid=9009, hwnd=0, cdp_port=9230, login_url=login_url, status="pid_missing")
        )
        fake = SimpleNamespace(
            accounts=[account],
            client_batch_store=store,
            client_direct_bindings={},
            logs=[],
            statuses=[],
            stop_event=SimpleNamespace(is_set=lambda: False),
            _log_file=None,
            client_direct_batch_status_var=SimpleNamespace(set=lambda _value: None),
            client_direct_base_port_var=SimpleNamespace(set=lambda _value: None),
            client_direct_port_range_var=SimpleNamespace(set=lambda _value: None),
            client_direct_batch_select_var=SimpleNamespace(get=lambda: f"单层账号-9号 | {batch.batch_id}", set=lambda _value: None),
            client_direct_batch_box=SimpleNamespace(configure=lambda **_kwargs: None),
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._wm_game_exe_path_filter = mock.Mock(return_value=r"E:\Program Files\DLH5\X5Game.exe")

        with (
            mock.patch("douluo_launcher.gui.messagebox.askyesno", side_effect=[True, True]),
            mock.patch.object(LauncherApp, "_client_direct_pid_exists", return_value=False),
            mock.patch.object(LauncherApp, "_client_direct_process_is_x5game", return_value=True),
            mock.patch.object(LauncherApp, "_client_direct_cdp_available", return_value=True),
            mock.patch("douluo_launcher.gui.is_tcp_port_available", return_value=True),
            mock.patch("douluo_launcher.gui.Path.exists", return_value=True),
            mock.patch(
                "douluo_launcher.gui.prepare_client_direct_client",
                return_value=SimpleNamespace(success=False, message=f"failed url={login_url}", binding=None),
            ),
        ):
            LauncherApp._repair_client_direct_current_batch(fake)

        joined_logs = "\n".join(fake.logs)
        self.assertNotIn("secret-token", joined_logs)
        self.assertNotIn("secret-sign", joined_logs)
        self.assertIn("token=***", joined_logs)
        self.assertIn("sign=***", joined_logs)

    def test_client_direct_login_scope_defaults_to_pending_accounts_only(self) -> None:
        accounts = [
            AccountConfig("单层账号", 1, 1, "https://example.com/1"),
            AccountConfig("单层账号", 9, 9, "https://example.com/9"),
        ]
        store = ClientBatchStore()
        store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        store.append_binding(ClientBatchBinding(accounts[0].key, accounts[0].display_name, pid=1001, hwnd=2001, cdp_port=9222, login_url=accounts[0].url, status="客户端登录成功"))
        store.append_binding(ClientBatchBinding(accounts[1].key, accounts[1].display_name, pid=1009, hwnd=2009, cdp_port=9230, login_url=accounts[1].url, status="客户端已启动/待登录"))
        fake = SimpleNamespace(
            accounts=accounts,
            client_batch_store=store,
            client_direct_bindings={},
            client_direct_auto_enter_var=SimpleNamespace(get=lambda: True),
            client_direct_concurrency_var=SimpleNamespace(get=lambda: 1, set=lambda _value: None),
            logs=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._start_client_direct_prepared_login_run = mock.Mock()

        LauncherApp._login_prepared_client_direct_current_scope(fake)

        fake._start_client_direct_prepared_login_run.assert_called_once()
        self.assertEqual([account.key for account in fake._start_client_direct_prepared_login_run.call_args.args[0]], [accounts[1].key])
        self.assertTrue(any("登录范围=待登录账号" in line and "本次登录账号数=1" in line for line in fake.logs))

    def test_client_direct_login_scope_selected_accounts_only_uses_tree_selection(self) -> None:
        accounts = [
            AccountConfig("单层账号", 1, 1, "https://example.com/1"),
            AccountConfig("单层账号", 9, 9, "https://example.com/9"),
        ]
        store = ClientBatchStore()
        store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        for index, account in enumerate(accounts, start=1):
            store.append_binding(ClientBatchBinding(account.key, account.display_name, pid=1000 + index, hwnd=2000 + index, cdp_port=9221 + index, login_url=account.url, status="客户端已启动/待登录"))
        fake = SimpleNamespace(
            accounts=accounts,
            client_batch_store=store,
            client_direct_bindings={},
            client_direct_login_scope_var=SimpleNamespace(get=lambda: "选中账号"),
            client_direct_auto_enter_var=SimpleNamespace(get=lambda: True),
            client_direct_concurrency_var=SimpleNamespace(get=lambda: 1, set=lambda _value: None),
            tree=SimpleNamespace(selection=lambda: (accounts[1].key,)),
            logs=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._start_client_direct_prepared_login_run = mock.Mock()

        LauncherApp._login_prepared_client_direct_current_scope(fake)

        self.assertEqual([account.key for account in fake._start_client_direct_prepared_login_run.call_args.args[0]], [accounts[1].key])

    def test_client_direct_login_scope_selected_accounts_requires_selection(self) -> None:
        account = AccountConfig("单层账号", 1, 1, "https://example.com/1")
        store = ClientBatchStore()
        store.create_batch("单层账号-9号", scope="当前层:单层账号", base_port=9222)
        store.append_binding(ClientBatchBinding(account.key, account.display_name, pid=1001, hwnd=2001, cdp_port=9222, login_url=account.url, status="客户端已启动/待登录"))
        fake = SimpleNamespace(
            accounts=[account],
            client_batch_store=store,
            client_direct_bindings={},
            client_direct_login_scope_var=SimpleNamespace(get=lambda: "选中账号"),
            tree=SimpleNamespace(selection=lambda: ()),
            logs=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._start_client_direct_prepared_login_run = mock.Mock()

        with mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning:
            LauncherApp._login_prepared_client_direct_current_scope(fake)

        warning.assert_called_once()
        self.assertIn("请先在账号列表中选择要登录的账号", warning.call_args.args[1])
        fake._start_client_direct_prepared_login_run.assert_not_called()

    def test_client_direct_login_scope_failed_and_all_accounts(self) -> None:
        accounts = [
            AccountConfig("单层账号", 1, 1, "https://example.com/1"),
            AccountConfig("单层账号", 2, 2, "https://example.com/2"),
            AccountConfig("单层账号", 3, 3, "https://example.com/3"),
        ]
        store = ClientBatchStore()
        store.create_batch("单层账号-3号", scope="当前层:单层账号", base_port=9222)
        statuses = ["客户端登录成功", "cdp_unavailable", "enter_game_failed"]
        for index, account in enumerate(accounts):
            store.append_binding(ClientBatchBinding(account.key, account.display_name, pid=1001 + index, hwnd=2001 + index, cdp_port=9222 + index, login_url=account.url, status=statuses[index]))
        fake = SimpleNamespace(
            accounts=accounts,
            client_batch_store=store,
            client_direct_bindings={},
            client_direct_login_scope_var=SimpleNamespace(get=lambda: "失败账号"),
            client_direct_auto_enter_var=SimpleNamespace(get=lambda: True),
            client_direct_concurrency_var=SimpleNamespace(get=lambda: 1, set=lambda _value: None),
            logs=[],
        )
        fake._log = lambda message: fake.logs.append(message)
        fake._start_client_direct_prepared_login_run = mock.Mock()

        LauncherApp._login_prepared_client_direct_current_scope(fake)
        self.assertEqual(
            [account.key for account in fake._start_client_direct_prepared_login_run.call_args.args[0]],
            [accounts[1].key, accounts[2].key],
        )

        fake._start_client_direct_prepared_login_run.reset_mock()
        fake.client_direct_login_scope_var = SimpleNamespace(get=lambda: "全部账号")
        LauncherApp._login_prepared_client_direct_current_scope(fake)
        self.assertEqual([account.key for account in fake._start_client_direct_prepared_login_run.call_args.args[0]], [account.key for account in accounts])

    def test_one_click_prepare_stops_before_arrange_and_login_when_ports_unavailable(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            client_direct_auto_enter_var=SimpleNamespace(get=lambda: True),
            client_direct_base_port_var=SimpleNamespace(get=lambda: 9222),
            logs=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=[account])
        fake._arrange_prepared_client_direct_current_scope = mock.Mock()
        fake._login_prepared_client_direct_current_scope = mock.Mock()
        fake._log = lambda message: fake.logs.append(message)

        with mock.patch.object(LauncherApp, "_start_client_direct_prepare_run", return_value=False) as start_prepare:
            LauncherApp._prepare_arrange_login_client_direct_current_scope(fake)

        start_prepare.assert_called_once()
        fake._arrange_prepared_client_direct_current_scope.assert_not_called()
        fake._login_prepared_client_direct_current_scope.assert_not_called()

    def test_client_direct_arrange_skips_invalid_hwnd_and_keeps_binding_data(self) -> None:
        accounts = [
            AccountConfig(
                "第一层",
                index,
                index,
                f"https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t{index}&time=123&sign=s{index}&isPcLauncher=true",
                include_in_all=True,
            )
            for index in range(1, 3)
        ]
        fake = SimpleNamespace(
            method_var=SimpleNamespace(get=lambda: "method1"),
            run_mode_var=SimpleNamespace(get=lambda: RUN_MODE_CLIENT_DIRECT_LABEL),
            level_var=SimpleNamespace(get=lambda: "第一层"),
            worker_thread=None,
            client_direct_bindings={
                accounts[0].key: ClientDirectRunRecord(
                    account_id=accounts[0].key,
                    account_name=accounts[0].display_name,
                    pid=2001,
                    hwnd=111,
                    cdp_port=9222,
                    login_url=accounts[0].url,
                    status="待登录",
                ),
                accounts[1].key: ClientDirectRunRecord(
                    account_id=accounts[1].key,
                    account_name=accounts[1].display_name,
                    pid=2002,
                    hwnd=222,
                    cdp_port=9223,
                    login_url=accounts[1].url,
                    status="待登录",
                ),
            },
            logs=[],
            statuses=[],
        )
        fake._filtered_accounts_for_ui = mock.Mock(return_value=accounts)
        fake._wm_read_arrangement_config = mock.Mock(
            return_value=("固定参数排列", TileConfig(width=800, height=600, start_x=0, start_y=0, offset_x=20, offset_y=20, per_row=2))
        )
        fake._save_window_manager_settings = mock.Mock(return_value=True)
        fake._log = lambda message: fake.logs.append(message)
        fake._set_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._wm_log_tile_results = mock.Mock()

        def tile_windows(_self, windows, *_args, **_kwargs):
            fake.arranged_hwnds = [window.hwnd for window in windows]
            return [
                SimpleNamespace(success=True, window=window, x=0, y=0, width=800, height=600, wrapped_by_screen=False)
                for window in windows
            ]

        with mock.patch("douluo_launcher.gui.user32.IsWindow", side_effect=lambda hwnd: int(hwnd) == 111), mock.patch(
            "douluo_launcher.gui.get_window_rect",
            return_value=WindowRect(10, 20, 810, 620),
        ), mock.patch.object(LauncherApp, "_client_direct_tile_binding_windows", side_effect=tile_windows):
            LauncherApp._arrange_prepared_client_direct_current_scope(fake)

        self.assertEqual(fake.arranged_hwnds, [111])
        self.assertIn((accounts[1].key, "窗口已失效"), fake.statuses)
        self.assertEqual(fake.client_direct_bindings[accounts[1].key].status, "窗口已失效")
        self.assertEqual(fake.client_direct_bindings[accounts[1].key].cdp_port, 9223)
        self.assertEqual(fake.client_direct_bindings[accounts[1].key].login_url, accounts[1].url)
        self.assertTrue(any("窗口已失效" in line and accounts[1].display_name in line for line in fake.logs))

    def test_client_direct_prepare_worker_reports_required_statuses(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://7tu7tu.com/dldl?genCode=true", include_in_all=True),
            AccountConfig(
                "第一层",
                2,
                2,
                "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t2&time=123&sign=s2&isPcLauncher=true",
                include_in_all=True,
            ),
        ]
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            client_direct_bindings={
                account.key: ClientDirectRunRecord(
                    account_id=account.key,
                    account_name=account.display_name,
                    cdp_port=9221 + index,
                    login_url=account.url,
                    status="待准备",
                )
                for index, account in enumerate(accounts, start=1)
            },
            logs=[],
            statuses=[],
            bars=[],
            file_logs=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._update_status_bar = lambda message: fake.bars.append(message)
        fake._write_file_log = lambda message: fake.file_logs.append(message)

        with mock.patch("douluo_launcher.gui.is_tcp_port_available", return_value=False), mock.patch(
            "douluo_launcher.gui.prepare_client_direct_client"
        ) as prepare:
            LauncherApp._client_direct_prepare_worker(
                fake,
                accounts,
                r"E:\Program Files\DLH5\X5Game.exe",
                "客户端准备当前层",
            )

        prepare.assert_not_called()
        self.assertIn((accounts[0].key, "URL无效"), fake.statuses)
        self.assertIn((accounts[1].key, "端口占用"), fake.statuses)
        self.assertEqual(fake.client_direct_bindings[accounts[0].key].status, "URL无效")
        self.assertEqual(fake.client_direct_bindings[accounts[1].key].status, "端口占用")

    def test_client_direct_prepare_worker_starts_clients_without_login(self) -> None:
        accounts = [
            AccountConfig(
                "第一层",
                index,
                index,
                f"https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t{index}&time=123&sign=s{index}&isPcLauncher=true",
                include_in_all=True,
            )
            for index in range(1, 3)
        ]
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            client_direct_bindings={
                account.key: ClientDirectRunRecord(
                    account_id=account.key,
                    account_name=account.display_name,
                    cdp_port=9221 + index,
                    login_url=account.url,
                status="待准备",
                )
                for index, account in enumerate(accounts, start=1)
            },
            logs=[],
            statuses=[],
            bars=[],
            file_logs=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._update_status_bar = lambda message: fake.bars.append(message)
        fake._write_file_log = lambda message: fake.file_logs.append(message)

        def prepare_result(config, **_kwargs):
            return SimpleNamespace(
                success=True,
                message="客户端已启动，待登录",
                binding=SimpleNamespace(pid=2000 + config.cdp_port, hwnd=3000 + config.cdp_port, cdp_port=config.cdp_port),
            )

        with mock.patch("douluo_launcher.gui.is_tcp_port_available", return_value=True), mock.patch(
            "douluo_launcher.gui.prepare_client_direct_client",
            side_effect=prepare_result,
        ) as prepare, mock.patch("douluo_launcher.gui.execute_prepared_client_direct_login") as execute:
            LauncherApp._client_direct_prepare_worker(
                fake,
                accounts,
                r"E:\Program Files\DLH5\X5Game.exe",
                "客户端准备当前层",
            )

        self.assertEqual([call.args[0].cdp_port for call in prepare.call_args_list], [9222, 9223])
        execute.assert_not_called()
        self.assertIn((accounts[0].key, "客户端已启动/待登录"), fake.statuses)
        self.assertIn((accounts[1].key, "客户端已启动/待登录"), fake.statuses)
        self.assertEqual(fake.client_direct_bindings[accounts[0].key].status, "客户端已启动/待登录")
        self.assertEqual(fake.client_direct_bindings[accounts[0].key].pid, 2000 + 9222)
        self.assertEqual(fake.client_direct_bindings[accounts[1].key].hwnd, 3000 + 9223)
        self.assertTrue(any("只启动客户端，不执行登录" in line for line in fake.logs))

    def test_client_direct_prepared_login_worker_uses_saved_binding_without_prepare(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            client_direct_bindings={
                account.key: ClientDirectRunRecord(
                    account_id=account.key,
                    account_name=account.display_name,
                    pid=2345,
                    hwnd=3456,
                    cdp_port=9222,
                    login_url=account.url,
                    status="待登录",
                )
            },
            logs=[],
            statuses=[],
            bars=[],
            file_logs=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda _account, status: fake.statuses.append(status)
        fake._update_status_bar = lambda message: fake.bars.append(message)
        fake._write_file_log = lambda message: fake.file_logs.append(message)

        result = SimpleNamespace(
            success=True,
            message="客户端已就绪，未自动进入游戏",
            binding=SimpleNamespace(pid=2345, hwnd=3456, cdp_port=9222),
        )
        with mock.patch.object(LauncherApp, "_client_direct_is_window_alive", return_value=True), mock.patch(
            "douluo_launcher.gui.prepare_client_direct_client"
        ) as prepare, mock.patch(
            "douluo_launcher.gui.execute_prepared_client_direct_login",
            return_value=result,
        ) as execute:
            LauncherApp._client_direct_prepared_login_worker(
                fake,
                [account],
                False,
                "客户端当前层登录",
            )

        prepare.assert_not_called()
        self.assertEqual(execute.call_args.args[0].cdp_port, 9222)
        self.assertEqual(execute.call_args.args[0].full_login_url, account.url)
        self.assertEqual(execute.call_args.args[1].pid, 2345)
        self.assertEqual(execute.call_args.args[1].hwnd, 3456)
        self.assertEqual(execute.call_args.args[1].login_url, account.url)
        self.assertEqual(fake.statuses, ["登录中", "客户端已就绪"])
        self.assertEqual(fake.client_direct_bindings[account.key].status, "客户端已就绪")

    def test_client_direct_prepared_login_worker_marks_closed_window_before_cdp(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            client_direct_bindings={
                account.key: ClientDirectRunRecord(
                    account_id=account.key,
                    account_name=account.display_name,
                    pid=2345,
                    hwnd=3456,
                    cdp_port=9222,
                    login_url=account.url,
                    status="待登录",
                )
            },
            logs=[],
            statuses=[],
            bars=[],
            file_logs=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda _account, status: fake.statuses.append(status)
        fake._update_status_bar = lambda message: fake.bars.append(message)
        fake._write_file_log = lambda message: fake.file_logs.append(message)

        with mock.patch.object(LauncherApp, "_client_direct_is_window_alive", return_value=False), mock.patch(
            "douluo_launcher.gui.execute_prepared_client_direct_login"
        ) as execute:
            LauncherApp._client_direct_prepared_login_worker(
                fake,
                [account],
                True,
                "客户端当前层登录",
            )

        execute.assert_not_called()
        self.assertEqual(fake.statuses, ["客户端已关闭"])
        self.assertEqual(fake.client_direct_bindings[account.key].status, "客户端已关闭")

    def test_client_direct_prepared_login_worker_updates_progress_statuses_from_cdp_log(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            client_direct_bindings={
                account.key: ClientDirectRunRecord(
                    account_id=account.key,
                    account_name=account.display_name,
                    pid=2345,
                    hwnd=3456,
                    cdp_port=9222,
                    login_url=account.url,
                    status="待登录",
                )
            },
            logs=[],
            statuses=[],
            bars=[],
            file_logs=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda _account, status: fake.statuses.append(status)
        fake._update_status_bar = lambda message: fake.bars.append(message)
        fake._write_file_log = lambda message: fake.file_logs.append(message)

        result = SimpleNamespace(
            success=True,
            message="client direct login success",
            binding=SimpleNamespace(pid=2345, hwnd=3456, cdp_port=9222),
        )

        def execute(_config, _binding, *, log, **_kwargs):
            log("importServer success")
            log("enterGame called")
            return result

        with mock.patch.object(LauncherApp, "_client_direct_is_window_alive", return_value=True), mock.patch(
            "douluo_launcher.gui.execute_prepared_client_direct_login",
            side_effect=execute,
        ):
            LauncherApp._client_direct_prepared_login_worker(
                fake,
                [account],
                True,
                "客户端当前层登录",
            )

        self.assertEqual(fake.statuses, ["登录中", "importServer成功", "进入游戏中", "客户端登录成功"])

    def test_client_direct_worker_reports_ready_without_auto_enter(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            timing_by_key={},
            logs=[],
            statuses=[],
            timings=[],
            bars=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda _account, status: fake.statuses.append(status)
        fake._queue_timing = lambda _account, seconds: fake.timings.append(seconds)
        fake._update_status_bar = lambda message: fake.bars.append(message)

        result = SimpleNamespace(success=True, message="客户端已就绪，未自动进入游戏", process=None)
        with mock.patch("douluo_launcher.gui.execute_client_direct_login", return_value=result) as execute:
            LauncherApp._client_direct_single_worker(fake, account, r"E:\Program Files\DLH5\X5Game.exe", False)

        self.assertEqual(fake.statuses, ["客户端已就绪"])
        self.assertTrue(any("客户端已就绪" in line for line in fake.logs))
        self.assertTrue(any("客户端直登完成：客户端已就绪" in line for line in fake.bars))
        self.assertFalse(execute.call_args.args[0].auto_enter_game)

    def test_client_direct_worker_reports_login_success_with_auto_enter(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            timing_by_key={},
            logs=[],
            statuses=[],
            timings=[],
            bars=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda _account, status: fake.statuses.append(status)
        fake._queue_timing = lambda _account, seconds: fake.timings.append(seconds)
        fake._update_status_bar = lambda message: fake.bars.append(message)

        result = SimpleNamespace(success=True, message="client direct login success", process=None)
        with mock.patch("douluo_launcher.gui.execute_client_direct_login", return_value=result) as execute:
            LauncherApp._client_direct_single_worker(fake, account, r"E:\Program Files\DLH5\X5Game.exe", True)

        self.assertEqual(fake.statuses, ["客户端登录成功"])
        self.assertTrue(any("客户端登录成功" in line for line in fake.logs))
        self.assertTrue(execute.call_args.args[0].auto_enter_game)

    def test_client_direct_worker_reports_failure_with_masked_reason(self) -> None:
        account = AccountConfig(
            "第一层",
            1,
            1,
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            include_in_all=True,
        )
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            timing_by_key={},
            logs=[],
            statuses=[],
            timings=[],
            bars=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda _account, status: fake.statuses.append(status)
        fake._queue_timing = lambda _account, seconds: fake.timings.append(seconds)
        fake._update_status_bar = lambda message: fake.bars.append(message)

        result = SimpleNamespace(success=False, message="bad token=secret&sign=abcdef", process=None)
        with mock.patch("douluo_launcher.gui.execute_client_direct_login", return_value=result):
            LauncherApp._client_direct_single_worker(fake, account, r"E:\Program Files\DLH5\X5Game.exe", True)

        self.assertEqual(fake.statuses, ["客户端直登失败"])
        joined_logs = "\n".join(fake.logs)
        self.assertIn("客户端直登失败", joined_logs)
        self.assertNotIn("secret", joined_logs)
        self.assertNotIn("abcdef", joined_logs)

    def test_client_direct_serial_worker_assigns_ports_and_continues_after_failure(self) -> None:
        accounts = [
            AccountConfig(
                "第一层",
                index,
                index,
                f"https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t{index}&time=123&sign=s{index}&isPcLauncher=true",
                include_in_all=True,
            )
            for index in range(1, 4)
        ]
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            client_direct_bindings={
                account.key: SimpleNamespace(
                    account_id=account.key,
                    account_name=account.display_name,
                    pid=0,
                    hwnd=0,
                    cdp_port=0,
                    login_url=account.url,
                    status="等待中",
                )
                for account in accounts
            },
            timing_by_key={},
            logs=[],
            statuses=[],
            timings=[],
            bars=[],
            file_logs=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._queue_timing = lambda account, seconds: fake.timings.append((account.key, seconds))
        fake._update_status_bar = lambda message: fake.bars.append(message)
        fake._write_file_log = lambda message: fake.file_logs.append(message)
        fake._update_client_direct_binding_from_result = (
            lambda account, result, port, status: fake.client_direct_bindings.__setitem__(
                account.key,
                SimpleNamespace(
                    account_id=account.key,
                    account_name=account.display_name,
                    pid=int(getattr(result.binding, "pid", 0) or 0),
                    hwnd=int(getattr(result.binding, "hwnd", 0) or 0),
                    cdp_port=port,
                    login_url=account.url,
                    status=status,
                ),
            )
        )

        def run_result(config, **_kwargs):
            if config.account_id.endswith("-2"):
                return SimpleNamespace(
                    success=False,
                    message="bad token=secret&sign=abcdef",
                    binding=SimpleNamespace(pid=2002, hwnd=3002, cdp_port=config.cdp_port),
                )
            return SimpleNamespace(
                success=True,
                message="客户端已就绪，未自动进入游戏",
                binding=SimpleNamespace(pid=2000 + config.cdp_port, hwnd=3000 + config.cdp_port, cdp_port=config.cdp_port),
            )

        with mock.patch("douluo_launcher.gui.is_tcp_port_available", return_value=True), mock.patch(
            "douluo_launcher.gui.execute_client_direct_login",
            side_effect=run_result,
        ) as execute:
            LauncherApp._client_direct_serial_worker(
                fake,
                accounts,
                r"E:\Program Files\DLH5\X5Game.exe",
                False,
                "客户端当前层串行",
            )

        self.assertEqual(execute.call_count, 3)
        self.assertEqual([call.args[0].cdp_port for call in execute.call_args_list], [9222, 9223, 9224])
        self.assertEqual([call.args[0].auto_enter_game for call in execute.call_args_list], [False, False, False])
        self.assertIn((accounts[0].key, "客户端已就绪"), fake.statuses)
        self.assertIn((accounts[1].key, "客户端直登失败"), fake.statuses)
        self.assertIn((accounts[2].key, "客户端已就绪"), fake.statuses)
        self.assertEqual(fake.client_direct_bindings[accounts[0].key].cdp_port, 9222)
        self.assertEqual(fake.client_direct_bindings[accounts[1].key].status, "客户端直登失败")
        joined_logs = "\n".join(fake.logs)
        self.assertIn("成功2，失败1", joined_logs)
        self.assertNotIn("secret", joined_logs)
        self.assertNotIn("abcdef", joined_logs)

    def test_client_direct_serial_worker_auto_enter_reports_login_success(self) -> None:
        accounts = [
            AccountConfig(
                "第一层",
                1,
                1,
                "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
                include_in_all=True,
            )
        ]
        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
            client_direct_bindings={
                accounts[0].key: SimpleNamespace(
                    account_id=accounts[0].key,
                    account_name=accounts[0].display_name,
                    pid=0,
                    hwnd=0,
                    cdp_port=9222,
                    login_url=accounts[0].url,
                    status="等待中",
                )
            },
            timing_by_key={},
            logs=[],
            statuses=[],
            timings=[],
            bars=[],
            file_logs=[],
            _log_file=None,
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._queue_status = lambda account, status: fake.statuses.append((account.key, status))
        fake._queue_timing = lambda account, seconds: fake.timings.append((account.key, seconds))
        fake._update_status_bar = lambda message: fake.bars.append(message)
        fake._write_file_log = lambda message: fake.file_logs.append(message)
        fake._update_client_direct_binding_from_result = (
            lambda account, result, port, status: fake.client_direct_bindings.__setitem__(
                account.key,
                SimpleNamespace(
                    account_id=account.key,
                    account_name=account.display_name,
                    pid=int(getattr(result.binding, "pid", 0) or 0),
                    hwnd=int(getattr(result.binding, "hwnd", 0) or 0),
                    cdp_port=port,
                    login_url=account.url,
                    status=status,
                ),
            )
        )
        result = SimpleNamespace(
            success=True,
            message="client direct login success",
            binding=SimpleNamespace(pid=2001, hwnd=3001, cdp_port=9222),
        )
        with mock.patch("douluo_launcher.gui.is_tcp_port_available", return_value=True), mock.patch(
            "douluo_launcher.gui.execute_client_direct_login",
            return_value=result,
        ) as execute:
            LauncherApp._client_direct_serial_worker(
                fake,
                accounts,
                r"E:\Program Files\DLH5\X5Game.exe",
                True,
                "客户端当前层串行",
            )

        self.assertTrue(execute.call_args.args[0].auto_enter_game)
        self.assertIn((accounts[0].key, "客户端登录成功"), fake.statuses)
        self.assertEqual(fake.client_direct_bindings[accounts[0].key].status, "客户端登录成功")

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

    def test_background_serial_worker_does_not_count_unverified_result_as_success(self) -> None:
        accounts = [AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True)]

        class FakeRunner:
            def __init__(self, account, settings, stop_event, log, update_status, passport_found):
                self.account = account
                self.update_status = update_status

            def run(self) -> BackgroundLoginResult:
                self.update_status(self.account, "失败")
                return BackgroundLoginResult(
                    status="failed",
                    success=False,
                    reason="final verification failed",
                    final_verified=False,
                )

        fake = SimpleNamespace(
            stop_event=SimpleNamespace(is_set=lambda: False),
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

        self.assertIn((1, "失败"), fake.statuses)
        self.assertTrue(any("窗口1：失败" in line for line in fake.logs))
        self.assertTrue(any("成功0，跳过0，失败1" in line for line in fake.logs))

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
        self.assertEqual((GUI_DEFAULT_WIDTH, GUI_DEFAULT_HEIGHT), (1160, 940))
        self.assertEqual((GUI_MIN_WIDTH, GUI_MIN_HEIGHT), (1080, 820))
        source = inspect.getsource(LauncherApp.__init__)

        self.assertIn("GUI_DEFAULT_WIDTH", source)
        self.assertIn("GUI_DEFAULT_HEIGHT", source)
        self.assertIn("self.minsize(GUI_MIN_WIDTH, GUI_MIN_HEIGHT)", source)

    def test_log_panel_defaults_to_collapsed_toolbar_height(self) -> None:
        self.assertEqual(LOG_TEXT_VISIBLE_LINES, 8)
        self.assertEqual(LOG_PANEL_COLLAPSED_HEIGHT, 42)
        self.assertGreaterEqual(LOG_PANEL_EXPANDED_HEIGHT, 120)
        self.assertLessEqual(LOG_PANEL_EXPANDED_HEIGHT, 170)
        self.assertEqual(LOG_PANEL_MIN_HEIGHT, LOG_PANEL_EXPANDED_HEIGHT)
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertIn("self._content_area.rowconfigure(0, weight=1)", source)
        self.assertIn("self._content_area.rowconfigure(1, weight=0, minsize=LOG_PANEL_COLLAPSED_HEIGHT)", source)
        self.assertIn("self._table_frame_m1.grid(row=0", source)
        self.assertIn("self._log_outer.grid(row=1", source)
        self.assertIn("self.log_panel_expanded = tk.BooleanVar(value=False)", source)
        self.assertIn("self._log_outer = ttk.Frame(self._content_area, padding=2)", source)
        self.assertIn("self._log_outer.configure(height=LOG_PANEL_COLLAPSED_HEIGHT)", source)
        self.assertIn('ttk.Label(log_header, text="日志")', source)
        self.assertIn("self._log_outer.grid_propagate(False)", source)
        self.assertIn("self._log_outer.rowconfigure(1, weight=1)", source)
        self.assertIn("self._log_text_frame.grid(row=1", source)
        self.assertIn("self._sync_log_panel_visibility()", source)
        self.assertIn("height=LOG_TEXT_VISIBLE_LINES", source)

    def test_log_directory_button_stays_in_log_header_right_side(self) -> None:
        source = inspect.getsource(LauncherApp._build_widgets)

        self.assertIn('text="打开日志目录"', source)
        self.assertIn('text="展开日志"', source)
        self.assertIn("pack(side=tk.RIGHT", source)

    def test_log_append_scrolls_to_bottom(self) -> None:
        source = inspect.getsource(LauncherApp._log)

        self.assertIn("self.log_text.insert(tk.END", source)
        self.assertIn("self.log_text.see(tk.END)", source)

    def test_log_panel_toggle_switches_body_and_height_without_clearing_text(self) -> None:
        class BoolVar:
            def __init__(self) -> None:
                self.value = False

            def get(self) -> bool:
                return self.value

            def set(self, value: bool) -> None:
                self.value = bool(value)

        class FakeContentArea:
            def __init__(self) -> None:
                self.row_heights: list[int] = []

            def rowconfigure(self, _row: int, **kwargs) -> None:
                self.row_heights.append(int(kwargs["minsize"]))

        class FakeOuter:
            def __init__(self) -> None:
                self.heights: list[int] = []

            def configure(self, **kwargs) -> None:
                self.heights.append(int(kwargs["height"]))

        class FakeFrame:
            def __init__(self) -> None:
                self.visible = True
                self.grid_calls = 0
                self.remove_calls = 0

            def grid(self, **_kwargs) -> None:
                self.visible = True
                self.grid_calls += 1

            def grid_remove(self) -> None:
                self.visible = False
                self.remove_calls += 1

        class FakeButton:
            def __init__(self) -> None:
                self.texts: list[str] = []

            def configure(self, **kwargs) -> None:
                self.texts.append(str(kwargs["text"]))

        class FakeLogText:
            def __init__(self) -> None:
                self.lines: list[str] = []
                self.see_calls = 0

            def insert(self, _where, text: str) -> None:
                self.lines.append(text)

            def see(self, _where) -> None:
                self.see_calls += 1

        fake = SimpleNamespace(
            log_panel_expanded=BoolVar(),
            _content_area=FakeContentArea(),
            _log_outer=FakeOuter(),
            _log_text_frame=FakeFrame(),
            log_toggle_btn=FakeButton(),
            log_text=FakeLogText(),
            written=[],
        )
        fake._write_file_log = lambda message: fake.written.append(message)
        fake._sync_log_panel_visibility = lambda: LauncherApp._sync_log_panel_visibility(fake)

        LauncherApp._sync_log_panel_visibility(fake)
        self.assertFalse(fake._log_text_frame.visible)
        self.assertEqual(fake._content_area.row_heights[-1], LOG_PANEL_COLLAPSED_HEIGHT)
        self.assertEqual(fake._log_outer.heights[-1], LOG_PANEL_COLLAPSED_HEIGHT)
        self.assertEqual(fake.log_toggle_btn.texts[-1], "展开日志")

        LauncherApp._log(fake, "hidden line")
        self.assertEqual(fake.log_text.lines, ["hidden line\n"])
        self.assertEqual(fake.log_text.see_calls, 1)

        LauncherApp._toggle_log_panel(fake)
        self.assertTrue(fake._log_text_frame.visible)
        self.assertEqual(fake._content_area.row_heights[-1], LOG_PANEL_EXPANDED_HEIGHT)
        self.assertEqual(fake._log_outer.heights[-1], LOG_PANEL_EXPANDED_HEIGHT)
        self.assertEqual(fake.log_toggle_btn.texts[-1], "收起日志")
        self.assertEqual(fake.log_text.lines, ["hidden line\n"])

        LauncherApp._toggle_log_panel(fake)
        self.assertFalse(fake._log_text_frame.visible)
        self.assertEqual(fake._content_area.row_heights[-1], LOG_PANEL_COLLAPSED_HEIGHT)
        self.assertEqual(fake.log_toggle_btn.texts[-1], "展开日志")

    def test_account_table_values_match_declared_column_order(self) -> None:
        account = AccountConfig(
            "存钻",
            3,
            3,
            "https://dldl.50pk.com/login.php?gid=1&pid=1&token=secret&time=1&sign=signvalue&isPcLauncher=true",
            bookmark_title="Z3",
            include_in_all=False,
        )

        values = _account_table_values(account, passport="d40786fa", status="成功", timing="8.1s")

        self.assertEqual(len(values), len(ACCOUNT_TABLE_COLUMNS))
        self.assertEqual(values[ACCOUNT_TABLE_COLUMN_INDEX["include_in_all"]], "否")
        self.assertEqual(values[ACCOUNT_TABLE_COLUMN_INDEX["passport"]], "d40786fa")
        self.assertEqual(values[ACCOUNT_TABLE_COLUMN_INDEX["url"]], "dldl.50pk.com /login.php 参数完整")
        self.assertEqual(values[ACCOUNT_TABLE_COLUMN_INDEX["status"]], "成功")
        self.assertEqual(values[ACCOUNT_TABLE_COLUMN_INDEX["timing"]], "8.1s")

    def test_account_url_display_masks_login_query_parameters(self) -> None:
        display = _account_url_display_value(
            "https://dldl.50pk.com/login.php?gid=1&pid=1&token=secret&time=1&sign=signvalue&isPcLauncher=true"
        )

        self.assertEqual(display, "dldl.50pk.com /login.php 参数完整")
        self.assertNotIn("secret", display)
        self.assertNotIn("signvalue", display)

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
