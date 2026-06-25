from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_LBUTTON = 0x0001


class WindowOperatorMode(str, Enum):
    FOREGROUND = "foreground"
    BACKGROUND = "background"


@dataclass(frozen=True)
class OperationResult:
    success: bool
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


class WindowOperator:
    mode: WindowOperatorMode
    uses_global_mouse: bool
    uses_global_keyboard: bool
    calls_set_foreground_window: bool

    def screenshot(self, hwnd: int):
        raise NotImplementedError

    def click(self, hwnd: int, x: int, y: int) -> OperationResult:
        raise NotImplementedError

    def input_text(self, hwnd: int, text: str) -> OperationResult:
        raise NotImplementedError

    def key_press(self, hwnd: int, key: int) -> OperationResult:
        raise NotImplementedError

    def enable_blackout(self, hwnd: int) -> OperationResult:
        return OperationResult(False, "黑屏保护接口已预留，本轮未启用", {"hwnd": int(hwnd)})

    def disable_blackout(self, hwnd: int) -> OperationResult:
        return OperationResult(True, "黑屏保护未启用，无需恢复", {"hwnd": int(hwnd)})

    def restore_all_blackout(self) -> OperationResult:
        return OperationResult(True, "黑屏保护未启用，无需恢复")


class ForegroundOperator(WindowOperator):
    """当前稳定 fallback 的能力声明。

    具体前台登录流程仍由现有 AccountRunner / dm_click_helper 执行，本类先作为
    新后台抽象层的兼容入口，不改动稳定链路。
    """

    mode = WindowOperatorMode.FOREGROUND
    uses_global_mouse = True
    uses_global_keyboard = True
    calls_set_foreground_window = True

    def screenshot(self, hwnd: int):
        raise NotImplementedError("前台模式截图仍使用现有稳定流程")

    def click(self, hwnd: int, x: int, y: int) -> OperationResult:
        return OperationResult(
            False,
            "前台模式点击仍使用现有稳定流程，本抽象层未接管",
            {"hwnd": int(hwnd), "x": int(x), "y": int(y)},
        )

    def input_text(self, hwnd: int, text: str) -> OperationResult:
        return OperationResult(
            False,
            "前台模式输入仍使用现有稳定流程，本抽象层未接管",
            {"hwnd": int(hwnd), "text_length": len(str(text))},
        )

    def key_press(self, hwnd: int, key: int) -> OperationResult:
        return OperationResult(
            False,
            "前台模式按键仍使用现有稳定流程，本抽象层未接管",
            {"hwnd": int(hwnd), "key": int(key)},
        )


class BackgroundOperator(WindowOperator):
    mode = WindowOperatorMode.BACKGROUND
    uses_global_mouse = False
    uses_global_keyboard = False
    calls_set_foreground_window = False

    def __init__(
        self,
        *,
        user32: Any | None = None,
        screenshot_func: Callable[[int], Any] | None = None,
    ) -> None:
        self._user32 = user32 or ctypes.windll.user32
        self._screenshot_func = screenshot_func or capture_hwnd_background

    def screenshot(self, hwnd: int):
        return self._screenshot_func(int(hwnd))

    def click(self, hwnd: int, x: int, y: int) -> OperationResult:
        hwnd = int(hwnd)
        x = int(x)
        y = int(y)
        lparam = _make_lparam(x, y)
        down_ok = bool(self._user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam))
        up_ok = bool(self._user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam))
        ok = down_ok and up_ok
        return OperationResult(
            ok,
            "后台消息点击已发送" if ok else "后台消息点击发送失败",
            {
                "hwnd": hwnd,
                "x": x,
                "y": y,
                "down_ok": down_ok,
                "up_ok": up_ok,
                "method": "PostMessageW WM_LBUTTONDOWN/UP",
            },
        )

    def input_text(self, hwnd: int, text: str) -> OperationResult:
        hwnd = int(hwnd)
        failures: list[str] = []
        for char in str(text):
            ok = bool(self._user32.PostMessageW(hwnd, WM_CHAR, ord(char), 0))
            if not ok:
                failures.append(char)
        success = not failures
        return OperationResult(
            success,
            "后台 WM_CHAR 输入已发送" if success else "后台 WM_CHAR 输入部分失败",
            {
                "hwnd": hwnd,
                "text_length": len(str(text)),
                "failed_count": len(failures),
                "method": "PostMessageW WM_CHAR",
            },
        )

    def key_press(self, hwnd: int, key: int) -> OperationResult:
        hwnd = int(hwnd)
        key = int(key)
        down_ok = bool(self._user32.PostMessageW(hwnd, WM_KEYDOWN, key, 0))
        up_ok = bool(self._user32.PostMessageW(hwnd, WM_KEYUP, key, 0))
        ok = down_ok and up_ok
        return OperationResult(
            ok,
            "后台按键消息已发送" if ok else "后台按键消息发送失败",
            {"hwnd": hwnd, "key": key, "down_ok": down_ok, "up_ok": up_ok},
        )


def capture_hwnd_background(hwnd: int):
    from .dm_client import WindowInfo, capture_window_background
    from .window_manager import get_window_class_name, get_window_process_id, get_window_rect

    rect = get_window_rect(int(hwnd))
    try:
        class_name = get_window_class_name(int(hwnd))
    except Exception:
        class_name = ""
    try:
        pid = get_window_process_id(int(hwnd))
    except Exception:
        pid = 0
    window = WindowInfo(
        hwnd=int(hwnd),
        title="",
        width=rect.width,
        height=rect.height,
        class_name=class_name,
        pid=int(pid or 0),
        left=rect.left,
        top=rect.top,
        right=rect.right,
        bottom=rect.bottom,
    )
    return capture_window_background(window)


def build_probe_result(
    *,
    background_screenshot: bool,
    background_click: bool,
    background_input: bool,
    mouse_stolen: bool,
    keyboard_stolen: bool,
    notes: str,
) -> dict[str, object]:
    return {
        "background_screenshot": bool(background_screenshot),
        "background_click": bool(background_click),
        "background_input": bool(background_input),
        "mouse_stolen": bool(mouse_stolen),
        "keyboard_stolen": bool(keyboard_stolen),
        "notes": str(notes),
    }


def images_changed(before: Any, after: Any, *, threshold: float = 0.01) -> bool:
    if before is None or after is None:
        return False
    if getattr(before, "size", None) != getattr(after, "size", None):
        return True
    try:
        from PIL import ImageChops

        diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
        extrema = diff.convert("L").getextrema()
        if extrema[1] <= 0:
            return False
        histogram = diff.convert("L").histogram()
        total_pixels = before.size[0] * before.size[1]
        changed_pixels = total_pixels - histogram[0]
        return (changed_pixels / max(1, total_pixels)) >= float(threshold)
    except Exception:
        return False


def _make_lparam(x: int, y: int) -> int:
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)
