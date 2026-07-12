import tempfile
import unittest
from pathlib import Path

from douluo_launcher.client_login_accounts import (
    DEFAULT_GROUP_NAME,
    SINGLE_GROUP_NAME,
    LoginAccountRosterStore,
    build_launcher_accounts,
    logical_group_from_bookmark_path,
    stable_refresh_account_key,
)
from douluo_launcher.direct_link_refresh import RefreshAccount


class ClientLoginAccountsTests(unittest.TestCase):
    def test_bookmark_path_drives_dynamic_group_for_all_supported_names(self) -> None:
        cases = {
            "": DEFAULT_GROUP_NAME,
            "账号/1": SINGLE_GROUP_NAME,
            "账号/A1": SINGLE_GROUP_NAME,
            "账号/张三": SINGLE_GROUP_NAME,
            "账号/第一层/1": "第一层",
            "账号/存钻/测试号": "存钻",
            r"账号\自定义\中A9": "自定义",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(logical_group_from_bookmark_path(path), expected)

    def test_roster_is_independent_from_refresh_enabled_and_preserves_global_order(self) -> None:
        accounts = [
            RefreshAccount("A", "u1", "p1", bookmark_path="账号/A", enabled=False),
            RefreshAccount("中文", "u2", "p2", bookmark_path="账号/第一层/中文"),
            RefreshAccount("9号", "u3", "p3", bookmark_path=""),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LoginAccountRosterStore(Path(temp_dir) / "login_accounts.json")
            rows = store.reconcile(accounts)
            self.assertEqual([row.account.name for row in rows], ["A", "中文", "9号"])
            self.assertTrue(all(row.included for row in rows))

            store.set_included(stable_refresh_account_key(accounts[1]), False)
            store.move(stable_refresh_account_key(accounts[2]), -1)
            rows = store.reconcile(accounts)
            self.assertEqual([row.account.name for row in rows], ["A", "9号", "中文"])
            self.assertFalse(rows[-1].included)

    def test_removed_then_reimported_account_restores_last_explicit_state(self) -> None:
        account = RefreshAccount("A", "user", "pass", bookmark_path="账号/A")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LoginAccountRosterStore(Path(temp_dir) / "login_accounts.json")
            self.assertTrue(store.reconcile([account])[0].included)
            store.set_included(stable_refresh_account_key(account), False)
            self.assertEqual(store.reconcile([]), [])
            self.assertFalse(store.reconcile([account])[0].included)

    def test_legacy_seen_key_without_state_defaults_to_participating(self) -> None:
        account = RefreshAccount("A", "user", "pass", bookmark_path="账号/A")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "login_accounts.json"
            key = stable_refresh_account_key(account)
            path.write_text('{"schema_version":1,"accounts":{},"seen_keys":["' + key + '"]}', encoding="utf-8")
            self.assertTrue(LoginAccountRosterStore(path).reconcile([account])[0].included)

    def test_batch_participation_saves_once(self) -> None:
        accounts = [RefreshAccount(str(index), f"u{index}", "p") for index in range(3)]
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LoginAccountRosterStore(Path(temp_dir) / "login_accounts.json")
            rows = store.reconcile(accounts)
            calls = 0
            original_save = store._save
            def counted_save():
                nonlocal calls
                calls += 1
                return original_save()
            store._save = counted_save
            self.assertEqual(store.set_included_many([row.key for row in rows], False), 3)
            self.assertEqual(calls, 1)
            self.assertTrue(all(not row.included for row in store.reconcile(accounts)))

    def test_launcher_accounts_filter_participation_and_group_include_without_fixed_counts(self) -> None:
        refresh_accounts = [
            RefreshAccount(f"账号{i}", f"u{i}", f"p{i}", bookmark_path=f"账号/第一层/账号{i}")
            for i in range(1, 12)
        ] + [RefreshAccount("单层A", "u12", "p12", bookmark_path="账号/单层A")]
        links = {
            account.name: {
                "direct_url": f"https://example.invalid/{index}",
                "bookmark_path": account.bookmark_path,
            }
            for index, account in enumerate(refresh_accounts, start=1)
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LoginAccountRosterStore(Path(temp_dir) / "login_accounts.json")
            rows = store.reconcile(refresh_accounts)
            accounts = build_launcher_accounts(
                rows,
                links,
                {"第一层": {"include_in_all": True}, SINGLE_GROUP_NAME: {"include_in_all": False}},
            )

        self.assertEqual(len(accounts), 12)
        self.assertEqual(sum(account.level == "第一层" for account in accounts), 11)
        self.assertEqual([account.game_window_no for account in accounts], list(range(1, 13)))
        self.assertTrue(all(account.include_in_all for account in accounts[:11]))
        self.assertFalse(accounts[-1].include_in_all)
        self.assertEqual(accounts[-1].bookmark_title, "单层A")


if __name__ == "__main__":
    unittest.main()
