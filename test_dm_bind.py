"""大漠 BindWindow 独立测试脚本。每次绑定在独立子进程中隔离崩溃。"""
import subprocess, sys, time, json, os
from pathlib import Path

TEST_CODE = r"""
import win32com.client, win32gui, json, sys, os, tempfile
from pathlib import Path

hwnd = int(sys.argv[1])
display = sys.argv[2]
mouse = sys.argv[3]
keypad = sys.argv[4]
mode = int(sys.argv[5])

result = {"hwnd": hwnd, "display": display, "mouse": mouse,
          "keypad": keypad, "mode": mode, "crashed": False}

try:
    title = win32gui.GetWindowText(hwnd)
    cls = win32gui.GetClassName(hwnd)
    rect = win32gui.GetWindowRect(hwnd)
    result["title"] = title
    result["class_name"] = cls
    result["width"] = rect[2] - rect[0]
    result["height"] = rect[3] - rect[1]

    dm = win32com.client.Dispatch("dm.dmsoft")
    result["dm_ver"] = dm.Ver()
    bind_ret = dm.BindWindow(hwnd, display, mouse, keypad, mode)
    result["bind_result"] = int(bind_ret) if bind_ret is not None else None

    if bind_ret == 1:
        w = result["width"]
        h = result["height"]
        tmp = os.path.join(tempfile.gettempdir(), f"dm_bind_test_{hwnd}.bmp")
        cap_ret = dm.Capture(0, 0, w, h, tmp)
        result["capture_result"] = int(cap_ret) if cap_ret is not None else None
        if os.path.exists(tmp):
            result["capture_size"] = os.path.getsize(tmp)
            os.remove(tmp)
        dm.MoveTo(rect[0] + 5, rect[1] + 5)
        dm.LeftClick()
        result["click_test"] = "ok"
        dm.UnBindWindow()
    else:
        result["bind_fail"] = f"ret={bind_ret}"
except Exception as e:
    result["exception"] = str(e)

print(json.dumps(result, ensure_ascii=False))
"""

BIND_MODES = [
    ("normal", "normal", "normal", 0),
    ("normal", "windows", "windows", 0),
    ("gdi", "normal", "normal", 0),
    ("gdi", "windows", "windows", 0),
    ("gdi2", "normal", "normal", 0),
    ("gdi2", "windows", "windows", 0),
    ("dx", "normal", "normal", 0),
    ("dx", "dx", "windows", 0),
    ("dx2", "normal", "normal", 0),
    ("dx2", "dx2", "windows", 0),
    ("dx3", "normal", "normal", 0),
    ("dx3", "dx2", "windows", 0),
]


def safe_print(s=""):
    try:
        sys.stdout.buffer.write((str(s) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception:
        pass


def find_target_windows():
    """找代表性测试窗口"""
    import win32gui
    targets = []

    # Notepad
    h = win32gui.FindWindow("Notepad", None)
    if not h:
        subprocess.Popen(["notepad.exe"], shell=True)
        time.sleep(1)
        h = win32gui.FindWindow("Notepad", None)
    if h:
        targets.append(("notepad", h))

    # 登录程序窗口 (只测一个)
    def cb1(hwnd, _):
        t = win32gui.GetWindowText(hwnd)
        if "H5-9-" in t:
            targets.append(("login_w9", hwnd))
    win32gui.EnumWindows(cb1, None)

    # Chrome/游戏窗口
    def cb2(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            c = win32gui.GetClassName(hwnd)
            if c == "Chrome_WidgetWin_1":
                t = win32gui.GetWindowText(hwnd)
                if "7tu7tu" in t or "7T" in t:
                    targets.append(("chrome_game", hwnd))
    win32gui.EnumWindows(cb2, None)

    # 普通Chrome
    def cb3(hwnd, _):
        if len(targets) < 10 and win32gui.IsWindowVisible(hwnd):
            if win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1":
                t = win32gui.GetWindowText(hwnd)
                if len(t) > 3 and not any(tag in t for tag in ["7tu7tu", "7T", "Visual Studio", "codex"]):
                    targets.append(("chrome_other", hwnd))
    win32gui.EnumWindows(cb3, None)

    return targets


def test_one(hwnd, display, mouse, keypad, mode):
    cmd = ["py", "-3.14-32", "-c", TEST_CODE,
           str(hwnd), display, mouse, keypad, str(mode)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                          encoding="utf-8", errors="replace")
        if r.returncode in (-11, 139, 3221225477):
            return {"crashed": True, "hwnd": hwnd, "mode": display}
        if r.returncode == 0:
            out = r.stdout.strip()
            if out:
                return json.loads(out)
        return {"crashed": False, "hwnd": hwnd, "mode": display,
                "rc": r.returncode, "stderr": r.stderr[:200]}
    except subprocess.TimeoutExpired:
        return {"timeout": True, "hwnd": hwnd, "mode": display}
    except Exception as e:
        return {"error": str(e), "hwnd": hwnd, "mode": display}


def enumerate_chrome_children():
    import win32gui
    parent = None
    def cb(h, _):
        nonlocal parent
        if not parent and win32gui.IsWindowVisible(h):
            if win32gui.GetClassName(h) == "Chrome_WidgetWin_1":
                t = win32gui.GetWindowText(h)
                if "7tu7tu" in t or "7T" in t:
                    parent = h
    win32gui.EnumWindows(cb, None)
    if not parent:
        return []
    children = []
    def ec(h, _):
        cls = win32gui.GetClassName(h)
        r = win32gui.GetWindowRect(h)
        children.append((h, cls, r[2]-r[0], r[3]-r[1]))
    win32gui.EnumChildWindows(parent, ec, None)
    return children


def main():
    safe_print("=" * 60)
    safe_print("Dm BindWindow Test")
    safe_print("=" * 60)

    targets = find_target_windows()
    safe_print(f"Test windows: {len(targets)}")
    for label, hwnd in targets:
        safe_print(f"  [{label}] hwnd={hwnd}")

    total = len(targets) * len(BIND_MODES)
    safe_print(f"Bind modes: {len(BIND_MODES)}")
    safe_print(f"Total tests: {total}")

    crashes = []
    successes = []
    fails = []
    n = 0

    for label, hwnd in targets:
        import win32gui
        cls = win32gui.GetClassName(hwnd)
        safe_print(f"\n--- [{label}] class={cls} ---")
        for display, mouse, keypad, mode in BIND_MODES:
            n += 1
            res = test_one(hwnd, display, mouse, keypad, mode)

            if res.get("crashed"):
                crashes.append((label, display, mouse, keypad, mode))
                status = "CRASH"
            elif res.get("bind_result") == 1:
                successes.append((label, display, mouse, keypad, mode,
                                  res.get("capture_result"), res.get("click_test")))
                status = f"OK cap={res.get('capture_result')} click={res.get('click_test')}"
            else:
                status = f"FAIL ret={res.get('bind_result')} exc={res.get('exception','')}"
                fails.append((label, display))

            safe_print(f"  [{n}/{total}] {display}/{mouse}/{keypad}/m{mode}: {status}")

    # Summary
    safe_print()
    safe_print("=" * 60)
    safe_print("SUMMARY")
    safe_print("=" * 60)
    safe_print(f"CRASH: {len(crashes)}/{total}")
    safe_print(f"OK:    {len(successes)}/{total}")
    safe_print(f"FAIL:  {len(fails)}/{total}")

    if successes:
        safe_print(f"\nWorking bindings ({len(successes)}):")
        for s in successes:
            safe_print(f"  [{s[0]}] {s[1]}/{s[2]}/{s[3]}/m{s[4]} cap={s[5]} click={s[6]}")

    if crashes:
        safe_print(f"\nCrash modes ({len(crashes)}):")
        for c in crashes:
            safe_print(f"  [{c[0]}] {c[1]}/{c[2]}/{c[3]}/m{c[4]}")

    # Chrome children
    safe_print()
    safe_print("=" * 60)
    safe_print("Chrome Game Child Windows")
    safe_print("=" * 60)
    children = enumerate_chrome_children()
    safe_print(f"Children: {len(children)}")
    for h, cls, w, h2 in sorted(children, key=lambda x: x[2]*x[3], reverse=True)[:15]:
        render = " <-- RENDER" if "Render" in cls else ""
        safe_print(f"  hwnd={h} class={cls} size={w}x{h2}{render}")

        # Test binding child windows too
        if "Render" in cls:
            safe_print(f"    Testing bind on Render child...")
            res = test_one(h, "normal", "normal", "normal", 0)
            if res.get("crashed"):
                safe_print(f"    -> CRASH")
            elif res.get("bind_result") == 1:
                safe_print(f"    -> OK cap={res.get('capture_result')}")
            else:
                safe_print(f"    -> FAIL")

    return 0


if __name__ == "__main__":
    sys.exit(main())
