import os
import tempfile
import unittest
from pathlib import Path

from douluo_launcher.config import (
    AccountConfig,
    SINGLE_LEVEL_NAME,
    compute_game_window_no,
    describe_bookmark_file,
    filter_accounts,
    find_bookmark_file_candidates,
    find_preferred_bookmark_file,
    list_bookmark_top_level_dirs,
    load_accounts_from_bookmarks,
    load_settings,
)


class ConfigTests(unittest.TestCase):
    def test_compute_game_window_no(self) -> None:
        self.assertEqual(compute_game_window_no("第一层", 1), 1)
        self.assertEqual(compute_game_window_no("第一层", 8), 8)
        self.assertEqual(compute_game_window_no("第二层", 1), 9)
        self.assertEqual(compute_game_window_no("第二层", 8), 16)
        self.assertEqual(compute_game_window_no("第三层", 1), 17)
        self.assertEqual(compute_game_window_no("第四层", 8), 32)

    def test_compute_game_window_no_uses_custom_level_counts(self) -> None:
        counts = {"第一层": 9, "第二层": 8, "第三层": 8, "第四层": 7}

        self.assertEqual(compute_game_window_no("第一层", 9, counts), 9)
        self.assertEqual(compute_game_window_no("第二层", 1, counts), 10)
        self.assertEqual(compute_game_window_no("第二层", 8, counts), 17)
        self.assertEqual(compute_game_window_no("第三层", 1, counts), 18)
        self.assertEqual(compute_game_window_no("第四层", 7, counts), 32)

    def test_load_bookmarks_computes_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Bookmarks"
            path.write_text(
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
            {
              "type": "folder",
              "name": "第二层",
              "children": [
                {"type": "url", "name": "1", "url": "https://example.com/9"}
              ]
            },
            {
              "type": "folder",
              "name": "第一层",
              "children": [
                {"type": "url", "name": "2号", "url": "https://example.com/2"}
              ]
            }
          ]
        }
      ]
    }
  }
}
""",
                encoding="utf-8",
            )

            accounts = load_accounts_from_bookmarks(path, "账号")

        windows_by_key = {account.key: account.game_window_no for account in accounts}
        self.assertEqual(windows_by_key["第一层-2"], 2)
        self.assertEqual(windows_by_key["第二层-1"], 9)

    def test_load_bookmarks_supports_custom_layer_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Bookmarks"
            path.write_text(
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
            {"type": "folder", "name": "第一层", "children": [
              {"type": "url", "name": "9", "url": "https://example.com/9"}
            ]},
            {"type": "folder", "name": "第二层", "children": [
              {"type": "url", "name": "1", "url": "https://example.com/10"},
              {"type": "url", "name": "8", "url": "https://example.com/17"}
            ]},
            {"type": "folder", "name": "第三层", "children": [
              {"type": "url", "name": "1", "url": "https://example.com/18"}
            ]},
            {"type": "folder", "name": "第四层", "children": [
              {"type": "url", "name": "7", "url": "https://example.com/32"}
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
                path,
                "账号",
                level_counts={"第一层": 9, "第二层": 8, "第三层": 8, "第四层": 7},
            )

        self.assertEqual([account.game_window_no for account in accounts], [9, 10, 17, 18, 32])

    def test_load_bookmarks_supports_single_level_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Bookmarks"
            path.write_text(
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
            {"type": "url", "name": "1", "url": "https://example.com/1"},
            {"type": "url", "name": "9号", "url": "https://example.com/9"},
            {"type": "url", "name": "说明", "url": "https://example.com/skip"},
            {"type": "folder", "name": "第一层", "children": [
              {"type": "url", "name": "1", "url": "https://example.com/layer1"}
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

            accounts = load_accounts_from_bookmarks(path, "账号")

        single_accounts = [account for account in accounts if account.level == SINGLE_LEVEL_NAME]
        self.assertEqual([account.bookmark_no for account in single_accounts], [1, 9])
        self.assertEqual([account.game_window_no for account in single_accounts], [1, 9])
        self.assertIn("第一层-1", [account.key for account in accounts])

    def test_load_bookmarks_supports_dynamic_custom_groups_in_original_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Bookmarks"
            path.write_text(
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
            {"type": "url", "name": "1", "url": "https://example.com/root1"},
            {"type": "url", "name": "JS", "url": "https://example.com/js"},
            {"type": "folder", "name": "第一层", "children": [
              {"type": "url", "name": "1", "url": "https://example.com/layer1"}
            ]},
            {"type": "folder", "name": "存钻", "children": [
              {"type": "url", "name": "z1", "url": "https://example.com/z1"},
              {"type": "url", "name": "z2", "url": "https://example.com/z2"},
              {"type": "url", "name": "z9", "url": "https://example.com/z9"}
            ]},
            {"type": "folder", "name": "备用", "children": [
              {"type": "url", "name": "备用A", "url": "https://example.com/backup"}
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
                path,
                "账号",
                account_group_settings={"第一层": {"include_in_all": True}},
            )

        custom_accounts = [account for account in accounts if account.level == "存钻"]
        self.assertEqual([account.bookmark_title for account in custom_accounts], ["z1", "z2", "z9"])
        self.assertEqual([account.bookmark_no for account in custom_accounts], [1, 2, 3])
        self.assertEqual([account.game_window_no for account in custom_accounts], [1, 2, 3])
        self.assertEqual(custom_accounts[0].display_name, "存钻-z1 → 窗口1")
        self.assertFalse(any(account.include_in_all for account in custom_accounts))

        backup_accounts = [account for account in accounts if account.level == "备用"]
        self.assertEqual(len(backup_accounts), 1)
        self.assertFalse(backup_accounts[0].include_in_all)

        single_accounts = [account for account in accounts if account.level == SINGLE_LEVEL_NAME]
        self.assertEqual([account.bookmark_title for account in single_accounts], ["1"])
        self.assertNotIn("JS", [account.bookmark_title for account in accounts])

    def test_missing_root_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Bookmarks"
            path.write_text('{"roots": {"bookmark_bar": {"type": "folder", "name": "root", "children": []}}}', encoding="utf-8")

            with self.assertRaises(ValueError):
                load_accounts_from_bookmarks(path, "账号")

    def test_filter_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Bookmarks"
            path.write_text(
                """
{
  "roots": {
    "bookmark_bar": {
      "type": "folder",
      "name": "root",
      "children": [
        {
          "type": "folder",
          "name": "账号",
          "children": [
            {"type": "folder", "name": "第一层", "children": [{"type": "url", "name": "1", "url": "https://example.com/1"}]},
            {"type": "folder", "name": "第二层", "children": [{"type": "url", "name": "1", "url": "https://example.com/9"}]}
          ]
        }
      ]
    }
  }
}
""",
                encoding="utf-8",
            )
            accounts = load_accounts_from_bookmarks(path, "账号")

        accounts = [
            AccountConfig(account.level, account.bookmark_no, account.game_window_no, account.url,
                          include_in_all=(account.level == "第一层"))
            for account in accounts
        ]

        self.assertEqual([account.level for account in filter_accounts(accounts, "全部")], ["第一层"])
        self.assertEqual(len(filter_accounts(accounts, "第一层")), 1)
        self.assertEqual(len(filter_accounts(accounts, "第二层")), 1)

    def test_filter_accounts_all_excludes_unchecked_groups_but_specific_level_does_not(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=True),
            AccountConfig("第二层", 1, 9, "https://example.com/l2", include_in_all=False),
            AccountConfig("存钻", 1, 1, "https://example.com/z1", include_in_all=False),
        ]

        self.assertEqual([account.level for account in filter_accounts(accounts, "全部")], ["第一层"])
        self.assertEqual([account.level for account in filter_accounts(accounts, "存钻")], ["存钻"])

    def test_filter_accounts_all_returns_empty_when_no_group_is_checked(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/l1", include_in_all=False),
            AccountConfig("存钻", 1, 1, "https://example.com/z1", include_in_all=False),
        ]

        self.assertEqual(filter_accounts(accounts, "全部"), [])

    def test_load_settings_accepts_new_bookmark_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                '{"bookmark_file": "C:/Users/Administrator/AppData/Local/Microsoft/Edge/User Data/Default/Bookmarks", "bookmark_browser": "Edge", "bookmark_profile": "Default", "bookmark_root_name": "账号", "level_names": ["第一层", "第二层", "第三层", "第四层"], "passport_ocr_region_ratio": [0, 0.75, 1, 1], "qr_passport_ocr_region_ratio": [0, 0.65, 1, 1], "qr_passport_ocr_scale": 4, "passport_region_x_margin": 20, "passport_region_y_offset": 5, "passport_region_height": 45, "notice_close_outside_ratio": [0.08, 0.08], "notice_close_retries": 3, "notice_template_path": "notice.bmp", "passport_dialog_template_path": "dialog.bmp", "notice_visible_text": "公告", "passport_dialog_visible_text": "通行证登录", "login_success_hidden_text": "通行证登录"}',
                encoding="utf-8",
            )

            settings = load_settings(path)

        self.assertEqual(settings.bookmark_file, "C:/Users/Administrator/AppData/Local/Microsoft/Edge/User Data/Default/Bookmarks")
        self.assertEqual(settings.bookmark_browser, "Edge")
        self.assertEqual(settings.bookmark_profile, "Default")
        self.assertEqual(settings.bookmark_root_name, "账号")
        self.assertEqual(settings.level_names[1], "第二层")
        self.assertEqual(settings.passport_ocr_region_ratio, (0, 0.75, 1, 1))
        self.assertEqual(settings.qr_passport_ocr_region_ratio, (0, 0.65, 1, 1))
        self.assertEqual(settings.qr_passport_ocr_scale, 4)
        self.assertEqual(settings.passport_region_x_margin, 20)
        self.assertEqual(settings.passport_region_y_offset, 5)
        self.assertEqual(settings.passport_region_height, 45)
        self.assertEqual(settings.notice_close_outside_ratio, (0.08, 0.08))
        self.assertEqual(settings.notice_close_retries, 3)
        self.assertEqual(settings.notice_template_path, "notice.bmp")
        self.assertEqual(settings.passport_dialog_template_path, "dialog.bmp")
        self.assertEqual(settings.notice_visible_text, "公告")
        self.assertEqual(settings.passport_dialog_visible_text, "通行证登录")

    def test_load_settings_merges_account_group_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                '{"account_group_settings": {"存钻": {"include_in_all": true}, "备用": {"include_in_all": false}}}',
                encoding="utf-8",
            )

            settings = load_settings(path)

        self.assertTrue(settings.account_group_settings["第一层"]["include_in_all"])
        self.assertTrue(settings.account_group_settings["存钻"]["include_in_all"])
        self.assertFalse(settings.account_group_settings["备用"]["include_in_all"])

    def test_bookmark_candidates_are_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir)
            chrome = local_app_data / "Google" / "Chrome" / "User Data" / "Default" / "Bookmarks"
            edge = local_app_data / "Microsoft" / "Edge" / "User Data" / "Default" / "Bookmarks"
            chrome.parent.mkdir(parents=True)
            edge.parent.mkdir(parents=True)
            chrome.write_text("{}", encoding="utf-8")
            edge.write_text("{}", encoding="utf-8")

            old_value = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(local_app_data)
            try:
                candidates = find_bookmark_file_candidates()
                preferred = find_preferred_bookmark_file("Edge", "Default")
            finally:
                if old_value is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = old_value

        self.assertEqual({candidate.browser for candidate in candidates}, {"Chrome", "Edge"})
        edge_candidate = next(candidate for candidate in candidates if candidate.browser == "Edge")
        self.assertEqual(edge_candidate.profile, "Default")
        self.assertTrue(edge_candidate.path.endswith("Bookmarks"))
        self.assertEqual(preferred, edge_candidate.path)

    def test_describe_bookmark_file_extracts_browser_and_profile(self) -> None:
        info = describe_bookmark_file(
            r"C:\Users\Administrator\AppData\Local\Microsoft\Edge\User Data\Default\Bookmarks"
        )

        self.assertEqual(info.browser, "Edge")
        self.assertEqual(info.profile, "Default")

    def test_missing_bookmark_root_reports_path_and_top_level_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Bookmarks"
            path.write_text(
                """
{
  "roots": {
    "bookmark_bar": {
      "type": "folder",
      "name": "收藏夹栏",
      "children": [
        {"type": "folder", "name": "不是账号", "children": []}
      ]
    }
  }
}
""",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as caught:
                load_accounts_from_bookmarks(path, "账号")

            top_level = list_bookmark_top_level_dirs(path)

        self.assertIn(str(path), str(caught.exception))
        self.assertIn("收藏夹栏/不是账号", str(caught.exception))
        self.assertIn("收藏夹栏/不是账号", top_level)


if __name__ == "__main__":
    unittest.main()
