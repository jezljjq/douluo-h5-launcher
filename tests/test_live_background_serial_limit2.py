import inspect
import unittest

from douluo_launcher.config import AccountConfig
from tools import live_background_serial_limit2 as live_limit2


class LiveBackgroundSerialLimit2Tests(unittest.TestCase):
    def test_select_live_accounts_uses_cunduan_first_two_only(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("存钻", 2, 2, "https://example.com/z2", include_in_all=False),
            AccountConfig("存钻", 1, 1, "https://example.com/z1", include_in_all=False),
            AccountConfig("存钻", 3, 3, "https://example.com/z3", include_in_all=False),
        ]

        selected = live_limit2.select_live_accounts(accounts)

        self.assertEqual([(account.level, account.bookmark_no, account.game_window_no) for account in selected], [
            ("存钻", 1, 1),
            ("存钻", 2, 2),
        ])

    def test_live_runner_is_fixed_to_limit_two_and_does_not_touch_formal_slots(self) -> None:
        source = inspect.getsource(live_limit2)

        self.assertEqual(live_limit2.LIVE_BACKGROUND_SERIAL_LIMIT, 2)
        self.assertEqual(live_limit2.LIVE_LEVEL, "存钻")
        self.assertIn("此 live 脚本固定只允许 limit=2", source)
        self.assertIn("--reuse-existing-test-windows", source)
        self.assertNotIn("window_slots.json", source)
        self.assertNotIn("save_window_manager_settings", source)
        self.assertNotIn("tile_game_windows", source)
        self.assertNotIn("_wm_launch_windows", source)
        self.assertNotIn("rename_game_windows", source)


if __name__ == "__main__":
    unittest.main()
