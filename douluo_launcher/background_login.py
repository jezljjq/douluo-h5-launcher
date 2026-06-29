from __future__ import annotations

import json
import importlib
import os
import struct
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from .automation import AccountRunner, extract_hex_passport, extract_passport_from_login_image
from .config import AccountConfig, AutomationSettings, app_root
from .dm_client import list_browser_windows, select_login_window_by_game_no
from .window_manager import SMTO_ABORTIFHUNG, get_window_class_name, get_window_process_id, get_window_rect, user32
from .window_operator import BackgroundOperator, images_changed


LogFn = Callable[[str], None]
StatusFn = Callable[[AccountConfig, str], None]
PassportFoundFn = Callable[[AccountConfig, str], None]

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_LBUTTONDBLCLK = 0x0203
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_CONTROL = 0x11
VK_C = 0x43

BACKGROUND_REQUIRED_MODULES = ("cv2", "numpy", "PIL", "pytesseract", "win32gui", "win32con", "win32api")
BACKGROUND_INSTALL_COMMANDS = {
    "cv2": "py -3.14-32 -m pip install opencv-python",
    "numpy": "py -3.14-32 -m pip install numpy",
    "PIL": "py -3.14-32 -m pip install pillow",
    "pytesseract": "py -3.14-32 -m pip install pytesseract",
    "win32gui": "py -3.14-32 -m pip install pywin32",
    "win32con": "py -3.14-32 -m pip install pywin32",
    "win32api": "py -3.14-32 -m pip install pywin32",
}


@dataclass(frozen=True)
class BackgroundDependencyCheck:
    ok: bool
    missing_modules: tuple[str, ...]
    python_executable: str
    python_bits: int
    install_commands: tuple[str, ...]


@dataclass(frozen=True)
class BackgroundPassportCopyResult:
    success: bool
    passport: str = ""
    error: str = ""
    method: str = ""
    clipboard_used: bool = False
    clipboard_restored: bool = True
    clipboard_restore_error: str = ""
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class BackgroundLoginResult:
    status: str
    success: bool = False
    reason: str = ""
    final_verified: bool = False

    def __bool__(self) -> bool:
        return bool(self.success or self.status == "skipped_logged_in")


def check_background_runtime_dependencies(
    *,
    import_module: Callable[[str], object] | None = None,
    python_executable: str | None = None,
    python_bits: int | None = None,
) -> BackgroundDependencyCheck:
    importer = import_module or importlib.import_module
    missing: list[str] = []
    for module_name in BACKGROUND_REQUIRED_MODULES:
        try:
            importer(module_name)
        except ImportError:
            missing.append(module_name)
    commands: list[str] = []
    for module_name in missing:
        command = BACKGROUND_INSTALL_COMMANDS.get(
            module_name,
            f"py -3.14-32 -m pip install {module_name}",
        )
        if command not in commands:
            commands.append(command)
    return BackgroundDependencyCheck(
        ok=not missing,
        missing_modules=tuple(missing),
        python_executable=python_executable or sys.executable,
        python_bits=int(python_bits or (struct.calcsize("P") * 8)),
        install_commands=tuple(commands),
    )


@dataclass
class _BrowserSession:
    playwright: object
    browser: object
    page: object
    hwnd: int
    context: object | None = None
    owns_playwright: bool = False

    def close(self) -> None:
        try:
            self.page.close()
        except Exception:
            pass
        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
        try:
            self.browser.close()
        except Exception:
            pass
        if self.owns_playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass


@dataclass
class _LoginWindowSnapshot:
    hwnd: int
    title: str
    image: Any
    raw_path: Path
    state: str
    metrics: dict[str, Any]


_BACKGROUND_OPEN_SESSIONS: list[_BrowserSession] = []
_BACKGROUND_OPEN_SESSIONS_LOCK = threading.Lock()
_BACKGROUND_PLAYWRIGHTS_BY_THREAD: dict[int, object] = {}
_BACKGROUND_PLAYWRIGHT_LOCK = threading.Lock()


def _remember_background_session(session: _BrowserSession) -> None:
    with _BACKGROUND_OPEN_SESSIONS_LOCK:
        _BACKGROUND_OPEN_SESSIONS.append(session)


def _get_background_playwright():
    thread_id = int(threading.get_ident())
    with _BACKGROUND_PLAYWRIGHT_LOCK:
        playwright = _BACKGROUND_PLAYWRIGHTS_BY_THREAD.get(thread_id)
        if playwright is None:
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            _BACKGROUND_PLAYWRIGHTS_BY_THREAD[thread_id] = playwright
        return playwright


def release_background_playwright_for_current_thread() -> None:
    thread_id = int(threading.get_ident())
    with _BACKGROUND_PLAYWRIGHT_LOCK:
        playwright = _BACKGROUND_PLAYWRIGHTS_BY_THREAD.get(thread_id)
    if playwright is None:
        return
    with _BACKGROUND_OPEN_SESSIONS_LOCK:
        retained = any(session.playwright is playwright for session in _BACKGROUND_OPEN_SESSIONS)
    if retained:
        return
    with _BACKGROUND_PLAYWRIGHT_LOCK:
        if _BACKGROUND_PLAYWRIGHTS_BY_THREAD.get(thread_id) is playwright:
            _BACKGROUND_PLAYWRIGHTS_BY_THREAD.pop(thread_id, None)
    try:
        playwright.stop()
    except Exception:
        pass


def _ensure_playwright_browsers_path_for_background() -> Path | None:
    if os.name != "nt":
        return None
    bundled = app_root() / "ms-playwright"
    if getattr(sys, "frozen", False) and bundled.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
        return bundled
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        return None
    expected = Path(localappdata) / "ms-playwright"
    current = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    current_lower = current.lower()
    if not current or ("_internal" in current_lower and ".local-browsers" in current_lower):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(expected)
    return expected


def _make_lparam(x: int, y: int) -> int:
    return (int(y) & 0xFFFF) << 16 | (int(x) & 0xFFFF)


def _extract_background_passport_hex(text: str | None) -> str | None:
    value = extract_hex_passport(str(text or ""))
    if value and len(value) == 8:
        return value.lower()
    return None


def _read_clipboard_text() -> tuple[bool, str | None]:
    try:
        import win32clipboard
        import win32con
    except Exception:
        return False, None

    for _ in range(8):
        try:
            win32clipboard.OpenClipboard()
            try:
                if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return True, None
                return True, win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.05)
    return False, None


def _set_clipboard_text(text: str) -> bool:
    try:
        import win32clipboard
        import win32con
    except Exception:
        return False

    for _ in range(8):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, str(text))
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.05)
    return False


def _read_hwnd_text(hwnd: int, *, max_chars: int = 4096) -> str:
    import ctypes

    hwnd = int(hwnd)
    length_result = ctypes.c_ulonglong(0)
    try:
        user32.SendMessageTimeoutW(
            hwnd,
            WM_GETTEXTLENGTH,
            0,
            0,
            SMTO_ABORTIFHUNG,
            200,
            ctypes.byref(length_result),
        )
        length = int(length_result.value or 0)
    except Exception:
        length = 0
    size = max(2, min(max_chars, length + 2 if length > 0 else 512))
    buffer = ctypes.create_unicode_buffer(size)
    result = ctypes.c_ulonglong(0)
    try:
        user32.SendMessageTimeoutW(
            hwnd,
            WM_GETTEXT,
            size,
            ctypes.addressof(buffer),
            SMTO_ABORTIFHUNG,
            300,
            ctypes.byref(result),
        )
        return str(buffer.value or "")
    except Exception:
        return ""


def _post_ctrl_c(hwnd: int) -> bool:
    hwnd = int(hwnd)
    down_ctrl = bool(user32.PostMessageW(hwnd, WM_KEYDOWN, VK_CONTROL, 0))
    down_c = bool(user32.PostMessageW(hwnd, WM_KEYDOWN, VK_C, 0))
    up_c = bool(user32.PostMessageW(hwnd, WM_KEYUP, VK_C, 0))
    up_ctrl = bool(user32.PostMessageW(hwnd, WM_KEYUP, VK_CONTROL, 0))
    return bool(down_ctrl and down_c and up_c and up_ctrl)


def _clipboard_copy_attempt(
    *,
    action: Callable[[], bool],
    timeout_seconds: float = 1.2,
) -> BackgroundPassportCopyResult:
    original_ok, original_text = _read_clipboard_text()
    marker = f"__douluo_background_copy_{uuid.uuid4().hex}__"
    if not _set_clipboard_text(marker):
        return BackgroundPassportCopyResult(
            False,
            "",
            "clipboard_marker_failed",
            clipboard_used=True,
            clipboard_restored=False,
            clipboard_restore_error="无法写入剪贴板 marker",
        )

    action_ok = bool(action())
    deadline = time.perf_counter() + timeout_seconds
    copied_text = ""
    changed = False
    while time.perf_counter() <= deadline:
        ok, text = _read_clipboard_text()
        if ok:
            copied_text = str(text or "")
            if copied_text and copied_text != marker:
                changed = True
                break
        time.sleep(0.08)

    restore_ok = True
    restore_error = ""
    if original_ok:
        restore_ok = _set_clipboard_text(original_text or "")
        if not restore_ok:
            restore_error = "原剪贴板文本恢复失败"
    else:
        restore_ok = _set_clipboard_text("")
        if not restore_ok:
            restore_error = "剪贴板 marker 清理失败"

    details = {
        "action_ok": action_ok,
        "changed": changed,
        "original_had_text": bool(original_text),
        "copied_preview": str(copied_text or "")[:80],
    }
    if not restore_ok:
        return BackgroundPassportCopyResult(
            False,
            "",
            "clipboard_restore_failed",
            clipboard_used=True,
            clipboard_restored=False,
            clipboard_restore_error=restore_error,
            details=details,
        )
    if not action_ok:
        return BackgroundPassportCopyResult(False, "", "background_copy_message_failed", clipboard_used=True, details=details)
    if not changed:
        return BackgroundPassportCopyResult(False, "", "clipboard_not_changed", clipboard_used=True, details=details)
    if original_text is not None and copied_text == original_text:
        return BackgroundPassportCopyResult(False, "", "clipboard_stale_original", clipboard_used=True, details=details)

    passport = _extract_background_passport_hex(copied_text)
    if not passport:
        return BackgroundPassportCopyResult(False, "", "clipboard_no_hex", clipboard_used=True, details=details)
    return BackgroundPassportCopyResult(
        True,
        passport,
        "",
        method="background_clipboard",
        clipboard_used=True,
        clipboard_restored=True,
        details=details,
    )


class BackgroundSingleAccountRunner:
    """方式一单账号后台登录实验流程。

    只使用 BackgroundOperator 做游戏页点击/输入，不调用 SetForegroundWindow、
    全局 MoveTo/LeftClick 或全局键盘输入。前台稳定链路仍由 AccountRunner 负责。
    """

    def __init__(
        self,
        account: AccountConfig,
        settings: AutomationSettings,
        stop_event: threading.Event,
        log: LogFn,
        update_status: StatusFn,
        passport_found: PassportFoundFn | None = None,
        operator: BackgroundOperator | None = None,
    ) -> None:
        self.account = account
        self.settings = settings
        self.stop_event = stop_event
        self.log = log
        self.update_status = update_status
        self.passport_found = passport_found
        self.operator = operator or BackgroundOperator()
        self._debug_dir = app_root() / settings.qr_passport_debug_dir / "_background"
        self._debug_dir.mkdir(parents=True, exist_ok=True)
        self._helper = AccountRunner(account, settings, stop_event, log, update_status, passport_found=passport_found)

    def run(self) -> BackgroundLoginResult:
        session: _BrowserSession | None = None
        keep_open = False
        started = time.perf_counter()
        try:
            self._ensure_not_stopped()
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 方式一单账号实验开始")
            self._ensure_not_stopped()
            self.update_status(self.account, "后台截图中")
            self._ensure_not_stopped()
            snapshot = self._capture_login_window_background()
            self._ensure_not_stopped()
            if self._should_skip_ocr(snapshot):
                self._ensure_not_stopped()
                self.update_status(self.account, "已进入游戏，跳过")
                self.log(
                    f"[后台模式][窗口{self.account.game_window_no}] 已进入游戏，跳过 OCR"
                )
                elapsed = time.perf_counter() - started
                self.log(f"[后台模式][窗口{self.account.game_window_no}] 后台单账号流程跳过，用时 {elapsed:.1f}s")
                return BackgroundLoginResult(
                    status="skipped_logged_in",
                    success=False,
                    reason="登录窗口已是 logged_in，跳过 OCR",
                    final_verified=True,
                )

            self._ensure_not_stopped()
            self.update_status(self.account, "识别通行证中")
            self._ensure_not_stopped()
            passport = self._extract_passport_from_login_window_background(snapshot)
            self._ensure_not_stopped()
            if self.passport_found is not None:
                self.passport_found(self.account, passport)
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 通行证识别成功：{passport}")

            self._ensure_not_stopped()
            self.update_status(self.account, "打开正式页中")
            self._ensure_not_stopped()
            session = self._open_formal_game_page()
            self._ensure_not_stopped()
            self.log(
                f"[后台模式][窗口{self.account.game_window_no}] 正式游戏页已打开 hwnd={session.hwnd}"
            )

            self._ensure_not_stopped()
            self.update_status(self.account, "关闭公告中")
            self._ensure_not_stopped()
            image = self.operator.screenshot(session.hwnd).convert("RGB")
            self._ensure_not_stopped()
            image.save(self._tmp_path("01_game_page_before_notice.png"))
            self._ensure_not_stopped()
            notice_closed, image = self._close_blocking_overlay(session.hwnd, image)
            self._ensure_not_stopped()
            if not notice_closed:
                raise RuntimeError("后台关闭公告/区服弹窗失败")
            image.save(self._tmp_path("02_after_notice.png"))

            self._ensure_not_stopped()
            self.update_status(self.account, "点击通行证中")
            self._ensure_not_stopped()
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 后台点击右侧通行证按钮")
            dialog_image = self._open_passport_dialog(session.hwnd, image)
            self._ensure_not_stopped()
            self.update_status(self.account, "输入通行证中")

            self._ensure_not_stopped()
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 后台输入通行证")
            input_image = self._input_passport_background(session.hwnd, dialog_image, passport)
            self._ensure_not_stopped()

            self.update_status(self.account, "确认中")
            self._ensure_not_stopped()
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 后台点击确认")
            confirmed = self._click_confirm_background(session.hwnd, input_image)
            if not confirmed:
                raise RuntimeError("后台确认失败，通行证弹窗仍未关闭")
            final_verified, verify_reason = self._verify_background_login_success(session.hwnd, snapshot.hwnd)
            if not final_verified:
                self.log(
                    f"[后台模式][窗口{self.account.game_window_no}] "
                    f"登录确认后未检测到成功状态，标记失败：{verify_reason}"
                )
                raise RuntimeError(f"登录确认后未检测到成功状态，标记失败：{verify_reason}")
            self._save_latest_success_artifacts(session.hwnd)
            self.update_status(self.account, "成功")
            elapsed = time.perf_counter() - started
            self.log(
                f"[后台模式][窗口{self.account.game_window_no}] "
                f"后台单账号流程完成，用时 {elapsed:.1f}s，最终校验={verify_reason}"
            )
            keep_open = bool(getattr(self.settings, "background_keep_success_browser", False))
            if keep_open:
                _remember_background_session(session)
            return BackgroundLoginResult(
                status="success",
                success=True,
                reason=verify_reason,
                final_verified=True,
            )
        except InterruptedError:
            self.update_status(self.account, "已停止")
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 任务已停止")
            return BackgroundLoginResult(status="stopped", success=False, reason="任务已停止", final_verified=False)
        except Exception as exc:
            self.update_status(self.account, "失败")
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 后台步骤失败：{exc}")
            return BackgroundLoginResult(status="failed", success=False, reason=str(exc), final_verified=False)
        finally:
            if session is not None and not keep_open:
                session.close()

    def _ensure_not_stopped(self) -> None:
        if self.stop_event.is_set():
            raise InterruptedError()

    def _tmp_path(self, name: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._debug_dir / f"w{self.account.game_window_no}_{stamp}_{name}"

    def _background_ocr_debug_dir(self) -> Path:
        path = app_root() / "debug_background"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _save_latest_success_artifacts(self, hwnd: int) -> None:
        debug_dir = self._background_ocr_debug_dir()
        try:
            image = self.operator.screenshot(int(hwnd)).convert("RGB")
            image.save(debug_dir / "latest_success.png")
            context = {
                "level": self.account.level,
                "bookmark_no": self.account.bookmark_no,
                "game_window_no": self.account.game_window_no,
                "url": self.account.url,
                "hwnd": int(hwnd),
                "saved_at": datetime.now().isoformat(timespec="seconds"),
            }
            (debug_dir / "latest_success_context.json").write_text(
                json.dumps(context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 保存成功现场失败：{exc}")

    def _capture_login_window_background(self) -> _LoginWindowSnapshot:
        self._ensure_not_stopped()
        selected, candidates = select_login_window_by_game_no(self.account.game_window_no)
        self.log(
            f"[后台模式][窗口{self.account.game_window_no}] 登录程序候选窗口数={len(candidates)}"
        )
        if selected is None:
            raise RuntimeError(f"未找到登录程序窗口{self.account.game_window_no}")

        self._ensure_not_stopped()
        image = self.operator.screenshot(selected.hwnd).convert("RGB")
        self._ensure_not_stopped()
        raw_path = self._tmp_path("login_window_full.png")
        image.save(raw_path)
        self.log(
            f"[后台模式][窗口{self.account.game_window_no}] 登录程序后台截图成功 "
            f"hwnd={selected.hwnd} title={selected.title}"
        )
        prefix = raw_path.stem
        self._ensure_not_stopped()
        state, metrics = self._helper.detect_login_page_state(image)
        self._ensure_not_stopped()
        self.log(
            f"[后台模式][窗口{self.account.game_window_no}] 登录窗口状态={state} "
            f"reason={metrics.get('final_reason')}"
        )
        return _LoginWindowSnapshot(
            hwnd=int(selected.hwnd),
            title=str(selected.title),
            image=image,
            raw_path=raw_path,
            state=str(state),
            metrics=dict(metrics or {}),
        )

    def _extract_passport_from_login_window_background(
        self,
        snapshot: _LoginWindowSnapshot | None = None,
    ) -> str:
        self._ensure_not_stopped()
        snapshot = snapshot or self._capture_login_window_background()
        self._ensure_not_stopped()
        self.log(
            f"[后台模式][窗口{self.account.game_window_no}] "
            "后台复制/读取已禁用，直接使用 OCR 多证据识别通行证"
        )
        self._ensure_not_stopped()
        result = extract_passport_from_login_image(
            snapshot.image,
            runner=self._helper,
            window_index=self.account.game_window_no,
            debug_dir=self._background_ocr_debug_dir(),
            mode="background",
            raw_path=snapshot.raw_path,
            login_context={
                "hwnd": snapshot.hwnd,
                "title": snapshot.title,
                "login_page_state": snapshot.state,
                "qr_box": snapshot.metrics.get("qr_box"),
                "fallback_qr_box": snapshot.metrics.get("fallback_qr_box"),
                "red_bar_box": snapshot.metrics.get("passport_bar_box"),
            },
            save_failure_artifacts=True,
        )
        self._ensure_not_stopped()
        if not result.passport:
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 后台 OCR 未能可靠识别本次通行证")
            raise RuntimeError("后台 OCR 未能可靠识别本次通行证")
        passport = result.passport.lower()
        votes = max(0, int(getattr(result, "evidence_votes", 0) or 0))
        source = str(getattr(result, "evidence_source", "") or "shared_ocr")
        self.log(
            f"[后台模式][窗口{self.account.game_window_no}] "
            f"OCR 识别成功：{passport}，来源={source}，votes={votes}"
        )
        return passport

    def _try_background_passport_copy(self, snapshot: _LoginWindowSnapshot) -> BackgroundPassportCopyResult:
        self.log(
            f"[后台模式][窗口{self.account.game_window_no}] "
            "后台复制/读取链路已禁用，未执行旧读取路径"
        )
        return BackgroundPassportCopyResult(
            False,
            "",
            "background_copy_read_disabled",
            method="disabled",
            clipboard_used=False,
            details={"hwnd": int(snapshot.hwnd), "disabled": True},
        )

    @staticmethod
    def _read_uia_texts(hwnd: int) -> list[str] | None:
        try:
            import uiautomation as auto  # type: ignore[import-not-found]
        except Exception:
            return None

        texts: list[str] = []

        def collect(control, depth: int) -> None:
            if depth > 3 or len(texts) >= 200:
                return
            for attr in ("Name", "Value", "HelpText"):
                try:
                    value = getattr(control, attr)
                    if value:
                        texts.append(str(value))
                except Exception:
                    pass
            try:
                children = control.GetChildren()
            except Exception:
                return
            for child in children:
                collect(child, depth + 1)

        try:
            root = auto.ControlFromHandle(int(hwnd))
            collect(root, 0)
        except Exception:
            return []
        return texts

    def _background_copy_window_point(self, snapshot: _LoginWindowSnapshot) -> tuple[int, int] | None:
        try:
            width, height = snapshot.image.size
            window = SimpleNamespace(
                hwnd=int(snapshot.hwnd),
                title=snapshot.title,
                width=int(width),
                height=int(height),
                left=0,
                top=0,
                right=int(width),
                bottom=int(height),
            )
            copy_region = self._helper._passport_copy_screen_region(window, snapshot.image)  # type: ignore[attr-defined]
            local_click = copy_region.get("local_click")
            if local_click is not None:
                return int(local_click[0]), int(local_click[1])
            return int(copy_region["click_x"]), int(copy_region["click_y"])
        except Exception as exc:
            self.log(
                f"[后台模式][窗口{self.account.game_window_no}] 后台复制定位失败：{exc}"
            )
            return None

    def _post_background_select_copy(self, hwnd: int, point: tuple[int, int]) -> bool:
        hwnd = int(hwnd)
        x, y = int(point[0]), int(point[1])
        first_click = self.operator.click(hwnd, x, y)
        time.sleep(0.05)
        double_click_ok = bool(user32.PostMessageW(hwnd, WM_LBUTTONDBLCLK, 0, _make_lparam(x, y)))
        time.sleep(0.08)
        copy_ok = _post_ctrl_c(hwnd)
        return bool((first_click.success or double_click_ok) and copy_ok)

    def _should_skip_ocr(self, snapshot: _LoginWindowSnapshot) -> bool:
        state = str(snapshot.state or "")
        if state == "qr_page":
            return False
        if state == "logged_in":
            return True

        metrics = snapshot.metrics or {}
        if bool(metrics.get("qr_page_evidence")) or bool(metrics.get("qr_suspected")):
            return False
        if str(metrics.get("qr_evidence_type") or "") not in ("", "no_qr"):
            return False
        return self._image_looks_nonblank(snapshot.image)

    @staticmethod
    def _image_looks_nonblank(image) -> bool:
        try:
            from PIL import ImageStat

            gray = image.convert("L")
            low, high = gray.getextrema()
            mean = float(ImageStat.Stat(gray).mean[0])
            return bool((int(high) - int(low)) >= 8 and mean >= 8.0)
        except Exception:
            return False

    def _open_formal_game_page(self) -> _BrowserSession:
        _ensure_playwright_browsers_path_for_background()
        before_hwnds = {int(window.hwnd) for window in list_browser_windows("")}
        playwright = _get_background_playwright()
        browser = None
        context = None
        try:
            launcher = getattr(playwright, self.settings.browser)
            browser = launcher.launch(
                headless=False,
                args=[
                    f"--window-size={self.settings.window_width},{self.settings.window_height}",
                    "--window-position=100,100",
                ],
            )
            context = browser.new_context(viewport={"width": self.settings.window_width, "height": self.settings.window_height})
            page = context.new_page()
            page.goto(self.account.url, wait_until="domcontentloaded", timeout=self.settings.page_load_timeout_ms)
            deadline = time.time() + 12
            selected = None
            while time.time() < deadline:
                self._ensure_not_stopped()
                for window in list_browser_windows(""):
                    if int(window.hwnd) not in before_hwnds:
                        selected = window
                        break
                if selected is not None:
                    break
                time.sleep(0.2)
            if selected is None:
                raise RuntimeError("未找到后台测试浏览器窗口")
            time.sleep(max(0.5, self.settings.after_goto_wait_ms / 1000.0))
            return _BrowserSession(
                playwright=playwright,
                browser=browser,
                page=page,
                hwnd=int(selected.hwnd),
                context=context,
            )
        except Exception:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            raise

    def _verify_background_login_success(self, session_hwnd: int, login_hwnd: int) -> tuple[bool, str]:
        deadline = time.time() + max(1.0, self.settings.state_check_timeout_ms / 1000.0)
        reasons: list[str] = []
        while time.time() <= deadline:
            self._ensure_not_stopped()
            reasons = []
            try:
                formal_image = self.operator.screenshot(int(session_hwnd)).convert("RGB")
                formal_image.save(self._tmp_path("06_final_verify_formal.png"))
                if self._helper._looks_like_game_notice_page(formal_image):  # type: ignore[attr-defined]
                    return True, "正式页检测到公告/已登录视觉特征"
                if self._helper._looks_like_game_ui_page(formal_image):  # type: ignore[attr-defined]
                    return True, "正式页检测到游戏主界面视觉特征"
                if self._passport_input_box_point(formal_image):
                    reasons.append("正式页仍显示通行证输入框")
                else:
                    reasons.append("正式页未检测到游戏主界面")
            except Exception as exc:
                reasons.append(f"正式页校验异常: {exc}")

            try:
                login_image = self.operator.screenshot(int(login_hwnd)).convert("RGB")
                login_image.save(self._tmp_path("06_final_verify_login_window.png"))
                state, metrics = self._helper.detect_login_page_state(login_image)
                if str(state) == "logged_in":
                    return True, f"登录窗口状态为 logged_in: {metrics.get('final_reason')}"
                reasons.append(f"登录窗口状态仍为 {state}: {metrics.get('final_reason')}")
            except Exception as exc:
                reasons.append(f"登录窗口校验异常: {exc}")

            time.sleep(0.5)

        return False, "；".join(reason for reason in reasons if reason) or "没有 logged_in 成功证据"

    def _window_children(self, hwnd: int) -> list[dict[str, object]]:
        import ctypes
        from ctypes import wintypes

        children: list[dict[str, object]] = []
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @enum_proc
        def callback(child_hwnd, _lparam):
            child = int(child_hwnd)
            try:
                rect = get_window_rect(child)
                rect_payload = [rect.left, rect.top, rect.right, rect.bottom]
            except Exception:
                rect_payload = [0, 0, 0, 0]
            try:
                class_name = get_window_class_name(child)
            except Exception:
                class_name = ""
            try:
                pid = get_window_process_id(child)
            except Exception:
                pid = 0
            children.append({"hwnd": child, "class_name": class_name, "rect": rect_payload, "pid": int(pid or 0)})
            return True

        try:
            user32.EnumChildWindows(int(hwnd), callback, 0)
        except Exception:
            pass
        return children

    @staticmethod
    def _render_child(children: list[dict[str, object]]) -> dict[str, object] | None:
        for child in children:
            if str(child.get("class_name", "")).lower() == "chrome_renderwidgethosthwnd".lower():
                return child
        return None

    def _translate_to_click_target(
        self,
        hwnd: int,
        point: tuple[int, int],
        children: list[dict[str, object]] | None = None,
    ) -> tuple[int, tuple[int, int]]:
        children = children if children is not None else self._window_children(hwnd)
        child = self._render_child(children)
        if child is None:
            return int(hwnd), (int(point[0]), int(point[1]))
        try:
            top_rect = get_window_rect(hwnd)
            child_left, child_top, child_right, child_bottom = [int(value) for value in child["rect"]]
            x = int(point[0]) - (child_left - int(top_rect.left))
            y = int(point[1]) - (child_top - int(top_rect.top))
            if 0 <= x <= child_right - child_left and 0 <= y <= child_bottom - child_top:
                return int(child["hwnd"]), (x, y)
        except Exception:
            pass
        return int(hwnd), (int(point[0]), int(point[1]))

    def _background_click_window_point(
        self,
        hwnd: int,
        point: tuple[int, int],
        label: str,
        children: list[dict[str, object]] | None = None,
    ) -> bool:
        target_hwnd, target_point = self._translate_to_click_target(hwnd, point, children)
        result = self.operator.click(target_hwnd, target_point[0], target_point[1])
        self.log(
            f"[后台模式][窗口{self.account.game_window_no}] {label}: "
            f"window_point={point} target_hwnd={target_hwnd} target_point={target_point} result={result.message}"
        )
        return bool(result.success)

    def _close_blocking_overlay(self, hwnd: int, image) -> tuple[bool, object]:
        if not self._detect_blocking_overlay(image):
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 未检测到公告/区服阻塞弹窗")
            return True, image
        children = self._window_children(hwnd)
        current = image
        ratios = ((0.22, 0.18), (0.78, 0.18), (0.78, 0.80))
        for attempt, ratio in enumerate(ratios, start=1):
            point = self._point_from_ratio(current, ratio)
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 尝试关闭公告/区服（第{attempt}次）")
            self._background_click_window_point(hwnd, point, "点击弹窗外区域", children)
            time.sleep(0.5)
            current = self.operator.screenshot(hwnd).convert("RGB")
            current.save(self._tmp_path(f"notice_after_outside_{attempt}.png"))
            if not self._detect_blocking_overlay(current):
                return True, current

        close_point = self._estimate_center_overlay_close_point(current)
        if close_point is not None:
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 外点关闭失败，尝试右上角关闭点")
            self._background_click_window_point(hwnd, close_point, "点击阻塞弹窗关闭点", children)
            time.sleep(0.5)
            current = self.operator.screenshot(hwnd).convert("RGB")
            current.save(self._tmp_path("notice_after_close_button.png"))
            if not self._detect_blocking_overlay(current):
                return True, current
        return False, current

    def _open_passport_dialog(self, hwnd: int, image):
        point, score = self._locate_passport_button(image)
        if point is None:
            point = self._render_point_to_window_point(hwnd, self.settings.passport_btn_viewport)
        self._background_click_window_point(hwnd, point, "点击通行证按钮")
        time.sleep(max(0.5, self.settings.after_passport_button_wait_ms / 1000.0))
        after = self.operator.screenshot(hwnd).convert("RGB")
        after.save(self._tmp_path("03_passport_dialog_after.png"))
        if not self._passport_input_box_point(after):
            raise RuntimeError("通行证输入面板未出现")
        return after

    def _input_passport_background(self, hwnd: int, image, passport: str):
        input_point = self._passport_input_box_point(image)
        if input_point is None:
            raise RuntimeError("未定位到通行证输入框")
        children = self._window_children(hwnd)
        self._background_click_window_point(hwnd, input_point, "点击通行证输入框", children)
        time.sleep(0.2)
        before = self.operator.screenshot(hwnd).convert("RGB")
        before_crop = self._crop_input_box_region(before, input_point)
        targets = [int(hwnd)]
        render = self._render_child(children)
        if render is not None:
            targets.append(int(render["hwnd"]))
        for target_hwnd in dict.fromkeys(targets):
            result = self.operator.input_text(target_hwnd, passport)
            time.sleep(0.3)
            after = self.operator.screenshot(hwnd).convert("RGB")
            after.save(self._tmp_path(f"04_input_after_{target_hwnd}.png"))
            after_crop = self._crop_input_box_region(after, input_point)
            if result.success and self._input_box_has_visual_text_change(before_crop, after_crop):
                self.log(
                    f"[后台模式][窗口{self.account.game_window_no}] 后台输入真实生效 target_hwnd={target_hwnd}"
                )
                return after
        raise RuntimeError("后台输入消息已发送，但未验证到输入框文字变化")

    def _click_confirm_background(self, hwnd: int, image) -> bool:
        confirm = self._helper._locate_confirm_button_center(image, log_result=True)
        if confirm is None:
            raise RuntimeError("未定位到确认按钮")
        self._background_click_window_point(hwnd, confirm, "点击确认按钮")
        time.sleep(max(0.6, self.settings.after_submit_wait_ms / 1000.0))
        after = self.operator.screenshot(hwnd).convert("RGB")
        after.save(self._tmp_path("05_after_confirm.png"))
        return not bool(self._passport_input_box_point(after))

    def _locate_passport_button(self, image) -> tuple[tuple[int, int] | None, float | None]:
        template_path = app_root() / self.settings.passport_btn_template
        if not template_path.exists():
            return None, None
        try:
            import cv2
            import numpy as np

            source = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
            template = cv2.imdecode(np.fromfile(str(template_path), dtype=np.uint8), cv2.IMREAD_COLOR)
            if template is None:
                return None, None
            result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            center = (int(max_loc[0] + template.shape[1] / 2), int(max_loc[1] + template.shape[0] / 2))
            if float(max_val) < 0.55:
                return None, float(max_val)
            self.log(
                f"[后台模式][窗口{self.account.game_window_no}] 通行证按钮模板匹配成功 {center} score={max_val:.3f}"
            )
            return center, float(max_val)
        except Exception as exc:
            self.log(f"[后台模式][窗口{self.account.game_window_no}] 通行证按钮模板匹配失败：{exc}")
            return None, None

    def _render_point_to_window_point(self, hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
        children = self._window_children(hwnd)
        child = self._render_child(children)
        if child is None:
            return int(point[0]), int(point[1])
        try:
            top_rect = get_window_rect(hwnd)
            child_left, child_top, *_ = [int(value) for value in child["rect"]]
            return int(point[0]) + (child_left - int(top_rect.left)), int(point[1]) + (child_top - int(top_rect.top))
        except Exception:
            return int(point[0]), int(point[1])

    @staticmethod
    def _point_from_ratio(image, ratio: tuple[float, float]) -> tuple[int, int]:
        width, height = image.size
        return (
            max(0, min(width - 1, int(width * ratio[0]))),
            max(0, min(height - 1, int(height * ratio[1]))),
        )

    def _detect_blocking_overlay(self, image) -> bool:
        try:
            text = self._helper._ocr_image_text(image, "后台阻塞弹窗")
            normalized = str(text or "").replace(" ", "")
            if any(marker in normalized for marker in ("公告", "选择区服", "最近登录")):
                return True
        except Exception:
            pass
        return self._detect_large_center_gray_panel(image)

    @staticmethod
    def _detect_large_center_gray_panel(image) -> bool:
        try:
            import numpy as np

            width, height = image.size
            crop = image.crop((int(width * 0.30), int(height * 0.25), int(width * 0.70), int(height * 0.85))).convert("RGB")
            pixels = np.array(crop)
            spread = pixels.max(axis=2) - pixels.min(axis=2)
            brightness = pixels.mean(axis=2)
            gray_mask = (spread < 28) & (brightness >= 90) & (brightness <= 235)
            return bool(float(gray_mask.mean()) >= 0.48)
        except Exception:
            return False

    @staticmethod
    def _estimate_center_overlay_close_point(image) -> tuple[int, int] | None:
        try:
            import cv2
            import numpy as np

            width, height = image.size
            pixels = np.array(image.convert("RGB"))
            spread = pixels.max(axis=2) - pixels.min(axis=2)
            brightness = pixels.mean(axis=2)
            mask = ((spread < 32) & (brightness >= 90) & (brightness <= 235)).astype("uint8") * 255
            mask[: int(height * 0.16), :] = 0
            mask[:, : int(width * 0.18)] = 0
            mask[:, int(width * 0.82) :] = 0
            count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
            best: tuple[int, int, int, int, int] | None = None
            for index in range(1, count):
                x, y, w, h, area = [int(value) for value in stats[index]]
                if area < width * height * 0.04 or w < width * 0.20 or h < height * 0.20:
                    continue
                if best is None or area > best[4]:
                    best = (x, y, w, h, area)
            if best is None:
                return (int(width * 0.685), int(height * 0.247))
            x, y, w, _h, _area = best
            return (min(width - 1, x + w - 12), min(height - 1, y + 12))
        except Exception:
            width, height = image.size
            return (int(width * 0.685), int(height * 0.247))

    @staticmethod
    def _passport_input_box_point(image) -> tuple[int, int] | None:
        try:
            import cv2
            import numpy as np

            width, height = image.size
            pixels = np.array(image.convert("RGB"))
            brightness = pixels.mean(axis=2)
            roi_left = int(width * 0.25)
            roi_top = int(height * 0.25)
            roi_right = int(width * 0.75)
            roi_bottom = int(height * 0.65)
            roi = brightness[roi_top:roi_bottom, roi_left:roi_right]
            mask = (roi < 105).astype("uint8") * 255
            count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
            best_index: int | None = None
            best_area = 0
            for index in range(1, count):
                _x, _y, w, h, area = [int(value) for value in stats[index]]
                if area < 500 or w < width * 0.10 or h < 12 or h > height * 0.08:
                    continue
                if area > best_area:
                    best_index = index
                    best_area = area
            if best_index is None:
                return None
            cx, cy = centroids[best_index]
            return int(roi_left + cx), int(roi_top + cy)
        except Exception:
            return None

    @staticmethod
    def _crop_input_box_region(image, point: tuple[int, int]):
        width, height = image.size
        x, y = point
        crop_width = max(160, int(width * 0.34))
        crop_height = max(45, int(height * 0.10))
        left = max(0, int(x - crop_width // 2))
        top = max(0, int(y - crop_height // 2))
        right = min(width, left + crop_width)
        bottom = min(height, top + crop_height)
        return image.crop((left, top, right, bottom))

    @staticmethod
    def _input_box_has_visual_text_change(before_crop, after_crop) -> bool:
        try:
            import numpy as np

            if getattr(before_crop, "size", None) != getattr(after_crop, "size", None):
                return True
            before_pixels = np.array(before_crop.convert("RGB"))
            after_pixels = np.array(after_crop.convert("RGB"))
            before_brightness = before_pixels.mean(axis=2)
            after_brightness = after_pixels.mean(axis=2)
            dark_field_mask = before_brightness < 125
            if float(dark_field_mask.mean()) < 0.05:
                return images_changed(before_crop, after_crop, threshold=0.003)
            diff = abs(after_brightness.astype("float32") - before_brightness.astype("float32"))
            changed_in_field = int(((diff > 18) & dark_field_mask).sum())
            before_light = int(((before_brightness > 130) & dark_field_mask).sum())
            after_light = int(((after_brightness > 130) & dark_field_mask).sum())
            return bool(changed_in_field >= 20 and after_light > before_light + 8)
        except Exception:
            return images_changed(before_crop, after_crop, threshold=0.003)
