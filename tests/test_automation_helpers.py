import threading
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image

import douluo_launcher.automation as automation_module
from douluo_launcher.automation import (
    AccountRunner,
    _dm_helper_command,
    _ensure_playwright_browsers_path,
    _find_playwright_chromium_exe,
    extract_hex_passport,
    extract_passport_from_text,
)
from douluo_launcher.config import AccountConfig, AutomationSettings


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

    def test_repairs_packaged_playwright_browser_path(self) -> None:
        bad_path = r"D:\app\_internal\playwright\driver\package\.local-browsers"
        with patch.dict(
            "os.environ",
            {
                "LOCALAPPDATA": r"C:\Users\Test\AppData\Local",
                "PLAYWRIGHT_BROWSERS_PATH": bad_path,
            },
            clear=False,
        ):
            expected = _ensure_playwright_browsers_path()
            self.assertIsNotNone(expected)
            self.assertEqual(str(expected), r"C:\Users\Test\AppData\Local\ms-playwright")

    def test_packaged_playwright_browser_path_prefers_bundled_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe_dir = Path(temp_dir) / "Launcher"
            browser_dir = exe_dir / "ms-playwright"
            chrome = browser_dir / "chromium-9999" / "chrome-win64" / "chrome.exe"
            chrome.parent.mkdir(parents=True)
            chrome.write_text("", encoding="utf-8")
            exe_path = exe_dir / "上号器.exe"
            exe_path.write_text("", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {
                    "LOCALAPPDATA": r"C:\Users\Test\AppData\Local",
                    "PLAYWRIGHT_BROWSERS_PATH": r"C:\Users\Test\AppData\Local\ms-playwright",
                },
                clear=False,
            ), patch.object(automation_module.sys, "frozen", True, create=True), patch.object(
                automation_module.sys, "executable", str(exe_path)
            ):
                expected = _ensure_playwright_browsers_path()

            self.assertEqual(expected.resolve(), browser_dir.resolve())

    def test_bundled_playwright_chromium_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            browser_dir = Path(temp_dir) / "ms-playwright"
            for revision in ("chromium-1208", "chromium-1217"):
                chrome = browser_dir / revision / "chrome-win64" / "chrome.exe"
                chrome.parent.mkdir(parents=True, exist_ok=True)
                chrome.write_text("", encoding="utf-8")

            self.assertIsNone(_find_playwright_chromium_exe(browser_dir))

    def test_dm_helper_command_prefers_bundled_exe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper_exe = root / "dm_click_helper.exe"
            helper_exe.write_text("", encoding="utf-8")

            with patch("douluo_launcher.automation.app_root", return_value=root):
                command = _dm_helper_command("chain", "click:1,2")

        self.assertEqual(command, [str(helper_exe), "chain", "click:1,2"])

    def test_dm_helper_command_falls_back_to_32bit_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with patch("douluo_launcher.automation.app_root", return_value=root):
                command = _dm_helper_command("type", "abc")

        self.assertEqual(command, ["py", "-3.14-32", str(root / "dm_click_helper.py"), "type", "abc"])

    def test_fast_submit_treats_retry_logged_in_as_success(self) -> None:
        account = AccountConfig(level="单层账号", bookmark_no=1, game_window_no=1, url="https://example.com")
        statuses: list[str] = []
        logs: list[str] = []
        runner = AccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=logs.append,
            update_status=lambda _account, status: statuses.append(status),
        )
        calls = iter([(None, "unknown"), (None, "unknown"), (None, "logged_in")])
        runner._extract_passport_from_login_window = lambda: next(calls)  # type: ignore[method-assign]
        runner._clean_tmp = lambda: None  # type: ignore[method-assign]
        runner._save_error_snapshots = lambda: None  # type: ignore[method-assign]

        self.assertTrue(runner.run_game_flow_fast_submit())
        self.assertEqual(runner.last_fast_submit_result, "already_logged_in")
        self.assertIn("已登录，跳过", statuses)
        self.assertTrue(any("检测到已登录界面，跳过" in line for line in logs))

    def test_passport_bar_and_fallback_qr_do_not_become_logged_in(self) -> None:
        account = AccountConfig(level="单层账号", bookmark_no=1, game_window_no=1, url="https://example.com")
        runner = AccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=lambda _msg: None,
            update_status=lambda _account, _status: None,
        )
        image = Image.new("RGB", (768, 1056), (235, 235, 235))
        runner._detect_opencv_qr_box = lambda _image: None  # type: ignore[method-assign]
        runner._locate_passport_copy_bar = lambda _image: (46, 885, 721, 950)  # type: ignore[method-assign]
        runner._is_passport_bar_box_valid = lambda _image, _box: True  # type: ignore[method-assign]
        runner._locate_qr_box_fallback = lambda _image: (243, 199, 578, 534)  # type: ignore[method-assign]
        runner._looks_like_game_notice_page = lambda _image: False  # type: ignore[method-assign]
        runner._looks_like_game_ui_page = lambda _image: False  # type: ignore[method-assign]

        state, metrics = runner.detect_login_page_state(image)

        self.assertEqual(state, "qr_page")
        self.assertEqual(metrics["qr_evidence_type"], "fallback_qr")
        self.assertEqual(metrics["final_reason"], "回退 QR 候选与通行证横条同时存在")

    def test_game_ui_overrides_weak_fallback_qr_and_false_bar(self) -> None:
        account = AccountConfig(level="单层账号", bookmark_no=1, game_window_no=1, url="https://example.com")
        runner = AccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=lambda _msg: None,
            update_status=lambda _account, _status: None,
        )
        image = Image.new("RGB", (768, 1056), (235, 235, 235))
        runner._detect_opencv_qr_box = lambda _image: None  # type: ignore[method-assign]
        runner._locate_passport_copy_bar = lambda _image: (46, 979, 721, 1021)  # type: ignore[method-assign]
        runner._is_passport_bar_box_valid = lambda _image, _box: True  # type: ignore[method-assign]
        runner._locate_qr_box_fallback = lambda _image: (243, 281, 578, 616)  # type: ignore[method-assign]
        runner._looks_like_game_notice_page = lambda _image: False  # type: ignore[method-assign]
        runner._looks_like_game_ui_page = lambda _image: True  # type: ignore[method-assign]

        state, metrics = runner.detect_login_page_state(image)

        self.assertEqual(state, "logged_in")
        self.assertTrue(metrics["game_ui_detected"])
        self.assertEqual(metrics["final_reason"], "检测到游戏界面特征且无 strong_qr")


if __name__ == "__main__":
    unittest.main()
