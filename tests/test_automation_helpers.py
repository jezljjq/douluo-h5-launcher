import unittest

from douluo_launcher.automation import extract_hex_passport, extract_passport_from_text


class AutomationHelperTests(unittest.TestCase):
    def test_extracts_passport_from_visible_text(self) -> None:
        text = "扫码登录\n本次通行证：8598a293\n请使用手机扫码"

        self.assertEqual(extract_passport_from_text(text, r"本次通行证\s*[:：]\s*([A-Za-z0-9_-]+)"), "8598a293")

    def test_extracts_passport_when_spacing_changes(self) -> None:
        text = "本次通行证 : 8598a293"

        self.assertEqual(extract_passport_from_text(text, r"本次通行证\s*[:：]\s*([A-Za-z0-9_-]+)"), "8598a293")

    def test_extracts_hex_passport_from_ocr_noise(self) -> None:
        self.assertEqual(extract_hex_passport("foo 8598a293 bar"), "8598a293")
        self.assertEqual(extract_hex_passport("8598 a293"), "8598a293")


if __name__ == "__main__":
    unittest.main()
