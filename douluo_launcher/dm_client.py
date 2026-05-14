from __future__ import annotations

import time
import struct
import winreg
import subprocess
import os
import re
from dataclasses import dataclass
from pathlib import Path


def ratio_to_client_point(ratio: tuple[float, float], width: int, height: int) -> tuple[int, int]:
    x = max(0, min(width - 1, int(width * ratio[0])))
    y = max(0, min(height - 1, int(height * ratio[1])))
    return x, y


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    width: int
    height: int
    class_name: str = ""
    pid: int = 0
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0


class DmClient:
    def __init__(self, settings, log) -> None:
        self.settings = settings
        self.log = log
        self.dm = None
        self.hwnd = 0
        self.client_width = 0
        self.client_height = 0

    def create(self) -> None:
        try:
            import win32com.client
        except Exception as exc:
            raise RuntimeError(f"pywin32 不可用，无法创建大漠对象: {exc}") from exc
        try:
            self.dm = win32com.client.Dispatch(self.settings.dm_prog_id)
        except Exception as exc:
            raise RuntimeError(f"创建大漠对象失败，请确认大漠插件已注册: {exc}") from exc
        try:
            version = self.dm.Ver()
        except Exception:
            version = "unknown"
        self.log(f"大漠对象创建成功，版本: {version}")

    def bind_browser_window(self, title_keyword: str = "") -> WindowInfo:
        if self.dm is None:
            self.create()
        window = find_browser_window(title_keyword)
        self.hwnd = window.hwnd
        self.client_width = window.width
        self.client_height = window.height
        self.log(f"找到浏览器窗口 hwnd={window.hwnd}, title={window.title}, client={window.width}x{window.height}")
        result = self.dm.BindWindow(
            self.hwnd,
            self.settings.dm_bind_display,
            self.settings.dm_bind_mouse,
            self.settings.dm_bind_keypad,
            self.settings.dm_bind_mode,
        )
        if int(result) != 1:
            raise RuntimeError(f"大漠绑定窗口失败，返回值: {result}")
        self.log("大漠绑定窗口成功，坐标基于该窗口客户区")
        return window

    def unbind(self) -> None:
        if self.dm is not None:
            try:
                self.dm.UnBindWindow()
            except Exception:
                pass

    def click_ratio(self, ratio: tuple[float, float], label: str) -> None:
        self._ensure_bound()
        x, y = ratio_to_client_point(ratio, self.client_width, self.client_height)
        self.log(f"大漠点击 {label}: client=({x}, {y})")
        self.dm.MoveTo(x, y)
        self.dm.LeftClick()

    def input_text(self, text: str) -> None:
        self._ensure_bound()
        result = self.dm.SendString(self.hwnd, text)
        if int(result) != 1:
            raise RuntimeError(f"大漠输入文本失败，返回值: {result}")

    def has_template(self, template_path: str) -> bool:
        if not template_path:
            raise RuntimeError("缺少模板图路径，无法校验真实状态")
        path = str(Path(template_path).resolve())
        if not Path(path).exists():
            raise RuntimeError(f"模板图不存在: {path}")
        self._ensure_bound()
        result = self.dm.FindPicE(
            0,
            0,
            self.client_width - 1,
            self.client_height - 1,
            path,
            self.settings.dm_findpic_delta_color,
            self.settings.dm_findpic_sim,
            0,
        )
        return self._findpic_success(result)

    def wait_until_template_gone(self, template_path: str, timeout_ms: int) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() <= deadline:
            if not self.has_template(template_path):
                return True
            time.sleep(0.25)
        return False

    def wait_until_template_present(self, template_path: str, timeout_ms: int) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() <= deadline:
            if self.has_template(template_path):
                return True
            time.sleep(0.25)
        return False

    def _ensure_bound(self) -> None:
        if self.dm is None or not self.hwnd:
            raise RuntimeError("大漠尚未绑定窗口")

    @staticmethod
    def _findpic_success(result) -> bool:
        if isinstance(result, tuple):
            return int(result[0]) >= 0
        if isinstance(result, str):
            first = result.split("|", 1)[0].split(",", 1)[0]
            return first.strip() not in ("", "-1")
        return int(result) >= 0


def find_browser_window(title_keyword: str = "") -> WindowInfo:
    try:
        import win32gui
    except Exception as exc:
        raise RuntimeError(f"win32gui 不可用，无法查找浏览器窗口: {exc}") from exc

    matches = list_browser_windows(title_keyword)
    if not matches:
        raise RuntimeError(f"未找到浏览器窗口，title_keyword={title_keyword!r}")
    return matches[-1]


def list_browser_windows(title_keyword: str = "") -> list[WindowInfo]:
    try:
        import win32gui
    except Exception as exc:
        raise RuntimeError(f"win32gui 不可用，无法查找浏览器窗口: {exc}") from exc

    matches: list[WindowInfo] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        class_name = win32gui.GetClassName(hwnd)
        if class_name != "Chrome_WidgetWin_1":
            return
        if title_keyword and title_keyword not in title:
            return
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        width = right - left
        height = bottom - top
        try:
            import win32process

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = 0
        if width > 100 and height > 100:
            matches.append(WindowInfo(hwnd=hwnd, title=title, width=width, height=height, class_name=class_name, pid=pid))

    win32gui.EnumWindows(callback, None)
    return matches


def list_visible_windows(title_keyword: str = "") -> list[WindowInfo]:
    try:
        import win32gui
    except Exception as exc:
        raise RuntimeError(f"win32gui 不可用，无法枚举窗口: {exc}") from exc

    current_pid = os.getpid()
    matches: list[WindowInfo] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        class_name = win32gui.GetClassName(hwnd)
        try:
            import win32process

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            pid = 0
        if pid == current_pid:
            return
        if title_keyword and title_keyword not in title:
            return
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top
        if width > 80 and height > 80:
            matches.append(
                WindowInfo(
                    hwnd=hwnd,
                    title=title,
                    width=width,
                    height=height,
                    class_name=class_name,
                    pid=pid,
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                )
            )

    win32gui.EnumWindows(callback, None)
    return matches


def select_login_window(title_keyword: str = "") -> tuple[WindowInfo | None, list[WindowInfo]]:
    candidates = list_visible_windows(title_keyword)
    if title_keyword:
        return (candidates[0] if candidates else None), candidates

    keywords = ("登录", "二维码", "通行证", "扫码", "斗罗")
    for window in candidates:
        if any(keyword in window.title for keyword in keywords):
            return window, candidates
    return None, candidates


def window_title_matches_game_no(title: str, game_window_no: int) -> bool:
    normalized = title.strip()
    if not normalized:
        return False
    number = str(game_window_no)
    strong_patterns = (
        f"H5-{number}-",
        f"斗罗大陆H5-{number}-",
    )
    if any(pattern in normalized for pattern in strong_patterns):
        return True
    if re.search(rf"H5-{re.escape(number)}(?!\d)", normalized):
        return True
    return False


def select_login_window_by_game_no(game_window_no: int) -> tuple[WindowInfo | None, list[WindowInfo]]:
    candidates = list_visible_windows("")
    for window in candidates:
        if window_title_matches_game_no(window.title, game_window_no):
            return window, candidates
    return None, candidates


def capture_window_image(window: WindowInfo):
    try:
        from PIL import ImageGrab
    except Exception as exc:
        raise RuntimeError(f"Pillow ImageGrab 不可用，无法截图窗口: {exc}") from exc
    if not window.left and not window.right:
        try:
            import win32gui

            left, top, right, bottom = win32gui.GetWindowRect(window.hwnd)
        except Exception as exc:
            raise RuntimeError(f"获取窗口位置失败: {exc}") from exc
    else:
        left, top, right, bottom = window.left, window.top, window.right, window.bottom
    return ImageGrab.grab(bbox=(left, top, right, bottom))


def capture_window_background(window: WindowInfo):
    """后台截图：BitBlt 从窗口 DC 直接获取内容，不依赖屏幕截图。

    对大多数非 DirectX 窗口，即使被遮挡也能正确截取。
    失败时回退到 ImageGrab 前台截图。
    """
    from PIL import Image

    try:
        import win32gui, win32ui, win32con
    except Exception as exc:
        raise RuntimeError(f"win32gui 不可用: {exc}") from exc

    hwnd = window.hwnd
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w = right - left
    h = bottom - top

    # BitBlt 从窗口 DC
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bitmap)
    save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)

    bmp_info = bitmap.GetInfo()
    bmp_bits = bitmap.GetBitmapBits(True)
    img = Image.frombuffer(
        "RGB", (bmp_info["bmWidth"], bmp_info["bmHeight"]),
        bmp_bits, "raw", "BGRX", 0, 1,
    )

    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    win32gui.DeleteObject(bitmap.GetHandle())

    # 检测是否全黑/空白（BitBlt 对 DirectX 窗口可能返回空内容）
    gray = img.convert("L")
    extrema = gray.getextrema()
    if extrema[1] < 30:
        # 全暗 → BitBlt 失败，回退 ImageGrab
        from PIL import ImageGrab

        img = ImageGrab.grab(bbox=(left, top, right, bottom))

    return img


def diagnose_dm_environment(prog_id: str = "dm.dmsoft") -> list[str]:
    messages: list[str] = []
    python_bits = struct.calcsize("P") * 8
    messages.append(f"Python 位数: {python_bits} 位")

    current_clsid = _read_prog_id_clsid(prog_id, 0)
    clsid_32 = _read_prog_id_clsid(prog_id, winreg.KEY_WOW64_32KEY)
    clsid_64 = _read_prog_id_clsid(prog_id, winreg.KEY_WOW64_64KEY)
    current_server = _read_clsid_server(current_clsid, 0) if current_clsid else None
    server_32 = _read_clsid_server(clsid_32, winreg.KEY_WOW64_32KEY) if clsid_32 else None
    server_64 = _read_clsid_server(clsid_64, winreg.KEY_WOW64_64KEY) if clsid_64 else None

    if current_clsid:
        messages.append(f"{prog_id} 当前 Python 可见注册 CLSID: {current_clsid}")
    else:
        messages.append(f"{prog_id} 当前 Python 位数下未注册")

    if clsid_32:
        messages.append(f"{prog_id} 32 位 ProgID 注册存在: {clsid_32}")
        messages.append(f"{prog_id} 32 位 InprocServer32: {server_32 or '不存在'}")
    else:
        messages.append(f"{prog_id} 32 位注册不存在")

    if clsid_64:
        messages.append(f"{prog_id} 64 位 ProgID 注册存在: {clsid_64}")
        messages.append(f"{prog_id} 64 位 InprocServer32: {server_64 or '不存在'}")
    else:
        messages.append(f"{prog_id} 64 位注册不存在")

    if current_clsid and current_server:
        messages.append("dm.dll 是否注册成功: 是，当前 Python 位数可见完整 COM 类注册")
    elif current_clsid and not current_server:
        messages.append("dm.dll 是否注册成功: 否，只有 ProgID/CLSID，没有当前位数 InprocServer32")
    elif clsid_32 or clsid_64:
        messages.append("dm.dll 是否注册成功: 否，当前 Python 位数不可见完整 COM 类注册")
    else:
        messages.append("dm.dll 是否注册成功: 否")

    try:
        import win32com.client

        dm = win32com.client.Dispatch(prog_id)
        try:
            version = dm.Ver()
        except Exception:
            version = "unknown"
        messages.append(f"是否成功创建 dm.dmsoft: 是，版本: {version}")
        messages.append("大漠环境可用")
        return messages
    except Exception as exc:
        messages.append(f"是否成功创建 dm.dmsoft: 否，错误: {exc}")

    if current_clsid and not current_server:
        messages.append("判断: 注册损坏或未用当前 Python 位数对应的 regsvr32 正确注册 dm.dll。")
        messages.append("修复: 用管理员权限运行对应位数的 regsvr32 dm.dll；64 位 Python 用 C:\\Windows\\System32\\regsvr32.exe，32 位 Python 用 C:\\Windows\\SysWOW64\\regsvr32.exe。")
    elif python_bits == 64 and server_32 and not server_64:
        messages.append("判断: 大概率是位数不匹配。当前是 64 位 Python，但只注册了 32 位大漠。")
        messages.append("修复: 使用 32 位 Python 运行程序，或注册 64 位大漠插件。")
    elif python_bits == 32 and server_64 and not server_32:
        messages.append("判断: 大概率是位数不匹配。当前是 32 位 Python，但只注册了 64 位大漠。")
        messages.append("修复: 使用 64 位 Python 运行程序，或注册 32 位大漠插件。")
    elif not server_32 and not server_64 and not current_server:
        messages.append("判断: dm.dll 未注册，或 ProgID 不是 dm.dmsoft。")
        messages.append("修复: 用管理员权限注册大漠插件，例如 regsvr32 dm.dll。")
    else:
        messages.append("判断: 已看到注册信息，但 COM 创建失败，可能是注册损坏、依赖缺失或权限问题。")
        messages.append("修复: 先用管理员权限重新 regsvr32 dm.dll；若仍失败，确认 dm.dll 位数与 Python 位数一致。")
    return messages


def diagnose_dm_environment_with_32bit_python(prog_id: str = "dm.dmsoft") -> list[str]:
    project_root = str(Path(__file__).resolve().parents[1])
    command = [
        "py",
        "-3.14-32",
        "-c",
        (
            f"import sys; sys.path.insert(0, {project_root!r}); "
            "from douluo_launcher.dm_client import diagnose_dm_environment; "
            f"print('\\n'.join(diagnose_dm_environment({prog_id!r})))"
        ),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        return [
            "未找到 py 启动器，无法调用 32 位 Python。",
            "修复: 安装 Python Launcher (py.exe)，或确认 32 位 Python 已安装并能通过 py -3.14-32 调用。",
        ]
    except subprocess.TimeoutExpired:
        return ["32 位 Python 大漠诊断超时。"]

    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    lines = ["方案A：使用 32 位 Python 诊断大漠环境", "命令: py -3.14-32"]
    if output:
        lines.extend(output.splitlines())
    if error:
        lines.append("stderr:")
        lines.extend(error.splitlines())
    if result.returncode != 0:
        lines.append(f"32 位 Python 诊断命令失败，退出码: {result.returncode}")
    return lines


def _read_prog_id_clsid(prog_id: str, access_flag: int) -> str | None:
    try:
        with winreg.OpenKeyEx(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\CLSID", 0, winreg.KEY_READ | access_flag) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return str(value)
    except OSError:
        return None


def _read_clsid_server(clsid: str | None, access_flag: int) -> str | None:
    if not clsid:
        return None
    try:
        with winreg.OpenKeyEx(
            winreg.HKEY_CLASSES_ROOT,
            rf"CLSID\{clsid}\InprocServer32",
            0,
            winreg.KEY_READ | access_flag,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return str(value)
    except OSError:
        return None
