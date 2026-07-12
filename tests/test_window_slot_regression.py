import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

if sys.platform != "win32":
    raise unittest.SkipTest("window slot regression tests target the Windows launcher")

from douluo_launcher.config import AccountConfig, load_accounts_from_bookmarks
from douluo_launcher.gui import (
    ACCOUNT_TABLE_COLUMN_INDEX,
    ACCOUNT_TABLE_COLUMNS,
    LauncherApp,
    WM_TILE_MODE_FIXED,
    _account_table_values,
    _build_serial_run_plan,
    _compact_number_ranges,
    _split_all_serial_accounts,
)
from douluo_launcher.window_manager import (
    GameWindow,
    LaunchResult,
    SlotEnvironment,
    SlotLayoutParams,
    TileConfig,
    TileResult,
    WindowRect,
    check_window_slots_compatibility,
    layout_params_from_tile_config,
    load_window_slots,
    refresh_window_slots_from_current_windows,
    repair_window_slot,
    save_current_windows_as_slots,
)


def _slot_payload(count: int, missing: set[int] | None = None) -> dict[str, object]:
    missing = missing or set()
    return {
        "version": 1,
        "slots": {
            str(index): {
                "slot_no": index,
                "title": f"斗罗大陆H5-{index}号",
                "hwnd": 1000 + index,
                "x": 250 + ((index - 1) % 8) * 320,
                "y": ((index - 1) // 8) * 525,
                "width": 320,
                "height": 540,
                "account_layer": "存钻" if index == 1 else "",
                "account_index": index if index == 1 else None,
                "status": "正常",
            }
            for index in range(1, count + 1)
            if index not in missing
        },
    }


def _window(number: int, hwnd: int | None = None) -> GameWindow:
    hwnd = hwnd if hwnd is not None else 2000 + number
    return GameWindow(
        hwnd=hwnd,
        title=f"斗罗大陆H5-{number}号",
        number=number,
        rect=WindowRect(
            250 + ((number - 1) % 8) * 320,
            ((number - 1) // 8) * 525,
            250 + ((number - 1) % 8) * 320 + 320,
            ((number - 1) // 8) * 525 + 540,
        ),
    )


class WindowSlotRegressionTests(unittest.TestCase):
    def test_incomplete_30_windows_cannot_overwrite_31_slot_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps(_slot_payload(31), ensure_ascii=False), encoding="utf-8")
            windows_30 = [_window(index) for index in range(1, 32) if index != 29]

            with mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=windows_30):
                with self.assertRaisesRegex(ValueError, "目标 31，当前 30"):
                    save_current_windows_as_slots(path, expected_count=31)
                with self.assertRaisesRegex(ValueError, "目标 31，当前 30"):
                    refresh_window_slots_from_current_windows(path, expected_count=31)

            slots = load_window_slots(path)
            self.assertEqual(len(slots), 31)
            self.assertEqual(next(slot for slot in slots if slot.slot_no == 29).hwnd, 1029)

    def test_repair_missing_slot_updates_only_target_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps(_slot_payload(31, missing={29}), ensure_ascii=False), encoding="utf-8")
            current_29 = _window(29, hwnd=9029)

            with (
                mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=[current_29]),
                mock.patch("douluo_launcher.window_manager.user32.IsWindow", return_value=False),
                mock.patch("douluo_launcher.window_manager.launch_game_process") as launch,
            ):
                result = repair_window_slot(29, "D:/dummy/game.exe", slots_path=path)

            self.assertTrue(result.success)
            self.assertEqual(result.slot.slot_no, 29)
            self.assertEqual(result.slot.status, "已存在")
            launch.assert_not_called()

            slots = load_window_slots(path)
            self.assertEqual(len(slots), 31)
            self.assertEqual(next(slot for slot in slots if slot.slot_no == 29).hwnd, 9029)
            self.assertEqual(next(slot for slot in slots if slot.slot_no == 1).account_layer, "存钻")
            self.assertEqual(next(slot for slot in slots if slot.slot_no == 30).hwnd, 1030)

    def test_new_session_auto_arrange_does_not_validate_old_profile(self) -> None:
        layout_params = layout_params_from_tile_config(
            TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8),
            title_template="斗罗大陆H5-{index}号",
            target_window_count=31,
        )
        windows_31 = [_window(index) for index in range(1, 32)]
        fake = SimpleNamespace(
            logs=[],
            busy_states=[],
            validate_calls=0,
            tile_calls=0,
            rename_force_global=None,
            slot_path=Path(tempfile.gettempdir()) / "new_session_regression_slots.json",
        )

        def queue_log(message: str) -> None:
            fake.logs.append(message)

        def validate_slot_profile(**kwargs) -> bool:
            fake.validate_calls += 1
            return False

        def run_tile(**kwargs):
            fake.tile_calls += 1
            return []

        def rename_after_tile(**kwargs) -> None:
            fake.rename_force_global = kwargs.get("force_global")

        def save_slots(**kwargs):
            fake.saved_expected_count = kwargs.get("expected_count")
            return []

        fake._queue_log = queue_log
        fake._wm_wait_for_windows_stable = lambda **kwargs: (True, kwargs["target_count"])
        fake._wm_has_saved_slots = lambda layout: True
        fake._wm_validate_slot_profile = validate_slot_profile
        fake._wm_slots_path = lambda layout: fake.slot_path
        fake._wm_run_tile = run_tile
        fake._wm_log_tile_results = lambda results, log: None
        fake._wm_rename_windows_after_tile = rename_after_tile
        fake.after = lambda delay, callback: callback()
        fake._wm_set_actions_busy = lambda busy: fake.busy_states.append(busy)

        with (
            mock.patch("douluo_launcher.gui.list_game_windows", side_effect=[[]] + [windows_31] * 32),
            mock.patch(
                "douluo_launcher.gui.launch_game_process",
                return_value=LaunchResult(game_path="D:/dummy/game.exe", success=True, shell_result=0),
            ) as launch,
            mock.patch("douluo_launcher.gui.restore_windows_by_slots") as restore,
            mock.patch("douluo_launcher.gui.save_current_windows_as_slots", side_effect=save_slots),
        ):
            LauncherApp._wm_launch_windows_worker(
                fake,
                "D:/dummy/game.exe",
                31,
                0,
                True,
                True,
                WM_TILE_MODE_FIXED,
                TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8),
                "斗罗大陆H5-{index}号",
                layout_params,
                [],
            )

        self.assertEqual(launch.call_count, 31)
        self.assertEqual(fake.validate_calls, 0)
        restore.assert_not_called()
        self.assertEqual(fake.tile_calls, 1)
        self.assertIs(fake.rename_force_global, True)
        self.assertEqual(fake.saved_expected_count, 31)
        self.assertIn(False, fake.busy_states)

    def test_profile_9_row_count_cannot_restore_31_fixed_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            payload = _slot_payload(9)
            payload["environment"] = {
                "screen_width": 2560,
                "screen_height": 1440,
                "dpi": 96,
                "scale": 1.0,
                "profile": "2560x1440_100",
            }
            payload["layout_params"] = {
                "mode": "row_count",
                "target_window_count": 9,
                "window_width": 768,
                "window_height": 1056,
                "per_row": 5,
                "start_x": 0,
                "start_y": 0,
                "offset_x": None,
                "offset_y": None,
                "title_template": "斗罗大陆H5-{index}号",
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            current_layout = layout_params_from_tile_config(
                TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8),
                title_template="斗罗大陆H5-{index}号",
                target_window_count=31,
            )

            with mock.patch(
                "douluo_launcher.window_manager.get_current_slot_environment",
                return_value=SlotEnvironment(2560, 1440, 96, 1.0, "2560x1440_100"),
            ):
                result = check_window_slots_compatibility(path, current_layout, current_window_count=31)

        self.assertFalse(result.compatible)
        self.assertTrue(any("排列方式变化" in warning for warning in result.warnings))
        self.assertTrue(any("目标窗口数量变化" in warning for warning in result.warnings))
        self.assertTrue(any("槽位数量变化" in warning for warning in result.warnings))

    def test_batch_launch_is_blocked_when_target_windows_already_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game_path = Path(tmp) / "game.exe"
            game_path.write_text("", encoding="utf-8")
            fake = SimpleNamespace(
                wm_launch_thread=None,
                wm_action_thread=None,
                wm_game_path_var=SimpleNamespace(get=lambda: str(game_path)),
                wm_launch_count_var=SimpleNamespace(get=lambda: 31),
                wm_launch_interval_var=SimpleNamespace(get=lambda: 0),
                logs=[],
            )
            fake._wm_has_running_action = lambda: False
            fake._log = lambda message: fake.logs.append(message)
            fake._wm_excluded_hwnds = lambda: []
            fake._save_window_manager_settings = mock.Mock()

            with (
                mock.patch("douluo_launcher.gui.list_game_windows", return_value=[_window(index) for index in range(1, 32)]),
                mock.patch("douluo_launcher.gui.messagebox.showwarning") as warning,
            ):
                LauncherApp._wm_launch_windows(fake)

            fake._save_window_manager_settings.assert_not_called()
            warning.assert_called_once()
            self.assertIn("当前已检测到 31 个窗口", warning.call_args.args[1])
            self.assertIsNone(fake.wm_launch_thread)

    def test_regenerate_slots_does_not_save_when_move_fails(self) -> None:
        layout_params = layout_params_from_tile_config(
            TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8),
            title_template="斗罗大陆H5-{index}号",
            target_window_count=31,
        )
        failed = TileResult(
            window=_window(1),
            x=250,
            y=0,
            success=False,
            error="窗口移动失败：Windows 拒绝访问。",
            width=320,
            height=540,
        )
        fake = SimpleNamespace(
            logs=[],
            wm_auto_rename_after_tile_var=SimpleNamespace(get=lambda: True),
            slot_path=Path(tempfile.gettempdir()) / "failed_move_profile.json",
        )
        fake._queue_log = lambda message: fake.logs.append(message)
        fake._wm_slots_path = lambda layout: fake.slot_path
        fake._wm_run_tile = lambda **kwargs: [failed]
        fake._wm_log_tile_results = lambda results, log: [log(result.error) for result in results if not result.success]
        fake._wm_rename_windows_after_tile = mock.Mock()
        fake.after = lambda delay, callback: callback()
        fake._wm_set_actions_busy = lambda busy: None

        with (
            mock.patch("douluo_launcher.gui.save_current_windows_as_slots") as save_slots,
            mock.patch("douluo_launcher.gui.messagebox.showerror") as show_error,
        ):
            LauncherApp._wm_regenerate_slots_worker(
                fake,
                WM_TILE_MODE_FIXED,
                TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8),
                [],
                layout_params,
                31,
                "D:/dummy/game.exe",
            )

        save_slots.assert_not_called()
        fake._wm_rename_windows_after_tile.assert_not_called()
        show_error.assert_called_once()
        self.assertTrue(any("未写入槽位" in line for line in fake.logs))

    def test_all_serial_plan_reports_missing_windows_before_any_run(self) -> None:
        accounts = [
            AccountConfig("存钻", index, index, f"https://example.com/z{index}", include_in_all=False)
            for index in range(1, 10)
        ] + [
            AccountConfig("第一层", index, 9 + index, f"https://example.com/l1-{index}", include_in_all=True)
            for index in range(1, 9)
        ]

        enabled, skipped = _split_all_serial_accounts(accounts)
        current_plan = _build_serial_run_plan(
            [account for account in accounts if account.level == "存钻"],
            visible_window_numbers=list(range(1, 10)),
        )
        all_plan = _build_serial_run_plan(enabled, visible_window_numbers=list(range(1, 10)))

        self.assertEqual([account.level for account in skipped], ["存钻"] * 9)
        self.assertEqual(current_plan.required_windows, tuple(range(1, 10)))
        self.assertEqual(current_plan.missing_windows, ())
        self.assertEqual(_compact_number_ranges(all_plan.required_windows), "10-17")
        self.assertEqual(_compact_number_ranges(all_plan.missing_windows), "10-17")

    def test_table_values_stay_aligned_with_declared_columns(self) -> None:
        account = AccountConfig("存钻", 2, 2, "https://example.com/z2", bookmark_title="z2", include_in_all=True)

        values = _account_table_values(account, window_title="斗罗大陆H5-2号", passport="14332db4", status="成功", timing="2.4s")

        self.assertEqual(set(ACCOUNT_TABLE_COLUMN_INDEX), set(ACCOUNT_TABLE_COLUMNS))
        self.assertEqual(len(values), len(ACCOUNT_TABLE_COLUMNS))
        row = dict(zip(ACCOUNT_TABLE_COLUMNS, values, strict=True))
        self.assertEqual(row["include_in_all"], "是")
        self.assertEqual(row["window_title"], "斗罗大陆H5-2号")
        self.assertEqual(row["status"], "成功")

    def test_bookmark_custom_group_order_and_include_in_all_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bookmarks = Path(tmp) / "Bookmarks"
            bookmarks.write_text(
                """
{
  "roots": {
    "bookmark_bar": {
      "type": "folder",
      "name": "收藏夹栏",
      "children": [
        {
          "type": "folder",
          "name": "账号",
          "children": [
            {"type": "folder", "name": "存钻", "children": [
              {"type": "url", "name": "z1", "url": "https://7tu7tu.com/dldl?g=1"},
              {"type": "url", "name": "z2", "url": "https://7tu7tu.com/dldl?g=2"},
              {"type": "url", "name": "z9", "url": "https://7tu7tu.com/dldl?g=9"}
            ]},
            {"type": "folder", "name": "第一层", "children": [
              {"type": "url", "name": "1", "url": "https://7tu7tu.com/dldl?g=10"}
            ]}
          ]
        }
      ]
    }
  }
}
""",
                encoding="utf-8",
            )

            accounts = load_accounts_from_bookmarks(
                bookmarks,
                "账号",
                account_group_settings={
                    "存钻": {"include_in_all": False},
                    "第一层": {"include_in_all": True},
                },
            )

        cunduan = [account for account in accounts if account.level == "存钻"]
        enabled, skipped = _split_all_serial_accounts(accounts)

        self.assertEqual([account.bookmark_title for account in cunduan], ["z1", "z2", "z9"])
        self.assertEqual([account.bookmark_no for account in cunduan], [1, 2, 3])
        self.assertEqual([account.game_window_no for account in cunduan], [1, 2, 3])
        self.assertFalse(any(account.include_in_all for account in cunduan))
        self.assertEqual([account.level for account in enabled], ["第一层"])
        self.assertEqual([account.bookmark_title for account in skipped], ["z1", "z2", "z9"])


if __name__ == "__main__":
    unittest.main()
