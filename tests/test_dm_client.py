import unittest

from douluo_launcher.dm_client import ratio_to_client_point, window_title_matches_game_no


class DmClientTests(unittest.TestCase):
    def test_ratio_to_client_point_uses_client_size(self) -> None:
        self.assertEqual(ratio_to_client_point((0.5, 0.25), 800, 600), (400, 150))

    def test_ratio_to_client_point_clamps_to_client_bounds(self) -> None:
        self.assertEqual(ratio_to_client_point((2, -1), 800, 600), (799, 0))

    def test_window_title_matches_exact_game_window_no(self) -> None:
        self.assertTrue(window_title_matches_game_no("斗罗大陆H5-9-伊导科技", 9))
        self.assertTrue(window_title_matches_game_no("斗罗大陆H5-5-伊导科技", 5))
        self.assertFalse(window_title_matches_game_no("斗罗大陆H5-19-伊导科技", 9))
        self.assertFalse(window_title_matches_game_no("斗罗大陆H5-9-伊导科技", 5))
        self.assertFalse(window_title_matches_game_no("斗罗大陆H5-19-伊导科技", 1))


if __name__ == "__main__":
    unittest.main()
