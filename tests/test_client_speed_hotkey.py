import inspect
import queue
import threading
import unittest
from types import SimpleNamespace

from douluo_launcher.client_speed_hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    WindowsSpeedHotkey,
    compose_speed_hotkey,
    normalize_speed_hotkey_bindings,
    parse_speed_hotkey,
)


class ClientSpeedHotkeyTests(unittest.TestCase):
    class MultiUser32:
        def __init__(self) -> None:
            self.messages = queue.Queue()
            self.registered = {}
            self.fail_vk = None
            self.register_calls = []

        def PeekMessageW(self, *_args): return 0
        def RegisterHotKey(self, _hwnd, hotkey_id, modifiers, virtual_key):
            self.register_calls.append((hotkey_id, modifiers, virtual_key))
            if virtual_key == self.fail_vk:
                return 0
            self.registered[hotkey_id] = (modifiers, virtual_key)
            return 1
        def UnregisterHotKey(self, _hwnd, hotkey_id):
            self.registered.pop(hotkey_id, None)
            return 1
        def PostThreadMessageW(self, _thread_id, message, wparam, _lparam):
            self.messages.put((message, wparam))
            return 1
        def GetMessageW(self, message_ptr, *_args):
            message, wparam = self.messages.get(timeout=2)
            if message == 0x0012:
                return 0
            message_ptr._obj.message = message
            message_ptr._obj.wParam = wparam
            return 1

    class Kernel32:
        def __init__(self, user32) -> None:
            self.user32 = user32
        def GetCurrentThreadId(self): return 77
        def GetLastError(self): return 1409 if self.user32.fail_vk is not None else 0

    def test_parse_supports_modifiers_letters_digits_and_function_keys(self) -> None:
        letter = parse_speed_hotkey("ctrl+shift+k")
        digit = parse_speed_hotkey("Alt+8")
        function = parse_speed_hotkey("Ctrl+Alt+F12")

        self.assertEqual((letter.text, letter.modifiers, letter.virtual_key), ("Ctrl+Shift+K", MOD_CONTROL | MOD_SHIFT, ord("K")))
        self.assertEqual((digit.text, digit.modifiers, digit.virtual_key), ("Alt+8", MOD_ALT, ord("8")))
        self.assertEqual(function.text, "Ctrl+Alt+F12")
        self.assertEqual(function.virtual_key, 0x7B)

    def test_parse_supports_clear_single_keys_and_rejects_unsupported_keys(self) -> None:
        self.assertIsNone(parse_speed_hotkey(""))
        self.assertEqual(parse_speed_hotkey(" K ").text, "K")
        for value in ("Ctrl+Esc", "Ctrl+F13", "Ctrl+A+B"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_speed_hotkey(value)

    def test_dropdown_parts_compose_normalized_hotkey(self) -> None:
        self.assertEqual(compose_speed_hotkey("Ctrl+Shift", " f9 "), "Ctrl+Shift+F9")
        self.assertEqual(compose_speed_hotkey("Alt", "8"), "Alt+8")
        self.assertEqual(compose_speed_hotkey("无", " 9 "), "9")

    def test_dropdown_parts_report_missing_or_invalid_main_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "请选择.*主键"):
            compose_speed_hotkey("Ctrl", "")
        with self.assertRaisesRegex(ValueError, "仅支持"):
            compose_speed_hotkey("Ctrl+Alt+Shift", "Esc")

    def test_multi_bindings_normalize_and_reject_duplicate_or_invalid_rate(self) -> None:
        rows = [{"rate": 3, "hotkey": "alt+2"}, {"rate": 6, "hotkey": "Alt+3"}]
        bindings = normalize_speed_hotkey_bindings(rows)
        self.assertEqual([(item.rate, item.spec.text) for item in bindings], [(3.0, "Alt+2"), (6.0, "Alt+3")])
        with self.assertRaisesRegex(ValueError, "重复"):
            normalize_speed_hotkey_bindings([rows[0], {"rate": 6, "hotkey": "ALT+2"}])
        with self.assertRaisesRegex(ValueError, "正数"):
            normalize_speed_hotkey_bindings([{"rate": 0, "hotkey": "Alt+2"}])

    def test_multi_registration_reuses_one_thread_and_dispatches_rate(self) -> None:
        user32 = self.MultiUser32()
        received = []
        listener = WindowsSpeedHotkey(received.append, user32=user32, kernel32=self.Kernel32(user32), platform_name="nt")
        rows = [{"rate": 3, "hotkey": "Alt+2"}, {"rate": 6, "hotkey": "Alt+3"}, {"rate": 20, "hotkey": "Alt+4"}, {"rate": 50, "hotkey": "Alt+5"}]
        self.assertTrue(listener.replace(rows)[0])
        thread = listener._thread
        self.assertTrue(listener.replace(rows)[0])
        self.assertIs(listener._thread, thread)
        user32.PostThreadMessageW(77, 0x0312, 0x5349, 0)
        for _ in range(100):
            if received: break
            threading.Event().wait(0.001)
        self.assertEqual(received, [6.0])
        listener.unregister()

    def test_atomic_registration_failure_rolls_back_old_mapping(self) -> None:
        user32 = self.MultiUser32()
        listener = WindowsSpeedHotkey(lambda _rate: None, user32=user32, kernel32=self.Kernel32(user32), platform_name="nt")
        old_rows = [{"rate": 3, "hotkey": "Alt+2"}, {"rate": 6, "hotkey": "Alt+3"}]
        self.assertTrue(listener.replace(old_rows)[0])
        old_registered = dict(user32.registered)
        user32.fail_vk = ord("4")
        ok, message = listener.replace([{"rate": 3, "hotkey": "Alt+2"}, {"rate": 20, "hotkey": "Alt+4"}])
        self.assertFalse(ok)
        self.assertIn("Alt+4", message)
        self.assertIn("1409", message)
        self.assertEqual(user32.registered, old_registered)
        listener.unregister()

    def test_windows_registration_uses_no_repeat_and_unregisters_on_stop(self) -> None:
        source = inspect.getsource(WindowsSpeedHotkey)

        self.assertIn("spec.modifiers | MOD_NOREPEAT", source)
        self.assertIn("RegisterHotKey", source)
        self.assertIn("UnregisterHotKey", source)
        self.assertIn("PostThreadMessageW", source)
        self.assertIn("PeekMessageW", source)
        self.assertIn("PM_NOREMOVE", source)
        self.assertEqual(MOD_NOREPEAT, 0x4000)

    def test_windows_message_loop_receives_hotkey_and_dispatches_callback(self) -> None:
        callbacks = []
        logs = []

        class User32:
            def __init__(self) -> None:
                self.reads = 0
                self.unregistered = False

            def PeekMessageW(self, *_args):
                return 0

            def RegisterHotKey(self, *_args):
                return 1

            def GetMessageW(self, message_ptr, *_args):
                self.reads += 1
                if self.reads == 1:
                    message_ptr._obj.message = 0x0312
                    message_ptr._obj.wParam = 0x5348
                    return 1
                return 0

            def UnregisterHotKey(self, *_args):
                self.unregistered = True
                return 1

        user32 = User32()
        kernel32 = SimpleNamespace(GetCurrentThreadId=lambda: 77, GetLastError=lambda: 0)
        listener = WindowsSpeedHotkey(
            lambda: callbacks.append("called"),
            user32=user32,
            kernel32=kernel32,
            platform_name="nt",
            log=logs.append,
        )
        spec = parse_speed_hotkey("Ctrl+9")
        assert spec is not None

        listener._message_loop(spec)

        self.assertEqual(callbacks, ["called"])
        self.assertTrue(user32.unregistered)
        self.assertTrue(any("已收到 Windows 快捷键" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
