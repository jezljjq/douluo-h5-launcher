from __future__ import annotations

import sys
import tkinter as tk
import ctypes
from pathlib import Path
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from douluo_launcher.path_utils import first_dropped_file_path, resolve_game_executable_path


def is_admin_process() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main() -> None:
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
    except Exception as exc:
        raise SystemExit(f"tkinterdnd2 不可用：{exc}") from exc

    root = TkinterDnD.Tk()
    root.title("拖拽 POC - 游戏路径")
    root.geometry("720x320")

    admin = is_admin_process()
    dropped_var = tk.StringVar(value="等待拖入 .lnk / .exe / 游戏目录")
    resolved_var = tk.StringVar(value="未识别")

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill=tk.BOTH, expand=True)
    frame.columnconfigure(0, weight=1)

    ttk.Label(
        frame,
        text=(
            "当前 POC 权限：管理员（普通桌面拖拽可能被 Windows 拦截）"
            if admin else
            "当前 POC 权限：普通用户（推荐用于拖拽测试）"
        ),
        foreground="#b45309" if admin else "#047857",
    ).grid(row=0, column=0, sticky="w", pady=(0, 8))

    drop_zone = tk.Label(
        frame,
        text="把桌面游戏图标 / 快捷方式 / X5Game.exe / 游戏目录拖到这里",
        relief=tk.RIDGE,
        borderwidth=2,
        height=6,
        bg="#f3f6fb",
        fg="#1f2937",
        font=("Microsoft YaHei UI", 12),
    )
    drop_zone.grid(row=1, column=0, sticky="nsew", pady=(0, 12))

    ttk.Label(frame, text="拖入路径：").grid(row=2, column=0, sticky="w")
    ttk.Entry(frame, textvariable=dropped_var).grid(row=3, column=0, sticky="ew", pady=(0, 8))
    ttk.Label(frame, text="解析结果：").grid(row=4, column=0, sticky="w")
    ttk.Entry(frame, textvariable=resolved_var).grid(row=5, column=0, sticky="ew")

    log = tk.Text(frame, height=5, wrap=tk.WORD)
    log.grid(row=6, column=0, sticky="nsew", pady=(12, 0))
    frame.rowconfigure(6, weight=1)

    def append(message: str) -> None:
        log.insert(tk.END, message + "\n")
        log.see(tk.END)
        print(message, flush=True)

    def handle_drop(event) -> str:
        raw = str(getattr(event, "data", "") or "")
        path = first_dropped_file_path(raw, splitlist=root.tk.splitlist)
        if not path:
            append(f"Drop received but no path parsed: {raw!r}")
            return getattr(event, "action", "copy")

        dropped_var.set(path)
        append(f"Drop raw: {raw!r}")
        append(f"First path: {path}")
        try:
            result = resolve_game_executable_path(path)
        except Exception as exc:
            resolved_var.set("识别失败")
            append(f"识别失败：{exc}")
            messagebox.showwarning("识别失败", str(exc))
            return getattr(event, "action", "copy")

        resolved_var.set(result.path)
        append(result.message or f"已识别：{result.path}")
        return getattr(event, "action", "copy")

    for widget in (drop_zone, frame, root):
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", handle_drop)

    append(
        "POC ready. "
        + ("当前是管理员权限；如果拖不进来，请用 tools\\run_drag_drop_poc.bat 从资源管理器双击启动普通权限 POC。"
           if admin else
           "当前是普通权限，请手动拖入 .lnk / .exe / 文件夹测试。")
    )
    root.mainloop()


if __name__ == "__main__":
    main()
