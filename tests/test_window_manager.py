import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if sys.platform != "win32":
    raise unittest.SkipTest("window_manager uses user32 and only runs on Windows")

from douluo_launcher.window_manager import (  # noqa: E402
    GameWindow,
    SlotEnvironment,
    SlotLayoutParams,
    TileConfig,
    WindowRect,
    calculate_slot_from_tile_config,
    calculate_tile_position,
    check_window_slots_compatibility,
    build_title_template_pattern,
    detect_game_window,
    extract_window_number,
    layout_params_from_tile_config,
    load_window_slot_metadata,
    load_window_slots,
    refresh_window_slots_from_current_windows,
    resolve_window_slot_for_repair,
    save_current_windows_as_slots,
    is_game_window,
    sort_game_windows,
    tile_game_windows,
    _write_window_detection_diagnostics,
    window_slots_profile_path,
)


class WindowManagerTests(unittest.TestCase):
    def test_extract_window_number(self) -> None:
        self.assertEqual(extract_window_number("斗罗大陆H5-1号"), 1)
        self.assertEqual(extract_window_number("斗罗大陆H5-1号-扫码登录"), 1)
        self.assertEqual(extract_window_number("斗罗大陆H5-1-伊号科技", "斗罗大陆H5-{index}"), 1)
        self.assertEqual(extract_window_number("斗罗大陆H5-31号"), 31)
        self.assertEqual(extract_window_number("斗罗大陆H5-31号-扫码登录"), 31)
        self.assertEqual(extract_window_number("斗罗大陆H5-31-伊号科技", "斗罗大陆H5-{index}"), 31)
        self.assertIsNone(extract_window_number("斗罗大陆H5-1号甲战区"))
        self.assertIsNone(extract_window_number("斗罗大陆H5_8号"))
        self.assertIsNone(extract_window_number("斗罗大陆H5"))

    def test_build_title_template_pattern_escapes_literal_text(self) -> None:
        pattern = build_title_template_pattern("DLH5.{index}")

        self.assertEqual(pattern.fullmatch("DLH5.1").group("index"), "1")
        self.assertEqual(pattern.fullmatch("DLH5.1-扫码登录").group("index"), "1")
        self.assertIsNone(pattern.fullmatch("DLH5x1"))

    def test_dynamic_title_template_controls_detection(self) -> None:
        self.assertTrue(is_game_window(1, "DLH5-1", title_template="DLH5-{index}"))
        self.assertTrue(is_game_window(2, "DLH5-1-扫码登录", title_template="DLH5-{index}"))
        self.assertFalse(is_game_window(3, "斗罗大陆H5-1号", title_template="DLH5-{index}"))
        self.assertTrue(is_game_window(4, "游戏窗口1", title_template="游戏窗口{index}"))
        self.assertTrue(is_game_window(5, "游戏窗口1-扫码登录", title_template="游戏窗口{index}"))
        self.assertFalse(is_game_window(6, "斗罗大陆H5 电脑版全自动辅助", title_template="斗罗大陆H5-{index}号"))

    def test_is_game_window_uses_strict_title_and_excludes_helpers(self) -> None:
        template = "斗罗大陆H5-{index}号"
        self.assertTrue(is_game_window(1, "斗罗大陆H5-1号", title_template=template))
        self.assertTrue(is_game_window(8, "斗罗大陆H5-1号-扫码登录", title_template=template))
        self.assertTrue(is_game_window(9, "斗罗大陆H5-31号-扫码登录", title_template=template))
        self.assertTrue(is_game_window(2, "斗罗大陆H5-31号", title_template=template))
        self.assertFalse(is_game_window(3, "斗罗大陆H5 电脑版全自动辅助", title_template=template))
        self.assertFalse(is_game_window(4, "斗罗大陆H5 辅助工具", title_template=template))
        self.assertFalse(is_game_window(5, "上号器 —— 前台串行模式", title_template=template))
        self.assertFalse(is_game_window(6, "斗罗大陆H5", title_template=template))
        self.assertTrue(
            is_game_window(
                7,
                "斗罗大陆H5",
                allow_unnumbered=True,
                title_template=template,
            )
        )

    def test_is_game_window_filters_by_configured_game_exe_path(self) -> None:
        configured = r"E:\Program Files\DLH5\X5Game.exe"
        process_paths = {
            1: configured,
            2: configured.lower(),
            31: configured,
            100: r"E:\Tools\斗罗大陆H5辅助.exe",
            101: r"D:\Tools\launcher.exe",
            102: configured,
        }

        def process_path(hwnd: int) -> str:
            return process_paths.get(hwnd, "")

        titles = [
            (1, "斗罗大陆H5-1号"),
            (2, "斗罗大陆H5-2号"),
            (31, "斗罗大陆H5-31号"),
            (100, "斗罗大陆H5 电脑版全自动辅助"),
            (101, "上号器 —— 前台串行模式"),
            (102, "斗罗大陆H5 辅助工具"),
        ]

        accepted = [
            hwnd
            for hwnd, title in titles
            if is_game_window(
                hwnd,
                title,
                configured_game_exe_path=configured,
                process_path_getter=process_path,
            )
        ]

        self.assertEqual(accepted, [1, 2, 31])

    def test_process_mismatch_does_not_reject_numbered_title_with_matching_size(self) -> None:
        configured = r"E:\Program Files\DLH5\X5Game.exe"

        self.assertTrue(
            is_game_window(
                1,
                "斗罗大陆H5-1-伊号科技",
                title_template="斗罗大陆H5-{index}",
                configured_game_exe_path=configured,
                rect=WindowRect(250, 0, 570, 540),
                expected_window_size=(320, 540),
                process_path_getter=lambda _hwnd: r"E:\Tools\launcher-opened-window.exe",
            )
        )

    def test_process_match_strongly_confirms_numbered_title_with_suffix(self) -> None:
        configured = r"E:\Program Files\DLH5\X5Game.exe"

        self.assertTrue(
            is_game_window(
                1,
                "斗罗大陆H5-1-伊号科技",
                title_template="斗罗大陆H5-{index}",
                configured_game_exe_path=configured,
                process_path_getter=lambda _hwnd: configured,
            )
        )

    def test_31_game_windows_plus_helper_counts_as_31(self) -> None:
        configured = r"E:\Program Files\DLH5\X5Game.exe"
        process_paths = {index: configured for index in range(1, 32)}
        process_paths[99] = r"E:\Tools\斗罗大陆H5辅助.exe"

        titles = [(index, f"斗罗大陆H5-{index}号") for index in range(1, 32)]
        titles.append((99, "斗罗大陆H5 电脑版全自动辅助"))

        count = sum(
            1
            for hwnd, title in titles
            if is_game_window(
                hwnd,
                title,
                configured_game_exe_path=configured,
                process_path_getter=lambda value: process_paths[value],
            )
        )

        self.assertEqual(count, 31)

    def test_window_detection_diagnostics_include_reject_reason(self) -> None:
        result = detect_game_window(
            99,
            "斗罗大陆H5 电脑版全自动辅助",
            class_name="HelperWindow",
            pid=1234,
            rect=WindowRect(0, 0, 800, 600),
            process_path_getter=lambda _hwnd: r"E:\Tools\helper.exe",
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "helper_keyword")
        self.assertEqual(result.helper_keyword, "全自动辅助")

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "window_detection_detail.log"
            _write_window_detection_diagnostics(
                [result],
                configured_game_exe_path=r"E:\Program Files\DLH5\X5Game.exe",
                expected_window_size=(320, 540),
                log_path=log_path,
            )

            content = log_path.read_text(encoding="utf-8")

        self.assertIn('"event": "window_detection"', content)
        self.assertIn('"title": "斗罗大陆H5 电脑版全自动辅助"', content)
        self.assertIn('"accepted": false', content)
        self.assertIn('"reason": "helper_keyword"', content)

    def test_tile_game_windows_reports_access_denied_diagnostics(self) -> None:
        windows = [
            GameWindow(
                hwnd=200,
                title="斗罗大陆H5-1号-扫码登录",
                number=1,
                rect=WindowRect(10, 20, 330, 560),
            )
        ]

        with (
            mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=windows),
            mock.patch("douluo_launcher.window_manager.user32.SetWindowPos", return_value=False),
            mock.patch("douluo_launcher.window_manager.ctypes.get_last_error", return_value=5),
            mock.patch("douluo_launcher.window_manager.get_window_process_id", return_value=1234),
            mock.patch("douluo_launcher.window_manager.get_window_process_path", return_value=r"E:\Tools\helper-opened.exe"),
            mock.patch("douluo_launcher.window_manager.is_current_process_admin", return_value=False),
        ):
            results = tile_game_windows(TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525))

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("Windows 拒绝访问", results[0].error)
        self.assertIn("hwnd=200", results[0].error)
        self.assertIn("pid=1234", results[0].error)
        self.assertIn("上号器管理员=False", results[0].error)
        self.assertIn("目标x=10", results[0].error)

    def test_tile_game_windows_still_scans_when_no_explicit_windows(self) -> None:
        windows = [
            GameWindow(
                hwnd=201,
                title="斗罗大陆H5-1号-扫码登录",
                number=1,
                rect=WindowRect(10, 20, 330, 560),
            )
        ]
        config = TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525)

        with (
            mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=windows) as list_windows,
            mock.patch("douluo_launcher.window_manager._set_window_pos_with_retries", return_value=(True, "")),
        ):
            results = tile_game_windows(config)

        list_windows.assert_called_once()
        self.assertEqual([result.window.hwnd for result in results], [201])
        self.assertTrue(results[0].success)

    def test_tile_game_windows_uses_explicit_windows_without_scanning(self) -> None:
        windows = [
            GameWindow(
                hwnd=301,
                title="斗罗大陆H5-1号-扫码登录",
                number=1,
                rect=WindowRect(10, 20, 330, 560),
            ),
            GameWindow(
                hwnd=302,
                title="斗罗大陆H5-2号-扫码登录",
                number=2,
                rect=WindowRect(20, 30, 340, 570),
            ),
        ]
        config = TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=2)

        with (
            mock.patch("douluo_launcher.window_manager.list_game_windows") as list_windows,
            mock.patch("douluo_launcher.window_manager._set_window_pos_with_retries", return_value=(True, "")),
        ):
            results = tile_game_windows(config, windows=windows)

        list_windows.assert_not_called()
        self.assertEqual([result.window.hwnd for result in results], [301, 302])
        self.assertTrue(all(result.success for result in results))

    def test_31_scan_login_windows_plus_helper_counts_as_31_with_process_mismatch(self) -> None:
        configured = r"E:\Program Files\DLH5\X5Game.exe"
        process_paths = {index: r"E:\Tools\launcher-opened-window.exe" for index in range(1, 32)}
        process_paths[99] = r"E:\Tools\斗罗大陆H5辅助.exe"

        titles = [(index, f"斗罗大陆H5-{index}-伊号科技") for index in range(1, 32)]
        titles.append((99, "斗罗大陆H5 电脑版全自动辅助"))

        count = sum(
            1
            for hwnd, title in titles
            if is_game_window(
                hwnd,
                title,
                title_template="斗罗大陆H5-{index}",
                configured_game_exe_path=configured,
                rect=WindowRect(250, 0, 570, 540),
                expected_window_size=(320, 540),
                process_path_getter=lambda value: process_paths[value],
            )
        )

        self.assertEqual(count, 31)

    def test_sort_game_windows_uses_numeric_order(self) -> None:
        windows = [
            GameWindow(hwnd=10, title="斗罗大陆H5-10号", number=10),
            GameWindow(hwnd=2, title="斗罗大陆H5-2号", number=2),
            GameWindow(hwnd=1, title="斗罗大陆H5-1号", number=1),
            GameWindow(hwnd=11, title="斗罗大陆H5-11号", number=11),
        ]

        sorted_numbers = [window.number for window in sort_game_windows(windows)]

        self.assertEqual(sorted_numbers, [1, 2, 10, 11])

    def test_sort_game_windows_places_numbered_windows_first(self) -> None:
        windows = [
            GameWindow(hwnd=30, title="斗罗大陆H5", number=None),
            GameWindow(hwnd=2, title="斗罗大陆H5-2号", number=2),
            GameWindow(hwnd=1, title="斗罗大陆H5-1号", number=1),
        ]

        sorted_windows = sort_game_windows(windows)

        self.assertEqual([window.number for window in sorted_windows], [1, 2, None])

    def test_calculate_tile_position_supports_more_than_31_windows(self) -> None:
        config = TileConfig(
            width=320,
            height=540,
            start_x=250,
            start_y=0,
            offset_x=320,
            offset_y=525,
            per_row=8,
        )

        positions = [calculate_tile_position(index, config) for index in range(32)]

        self.assertEqual(positions[0], (250, 0))
        self.assertEqual(positions[7], (2490, 0))
        self.assertEqual(positions[8], (250, 525))
        self.assertEqual(positions[30], (2170, 1575))
        self.assertEqual(positions[31], (2490, 1575))

    def test_tile_config_defaults(self) -> None:
        config = TileConfig()

        self.assertEqual(config.width, 320)
        self.assertEqual(config.height, 540)
        self.assertEqual(config.start_x, 250)
        self.assertEqual(config.start_y, 0)
        self.assertEqual(config.offset_x, 320)
        self.assertEqual(config.offset_y, 525)
        self.assertEqual(config.per_row, 8)

    def test_calculate_slot_from_tile_config_uses_slot_number(self) -> None:
        config = TileConfig(
            width=320,
            height=540,
            start_x=250,
            start_y=0,
            offset_x=320,
            offset_y=525,
            per_row=8,
        )

        slot = calculate_slot_from_tile_config(15, config)

        self.assertEqual(slot.slot_no, 15)
        self.assertEqual((slot.x, slot.y, slot.width, slot.height), (2170, 525, 320, 540))
        self.assertEqual(slot.title, "斗罗大陆H5-15号")

    def test_load_window_slots_uses_numeric_slot_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_slots.json"
            path.write_text(
                """
                {
                  "11": {"slot_no": 11, "title": "斗罗大陆H5-11号", "hwnd": 1100,
                         "x": 890, "y": 525, "width": 320, "height": 540},
                  "2": {"slot_no": 2, "title": "斗罗大陆H5-2号", "hwnd": 200,
                        "x": 570, "y": 0, "width": 320, "height": 540}
                }
                """,
                encoding="utf-8",
            )

            slots = load_window_slots(path)

        self.assertEqual([slot.slot_no for slot in slots], [2, 11])
        self.assertEqual(slots[1].title, "斗罗大陆H5-11号")
        self.assertEqual((slots[1].x, slots[1].y, slots[1].width, slots[1].height), (890, 525, 320, 540))

    def test_load_window_slot_metadata_supports_new_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_slots.json"
            path.write_text(
                """
                {
                  "version": 1,
                  "environment": {
                    "screen_width": 1920,
                    "screen_height": 1080,
                    "dpi": 120,
                    "scale": 1.25,
                    "profile": "1920x1080_125"
                  },
                  "layout_params": {
                    "mode": "fixed",
                    "window_width": 320,
                    "window_height": 540,
                    "per_row": 8,
                    "start_x": 250,
                    "start_y": 0,
                    "offset_x": 320,
                    "offset_y": 525,
                    "title_template": "斗罗大陆H5-{index}号"
                  },
                  "slots": {
                    "2": {"slot_no": 2, "title": "斗罗大陆H5-2号", "hwnd": 200,
                          "x": 570, "y": 0, "width": 320, "height": 540}
                  }
                }
                """,
                encoding="utf-8",
            )

            environment, layout_params = load_window_slot_metadata(path)
            slots = load_window_slots(path)

        self.assertEqual(len(slots), 1)
        self.assertEqual(environment, SlotEnvironment(1920, 1080, 120, 1.25, "1920x1080_125"))
        self.assertEqual(
            layout_params,
            SlotLayoutParams(
                mode="fixed",
                window_width=320,
                window_height=540,
                per_row=8,
                start_x=250,
                start_y=0,
                offset_x=320,
                offset_y=525,
                title_template="斗罗大陆H5-{index}号",
            ),
        )

    def test_check_window_slots_compatibility_reports_layout_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_slots.json"
            path.write_text(
                """
                {
                  "version": 1,
                  "environment": {
                    "screen_width": 1920,
                    "screen_height": 1080,
                    "dpi": 96,
                    "scale": 1.0,
                    "profile": "1920x1080_100"
                  },
                  "layout_params": {
                    "mode": "fixed",
                    "window_width": 320,
                    "window_height": 540,
                    "per_row": 8,
                    "start_x": 250,
                    "start_y": 0,
                    "offset_x": 320,
                    "offset_y": 525,
                    "title_template": "斗罗大陆H5-{index}号"
                  },
                  "slots": {}
                }
                """,
                encoding="utf-8",
            )
            current = layout_params_from_tile_config(
                TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=10),
                title_template="斗罗大陆H5-{index}号",
            )

            with mock.patch(
                "douluo_launcher.window_manager.get_current_slot_environment",
                return_value=SlotEnvironment(1920, 1080, 96, 1.0, "1920x1080_100"),
            ):
                result = check_window_slots_compatibility(path, current)

        self.assertFalse(result.compatible)
        self.assertTrue(any("每行数量变化" in warning for warning in result.warnings))

    def test_profile_slot_path_separates_window_count_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            environment = SlotEnvironment(2560, 1440, 96, 1.0, "2560x1440_100")
            fixed_31 = layout_params_from_tile_config(
                TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8),
                title_template="斗罗大陆H5-{index}号",
                mode="fixed",
                target_window_count=31,
            )
            fixed_9 = layout_params_from_tile_config(
                TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8),
                title_template="斗罗大陆H5-{index}号",
                mode="fixed",
                target_window_count=9,
            )
            row_9 = SlotLayoutParams(
                mode="row_count",
                target_window_count=9,
                window_width=768,
                window_height=1056,
                per_row=5,
                start_x=0,
                start_y=0,
                title_template="斗罗大陆H5-{index}号",
            )

            fixed_31_path = window_slots_profile_path(tmp, fixed_31, environment=environment)
            fixed_9_path = window_slots_profile_path(tmp, fixed_9, environment=environment)
            row_9_path = window_slots_profile_path(tmp, row_9, environment=environment)

        self.assertNotEqual(fixed_31_path, fixed_9_path)
        self.assertNotEqual(fixed_31_path, row_9_path)
        self.assertIn("2560x1440_100_31_fixed", fixed_31_path.name)
        self.assertIn("2560x1440_100_9_row_count", row_9_path.name)

    def test_check_window_slots_compatibility_blocks_slot_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_slots.json"
            slots = {
                str(index): {
                    "slot_no": index,
                    "title": f"斗罗大陆H5-{index}号",
                    "hwnd": 1000 + index,
                    "x": 250 + (index - 1) * 320,
                    "y": 0,
                    "width": 320,
                    "height": 540,
                }
                for index in range(1, 10)
            }
            payload = {
                "version": 1,
                "environment": {
                    "screen_width": 2560,
                    "screen_height": 1440,
                    "dpi": 96,
                    "scale": 1.0,
                    "profile": "2560x1440_100",
                },
                "layout_params": {
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
                },
                "slots": slots,
            }
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            current = layout_params_from_tile_config(
                TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8),
                title_template="斗罗大陆H5-{index}号",
                mode="fixed",
                target_window_count=31,
            )

            with mock.patch(
                "douluo_launcher.window_manager.get_current_slot_environment",
                return_value=SlotEnvironment(2560, 1440, 96, 1.0, "2560x1440_100"),
            ):
                result = check_window_slots_compatibility(path, current, current_window_count=31)

        self.assertFalse(result.compatible)
        self.assertTrue(any("排列方式变化" in warning for warning in result.warnings))
        self.assertTrue(any("目标窗口数量变化" in warning for warning in result.warnings))
        self.assertTrue(any("槽位数量变化" in warning for warning in result.warnings))
        self.assertTrue(any("当前窗口数量变化" in warning for warning in result.warnings))

    def test_save_current_windows_as_slots_writes_environment_and_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_slots.json"
            layout_params = layout_params_from_tile_config(
                TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8),
                title_template="斗罗大陆H5-{index}号",
            )
            environment = SlotEnvironment(1920, 1080, 96, 1.0, "1920x1080_100")
            windows = [
                GameWindow(
                    hwnd=200,
                    title="斗罗大陆H5-2号",
                    number=2,
                    rect=WindowRect(570, 0, 890, 540),
                )
            ]

            with mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=windows):
                saved = save_current_windows_as_slots(path, environment=environment, layout_params=layout_params)

            loaded_environment, loaded_layout = load_window_slot_metadata(path)
            loaded_slots = load_window_slots(path)

        self.assertEqual([slot.slot_no for slot in saved], [2])
        self.assertEqual(loaded_environment, environment)
        self.assertEqual(loaded_layout, layout_params)
        self.assertEqual(loaded_slots[0].hwnd, 200)

    def test_save_current_windows_as_slots_blocks_expected_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_slots.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "slots": {
                            str(index): {
                                "slot_no": index,
                                "title": f"斗罗大陆H5-{index}号",
                                "hwnd": 1000 + index,
                                "x": index,
                                "y": 0,
                                "width": 320,
                                "height": 540,
                            }
                            for index in range(1, 32)
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            windows = [
                GameWindow(hwnd=2000 + index, title=f"斗罗大陆H5-{index}号", number=index)
                for index in range(1, 31)
            ]

            with mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=windows):
                with self.assertRaisesRegex(ValueError, "目标 31，当前 30"):
                    save_current_windows_as_slots(path, expected_count=31)

            self.assertEqual(len(load_window_slots(path)), 31)

    def test_refresh_window_slots_blocks_expected_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_slots.json"
            path.write_text(
                json.dumps({"version": 1, "slots": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            windows = [
                GameWindow(hwnd=2000 + index, title=f"斗罗大陆H5-{index}号", number=index)
                for index in range(1, 31)
            ]

            with mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=windows):
                with self.assertRaisesRegex(ValueError, "目标 31，当前 30"):
                    refresh_window_slots_from_current_windows(path, expected_count=31)

            self.assertEqual(load_window_slots(path), [])

    def test_slot_write_creates_backup_before_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "window_slots.json"
            first = [GameWindow(hwnd=201, title="斗罗大陆H5-1号", number=1)]
            second = [GameWindow(hwnd=202, title="斗罗大陆H5-1号", number=1)]

            with mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=first):
                save_current_windows_as_slots(path, expected_count=1)
            with mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=second):
                save_current_windows_as_slots(path, expected_count=1)

            backups = list((Path(tmp) / "backups").glob("window_slots_*.json"))
            self.assertEqual(len(backups), 1)
            self.assertIn('"hwnd": 201', backups[0].read_text(encoding="utf-8"))
            self.assertFalse(path.with_name("window_slots.json.tmp").exists())
            self.assertEqual(load_window_slots(path)[0].hwnd, 202)

    def test_resolve_repair_slot_uses_recent_backup_before_fixed_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            slots_dir = Path(tmp) / "slots"
            backups_dir = slots_dir / "backups"
            backups_dir.mkdir(parents=True)
            path = slots_dir / "profile.json"
            path.write_text(json.dumps({"version": 1, "slots": {}}, ensure_ascii=False), encoding="utf-8")
            backup = backups_dir / "profile_20260610_010203.json"
            backup.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "slots": {
                            "29": {
                                "slot_no": 29,
                                "title": "斗罗大陆H5-29号",
                                "hwnd": 2900,
                                "x": 1530,
                                "y": 1575,
                                "width": 320,
                                "height": 540,
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            fixed = TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8)

            with mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=[]):
                slot, source, error = resolve_window_slot_for_repair(29, path, fixed_config=fixed)

            self.assertEqual(error, "")
            self.assertEqual(source, "slot_backup")
            self.assertEqual(slot.x, 1530)

    def test_resolve_repair_slot_uses_fixed_config_without_writing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slots" / "profile.json"
            fixed = TileConfig(width=320, height=540, start_x=250, start_y=0, offset_x=320, offset_y=525, per_row=8)

            with mock.patch("douluo_launcher.window_manager.list_game_windows", return_value=[]):
                slot, source, error = resolve_window_slot_for_repair(
                    29,
                    path,
                    title_template="斗罗大陆H5-{index}号",
                    fixed_config=fixed,
                )

            self.assertEqual(error, "")
            self.assertEqual(source, "fixed_config")
            self.assertEqual((slot.x, slot.y, slot.width, slot.height), (1530, 1575, 320, 540))
            self.assertEqual(slot.title, "斗罗大陆H5-29号")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
