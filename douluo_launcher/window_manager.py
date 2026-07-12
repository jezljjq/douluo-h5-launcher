from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
import shutil
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional


GAME_TITLE_KEYWORD = "斗罗大陆H5"
DEFAULT_TITLE_TEMPLATE = f"{GAME_TITLE_KEYWORD}-{{index}}号"
EXCLUDED_GAME_WINDOW_TITLE_KEYWORDS = (
    "全自动辅助",
    "辅助",
    "任务开关",
    "公共设置",
    "日常设置",
    "代理设置",
    "上号器",
    "工具",
)

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOSIZE = 0x0001
WM_CLOSE = 0x0010
SMTO_ABORTIFHUNG = 0x0002
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SPI_GETWORKAREA = 0x0030
DWMWA_CLOAKED = 14
DEFAULT_DPI = 96
SLOT_FILE_VERSION = 1
WINDOW_DETECTION_LOG_PATH = Path("logs") / "window_detection_detail.log"

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SystemParametersInfoW.argtypes = [
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.c_uint,
]
user32.SystemParametersInfoW.restype = wintypes.BOOL
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
dwmapi.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND,
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.c_uint,
]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = wintypes.BOOL


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    title: str
    number: Optional[int]
    rect: WindowRect = WindowRect(0, 0, 0, 0)


@dataclass(frozen=True)
class WindowDetectResult:
    hwnd: int
    title: str
    slot_no: Optional[int]
    accepted: bool
    reason: str
    class_name: str = ""
    pid: Optional[int] = None
    process_path: str = ""
    rect: WindowRect = WindowRect(0, 0, 0, 0)
    title_numbered: bool = False
    helper_keyword: str = ""
    process_path_match: bool = False
    size_match: bool = False


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
class RowTileConfig:
    width: Optional[int] = None
    height: Optional[int] = None
    start_x: int = 0
    start_y: int = 0
    per_row: int = 5
    prevent_overflow: bool = True
    gap_x: int = 0
    gap_y: int = 0


@dataclass(frozen=True)
class RowTilePlan:
    screen_width: int
    screen_height: int
    work_area: WindowRect
    work_area_width: int
    work_area_height: int
    window_count: int
    cols: int
    rows: int
    target_width: int
    target_height: int
    raw_target_width: float
    raw_target_height: float
    gap_x: int
    gap_y: int
    width_gap_total: int
    height_gap_total: int
    padding: int
    safe_margin: int
    usable_width: int
    usable_height: int


@dataclass(frozen=True)
class TileResult:
    window: GameWindow
    x: int
    y: int
    success: bool
    error: str = ""
    width: int = 0
    height: int = 0
    wrapped_by_screen: bool = False


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


@dataclass(frozen=True)
class WindowSlot:
    slot_no: int
    x: int
    y: int
    width: int
    height: int
    title: str = ""
    hwnd: Optional[int] = None
    account_layer: str = ""
    account_index: Optional[int] = None
    status: str = ""


@dataclass(frozen=True)
class SlotEnvironment:
    screen_width: int
    screen_height: int
    dpi: int
    scale: float
    profile: str


@dataclass(frozen=True)
class SlotLayoutParams:
    mode: str = "fixed"
    target_window_count: Optional[int] = None
    window_width: Optional[int] = None
    window_height: Optional[int] = None
    per_row: Optional[int] = None
    start_x: Optional[int] = None
    start_y: Optional[int] = None
    offset_x: Optional[int] = None
    offset_y: Optional[int] = None
    title_template: str = ""
    profile_name: str = ""


@dataclass(frozen=True)
class SlotCompatibilityResult:
    compatible: bool
    warnings: List[str]
    current_environment: SlotEnvironment
    slot_environment: Optional[SlotEnvironment] = None
    current_layout_params: Optional[SlotLayoutParams] = None
    slot_layout_params: Optional[SlotLayoutParams] = None


@dataclass(frozen=True)
class SlotRestoreResult:
    slot: WindowSlot
    window: Optional[GameWindow]
    success: bool
    x: int
    y: int
    width: int
    height: int
    new_title: str = ""
    moved: bool = False
    renamed: bool = False
    error: str = ""


@dataclass(frozen=True)
class RepairSlotResult:
    slot: WindowSlot
    success: bool
    old_hwnd: Optional[int] = None
    new_hwnd: Optional[int] = None
    new_title: str = ""
    error: str = ""
    requires_close_confirmation: bool = False
    slot_source: str = ""


def _get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    copied = user32.GetWindowTextW(hwnd, buffer, length + 1)
    if copied <= 0:
        return ""
    return buffer.value


def get_window_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    copied = user32.GetClassNameW(wintypes.HWND(hwnd), buffer, len(buffer))
    if copied <= 0:
        return ""
    return buffer.value


def get_window_rect(hwnd: int) -> WindowRect:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        error_code = ctypes.get_last_error()
        raise ctypes.WinError(error_code)
    return WindowRect(
        left=int(rect.left),
        top=int(rect.top),
        right=int(rect.right),
        bottom=int(rect.bottom),
    )


def get_screen_work_area() -> WindowRect:
    rect = wintypes.RECT()
    ok = bool(user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0))
    if not ok:
        error_code = ctypes.get_last_error()
        raise ctypes.WinError(error_code)
    return WindowRect(
        left=int(rect.left),
        top=int(rect.top),
        right=int(rect.right),
        bottom=int(rect.bottom),
    )


def get_full_screen_size() -> tuple[int, int]:
    return (
        int(user32.GetSystemMetrics(SM_CXSCREEN)),
        int(user32.GetSystemMetrics(SM_CYSCREEN)),
    )


def get_system_dpi() -> int:
    try:
        get_dpi = user32.GetDpiForSystem
        get_dpi.restype = ctypes.c_uint
        dpi = int(get_dpi())
        if dpi > 0:
            return dpi
    except Exception:
        pass
    return DEFAULT_DPI


def is_current_process_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def _format_windows_error(error_code: int) -> str:
    try:
        return ctypes.FormatError(int(error_code)).strip()
    except Exception:
        return ""


def _format_set_window_pos_failure(
    window: GameWindow,
    x: int,
    y: int,
    width: int,
    height: int,
    error_code: int,
) -> str:
    try:
        pid = get_window_process_id(window.hwnd)
    except Exception:
        pid = None
    try:
        process_path = get_window_process_path(window.hwnd)
    except Exception:
        process_path = ""
    rect = window.rect
    error_text = _format_windows_error(error_code)
    access_text = ""
    if int(error_code) == 5:
        access_text = (
            "窗口移动失败：Windows 拒绝访问。"
            "可能原因：目标窗口由其它辅助软件以更高权限启动，或上号器权限不足。"
            "请用相同权限启动上号器和辅助软件，或改用上号器批量启动窗口。"
        )
    else:
        access_text = "窗口移动失败。"
    return (
        f"{access_text} "
        f"SetWindowPos 失败，错误码 {int(error_code)}"
        f"{f'({error_text})' if error_text else ''}；"
        f"hwnd={window.hwnd}；title={window.title}；pid={pid if pid is not None else '未知'}；"
        f"process_path={process_path or '未知'}；上号器管理员={is_current_process_admin()}；"
        "目标进程管理员=未知；"
        f"当前rect=({rect.left},{rect.top},{rect.right},{rect.bottom})；"
        f"目标x={x} y={y} w={width} h={height}"
    )


def _set_window_pos_with_retries(
    window: GameWindow,
    x: int,
    y: int,
    width: int,
    height: int,
    flags: int,
    retries: int,
    retry_delay: float,
) -> tuple[bool, str]:
    error_code = 0
    for attempt in range(retries + 1):
        ctypes.set_last_error(0)
        ok = bool(
            user32.SetWindowPos(
                wintypes.HWND(window.hwnd),
                None,
                x,
                y,
                width,
                height,
                flags,
            )
        )
        if ok:
            return True, ""
        error_code = ctypes.get_last_error()
        if attempt < retries:
            time.sleep(retry_delay)
    return False, _format_set_window_pos_failure(window, x, y, width, height, error_code)


def make_slot_environment(screen_width: int, screen_height: int, dpi: int) -> SlotEnvironment:
    safe_dpi = int(dpi) if int(dpi) > 0 else DEFAULT_DPI
    scale = round(safe_dpi / DEFAULT_DPI, 4)
    percent = int(round(scale * 100))
    return SlotEnvironment(
        screen_width=int(screen_width),
        screen_height=int(screen_height),
        dpi=safe_dpi,
        scale=scale,
        profile=f"{int(screen_width)}x{int(screen_height)}_{percent}",
    )


def get_current_slot_environment() -> SlotEnvironment:
    screen_width, screen_height = get_full_screen_size()
    return make_slot_environment(screen_width, screen_height, get_system_dpi())


def layout_params_from_tile_config(
    config: TileConfig | RowTileConfig,
    title_template: Optional[str] = None,
    mode: str = "fixed",
    target_window_count: Optional[int] = None,
    profile_name: str = "",
) -> SlotLayoutParams:
    return SlotLayoutParams(
        mode=mode,
        target_window_count=int(target_window_count) if target_window_count is not None else None,
        window_width=config.width if isinstance(config.width, int) else None,
        window_height=config.height if isinstance(config.height, int) else None,
        per_row=int(config.per_row),
        start_x=int(config.start_x),
        start_y=int(config.start_y),
        offset_x=int(config.offset_x) if isinstance(config, TileConfig) else None,
        offset_y=int(config.offset_y) if isinstance(config, TileConfig) else None,
        title_template=str(title_template or ""),
        profile_name=str(profile_name or ""),
    )


def _environment_payload(environment: SlotEnvironment) -> dict[str, object]:
    return {
        "screen_width": environment.screen_width,
        "screen_height": environment.screen_height,
        "dpi": environment.dpi,
        "scale": environment.scale,
        "profile": environment.profile,
    }


def _layout_params_payload(layout_params: SlotLayoutParams) -> dict[str, object]:
    return {
        "mode": layout_params.mode,
        "target_window_count": layout_params.target_window_count,
        "window_width": layout_params.window_width,
        "window_height": layout_params.window_height,
        "per_row": layout_params.per_row,
        "start_x": layout_params.start_x,
        "start_y": layout_params.start_y,
        "offset_x": layout_params.offset_x,
        "offset_y": layout_params.offset_y,
        "title_template": layout_params.title_template,
        "profile_name": layout_params.profile_name,
    }


def _environment_from_mapping(data: object) -> Optional[SlotEnvironment]:
    if not isinstance(data, dict):
        return None
    try:
        screen_width = int(data.get("screen_width") or 0)
        screen_height = int(data.get("screen_height") or 0)
        dpi = int(data.get("dpi") or DEFAULT_DPI)
        profile = str(data.get("profile") or "")
        if screen_width <= 0 or screen_height <= 0:
            return None
        environment = make_slot_environment(screen_width, screen_height, dpi)
        if profile:
            return SlotEnvironment(
                screen_width=environment.screen_width,
                screen_height=environment.screen_height,
                dpi=environment.dpi,
                scale=environment.scale,
                profile=profile,
            )
        return environment
    except Exception:
        return None


def _optional_int(value: object) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _layout_params_from_mapping(data: object) -> Optional[SlotLayoutParams]:
    if not isinstance(data, dict):
        return None
    return SlotLayoutParams(
        mode=str(data.get("mode") or "fixed"),
        target_window_count=_optional_int(data.get("target_window_count")),
        window_width=_optional_int(data.get("window_width")),
        window_height=_optional_int(data.get("window_height")),
        per_row=_optional_int(data.get("per_row")),
        start_x=_optional_int(data.get("start_x")),
        start_y=_optional_int(data.get("start_y")),
        offset_x=_optional_int(data.get("offset_x")),
        offset_y=_optional_int(data.get("offset_y")),
        title_template=str(data.get("title_template") or ""),
        profile_name=str(data.get("profile_name") or ""),
    )


def _safe_profile_part(value: object, fallback: str = "unknown") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"[^0-9A-Za-z_-]+", "_", text)
    return text.strip("_")[:80] or fallback


def slot_profile_name(
    layout_params: SlotLayoutParams,
    environment: Optional[SlotEnvironment] = None,
) -> str:
    env = environment or get_current_slot_environment()
    count = layout_params.target_window_count if layout_params.target_window_count is not None else "unknown"
    mode = _safe_profile_part(layout_params.mode)
    readable = f"{env.profile}_{count}_{mode}"
    digest_payload = {
        "environment": _environment_payload(env),
        "layout_params": _layout_params_payload(layout_params),
    }
    digest = hashlib.sha1(
        json.dumps(digest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:8]
    return f"{_safe_profile_part(readable)}_{digest}"


def window_slots_profile_path(
    root_dir: str | Path,
    layout_params: SlotLayoutParams,
    environment: Optional[SlotEnvironment] = None,
) -> Path:
    return Path(root_dir) / "slots" / f"{slot_profile_name(layout_params, environment=environment)}.json"


def _is_window_cloaked(hwnd: int) -> bool:
    cloaked = ctypes.c_int(0)
    result = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        DWMWA_CLOAKED,
        ctypes.byref(cloaked),
        ctypes.sizeof(cloaked),
    )
    if result != 0:
        return False
    return bool(cloaked.value)


def _normalize_exe_path_for_compare(path: str | Path | None) -> str:
    text = str(path or "").strip().strip('"')
    if not text:
        return ""
    try:
        normalized = str(Path(text).expanduser().resolve(strict=False))
    except Exception:
        normalized = os.path.abspath(os.path.expandvars(os.path.expanduser(text)))
    return os.path.normcase(os.path.normpath(normalized))


def get_window_process_id(hwnd: int) -> int:
    process_id = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(process_id))
    return int(process_id.value or 0)


def get_window_process_path(hwnd: int) -> str:
    process_id = get_window_process_id(hwnd)
    if not process_id:
        return ""
    return get_process_path_by_pid(process_id)


def get_process_path_by_pid(process_id: int) -> str:
    if int(process_id or 0) <= 0:
        return ""

    process_handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        int(process_id),
    )
    if not process_handle:
        return ""

    try:
        buffer_size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(buffer_size.value)
        if not kernel32.QueryFullProcessImageNameW(
            process_handle,
            0,
            buffer,
            ctypes.byref(buffer_size),
        ):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(process_handle)


def build_title_template_pattern(title_template: str | None) -> re.Pattern[str]:
    """Build a numbered-window pattern from a title template containing {index} or {number}."""
    template = str(title_template or DEFAULT_TITLE_TEMPLATE).strip()
    placeholder = "{index}"
    position = template.find(placeholder)
    if position < 0:
        placeholder = "{number}"
        position = template.find(placeholder)
    if position < 0:
        return re.compile(r"a^")

    before = template[:position]
    after = template[position + len(placeholder):]
    pattern = f"^{re.escape(before)}(?P<index>\\d+){re.escape(after)}(?:-.+)?$"
    return re.compile(pattern)


def _title_template_literal_prefix(title_template: str | None) -> str:
    template = str(title_template or DEFAULT_TITLE_TEMPLATE).strip()
    positions = [pos for pos in (template.find("{index}"), template.find("{number}")) if pos >= 0]
    if not positions:
        return template
    return template[: min(positions)]


def _unnumbered_title_from_template(title_template: str | None) -> str:
    prefix = _title_template_literal_prefix(title_template).rstrip("-_ #：:号")
    return prefix or GAME_TITLE_KEYWORD


def extract_window_number(title: str, title_template: str | None = None) -> Optional[int]:
    match = build_title_template_pattern(title_template).fullmatch(str(title or "").strip())
    if match:
        return int(match.group("index"))

    return None


def _window_size_matches(
    rect: WindowRect | None,
    expected_window_size: tuple[int, int] | None,
) -> bool:
    if rect is None or expected_window_size is None:
        return False
    expected_width, expected_height = expected_window_size
    if expected_width <= 0 or expected_height <= 0:
        return False
    width_tolerance = max(90, int(expected_width * 0.45))
    height_tolerance = max(120, int(expected_height * 0.45))
    return (
        abs(rect.width - expected_width) <= width_tolerance
        and abs(rect.height - expected_height) <= height_tolerance
    )


def _is_detection_candidate_title(title: str, title_template: str | None = None) -> bool:
    clean_title = str(title or "").strip()
    if not clean_title:
        return False
    if any(keyword in clean_title for keyword in EXCLUDED_GAME_WINDOW_TITLE_KEYWORDS):
        return True
    if extract_window_number(clean_title, title_template=title_template) is not None:
        return True
    prefix = _title_template_literal_prefix(title_template).strip()
    return bool((prefix and prefix in clean_title) or "上号器" in clean_title or GAME_TITLE_KEYWORD in clean_title)


def _result_payload(result: WindowDetectResult) -> dict[str, object]:
    return {
        "hwnd": result.hwnd,
        "title": result.title,
        "class_name": result.class_name,
        "pid": result.pid,
        "process_path": result.process_path,
        "rect": [result.rect.left, result.rect.top, result.rect.right, result.rect.bottom],
        "width": result.rect.width,
        "height": result.rect.height,
        "title_numbered": result.title_numbered,
        "helper_keyword": result.helper_keyword,
        "process_path_match": result.process_path_match,
        "size_match": result.size_match,
        "accepted": result.accepted,
        "reason": result.reason,
        "slot_no": result.slot_no,
    }


def _write_window_detection_diagnostics(
    results: list[WindowDetectResult],
    configured_game_exe_path: str | Path | None,
    expected_window_size: tuple[int, int] | None,
    log_path: str | Path | None = WINDOW_DETECTION_LOG_PATH,
) -> None:
    if not results or log_path is None:
        return
    path = Path(log_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        accepted_count = sum(1 for result in results if result.accepted)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "event": "window_detection",
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "configured_game_exe_path": str(configured_game_exe_path or ""),
                        "expected_window_size": list(expected_window_size) if expected_window_size else None,
                        "candidate_count": len(results),
                        "accepted_count": accepted_count,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            for result in results:
                handle.write(json.dumps(_result_payload(result), ensure_ascii=False) + "\n")
    except Exception:
        return


def detect_game_window(
    hwnd: int,
    title: str,
    configured_game_exe_path: str | Path | None = None,
    title_template: str | None = None,
    allow_unnumbered: bool = False,
    rect: WindowRect | None = None,
    expected_window_size: tuple[int, int] | None = None,
    class_name: str = "",
    pid: Optional[int] = None,
    process_path_getter: Callable[[int], str] = get_window_process_path,
) -> WindowDetectResult:
    clean_title = str(title or "").strip()
    window_rect = rect or WindowRect(0, 0, 0, 0)
    slot_no = extract_window_number(clean_title, title_template=title_template)
    title_numbered = slot_no is not None
    size_match = _window_size_matches(window_rect, expected_window_size)
    process_path = ""
    process_path_match = False

    configured_path = _normalize_exe_path_for_compare(configured_game_exe_path)
    if configured_path:
        process_path = process_path_getter(int(hwnd))
        actual_path = _normalize_exe_path_for_compare(process_path)
        process_path_match = bool(actual_path and actual_path == configured_path)

    def result(accepted: bool, reason: str, helper_keyword: str = "") -> WindowDetectResult:
        return WindowDetectResult(
            hwnd=int(hwnd),
            title=clean_title,
            slot_no=slot_no,
            accepted=accepted,
            reason=reason,
            class_name=class_name,
            pid=pid,
            process_path=process_path,
            rect=window_rect,
            title_numbered=title_numbered,
            helper_keyword=helper_keyword,
            process_path_match=process_path_match,
            size_match=size_match,
        )

    if not clean_title:
        return result(False, "empty_title")

    for keyword in EXCLUDED_GAME_WINDOW_TITLE_KEYWORDS:
        if keyword in clean_title:
            return result(False, "helper_keyword", helper_keyword=keyword)

    if title_numbered:
        if process_path_match:
            return result(True, "process_match_numbered_title")
        if configured_path and expected_window_size is not None:
            if size_match:
                return result(True, "process_mismatch_but_title_size_ok")
            return result(False, "process_mismatch_size_mismatch")
        if "-" in clean_title:
            return result(True, "title_numbered_with_suffix")
        return result(True, "title_numbered")

    if allow_unnumbered and clean_title == _unnumbered_title_from_template(title_template):
        if process_path_match:
            return result(True, "process_match_unnumbered_exact")
        if configured_path and expected_window_size is not None:
            if size_match:
                return result(True, "unnumbered_exact_size_ok")
            return result(False, "unnumbered_exact_size_mismatch")
        return result(True, "unnumbered_exact")

    return result(False, "title_not_game_window")


def is_game_window(
    hwnd: int,
    title: str,
    configured_game_exe_path: str | Path | None = None,
    title_template: str | None = None,
    allow_unnumbered: bool = False,
    rect: WindowRect | None = None,
    expected_window_size: tuple[int, int] | None = None,
    process_path_getter: Callable[[int], str] = get_window_process_path,
) -> bool:
    return detect_game_window(
        hwnd,
        title,
        configured_game_exe_path=configured_game_exe_path,
        title_template=title_template,
        allow_unnumbered=allow_unnumbered,
        rect=rect,
        expected_window_size=expected_window_size,
        process_path_getter=process_path_getter,
    ).accepted


def sort_game_windows(windows: List[GameWindow]) -> List[GameWindow]:
    return sorted(
        windows,
        key=lambda item: (
            item.number is None,
            item.number if item.number is not None else 0,
            item.rect.top if item.number is None else 0,
            item.rect.left if item.number is None else 0,
            item.title,
            item.hwnd,
        ),
    )


def _slot_title(title_template: Optional[str], slot: WindowSlot) -> str:
    if title_template and title_template.strip():
        try:
            return title_template.format(
                index=slot.slot_no,
                number=slot.slot_no,
                slot_no=slot.slot_no,
                old_title=slot.title,
                hwnd=slot.hwnd or "",
            )
        except Exception:
            pass
    return slot.title or f"{GAME_TITLE_KEYWORD}-{slot.slot_no}号"


def _slot_from_mapping(slot_no: int, data: object) -> WindowSlot:
    if not isinstance(data, dict):
        raise ValueError(f"slot {slot_no} 内容不是对象")

    required = ("x", "y", "width", "height")
    missing = [field for field in required if field not in data]
    if missing:
        raise ValueError(f"slot {slot_no} 缺少字段：{', '.join(missing)}")

    return WindowSlot(
        slot_no=int(data.get("slot_no") or slot_no),
        x=int(data["x"]),
        y=int(data["y"]),
        width=int(data["width"]),
        height=int(data["height"]),
        title=str(data.get("title") or ""),
        hwnd=int(data["hwnd"]) if data.get("hwnd") not in (None, "") else None,
        account_layer=str(data.get("account_layer") or ""),
        account_index=int(data["account_index"]) if data.get("account_index") not in (None, "") else None,
        status=str(data.get("status") or ""),
    )


def _read_slot_file(slots_path: str | Path) -> dict[str, object]:
    path = Path(slots_path)
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("window_slots.json 根节点必须是对象")
    return data


def _slot_records(data: dict[str, object]) -> dict[str, object]:
    slots = data.get("slots")
    if isinstance(slots, dict):
        return slots
    return data


def _is_legacy_slot_file(data: dict[str, object]) -> bool:
    return "slots" not in data


def _slot_file_payload(
    slots: dict[str, object],
    environment: Optional[SlotEnvironment] = None,
    layout_params: Optional[SlotLayoutParams] = None,
) -> dict[str, object]:
    return {
        "version": SLOT_FILE_VERSION,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "environment": _environment_payload(environment or get_current_slot_environment()),
        "layout_params": _layout_params_payload(layout_params) if layout_params else None,
        "slots": slots,
    }


def _normalize_slot_file(
    data: dict[str, object],
    environment: Optional[SlotEnvironment] = None,
    layout_params: Optional[SlotLayoutParams] = None,
) -> dict[str, object]:
    if _is_legacy_slot_file(data):
        return _slot_file_payload(
            slots=dict(_slot_records(data)),
            environment=environment,
            layout_params=layout_params,
        )

    normalized = dict(data)
    normalized["version"] = int(normalized.get("version") or SLOT_FILE_VERSION)
    normalized["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if environment is not None or not isinstance(normalized.get("environment"), dict):
        normalized["environment"] = _environment_payload(environment or get_current_slot_environment())
    if layout_params is not None:
        normalized["layout_params"] = _layout_params_payload(layout_params)
    elif "layout_params" not in normalized:
        normalized["layout_params"] = None
    if not isinstance(normalized.get("slots"), dict):
        normalized["slots"] = {}
    return normalized


def load_window_slots(slots_path: str | Path = "window_slots.json") -> List[WindowSlot]:
    data = _read_slot_file(slots_path)
    if not data:
        return []

    slots: List[WindowSlot] = []
    for raw_key, value in _slot_records(data).items():
        try:
            slot_no = int(raw_key)
        except (TypeError, ValueError):
            continue
        slots.append(_slot_from_mapping(slot_no, value))
    return sorted(slots, key=lambda item: item.slot_no)


def load_window_slot_metadata(
    slots_path: str | Path = "window_slots.json",
) -> tuple[Optional[SlotEnvironment], Optional[SlotLayoutParams]]:
    data = _read_slot_file(slots_path)
    if not data or _is_legacy_slot_file(data):
        return None, None
    return (
        _environment_from_mapping(data.get("environment")),
        _layout_params_from_mapping(data.get("layout_params")),
    )


def _slot_payload(slot: WindowSlot) -> dict[str, object]:
    return {
        "slot_no": slot.slot_no,
        "title": slot.title,
        "hwnd": slot.hwnd,
        "x": slot.x,
        "y": slot.y,
        "width": slot.width,
        "height": slot.height,
        "account_layer": slot.account_layer,
        "account_index": slot.account_index,
        "status": slot.status,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _read_slot_payload(slots_path: str | Path) -> dict[str, object]:
    return _read_slot_file(slots_path)


def _backup_slot_file(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{path.stem}_{timestamp}.json"
    suffix = 1
    while backup_path.exists():
        backup_path = backup_dir / f"{path.stem}_{timestamp}_{suffix}.json"
        suffix += 1
    shutil.copy2(path, backup_path)
    return backup_path


def _write_slot_payload(slots_path: str | Path, data: dict[str, object]) -> None:
    path = Path(slots_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup_slot_file(path)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _upsert_window_slot(
    slots_path: str | Path,
    slot: WindowSlot,
    environment: Optional[SlotEnvironment] = None,
    layout_params: Optional[SlotLayoutParams] = None,
) -> None:
    data = _normalize_slot_file(
        _read_slot_payload(slots_path),
        environment=environment,
        layout_params=layout_params,
    )
    slots = _slot_records(data)
    previous = slots.get(str(slot.slot_no))
    payload = _slot_payload(slot)
    if isinstance(previous, dict):
        for key in ("account_layer", "account_index"):
            if not payload.get(key) and previous.get(key) not in (None, ""):
                payload[key] = previous.get(key)
    slots[str(slot.slot_no)] = payload
    _write_slot_payload(slots_path, data)


def has_valid_window_slots(slots_path: str | Path = "window_slots.json") -> bool:
    try:
        return bool(load_window_slots(slots_path))
    except Exception:
        return False


def _slot_from_file(path: Path, slot_no: int) -> Optional[WindowSlot]:
    try:
        for slot in load_window_slots(path):
            if slot.slot_no == slot_no:
                return slot
    except Exception:
        return None
    return None


def _recent_backup_slot_paths(slots_path: str | Path) -> List[Path]:
    path = Path(slots_path)
    backup_dir = path.parent / "backups"
    if not backup_dir.exists():
        return []
    backups = list(backup_dir.glob(f"{path.stem}_*.json"))
    return sorted(backups, key=lambda item: (item.stat().st_mtime, item.name), reverse=True)


def _legacy_slot_path(slots_path: str | Path) -> Path:
    path = Path(slots_path)
    return path.parent.parent / "window_slots.json"


def check_window_slots_compatibility(
    slots_path: str | Path = "window_slots.json",
    current_layout_params: Optional[SlotLayoutParams] = None,
    current_window_count: Optional[int] = None,
) -> SlotCompatibilityResult:
    current_environment = get_current_slot_environment()
    slot_environment, slot_layout_params = load_window_slot_metadata(slots_path)
    try:
        slot_count = len(load_window_slots(slots_path))
    except Exception:
        slot_count = 0
    warnings: List[str] = []

    if slot_environment is None:
        warnings.append("槽位文件缺少环境信息，无法确认屏幕/DPI/缩放是否一致")
    else:
        if slot_environment.screen_width != current_environment.screen_width:
            warnings.append(
                f"屏幕宽度变化：槽位={slot_environment.screen_width} 当前={current_environment.screen_width}"
            )
        if slot_environment.screen_height != current_environment.screen_height:
            warnings.append(
                f"屏幕高度变化：槽位={slot_environment.screen_height} 当前={current_environment.screen_height}"
            )
        if slot_environment.dpi != current_environment.dpi:
            warnings.append(f"DPI变化：槽位={slot_environment.dpi} 当前={current_environment.dpi}")
        if abs(slot_environment.scale - current_environment.scale) > 0.001:
            warnings.append(f"缩放比例变化：槽位={slot_environment.scale:g} 当前={current_environment.scale:g}")

    if current_layout_params is not None:
        if slot_layout_params is None:
            warnings.append("槽位文件缺少 layout_params，无法确认排列参数是否一致")
        else:
            checks = [
                ("mode", "排列方式"),
                ("target_window_count", "目标窗口数量"),
                ("window_width", "窗口宽度"),
                ("window_height", "窗口高度"),
                ("per_row", "每行数量"),
                ("start_x", "起点X"),
                ("start_y", "起点Y"),
                ("offset_x", "横向偏移"),
                ("offset_y", "纵向偏移"),
                ("title_template", "标题模板"),
            ]
            for attr, label in checks:
                current_value = getattr(current_layout_params, attr)
                slot_value = getattr(slot_layout_params, attr)
                if current_value != slot_value:
                    warnings.append(f"{label}变化：槽位={slot_value} 当前={current_value}")

        if current_layout_params.target_window_count is not None and slot_count:
            if int(current_layout_params.target_window_count) != slot_count:
                warnings.append(
                    f"槽位数量变化：槽位文件={slot_count} 当前目标={current_layout_params.target_window_count}"
                )

    if current_window_count is not None and slot_count:
        if int(current_window_count) != slot_count:
            warnings.append(f"当前窗口数量变化：槽位文件={slot_count} 当前识别={current_window_count}")

    if current_window_count is not None and current_layout_params is not None:
        target_count = current_layout_params.target_window_count
        if target_count is not None and int(current_window_count) != int(target_count):
            warnings.append(f"当前窗口数量与UI打开数量不一致：当前识别={current_window_count} UI目标={target_count}")

    return SlotCompatibilityResult(
        compatible=not warnings,
        warnings=warnings,
        current_environment=current_environment,
        slot_environment=slot_environment,
        current_layout_params=current_layout_params,
        slot_layout_params=slot_layout_params,
    )


def _window_matches_slot(
    slot: WindowSlot,
    windows_by_hwnd: dict[int, GameWindow],
    windows_by_title: dict[str, List[GameWindow]],
    windows_by_number: dict[int, List[GameWindow]],
    used_hwnds: set[int],
) -> Optional[GameWindow]:
    if slot.hwnd is not None:
        window = windows_by_hwnd.get(int(slot.hwnd))
        if window is not None and window.hwnd not in used_hwnds:
            return window

    if slot.title:
        for window in windows_by_title.get(slot.title, []):
            if window.hwnd not in used_hwnds:
                return window

    for window in windows_by_number.get(slot.slot_no, []):
        if window.hwnd not in used_hwnds:
            return window

    return None


def restore_windows_by_slots(
    slots_path: str | Path = "window_slots.json",
    title_template: Optional[str] = None,
    exclude_hwnds: Optional[Iterable[int]] = None,
    game_exe_path: str | Path | None = None,
    move_windows: bool = True,
    rename_windows: bool = True,
    retries: int = 3,
    retry_delay: float = 0.5,
) -> List[SlotRestoreResult]:
    try:
        slots = load_window_slots(slots_path)
    except Exception:
        slots = []
    if not slots:
        raise ValueError("未找到有效 window_slots.json 槽位映射")

    windows = list_game_windows(
        title_template=title_template,
        exclude_hwnds=exclude_hwnds,
        game_exe_path=game_exe_path,
    )
    windows_by_hwnd = {window.hwnd: window for window in windows}
    windows_by_title: dict[str, List[GameWindow]] = {}
    windows_by_number: dict[int, List[GameWindow]] = {}
    for window in windows:
        windows_by_title.setdefault(window.title, []).append(window)
        if window.number is not None:
            windows_by_number.setdefault(window.number, []).append(window)

    if move_windows and windows:
        probe = windows[0]
        move_ok, move_error = _set_window_pos_with_retries(
            probe,
            probe.rect.left,
            probe.rect.top,
            probe.rect.width,
            probe.rect.height,
            SWP_NOZORDER | SWP_NOACTIVATE,
            retries=0,
            retry_delay=0,
        )
        if not move_ok:
            first_slot = slots[0]
            return [
                SlotRestoreResult(
                    slot=first_slot,
                    window=probe,
                    success=False,
                    x=first_slot.x,
                    y=first_slot.y,
                    width=first_slot.width,
                    height=first_slot.height,
                    new_title=_slot_title(title_template, first_slot),
                    error=f"移动权限预检失败：{move_error}",
                )
            ]

    results: List[SlotRestoreResult] = []
    used_hwnds: set[int] = set()
    for slot in slots:
        window = _window_matches_slot(
            slot=slot,
            windows_by_hwnd=windows_by_hwnd,
            windows_by_title=windows_by_title,
            windows_by_number=windows_by_number,
            used_hwnds=used_hwnds,
        )
        if window is None:
            results.append(
                SlotRestoreResult(
                    slot=slot,
                    window=None,
                    success=False,
                    x=slot.x,
                    y=slot.y,
                    width=slot.width,
                    height=slot.height,
                    new_title=_slot_title(title_template, slot),
                    error=f"未找到 slot {slot.slot_no} 对应窗口",
                )
            )
            continue

        used_hwnds.add(window.hwnd)
        move_ok = True
        rename_ok = True
        errors: List[str] = []
        if move_windows:
            move_ok, move_error = _set_window_pos_with_retries(
                window,
                slot.x,
                slot.y,
                slot.width,
                slot.height,
                SWP_NOZORDER | SWP_NOACTIVATE,
                retries,
                retry_delay,
            )
            if not move_ok:
                errors.append(move_error)

        new_title = _slot_title(title_template, slot)
        if rename_windows and new_title:
            rename_ok = bool(user32.SetWindowTextW(wintypes.HWND(window.hwnd), new_title))
            if not rename_ok:
                error_code = ctypes.get_last_error()
                errors.append(f"SetWindowTextW 失败，错误码 {error_code}")

        results.append(
            SlotRestoreResult(
                slot=slot,
                window=window,
                success=move_ok and rename_ok,
                x=slot.x,
                y=slot.y,
                width=slot.width,
                height=slot.height,
                new_title=new_title,
                moved=move_windows and move_ok,
                renamed=rename_windows and rename_ok,
                error="；".join(errors),
            )
        )

    return results


def save_current_windows_as_slots(
    slots_path: str | Path = "window_slots.json",
    exclude_hwnds: Optional[Iterable[int]] = None,
    game_exe_path: str | Path | None = None,
    title_template: str | None = None,
    environment: Optional[SlotEnvironment] = None,
    layout_params: Optional[SlotLayoutParams] = None,
    expected_count: Optional[int] = None,
) -> List[WindowSlot]:
    windows = list_game_windows(
        title_template=title_template,
        exclude_hwnds=exclude_hwnds,
        game_exe_path=game_exe_path,
    )
    if expected_count is not None and len(windows) != int(expected_count):
        raise ValueError(
            f"当前窗口数量不完整：目标 {int(expected_count)}，当前 {len(windows)}。"
            "禁止保存槽位，避免用不完整窗口覆盖槽位。"
        )
    previous: dict[int, WindowSlot] = {}
    try:
        previous = {slot.slot_no: slot for slot in load_window_slots(slots_path)}
    except Exception:
        previous = {}

    slots: List[WindowSlot] = []
    payload: dict[str, dict[str, object]] = {}
    for index, window in enumerate(windows, start=1):
        slot_no = window.number if window.number is not None else index
        previous_slot = previous.get(slot_no)
        slot = WindowSlot(
            slot_no=slot_no,
            title=window.title,
            hwnd=window.hwnd,
            x=window.rect.left,
            y=window.rect.top,
            width=window.rect.width,
            height=window.rect.height,
            account_layer=previous_slot.account_layer if previous_slot else "",
            account_index=previous_slot.account_index if previous_slot else None,
            status="正常",
        )
        slots.append(slot)
        payload[str(slot_no)] = _slot_payload(slot)

    data = _slot_file_payload(
        payload,
        environment=environment,
        layout_params=layout_params,
    )
    _write_slot_payload(slots_path, data)
    return sorted(slots, key=lambda item: item.slot_no)


def refresh_window_slots_from_current_windows(
    slots_path: str | Path = "window_slots.json",
    exclude_hwnds: Optional[Iterable[int]] = None,
    game_exe_path: str | Path | None = None,
    title_template: str | None = None,
    environment: Optional[SlotEnvironment] = None,
    layout_params: Optional[SlotLayoutParams] = None,
    expected_count: Optional[int] = None,
) -> List[WindowSlot]:
    """Save numbered visible game windows as slots without moving or renaming them."""
    windows = list_game_windows(
        title_template=title_template,
        exclude_hwnds=exclude_hwnds,
        game_exe_path=game_exe_path,
    )
    if expected_count is not None and len(windows) != int(expected_count):
        raise ValueError(
            f"当前窗口数量不完整：目标 {int(expected_count)}，当前 {len(windows)}。"
            "禁止刷新槽位映射，避免用不完整窗口覆盖槽位。"
        )
    previous: dict[int, WindowSlot] = {}
    try:
        previous = {slot.slot_no: slot for slot in load_window_slots(slots_path)}
    except Exception:
        previous = {}

    data = _normalize_slot_file(
        _read_slot_payload(slots_path),
        environment=environment,
        layout_params=layout_params,
    )
    slot_records = _slot_records(data)
    refreshed: List[WindowSlot] = []
    for window in windows:
        if window.number is None:
            continue
        previous_slot = previous.get(window.number)
        slot = WindowSlot(
            slot_no=window.number,
            title=window.title,
            hwnd=window.hwnd,
            x=window.rect.left,
            y=window.rect.top,
            width=window.rect.width,
            height=window.rect.height,
            account_layer=previous_slot.account_layer if previous_slot else "",
            account_index=previous_slot.account_index if previous_slot else None,
            status="正常",
        )
        slot_records[str(slot.slot_no)] = _slot_payload(slot)
        refreshed.append(slot)

    if expected_count is not None and len(refreshed) != int(expected_count):
        raise ValueError(
            f"当前带编号窗口数量不完整：目标 {int(expected_count)}，当前 {len(refreshed)}。"
            "禁止刷新槽位映射，避免用不完整窗口覆盖槽位。"
        )
    _write_slot_payload(slots_path, data)
    return sorted(refreshed, key=lambda item: item.slot_no)


def calculate_slot_from_tile_config(
    slot_no: int,
    config: TileConfig,
    title_template: Optional[str] = None,
) -> WindowSlot:
    if slot_no <= 0:
        raise ValueError("目标槽位必须大于 0")
    if config.per_row <= 0:
        raise ValueError("每行数量必须大于 0")
    if config.width <= 0 or config.height <= 0:
        raise ValueError("窗口宽度和高度必须大于 0")

    index0 = slot_no - 1
    row = index0 // config.per_row
    col = index0 % config.per_row
    slot = WindowSlot(
        slot_no=slot_no,
        title=f"{GAME_TITLE_KEYWORD}-{slot_no}号",
        x=config.start_x + col * config.offset_x,
        y=config.start_y + row * config.offset_y,
        width=config.width,
        height=config.height,
        status="参数推导",
    )
    if title_template:
        return WindowSlot(
            slot_no=slot.slot_no,
            title=_slot_title(title_template, slot),
            x=slot.x,
            y=slot.y,
            width=slot.width,
            height=slot.height,
            status=slot.status,
        )
    return slot


def resolve_window_slot_for_repair(
    slot_no: int,
    slots_path: str | Path = "window_slots.json",
    title_template: Optional[str] = None,
    fixed_config: Optional[TileConfig] = None,
    exclude_hwnds: Optional[Iterable[int]] = None,
    game_exe_path: str | Path | None = None,
    environment: Optional[SlotEnvironment] = None,
    layout_params: Optional[SlotLayoutParams] = None,
) -> tuple[Optional[WindowSlot], str, str]:
    slot_no = int(slot_no)
    if slot_no <= 0:
        return None, "", "目标槽位必须大于 0"

    slots = load_window_slots(slots_path)
    slot_map = {slot.slot_no: slot for slot in slots}
    if slot_no in slot_map:
        return slot_map[slot_no], "slot_file", ""

    for backup_path in _recent_backup_slot_paths(slots_path):
        slot = _slot_from_file(backup_path, slot_no)
        if slot is not None:
            return slot, "slot_backup", ""

    legacy_path = _legacy_slot_path(slots_path)
    if legacy_path != Path(slots_path):
        slot = _slot_from_file(legacy_path, slot_no)
        if slot is not None:
            return slot, "legacy_slot_file", ""

    for window in list_game_windows(
        title_template=title_template,
        exclude_hwnds=exclude_hwnds,
        game_exe_path=game_exe_path,
    ):
        if window.number != slot_no:
            continue
        slot = WindowSlot(
            slot_no=slot_no,
            title=window.title,
            hwnd=window.hwnd,
            x=window.rect.left,
            y=window.rect.top,
            width=window.rect.width,
            height=window.rect.height,
            status="从当前窗口标题补齐",
        )
        return slot, "current_title", ""

    if fixed_config is not None:
        slot = calculate_slot_from_tile_config(slot_no, fixed_config, title_template=title_template)
        return slot, "fixed_config", ""

    return (
        None,
        "",
        f"当前缺少 slot {slot_no} 的历史槽位，且当前排列方式无法推导坐标。"
        "请先关闭全部窗口，按当前参数重新批量启动生成完整槽位。"
        "不要在窗口缺失状态下重新生成槽位。",
    )


def repair_window_slot(
    slot_no: int,
    game_path: str,
    slots_path: str | Path = "window_slots.json",
    title_template: Optional[str] = None,
    close_existing: bool = False,
    exclude_hwnds: Optional[Iterable[int]] = None,
    game_exe_path: str | Path | None = None,
    fixed_config: Optional[TileConfig] = None,
    environment: Optional[SlotEnvironment] = None,
    layout_params: Optional[SlotLayoutParams] = None,
    timeout_seconds: float = 60.0,
    poll_interval: float = 0.5,
) -> RepairSlotResult:
    slot, slot_source, resolve_error = resolve_window_slot_for_repair(
        slot_no=slot_no,
        slots_path=slots_path,
        title_template=title_template,
        fixed_config=fixed_config,
        exclude_hwnds=exclude_hwnds,
        game_exe_path=game_exe_path or game_path,
        environment=environment,
        layout_params=layout_params,
    )
    if slot is None:
        placeholder = WindowSlot(slot_no=int(slot_no), x=0, y=0, width=0, height=0)
        return RepairSlotResult(
            slot=placeholder,
            success=False,
            error=resolve_error,
        )

    old_hwnd = slot.hwnd
    if old_hwnd is not None and user32.IsWindow(wintypes.HWND(old_hwnd)):
        if not close_existing:
            return RepairSlotResult(
                slot=slot,
                success=False,
                old_hwnd=old_hwnd,
                error=f"slot {slot_no} 的旧窗口仍存在 hwnd={old_hwnd}",
                requires_close_confirmation=True,
                slot_source=slot_source,
            )
        close_result = wintypes.DWORD()
        user32.SendMessageTimeoutW(
            wintypes.HWND(old_hwnd),
            WM_CLOSE,
            0,
            0,
            SMTO_ABORTIFHUNG,
            1500,
            ctypes.byref(close_result),
        )
        time.sleep(0.5)

    excluded = {int(hwnd) for hwnd in exclude_hwnds or []}
    filter_game_path = game_exe_path or game_path
    before_windows = list_game_windows(
        title_template=title_template,
        exclude_hwnds=excluded,
        game_exe_path=filter_game_path,
    )
    for window in before_windows:
        if window.number != int(slot_no):
            continue
        repaired_slot = WindowSlot(
            slot_no=slot.slot_no,
            title=window.title,
            hwnd=window.hwnd,
            x=window.rect.left,
            y=window.rect.top,
            width=window.rect.width,
            height=window.rect.height,
            account_layer=slot.account_layer,
            account_index=slot.account_index,
            status="已存在",
        )
        _upsert_window_slot(
            slots_path,
            repaired_slot,
            environment=environment,
            layout_params=layout_params,
        )
        return RepairSlotResult(
            slot=repaired_slot,
            success=True,
            old_hwnd=old_hwnd,
            new_hwnd=window.hwnd,
            new_title=window.title,
            slot_source="current_title",
        )

    before_hwnds = {window.hwnd for window in before_windows}
    launch_result = launch_game_process(game_path)
    if not launch_result.success:
        return RepairSlotResult(
            slot=slot,
            success=False,
            old_hwnd=old_hwnd,
            error=f"启动新窗口失败：{launch_result.error}",
            slot_source=slot_source,
        )

    new_window: Optional[GameWindow] = None
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        windows = list_game_windows(
            title_template=title_template,
            exclude_hwnds=excluded,
            game_exe_path=filter_game_path,
        )
        candidates = [window for window in windows if window.hwnd not in before_hwnds]
        if candidates:
            candidates.sort(key=lambda item: (item.number is not None, item.title, item.hwnd))
            new_window = candidates[0]
            break

    if new_window is None:
        return RepairSlotResult(
            slot=slot,
            success=False,
            old_hwnd=old_hwnd,
            error="启动后未检测到新增 H5 窗口",
            slot_source=slot_source,
        )

    move_ok, move_error = _set_window_pos_with_retries(
        new_window,
        slot.x,
        slot.y,
        slot.width,
        slot.height,
        SWP_NOZORDER | SWP_NOACTIVATE,
        retries=3,
        retry_delay=0.5,
    )
    if not move_ok:
        return RepairSlotResult(
            slot=slot,
            success=False,
            old_hwnd=old_hwnd,
            new_hwnd=new_window.hwnd,
            error=f"移动新窗口失败：{move_error}",
            slot_source=slot_source,
        )

    new_title = _slot_title(title_template, slot)
    rename_ok = bool(user32.SetWindowTextW(wintypes.HWND(new_window.hwnd), new_title))
    if not rename_ok:
        error_code = ctypes.get_last_error()
        return RepairSlotResult(
            slot=slot,
            success=False,
            old_hwnd=old_hwnd,
            new_hwnd=new_window.hwnd,
            new_title=new_title,
            error=f"重命名新窗口失败，错误码 {error_code}",
            slot_source=slot_source,
        )

    repaired_slot = WindowSlot(
        slot_no=slot.slot_no,
        title=new_title,
        hwnd=new_window.hwnd,
        x=slot.x,
        y=slot.y,
        width=slot.width,
        height=slot.height,
        account_layer=slot.account_layer,
        account_index=slot.account_index,
        status="已补位",
    )
    _upsert_window_slot(
        slots_path,
        repaired_slot,
        environment=environment,
        layout_params=layout_params,
    )

    return RepairSlotResult(
        slot=slot,
        success=True,
        old_hwnd=old_hwnd,
        new_hwnd=new_window.hwnd,
        new_title=new_title,
        slot_source=slot_source,
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
    title_keyword: str = "",
    title_template: str | None = None,
    exclude_hwnds: Optional[Iterable[int]] = None,
    game_exe_path: str | Path | None = None,
    allow_unnumbered: bool = True,
    expected_window_size: tuple[int, int] | None = None,
    diagnostic_log_path: str | Path | None = WINDOW_DETECTION_LOG_PATH,
) -> List[GameWindow]:
    windows: List[GameWindow] = []
    detection_results: list[WindowDetectResult] = []
    excluded = {int(hwnd) for hwnd in exclude_hwnds or []}

    @EnumWindowsProc
    def callback(hwnd: int, _lparam: int) -> bool:
        if int(hwnd) in excluded:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        if _is_window_cloaked(hwnd):
            return True

        title = _get_window_title(hwnd)
        if not (_is_detection_candidate_title(title, title_template=title_template) or (title_keyword and title_keyword in title)):
            return True
        try:
            rect = get_window_rect(int(hwnd))
        except OSError:
            rect = WindowRect(0, 0, 0, 0)
        try:
            class_name = get_window_class_name(int(hwnd))
        except Exception:
            class_name = ""
        try:
            pid = get_window_process_id(int(hwnd))
        except Exception:
            pid = None
        detect_result = detect_game_window(
            int(hwnd),
            title,
            configured_game_exe_path=game_exe_path,
            title_template=title_template,
            allow_unnumbered=allow_unnumbered,
            rect=rect,
            expected_window_size=expected_window_size,
            class_name=class_name,
            pid=pid,
        )
        detection_results.append(detect_result)
        if detect_result.accepted:
            windows.append(
                GameWindow(
                    hwnd=int(hwnd),
                    title=title,
                    number=detect_result.slot_no,
                    rect=rect,
                )
            )
        return True

    if not user32.EnumWindows(callback, 0):
        error_code = ctypes.get_last_error()
        raise ctypes.WinError(error_code)

    _write_window_detection_diagnostics(
        detection_results,
        configured_game_exe_path=game_exe_path,
        expected_window_size=expected_window_size,
        log_path=diagnostic_log_path,
    )
    return sort_game_windows(windows)


def tile_game_windows(
    config: TileConfig,
    exclude_hwnds: Optional[Iterable[int]] = None,
    game_exe_path: str | Path | None = None,
    title_template: str | None = None,
    windows: Optional[List[GameWindow]] = None,
    slot_indexes: Optional[Iterable[int]] = None,
    layout_window_count: int | None = None,
    retries: int = 3,
    retry_delay: float = 0.5,
) -> List[TileResult]:
    if config.per_row <= 0:
        raise ValueError("每行数量必须大于 0")
    if config.width <= 0 or config.height <= 0:
        raise ValueError("窗口宽度和高度必须大于 0")

    arranged_windows = (
        list(windows)
        if windows is not None
        else list_game_windows(
            title_template=title_template,
            exclude_hwnds=exclude_hwnds,
            game_exe_path=game_exe_path,
            expected_window_size=(config.width, config.height),
        )
    )
    positions = _normalize_tile_slot_indexes(arranged_windows, slot_indexes, layout_window_count)
    results: List[TileResult] = []
    if arranged_windows:
        probe = arranged_windows[0]
        ok, error = _set_window_pos_with_retries(
            probe,
            probe.rect.left,
            probe.rect.top,
            probe.rect.width,
            probe.rect.height,
            SWP_NOZORDER | SWP_NOACTIVATE,
            retries=0,
            retry_delay=0,
        )
        if not ok:
            return [
                TileResult(
                    window=probe,
                    x=probe.rect.left,
                    y=probe.rect.top,
                    success=False,
                    error=f"移动权限预检失败：{error}",
                    width=probe.rect.width,
                    height=probe.rect.height,
                )
            ]

    for slot_index, window in zip(positions, arranged_windows):
        x, y = calculate_tile_position(slot_index, config)

        ok, error = _set_window_pos_with_retries(
            window,
            x,
            y,
            config.width,
            config.height,
            SWP_NOZORDER | SWP_NOACTIVATE,
            retries,
            retry_delay,
        )

        if ok:
            results.append(
                TileResult(
                    window=window,
                    x=x,
                    y=y,
                    success=True,
                    width=config.width,
                    height=config.height,
                )
            )
        else:
            results.append(
                TileResult(
                    window=window,
                    x=x,
                    y=y,
                    success=False,
                    error=error,
                    width=config.width,
                    height=config.height,
                )
            )

    return results


def tile_game_windows_by_row_count(
    config: RowTileConfig,
    exclude_hwnds: Optional[Iterable[int]] = None,
    game_exe_path: str | Path | None = None,
    title_template: str | None = None,
    windows: Optional[List[GameWindow]] = None,
    slot_indexes: Optional[Iterable[int]] = None,
    layout_window_count: int | None = None,
    retries: int = 3,
    retry_delay: float = 0.5,
) -> List[TileResult]:
    if config.per_row <= 0:
        raise ValueError("单行数量必须大于 0")
    if config.gap_x < 0 or config.gap_y < 0:
        raise ValueError("窗口间距不能小于 0")

    arranged_windows = (
        list(windows)
        if windows is not None
        else list_game_windows(
            title_template=title_template,
            exclude_hwnds=exclude_hwnds,
            game_exe_path=game_exe_path,
            expected_window_size=(config.width, config.height)
            if config.width is not None and config.height is not None
            else None,
        )
    )
    positions = _normalize_tile_slot_indexes(arranged_windows, slot_indexes, layout_window_count)
    planned_count = max(
        int(layout_window_count or 0),
        max(positions, default=-1) + 1,
        len(arranged_windows),
    )
    plan = calculate_row_tile_plan(planned_count, config)
    results: List[TileResult] = []
    if arranged_windows:
        probe = arranged_windows[0]
        ok, error = _set_window_pos_with_retries(
            probe,
            probe.rect.left,
            probe.rect.top,
            probe.rect.width,
            probe.rect.height,
            SWP_NOZORDER | SWP_NOACTIVATE,
            retries=0,
            retry_delay=0,
        )
        if not ok:
            return [
                TileResult(
                    window=probe,
                    x=probe.rect.left,
                    y=probe.rect.top,
                    success=False,
                    error=f"移动权限预检失败：{error}",
                    width=probe.rect.width,
                    height=probe.rect.height,
                )
            ]

    for slot_index, window in zip(positions, arranged_windows):
        row = slot_index // plan.cols
        col = slot_index % plan.cols
        x = config.start_x + col * (plan.target_width + plan.gap_x)
        y = config.start_y + row * (plan.target_height + plan.gap_y)
        wrapped_by_screen = col == 0 and row > 0
        flags = SWP_NOZORDER | SWP_NOACTIVATE

        ok, error = _set_window_pos_with_retries(
            window,
            x,
            y,
            plan.target_width,
            plan.target_height,
            flags,
            retries,
            retry_delay,
        )

        result = TileResult(
            window=window,
            x=x,
            y=y,
            success=ok,
            error="" if ok else error,
            width=plan.target_width,
            height=plan.target_height,
            wrapped_by_screen=wrapped_by_screen,
        )
        results.append(result)

    return results


def _normalize_tile_slot_indexes(
    windows: Iterable[GameWindow],
    slot_indexes: Optional[Iterable[int]],
    layout_window_count: int | None,
) -> list[int]:
    arranged_windows = list(windows)
    positions = list(range(len(arranged_windows))) if slot_indexes is None else [int(value) for value in slot_indexes]
    if len(positions) != len(arranged_windows):
        raise ValueError("槽位索引数量必须与窗口数量一致")
    if any(value < 0 for value in positions):
        raise ValueError("槽位索引不能小于 0")
    if layout_window_count is not None:
        clean_count = int(layout_window_count)
        if clean_count < 0:
            raise ValueError("布局窗口数量不能小于 0")
        if positions and max(positions) >= clean_count:
            raise ValueError("槽位索引超出布局窗口数量")
    return positions


def calculate_row_tile_plan(window_count: int, config: RowTileConfig) -> RowTilePlan:
    if config.per_row <= 0:
        raise ValueError("单行数量必须大于 0")
    work_area = get_screen_work_area()
    screen_width, screen_height = get_full_screen_size()
    cols = max(1, config.per_row)
    rows = max(1, math.ceil(window_count / cols)) if window_count > 0 else 0
    usable_width = max(1, work_area.right - config.start_x)
    usable_height = max(1, work_area.bottom - config.start_y)
    width_gap_total = config.gap_x * max(0, cols - 1)
    height_gap_total = config.gap_y * max(0, rows - 1)
    raw_target_width = (usable_width - width_gap_total) / cols
    raw_target_height = (usable_height - height_gap_total) / max(1, rows)
    target_width = max(1, math.floor(raw_target_width))
    target_height = max(1, math.floor(raw_target_height))
    return RowTilePlan(
        screen_width=screen_width,
        screen_height=screen_height,
        work_area=work_area,
        work_area_width=work_area.width,
        work_area_height=work_area.height,
        window_count=window_count,
        cols=cols,
        rows=rows,
        target_width=target_width,
        target_height=target_height,
        raw_target_width=raw_target_width,
        raw_target_height=raw_target_height,
        gap_x=config.gap_x,
        gap_y=config.gap_y,
        width_gap_total=width_gap_total,
        height_gap_total=height_gap_total,
        padding=0,
        safe_margin=0,
        usable_width=usable_width,
        usable_height=usable_height,
    )


def rename_game_windows(
    title_template: str,
    exclude_hwnds: Optional[Iterable[int]] = None,
    game_exe_path: str | Path | None = None,
) -> List[RenameResult]:
    if not title_template.strip():
        raise ValueError("标题模板不能为空")

    results: List[RenameResult] = []
    for index, window in enumerate(
        list_game_windows(
            title_template=title_template,
            exclude_hwnds=exclude_hwnds,
            game_exe_path=game_exe_path,
        ),
        start=1,
    ):
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
    game_exe_path: str | Path | None = None,
    title_template: str | None = None,
) -> List[CloseResult]:
    results: List[CloseResult] = []
    for window in list_game_windows(
        title_template=title_template,
        exclude_hwnds=exclude_hwnds,
        game_exe_path=game_exe_path,
    ):
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
