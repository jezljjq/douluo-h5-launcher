import inspect
import threading
import unittest
import tempfile
from pathlib import Path
from unittest import mock

from PIL import Image

from douluo_launcher.automation import PassportOcrResult
from douluo_launcher.background_login import (
    BACKGROUND_INSTALL_COMMANDS,
    BackgroundSingleAccountRunner,
    _LoginWindowSnapshot,
    check_background_runtime_dependencies,
)
from douluo_launcher.config import AccountConfig, AutomationSettings
from douluo_launcher.dm_client import WindowInfo
from douluo_launcher.window_operator import BackgroundOperator


class BackgroundLoginTests(unittest.TestCase):
    def test_background_single_runner_uses_background_operator(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com")
        runner = BackgroundSingleAccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=lambda _message: None,
            update_status=lambda _account, _status: None,
        )

        self.assertIsInstance(runner.operator, BackgroundOperator)
        self.assertFalse(runner.operator.uses_global_mouse)
        self.assertFalse(runner.operator.uses_global_keyboard)
        self.assertFalse(runner.operator.calls_set_foreground_window)

    def test_login_window_screenshot_uses_background_operator(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com")
        screenshot_hwnds: list[int] = []

        class FakeBackgroundOperator:
            uses_global_mouse = False
            uses_global_keyboard = False
            calls_set_foreground_window = False

            def screenshot(self, hwnd: int):
                screenshot_hwnds.append(int(hwnd))
                return Image.new("RGB", (32, 32), "white")

        runner = BackgroundSingleAccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=lambda _message: None,
            update_status=lambda _account, _status: None,
            operator=FakeBackgroundOperator(),  # type: ignore[arg-type]
        )
        runner._helper.detect_login_page_state = lambda _image: ("qr_page", {"final_reason": "test"})  # type: ignore[method-assign]
        selected = WindowInfo(hwnd=321, title="H5-1", width=320, height=540)

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "douluo_launcher.background_login.select_login_window_by_game_no",
            return_value=(selected, [selected]),
        ), mock.patch(
            "douluo_launcher.background_login.extract_passport_from_login_image",
            return_value=PassportOcrResult(
                passport="d40786fa",
                raw_output="",
                text_region_box=None,
                evidence_source="red_bar_box",
                evidence_votes=3,
            ),
        ):
            runner._background_ocr_debug_dir = lambda: Path(temp_dir)  # type: ignore[attr-defined,method-assign]
            passport = runner._extract_passport_from_login_window_background()

        self.assertEqual(passport, "d40786fa")
        self.assertEqual(screenshot_hwnds, [321])

    def test_background_ocr_uses_shared_foreground_extractor(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com")
        runner = BackgroundSingleAccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=lambda _message: None,
            update_status=lambda _account, _status: None,
        )
        image = Image.new("RGB", (768, 1056), "white")
        snapshot = _LoginWindowSnapshot(
            hwnd=71756,
            title="斗罗大陆H5-1号",
            image=image,
            raw_path=Path("debug_background") / "login.png",
            state="qr_page",
            metrics={
                "image_size": (768, 1056),
                "qr_box": None,
                "fallback_qr_box": (243, 199, 578, 534),
                "passport_bar_box": (46, 885, 721, 950),
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "douluo_launcher.background_login.extract_passport_from_login_image",
            return_value=PassportOcrResult(
                passport="d40786fa",
                raw_output="",
                text_region_box=(10, 528, 758, 1046),
                evidence_source="red_bar_box",
                evidence_votes=3,
            ),
        ) as shared_extract:
            runner._background_ocr_debug_dir = lambda: Path(temp_dir)  # type: ignore[attr-defined,method-assign]
            passport = runner._extract_passport_from_login_window_background(snapshot)

        self.assertEqual(passport, "d40786fa")
        shared_extract.assert_called_once()
        kwargs = shared_extract.call_args.kwargs
        self.assertIs(kwargs["runner"], runner._helper)
        self.assertEqual(kwargs["window_index"], 1)
        self.assertEqual(kwargs["mode"], "background")
        self.assertTrue(kwargs["save_failure_artifacts"])
        self.assertEqual(kwargs["login_context"]["red_bar_box"], (46, 885, 721, 950))

    def test_background_ocr_failure_raises_clear_error(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com")
        logs: list[str] = []
        runner = BackgroundSingleAccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=logs.append,
            update_status=lambda _account, _status: None,
        )
        snapshot = _LoginWindowSnapshot(
            hwnd=71756,
            title="斗罗大陆H5-1号",
            image=Image.new("RGB", (768, 1056), "white"),
            raw_path=Path("debug_background") / "login.png",
            state="qr_page",
            metrics={"image_size": (768, 1056)},
        )

        with mock.patch(
            "douluo_launcher.background_login.extract_passport_from_login_image",
            return_value=PassportOcrResult(passport=None, raw_output="", text_region_box=None),
        ) as ocr:
            with self.assertRaisesRegex(RuntimeError, "后台 OCR 未能可靠识别本次通行证"):
                runner._extract_passport_from_login_window_background(snapshot)

        self.assertTrue(ocr.call_args.kwargs["save_failure_artifacts"])
        self.assertTrue(any("后台 OCR 未能可靠识别本次通行证" in line for line in logs))

    def test_background_passport_extraction_disables_copy_read_chain(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com")
        logs: list[str] = []
        runner = BackgroundSingleAccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=logs.append,
            update_status=lambda _account, _status: None,
        )
        snapshot = _LoginWindowSnapshot(
            hwnd=100,
            title="斗罗大陆H5-1号",
            image=Image.new("RGB", (768, 1056), "white"),
            raw_path=Path("debug_background") / "login.png",
            state="qr_page",
            metrics={"image_size": (768, 1056), "passport_bar_box": (46, 885, 721, 950)},
        )

        with mock.patch(
            "douluo_launcher.background_login._read_hwnd_text",
            side_effect=AssertionError("WM_GETTEXT must not run in background passport extraction"),
        ) as read_hwnd, mock.patch.object(
            BackgroundSingleAccountRunner,
            "_read_uia_texts",
            side_effect=AssertionError("UIA must not run in background passport extraction"),
        ), mock.patch(
            "douluo_launcher.background_login._clipboard_copy_attempt",
            side_effect=AssertionError("clipboard must not run in background passport extraction"),
        ) as clipboard_copy, mock.patch(
            "douluo_launcher.background_login._read_clipboard_text",
            side_effect=AssertionError("clipboard read must not run in background passport extraction"),
        ) as read_clipboard, mock.patch(
            "douluo_launcher.background_login._set_clipboard_text",
            side_effect=AssertionError("clipboard write must not run in background passport extraction"),
        ) as write_clipboard, mock.patch.object(
            runner,
            "_post_background_select_copy",
            side_effect=AssertionError("background Ctrl+C must not run"),
        ) as post_copy, mock.patch(
            "douluo_launcher.background_login.extract_passport_from_login_image",
            return_value=PassportOcrResult(
                passport="fd829a15",
                raw_output="",
                text_region_box=(10, 528, 758, 1046),
                evidence_source="red_bar_box",
                evidence_votes=4,
            ),
        ) as ocr:
            passport = runner._extract_passport_from_login_window_background(snapshot)

        self.assertEqual(passport, "fd829a15")
        read_hwnd.assert_not_called()
        clipboard_copy.assert_not_called()
        read_clipboard.assert_not_called()
        write_clipboard.assert_not_called()
        post_copy.assert_not_called()
        ocr.assert_called_once()
        self.assertTrue(any("后台复制/读取已禁用，直接使用 OCR 多证据识别通行证" in line for line in logs))
        self.assertTrue(any("red_bar_box 局部 OCR 强证据：fd829a15，votes=4" in line for line in logs))
        self.assertFalse(any("WM_GETTEXT" in line or "UIA" in line or "clipboard" in line or "尝试后台复制" in line for line in logs))

    def test_background_passport_extraction_source_does_not_call_copy_read_helpers(self) -> None:
        source = inspect.getsource(BackgroundSingleAccountRunner._extract_passport_from_login_window_background)

        for forbidden in (
            "_try_background_passport_copy",
            "_read_hwnd_text",
            "_read_uia_texts",
            "_clipboard_copy_attempt",
            "_read_clipboard_text",
            "_set_clipboard_text",
            "_post_background_select_copy",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("extract_passport_from_login_image", source)

    def test_background_ocr_path_does_not_use_foreground_mouse_or_keyboard_calls(self) -> None:
        sources = "\n".join(
            [
                inspect.getsource(BackgroundSingleAccountRunner._extract_passport_from_login_window_background),
                inspect.getsource(BackgroundSingleAccountRunner._capture_login_window_background),
            ]
        )

        for forbidden in ("SetForegroundWindow", "SetCursorPos", "mouse_event", "keybd_event", "MoveTo", "LeftClick"):
            self.assertNotIn(forbidden, sources)

    def test_background_formal_page_open_uses_shared_playwright_driver(self) -> None:
        source = inspect.getsource(BackgroundSingleAccountRunner._open_formal_game_page)

        self.assertIn("_get_background_playwright()", source)
        self.assertNotIn("sync_playwright().start()", source)
        self.assertNotIn("playwright.stop()", source)

    def test_retained_background_session_does_not_stop_shared_playwright_on_close(self) -> None:
        from douluo_launcher.background_login import _BrowserSession

        browser = mock.Mock()
        playwright = mock.Mock()
        session = _BrowserSession(playwright=playwright, browser=browser, page=object(), hwnd=100)

        session.close()

        browser.close.assert_called_once()
        playwright.stop.assert_not_called()

    def test_missing_cv2_dependency_reports_32bit_install_command(self) -> None:
        def fake_import(module_name: str):
            if module_name == "cv2":
                raise ModuleNotFoundError("No module named 'cv2'")
            return object()

        check = check_background_runtime_dependencies(
            import_module=fake_import,
            python_executable=r"D:\Dev\Python\Python314-32\python.exe",
            python_bits=32,
        )

        self.assertFalse(check.ok)
        self.assertEqual(check.missing_modules, ("cv2",))
        self.assertEqual(BACKGROUND_INSTALL_COMMANDS["cv2"], "py -3.14-32 -m pip install opencv-python")
        self.assertIn("py -3.14-32 -m pip install opencv-python", check.install_commands)

    def test_logged_in_window_skips_ocr_without_ocr_status(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com")
        statuses: list[str] = []
        logs: list[str] = []

        class FakeBackgroundOperator:
            uses_global_mouse = False
            uses_global_keyboard = False
            calls_set_foreground_window = False

            def screenshot(self, _hwnd: int):
                return Image.new("RGB", (80, 80), (120, 90, 60))

        runner = BackgroundSingleAccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=logs.append,
            update_status=lambda _account, status: statuses.append(status),
            operator=FakeBackgroundOperator(),  # type: ignore[arg-type]
        )
        runner._helper.detect_login_page_state = lambda _image: (  # type: ignore[method-assign]
            "logged_in",
            {"final_reason": "检测到游戏界面特征且无 strong_qr", "qr_page_evidence": False},
        )
        runner._helper._ocr_passport_from_text_region = mock.Mock(return_value="D40786FA")  # type: ignore[method-assign]
        runner._open_formal_game_page = mock.Mock()  # type: ignore[method-assign]
        selected = WindowInfo(hwnd=654, title="斗罗大陆H5-1号", width=320, height=540)

        with mock.patch(
            "douluo_launcher.background_login.select_login_window_by_game_no",
            return_value=(selected, [selected]),
        ):
            result = runner.run()

        self.assertTrue(result)
        self.assertIn("已进入游戏，跳过", statuses)
        self.assertNotIn("识别通行证中", statuses)
        self.assertTrue(any("已进入游戏，跳过 OCR" in line for line in logs))
        runner._helper._ocr_passport_from_text_region.assert_not_called()
        runner._open_formal_game_page.assert_not_called()

    def test_background_single_runner_uses_required_status_labels_and_keeps_success_window(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com")
        statuses: list[str] = []
        closed = {"value": False}

        class FakeSession:
            hwnd = 8765

            def close(self) -> None:
                closed["value"] = True

        class FakeOperator:
            uses_global_mouse = False
            uses_global_keyboard = False
            calls_set_foreground_window = False

            def screenshot(self, _hwnd: int):
                return Image.new("RGB", (80, 80), "white")

        runner = BackgroundSingleAccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=lambda _message: None,
            update_status=lambda _account, status: statuses.append(status),
            operator=FakeOperator(),  # type: ignore[arg-type]
        )
        snapshot = _LoginWindowSnapshot(
            hwnd=100,
            title="斗罗大陆H5-1号",
            image=Image.new("RGB", (80, 80), "white"),
            raw_path=Path("debug_background") / "login.png",
            state="qr_page",
            metrics={"qr_page_evidence": True},
        )
        runner._capture_login_window_background = mock.Mock(return_value=snapshot)  # type: ignore[method-assign]
        runner._open_formal_game_page = mock.Mock(return_value=FakeSession())  # type: ignore[method-assign]
        runner._close_blocking_overlay = mock.Mock(return_value=(True, Image.new("RGB", (80, 80), "white")))  # type: ignore[method-assign]
        runner._open_passport_dialog = mock.Mock(return_value=Image.new("RGB", (80, 80), "white"))  # type: ignore[method-assign]
        runner._input_passport_background = mock.Mock(return_value=Image.new("RGB", (80, 80), "white"))  # type: ignore[method-assign]
        runner._click_confirm_background = mock.Mock(return_value=True)  # type: ignore[method-assign]
        runner._save_latest_success_artifacts = mock.Mock()  # type: ignore[attr-defined]

        with mock.patch(
            "douluo_launcher.background_login.extract_passport_from_login_image",
            return_value=PassportOcrResult(
                passport="fd829a15",
                raw_output="",
                text_region_box=(10, 528, 758, 1046),
                evidence_source="red_bar_box",
                evidence_votes=3,
            ),
        ) as ocr:
            result = runner.run()

        self.assertTrue(result)
        self.assertFalse(closed["value"])
        self.assertEqual(
            statuses,
            [
                "后台截图中",
                "识别通行证中",
                "打开正式页中",
                "关闭公告中",
                "点击通行证中",
                "输入通行证中",
                "确认中",
                "成功",
            ],
        )
        ocr.assert_called_once()
        runner._open_formal_game_page.assert_called_once()
        runner._input_passport_background.assert_called_once()
        self.assertEqual(runner._input_passport_background.call_args.args[2], "fd829a15")
        runner._save_latest_success_artifacts.assert_called_once()

    def test_qr_page_does_not_skip_ocr(self) -> None:
        account = AccountConfig("第一层", 1, 1, "https://example.com")
        runner = BackgroundSingleAccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=lambda _message: None,
            update_status=lambda _account, _status: None,
        )
        snapshot = _LoginWindowSnapshot(
            hwnd=1,
            title="斗罗大陆H5-1号",
            image=Image.new("RGB", (768, 1056), "white"),
            raw_path=Path("debug_background") / "login.png",
            state="qr_page",
            metrics={"qr_page_evidence": True, "qr_evidence_type": "fallback_qr"},
        )

        self.assertFalse(runner._should_skip_ocr(snapshot))


if __name__ == "__main__":
    unittest.main()
