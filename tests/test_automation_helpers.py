import threading
import tempfile
import unittest
import json
import inspect
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
    extract_passport_from_login_image,
)
from douluo_launcher.config import AccountConfig, AutomationSettings


class AutomationHelperTests(unittest.TestCase):
    def _make_runner(self) -> AccountRunner:
        account = AccountConfig(level="单层账号", bookmark_no=1, game_window_no=1, url="https://example.com")
        return AccountRunner(
            account,
            AutomationSettings(),
            threading.Event(),
            log=lambda _msg: None,
            update_status=lambda _account, _status: None,
        )

    def test_extracts_passport_from_visible_text(self) -> None:
        text = "扫码登录\n本次通行证：8598a293\n请使用手机扫码"

        self.assertEqual(extract_passport_from_text(text, r"本次通行证\s*[:：]\s*([A-Za-z0-9_-]+)"), "8598a293")

    def test_extracts_passport_when_spacing_changes(self) -> None:
        text = "本次通行证 : 8598a293"

        self.assertEqual(extract_passport_from_text(text, r"本次通行证\s*[:：]\s*([A-Za-z0-9_-]+)"), "8598a293")

    def test_extracts_hex_passport_from_ocr_noise(self) -> None:
        self.assertEqual(extract_hex_passport("foo 8598a293 bar"), "8598a293")
        self.assertEqual(extract_hex_passport("8598 a293"), "8598a293")

    def test_background_login_image_ocr_failure_saves_red_bar_artifacts_without_fallbacks(self) -> None:
        runner = self._make_runner()
        runner._ocr_passport_from_text_region = self._forbidden_background_ocr_call("text_region")  # type: ignore[method-assign]
        runner._ocr_passport_by_template_match = self._forbidden_background_ocr_call("template")  # type: ignore[method-assign]
        runner._ocr_passport_from_login_image = self._forbidden_background_ocr_call("full_image")  # type: ignore[method-assign]
        runner._ocr_passport_from_red_bar_region = lambda *_args, **_kwargs: automation_module.RedBarLocalOcrResult(  # type: ignore[method-assign]
            passport=None,
            red_bar_box=(46, 885, 721, 950),
            local_box=(400, 900, 520, 940),
            candidates={},
            accepted=False,
            reject_reason="RED_BAR_OCR_LOW_CONFIDENCE",
            crop_image=Image.new("RGB", (120, 40), "white"),
            preprocessed_image=Image.new("L", (120, 40), "white"),
        )
        image = Image.new("RGB", (768, 1056), "white")

        with tempfile.TemporaryDirectory() as temp_dir:
            debug_dir = Path(temp_dir)
            result = extract_passport_from_login_image(
                image,
                runner=runner,
                window_index=1,
                debug_dir=debug_dir,
                mode="background",
                raw_path=debug_dir / "source.png",
                login_context={
                    "hwnd": 71756,
                    "title": "斗罗大陆H5-1号",
                    "login_page_state": "qr_page",
                    "qr_box": None,
                    "fallback_qr_box": (243, 199, 578, 534),
                    "red_bar_box": (46, 885, 721, 950),
                },
                save_failure_artifacts=True,
            )

            self.assertIsNone(result.passport)
            self.assertEqual(result.failure_reason, "RED_BAR_OCR_LOW_CONFIDENCE")
            self.assertTrue((debug_dir / "latest_passport_extract_input.png").exists())
            self.assertTrue((debug_dir / "latest_passport_extract_red_bar_crop.png").exists())
            self.assertTrue((debug_dir / "latest_passport_extract_red_bar_preprocessed.png").exists())
            self.assertTrue((debug_dir / "latest_passport_extract_raw.txt").exists())
            self.assertFalse((debug_dir / "latest_ocr_input.png").exists())
            context = json.loads((debug_dir / "latest_passport_extract_context.json").read_text(encoding="utf-8"))

        self.assertEqual(context["hwnd"], 71756)
        self.assertEqual(context["title"], "斗罗大陆H5-1号")
        self.assertEqual(context["image_size"], [768, 1056])
        self.assertEqual(context["login_page_state"], "qr_page")
        self.assertEqual(context["red_bar_box"], [46, 885, 721, 950])
        self.assertEqual(context["failure_reason"], "RED_BAR_OCR_LOW_CONFIDENCE")

    @staticmethod
    def _forbidden_background_ocr_call(name: str):
        def forbidden(*_args, **_kwargs):
            raise AssertionError(f"background mode must not call {name}")

        return forbidden

    def test_shared_login_image_ocr_uses_same_frontend_sequence(self) -> None:
        runner = self._make_runner()
        calls: list[str] = []
        runner._ocr_passport_from_text_region = lambda *_args, **_kwargs: calls.append("text_region") or None  # type: ignore[method-assign]
        runner._ocr_passport_by_template_match = lambda *_args, **_kwargs: calls.append("template") or None  # type: ignore[method-assign]
        runner._ocr_passport_from_login_image = lambda *_args, **_kwargs: calls.append("full_image") or "D40786FA"  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory() as temp_dir:
            result = extract_passport_from_login_image(
                Image.new("RGB", (768, 1056), "white"),
                runner=runner,
                window_index=1,
                debug_dir=Path(temp_dir),
                mode="foreground",
                raw_path=Path(temp_dir) / "source.png",
            )

        self.assertEqual(result.passport, "d40786fa")
        self.assertEqual(calls, ["text_region", "template", "full_image"])

    def test_background_login_image_ocr_uses_only_red_bar_local_evidence(self) -> None:
        runner = self._make_runner()
        calls: list[str] = []
        runner._ocr_passport_from_text_region = self._forbidden_background_ocr_call("text_region")  # type: ignore[method-assign]
        runner._ocr_passport_by_template_match = self._forbidden_background_ocr_call("template")  # type: ignore[method-assign]
        runner._ocr_passport_from_login_image = self._forbidden_background_ocr_call("full_image")  # type: ignore[method-assign]
        runner._ocr_passport_from_red_bar_region = lambda *_args, **_kwargs: calls.append("red_bar") or automation_module.RedBarLocalOcrResult(  # type: ignore[method-assign]
            passport="d40786fa",
            red_bar_box=(100, 200, 900, 300),
            local_box=(500, 215, 676, 295),
            candidates={"d40786fa": 3},
            variants=(),
            accepted=True,
            reject_reason="",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = extract_passport_from_login_image(
                Image.new("RGB", (1000, 500), "white"),
                runner=runner,
                window_index=1,
                debug_dir=Path(temp_dir),
                mode="background",
                raw_path=Path(temp_dir) / "source.png",
                login_context={"red_bar_box": (100, 200, 900, 300)},
            )

        self.assertEqual(result.passport, "d40786fa")
        self.assertEqual(result.evidence_source, "red_bar_box")
        self.assertEqual(result.evidence_votes, 3)
        self.assertEqual(calls, ["red_bar"])

    def test_red_bar_local_box_uses_red_bar_ratios_not_fixed_pixels(self) -> None:
        runner = self._make_runner()
        image = Image.new("RGB", (1000, 500), "white")

        box = runner._red_bar_local_box(image, (100, 200, 900, 300))

        self.assertEqual(box, (500, 215, 676, 295))

    def test_red_bar_local_ocr_accepts_multi_vote_candidate(self) -> None:
        runner = self._make_runner()
        image = Image.new("RGB", (1000, 500), "white")
        outputs = iter(("F9dbc943", "", "F9dbc943", "F9dbc943", ""))

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "pytesseract.image_to_string",
            side_effect=lambda *_args, **_kwargs: next(outputs, ""),
        ):
            result = runner._ocr_passport_from_red_bar_region(
                image,
                (100, 200, 900, 300),
                "red_bar_test",
                Path(temp_dir),
            )

        self.assertEqual(result.passport, "f9dbc943")
        self.assertTrue(result.accepted)
        self.assertGreaterEqual(result.candidates["f9dbc943"], 3)

    def test_red_bar_local_ocr_rejects_single_hit(self) -> None:
        runner = self._make_runner()
        image = Image.new("RGB", (1000, 500), "white")
        outputs = iter(("F9dbc943", "", "", "", ""))

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "pytesseract.image_to_string",
            side_effect=lambda *_args, **_kwargs: next(outputs, ""),
        ):
            result = runner._ocr_passport_from_red_bar_region(
                image,
                (100, 200, 900, 300),
                "red_bar_test",
                Path(temp_dir),
            )

        self.assertIsNone(result.passport)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reject_reason, "RED_BAR_OCR_LOW_CONFIDENCE")

    def test_red_bar_local_ocr_rejects_conflicting_candidates(self) -> None:
        runner = self._make_runner()
        image = Image.new("RGB", (1000, 500), "white")
        outputs = iter(("F9dbc943", "F9db0943", "F9dbc943", "F9db0943", ""))

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "pytesseract.image_to_string",
            side_effect=lambda *_args, **_kwargs: next(outputs, ""),
        ):
            result = runner._ocr_passport_from_red_bar_region(
                image,
                (100, 200, 900, 300),
                "red_bar_test",
                Path(temp_dir),
            )

        self.assertIsNone(result.passport)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reject_reason, "RED_BAR_OCR_CONFLICT")

    def test_red_bar_local_ocr_failure_saves_extract_artifacts(self) -> None:
        runner = self._make_runner()
        runner._ocr_passport_from_text_region = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
        runner._ocr_passport_by_template_match = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
        runner._ocr_passport_from_login_image = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
        image = Image.new("RGB", (1000, 500), "white")

        with tempfile.TemporaryDirectory() as temp_dir, patch("pytesseract.image_to_string", return_value=""):
            debug_dir = Path(temp_dir)
            result = extract_passport_from_login_image(
                image,
                runner=runner,
                window_index=1,
                debug_dir=debug_dir,
                mode="background",
                raw_path=debug_dir / "source.png",
                login_context={
                    "hwnd": 71756,
                    "title": "斗罗大陆H5-1号",
                    "login_page_state": "qr_page",
                    "red_bar_box": (100, 200, 900, 300),
                },
                save_failure_artifacts=True,
            )
            candidates = json.loads((debug_dir / "latest_passport_extract_candidates.json").read_text(encoding="utf-8"))
            context = json.loads((debug_dir / "latest_passport_extract_context.json").read_text(encoding="utf-8"))
            self.assertIsNone(result.passport)
            self.assertTrue((debug_dir / "latest_passport_extract_input.png").exists())
            self.assertTrue((debug_dir / "latest_passport_extract_red_bar_crop.png").exists())
            self.assertTrue((debug_dir / "latest_passport_extract_red_bar_preprocessed.png").exists())
            self.assertTrue((debug_dir / "latest_passport_extract_raw.txt").exists())
            self.assertEqual(context["red_bar_box"], [100, 200, 900, 300])
            self.assertEqual(context["red_bar_local_box"], [500, 215, 676, 295])
            self.assertFalse(candidates["accepted"])
            self.assertEqual(candidates["reject_reason"], "RED_BAR_OCR_LOW_CONFIDENCE")

    def test_login_window_extraction_keeps_copy_before_ocr(self) -> None:
        source = inspect.getsource(AccountRunner._extract_passport_from_login_window)

        self.assertLess(
            source.index("_copy_passport_from_login_window"),
            source.index("extract_passport_from_login_image"),
        )

    def test_full_image_ocr_accepts_hex_when_label_is_garbled(self) -> None:
        runner = self._make_runner()
        runner._save_latest_ocr_success = lambda _image: None  # type: ignore[method-assign]
        image = Image.new("RGB", (768, 1056), "white")

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "pytesseract.image_to_string",
            return_value="AORIB{TIE: 92cd7352 —",
        ):
            passport = runner._ocr_passport_from_login_image(image, "offline_test", Path(temp_dir) / "source.png")

        self.assertEqual(passport, "92cd7352")

    def test_ocr_candidate_accepts_three_consistent_votes_but_rejects_single_vote(self) -> None:
        runner = self._make_runner()

        accepted, failure = runner._decide_ocr_candidate("全图", {"92cd7352": 3})
        rejected, rejected_failure = runner._decide_ocr_candidate("模板匹配", {"92cd7352": 1})

        self.assertEqual(accepted, "92cd7352")
        self.assertIsNone(failure)
        self.assertIsNone(rejected)
        self.assertEqual(rejected_failure, "OCR_LOW_CONFIDENCE")

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

    def test_passport_button_cache_success_waits_for_dialog_before_input(self) -> None:
        runner = self._make_runner()
        clicked: list[tuple[int, int]] = []
        runner._get_browser_viewport_size = lambda _hwnd: (960, 720)  # type: ignore[method-assign]
        runner._capture_browser_client = lambda _hwnd, _name=None: Image.new("RGB", (960, 720))  # type: ignore[method-assign]
        runner._is_passport_dialog_visible_by_ocr = lambda _image: True  # type: ignore[method-assign]
        runner._locate_passport_input_center = lambda _image, log_result=False: (300, 330)  # type: ignore[method-assign]
        runner._locate_confirm_button_center = lambda _image, log_result=False: (520, 520)  # type: ignore[method-assign]
        runner._dm_click_viewport = lambda x, y, _label, _hold=120: clicked.append((x, y)) or True  # type: ignore[method-assign]
        runner._dm_chain = lambda _steps, _label="": self.fail("弹窗出现前不应调用输入+确认")  # type: ignore[method-assign]
        runner._save_passport_dialog_coord_cache = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        controls = runner._click_passport_button_with_retry(
            browser_hwnd=100,
            btn_pos=(680, 300),
            label="方式一",
            viewport_key=(960, 720),
            used_cache=True,
            cache_source="dialog_cache",
            first_wait_timeout_s=0.05,
            retry_wait_timeout_s=0.05,
        )

        self.assertEqual(controls, (300, 330, 520, 520))
        self.assertEqual(clicked, [(680, 300)])

    def test_passport_button_cache_failure_clears_cache_and_retemplates(self) -> None:
        runner = self._make_runner()
        AccountRunner._cached_btn = (680, 300)
        AccountRunner._cached_window_size = (runner.settings.window_width, runner.settings.window_height)
        AccountRunner._dialog_coord_cache[(960, 720)] = ((680, 300), (301, 331), (521, 521))
        clicked: list[tuple[int, int]] = []
        visible = iter([False, True])
        runner._get_browser_viewport_size = lambda _hwnd: (960, 720)  # type: ignore[method-assign]
        runner._capture_browser_client = lambda _hwnd, _name=None: Image.new("RGB", (960, 720))  # type: ignore[method-assign]
        runner._is_passport_dialog_visible_by_ocr = lambda _image: next(visible)  # type: ignore[method-assign]
        runner._locate_passport_input_center = lambda _image, log_result=False: (310, 340)  # type: ignore[method-assign]
        runner._locate_confirm_button_center = lambda _image, log_result=False: (530, 540)  # type: ignore[method-assign]
        runner._dm_click_viewport = lambda x, y, _label, _hold=120: clicked.append((x, y)) or True  # type: ignore[method-assign]
        runner._locate_passport_button_with_details = lambda _image, use_fallback=False: ((700, 360), 0.91, "template")  # type: ignore[method-assign]
        runner._save_passport_dialog_coord_cache = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        controls = runner._click_passport_button_with_retry(
            browser_hwnd=100,
            btn_pos=(680, 300),
            label="方式一",
            viewport_key=(960, 720),
            used_cache=True,
            cache_source="dialog_cache",
            first_wait_timeout_s=0.05,
            retry_wait_timeout_s=0.05,
        )

        self.assertEqual(controls, (310, 340, 530, 540))
        self.assertEqual(clicked, [(680, 300), (700, 360)])
        self.assertEqual(AccountRunner._dialog_coord_cache[(960, 720)][0], (700, 360))
        self.assertEqual(AccountRunner._cached_btn, (700, 360))

    def test_passport_button_two_failed_clicks_raise_without_input(self) -> None:
        runner = self._make_runner()
        saved_contexts: list[dict] = []
        runner._get_browser_viewport_size = lambda _hwnd: (960, 720)  # type: ignore[method-assign]
        runner._capture_browser_client = lambda _hwnd, _name=None: Image.new("RGB", (960, 720))  # type: ignore[method-assign]
        runner._is_passport_dialog_visible_by_ocr = lambda _image: False  # type: ignore[method-assign]
        runner._dm_click_viewport = lambda _x, _y, _label, _hold=120: True  # type: ignore[method-assign]
        runner._locate_passport_button_with_details = lambda _image, use_fallback=False: ((700, 360), 0.88, "template")  # type: ignore[method-assign]
        runner._save_passport_click_failure_context = lambda _hwnd, context, _image=None: saved_contexts.append(context)  # type: ignore[method-assign]
        runner._dm_chain = lambda _steps, _label="": self.fail("弹窗未出现时不能调用输入+确认")  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "通行证弹窗未出现"):
            runner._click_passport_button_with_retry(
                browser_hwnd=100,
                btn_pos=(680, 300),
                label="方式一",
                viewport_key=(960, 720),
                used_cache=True,
                cache_source="dialog_cache",
                first_wait_timeout_s=0.05,
                retry_wait_timeout_s=0.05,
            )

        self.assertTrue(saved_contexts)
        self.assertFalse(saved_contexts[-1]["dialog_detected"])

    def test_fast_dm_chain_path_is_disabled_until_dialog_is_verified(self) -> None:
        runner = self._make_runner()
        runner._dm_chain = lambda _steps, _label="": self.fail("禁用快路径不能调用输入+确认 chain")  # type: ignore[method-assign]

        result = runner._click_passport_button_input_confirm_fast(
            (960, 720),
            680,
            300,
            "8598a293",
            "方式一",
        )

        self.assertFalse(result)

    def test_passport_button_click_must_be_inside_viewport(self) -> None:
        runner = self._make_runner()
        saved_contexts: list[dict] = []
        runner._get_browser_viewport_size = lambda _hwnd: (960, 720)  # type: ignore[method-assign]
        runner._save_passport_click_failure_context = lambda _hwnd, context, _image=None: saved_contexts.append(context)  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "通行证按钮坐标超出当前窗口客户区"):
            runner._click_passport_button_with_retry(
                browser_hwnd=100,
                btn_pos=(1200, 300),
                label="方式一",
                viewport_key=(960, 720),
                used_cache=False,
                cache_source="template",
            )

        self.assertEqual(saved_contexts[-1]["reject_reason"], "button_outside_viewport")


if __name__ == "__main__":
    unittest.main()
