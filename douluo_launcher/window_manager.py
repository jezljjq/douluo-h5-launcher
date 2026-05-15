from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


GAME_TITLE_KEYWORD = "斗罗大陆H5"

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
WM_CLOSE = 0x0010
SMTO_ABORTIFHUNG = 0x0002

user32 = ctypes.WinDLL("user32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.SetWindowTextW.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    ctypes.c_uint,
    wintypes.WPARAM,
    wintypes.LPARAM,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.POINTER(wintypes.DWORD),
]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    title: str
    number: Optional[int]


@dataclass(frozen=True)
class TileConfig:
    width: int = 320
    height: int = 540
    start_x: int = 250
    start_y: int = 0
    offset_x: int = 320
    offset_y: int = 525
    per_row: int = 8


@dataclass(frozen=True)
class TileResult:
    window: GameWindow
    x: int
    y: int
    success: bool
    error: str = ""


@dataclass(frozen=True)
class CloseResult:
    window: GameWindow
    success: bool
    error: str = ""


@dataclass(frozen=True)
class RenameResult:
    window: GameWindow
    new_title: str
    success: bool
    error: str = ""


@dataclass(frozen=True)
class LaunchResult:
    game_path: str
    success: bool
    shell_result: int
    error: str = ""


def _get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    copied = user32.GetWindowTextW(hwnd, buffer, length + 1)
    if copied <= 0:
        return ""
    return buffer.value


def extract_window_number(title: str) -> Optional[int]:
    match = re.search(r"斗罗大陆H5\s*[-_ ]*\s*(\d+)\s*号", title)
    if match:
        return int(match.group(1))

    searchable_title = title.replace("斗罗大陆H5", "", 1)
    fallback = re.search(r"(\d+)", searchable_title)
    if fallback:
        return int(fallback.group(1))

    return None


def sort_game_windows(windows: List[GameWindow]) -> List[GameWindow]:
    return sorted(
        windows,
        key=lambda item: (
            item.number is None,
            item.number if item.number is not None else 0,
            item.title,
            item.hwnd,
        ),
    )


def calculate_tile_position(index: int, config: TileConfig) -> tuple[int, int]:
    row = index // config.per_row
    col = index % config.per_row
    x = config.start_x + col * config.offset_x
    y = config.start_y + row * config.offset_y
    return x, y


def launch_game_process(game_path: str) -> LaunchResult:
    cleaned_path = game_path.strip().strip('"')
    path = Path(cleaned_path)
    working_dir = str(path.parent) if path.parent else None

    try:
        result = int(
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "open",
                str(path),
                None,
                working_dir,
                1,
            )
        )
    except Exception as exc:
        return LaunchResult(game_path=cleaned_path, success=False, shell_result=0, error=str(exc))

    if result > 32:
        return LaunchResult(game_path=cleaned_path, success=True, shell_result=result)

    return LaunchResult(
        game_path=cleaned_path,
        success=False,
        shell_result=result,
        error=f"ShellExecuteW 返回码 {result}",
    )


def list_game_windows(
    title_keyword: str = GAME_TITLE_KEYWORD,
    exclude_hwnds: Optional[Iterable[int]] = None,
) -> List[GameWindow]:
    windows: List[GameWindow] = []
    excluded = {int(hwnd) for hwnd in exclude_hwnds or []}

    @EnumWindowsProc
    def callback(hwnd: int, _lparam: int) -> bool:
        if int(hwnd) in excluded:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True

        title = _get_window_title(hwnd)
        if title_keyword in title:
            windows.append(
                GameWindow(
                    hwnd=int(hwnd),
                    title=title,
                    number=extract_window_number(title),
                )
            )
        return True

    if not user32.EnumWindows(callback, 0):
        error_code = ctypes.get_last_error()
        raise ctypes.WinError(error_code)

    return sort_game_windows(windows)


def tile_game_windows(
    config: TileConfig,
    exclude_hwnds: Optional[Iterable[int]] = None,
    retries: int = 3,
    retry_delay: float = 0.5,
) -> List[TileResult]:
    if config.per_row <= 0:
        raise ValueError("每行数量必须大于 0")
    if config.width <= 0 or config.height <= 0:
        raise ValueError("窗口宽度和高度必须大于 0")

    results: List[TileResult] = []
    for index, window in enumerate(list_game_windows(exclude_hwnds=exclude_hwnds)):
        x, y = calculate_tile_position(index, config)

        ok = False
        error_code = 0
        for attempt in range(retries + 1):
            ok = bool(
                user32.SetWindowPos(
                    wintypes.HWND(window.hwnd),
                    None,
                    x,
                    y,
                    config.width,
                    config.height,
                    SWP_NOZORDER | SWP_NOACTIVATE,
                )
            )
            if ok:
                break
            error_code = ctypes.get_last_error()
            if attempt < retries:
                time.sleep(retry_delay)

        if ok:
            results.append(TileResult(window=window, x=x, y=y, success=True))
        else:
            results.append(
                TileResult(
                    window=window,
                    x=x,
                    y=y,
                    success=False,
                    error=f"SetWindowPos 失败，错误码 {error_code}",
                )
            )

    return results


def rename_game_windows(
    title_template: str,
    exclude_hwnds: Optional[Iterable[int]] = None,
) -> List[RenameResult]:
    if not title_template.strip():
        raise ValueError("标题模板不能为空")

    results: List[RenameResult] = []
    for index, window in enumerate(list_game_windows(exclude_hwnds=exclude_hwnds), start=1):
        new_title = title_template.format(
            index=index,
            number=window.number if window.number is not None else index,
            old_title=window.title,
            hwnd=window.hwnd,
        )
        ok = bool(user32.SetWindowTextW(wintypes.HWND(window.hwnd), new_title))
        if ok:
            results.append(RenameResult(window=window, new_title=new_title, success=True))
        else:
            error_code = ctypes.get_last_error()
            results.append(
                RenameResult(
                    window=window,
                    new_title=new_title,
                    success=False,
                    error=f"SetWindowTextW 失败，错误码 {error_code}",
                )
            )

    return results


def close_game_windows(
    timeout_ms: int = 1500,
    exclude_hwnds: Optional[Iterable[int]] = None,
) -> List[CloseResult]:
    results: List[CloseResult] = []
    for window in list_game_windows(exclude_hwnds=exclude_hwnds):
        result = wintypes.DWORD()
        send_result = user32.SendMessageTimeoutW(
            wintypes.HWND(window.hwnd),
            WM_CLOSE,
            0,
            0,
            SMTO_ABORTIFHUNG,
            timeout_ms,
            ctypes.byref(result),
        )
        if send_result:
            results.append(CloseResult(window=window, success=True))
        else:
            error_code = ctypes.get_last_error()
            results.append(
                CloseResult(
                    window=window,
                    success=False,
                    error=f"窗口无响应或关闭消息发送失败，错误码 {error_code}",
                )
            )
    return results
