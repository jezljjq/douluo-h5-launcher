import unittest
from types import SimpleNamespace

from douluo_launcher.window_operator import (
    BackgroundOperator,
    ForegroundOperator,
    OperationResult,
    WindowOperatorMode,
    build_probe_result,
    images_changed,
)


class FakeUser32:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def PostMessageW(self, *args):
        self.calls.append(("PostMessageW", args))
        return 1

    def SendMessageW(self, *args):
        self.calls.append(("SendMessageW", args))
        return 1

    def SetForegroundWindow(self, *args):
        self.calls.append(("SetForegroundWindow", args))
        return 1


class WindowOperatorTests(unittest.TestCase):
    def test_background_operator_does_not_use_foreground_or_global_mouse(self) -> None:
        fake_user32 = FakeUser32()
        operator = BackgroundOperator(user32=fake_user32, screenshot_func=lambda hwnd: SimpleNamespace(size=(10, 10)))

        result = operator.click(1001, 12, 34)

        self.assertTrue(result.success)
        called_names = [name for name, _ in fake_user32.calls]
        self.assertEqual(called_names, ["PostMessageW", "PostMessageW"])
        self.assertNotIn("SetForegroundWindow", called_names)
        self.assertFalse(operator.uses_global_mouse)
        self.assertFalse(operator.uses_global_keyboard)
        self.assertFalse(operator.calls_set_foreground_window)

    def test_background_operator_input_uses_window_messages_not_global_keyboard(self) -> None:
        fake_user32 = FakeUser32()
        operator = BackgroundOperator(user32=fake_user32, screenshot_func=lambda hwnd: SimpleNamespace(size=(10, 10)))

        result = operator.input_text(1001, "a1")

        self.assertTrue(result.success)
        called_names = [name for name, _ in fake_user32.calls]
        self.assertEqual(called_names, ["PostMessageW", "PostMessageW"])
        self.assertFalse(operator.uses_global_keyboard)
        self.assertFalse(operator.calls_set_foreground_window)

    def test_background_operator_screenshot_uses_hwnd_capture(self) -> None:
        captured_hwnds: list[int] = []
        operator = BackgroundOperator(
            user32=FakeUser32(),
            screenshot_func=lambda hwnd: captured_hwnds.append(hwnd) or SimpleNamespace(size=(320, 540)),
        )

        image = operator.screenshot(2002)

        self.assertEqual(captured_hwnds, [2002])
        self.assertEqual(image.size, (320, 540))

    def test_blackout_hooks_are_safe_noops_until_implemented(self) -> None:
        operator = BackgroundOperator(user32=FakeUser32(), screenshot_func=lambda hwnd: SimpleNamespace(size=(10, 10)))

        self.assertFalse(operator.enable_blackout(1001).success)
        self.assertTrue(operator.disable_blackout(1001).success)
        self.assertTrue(operator.restore_all_blackout().success)

    def test_foreground_operator_remains_declared_fallback(self) -> None:
        operator = ForegroundOperator()

        self.assertEqual(operator.mode, WindowOperatorMode.FOREGROUND)
        self.assertTrue(operator.uses_global_mouse)
        self.assertTrue(operator.uses_global_keyboard)
        self.assertTrue(operator.calls_set_foreground_window)

    def test_probe_result_keeps_complete_json_shape(self) -> None:
        result = build_probe_result(
            background_screenshot=True,
            background_click=False,
            background_input=False,
            mouse_stolen=False,
            keyboard_stolen=False,
            notes="click needs verification",
        )

        self.assertEqual(
            set(result),
            {
                "background_screenshot",
                "background_click",
                "background_input",
                "mouse_stolen",
                "keyboard_stolen",
                "notes",
            },
        )
        self.assertTrue(result["background_screenshot"])
        self.assertFalse(result["background_click"])

    def test_operation_result_failure_has_message(self) -> None:
        result = OperationResult(False, "backend click failed")

        self.assertFalse(result.success)
        self.assertIn("failed", result.message)

    def test_images_changed_detects_real_visual_change(self) -> None:
        from PIL import Image

        before = Image.new("RGB", (8, 8), "black")
        after_same = Image.new("RGB", (8, 8), "black")
        after_changed = Image.new("RGB", (8, 8), "black")
        after_changed.putpixel((0, 0), (255, 255, 255))

        self.assertFalse(images_changed(before, after_same))
        self.assertTrue(images_changed(before, after_changed, threshold=0.001))
