import unittest

from douluo_launcher.config import AccountConfig
from douluo_launcher.gui import (
    ACCOUNT_TABLE_COLUMN_INDEX,
    ACCOUNT_TABLE_COLUMNS,
    _account_table_values,
    _merge_account_group_settings,
    _split_all_serial_accounts,
)


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


if __name__ == "__main__":
    unittest.main()
