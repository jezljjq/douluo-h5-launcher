"""Dm 前台输入辅助脚本 — 32位 Python 调用。

不使用 BindWindow。只做前台鼠标/键盘模拟。
"""

import json
import subprocess as _sp
import sys
import time
from pathlib import Path

import win32com.client
import win32con
import win32gui

info = json.loads(Path("debug_ocr/browser_pos.json").read_text())
cx, cy = int(info["cx"]), int(info["cy"])
hwnd = int(info.get("hwnd", 0) or 0)


def bring_to_front() -> None:
    if not hwnd:
        return
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.05)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.08)
    except Exception:
        pass


dm = win32com.client.Dispatch("dm.dmsoft")


def _do_click(vx, vy, hold_ms):
    sx, sy = cx + int(vx), cy + int(vy)
    dm.MoveTo(sx, sy)
    time.sleep(0.08)
    try:
        dm.LeftDown()
        time.sleep(max(0, int(hold_ms)) / 1000)
        dm.LeftUp()
    except Exception:
        dm.LeftClick()
    return f"click({vx},{vy})"


def _do_type(text):
    import subprocess as _sp
    _sp.run(["clip"], input=str(text), text=True, creationflags=_sp.CREATE_NO_WINDOW)
    time.sleep(0.08)
    dm.KeyDown(17)
    time.sleep(0.03)
    dm.KeyPress(86)
    time.sleep(0.03)
    dm.KeyUp(17)
    return f"type({text})"


if len(sys.argv) >= 2 and sys.argv[1] == "chain":
    # 链式操作：click|type|click 合并为一次子进程调用
    bring_to_front()
    time.sleep(0.05)
    results = []
    for step in sys.argv[2].split("|"):
        parts = step.split(",")
        if parts[0] == "click":
            r = _do_click(parts[1], parts[2], parts[3] if len(parts) > 3 else 120)
        elif parts[0] == "type":
            r = _do_type(parts[1])
        elif parts[0] == "wait":
            time.sleep(max(0, int(parts[1])) / 1000)
            r = f"wait({parts[1]}ms)"
        else:
            r = f"unknown:{step}"
        results.append(r)
    print("DM_CHAIN: " + " | ".join(results))
elif len(sys.argv) >= 2 and sys.argv[1] == "type":
    text = sys.argv[2]
    bring_to_front()
    time.sleep(0.1)
    # 用 clip.exe 设置剪贴板（避免 OpenClipboard 冲突）
    _sp.run(["clip"], input=text, text=True)
    time.sleep(0.1)
    # Dm 发送 Ctrl+V 粘贴
    dm.KeyDown(17)
    time.sleep(0.03)
    dm.KeyPress(86)
    time.sleep(0.03)
    dm.KeyUp(17)
    print(f"DM_TYPE: {text}")
else:
    if len(sys.argv) >= 2 and sys.argv[1] == "click":
        vx, vy = int(sys.argv[2]), int(sys.argv[3])
        hold_ms = int(sys.argv[4]) if len(sys.argv) >= 5 else 120
    else:
        vx, vy = int(sys.argv[1]), int(sys.argv[2])
        hold_ms = int(sys.argv[3]) if len(sys.argv) >= 4 else 120
    bring_to_front()
    time.sleep(0.05)
    sx, sy = cx + vx, cy + vy
    dm.MoveTo(sx, sy)
    time.sleep(0.08)
    try:
        dm.LeftDown()
        time.sleep(max(0, hold_ms) / 1000)
        dm.LeftUp()
    except Exception:
        dm.LeftClick()
    print(f"DM_CLICK: viewport({vx},{vy}) screen({sx},{sy}) hold_ms={hold_ms}")
