import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("window_manager uses user32 and only runs on Windows")

from douluo_launcher.window_manager import (  # noqa: E402
    GameWindow,
    TileConfig,
    calculate_tile_position,
    extract_window_number,
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


if __name__ == "__main__":
    unittest.main()
