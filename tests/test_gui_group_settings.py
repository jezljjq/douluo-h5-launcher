import unittest
from types import SimpleNamespace
from unittest import mock

from douluo_launcher.config import AccountConfig
from douluo_launcher.gui import (
    ACCOUNT_TABLE_COLUMN_INDEX,
    ACCOUNT_TABLE_COLUMNS,
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
