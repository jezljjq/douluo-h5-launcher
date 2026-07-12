from __future__ import annotations

import ctypes
import os
import queue
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_HOTKEY_UPDATE = 0x8001
PM_NOREMOVE = 0x0000
HOTKEY_ID_BASE = 0x5348


@dataclass(frozen=True)
class SpeedHotkeySpec:
    text: str
    modifiers: int
    virtual_key: int


@dataclass(frozen=True)
class SpeedHotkeyBinding:
    rate: float
    spec: SpeedHotkeySpec


def normalize_speed_hotkey_bindings(rows: object) -> list[SpeedHotkeyBinding]:
    if not isinstance(rows, (list, tuple)):
        raise ValueError("多倍率快捷键配置必须是列表")
    bindings: list[SpeedHotkeyBinding] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if isinstance(row, dict):
            rate_value = row.get("rate")
            hotkey_value = row.get("hotkey")
        elif isinstance(row, (list, tuple)) and len(row) == 2:
            rate_value, hotkey_value = row
        else:
            raise ValueError(f"第 {index} 行配置格式无效")
        try:
            rate = float(rate_value)
        except (TypeError, ValueError):
            raise ValueError(f"第 {index} 行倍率必须是正数") from None
        if rate <= 0:
            raise ValueError(f"第 {index} 行倍率必须是正数")
        spec = parse_speed_hotkey(hotkey_value)
        if spec is None:
            raise ValueError(f"第 {index} 行快捷键不能为空")
        if spec.text in seen:
            raise ValueError(f"快捷键重复：{spec.text}")
        seen.add(spec.text)
        bindings.append(SpeedHotkeyBinding(rate, spec))
    return bindings


def parse_speed_hotkey(value: object) -> SpeedHotkeySpec | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = [part.strip() for part in text.replace("＋", "+").split("+") if part.strip()]
    modifiers = 0
    key_name = ""
    normalized_parts: list[str] = []
    for raw_part in parts:
        part = raw_part.upper()
        if part in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
            if "Ctrl" not in normalized_parts:
                normalized_parts.append("Ctrl")
        elif part == "ALT":
            modifiers |= MOD_ALT
            if "Alt" not in normalized_parts:
                normalized_parts.append("Alt")
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
            if "Shift" not in normalized_parts:
                normalized_parts.append("Shift")
        elif key_name:
            raise ValueError("快捷键只能包含一个字母、数字或 F1-F12 主键")
        else:
            key_name = part
    if not key_name:
        raise ValueError("快捷键缺少字母、数字或 F1-F12 主键")
    if len(key_name) == 1 and ("A" <= key_name <= "Z" or "0" <= key_name <= "9"):
        virtual_key = ord(key_name)
    elif key_name.startswith("F") and key_name[1:].isdigit() and 1 <= int(key_name[1:]) <= 12:
        virtual_key = 0x70 + int(key_name[1:]) - 1
    else:
        raise ValueError("快捷键主键仅支持字母、数字或 F1-F12")
    normalized_parts.append(key_name)
    return SpeedHotkeySpec("+".join(normalized_parts), modifiers, virtual_key)


def compose_speed_hotkey(modifier: object, main_key: object, legacy_main_key: object | None = None) -> str:
    # The optional third argument keeps old callers/config migrations readable;
    # the v1.4.14 UI passes one combined modifier and one editable main key.
    if legacy_main_key is not None:
        parts = [str(value or "").strip() for value in (modifier, main_key) if str(value or "").strip() not in {"", "无"}]
        modifier = "+".join(parts) if parts else "无"
        main_key = legacy_main_key
    raw_modifier = str(modifier or "").strip()
    normalized_modifiers = [] if raw_modifier in {"", "无"} else raw_modifier.split("+")
    key = str(main_key or "").strip().upper()
    if not key:
        raise ValueError("请选择字母、数字或 F1-F12 主键")
    value = "+".join([*normalized_modifiers, key])
    spec = parse_speed_hotkey(value)
    assert spec is not None
    return spec.text


class WindowsSpeedHotkey:
    def __init__(
        self,
        callback: Callable[..., None],
        *,
        hotkey_id: int = 0x5348,
        log: Callable[[str], None] | None = None,
        user32=None,
        kernel32=None,
        platform_name: str | None = None,
    ) -> None:
        self._callback = callback
        self._hotkey_id = int(hotkey_id)
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._registered = False
        self._error = ""
        self.spec: SpeedHotkeySpec | None = None
        self.bindings: list[SpeedHotkeyBinding] = []
        self._commands: queue.Queue[tuple[list[SpeedHotkeyBinding], threading.Event, dict[str, object]]] = queue.Queue()
        self._log = log or (lambda _message: None)
        self._user32 = user32
        self._kernel32 = kernel32
        self._platform_name = platform_name or os.name

    def _emit(self, message: str) -> None:
        try:
            self._log(str(message))
        except Exception:
            pass

    def register(self, value: object) -> tuple[bool, str]:
        spec = parse_speed_hotkey(value)
        if spec is None:
            ok, message = self.replace([])
            self.spec = None
            return ok, "加速器快捷键未设置" if ok else message
        ok, message = self.replace([SpeedHotkeyBinding(1.0, spec)])
        if ok:
            self.spec = spec
            return True, f"加速器快捷键已注册：{spec.text}"
        return False, message

    def replace(self, bindings: object) -> tuple[bool, str]:
        try:
            normalized = normalize_speed_hotkey_bindings(
                [{"rate": item.rate, "hotkey": item.spec.text} for item in bindings]
                if all(isinstance(item, SpeedHotkeyBinding) for item in bindings)
                else bindings
            )
        except (TypeError, ValueError) as exc:
            return False, str(exc)
        if self._platform_name != "nt":
            return False, "加速器快捷键仅支持 Windows"
        if self._thread is None or not self._thread.is_alive():
            self._ready.clear()
            self._thread = threading.Thread(target=self._message_loop, daemon=True)
            self._thread.start()
            if not self._ready.wait(2.0):
                self.unregister()
                return False, "加速器快捷键消息线程启动超时"
        done = threading.Event()
        result: dict[str, object] = {}
        self._commands.put((normalized, done, result))
        user32 = self._user32 or ctypes.windll.user32
        user32.PostThreadMessageW(int(self._thread_id), WM_HOTKEY_UPDATE, 0, 0)
        if not done.wait(2.0):
            return False, "加速器快捷键注册超时"
        if not bool(result.get("ok")):
            return False, str(result.get("message") or "加速器快捷键注册失败")
        self.bindings = normalized
        self._registered = bool(normalized)
        return True, f"已注册 {len(normalized)} 组加速器快捷键"

    def unregister(self) -> None:
        thread_id = int(self._thread_id or 0)
        if thread_id and self._platform_name == "nt":
            try:
                user32 = self._user32 or ctypes.windll.user32
                user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = 0
        self._registered = False
        self.bindings = []

    def _message_loop(self, spec: SpeedHotkeySpec | None = None) -> None:
        user32 = self._user32 or ctypes.windll.user32
        kernel32 = self._kernel32 or ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        message = wintypes.MSG()
        # Win32 only creates a thread message queue after the thread calls a
        # user32 message API.  Create it explicitly before RegisterHotKey so a
        # fast key press cannot be lost between registration and GetMessageW.
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_NOREMOVE)
        self._ready.set()
        active: dict[int, SpeedHotkeyBinding] = {}
        if spec is not None:
            active[self._hotkey_id] = SpeedHotkeyBinding(1.0, spec)
            user32.RegisterHotKey(None, self._hotkey_id, spec.modifiers | MOD_NOREPEAT, spec.virtual_key)
        self._emit("已进入 Windows 多倍率快捷键消息循环")
        try:
            while True:
                message_result = int(user32.GetMessageW(ctypes.byref(message), None, 0, 0))
                if message_result == 0:
                    break
                if message_result < 0:
                    self._emit(f"Windows 快捷键消息读取失败：Windows错误码={int(kernel32.GetLastError() or 0)}")
                    break
                if int(message.message) == WM_HOTKEY_UPDATE:
                    try:
                        requested, done, result = self._commands.get_nowait()
                    except queue.Empty:
                        continue
                    old = dict(active)
                    for hotkey_id in old:
                        user32.UnregisterHotKey(None, hotkey_id)
                    active = {}
                    failure = ""
                    for offset, binding in enumerate(requested):
                        hotkey_id = HOTKEY_ID_BASE + offset
                        if not user32.RegisterHotKey(None, hotkey_id, binding.spec.modifiers | MOD_NOREPEAT, binding.spec.virtual_key):
                            error_code = int(kernel32.GetLastError() or 0)
                            failure = f"快捷键 {binding.spec.text} 注册失败：Windows错误码={error_code}"
                            if error_code == 1409:
                                failure = f"快捷键冲突或已被占用：{binding.spec.text}（Windows错误码=1409）"
                            break
                        active[hotkey_id] = binding
                    if failure:
                        for hotkey_id in active:
                            user32.UnregisterHotKey(None, hotkey_id)
                        active = {}
                        rollback_failed = False
                        for hotkey_id, binding in old.items():
                            if user32.RegisterHotKey(None, hotkey_id, binding.spec.modifiers | MOD_NOREPEAT, binding.spec.virtual_key):
                                active[hotkey_id] = binding
                            else:
                                rollback_failed = True
                        result.update(ok=False, message=failure + ("；旧配置回滚失败" if rollback_failed else "；已回滚旧配置"))
                    else:
                        result.update(ok=True, message=f"已注册 {len(active)} 组加速器快捷键")
                    done.set()
                    continue
                hotkey_id = int(message.wParam)
                if int(message.message) == WM_HOTKEY and hotkey_id in active:
                    binding = active[hotkey_id]
                    self._emit(f"已收到 Windows 快捷键：{binding.spec.text}，倍率={binding.rate}")
                    try:
                        try:
                            self._callback(binding.rate)
                        except TypeError:
                            self._callback()
                    except Exception as exc:
                        self._emit(f"快捷键回调分发失败：{type(exc).__name__}: {exc}")
        finally:
            for hotkey_id in active:
                user32.UnregisterHotKey(None, hotkey_id)
            self._registered = False
