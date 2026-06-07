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
    extract_window_number,
    layout_params_from_tile_config,
    load_window_slot_metadata,
    load_window_slots,
    save_current_windows_as_slots,
    sort_game_windows,
)


class WindowManagerTests(unittest.TestCase):
    def test_extract_window_number(self) -> None:
        self.assertEqual(extract_window_number("斗罗大陆H5-1号甲战区"), 1)
        self.assertEqual(extract_window_number("斗罗大陆H5-31号甲战区"), 31)
        self.assertEqual(extract_window_number("斗罗大陆H5_8号"), 8)
        self.assertIsNone(extract_window_number("斗罗大陆H5"))

    def test_sort_game_windows_uses_numeric_order(self) -> None:
        windows = [
            GameWindow(hwnd=10, title="斗罗大陆H5-10号甲战区", number=10),
            GameWindow(hwnd=2, title="斗罗大陆H5-2号甲战区", number=2),
            GameWindow(hwnd=1, title="斗罗大陆H5-1号甲战区", number=1),
            GameWindow(hwnd=11, title="斗罗大陆H5-11号甲战区", number=11),
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


if __name__ == "__main__":
    unittest.main()
