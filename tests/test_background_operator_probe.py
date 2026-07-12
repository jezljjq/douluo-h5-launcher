import unittest
import inspect
import tempfile
from types import SimpleNamespace

import tools.background_operator_probe as background_operator_probe
from tools.background_operator_probe import (
    DEFAULT_INPUT_TEXT,
    classify_game_page_text,
    close_test_window,
    crop_input_box_region,
    detect_passport_input_panel,
    input_method_labels,
    input_box_has_visual_text_change,
    locate_passport_input_box,
    normalize_path_for_compare,
    select_new_browser_window,
    select_new_test_window,
    select_account_url,
    verify_input_text_visible,
    window_summary,
)
from douluo_launcher.config import AccountConfig


class FakeUser32:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.is_window_values: list[bool] = [False]

    def PostMessageW(self, *args):
        self.calls.append(("PostMessageW", args))
        return 1

    def IsWindow(self, hwnd):
        self.calls.append(("IsWindow", (hwnd,)))
        if self.is_window_values:
            return self.is_window_values.pop(0)
        return False


class BackgroundOperatorProbeTests(unittest.TestCase):
    def test_default_input_text_is_8_digit_hex(self) -> None:
        self.assertEqual(DEFAULT_INPUT_TEXT, "a1b2c3d4")

    def test_select_account_url_uses_layer_and_index(self) -> None:
        accounts = [
            AccountConfig("第一层", 1, 1, "https://example.com/one"),
            AccountConfig("第二层", 1, 9, "https://example.com/nine"),
        ]

        self.assertEqual(select_account_url(accounts, "第二层", 1), "https://example.com/nine")

    def test_select_new_test_window_uses_hwnd_difference_and_prefers_game_process(self) -> None:
        before = {1001, 1002}
        after = [
            SimpleNamespace(hwnd=1001, title="斗罗大陆H5-1号"),
            SimpleNamespace(hwnd=1003, title="斗罗大陆H5"),
            SimpleNamespace(hwnd=1004, title="斗罗大陆H5"),
        ]

        selected = select_new_test_window(
            before,
            after,
            game_exe_path=r"E:\Program Files\DLH5\X5Game.exe",
            process_path_getter=lambda hwnd: (
                r"C:\Windows\System32\dwm.exe" if hwnd == 1003 else r"E:\Program Files\DLH5\X5Game.exe"
            ),
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected.hwnd, 1004)

    def test_select_new_test_window_returns_none_without_new_hwnd(self) -> None:
        before = {1001, 1002}
        after = [
            SimpleNamespace(hwnd=1001, title="斗罗大陆H5-1号"),
            SimpleNamespace(hwnd=1002, title="斗罗大陆H5-2号"),
        ]

        self.assertIsNone(select_new_test_window(before, after))

    def test_launch_test_window_probe_does_not_touch_formal_slots(self) -> None:
        source = inspect.getsource(background_operator_probe.launch_test_window_and_probe)

        self.assertNotIn("save_current_windows_as_slots", source)
        self.assertNotIn("refresh_window_slots", source)
        self.assertNotIn("window_slots", source)
        self.assertNotIn("tile_game_windows", source)

    def test_passport_copy_probe_does_not_touch_formal_slots_or_foreground(self) -> None:
        source = inspect.getsource(background_operator_probe.launch_test_window_and_verify_passport_copy)

        for forbidden in (
            "save_current_windows_as_slots",
            "refresh_window_slots",
            "window_slots",
            "tile_game_windows",
            "SetForegroundWindow",
            "SetCursorPos",
            "keybd_event",
            "mouse_event",
        ):
            self.assertNotIn(forbidden, source)

    def test_wait_for_login_passport_page_retries_until_qr_page(self) -> None:
        from PIL import Image

        screenshots: list[int] = []
        sleeps: list[float] = []
        states = iter(
            [
                ("unknown", {"final_reason": "loading"}),
                ("qr_page", {"final_reason": "qr_visible", "passport_bar_box": (1, 2, 3, 4)}),
            ]
        )

        class FakeOperator:
            def screenshot(self, hwnd: int):
                screenshots.append(int(hwnd))
                return Image.new("RGB", (32, 32), "white")

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot, context = background_operator_probe.wait_for_login_passport_page(
                hwnd=3003,
                title="斗罗大陆H5",
                output_dir=background_operator_probe.Path(temp_dir),
                operator=FakeOperator(),
                state_detector=lambda _image: next(states),
                timeout_seconds=30.0,
                interval_seconds=1.0,
                sleep_func=sleeps.append,
            )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.hwnd, 3003)
        self.assertEqual(snapshot.state, "qr_page")
        self.assertEqual(len(screenshots), 2)
        self.assertEqual(sleeps, [1.0])
        self.assertTrue(context["qr_page_detected"])
        self.assertEqual(context["attempts"], 2)

    def test_wait_for_login_passport_page_timeout_saves_launch_artifacts(self) -> None:
        from PIL import Image

        class FakeOperator:
            def screenshot(self, _hwnd: int):
                return Image.new("RGB", (32, 32), "white")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = background_operator_probe.Path(temp_dir)
            snapshot, context = background_operator_probe.wait_for_login_passport_page(
                hwnd=3003,
                title="斗罗大陆H5",
                output_dir=output_dir,
                operator=FakeOperator(),
                state_detector=lambda _image: ("unknown", {"final_reason": "yellow_loading"}),
                timeout_seconds=2.0,
                interval_seconds=1.0,
                sleep_func=lambda _seconds: None,
            )

            self.assertIsNone(snapshot)
            self.assertTrue((output_dir / "latest_launch_timeout.png").exists())
            self.assertTrue((output_dir / "latest_launch_timeout_context.json").exists())

        self.assertFalse(context["qr_page_detected"])
        self.assertEqual(context["final_reason"], "launch_timeout")
        self.assertEqual(context["attempts"], 2)

    def test_save_passport_copy_failure_artifacts_contains_required_context(self) -> None:
        from PIL import Image

        context = background_operator_probe.build_passport_copy_context(
            hwnd=3003,
            title="斗罗大陆H5",
            image_size=(320, 540),
            method_results=[{"method": "wm_gettext", "success": False}],
            child_hwnd_list=[{"hwnd": 4004, "class_name": "Chrome_RenderWidgetHostHWND"}],
            clipboard_used=True,
            clipboard_restored=False,
            final_reason="clipboard_restore_failed",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = background_operator_probe.Path(temp_dir)
            background_operator_probe.save_passport_copy_failure_artifacts(
                output_dir=output_dir,
                image=Image.new("RGB", (32, 32), "white"),
                context=context,
                log_lines=["[后台模式][窗口3003] 剪贴板恢复失败：x"],
            )

            self.assertTrue((output_dir / "latest_passport_copy_input.png").exists())
            self.assertTrue((output_dir / "latest_passport_copy_context.json").exists())
            self.assertTrue((output_dir / "latest_passport_copy.log").exists())
            saved_context = background_operator_probe.json.loads(
                (output_dir / "latest_passport_copy_context.json").read_text(encoding="utf-8")
            )

        for key in (
            "hwnd",
            "title",
            "image_size",
            "method_results",
            "child_hwnd_list",
            "clipboard_used",
            "clipboard_restored",
            "final_reason",
        ):
            self.assertIn(key, saved_context)

    def test_select_new_browser_window_uses_hwnd_difference(self) -> None:
        before = {7001}
        after = [
            SimpleNamespace(hwnd=7001, title="old"),
            SimpleNamespace(hwnd=7002, title="new formal game"),
        ]

        selected = select_new_browser_window(before, after)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.hwnd, 7002)

    def test_classify_game_page_text_detects_login_qr_page(self) -> None:
        self.assertEqual(classify_game_page_text("扫码登录斗罗大陆\n本次通行证：d27796b4"), "login_qr_page")

    def test_classify_game_page_text_detects_formal_game_page(self) -> None:
        self.assertEqual(classify_game_page_text("公告 用户协议 隐私政策 进入游戏"), "formal_game_page")

    def test_passport_panel_detection_uses_dark_input_box_visual_fallback(self) -> None:
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (900, 700), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((280, 180, 650, 470), fill=(190, 190, 190))
        draw.rectangle((410, 300, 560, 325), fill=(70, 70, 70))

        point = locate_passport_input_box(image)

        self.assertIsNotNone(point)
        self.assertTrue(detect_passport_input_panel(image))

    def test_input_visual_text_change_detects_text_entered_in_dark_field(self) -> None:
        from PIL import Image, ImageDraw

        before = Image.new("RGB", (260, 70), (190, 190, 190))
        after = before.copy()
        draw_before = ImageDraw.Draw(before)
        draw_after = ImageDraw.Draw(after)
        draw_before.rectangle((90, 20, 230, 45), fill=(70, 70, 70))
        draw_after.rectangle((90, 20, 230, 45), fill=(70, 70, 70))
        draw_after.text((95, 23), "a1b2c3d4", fill=(230, 230, 230))

        self.assertTrue(input_box_has_visual_text_change(before, after))

    def test_normalize_path_for_compare_is_case_insensitive(self) -> None:
        self.assertEqual(
            normalize_path_for_compare(r"e:/Program Files/DLH5/X5Game.exe"),
            normalize_path_for_compare(r"E:\Program Files\DLH5\X5Game.exe"),
        )

    def test_close_test_window_posts_wm_close_only_to_target(self) -> None:
        fake_user32 = FakeUser32()

        self.assertTrue(close_test_window(2002, user32=fake_user32))
        self.assertGreaterEqual(len(fake_user32.calls), 2)
        self.assertEqual(fake_user32.calls[0][1][0], 2002)

    def test_close_test_window_returns_false_when_window_stays_alive(self) -> None:
        fake_user32 = FakeUser32()
        fake_user32.is_window_values = [True, True, True]

        self.assertFalse(close_test_window(2002, user32=fake_user32, timeout_seconds=0.01))

    def test_window_summary_contains_hwnd_and_title(self) -> None:
        window = SimpleNamespace(hwnd=3003, title="斗罗大陆H5")

        self.assertEqual(window_summary(window), {"hwnd": 3003, "title": "斗罗大陆H5"})

    def test_verify_input_text_visible_requires_ocr_text_match(self) -> None:
        image = object()

        self.assertTrue(verify_input_text_visible(image, "bgtest8", ocr_func=lambda _image: "xx bgtest8 yy"))
        self.assertFalse(verify_input_text_visible(image, "bgtest8", ocr_func=lambda _image: "xx bgtest yy"))

    def test_input_method_all_expands_to_all_methods(self) -> None:
        self.assertEqual(input_method_labels("all"), ["wm_char", "key_sequence", "send_message"])
        self.assertEqual(input_method_labels("wm_char"), ["wm_char"])

    def test_crop_input_box_region_uses_point_bounds(self) -> None:
        from PIL import Image

        image = Image.new("RGB", (100, 80), "white")
        crop = crop_input_box_region(image, (50, 40))

        self.assertGreater(crop.size[0], 1)
        self.assertGreater(crop.size[1], 1)

    def test_launch_probe_without_game_url_marks_input_not_testable(self) -> None:
        from tools import background_operator_probe as probe

        original_launch = probe.launch_game_process
        original_wait = probe.wait_for_new_test_window
        original_close = probe.close_test_window
        original_scan = probe.scan_probe_windows
        try:
            probe.scan_probe_windows = lambda *_args, **_kwargs: []
            probe.launch_game_process = lambda _path: SimpleNamespace(success=True, shell_result=42, error="")
            probe.wait_for_new_test_window = lambda **_kwargs: (
                SimpleNamespace(hwnd=4004, title="斗罗大陆H5"),
                [SimpleNamespace(hwnd=4004, title="斗罗大陆H5")],
            )
            probe.close_test_window = lambda _hwnd: True

            result, exit_code = probe.launch_test_window_and_probe(
                game_exe_path=r"E:\Program Files\DLH5\X5Game.exe",
                title_template="斗罗大陆H5-{index}号",
                output_dir=probe.DEFAULT_DEBUG_DIR,
                click_point=None,
                input_text="a1b2c3d4",
                close_after=True,
                open_game_url=False,
            )
        finally:
            probe.launch_game_process = original_launch
            probe.wait_for_new_test_window = original_wait
            probe.close_test_window = original_close
            probe.scan_probe_windows = original_scan

        self.assertEqual(exit_code, 0)
        self.assertFalse(result["background_input"])
        self.assertFalse(result["game_url_opened"])
        self.assertEqual(result["reason"], "passport input panel only appears after opening bookmark game url")
