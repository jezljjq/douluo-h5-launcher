import tempfile
import unittest
from pathlib import Path

from douluo_launcher.config import compute_game_window_no, filter_accounts, load_accounts_from_bookmarks, load_settings


class ConfigTests(unittest.TestCase):
    def test_compute_game_window_no(self) -> None:
        self.assertEqual(compute_game_window_no("第一层", 1), 1)
        self.assertEqual(compute_game_window_no("第一层", 8), 8)
        self.assertEqual(compute_game_window_no("第二层", 1), 9)
        self.assertEqual(compute_game_window_no("第二层", 8), 16)
        self.assertEqual(compute_game_window_no("第三层", 1), 17)
        self.assertEqual(compute_game_window_no("第四层", 8), 32)

    def test_load_bookmarks_computes_and_sorts_windows(self) -> None:
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

        self.assertEqual([account.game_window_no for account in accounts], [2, 9])
        self.assertEqual(accounts[1].key, "第二层-1")

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

        self.assertEqual(len(filter_accounts(accounts, "全部")), 2)
        self.assertEqual(len(filter_accounts(accounts, "第一层")), 1)

    def test_load_settings_accepts_new_bookmark_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                '{"bookmark_root_name": "账号", "level_names": ["第一层", "第二层", "第三层", "第四层"], "passport_ocr_region_ratio": [0, 0.75, 1, 1], "qr_passport_ocr_region_ratio": [0, 0.65, 1, 1], "qr_passport_ocr_scale": 4, "passport_region_x_margin": 20, "passport_region_y_offset": 5, "passport_region_height": 45, "notice_close_outside_ratio": [0.08, 0.08], "notice_close_retries": 3, "notice_template_path": "notice.bmp", "passport_dialog_template_path": "dialog.bmp", "notice_visible_text": "公告", "passport_dialog_visible_text": "通行证登录", "login_success_hidden_text": "通行证登录"}',
                encoding="utf-8",
            )

            settings = load_settings(path)

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


if __name__ == "__main__":
    unittest.main()
