from __future__ import annotations

import re
import shutil
import subprocess as _subprocess
import threading
import time
import ctypes
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir

# 全局：所有子进程默认不弹控制台窗口（覆盖 pytesseract→tesseract.exe 等）
# 用 class 包装而非 function，避免破坏 asyncio 对 subprocess.Popen 的子类化
_original_popen = _subprocess.Popen
class _NoConsolePopen(_original_popen):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("creationflags", _subprocess.CREATE_NO_WINDOW)
        super().__init__(*args, **kwargs)
_subprocess.Popen = _NoConsolePopen

from .config import AccountConfig, AutomationSettings, app_root
from .dm_client import DmClient
from .dm_client import capture_window_image, capture_window_background, select_login_window_by_game_no

LogFn = Callable[[str], None]
StatusFn = Callable[[AccountConfig, str], None]
PassportFn = Callable[[AccountConfig], str | None]
PassportFoundFn = Callable[[AccountConfig, str], None]

_OPEN_SESSIONS: list[tuple[object, object]] = []
_OPEN_SESSIONS_LOCK = threading.Lock()


def extract_passport_from_text(text: str, regex: str) -> str | None:
    match = re.search(regex, text)
    if match:
        return match.group(1).strip()
    return None


def extract_hex_passport(text: str) -> str | None:
    """从 OCR 文本提取 8 位 hex 通行证。"""
    lowered = text.lower()
    # 原始文本中找连续8位hex
    match = re.search(r"[a-f0-9]{8}", lowered)
    if match:
        return match.group(0)
    # OCR纠错（先于去空格，避免假阳性）
    corrections = [("l", "1"), ("o", "0"), ("s", "5"), ("i", "1"), ("g", "9"), ("z", "2"), ("t", "1")]
    # OCR Unicode 符号纠错（€→c, £→e 等）
    symbol_fixes = [("€", "c"), ("¢", "c"), ("£", "e"), ("¥", "y"), ("$", "s")]
    # 尝试逐字纠错后匹配
    fixed = lowered
    for old, new in symbol_fixes + corrections:
        fixed = fixed.replace(old, new)
    match = re.search(r"[a-f0-9]{8}", fixed)
    if match:
        return match.group(0)
    # 去空格/换行后重试
    no_space = re.sub(r"\s+", "", fixed)
    match = re.search(r"[a-f0-9]{8}", no_space)
    if match:
        return match.group(0)
    return None


def _preview_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) > limit:
        return normalized[:limit] + "..."
    return normalized


def _extract_clipboard_hex(text: str) -> str | None:
    match = re.search(r"[0-9a-fA-F]{8}", text or "")
    if not match:
        return None
    return match.group(0).lower()


class AccountRunner:
    # 坐标缓存（类级别，同尺寸窗口共享）
    _cached_btn: tuple[int, int] | None = None
    _cached_btn_m2: tuple[int, int] | None = None  # 方式二独立缓存
    _cached_input: tuple[int, int] | None = None
    _cached_confirm: tuple[int, int] | None = None
    _cached_dialog_window_size: tuple[int, int] | None = None
    _dialog_coord_cache: dict[
        tuple[int, int],
        tuple[tuple[int, int], tuple[int, int], tuple[int, int]],
    ] = {}
    _cached_window_size: tuple[int, int] | None = None

    def __init__(
        self,
        account: AccountConfig,
        settings: AutomationSettings,
        stop_event: threading.Event,
        log: LogFn,
        update_status: StatusFn,
        request_passport: PassportFn | None = None,
        passport_found: PassportFoundFn | None = None,
    ) -> None:
        self.account = account
        self.settings = settings
        self.stop_event = stop_event
        self.log = log
        self.update_status = update_status
        self.request_passport = request_passport
        self.passport_found = passport_found
        self._debug_dir = app_root() / settings.qr_passport_debug_dir
        self._tmp_dir = self._debug_dir / "_tmp"
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        self._save_screenshots = (settings.log_level == "debug")
        self.last_timings: dict[str, float] = {}

    def run(self) -> bool:
        playwright = None
        browser = None
        keep_open = False
        try:
            self._ensure_not_stopped()
            self.update_status(self.account, "打开中")
            self._vlog("debug", f"[窗口{self.account.game_window_no}] 打开链接: {self.account.url}")

            # 临时恢复原始 Popen 让 asyncio 正确子类化，导入后恢复补丁
            _subprocess.Popen = _original_popen
            try:
                from playwright.sync_api import sync_playwright
            finally:
                _subprocess.Popen = _NoConsolePopen

            playwright = sync_playwright().start()
            launcher = getattr(playwright, self.settings.browser)
            x, y = self._window_position()
            browser = launcher.launch(
                headless=False,
                args=[
                    f"--window-size={self.settings.window_width},{self.settings.window_height}",
                    f"--window-position={x},{y}",
                ],
            )
            page = browser.new_page(
                viewport={
                    "width": self.settings.window_width,
                    "height": self.settings.window_height,
                }
            )
            page.goto(
                self.account.url,
                wait_until="domcontentloaded",
                timeout=self.settings.page_load_timeout_ms,
            )
            self.log(
                f"[窗口{self.account.game_window_no}] 停留二维码登录页，等待 {self.settings.qr_login_page_wait_ms}ms 后立即 OCR"
            )
            self._wait_or_stop(page,self.settings.qr_login_page_wait_ms)
            self._ensure_not_stopped()

            self.log(f"[窗口{self.account.game_window_no}] 尝试提取通行证")
            passport = self._extract_passport(page)
            if not passport and self.settings.enable_ocr_fallback:
                passport = self._extract_passport_by_ocr(page)
            if not passport and self.request_passport is not None:
                self.log(f"[窗口{self.account.game_window_no}] 通行证提取失败，进入手动确认模式")
                passport = self.request_passport(self.account)
            if not passport:
                raise RuntimeError("未能提取通行证")

            if self.passport_found is not None:
                self.passport_found(self.account, passport)
            self.update_status(self.account, "已提取通行证")
            self.log(f"[窗口{self.account.game_window_no}] 通行证提取成功: {passport}")
            self._wait_or_stop(page,self.settings.after_passport_extract_wait_ms)
            self._ensure_not_stopped()

            self.log(f"[窗口{self.account.game_window_no}] 等待游戏页面加载")
            self._wait_or_stop(page,self.settings.after_goto_wait_ms)
            if self.settings.dm_enabled:
                self._run_game_steps_with_dm(page, passport)
                keep_open = True
                _remember_open_session(playwright, browser)
                return True

            self._close_notice_by_outside_click(page)
            self.update_status(self.account, "已关闭公告")
            self._wait_or_stop(page,self.settings.after_notice_wait_ms)
            self._ensure_not_stopped()

            self.log(f"[窗口{self.account.game_window_no}] 尝试点击通行证按钮")
            self._click_target(page, self.settings.passport_button_selector, self.settings.passport_button_ratio, "通行证按钮")
            if not self._wait_state(page, self._is_passport_dialog_visible):
                self.log(f"[窗口{self.account.game_window_no}] 通行证弹窗未出现")
                raise RuntimeError("通行证弹窗未出现")
            self.log(f"[窗口{self.account.game_window_no}] 通行证弹窗已出现")
            self._wait_or_stop(page,self.settings.after_passport_button_wait_ms)
            self._ensure_not_stopped()

            self.log(f"[窗口{self.account.game_window_no}] 尝试输入通行证")
            self._fill_passport(page, passport)
            self.update_status(self.account, "已输入通行证")
            self.log(f"[窗口{self.account.game_window_no}] 输入通行证成功")
            self._ensure_not_stopped()

            self.log(f"[窗口{self.account.game_window_no}] 尝试点击确认")
            self._click_target(page, self.settings.confirm_button_selector, self.settings.confirm_button_ratio, "确认按钮")
            self._wait_or_stop(page,self.settings.after_submit_wait_ms)
            if not self._wait_state(page, self._is_login_confirmed):
                self.log(f"[窗口{self.account.game_window_no}] 确认失败")
                raise RuntimeError("确认失败，通行证弹窗仍未关闭")
            self.update_status(self.account, "成功")
            self.log(f"[窗口{self.account.game_window_no}] 确认成功，流程完成，浏览器窗口保持打开")
            keep_open = True
            _remember_open_session(playwright, browser)
            return True
        except TimeoutError as exc:
            self.update_status(self.account, "失败")
            self.log(f"[窗口{self.account.game_window_no}] 页面加载超时: {exc}")
            return False
        except InterruptedError:
            self.update_status(self.account, "失败")
            self.log(f"[窗口{self.account.game_window_no}] 任务已停止")
            return False
        except Exception as exc:
            self.update_status(self.account, "失败")
            self.log(f"[窗口{self.account.game_window_no}] 失败: {exc}")
            return False
        finally:
            if not keep_open:
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass

    def run_passport_only(self) -> bool:
        try:
            self._ensure_not_stopped()
            self.update_status(self.account, "打开中")
            self.log(f"[窗口{self.account.game_window_no}] 测试1：只截图登录程序窗口并 OCR 通行证")
            self.log(
                f"[窗口{self.account.game_window_no}] 当前账号: 层级={self.account.level}, 收藏编号={self.account.bookmark_no}, 游戏窗口号={self.account.game_window_no}"
            )
            passport, source = self._extract_passport_from_login_window()
            if not passport and self.request_passport is not None:
                self.log(f"[窗口{self.account.game_window_no}] 自动提取失败，进入手动输入")
                passport = self.request_passport(self.account)
                source = "manual"
            if not passport:
                raise RuntimeError("未能提取通行证")

            if self.passport_found is not None:
                self.passport_found(self.account, passport)
            self.update_status(self.account, "已提取通行证")
            if source == "ocr":
                self.log(f"[窗口{self.account.game_window_no}] OCR 提取成功：{passport}")
            elif source == "copy":
                self.log(f"[窗口{self.account.game_window_no}] 复制方式提取成功：{passport}")
            elif source == "manual":
                self.log(f"[窗口{self.account.game_window_no}] 手动输入通行证：{passport}")
            else:
                self.log(f"[窗口{self.account.game_window_no}] DOM 提取成功：{passport}")
            self.log(f"[窗口{self.account.game_window_no}] 测试1完成：不打开浏览器，不进入后续游戏流程")
            return True
        except InterruptedError:
            self.update_status(self.account, "失败")
            self.log(f"[窗口{self.account.game_window_no}] 任务已停止")
            return False
        except Exception as exc:
            self.update_status(self.account, "失败")
            self.log(f"[窗口{self.account.game_window_no}] 失败: {exc}")
            return False

    def run_game_flow(self, verify_after_submit: bool = True) -> bool:
        """完整单账号流程：OCR通行证 → 打开游戏页 → 关闭公告 → 输入通行证 → 确认。

        成功时关闭浏览器，失败时保留浏览器便于排查。
        通行证过期自动刷新重试（最多1次）。
        """
        playwright = None
        browser = None
        keep_open = True
        passport = None
        import time as _time
        _timings: dict[str, float] = {}

        for retry in range(2):
            _t_start = _time.perf_counter()
            _timings.clear()
            try:
                self._clean_tmp()
                # === 步骤1：OCR 提取通行证 ===
                _t0 = _time.perf_counter()
                self._ensure_not_stopped()
                self.update_status(self.account, "OCR中")
                if retry > 0:
                    self.log(f"[窗口{self.account.game_window_no}] 重试：重新OCR通行证")
                else:
                    self.log(f"[窗口{self.account.game_window_no}] 从登录程序窗口提取通行证")
                new_passport, source = self._extract_passport_from_login_window()
                if not new_passport:
                    if passport is not None:
                        # 重试时 OCR 返回空：窗口可能正处于黑屏/过渡态
                        self.log(
                            f"[窗口{self.account.game_window_no}] "
                            f"重试OCR未检测到通行证，等待后二次确认"
                        )
                        for _ in range(5):
                            self._ensure_not_stopped()
                            _time.sleep(0.1)
                        new_passport2, new_source2 = self._extract_passport_from_login_window()
                        if new_passport2 is None and new_source2 == "logged_in":
                            self.update_status(self.account, "登录成功")
                            self.log(f"[窗口{self.account.game_window_no}] 登录成功（QR码消失）")
                            keep_open = False
                            self._clean_tmp()
                            return True
                        if new_passport2 is not None:
                            new_passport = new_passport2
                            source = new_source2
                    elif retry == 0:
                        if source == "logged_in":
                            self.update_status(self.account, "已登录，跳过")
                            keep_open = False
                            self._clean_tmp()
                            return True
                        elif source in ("qr_page", "unknown"):
                            self.log(
                                f"[窗口{self.account.game_window_no}] "
                                f"页面状态={source}，OCR失败，等待后重试"
                            )
                            for _ in range(5):
                                self._ensure_not_stopped()
                                _time.sleep(0.1)
                            new_passport2, new_source2 = self._extract_passport_from_login_window()
                            if new_passport2 is not None:
                                new_passport = new_passport2
                                source = new_source2
                            # 二次OCR仍失败：走手动输入
                            if self.request_passport is not None:
                                new_passport = self.request_passport(self.account)
                    elif self.request_passport is not None:
                        new_passport = self.request_passport(self.account)
                if not new_passport:
                    if source in ("qr_page", "unknown"):
                        raise RuntimeError(f"通行证识别失败（页面状态={source}）")
                    raise RuntimeError("未能提取通行证")
                passport = new_passport
                self.log(f"[窗口{self.account.game_window_no}] 通行证: {passport} (来源={source})")
                if self.passport_found is not None:
                    self.passport_found(self.account, passport)
                self.update_status(self.account, "已提取通行证")
                self._clean_tmp()
                _timings["OCR"] = _time.perf_counter() - _t0

                # === 步骤2：打开浏览器游戏页 ===
                _t_br = _time.perf_counter()
                self._ensure_not_stopped()
                self.update_status(self.account, "打开中")
                self._vlog("debug", f"[窗口{self.account.game_window_no}] 打开链接: {self.account.url}")
                # 临时恢复原始 Popen 让 asyncio 正确子类化，导入后恢复补丁
                _subprocess.Popen = _original_popen
                try:
                    from playwright.sync_api import sync_playwright
                finally:
                    _subprocess.Popen = _NoConsolePopen
                playwright = sync_playwright().start()
                launcher = getattr(playwright, self.settings.browser)
                browser = launcher.launch(
                    headless=False,
                    args=[
                        f"--window-size={self.settings.window_width},{self.settings.window_height}",
                        "--window-position=100,100",
                    ],
                )
                page = browser.new_page(
                    viewport={"width": self.settings.window_width, "height": self.settings.window_height}
                )
                page.goto(self.account.url, wait_until="domcontentloaded", timeout=self.settings.page_load_timeout_ms)
                self.log(f"[窗口{self.account.game_window_no}] 游戏页已打开: {page.title}")
                # 轮询 canvas 出现替代固定等待（最多 2s，200ms×10）
                for _poll in range(10):
                    self._ensure_not_stopped()
                    _time.sleep(0.2)
                    try:
                        if page.locator("canvas").count() > 0:
                            break
                    except Exception:
                        pass
                self._ensure_not_stopped()
                _timings["打开页面"] = _time.perf_counter() - _t_br

                # === 步骤3：关闭公告 ===
                _t_notice = _time.perf_counter()
                self.log(f"[窗口{self.account.game_window_no}] [耗时] 关闭公告开始")
                self.update_status(self.account, "关闭公告")
                for _ in range(2):
                    page.mouse.click(740, 680)
                    self._wait_or_stop(page,100)
                self._wait_or_stop(page,200)
                self.update_status(self.account, "已关闭公告")
                self.log(f"[窗口{self.account.game_window_no}] 公告已关闭（canvas 右下角点击）")
                _t_notice_closed = _time.perf_counter()
                self.log(
                    f"[窗口{self.account.game_window_no}] [耗时] 关闭公告="
                    f"{_t_notice_closed - _t_notice:.2f}s"
                )
                self._wait_or_stop(page,self.settings.after_notice_wait_ms)
                self._ensure_not_stopped()
                _timings["关闭公告"] = _time.perf_counter() - _t_notice
                _t_after_notice_wait = _time.perf_counter()
                self.log(
                    f"[窗口{self.account.game_window_no}] [耗时] 关闭公告后等待="
                    f"{_t_after_notice_wait - _t_notice_closed:.2f}s"
                )

                # === 步骤4+5+6：按钮+输入+确认 合并为一次 Dm 子进程调用 ===
                _t_btn = _time.perf_counter()
                self._ensure_not_stopped()
                _t_locate_start = _time.perf_counter()
                self.log(
                    f"[窗口{self.account.game_window_no}] [耗时] 关闭公告结束→开始定位通行证按钮="
                    f"{_t_locate_start - _t_after_notice_wait:.2f}s"
                )
                browser_hwnd = self._find_game_browser_window()
                if browser_hwnd is None:
                    raise RuntimeError("未找到浏览器窗口")
                self._write_browser_pos(browser_hwnd)
                viewport_key = self._get_browser_viewport_size(browser_hwnd)
                viewport_label = f"{viewport_key[0]}x{viewport_key[1]}"
                self.log(f"[窗口{self.account.game_window_no}] 浏览器viewport={viewport_label}")

                # 按钮坐标
                cache_key = (self.settings.window_width, self.settings.window_height)
                dialog_coord_cache = self._load_passport_dialog_coord_cache(viewport_key)
                if dialog_coord_cache:
                    btn_pos = dialog_coord_cache[0]
                    self.log(
                        f"[窗口{self.account.game_window_no}] 使用缓存通行证按钮坐标: "
                        f"viewport={viewport_label} button={btn_pos}"
                    )
                elif AccountRunner._cached_window_size == cache_key and AccountRunner._cached_btn:
                    btn_pos = AccountRunner._cached_btn
                    self.log(f"[窗口{self.account.game_window_no}] 使用缓存按钮坐标: {btn_pos}")
                else:
                    _client = self._capture_browser_client(browser_hwnd, None)
                    btn_pos = self._locate_passport_button(_client)
                    if btn_pos:
                        AccountRunner._cached_btn = btn_pos
                        AccountRunner._cached_window_size = cache_key
                        self.log(f"[窗口{self.account.game_window_no}] 模板匹配定位按钮: {btn_pos}（已缓存）")
                    else:
                        self.log(f"[窗口{self.account.game_window_no}] 模板匹配失败，使用回退坐标")
                        btn_pos = self.settings.passport_btn_viewport
                btn_vx, btn_vy = btn_pos
                _t_locate_done = _time.perf_counter()
                self.log(
                    f"[窗口{self.account.game_window_no}] [耗时] 通行证按钮定位="
                    f"{_t_locate_done - _t_locate_start:.2f}s"
                )
                self.log(
                    f"[窗口{self.account.game_window_no}] [耗时] 定位完成→发起点击通行证按钮="
                    f"{_time.perf_counter() - _t_locate_done:.2f}s"
                )

                _t_input_done = None
                if self._click_passport_button_input_confirm_fast(
                    viewport_key,
                    btn_vx,
                    btn_vy,
                    passport,
                    "方式一",
                ):
                    _t_input_done = _time.perf_counter()
                    self.update_status(self.account, "已输入通行证")
                    self.log(f"[窗口{self.account.game_window_no}] 输入+确认完成（合并DM chain 快路径）")
                else:
                    input_x, input_y, confirm_x, confirm_y = self._click_passport_button_and_wait_dialog(
                        browser_hwnd,
                        btn_vx,
                        btn_vy,
                        "方式一",
                        viewport_key,
                    )
                    _t_dialog_ready = _time.perf_counter()

                    self.update_status(self.account, "输入中")
                    self.log(f"[窗口{self.account.game_window_no}] 输入通行证并点击确认: {passport}")
                    self.log(
                        f"[窗口{self.account.game_window_no}] [耗时] 检测到弹窗→发起输入="
                        f"{_time.perf_counter() - _t_dialog_ready:.2f}s"
                    )

                    # 弹窗已确认出现后，再执行输入+确认。
                    _t_input_chain = _time.perf_counter()
                    if not self._dm_chain(
                        [f"click,{input_x},{input_y},80",
                         f"type,{passport}",
                         f"click,{confirm_x},{confirm_y},100"],
                        "输入+确认"
                    ):
                        raise RuntimeError("Dm 输入+确认失败")
                    _t_input_done = _time.perf_counter()
                    self.log(
                        f"[窗口{self.account.game_window_no}] [耗时] 点击输入框+输入通行证+点击确认="
                        f"{_t_input_done - _t_input_chain:.2f}s"
                    )
                    self.update_status(self.account, "已输入通行证")
                    self.log(f"[窗口{self.account.game_window_no}] 输入+确认完成（Dm 合并调用）")
                self._ensure_not_stopped()
                _timings["点击按钮"] = _time.perf_counter() - _t_btn
                _timings["输入"] = 0
                _t_confirm = _time.perf_counter()
                _timings["点击确认"] = 0  # 合并到按钮计时

                if not verify_after_submit:
                    _time.sleep(0.3)
                    self.update_status(self.account, "待复核")
                    _timings["校验"] = 0
                    _timings["总计"] = _time.perf_counter() - _t_start
                    self._log_timings(_timings)
                    self.log(
                        f"[窗口{self.account.game_window_no}] 批量快速登录提交完成，"
                        "已输入并点击确认，等待统一校验"
                    )
                    keep_open = False
                    self._clean_tmp()
                    return True

                # === 步骤7：校验登录成功（轻量化：先判断 QR 是否消失） ===
                _t_verify = _time.perf_counter()
                self.log(
                    f"[窗口{self.account.game_window_no}] [耗时] 点击确认→登录校验开始="
                    f"{_t_verify - _t_input_done:.2f}s"
                )
                self.log(f"[窗口{self.account.game_window_no}] 校验登录程序窗口：检测QR页面是否消失")

                # 短轮询：200ms快速状态检测，最多10s。只有明确 logged_in 才能成功。
                verified_success = False
                login_passport_after = None
                login_source_after = ""
                last_verify_state = "unknown"
                last_verify_error = "LOGIN_VERIFY_UNKNOWN"
                _verify_deadline = _time.perf_counter() + 10.0
                _poll = 0
                while _time.perf_counter() < _verify_deadline:
                    self._ensure_not_stopped()
                    _time.sleep(0.2)
                    state = self._quick_login_state()
                    last_verify_state = state
                    if state == "qr_page":
                        last_verify_error = "LOGIN_VERIFY_UNKNOWN"
                    elif state == "unknown":
                        last_verify_error = "LOGIN_VERIFY_UNKNOWN"
                    if state == "logged_in":
                        verified_success = True
                        last_verify_error = ""
                        break
                    # 仅第5轮起每15轮（~3s）做一次完整OCR，跳过第0轮避免OCR刚跑完又跑
                    if _poll >= 5 and _poll % 15 == 0 and state == "qr_page":
                        login_passport_after, login_source_after = self._extract_passport_from_login_window()
                        if login_passport_after is not None:
                            last_verify_error = "LOGIN_VERIFY_STILL_QR"
                            self.log(
                                f"[窗口{self.account.game_window_no}] 校验仍可获取通行证: "
                                f"{login_passport_after} (来源={login_source_after})"
                            )
                        else:
                            last_verify_error = "LOGIN_VERIFY_UNKNOWN"
                            self.log(
                                f"[窗口{self.account.game_window_no}] 校验疑似二维码页，"
                                "但未能获取通行证，继续等待复查"
                            )
                        if login_passport_after is not None and login_passport_after != passport:
                            break
                    _poll += 1

                if verified_success:
                    self.update_status(self.account, "成功")
                    _timings["校验"] = _time.perf_counter() - _t_verify
                    _timings["总计"] = _time.perf_counter() - _t_start
                    self._log_timings(_timings)
                    self.log(f"[窗口{self.account.game_window_no}] 登录成功（QR码消失）")
                    keep_open = False
                    self._clean_tmp()
                    return True

                if login_passport_after is None:
                    self.log(
                        f"[窗口{self.account.game_window_no}] 登录校验未通过："
                        f"state={last_verify_state}，失败类型={last_verify_error}"
                    )

                # QR页面仍存在 → 检查通行证是否刷新
                self._ensure_not_stopped()
                if login_passport_after is not None and login_passport_after != passport and retry == 0:
                    self.log(
                        f"[窗口{self.account.game_window_no}] 通行证已刷新: "
                        f"{passport} → {login_passport_after}，重试"
                    )
                    self._cleanup_for_retry(browser, playwright)
                    browser = None
                    playwright = None
                    continue  # 重新OCR+登录

                # QR页面仍存在且通行证相同 → 登录未完成，重试整流程
                self._ensure_not_stopped()
                if retry == 0:
                    if login_passport_after is not None:
                        self.log(
                            f"[窗口{self.account.game_window_no}] 校验超时QR仍存在且通行证未变，重试整流程"
                        )
                    else:
                        self.log(
                            f"[窗口{self.account.game_window_no}] 校验超时仍无法确认登录状态，重试整流程"
                        )
                    self._cleanup_for_retry(browser, playwright)
                    browser = None
                    playwright = None
                    continue
                if login_passport_after is not None:
                    raise RuntimeError("校验超时，QR页面未消失")
                raise RuntimeError("登录校验状态不确定")

            except TimeoutError as exc:
                self.update_status(self.account, "失败")
                self.log(f"[窗口{self.account.game_window_no}] 超时: {exc}")
                self._save_error_snapshots()
                if retry == 0:
                    self.update_status(self.account, "重试")
                    self._cleanup_for_retry(browser, playwright)
                    browser = None
                    playwright = None
                    continue
                break
            except InterruptedError:
                self.update_status(self.account, "失败")
                self.log(f"[窗口{self.account.game_window_no}] 已停止")
                self._save_error_snapshots()
                break
            except Exception as exc:
                self.update_status(self.account, "失败")
                self.log(f"[窗口{self.account.game_window_no}] 失败: {exc}")
                self._save_error_snapshots()
                if retry == 0:
                    self.update_status(self.account, "重试")
                    self._cleanup_for_retry(browser, playwright)
                    browser = None
                    playwright = None
                    continue
                break
            finally:
                if not keep_open:
                    if browser is not None:
                        try: browser.close()
                        except Exception: pass
                    if playwright is not None:
                        try: playwright.stop()
                        except Exception: pass
        self._clean_tmp()
        return False

    def run_game_flow_fast_submit(self) -> bool:
        """批量模式：只执行到输入通行证并点击确认，不做完整登录校验。"""
        return self.run_game_flow(verify_after_submit=False)

    def verify_login_result(self) -> str:
        """统一校验阶段：只读取登录窗口状态，不放宽成功规则。"""
        self._ensure_not_stopped()
        self.update_status(self.account, "校验中")
        self.log(f"[窗口{self.account.game_window_no}] 统一校验：检测登录程序窗口状态")
        try:
            state = self._quick_login_state()
        except Exception as exc:
            self.log(
                f"[窗口{self.account.game_window_no}] 统一校验截图/状态检测失败: {exc}"
            )
            return "screenshot_failed"
        if state == "logged_in":
            self.log(f"[窗口{self.account.game_window_no}] 统一校验结果: logged_in")
            return "logged_in"
        if state == "qr_page":
            self.log(f"[窗口{self.account.game_window_no}] 统一校验结果: qr_page，需要重登")
            return "qr_page"
        self.log(f"[窗口{self.account.game_window_no}] 统一校验结果: unknown，需要重登")
        return "unknown"

    # ===== 方式二：账号密码 + 通行证上号 =====

    def run_method2(self, csv_account) -> bool:
        """方式二入口：账号密码登录 + 通行证上号。"""
        from .config import AccountConfig
        import time as _time
        _timings: dict[str, float] = {}
        _saved_account = self.account
        self.account = AccountConfig(
            level="方式二", bookmark_no=0,
            game_window_no=csv_account.game_window_no, url=csv_account.url
        )

        for retry in range(2):
            _t_start = _time.perf_counter()
            _timings.clear()
            playwright = None
            browser = None
            try:
                # === 步骤1：OCR 提取通行证 ===
                _t0 = _time.perf_counter()
                self._ensure_not_stopped()
                self.update_status(self.account, "OCR中")
                self.log(f"[方式二] 从登录程序窗口提取通行证 (窗口{csv_account.game_window_no})")
                passport, source = self._extract_passport_from_login_window()
                if not passport:
                    if source == "logged_in":
                        self.update_status(self.account, "已登录，跳过")
                        self.log("[方式二] 检测到已登录界面，跳过")
                        _timings["总计"] = _time.perf_counter() - _t_start
                        self._log_timings(_timings)
                        return True
                    # 二次确认
                    time.sleep(0.5)
                    passport2, source2 = self._extract_passport_from_login_window()
                    if passport2:
                        passport = passport2
                        source = source2
                    elif source2 == "logged_in":
                        self.update_status(self.account, "已登录，跳过")
                        _timings["总计"] = _time.perf_counter() - _t_start
                        self._log_timings(_timings)
                        return True
                if not passport:
                    raise RuntimeError(f"通行证识别失败（页面状态={source}）")
                _timings["OCR"] = _time.perf_counter() - _t0
                self.log(f"[方式二] 通行证: {passport} (来源={source})")
                self.update_status(self.account, "已提取通行证")

                # === 步骤2：打开浏览器 + 账号密码登录 ===
                _t1 = _time.perf_counter()
                self.update_status(self.account, "打开中")
                self.log(f"[方式二] 打开链接: {csv_account.url}")
                _subprocess.Popen = _original_popen
                try:
                    from playwright.sync_api import sync_playwright
                finally:
                    _subprocess.Popen = _NoConsolePopen

                playwright = sync_playwright().start()
                launcher = getattr(playwright, self.settings.browser)
                browser = launcher.launch(
                    headless=False,
                    args=[
                        f"--window-size={self.settings.window_width},{self.settings.window_height}",
                        "--window-position=100,100",
                    ],
                )
                page = browser.new_page(
                    viewport={"width": self.settings.window_width, "height": self.settings.window_height}
                )
                page.goto(csv_account.url, wait_until="domcontentloaded", timeout=self.settings.page_load_timeout_ms)
                self.log(f"[方式二] 页面已打开: {page.title}")

                if not self._detect_login_form(page):
                    raise RuntimeError("未检测到账号密码登录界面")
                self.update_status(self.account, "输入中")
                self._fill_and_submit_login(page, csv_account.username, csv_account.password)
                self.log(f"[方式二] 账号密码已提交 (username={csv_account.username}, password=已填写)")

                if not self._wait_game_page_ready(page):
                    raise RuntimeError("登录后未进入正式游戏页")
                self.log("[方式二] 已进入游戏页面")
                _timings["打开页面"] = _time.perf_counter() - _t1

                # === 步骤3：关闭公告（多点几次确保公告消失） ===
                _t2 = _time.perf_counter()
                self.update_status(self.account, "关闭公告")
                self._close_m2_notice(page)
                self.update_status(self.account, "已关闭公告")
                self.log("[方式二] 公告已关闭")
                _timings["关闭公告"] = _time.perf_counter() - _t2
                self._wait_or_stop(page, self.settings.after_notice_wait_ms)
                self._ensure_not_stopped()

                # === 步骤4+5+6：按钮+输入+确认（方式二独立模板匹配，不套用方式一坐标） ===
                _t_btn = _time.perf_counter()
                browser_hwnd = self._find_game_browser_window()
                if browser_hwnd is None:
                    raise RuntimeError("未找到浏览器窗口")
                self._write_browser_pos(browser_hwnd)

                cache_key = (self.settings.window_width, self.settings.window_height)
                # 方式二通行证按钮位置不同，必须独立模板匹配
                if AccountRunner._cached_window_size == cache_key and AccountRunner._cached_btn_m2:
                    btn_pos = AccountRunner._cached_btn_m2
                    self.log(f"[方式二] 使用方式二缓存按钮坐标: {btn_pos}")
                else:
                    _client = self._capture_browser_client(browser_hwnd, "m2_button_match.png")
                    # 保存方式二浏览器截图供手动分析（不清理）
                    try:
                        _ref_path = self._debug_dir / "m2_browser_screenshot.png"
                        _client.save(str(_ref_path))
                        self.log(f"[方式二] 浏览器截图已保存: {_ref_path}")
                    except Exception:
                        pass
                    if self._m2_notice_overlay_visible(_client):
                        raise RuntimeError("方式二公告仍未关闭，停止定位通行证按钮")
                    btn_pos = self._locate_passport_button(_client, use_fallback=False)
                    if btn_pos:
                        AccountRunner._cached_btn_m2 = btn_pos
                        AccountRunner._cached_window_size = cache_key
                        self.log(f"[方式二] 模板匹配定位按钮: {btn_pos}（已缓存到方式二）")
                    else:
                        raise RuntimeError("方式二通行证按钮模板匹配失败，请检查模板文件")
                btn_vx, btn_vy = btn_pos

                input_x, input_y, confirm_x, confirm_y = self._click_passport_button_and_wait_dialog(
                    browser_hwnd,
                    btn_vx,
                    btn_vy,
                    "方式二",
                )

                self.update_status(self.account, "输入中")
                self.log(f"[方式二] 输入通行证并点击确认: {passport}")
                if not self._dm_chain(
                    [f"click,{input_x},{input_y},80",
                     f"type,{passport}",
                     f"click,{confirm_x},{confirm_y},100"],
                    "输入+确认"
                ):
                    raise RuntimeError("Dm 输入+确认失败")
                self.update_status(self.account, "已输入通行证")
                self.log("[方式二] 输入+确认完成（Dm 合并调用）")
                _timings["点击按钮"] = _time.perf_counter() - _t_btn

                # === 步骤7：校验 ===
                _t_verify = _time.perf_counter()
                self.log("[方式二] 校验登录程序窗口：检测QR页面是否消失")
                verified_success = False
                _verify_deadline = time.perf_counter() + 10.0
                _poll = 0
                while time.perf_counter() < _verify_deadline:
                    self._ensure_not_stopped()
                    time.sleep(0.2)
                    state = self._quick_login_state()
                    if state == "logged_in":
                        verified_success = True
                        break
                    if _poll >= 5 and _poll % 15 == 0 and state == "qr_page":
                        p_after, _ = self._extract_passport_from_login_window()
                        if p_after is not None and p_after != passport:
                            break
                    _poll += 1

                if verified_success:
                    self.update_status(self.account, "成功")
                    _timings["校验"] = _time.perf_counter() - _t_verify
                    _timings["总计"] = _time.perf_counter() - _t_start
                    self._log_timings(_timings)
                    self.log("[方式二] 登录成功（QR码消失）")
                    self._clean_tmp()
                    return True
                if retry == 0:
                    self.log("[方式二] 校验超时QR未消失，重试整流程")
                    self._clean_tmp()
                    continue
                raise RuntimeError("校验超时，QR页面未消失")

            except Exception as exc:
                self.update_status(self.account, "失败")
                self.log(f"[方式二] 失败: {exc}")
                self._save_error_snapshots()
                if retry == 0:
                    self.log("[方式二] 异常，重试整流程")
                    continue
                self.last_timings = {}
                return False
            finally:
                self.account = _saved_account
                if browser is not None:
                    time.sleep(2)
                    try:
                        browser.close()
                    except Exception:
                        pass
                if playwright is not None:
                    try:
                        playwright.stop()
                    except Exception:
                        pass

        self.last_timings = {}
        return False

    def _detect_login_form(self, page) -> bool:
        """检测页面是否包含账号密码登录表单。返回 True/False。"""
        import time as _time
        deadline = _time.perf_counter() + 15
        while _time.perf_counter() < deadline:
            self._ensure_not_stopped()
            try:
                # 至少有一个 password 输入框才算登录表单
                pwd_count = page.locator("input[type=password]").count()
                if pwd_count > 0:
                    return True
                # 也尝试常见的选择器
                if page.locator("input[name=password]").count() > 0:
                    return True
            except Exception:
                pass
            _time.sleep(0.5)
        return False

    def _fill_and_submit_login(self, page, username: str, password: str) -> None:
        """填写登录表单并提交。password 仅内存使用，不打印日志。

        页面结构：白色面板，placeholder"账号"/"密码"，右侧橙色"立即登录"按钮。
        """
        import time as _time

        # 1. 定位账号输入框（placeholder="账号" 或页面第一个可见文本input）
        username_input = None
        try:
            username_input = page.get_by_placeholder("账号").first
        except Exception:
            pass
        if username_input is None:
            try:
                username_input = page.locator("input:visible").first
            except Exception:
                pass
        if username_input is None:
            raise RuntimeError("账号输入框未找到")
        username_input.click()
        _time.sleep(0.15)
        username_input.fill(username)
        self.log(f"[方式二] 账号已输入 (username={username})")

        # 2. 定位密码输入框（placeholder="密码" 或 input[type=password]）
        password_input = None
        try:
            password_input = page.get_by_placeholder("密码").first
        except Exception:
            pass
        if password_input is None:
            try:
                password_input = page.locator("input[type=password]").first
            except Exception:
                pass
        if password_input is None:
            raise RuntimeError("密码输入框未找到")
        password_input.click()
        _time.sleep(0.15)
        password_input.fill(password)
        self.log("[方式二] 密码已输入 (password=已填写)")

        # 3. 点击"立即登录"按钮（右侧橙色按钮，不要点"手机注册"）
        _time.sleep(0.2)
        login_btn = None
        # 优先精确匹配"立即登录"文本
        try:
            login_btn = page.get_by_text("立即登录", exact=True).first
        except Exception:
            pass
        if login_btn is None:
            # 备选：包含"登录"但不包含"注册"的按钮
            try:
                buttons = page.locator("button, a, span, div")
                count = buttons.count()
                for i in range(min(count, 50)):
                    btn = buttons.nth(i)
                    try:
                        text = (btn.inner_text() or "").strip()
                    except Exception:
                        continue
                    if "立即登录" in text and "注册" not in text:
                        login_btn = btn
                        break
            except Exception:
                pass
        if login_btn is None:
            raise RuntimeError("未找到\"立即登录\"按钮")
        login_btn.click()
        self.log("[方式二] 已点击\"立即登录\"")

    def _wait_game_page_ready(self, page) -> bool:
        """等待登录成功后进入正式游戏页。返回 True/False。"""
        import time as _time
        deadline = _time.perf_counter() + 30
        while _time.perf_counter() < deadline:
            self._ensure_not_stopped()
            try:
                # 检测游戏 canvas 或页面变化
                if page.locator("canvas").count() > 0:
                    return True
                # URL 不再包含 login 字样
                url = page.url
                if "login" not in url.lower():
                    return True
            except Exception:
                pass
            _time.sleep(0.5)
        return False

    _LOG_LEVELS = {"quiet": 0, "normal": 1, "debug": 2}

    def _vlog(self, level: str, msg: str) -> None:
        if self._LOG_LEVELS.get(level, 1) <= self._LOG_LEVELS.get(self.settings.log_level, 1):
            self.log(msg)

    @staticmethod
    def _generate_passport_candidates(passport: str) -> list[str]:
        """OCR 常见混淆字符的候选替换。最多返回 3 个。"""
        swaps = {
            "c": "e", "e": "c",
            "0": ["o", "c", "a"], "o": "0", "c": ["e", "0"], "a": "0",
            "1": "l", "l": "1",
            "5": "s", "s": "5",
            "7": "f", "f": ["7", "4"],
            "8": "b", "6": "b", "b": ["8", "6"],
            "4": "f",
        }
        candidates = []
        for i, ch in enumerate(passport):
            repl = swaps.get(ch)
            if not repl:
                continue
            if isinstance(repl, str):
                candidates.append(passport[:i] + repl + passport[i + 1:])
            else:
                for r in repl:
                    candidates.append(passport[:i] + r + passport[i + 1:])
            if len(candidates) >= 3:
                break
        return candidates[:3]

    def _log_timings(self, timings: dict) -> None:
        self.last_timings = dict(timings)
        parts = [f"[窗口{self.account.game_window_no}] 耗时统计: "]
        for k, v in timings.items():
            parts.append(f"{k}={v:.1f}s")
        self.log(" ".join(parts))

    @staticmethod
    def _cleanup_for_retry(browser, playwright) -> None:
        import subprocess as _sp
        import gc as _gc
        import time as _t2
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)
        _sp.run(["taskkill", "/f", "/im", "chrome.exe"], capture_output=True, creationflags=_sp.CREATE_NO_WINDOW)
        _t2.sleep(2)
        _gc.collect()

    def _tmp_path(self, name: str) -> Path:
        return self._tmp_dir / name

    def _clean_tmp(self) -> None:
        """清理 _tmp/ 目录下所有临时截图"""
        if not self._tmp_dir.exists():
            return
        for f in self._tmp_dir.iterdir():
            try:
                f.unlink()
                self._vlog("debug", f"[窗口{self.account.game_window_no}] 删除临时截图: {f.name}")
            except Exception:
                pass

    def _save_error_snapshots(self) -> Path | None:
        """失败时移动 _tmp/ 内容到 _error/，保留排查现场，仅保留最新10个文件"""
        files = list(self._tmp_dir.iterdir())
        if not files:
            return None
        error_dir = self._debug_dir / "_error"
        error_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            try:
                shutil.move(str(f), str(error_dir / f.name))
            except Exception:
                pass
        # 清理旧截图，仅保留最新10个文件
        all_error_files = sorted(
            error_dir.iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in all_error_files[10:]:
            try:
                old.unlink()
            except Exception:
                pass
        self.log(
            f"[窗口{self.account.game_window_no}] 失败现场已保留: _error/ ({len(files)} 个文件)"
        )
        return error_dir

    def _save_latest_ocr_success(self, image) -> None:
        """保存最新 OCR 成功截图到 debug_ocr/latest_ocr_success.png"""
        try:
            latest = self._debug_dir / "latest_ocr_success.png"
            image.save(latest)
        except Exception:
            pass

    def _window_position(self) -> tuple[int, int]:
        index = self.account.game_window_no - 1
        column = index % self.settings.columns
        row = index // self.settings.columns
        x = column * (self.settings.window_width + self.settings.gap_x)
        y = row * (self.settings.window_height + self.settings.gap_y)
        return x, y

    def _click_ratio(self, page, ratio: tuple[float, float], action_name: str) -> None:
        width = self.settings.window_width
        height = self.settings.window_height
        x = int(width * ratio[0])
        y = int(height * ratio[1])
        self.log(f"[窗口{self.account.game_window_no}] {action_name} viewport 坐标: ({x}, {y})")
        page.mouse.click(x, y)

    def _ensure_not_stopped(self) -> None:
        if self.stop_event.is_set():
            raise InterruptedError()

    def _wait_or_stop(self, page, ms: int) -> None:
        """可中断等待：每 200ms 检查一次停止事件"""
        while ms > 0:
            self._ensure_not_stopped()
            chunk = min(200, ms)
            page.wait_for_timeout(chunk)
            ms -= chunk

    def _extract_passport(self, page) -> str | None:
        deadline_ms = self.settings.passport_extract_timeout_ms
        step_ms = 500
        waited_ms = 0
        self.log(f"[窗口{self.account.game_window_no}] 从页面可见文本提取本次通行证")
        while waited_ms <= deadline_ms:
            self._ensure_not_stopped()
            text = self._all_visible_text(page)
            passport = extract_passport_from_text(text, self.settings.passport_regex)
            if passport:
                return passport
            self._wait_or_stop(page,step_ms)
            waited_ms += step_ms
        return None

    def _extract_passport_by_ocr(self, page) -> str | None:
        try:
            import pytesseract
            from PIL import Image
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] OCR 依赖不可用，跳过识别: {exc}")
            return None

        left, top, right, bottom = self.settings.passport_ocr_region_ratio
        clip = {
            "x": int(self.settings.window_width * left),
            "y": int(self.settings.window_height * top),
            "width": int(self.settings.window_width * (right - left)),
            "height": int(self.settings.window_height * (bottom - top)),
        }
        screenshot_path = Path(gettempdir()) / f"douluo_passport_{self.account.game_window_no}.png"
        self.log(f"[窗口{self.account.game_window_no}] DOM 未提取到通行证，尝试 OCR 区域截图")
        page.screenshot(path=str(screenshot_path), clip=clip)
        text = pytesseract.image_to_string(Image.open(screenshot_path), lang="chi_sim+eng")
        return extract_passport_from_text(text, self.settings.passport_regex)

    def _extract_passport_strict(self, page) -> tuple[str | None, str]:
        self.log(f"[窗口{self.account.game_window_no}] 已确认页面为 canvas 渲染，跳过 DOM/frame 读取")
        self.log(f"[窗口{self.account.game_window_no}] 开始二维码定位 + 通行证区域 OCR")
        passport = self._extract_passport_by_qr_region_ocr(page)
        if passport:
            return passport, "ocr"
        return None, ""

    def _extract_passport_from_login_window(self) -> tuple[str | None, str]:
        self.log(
            f"[窗口{self.account.game_window_no}] 根据游戏窗口号定位登录程序窗口: 目标标题应匹配 H5-{self.account.game_window_no}"
        )
        selected, candidates = select_login_window_by_game_no(self.account.game_window_no)
        self._vlog("debug", f"[窗口{self.account.game_window_no}] 可见候选窗口数量: {len(candidates)}")
        for index, window in enumerate(candidates):
            marker = " <- 选中登录程序窗口" if selected and window.hwnd == selected.hwnd else ""
            self._vlog("debug",
                f"[窗口{self.account.game_window_no}] candidate[{index}] hwnd={window.hwnd} title={window.title} class={window.class_name} pid={window.pid} rect=({window.left},{window.top},{window.right},{window.bottom}) size={window.width}x{window.height}{marker}"
            )
        if selected is None:
            self.log(f"[窗口{self.account.game_window_no}] 未能定位登录程序窗口{self.account.game_window_no}，停止 OCR")
            self.log(f"[窗口{self.account.game_window_no}] 请确认登录程序窗口标题类似：斗罗大陆H5-{self.account.game_window_no}-伊导科技")
            return None, ""

        front_ok = self._force_foreground_window(selected.hwnd)
        self.log(
            f"[窗口{self.account.game_window_no}] 提取通行证前置顶登录窗口 "
            f"hwnd={selected.hwnd} 结果={'成功' if front_ok else '未确认'}"
        )
        time.sleep(0.12)

        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        prefix = f"login_hwnd{selected.hwnd}_{stamp}"
        raw_path = self._tmp_path(f"{prefix}_01_login_window_full.png")
        image = capture_window_background(selected).convert("RGB")
        image.save(raw_path)
        self._vlog("debug", f"[窗口{self.account.game_window_no}] 后台截图 hwnd={selected.hwnd} title={selected.title}")
        self._vlog("debug", f"[窗口{self.account.game_window_no}] 临时截图已保存: _tmp/{raw_path.name}")

        # === 图像状态判断（不用Tesseract，不依赖OCR） ===
        state, metrics = self.detect_login_page_state(image)
        self.log(
            f"(black={metrics['black_ratio']}, edge={metrics['edge_density']}, var={metrics['local_variance']})"
        )

        if state == "logged_in":
            passport_evidence = self._has_passport_page_evidence(image)
            if not passport_evidence:
                self.log(f"[窗口{self.account.game_window_no}] 检测到已登录界面，跳过")
                return None, "logged_in"
            self.log(
                f"[窗口{self.account.game_window_no}] 状态初判为已登录，"
                "但仍检测到二维码/通行证横条证据，改按二维码页继续获取通行证"
            )
            state = "qr_page"

        if state == "qr_page" or metrics.get("qr_suspected"):
            if state == "qr_page":
                self.log(f"[窗口{self.account.game_window_no}] 检测到二维码登录界面")
            else:
                self.log(
                    f"[窗口{self.account.game_window_no}] 疑似二维码登录界面，"
                    "需要通过通行证证据确认"
                )
            copied_passport, copy_error = self._copy_passport_from_login_window(selected, image)
            if copied_passport:
                self.log(f"[窗口{self.account.game_window_no}] 复制方式获取通行证成功，采用复制结果")
                return copied_passport, "copy"
            self.log(
                f"[窗口{self.account.game_window_no}] 复制方式获取通行证失败，失败类型={copy_error}，进入 OCR 兜底"
            )
            passport = self._ocr_passport_from_text_region(image, prefix, raw_path)
            if passport:
                return passport, "ocr"
            # 文字区域失败 → 模板匹配（对 hex 字符区分度优于 Tesseract）
            passport = self._ocr_passport_by_template_match(image)
            if passport and len(passport) >= 8:
                self.log(f"[窗口{self.account.game_window_no}] 模板匹配结果: {passport}")
                return passport, "ocr"
            # 回退全图OCR
            passport = self._ocr_passport_from_login_image(image, prefix, raw_path)
            if passport:
                return passport, "ocr"
            self.log(
                f"[窗口{self.account.game_window_no}] 疑似二维码登录界面，"
                "但未能识别通行证，返回 unknown 等待复查"
            )
            return None, "unknown"

        self.log(
            f"[窗口{self.account.game_window_no}] 登录窗口状态不确定，"
            "不按已登录处理，失败类型=LOGIN_VERIFY_UNKNOWN"
        )
        return None, "unknown"

    def _copy_passport_from_login_window(self, window, image) -> tuple[str | None, str]:
        self.log(f"[窗口{self.account.game_window_no}] 开始复制方式获取通行证")
        self.log(
            f"[窗口{self.account.game_window_no}] 登录窗口 hwnd={window.hwnd} "
            f"标题={window.title} size={window.width}x{window.height}"
        )

        original_ok, original_text = self._read_clipboard_text()
        if not self._set_clipboard_text(""):
            self.log(f"[窗口{self.account.game_window_no}] 剪贴板预清空失败，仍继续尝试复制")

        try:
            copy_region = self._passport_copy_screen_region(window, image)
            click_x = copy_region["click_x"]
            click_y = copy_region["click_y"]
            drag_start_x = copy_region["drag_start_x"]
            drag_end_x = copy_region["drag_end_x"]
            drag_y = copy_region["drag_y"]
            bar_box = copy_region.get("bar_box")
            self.log(
                f"[窗口{self.account.game_window_no}] 通行证复制区域 source={copy_region['source']} "
                f"bar_box={bar_box} 双击坐标=({click_x}, {click_y}) "
                f"拖选=({drag_start_x}, {drag_y})→({drag_end_x}, {drag_y})"
            )
            if not self._activate_and_copy_at(window.hwnd, click_x, click_y):
                self.log(f"[窗口{self.account.game_window_no}] 窗口激活校验失败，失败类型=COPY_WINDOW_NOT_ACTIVE，仍继续读取剪贴板")
            clipboard_ok, clipboard_text = self._wait_for_clipboard_text(timeout_seconds=1.2)
            if not clipboard_ok:
                self.log(f"[窗口{self.account.game_window_no}] 剪贴板读取失败")
                return None, "COPY_CLIPBOARD_TIMEOUT"

            text_length = len(clipboard_text or "")
            self.log(
                f"[窗口{self.account.game_window_no}] 剪贴板文本长度: {text_length} "
                f"摘要={_preview_text(clipboard_text or '', 40)}"
            )
            if not clipboard_text:
                self.log(f"[窗口{self.account.game_window_no}] 双击复制为空，尝试拖选复制")
                self._set_clipboard_text("")
                if not self._drag_select_and_copy(window.hwnd, drag_start_x, drag_y, drag_end_x):
                    self.log(f"[窗口{self.account.game_window_no}] 拖选时窗口激活校验失败，失败类型=COPY_WINDOW_NOT_ACTIVE，仍继续读取剪贴板")
                clipboard_ok, clipboard_text = self._wait_for_clipboard_text(timeout_seconds=1.5)
                if not clipboard_ok:
                    self.log(f"[窗口{self.account.game_window_no}] 拖选后剪贴板读取失败")
                    return None, "COPY_CLIPBOARD_TIMEOUT"
                text_length = len(clipboard_text or "")
                self.log(
                    f"[窗口{self.account.game_window_no}] 拖选后剪贴板文本长度: {text_length} "
                    f"摘要={_preview_text(clipboard_text or '', 40)}"
                )
                if not clipboard_text:
                    return None, "COPY_EMPTY"

            passport = _extract_clipboard_hex(clipboard_text)
            if not passport:
                preview = _preview_text(clipboard_text, 80)
                self.log(f"[窗口{self.account.game_window_no}] 剪贴板未提取到 8 位 hex: {preview}")
                return None, "COPY_NO_HEX"

            self.log(f"[窗口{self.account.game_window_no}] 提取到的 8 位通行证: {passport}")
            if len(passport) != 8:
                return None, "COPY_NO_HEX"
            return passport, ""
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] 复制方式异常: {exc}")
            return None, "COPY_FAILED"
        finally:
            if original_ok and original_text is not None:
                if not self._set_clipboard_text(original_text):
                    self.log(f"[窗口{self.account.game_window_no}] 原剪贴板文本恢复失败")
            else:
                self.log(f"[窗口{self.account.game_window_no}] 原剪贴板无可恢复文本，已跳过恢复")

    def _passport_copy_screen_region(self, window, image) -> dict:
        source = "red_bar"
        bar_box = None
        qr_box = self._detect_opencv_qr_box(image)
        if qr_box is not None:
            bar_box = self._find_red_bar_below_qr(image, qr_box)
            if bar_box is not None:
                source = "qr_red_bar"

        if bar_box is None:
            bar_box = self._locate_passport_copy_bar(image)

        if bar_box is not None:
            left, top, right, bottom = bar_box
            local_x = left + int((right - left) * 0.68)
            local_y = top + (bottom - top) // 2
            drag_start_x = window.left + left + int((right - left) * 0.42)
            drag_end_x = window.left + left + int((right - left) * 0.96)
            self.log(
                f"[窗口{self.account.game_window_no}] 复制定位通行证横条: "
                f"box=({left},{top},{right},{bottom}) source={source}"
            )
            return {
                "click_x": window.left + local_x,
                "click_y": window.top + local_y,
                "drag_start_x": drag_start_x,
                "drag_end_x": drag_end_x,
                "drag_y": window.top + local_y,
                "bar_box": (left, top, right, bottom),
                "source": source,
            }

        _crop, bbox = self._crop_passport_hex_region(image)
        if bbox is not None:
            left, top, right, bottom = bbox
            local_x = left + int((right - left) * 0.68)
            local_y = top + (bottom - top) // 2
            drag_start_x = window.left + left + int((right - left) * 0.40)
            drag_end_x = window.left + left + int((right - left) * 0.95)
            return {
                "click_x": window.left + local_x,
                "click_y": window.top + local_y,
                "drag_start_x": drag_start_x,
                "drag_end_x": drag_end_x,
                "drag_y": window.top + local_y,
                "bar_box": (left, top, right, bottom),
                "source": "ocr_crop",
            }

        local_x = int(window.width * 0.66)
        local_y = int(window.height * 0.74)
        drag_start_x = window.left + int(window.width * 0.48)
        drag_end_x = window.left + int(window.width * 0.92)
        return {
            "click_x": window.left + local_x,
            "click_y": window.top + local_y,
            "drag_start_x": drag_start_x,
            "drag_end_x": drag_end_x,
            "drag_y": window.top + local_y,
            "bar_box": None,
            "source": "ratio_fallback",
        }

    def _has_passport_page_evidence(self, image) -> bool:
        """判断截图是否仍像二维码通行证页，防止大窗口被误判为已登录。"""
        qr_box = self._detect_opencv_qr_box(image)
        if qr_box is not None:
            self.log(
                f"[窗口{self.account.game_window_no}] 已登录初判复核：仍检测到 OpenCV QR box={qr_box}"
            )
            return True

        fallback_qr = self._locate_qr_box_fallback(image)
        if fallback_qr is not None:
            red_bar = self._find_red_bar_below_qr(image, fallback_qr)
            if red_bar is not None:
                self.log(
                    f"[窗口{self.account.game_window_no}] 已登录初判复核："
                    f"回退QR候选={fallback_qr} 且下方存在通行证横条={red_bar}"
                )
                return True

        bar_box = self._locate_passport_copy_bar(image)
        if bar_box is not None:
            self.log(
                f"[窗口{self.account.game_window_no}] 已登录初判复核：仍检测到通行证横条={bar_box}"
            )
            return True
        return False

    @staticmethod
    def _locate_passport_copy_bar(image) -> tuple[int, int, int, int] | None:
        import numpy as np

        arr = np.array(image.convert("RGB"))
        height, width = arr.shape[:2]
        r_arr = arr[:, :, 0].astype(int)
        g_arr = arr[:, :, 1].astype(int)
        b_arr = arr[:, :, 2].astype(int)

        reddish = (
            (r_arr > 70)
            & (r_arr > g_arr + 10)
            & (r_arr > b_arr + 5)
            & (g_arr < 140)
            & (b_arr < 140)
        )
        dark_reddish = (
            (r_arr > 55)
            & (r_arr > g_arr + 8)
            & (r_arr > b_arr + 5)
            & (g_arr < 120)
            & (b_arr < 120)
        )
        row_ratio = (reddish | dark_reddish).mean(axis=1)

        search_start = int(height * 0.80)
        search_end = int(height * 0.94)
        best_score = 0.0
        best_box = None
        streak_start = None

        for y in range(search_start, search_end):
            if row_ratio[y] >= 0.16:
                if streak_start is None:
                    streak_start = y
            elif streak_start is not None:
                top = streak_start
                bottom = y
                streak_start = None
                if bottom - top < 6:
                    continue
                lower_weight = 1.0 + (top / max(height, 1)) * 0.35
                score = float(row_ratio[top:bottom].mean()) * (bottom - top) * lower_weight
                if score > best_score:
                    best_score = score
                    best_box = (int(width * 0.06), top, int(width * 0.94), bottom)

        if streak_start is not None:
            top = streak_start
            bottom = search_end
            if bottom - top >= 6:
                lower_weight = 1.0 + (top / max(height, 1)) * 0.35
                score = float(row_ratio[top:bottom].mean()) * (bottom - top) * lower_weight
                if score > best_score:
                    best_box = (int(width * 0.06), top, int(width * 0.94), bottom)

        if best_box is None:
            return None

        left, top, right, bottom = best_box
        if bottom - top < 24:
            bottom = min(height, top + 42)
        return left, top, right, bottom

    def _activate_and_copy_at(self, hwnd: int, x: int, y: int) -> bool:
        user32 = ctypes.windll.user32
        is_active = self._force_foreground_window(hwnd)
        time.sleep(0.12)

        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        left_down = 0x0002
        left_up = 0x0004
        for _ in range(2):
            user32.mouse_event(left_down, 0, 0, 0, 0)
            time.sleep(0.04)
            user32.mouse_event(left_up, 0, 0, 0, 0)
            time.sleep(0.05)

        vk_control = 0x11
        vk_c = 0x43
        keyeventf_keyup = 0x0002
        time.sleep(0.08)
        user32.keybd_event(vk_control, 0, 0, 0)
        user32.keybd_event(vk_c, 0, 0, 0)
        time.sleep(0.04)
        user32.keybd_event(vk_c, 0, keyeventf_keyup, 0)
        user32.keybd_event(vk_control, 0, keyeventf_keyup, 0)
        return bool(is_active)

    def _drag_select_and_copy(self, hwnd: int, start_x: int, y: int, end_x: int) -> bool:
        user32 = ctypes.windll.user32
        is_active = self._force_foreground_window(hwnd)
        time.sleep(0.12)

        left_down = 0x0002
        left_up = 0x0004
        user32.SetCursorPos(int(start_x), int(y))
        time.sleep(0.08)
        user32.mouse_event(left_down, 0, 0, 0, 0)
        time.sleep(0.08)
        step = 8 if end_x >= start_x else -8
        for x in range(int(start_x), int(end_x), step):
            user32.SetCursorPos(x, int(y))
            time.sleep(0.01)
        user32.SetCursorPos(int(end_x), int(y))
        time.sleep(0.08)
        user32.mouse_event(left_up, 0, 0, 0, 0)

        vk_control = 0x11
        vk_c = 0x43
        keyeventf_keyup = 0x0002
        time.sleep(0.12)
        user32.keybd_event(vk_control, 0, 0, 0)
        user32.keybd_event(vk_c, 0, 0, 0)
        time.sleep(0.04)
        user32.keybd_event(vk_c, 0, keyeventf_keyup, 0)
        user32.keybd_event(vk_control, 0, keyeventf_keyup, 0)
        return bool(is_active)

    @staticmethod
    def _force_foreground_window(hwnd: int) -> bool:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        SW_RESTORE = 9
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_SHOWWINDOW = 0x0040

        try:
            user32.ShowWindow(hwnd, SW_RESTORE)
            foreground = user32.GetForegroundWindow()
            current_thread = kernel32.GetCurrentThreadId()
            target_thread = user32.GetWindowThreadProcessId(hwnd, None)
            foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0

            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
            attached_foreground = False
            if foreground_thread and foreground_thread != target_thread:
                attached_foreground = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
            try:
                user32.SetWindowPos(
                    hwnd,
                    HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
                )
                user32.SetWindowPos(
                    hwnd,
                    HWND_NOTOPMOST,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
                )
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                if attached_foreground:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
                if attached_target:
                    user32.AttachThreadInput(current_thread, target_thread, False)
            time.sleep(0.08)
            return user32.GetForegroundWindow() == hwnd
        except Exception:
            return False

    def _wait_for_clipboard_text(self, timeout_seconds: float) -> tuple[bool, str | None]:
        deadline = time.perf_counter() + timeout_seconds
        last_ok = True
        while time.perf_counter() < deadline:
            ok, text = self._read_clipboard_text()
            last_ok = ok
            if not ok:
                time.sleep(0.08)
                continue
            if text:
                return True, text
            time.sleep(0.08)
        ok, text = self._read_clipboard_text()
        if ok:
            return True, text
        return last_ok, None

    @staticmethod
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

    @staticmethod
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
                    win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                    return True
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                time.sleep(0.05)
        return False

    def _quick_login_state(self) -> str:
        """轻量状态检测：截图 + 图像特征判断，不做 OCR。用于校验轮询。"""
        selected, _ = select_login_window_by_game_no(self.account.game_window_no)
        if selected is None:
            self.log(
                f"[窗口{self.account.game_window_no}] 登录校验窗口定位失败，"
                "失败类型=LOGIN_VERIFY_SCREENSHOT_FAILED"
            )
            return "unknown"
        try:
            self._tmp_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            raw_path = self._tmp_path(f"verify_hwnd{selected.hwnd}_{stamp}.png")
            image = capture_window_background(selected).convert("RGB")
            image.save(raw_path)
        except Exception as exc:
            self.log(
                f"[窗口{self.account.game_window_no}] 登录校验截图失败 hwnd={selected.hwnd} "
                f"标题={selected.title} size={selected.width}x{selected.height} "
                f"失败类型=LOGIN_VERIFY_SCREENSHOT_FAILED 错误={exc}"
            )
            return "unknown"

        state, metrics = self.detect_login_page_state(image)
        failure_type = ""
        if state == "qr_page":
            failure_type = "LOGIN_VERIFY_QR_DETECTED"
        elif state == "unknown":
            failure_type = "LOGIN_VERIFY_UNKNOWN"
        self.log(
            f"[窗口{self.account.game_window_no}] 登录校验 hwnd={selected.hwnd} "
            f"标题={selected.title} size={selected.width}x{selected.height} "
            f"截图={raw_path} state={state} 二维码特征={metrics.get('qr_detected', False)} "
            f"疑似二维码={metrics.get('qr_suspected', False)} "
            f"black={metrics.get('black_ratio')} edge={metrics.get('edge_density')} "
            f"var={metrics.get('local_variance')} 失败类型={failure_type or '无'}"
        )
        return state

    def _log_iframe_info(self, page) -> None:
        try:
            iframe_count = page.locator("iframe").count()
        except Exception:
            iframe_count = max(0, len(page.frames) - 1)
        self.log(f"[窗口{self.account.game_window_no}] iframe 数量: {iframe_count}")

        for index in range(iframe_count):
            try:
                iframe = page.locator("iframe").nth(index)
                src = iframe.get_attribute("src", timeout=1000) or ""
                name = iframe.get_attribute("name", timeout=1000) or ""
                title = iframe.get_attribute("title", timeout=1000) or ""
            except Exception as exc:
                src, name, title = f"读取失败: {exc}", "", ""
            self.log(
                f"[窗口{self.account.game_window_no}] iframe[{index}] url={src} name={name} title={title}"
            )

    def _extract_passport_from_frames(self, page) -> str | None:
        self.log(f"[窗口{self.account.game_window_no}] 遍历所有 frame 执行 frame.evaluate(\"document.body.innerText\")")
        for frame in page.frames:
            index = page.frames.index(frame)
            title = self._frame_title(frame)
            try:
                text = frame.evaluate("() => document.body ? document.body.innerText : ''")
            except Exception as exc:
                text = ""
                self.log(
                    f"[窗口{self.account.game_window_no}] frame[{index}] evaluate 失败: {exc}"
                )
            preview = _preview_text(text, 400)
            self.log(
                f"[窗口{self.account.game_window_no}] frame[{index}] url={frame.url} name={frame.name} title={title}"
            )
            self.log(f"[窗口{self.account.game_window_no}] frame[{index}] innerText 前400字符: {preview}")
            passport = extract_passport_from_text(text, self.settings.passport_regex)
            if passport:
                self.log(f"[窗口{self.account.game_window_no}] frame[{index}] 包含“本次通行证”")
                return passport
        return None

    def _frame_title(self, frame) -> str:
        try:
            element = frame.frame_element()
            return element.get_attribute("title", timeout=1000) or ""
        except Exception:
            return ""

    def _extract_passport_by_full_page_ocr(self, page) -> str | None:
        try:
            import pytesseract
            from PIL import Image
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] OCR 依赖不可用，跳过识别: {exc}")
            return None

        screenshot_path = Path(gettempdir()) / f"douluo_passport_full_{self.account.game_window_no}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        try:
            text = pytesseract.image_to_string(Image.open(screenshot_path), lang="chi_sim+eng")
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] OCR 识别失败: {exc}")
            return None
        return extract_passport_from_text(text, self.settings.passport_regex)

    def _extract_passport_by_qr_region_ocr(self, page) -> str | None:
        try:
            import pytesseract
            from PIL import Image, ImageFilter, ImageOps
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] OCR 依赖不可用，跳过识别: {exc}")
            return None

        debug_dir = app_root() / self.settings.qr_passport_debug_dir
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        prefix = f"win{self.account.game_window_no}_{stamp}"

        raw_path = debug_dir / f"{prefix}_01_qr_page_full.png"
        page.screenshot(path=str(raw_path), full_page=True)
        raw_image = Image.open(raw_path).convert("RGB")
        self.log(f"[窗口{self.account.game_window_no}] 二维码页完整截图已保存: {raw_path}")

        qr_box = self._locate_qr_box(raw_image)
        if qr_box is None:
            self.log(f"[窗口{self.account.game_window_no}] 完整截图中未定位到二维码，停止 OCR")
            self.log(f"[窗口{self.account.game_window_no}] 请检查截图是否为二维码登录页: {raw_path}")
            return None
        self.log(f"[窗口{self.account.game_window_no}] 定位二维码区域: {qr_box}")
        crop_box = self._passport_crop_box_from_qr(qr_box, raw_image.size)
        crop = raw_image.crop(crop_box)
        crop_path = debug_dir / f"{prefix}_02_passport_region_crop.png"
        crop.save(crop_path)
        self.log(f"[窗口{self.account.game_window_no}] 通行证裁剪区域: {crop_box}，已保存: {crop_path}")
        self._draw_debug_boxes(raw_image, qr_box, crop_box, prefix, debug_dir)
        if not self._crop_likely_contains_passport_bar(crop):
            self.log(f"[窗口{self.account.game_window_no}] 通行证裁剪区域错误：未检测到疑似红色横条/文字区域，停止 OCR")
            return None

        variants: list[tuple[str, object, str]] = []
        scales = sorted({2, 3, 4, max(1, int(self.settings.qr_passport_ocr_scale))})
        threshold = max(0, min(255, int(self.settings.qr_passport_ocr_threshold)))
        for scale in scales:
            scaled_rgb = crop.resize((crop.width * scale, crop.height * scale))
            scaled_path = debug_dir / f"{prefix}_03_scale{scale}_rgb.png"
            scaled_rgb.save(scaled_path)
            variants.append((f"scale{scale}_rgb_no_binary", scaled_rgb, str(scaled_path)))

            gray = ImageOps.autocontrast(scaled_rgb.convert("L"))
            gray_path = debug_dir / f"{prefix}_04_scale{scale}_gray.png"
            gray.save(gray_path)
            variants.append((f"scale{scale}_gray_no_binary", gray, str(gray_path)))

            fixed_binary = gray.point(lambda pixel: 255 if pixel > threshold else 0, mode="1")
            fixed_path = debug_dir / f"{prefix}_05_scale{scale}_fixed_binary_{threshold}.png"
            fixed_binary.save(fixed_path)
            variants.append((f"scale{scale}_fixed_binary_{threshold}", fixed_binary, str(fixed_path)))

            background = gray.filter(ImageFilter.GaussianBlur(radius=max(3, scale * 2)))
            adaptive = Image.new("1", gray.size)
            gray_pixels = gray.load()
            bg_pixels = background.load()
            adaptive_pixels = adaptive.load()
            for y in range(gray.height):
                for x in range(gray.width):
                    adaptive_pixels[x, y] = 255 if gray_pixels[x, y] > bg_pixels[x, y] - 8 else 0
            adaptive_path = debug_dir / f"{prefix}_06_scale{scale}_adaptive_binary.png"
            adaptive.save(adaptive_path)
            variants.append((f"scale{scale}_adaptive_binary", adaptive, str(adaptive_path)))

        best_candidate: str | None = None
        best_variant = ""
        best_text = ""
        best_image = None
        first_variant_image = variants[0][1] if variants else crop
        config = "--psm 7 -c tessedit_char_whitelist=0123456789abcdef"
        for variant_name, image, image_path in variants:
            try:
                text = pytesseract.image_to_string(image, lang="eng", config=config)
            except Exception as exc:
                self.log(f"[窗口{self.account.game_window_no}] OCR 变体 {variant_name} 失败: {exc}")
                continue
            candidate = extract_hex_passport(text)
            self.log(
                f"[窗口{self.account.game_window_no}] OCR 变体 {variant_name}: 文本={_preview_text(text, 120)} 候选={candidate or '无'} 图片={image_path}"
            )
            if candidate and not best_candidate:
                best_candidate = candidate
                best_variant = variant_name
                best_text = text
                best_image = image

        final_path = debug_dir / f"{prefix}_07_ocr_final_input.png"
        if best_candidate:
            if best_image is not None:
                best_image.save(final_path)
            self.log(
                f"[窗口{self.account.game_window_no}] 最佳 OCR 结果: {best_candidate}，变体={best_variant}，原始文本={_preview_text(best_text, 120)}"
            )
            self.log(f"[窗口{self.account.game_window_no}] OCR 最终输入图已保存: {final_path}")
            return best_candidate
        first_variant_image.save(final_path)
        self.log(f"[窗口{self.account.game_window_no}] OCR 最终输入图已保存: {final_path}")
        self.log(f"[窗口{self.account.game_window_no}] 所有 OCR 变体均未识别到 8 位十六进制通行证")
        return None

    def _ocr_passport_by_template_match(self, raw_image) -> str | None:
        """用模板匹配方式识别通行证 hex 字符。

        裁剪底部文字区域，二值化后做滑动窗口模板匹配。
        对 hex 字符（0-9,a-f）的区分度优于 Tesseract。
        """
        from PIL import Image, ImageOps, ImageFilter
        try:
            w, h = raw_image.size
            crop = raw_image.crop((10, int(h * 0.50), w - 10, h - 10))
            big = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
            big = big.filter(ImageFilter.SHARPEN)
            gray = ImageOps.autocontrast(big.convert("L"))
            binary = gray.point(lambda p: 0 if p < 100 else 255, mode="1")
            result = self._ocr_chars_template_match(binary)
            if not result:
                self.log(f"[窗口{self.account.game_window_no}] 模板匹配OCR候选结果: 无")
                return None
            accepted, failure_type = self._decide_ocr_candidate("模板匹配", {result: 1})
            if failure_type:
                self.log(f"[窗口{self.account.game_window_no}] 模板匹配OCR失败类型={failure_type}")
            return accepted
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] 模板匹配OCR异常: {exc}")
            return None

    @staticmethod
    def _crop_passport_hex_region(raw_image):
        """从登录窗口截图中定位并裁剪通行证文字区域。

        目标区域在二维码下方，文字格式："本次通行证：XXXXXXXX"。
        通过粉色横条定位（窗口下半部分，y>55%）。
        不使用二维码定位。
        返回 (passport_text_region_image, bbox) 或 (None, None)。
        """
        import numpy as np
        from PIL import Image, ImageOps, ImageFilter

        arr = np.array(raw_image.convert("RGB"))
        h, w = arr.shape[:2]

        # 粉色检测：定位二维码下方的通行证文字横条
        # 搜索范围：窗口下半部分（y > 55%），二维码之下
        r_arr = arr[:, :, 0].astype(int)
        g_arr = arr[:, :, 1].astype(int)
        b_arr = arr[:, :, 2].astype(int)
        pink = (
            (r_arr > 110) & (r_arr < 250)
            & (r_arr > g_arr + 15)
            & (r_arr > b_arr + 20)
        )
        row_pct = pink.mean(axis=1)

        # 从窗口 55% 处开始搜索（二维码区域在上面）
        search_start = int(h * 0.55)
        search_end = int(h * 0.88)
        best_score, best_top, best_bot = 0, 0, 0
        for top in range(search_start, search_end - 8):
            for bot in range(top + 10, min(top + 50, search_end)):
                score = row_pct[top:bot].mean() * (bot - top)
                if score > best_score:
                    best_score, best_top, best_bot = score, top, bot

        if best_score < 0.5:
            return None, None

        # 裁剪文字行，上下左右留边距
        padding_y = 6
        margin_x = int(w * 0.04)
        crop_top = max(0, best_top - padding_y)
        crop_bot = min(h, best_bot + padding_y)
        crop = raw_image.crop((margin_x, crop_top, w - margin_x, crop_bot))

        # 保存完整通行证文字区域截图（调试图用）
        cropped_rgb = crop.copy()

        # 放大 4 倍 + 锐化 + 灰度 + 二值化
        big = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
        big = big.filter(ImageFilter.SHARPEN)
        gray = ImageOps.autocontrast(big.convert("L"))
        binary = gray.point(lambda p: 0 if p < 100 else 255, mode="1")

        return binary, (margin_x, crop_top, w - margin_x, crop_bot)

    @staticmethod
    def _ocr_chars_template_match(binary_hex_region):
        """对二值化后的 hex 字符区域做滑动窗口模板匹配。

        用 16 个字符模板（0-9,a-f）在 hex 区域滑动匹配，
        取匹配度最高的 8 个非重叠窗口。
        返回 8 位 hex 字符串或 None。
        """
        import cv2
        import numpy as np
        from PIL import Image, ImageFont, ImageDraw

        arr = np.array(binary_hex_region.convert("L"))
        h, bw = arr.shape[:2]
        if arr.mean() > 128:
            arr = 255 - arr  # 确保黑底白字

        # 生成模板：白底黑字，渲染 16 个 hex 字符
        hex_chars = list("0123456789abcdef")
        templates = {}
        font_size = max(16, int(h * 0.8))
        font = None
        # 尝试多个常见等宽字体路径
        for font_path in (
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "C:/Windows/Fonts/lucon.ttf",
            "consola.ttf",
            "cour.ttf",
        ):
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        for ch in hex_chars:
            timg = Image.new("L", (font_size + 8, font_size + 8), 255)
            draw = ImageDraw.Draw(timg)
            bbox = draw.textbbox((0, 0), ch, font=font)
            tx = (timg.width - (bbox[2] - bbox[0])) // 2 - bbox[0]
            ty = (timg.height - (bbox[3] - bbox[1])) // 2 - bbox[1]
            draw.text((tx, ty), ch, fill=0, font=font)
            # 缩放到与目标高度一致，宽度保持比例
            tarr = np.array(timg)
            _, tbw = cv2.threshold(tarr, 128, 255, cv2.THRESH_BINARY)
            # 裁剪到实际字符宽度
            cols = tbw.sum(axis=0)
            active = np.where(cols < 255 * tbw.shape[0] * 0.9)[0]
            if len(active) > 0:
                tbw = tbw[:, active[0]:active[-1] + 1]
            if tbw.shape[1] < 3:
                continue
            templates[ch] = cv2.resize(tbw, (max(3, int(tbw.shape[1] * h / tbw.shape[0])), h))

        if len(templates) < 16:
            return None

        # 滑动窗口匹配：以平均模板宽度为窗口
        avg_w = int(np.mean([t.shape[1] for t in templates.values()]))
        step = max(2, avg_w // 4)
        matches = []
        for x in range(0, bw - avg_w, step):
            window = arr[:, x:x + avg_w]
            if window.shape[1] < 3:
                continue
            for ch, tmpl in templates.items():
                if tmpl.shape[1] > window.shape[1]:
                    continue
                result = cv2.matchTemplate(window, tmpl, cv2.TM_CCOEFF_NORMED)
                score = result[0][0] if result.size > 0 else -1
                if score > 0.3:
                    matches.append((x, score, ch))

        if not matches:
            return None

        # 非极大值抑制：按 x 排序，取每个位置最高分的字符
        matches.sort(key=lambda m: m[0])
        selected = []
        last_x = -avg_w
        for x, score, ch in matches:
            if x - last_x >= avg_w * 0.6:
                selected.append((x, ch, score))
                last_x = x
            else:
                # 同位置选更高分
                if selected and score > selected[-1][2]:
                    selected[-1] = (x, ch, score)

        if len(selected) >= 6:
            chars = [ch for _, ch, _ in selected[:8]]
            return "".join(chars)
        return None

    def _decide_ocr_candidate(self, label: str, results: dict[str, int]) -> tuple[str | None, str | None]:
        normalized: dict[str, int] = {}
        for candidate, votes in results.items():
            value = (candidate or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{8}", value):
                continue
            normalized[value] = normalized.get(value, 0) + int(votes)

        if not normalized:
            self.log(f"[窗口{self.account.game_window_no}] {label} OCR候选结果: 无")
            self.log(
                f"[窗口{self.account.game_window_no}] {label} OCR是否接受: 否，失败类型=OCR_LOW_CONFIDENCE"
            )
            return None, "OCR_LOW_CONFIDENCE"

        total_votes = sum(normalized.values())
        ordered = sorted(normalized.items(), key=lambda item: (-item[1], item[0]))
        self.log(
            f"[窗口{self.account.game_window_no}] {label} OCR候选结果: "
            f"{len(ordered)}种，总票数={total_votes}"
        )
        for candidate, votes in ordered:
            self.log(
                f"[窗口{self.account.game_window_no}] {label} OCR候选票数: "
                f"{candidate}={votes}/{total_votes}"
            )

        ambiguous_positions: list[int] = []
        low_confidence_positions: list[int] = []
        for index in range(8):
            char_votes: dict[str, int] = {}
            for candidate, votes in normalized.items():
                char = candidate[index]
                char_votes[char] = char_votes.get(char, 0) + votes

            char_ordered = sorted(char_votes.items(), key=lambda item: (-item[1], item[0]))
            vote_text = ", ".join(f"{char}={votes}" for char, votes in char_ordered)
            top_char, top_votes = char_ordered[0]
            ce_competing = char_votes.get("c", 0) > 0 and char_votes.get("e", 0) > 0
            if ce_competing:
                ambiguous_positions.append(index + 1)
            if top_votes != total_votes:
                low_confidence_positions.append(index + 1)
            self.log(
                f"[窗口{self.account.game_window_no}] {label} 第{index + 1}位字符投票: "
                f"{vote_text}；最高={top_char}({top_votes}/{total_votes})"
            )

        if ambiguous_positions:
            positions = ",".join(str(pos) for pos in ambiguous_positions)
            self.log(f"[窗口{self.account.game_window_no}] {label} OCR存疑位置: {positions}（c/e竞争）")
            self.log(
                f"[窗口{self.account.game_window_no}] {label} OCR是否接受: 否，失败类型=OCR_AMBIGUOUS_CHAR"
            )
            return None, "OCR_AMBIGUOUS_CHAR"

        best, best_votes = ordered[0]
        if total_votes < 4:
            self.log(f"[窗口{self.account.game_window_no}] {label} OCR存疑位置: 全部（总票数不足）")
            self.log(
                f"[窗口{self.account.game_window_no}] {label} OCR是否接受: 否，失败类型=OCR_LOW_CONFIDENCE"
            )
            return None, "OCR_LOW_CONFIDENCE"

        if best_votes != total_votes or low_confidence_positions:
            positions = ",".join(str(pos) for pos in sorted(set(low_confidence_positions))) or "候选不一致"
            self.log(f"[窗口{self.account.game_window_no}] {label} OCR存疑位置: {positions}")
            self.log(
                f"[窗口{self.account.game_window_no}] {label} OCR是否接受: 否，失败类型=OCR_LOW_CONFIDENCE"
            )
            return None, "OCR_LOW_CONFIDENCE"

        self.log(f"[窗口{self.account.game_window_no}] {label} OCR存疑位置: 无")
        self.log(
            f"[窗口{self.account.game_window_no}] {label} OCR是否接受: 是，结果={best}"
        )
        return best, None

    def _ocr_passport_from_text_region(self, raw_image, prefix: str, raw_path: Path) -> str | None:
        """针对二维码页底部文字区域做OCR（避开QR码密集图案的干扰）。"""
        import re as _re
        try:
            import pytesseract
            from PIL import Image, ImageOps
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] OCR 依赖不可用: {exc}")
            return None

        # 裁切底部文字区域（通行证文字在二维码下方）
        w, h = raw_image.size
        text_crop = raw_image.crop((10, int(h * 0.50), w - 10, h - 10))
        regex = self.settings.passport_regex
        results: dict[str, int] = {}

        for scale in (2, 3, 4):
            big = text_crop.resize((text_crop.width * scale, text_crop.height * scale), Image.LANCZOS)
            for psm in (6, 7):
                try:
                    text = pytesseract.image_to_string(big, lang="chi_sim+eng", config=f"--psm {psm}")
                except Exception:
                    continue
                # 方式1: 匹配"本次通行证"正则
                passport = extract_passport_from_text(text, regex)
                if passport:
                    hex_val = extract_hex_passport(passport)
                    if hex_val:
                        results[hex_val] = results.get(hex_val, 0) + 1
                # 方式2: 冒号模式双向匹配（hex可能在冒号前或后）
                for pattern in (r":\s*(\S{7,10})(?:\s|$)", r"(\S{7,10})\s*:"):
                    m = _re.search(pattern, text)
                    if m:
                        hex_val = extract_hex_passport(m.group(1))
                        if hex_val:
                            results[hex_val] = results.get(hex_val, 0) + 1
                # 方式3: 直接在全文搜索hex（兜底）
                for hex_val in _re.findall(r"[a-f0-9]{8}", text.lower()):
                    results[hex_val] = results.get(hex_val, 0) + 1

        if not results:
            self.log(
                f"[窗口{self.account.game_window_no}] 文字区域OCR未提取到hex，回退全图OCR"
            )
            return None

        best, failure_type = self._decide_ocr_candidate("文字区域", results)
        if failure_type:
            self.log(f"[窗口{self.account.game_window_no}] 文字区域OCR失败类型={failure_type}")
            return None

        return best

    def _ocr_passport_from_login_image(self, raw_image, prefix: str, raw_path: Path) -> str | None:
        import numpy as np
        try:
            import pytesseract
            from PIL import Image, ImageOps, ImageFilter
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] OCR 依赖不可用，跳过识别: {exc}")
            return None

        debug_dir = app_root() / self.settings.qr_passport_debug_dir
        regex = self.settings.passport_regex

        # === 全图 OCR：收集所有变体结果，投票选出最佳值 ===
        results: dict[str, int] = {}  # hex_val → 出现次数
        best_image_for_result: dict[str, object] = {}  # 保存对应截图

        def _add_result(hex_val: str, save_image) -> None:
            results[hex_val] = results.get(hex_val, 0) + 1
            if hex_val not in best_image_for_result:
                best_image_for_result[hex_val] = save_image

        for scale in (1, 2):
            if scale > 1:
                img = raw_image.resize((raw_image.width * scale, raw_image.height * scale))
            else:
                img = raw_image.copy()

            for psm in (6, 3):
                config = f"--psm {psm}"
                try:
                    text = pytesseract.image_to_string(img, lang="chi_sim+eng", config=config)
                except Exception:
                    continue
                self._vlog("debug",
                    f"[窗口{self.account.game_window_no}] 全图OCR scale={scale} psm={psm}: "
                    f"{_preview_text(text, 200)}"
                )
                # 方式1: 匹配"本次通行证"提取
                passport = extract_passport_from_text(text, regex)
                if passport:
                    hex_val = extract_hex_passport(passport)
                    if hex_val:
                        self.log(f"[窗口{self.account.game_window_no}] 全图OCR成功: {hex_val}")
                        _add_result(hex_val, img.copy())
                # 方式2: 冒号后捕获宽松文本，走纠错管线
                # OCR 乱码时"本次通行证"可能被识别为乱码，QR检测可提供外部确认
                if "通行证" in text:
                    m = re.search(r":\s*(\S{7,10})(?:\s|$)", text)
                    if m:
                        hex_val = extract_hex_passport(m.group(1))
                        if hex_val:
                            self.log(f"[窗口{self.account.game_window_no}] 全图OCR成功(冒号模式): {hex_val}")
                            _add_result(hex_val, img.copy())

            # 灰度图
            gray = ImageOps.autocontrast(img.convert("L"))
            for psm in (6, 3):
                config = f"--psm {psm}"
                try:
                    text = pytesseract.image_to_string(gray, lang="chi_sim+eng", config=config)
                except Exception:
                    continue
                self._vlog("debug",
                    f"[窗口{self.account.game_window_no}] 全图OCR灰度 scale={scale} psm={psm}: "
                    f"{_preview_text(text, 200)}"
                )
                passport = extract_passport_from_text(text, regex)
                if passport:
                    hex_val = extract_hex_passport(passport)
                    if hex_val:
                        self.log(f"[窗口{self.account.game_window_no}] 全图OCR灰度成功: {hex_val}")
                        _add_result(hex_val, gray.copy())
                if "通行证" in text:
                    m = re.search(r":\s*(\S{7,10})(?:\s|$)", text)
                    if m:
                        hex_val = extract_hex_passport(m.group(1))
                        if hex_val:
                            self.log(f"[窗口{self.account.game_window_no}] 全图OCR灰度成功(冒号模式): {hex_val}")
                            _add_result(hex_val, gray.copy())

        if not results:
            self.log(f"[窗口{self.account.game_window_no}] 全图OCR未能识别到8位hex通行证")
            return None

        best, failure_type = self._decide_ocr_candidate("全图", results)
        if failure_type:
            self.log(f"[窗口{self.account.game_window_no}] 全图OCR失败类型={failure_type}")
            return None

        # 保存最佳结果截图
        if best in best_image_for_result:
            final_path = self._tmp_path(f"{prefix}_ocr_success.png")
            best_image_for_result[best].save(final_path)
            self._save_latest_ocr_success(best_image_for_result[best])

        return best

    def _log_screenshot_context(self, page) -> None:
        self.log(
            f"[窗口{self.account.game_window_no}] 当前账号: 层级={self.account.level}, 收藏编号={self.account.bookmark_no}, 游戏窗口号={self.account.game_window_no}"
        )
        self.log(f"[窗口{self.account.game_window_no}] Playwright page 标题: {page.title()}")
        self.log(f"[窗口{self.account.game_window_no}] Playwright page URL: {page.url}")
        self.log(f"[窗口{self.account.game_window_no}] Playwright page 截图 hwnd: N/A（不使用系统窗口截图）")
        self.log(f"[窗口{self.account.game_window_no}] 截图来源: 当前 Playwright page 对象，不使用系统窗口截图")
        try:
            candidates = list_browser_windows("")
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] 读取候选浏览器窗口失败: {exc}")
            return
        self.log(f"[窗口{self.account.game_window_no}] 候选浏览器窗口数量: {len(candidates)}")
        page_title = page.title()
        matched = False
        for index, window in enumerate(candidates):
            marker = ""
            if page_title and page_title in window.title:
                marker = " <- 标题匹配当前 page"
                matched = True
            self.log(
                f"[窗口{self.account.game_window_no}] candidate[{index}] hwnd={window.hwnd} title={window.title} client={window.width}x{window.height}{marker}"
            )
        if not matched:
            self.log(f"[窗口{self.account.game_window_no}] 未找到标题匹配当前 page 的系统窗口；截图仍使用 Playwright page.screenshot()")

    def detect_login_page_state(self, image) -> tuple[str, dict]:
        """用图像特征判断登录程序窗口状态（不用Tesseract）。

        返回 (state, metrics)，state ∈ {"qr_page", "logged_in", "unknown"}。
        """
        import cv2
        import numpy as np

        qr_box = None
        try:
            qr_box = self._detect_opencv_qr_box(image)
        except Exception as exc:
            self._vlog("debug", f"[窗口{self.account.game_window_no}] QR检测异常: {exc}")

        roi = self.settings.login_state_roi  # (left, top, right, bottom)
        arr = np.array(image.convert("L"))
        h, w = arr.shape[:2]
        left = max(0, roi[0])
        top = max(0, roi[1])
        right = min(w, roi[2])
        bottom = min(h, roi[3])
        roi_arr = arr[top:bottom, left:right]
        roi_h, roi_w = roi_arr.shape
        if roi_h <= 0 or roi_w <= 0:
            return "unknown", {
                "black_ratio": 0,
                "edge_density": 0,
                "local_variance": 0,
                "roi": roi,
                "state": "unknown",
                "qr_detected": bool(qr_box),
                "failure_type": "WINDOW_SIZE_UNSUPPORTED",
                "image_size": (w, h),
            }

        # --- 指标1: 黑色像素占比 ---
        black_pixels = int((roi_arr < 80).sum())
        total_pixels = roi_w * roi_h
        black_ratio = black_pixels / max(total_pixels, 1)

        # --- 指标2: 边缘密度 (Sobel) ---
        grad_x = cv2.Sobel(roi_arr, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(roi_arr, cv2.CV_64F, 0, 1, ksize=3)
        edge_mag = np.sqrt(grad_x ** 2 + grad_y ** 2)
        edge_pixels = int((edge_mag > 60).sum())
        edge_density = edge_pixels / max(total_pixels, 1)

        # --- 指标3: 局部方差 ---
        block_size = 20
        variances = []
        for by in range(0, roi_h - block_size, block_size):
            for bx in range(0, roi_w - block_size, block_size):
                block = roi_arr[by:by + block_size, bx:bx + block_size]
                variances.append(float(np.var(block)))
        local_variance = float(np.mean(variances)) if variances else 0.0

        # --- 判定 ---
        qr_min = self.settings.qr_black_ratio_min
        qr_edge = self.settings.qr_edge_density_min
        qr_var = self.settings.qr_variance_min
        logged_max = self.settings.logged_in_black_ratio_max
        logged_edge = self.settings.logged_in_edge_density_max

        qr_suspected = (
            qr_box is None
            and black_ratio >= qr_min
            and edge_density >= qr_edge
            and local_variance >= qr_var
        )

        game_notice_detected = False
        if qr_box is None and not qr_suspected:
            try:
                game_notice_detected = self._looks_like_game_notice_page(image)
            except Exception as exc:
                self._vlog("debug", f"[窗口{self.account.game_window_no}] 公告页检测异常: {exc}")

        if qr_box is not None:
            state = "qr_page"
        elif qr_suspected:
            state = "unknown"
        elif game_notice_detected:
            state = "logged_in"
        elif black_ratio <= logged_max and edge_density <= logged_edge:
            state = "logged_in"
        else:
            state = "unknown"

        metrics = {
            "black_ratio": round(black_ratio, 4),
            "edge_density": round(edge_density, 4),
            "local_variance": round(local_variance, 1),
            "roi": roi,
            "state": state,
            "qr_detected": bool(qr_box),
            "qr_suspected": bool(qr_suspected),
            "game_notice_detected": bool(game_notice_detected),
            "qr_box": qr_box,
            "image_size": (w, h),
        }

        # --- 调试：保存ROI截图 ---
        try:
            debug_dir = app_root() / "debug_ocr"
            debug_dir.mkdir(parents=True, exist_ok=True)
            roi_img = image.crop((left, top, right, bottom))
            roi_img.save(debug_dir / "latest_login_state_roi.png")
        except Exception:
            pass

        return state, metrics

    def _detect_opencv_qr_box(self, image) -> tuple[int, int, int, int] | None:
        """只使用 OpenCV QRCodeDetector 做强二维码检测，不做暗像素回退。"""
        import cv2
        import numpy as np

        cv_image = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        detector = cv2.QRCodeDetector()

        # 尝试多尺度：原图 + 2x/3x 放大，提高小 QR 码检出率
        scales = [(1.0, cv_image)]
        h, w = cv_image.shape[:2]
        for factor in (2, 3):
            scales.append((factor, cv2.resize(cv_image, (w * factor, h * factor))))

        for factor, scaled in scales:
            try:
                data, bbox, _ = detector.detectAndDecode(scaled)
            except Exception:
                continue
            if bbox is not None and len(bbox) > 0:
                pts = (bbox.astype(np.float64) / factor).astype(int)
                left = max(0, pts[:, 0].min())
                top = max(0, pts[:, 1].min())
                right = min(image.width, pts[:, 0].max())
                bottom = min(image.height, pts[:, 1].max())
                if right - left >= 50 and bottom - top >= 50:
                    self.log(
                        f"[窗口{self.account.game_window_no}] OpenCV QR检测成功 "
                        f"(scale={factor}x): ({left},{top},{right},{bottom}) "
                        f"解码={data or '失败'}"
                    )
                    return (left, top, right, bottom)

        return None

    def _locate_qr_box(self, image) -> tuple[int, int, int, int] | None:
        qr_box = self._detect_opencv_qr_box(image)
        if qr_box is not None:
            return qr_box
        self.log(f"[窗口{self.account.game_window_no}] OpenCV QR检测失败，回退暗像素搜索")
        return self._locate_qr_box_fallback(image)

    def _locate_qr_box_fallback(self, image) -> tuple[int, int, int, int] | None:
        gray = image.convert("L")
        width, height = gray.size
        pixels = gray.load()
        integral = [[0] * (width + 1) for _ in range(height + 1)]
        for y in range(height):
            row_sum = 0
            for x in range(width):
                row_sum += 1 if pixels[x, y] < 110 else 0
                integral[y + 1][x + 1] = integral[y][x + 1] + row_sum

        def dark_sum(left: int, top: int, right: int, bottom: int) -> int:
            return (
                integral[bottom][right]
                - integral[top][right]
                - integral[bottom][left]
                + integral[top][left]
            )

        min_size = max(90, int(min(width, height) * 0.15))
        max_size = max(min_size + 1, int(min(width, height) * 0.45))
        best_score = -1.0
        best_box: tuple[int, int, int, int] | None = None
        center_x = width / 2
        for size in range(min_size, max_size + 1, 20):
            step = max(8, size // 8)
            top_start = int(height * 0.15)
            top_end = max(int(height * 0.65) - size, top_start + 1)
            for top in range(top_start, top_end, step):
                for left in range(
                    int(width * 0.05),
                    max(int(width * 0.95) - size, int(width * 0.05) + 1),
                    step,
                ):
                    area = size * size
                    density = dark_sum(left, top, left + size, top + size) / area
                    if density < 0.12 or density > 0.65:
                        continue
                    center_weight = (
                        1
                        - min(1, abs((left + size / 2) - center_x) / center_x) * 0.35
                    )
                    size_weight = size / max_size
                    score = density * center_weight * (0.6 + size_weight)
                    if score > best_score:
                        best_score = score
                        best_box = (left, top, left + size, top + size)

        if best_box is not None:
            self.log(
                f"[窗口{self.account.game_window_no}] 回退搜索定位: {best_box} score={best_score:.3f}"
            )
        return best_box

    def _find_red_bar_below_qr(
        self,
        image,
        qr_box: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        """在二维码下方扫描红色横条，返回 (left, top, right, bottom) 或 None"""
        width, height = image.size
        _, _, qr_left, qr_bottom = qr_box
        rgb = image.convert("RGB")
        import numpy as np

        arr = np.array(rgb)
        r_arr = arr[:, :, 0].astype(int)
        g_arr = arr[:, :, 1].astype(int)
        b_arr = arr[:, :, 2].astype(int)

        scan_start = max(0, qr_bottom - 10)
        scan_end = min(height, qr_bottom + 180)

        best_top = None
        best_bottom = None
        best_red_count = 0

        # 逐行扫描，统计每行红色/深红像素占比。大窗口横条是半透明深红，不能只看亮红。
        min_red_ratio = 0.16
        consecutive_red_rows = 0
        streak_start = None
        x_left = max(0, int(width * 0.06))
        x_right = min(width, int(width * 0.94))
        red_like = (
            (r_arr > 70)
            & (r_arr > g_arr + 10)
            & (r_arr > b_arr + 5)
            & (g_arr < 150)
            & (b_arr < 150)
        )
        dark_red_like = (
            (r_arr > 55)
            & (r_arr > g_arr + 8)
            & (r_arr > b_arr + 5)
            & (g_arr < 120)
            & (b_arr < 120)
        )
        red_mask = red_like | dark_red_like

        for y in range(scan_start, scan_end):
            red_ratio = float(red_mask[y, x_left:x_right].mean())

            if red_ratio >= min_red_ratio:
                if streak_start is None:
                    streak_start = y
                consecutive_red_rows += 1
                if consecutive_red_rows > best_red_count:
                    best_red_count = consecutive_red_rows
                    best_top = streak_start
                    best_bottom = y + 1
            else:
                consecutive_red_rows = 0
                streak_start = None

        if best_top is not None and best_bottom is not None and best_bottom - best_top >= 12:
            margin = max(0, int(self.settings.passport_region_x_margin))
            return (margin, best_top, width - margin, best_bottom)

        return None

    def _passport_crop_box_from_qr(
        self,
        qr_box: tuple[int, int, int, int],
        image_size: tuple[int, int],
    ) -> tuple[int, int, int, int]:
        width, height = image_size
        _, _, _, bottom = qr_box
        margin = max(0, int(self.settings.passport_region_x_margin))
        y_offset = max(0, int(self.settings.passport_region_y_offset))
        region_height = max(20, int(self.settings.passport_region_height))
        crop_left = min(width - 1, margin)
        crop_right = max(crop_left + 1, width - margin)
        crop_top = min(height - 1, bottom + y_offset)
        crop_bottom = min(height, crop_top + region_height)
        if crop_bottom <= crop_top + 20:
            crop_top = max(0, min(height - 21, bottom + y_offset))
            crop_bottom = min(height, crop_top + 45)
        return (crop_left, crop_top, crop_right, crop_bottom)

    def _draw_debug_boxes(self, image, qr_box, crop_box, prefix, debug_dir):
        from PIL import ImageDraw

        draw_img = image.copy().convert("RGB")
        draw = ImageDraw.Draw(draw_img)
        draw.rectangle(qr_box, outline="blue", width=2)
        draw.rectangle(crop_box, outline="red", width=2)
        _, _, _, qr_bottom = qr_box
        draw.line(
            [(0, qr_bottom), (image.width, qr_bottom)],
            fill="yellow",
            width=1,
        )
        debug_path = debug_dir / f"{prefix}_debug_boxes.png"
        draw_img.save(debug_path)
        self.log(
            f"[窗口{self.account.game_window_no}] 调试框已保存: {debug_path}"
        )

    def _crop_likely_contains_passport_bar(self, crop) -> bool:
        image = crop.convert("RGB")
        width, height = image.size
        if width < 80 or height < 20:
            return False
        pixels = image.load()
        red_like = 0
        dark_like = 0
        total = width * height
        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y]
                if r > 120 and r > g * 1.25 and r > b * 1.25:
                    red_like += 1
                if r < 90 and g < 90 and b < 90:
                    dark_like += 1
        red_ratio = red_like / total
        dark_ratio = dark_like / total
        self.log(
            f"[窗口{self.account.game_window_no}] 通行证裁剪区域检查: red_ratio={red_ratio:.3f}, dark_ratio={dark_ratio:.3f}, size={width}x{height}"
        )
        return red_ratio > 0.08 or dark_ratio > 0.02

    def _all_visible_text(self, page) -> str:
        parts: list[str] = []
        for frame in page.frames:
            try:
                text = frame.locator("body").inner_text(timeout=1000)
            except Exception:
                try:
                    text = frame.evaluate("() => document.body ? document.body.innerText : ''")
                except Exception:
                    text = ""
            if text:
                parts.append(text)
        return "\n".join(parts)

    def _find_game_browser_window(self) -> int | None:
        import win32gui

        matches: list[tuple[int, str]] = []

        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            if win32gui.GetClassName(hwnd) != "Chrome_WidgetWin_1":
                return
            title = win32gui.GetWindowText(hwnd)
            if "7tu7tu" in title or "7兔" in title or "斗罗" in title:
                matches.append((hwnd, title))

        win32gui.EnumWindows(callback, None)
        for index, (hwnd, title) in enumerate(matches):
            marker = " <- 选中" if index == 0 else ""
            self._vlog("debug", f"[窗口{self.account.game_window_no}] 浏览器候选[{index}] hwnd={hwnd} title={title}{marker}")
        return matches[0][0] if matches else None

    def _write_browser_pos(self, browser_hwnd: int) -> None:
        import json
        import win32gui

        cx, cy = win32gui.ClientToScreen(browser_hwnd, (0, 0))

        def find_render(hwnd, _):
            nonlocal cx, cy
            if win32gui.GetClassName(hwnd) == "Chrome_RenderWidgetHostHWND":
                left, top, _, _ = win32gui.GetWindowRect(hwnd)
                cx, cy = left, top

        win32gui.EnumChildWindows(browser_hwnd, find_render, None)
        path = app_root() / "debug_ocr/browser_pos.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"hwnd": browser_hwnd, "cx": cx, "cy": cy}, ensure_ascii=False), encoding="utf-8")
        self.log(f"[窗口{self.account.game_window_no}] 已写入 browser_pos.json: hwnd={browser_hwnd}, render_origin=({cx},{cy})")

    def _get_browser_viewport_size(self, browser_hwnd: int) -> tuple[int, int]:
        import win32gui

        render_size: tuple[int, int] | None = None

        def find_render(hwnd, _):
            nonlocal render_size
            if win32gui.GetClassName(hwnd) == "Chrome_RenderWidgetHostHWND":
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                render_size = (max(1, right - left), max(1, bottom - top))

        win32gui.EnumChildWindows(browser_hwnd, find_render, None)
        if render_size is not None:
            return render_size

        client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(browser_hwnd)
        width = max(1, client_right - client_left)
        height = max(1, client_bottom - client_top)
        return width, height

    def _capture_browser_client(self, browser_hwnd: int, file_name: str | None = None):
        import win32gui

        from .dm_client import WindowInfo as _WindowInfo

        left, top, right, bottom = win32gui.GetWindowRect(browser_hwnd)
        render_rect: tuple[int, int, int, int] | None = None

        def find_render(hwnd, _):
            nonlocal render_rect
            if win32gui.GetClassName(hwnd) == "Chrome_RenderWidgetHostHWND":
                render_rect = win32gui.GetWindowRect(hwnd)

        win32gui.EnumChildWindows(browser_hwnd, find_render, None)
        window = _WindowInfo(
            hwnd=browser_hwnd,
            title=win32gui.GetWindowText(browser_hwnd),
            width=right - left,
            height=bottom - top,
            left=left,
            top=top,
            right=right,
            bottom=bottom,
        )
        # 确保浏览器在前台（exe 模式 Tkinter 可能抢焦点导致 ImageGrab 截错窗口）
        import win32con as _w32c
        try:
            win32gui.BringWindowToTop(browser_hwnd)
            win32gui.SetForegroundWindow(browser_hwnd)
        except Exception:
            pass
        import time as _t2
        _t2.sleep(0.03)

        full = capture_window_background(window).convert("RGB")
        if render_rect is not None:
            render_left, render_top, render_right, render_bottom = render_rect
            crop_box = (
                max(0, render_left - left),
                max(0, render_top - top),
                min(full.width, render_right - left),
                min(full.height, render_bottom - top),
            )
            self.log(f"[窗口{self.account.game_window_no}] 截取浏览器渲染区: {crop_box}")
            client = full.crop(crop_box)
        else:
            client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(browser_hwnd)
            border_x = (right - left - client_right) // 2
            title_height = bottom - top - client_bottom - border_x
            self.log(f"[窗口{self.account.game_window_no}] 未找到渲染子窗口，回退客户区裁剪")
            client = full.crop((border_x, title_height, full.width - border_x, full.height - border_x))
        expected_size = (self.settings.window_width, self.settings.window_height)
        if client.size != expected_size:
            client = client.resize(expected_size)
        if file_name and self._save_screenshots:
            path = self._tmp_path(file_name)
            client.save(path)
            self.log(f"[窗口{self.account.game_window_no}] 临时截图已保存: _tmp/{file_name}")
        return client

    def _passport_button_click_points(self, btn_pos: tuple[int, int]) -> list[tuple[int, int]]:
        x, y = btn_pos
        configured = self.settings.passport_btn_viewport
        points = [
            (x, y),
            (x, y + 28),
            (x, y + 42),
            (x + 8, y + 28),
            (x - 8, y + 28),
        ]
        if configured and configured not in points:
            points.append(configured)
        bounded: list[tuple[int, int]] = []
        for px, py in points:
            px = max(0, min(self.settings.window_width - 1, int(px)))
            py = max(0, min(self.settings.window_height - 1, int(py)))
            if (px, py) not in bounded:
                bounded.append((px, py))
        return bounded

    def _passport_dialog_cache_path(self) -> Path:
        return app_root() / "debug_ocr" / "passport_dialog_pos_cache.json"

    @staticmethod
    def _viewport_cache_key(viewport_key: tuple[int, int]) -> str:
        return f"{int(viewport_key[0])}x{int(viewport_key[1])}"

    @staticmethod
    def _parse_dialog_point(value) -> tuple[int, int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        try:
            return int(value[0]), int(value[1])
        except Exception:
            return None

    def _load_passport_dialog_coord_cache(
        self,
        viewport_key: tuple[int, int],
    ) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]] | None:
        cached = AccountRunner._dialog_coord_cache.get(viewport_key)
        if cached is not None:
            return cached

        cache_label = self._viewport_cache_key(viewport_key)
        path = self._passport_dialog_cache_path()
        if not path.exists():
            self.log(f"[窗口{self.account.game_window_no}] 通行证弹窗坐标缓存不存在：{path}")
            return None

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.log(
                f"[窗口{self.account.game_window_no}] 通行证弹窗坐标缓存失效："
                f"读取失败 {exc}"
            )
            return None

        if not isinstance(raw, dict):
            self.log(f"[窗口{self.account.game_window_no}] 通行证弹窗坐标缓存失效：根节点不是对象")
            return None

        entry = raw.get(cache_label)
        if not isinstance(entry, dict):
            self.log(
                f"[窗口{self.account.game_window_no}] 通行证弹窗坐标缓存未命中："
                f"viewport={cache_label}"
            )
            return None

        button = self._parse_dialog_point(entry.get("button"))
        input_center = self._parse_dialog_point(entry.get("input"))
        confirm_center = self._parse_dialog_point(entry.get("confirm"))
        if button is None or input_center is None or confirm_center is None:
            self.log(
                f"[窗口{self.account.game_window_no}] 通行证弹窗坐标缓存失效："
                f"viewport={cache_label} 坐标格式错误"
            )
            return None

        coords = (button, input_center, confirm_center)
        AccountRunner._dialog_coord_cache[viewport_key] = coords
        self.log(
            f"[窗口{self.account.game_window_no}] 已读取通行证弹窗坐标缓存："
            f"viewport={cache_label} button={button} input={input_center} confirm={confirm_center}"
        )
        return coords

    def _save_passport_dialog_coord_cache(
        self,
        viewport_key: tuple[int, int],
        button: tuple[int, int],
        input_center: tuple[int, int],
        confirm_center: tuple[int, int],
    ) -> None:
        cache_label = self._viewport_cache_key(viewport_key)
        path = self._passport_dialog_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        raw: dict[str, object] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    raw = loaded
            except Exception as exc:
                self.log(
                    f"[窗口{self.account.game_window_no}] 通行证弹窗坐标缓存失效："
                    f"写入前读取失败 {exc}，将重建缓存"
                )

        raw[cache_label] = {
            "button": [int(button[0]), int(button[1])],
            "input": [int(input_center[0]), int(input_center[1])],
            "confirm": [int(confirm_center[0]), int(confirm_center[1])],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(
            f"[窗口{self.account.game_window_no}] 已写入通行证弹窗坐标缓存："
            f"viewport={cache_label}"
        )

    def _click_passport_button_and_wait_dialog(
        self,
        browser_hwnd: int,
        btn_vx: int,
        btn_vy: int,
        label: str,
        viewport_key: tuple[int, int] | None = None,
    ) -> tuple[int, int, int, int]:
        if viewport_key is None:
            viewport_key = self._get_browser_viewport_size(browser_hwnd)
        viewport_label = f"{viewport_key[0]}x{viewport_key[1]}"
        t_start = time.perf_counter()
        self.log(
            f"[窗口{self.account.game_window_no}] 点击通行证按钮并等待弹窗: "
            f"{label} button=({btn_vx},{btn_vy})"
        )
        if not self._dm_click_viewport(btn_vx, btn_vy, "通行证按钮", 120):
            raise RuntimeError("Dm 点击通行证按钮失败")
        t_click_done = time.perf_counter()
        self.log(
            f"[窗口{self.account.game_window_no}] [耗时] 发起点击→点击通行证按钮完成="
            f"{t_click_done - t_start:.2f}s"
        )

        deadline = time.perf_counter() + 5.0
        last_input = None
        last_confirm = None
        attempt = 0
        while time.perf_counter() < deadline:
            self._ensure_not_stopped()
            time.sleep(0.05)
            attempt += 1
            image = self._capture_browser_client(browser_hwnd, None)
            dialog_visible = self._is_passport_dialog_visible_by_ocr(image)
            if not dialog_visible:
                self.log(
                    f"[窗口{self.account.game_window_no}] 通行证弹窗未出现，继续等待 "
                    f"({attempt})"
                )
                continue

            input_center = self._locate_passport_input_center(image, log_result=True)
            confirm_center = self._locate_confirm_button_center(image, log_result=True)
            t_dialog_seen = time.perf_counter()
            self.log(
                f"[窗口{self.account.game_window_no}] [耗时] 点击按钮到弹窗出现="
                f"{t_dialog_seen - t_click_done:.2f}s"
            )
            last_input = input_center
            last_confirm = confirm_center
            if input_center is None or confirm_center is None:
                self.log(
                    f"[窗口{self.account.game_window_no}] 已看到通行证弹窗，"
                    f"但输入框/确认按钮定位不完整 input={input_center} confirm={confirm_center}"
                )
                continue

            AccountRunner._cached_input = input_center
            AccountRunner._cached_confirm = confirm_center
            AccountRunner._cached_dialog_window_size = (
                self.settings.window_width,
                self.settings.window_height,
            )
            button_center = (int(btn_vx), int(btn_vy))
            if label == "方式一":
                AccountRunner._dialog_coord_cache[viewport_key] = (
                    button_center,
                    input_center,
                    confirm_center,
                )
                self.log(
                    f"[窗口{self.account.game_window_no}] 已缓存通行证弹窗坐标："
                    f"viewport={viewport_label} button={button_center} "
                    f"input={input_center} confirm={confirm_center}"
                )
                self._save_passport_dialog_coord_cache(
                    viewport_key,
                    button_center,
                    input_center,
                    confirm_center,
                )
            t_controls_done = time.perf_counter()
            self.log(
                f"[窗口{self.account.game_window_no}] 通行证弹窗已出现，"
                f"输入框={input_center} 确认按钮={confirm_center}"
            )
            self.log(
                f"[窗口{self.account.game_window_no}] [耗时] 弹窗出现→控件定位完成="
                f"{t_controls_done - t_dialog_seen:.2f}s"
            )
            return input_center[0], input_center[1], confirm_center[0], confirm_center[1]

        try:
            self._capture_browser_client(browser_hwnd, f"passport_dialog_wait_failed_{label}.png")
        except Exception:
            pass
        raise RuntimeError(
            "点击通行证按钮后弹窗未出现或定位失败，"
            f"input={last_input} confirm={last_confirm}"
        )

    def _click_passport_button_input_confirm_fast(
        self,
        viewport_key: tuple[int, int],
        btn_vx: int,
        btn_vy: int,
        passport: str,
        label: str,
        wait_ms: int = 450,
    ) -> bool:
        """Use one Dm helper process when dialog control coordinates are known."""
        viewport_label = f"{viewport_key[0]}x{viewport_key[1]}"
        cached_coords = self._load_passport_dialog_coord_cache(viewport_key)
        if cached_coords is None:
            self.log(
                f"[窗口{self.account.game_window_no}] 未使用合并DM chain："
                f"viewport={viewport_label} 暂无同尺寸弹窗坐标缓存，走视觉检测安全路径"
            )
            return False

        cached_button, cached_input, cached_confirm = cached_coords
        btn_vx, btn_vy = cached_button
        input_x, input_y = cached_input
        confirm_x, confirm_y = cached_confirm
        self.log(
            f"[窗口{self.account.game_window_no}] 使用合并DM chain："
            f"viewport={viewport_label} button=({btn_vx},{btn_vy}) "
            f"input=({input_x},{input_y}) confirm=({confirm_x},{confirm_y}) "
            f"wait={wait_ms}ms label={label}"
        )
        self.log(f"[窗口{self.account.game_window_no}] 输入通行证并点击确认: {passport}")
        chain_start = time.perf_counter()
        if not self._dm_chain(
            [
                f"click,{btn_vx},{btn_vy},120",
                f"wait,{wait_ms}",
                f"click,{input_x},{input_y},80",
                f"type,{passport}",
                f"click,{confirm_x},{confirm_y},100",
            ],
            "合并点击按钮+输入+确认",
        ):
            raise RuntimeError("Dm 合并点击按钮+输入+确认失败")
        chain_done = time.perf_counter()
        self.log(
            f"[窗口{self.account.game_window_no}] [耗时] 合并DM chain总耗时="
            f"{chain_done - chain_start:.2f}s"
        )
        self.log(
            f"[窗口{self.account.game_window_no}] [耗时] 发起点击→点击通行证按钮完成="
            "合并chain内执行"
        )
        self.log(
            f"[窗口{self.account.game_window_no}] [耗时] 点击按钮到弹窗出现="
            f"{wait_ms / 1000:.2f}s（合并chain固定等待）"
        )
        self.log(
            f"[窗口{self.account.game_window_no}] [耗时] 检测到弹窗→发起输入="
            "合并chain内执行"
        )
        self.log(
            f"[窗口{self.account.game_window_no}] [耗时] 点击输入框+输入通行证+点击确认="
            f"{chain_done - chain_start:.2f}s（包含按钮点击与等待）"
        )
        return True

    def _dm_click_viewport(self, vx: int, vy: int, label: str, hold_ms: int = 120) -> bool:
        import subprocess

        pos_file = app_root() / "debug_ocr/browser_pos.json"
        if not pos_file.exists():
            self.log(f"[窗口{self.account.game_window_no}] browser_pos.json 不存在")
            return False
        helper = str(app_root() / "dm_click_helper.py")
        result = subprocess.run(
            ["py", "-3.14-32", helper, "click", str(vx), str(vy), str(hold_ms)],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0:
            self.log(f"[窗口{self.account.game_window_no}] Dm点击{label}: {output}")
            return True
        self.log(f"[窗口{self.account.game_window_no}] Dm点击{label}失败: {output}")
        return False

    def _dm_chain(self, steps: list[str], label: str = "链式操作") -> bool:
        """一次子进程调用执行多个 Dm 操作（click/type），节省子进程启动开销。"""
        import subprocess
        helper = str(app_root() / "dm_click_helper.py")
        result = subprocess.run(
            ["py", "-3.14-32", helper, "chain", "|".join(steps)],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0:
            self.log(f"[窗口{self.account.game_window_no}] Dm{label}: {output}")
            return True
        self.log(f"[窗口{self.account.game_window_no}] Dm{label}失败: {output}")
        return False

    def _dm_type_text(self, text: str) -> bool:
        import subprocess

        helper = str(app_root() / "dm_click_helper.py")
        result = subprocess.run(
            ["py", "-3.14-32", helper, "type", text],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0:
            self.log(f"[窗口{self.account.game_window_no}] Dm输入: {output}")
            return True
        self.log(f"[窗口{self.account.game_window_no}] Dm输入失败: {output}")
        return False

    def _ocr_image_text(self, image, label: str) -> str:
        try:
            import pytesseract
        except Exception as exc:
            self.log(f"[窗口{self.account.game_window_no}] OCR 依赖不可用，无法校验{label}: {exc}")
            return ""
        parts: list[str] = []
        for psm in (6, 3):
            try:
                text = pytesseract.image_to_string(image, lang="chi_sim+eng", config=f"--psm {psm}")
            except Exception as exc:
                self.log(f"[窗口{self.account.game_window_no}] OCR校验{label}失败 psm={psm}: {exc}")
                continue
            if text:
                parts.append(text)
        merged = "\n".join(parts)
        self.log(f"[窗口{self.account.game_window_no}] OCR校验{label}: {_preview_text(merged, 160)}")
        return merged

    def _is_passport_dialog_visible_by_ocr(self, image) -> bool:
        # 快速视觉校验（免OCR），大多数弹窗可直接检出
        if self._looks_like_passport_dialog(image):
            return True
        # 快速排除：gray_ratio 极低说明肯定不是弹窗，跳过 OCR
        try:
            import numpy as np
            arr = np.array(image.convert("RGB"))
            h, w = arr.shape[:2]
            region = arr[int(h*0.18):int(h*0.72), int(w*0.22):int(w*0.80)]
            if region.size > 0:
                r, g, b = region[:,:,0].astype(int), region[:,:,1].astype(int), region[:,:,2].astype(int)
                gray_panel = (r>135)&(r<235)&(g>135)&(g<235)&(b>135)&(b<235)&(abs(r-g)<22)&(abs(g-b)<22)
                if float(gray_panel.mean()) < 0.10:
                    return False
        except Exception:
            pass
        # OCR 兜底
        text = self._ocr_image_text(image, "通行证弹窗")
        normalized = re.sub(r"\s+", "", text)
        targets = (
            self.settings.passport_dialog_text,
            self.settings.passport_dialog_visible_text,
            "通行证登录",
        )
        if any(target and target in normalized for target in targets) or ("通行证" in normalized and "登录" in normalized):
            return True
        if self._looks_like_passport_dialog(image):
            self.log(f"[窗口{self.account.game_window_no}] 视觉校验检测到通行证登录弹窗")
            return True
        return False

    def _looks_like_game_notice_page(self, image) -> bool:
        """识别登录成功后的游戏公告页，用于大窗口登录校验。"""
        import numpy as np

        if self._has_passport_page_evidence(image):
            return False

        arr = np.array(image.convert("RGB"))
        height, width = arr.shape[:2]
        if height < 300 or width < 240:
            return False

        center = arr[int(height * 0.12):int(height * 0.88), int(width * 0.10):int(width * 0.90)]
        if center.size == 0:
            return False
        r = center[:, :, 0].astype(int)
        g = center[:, :, 1].astype(int)
        b = center[:, :, 2].astype(int)
        gray_panel = (
            (r > 145)
            & (r < 235)
            & (g > 145)
            & (g < 235)
            & (b > 145)
            & (b < 235)
            & (abs(r - g) < 28)
            & (abs(g - b) < 28)
        )
        gray_ratio = float(gray_panel.mean())

        right_panel = arr[int(height * 0.10):int(height * 0.65), int(width * 0.78):int(width * 0.98)]
        right_bright_ratio = 0.0
        if right_panel.size:
            rr = right_panel[:, :, 0].astype(int)
            gg = right_panel[:, :, 1].astype(int)
            bb = right_panel[:, :, 2].astype(int)
            right_bright_ratio = float(((rr > 120) & (gg > 105) & (bb > 80)).mean())

        self.log(
            f"[窗口{self.account.game_window_no}] 游戏公告页视觉校验: "
            f"gray_ratio={gray_ratio:.3f}, right_bright_ratio={right_bright_ratio:.3f}"
        )
        return gray_ratio > 0.20 and right_bright_ratio > 0.04

    def _image_contains_text_or_hex(self, image, expected: str) -> bool:
        text = self._ocr_image_text(image, "通行证输入")
        if expected.lower() in text.lower():
            return True
        return extract_hex_passport(text) == expected.lower()

    def _looks_like_passport_dialog(self, image) -> bool:
        import numpy as np

        arr = np.array(image.convert("RGB"))
        height, width = arr.shape[:2]
        x1, x2 = int(width * 0.22), int(width * 0.80)
        y1, y2 = int(height * 0.18), int(height * 0.72)
        region = arr[y1:y2, x1:x2]
        if region.size == 0:
            return False
        r = region[:, :, 0].astype(int)
        g = region[:, :, 1].astype(int)
        b = region[:, :, 2].astype(int)
        gray_panel = (
            (r > 135)
            & (r < 235)
            & (g > 135)
            & (g < 235)
            & (b > 135)
            & (b < 235)
            & (abs(r - g) < 22)
            & (abs(g - b) < 22)
        )
        gray_ratio = float(gray_panel.mean())

        input_center = self._locate_passport_input_center(image, log_result=False)
        confirm_center = self._locate_confirm_button_center(image, log_result=False)
        self.log(
            f"[窗口{self.account.game_window_no}] 弹窗视觉校验: gray_ratio={gray_ratio:.3f}, "
            f"input={input_center or '无'}, confirm={confirm_center or '无'}"
        )
        return gray_ratio > 0.28 and input_center is not None and confirm_center is not None

    def _locate_passport_input_center(self, image, log_result: bool = True) -> tuple[int, int] | None:
        import cv2
        import numpy as np

        arr = np.array(image.convert("RGB"))
        height, width = arr.shape[:2]
        roi_left, roi_top = int(width * 0.25), int(height * 0.25)
        roi_right, roi_bottom = int(width * 0.78), int(height * 0.55)
        roi = arr[roi_top:roi_bottom, roi_left:roi_right]
        if roi.size == 0:
            return None
        r = roi[:, :, 0].astype(int)
        g = roi[:, :, 1].astype(int)
        b = roi[:, :, 2].astype(int)
        mask = (
            (r > 45)
            & (r < 135)
            & (g > 45)
            & (g < 135)
            & (b > 45)
            & (b < 135)
            & (abs(r - g) < 24)
            & (abs(g - b) < 24)
        ).astype("uint8") * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best: tuple[int, int, int, int] | None = None
        best_area = 0
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if w < 120 or h < 20 or h > 80:
                continue
            if area > best_area:
                best_area = area
                best = (roi_left + x, roi_top + y, w, h)
        if best is None:
            return None
        x, y, w, h = best
        center = (x + w // 2, y + h // 2)
        if log_result:
            self.log(f"[窗口{self.account.game_window_no}] 视觉定位输入框: center={center}, box=({x},{y},{w},{h})")
        return center

    def _locate_confirm_button_center(self, image, log_result: bool = True) -> tuple[int, int] | None:
        import cv2
        import numpy as np

        arr = np.array(image.convert("RGB"))
        height, width = arr.shape[:2]
        roi_left, roi_top = int(width * 0.35), int(height * 0.42)
        roi_right, roi_bottom = int(width * 0.85), int(height * 0.78)
        roi = arr[roi_top:roi_bottom, roi_left:roi_right]
        if roi.size == 0:
            return None
        r = roi[:, :, 0].astype(int)
        g = roi[:, :, 1].astype(int)
        b = roi[:, :, 2].astype(int)
        mask = ((r > 165) & (g > 125) & (b < 145) & (r >= g - 15)).astype("uint8") * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 收集所有符合尺寸的按钮候选
        candidates: list[tuple[int, int, int, int, int]] = []  # (x, y, w, h, area)
        for contour in contours:
            bx, by, bw, bh = cv2.boundingRect(contour)
            area = bw * bh
            if bw < 60 or bh < 20 or bh > 90:
                continue
            candidates.append((roi_left + bx, roi_top + by, bw, bh, area))

        if not candidates:
            return None

        # "确认"在弹窗内部右侧，"进入游戏"在弹窗下方外部
        # 选 y 最小（最高）且 x 较大的候选
        candidates.sort(key=lambda c: c[1])  # 按 y 排序（从上到下）
        # 取前两个候选中 x 较大的（确认在右侧）
        top_candidates = candidates[: min(2, len(candidates))]
        top_candidates.sort(key=lambda c: c[0], reverse=True)  # 按 x 降序
        x, y, w, h, area = top_candidates[0]

        center = (x + w // 2, y + h // 2)
        if log_result:
            self.log(
                f"[窗口{self.account.game_window_no}] 视觉定位确认按钮: "
                f"center={center}, box=({x},{y},{w},{h}), candidates={len(candidates)}"
            )
        return center

    def _close_m2_notice(self, page) -> None:
        width = int(self.settings.window_width)
        height = int(self.settings.window_height)
        points = [
            (width - 15, 15, "右上角关闭"),
            (int(width * 0.495), int(height * 0.897), "底部圆形关闭"),
            (int(width * 0.08), int(height * 0.08), "公告外区域"),
            (740, 680, "历史关闭坐标"),
        ]

        for attempt in range(1, max(1, self.settings.notice_close_retries) + 2):
            self._ensure_not_stopped()
            image = self._capture_page_image(page, f"m2_notice_before_{attempt}.png")
            if image is not None and not self._m2_notice_overlay_visible(image):
                self.log(f"[方式二] 公告检测：未发现遮挡弹窗（第{attempt}次检查）")
                return

            self.log(f"[方式二] 尝试关闭公告（第{attempt}次）")
            for x, y, label in points:
                if 0 <= x < width and 0 <= y < height:
                    self.log(f"[方式二] 点击公告关闭候选：{label} ({x},{y})")
                    page.mouse.click(x, y)
                    self._wait_or_stop(page, 180)

            self._wait_or_stop(page, 300)
            image = self._capture_page_image(page, f"m2_notice_after_{attempt}.png")
            if image is not None and not self._m2_notice_overlay_visible(image):
                self.log(f"[方式二] 公告关闭成功（第{attempt}次）")
                return
            if attempt <= self.settings.notice_close_retries:
                self.log("[方式二] 公告仍存在，继续重试")

        self._capture_page_image(page, "m2_notice_still_visible.png")
        raise RuntimeError("方式二公告关闭失败")

    def _capture_page_image(self, page, file_name: str | None = None):
        try:
            import io

            from PIL import Image

            data = page.screenshot(full_page=False)
            image = Image.open(io.BytesIO(data)).convert("RGB")
            if file_name:
                try:
                    image.save(str(self._debug_dir / file_name))
                except Exception:
                    pass
            return image
        except Exception as exc:
            self.log(f"[方式二] 公告截图检测失败: {exc}")
            return None

    @staticmethod
    def _m2_notice_overlay_visible(image) -> bool:
        import numpy as np

        arr = np.array(image.convert("RGB"))
        height, width = arr.shape[:2]
        center = arr[int(height * 0.08): int(height * 0.90), int(width * 0.26): int(width * 0.74)]
        if center.size == 0:
            return False

        r_arr = arr[:, :, 0].astype(int)
        g_arr = arr[:, :, 1].astype(int)
        b_arr = arr[:, :, 2].astype(int)
        center_r = center[:, :, 0].astype(int)
        center_g = center[:, :, 1].astype(int)
        center_b = center[:, :, 2].astype(int)

        bright_center = (
            (center_r > 210)
            & (center_g > 190)
            & (center_b > 160)
            & (abs(center_r - center_g) < 70)
        )
        orange_center = (
            (center_r > 180)
            & (center_g > 45)
            & (center_g < 130)
            & (center_b < 90)
        )
        dark_page = (r_arr < 70) & (g_arr < 70) & (b_arr < 70)

        bright_ratio = float(bright_center.mean())
        orange_ratio = float(orange_center.mean())
        dark_ratio = float(dark_page.mean())
        return bright_ratio > 0.16 and orange_ratio > 0.006 and dark_ratio > 0.30

    def _locate_passport_button(self, screenshot, use_fallback: bool = True) -> tuple[int, int] | None:
        """模板匹配定位通行证按钮，返回 viewport 中心坐标 (vx, vy) 或 None"""
        template_path = app_root() / self.settings.passport_btn_template
        if not template_path.exists():
            self.log(f"[窗口{self.account.game_window_no}] 通行证按钮模板不存在: {template_path}")
            return None
        import cv2
        import numpy as np
        screen_arr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        template = cv2.imdecode(np.fromfile(str(template_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if template is None:
            self.log(f"[窗口{self.account.game_window_no}] 无法读取模板: {template_path}")
            return None
        result = cv2.matchTemplate(screen_arr, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        th, tw = template.shape[:2]
        center_x = max_loc[0] + tw // 2
        center_y = max_loc[1] + th // 2
        if max_val < 0.6:
            self.log(
                f"[窗口{self.account.game_window_no}] 模板匹配得分偏低: {max_val:.3f}"
            )
            if use_fallback:
                self.log(f"[窗口{self.account.game_window_no}] 回退已知坐标")
                known = self.settings.passport_btn_viewport
                if known and known[0] > 0:
                    return (known[0], known[1])
                return None
            self.log(f"[窗口{self.account.game_window_no}] 不使用低分匹配结果，避免缓存错误坐标")
            return None
        self.log(
            f"[窗口{self.account.game_window_no}] 模板匹配成功: "
            f"({center_x},{center_y}) score={max_val:.3f}"
        )
        return (center_x, center_y)

    def _click_passport_button_dm(self, vx: int, vy: int) -> bool:
        """通过 Dm 子进程在 viewport (vx, vy) 处后台点击"""
        import subprocess
        pos_file = app_root() / "debug_ocr/browser_pos.json"
        if not pos_file.exists():
            self.log(f"[窗口{self.account.game_window_no}] browser_pos.json 不存在")
            return False
        helper = str(app_root() / "dm_click_helper.py")
        result = subprocess.run(
            ["py", "-3.14-32", helper, str(vx), str(vy)],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            self.log(f"[窗口{self.account.game_window_no}] Dm点击: viewport({vx},{vy})")
            return True
        self.log(f"[窗口{self.account.game_window_no}] Dm点击失败: {result.stderr}")
        return False

    def _click_target(self, page, selector: str, ratio: tuple[float, float], action_name: str) -> None:
        if selector:
            locator = self._first_visible_locator(page, selector)
            if locator is not None:
                self.log(f"[窗口{self.account.game_window_no}] 点击 {action_name} DOM 元素: {selector}")
                locator.click(timeout=3000)
                return
            self.log(f"[窗口{self.account.game_window_no}] 未找到 {action_name} DOM 元素，改用 viewport 坐标")
        self._click_ratio(page, ratio, f"点击 {action_name}")

    def _fill_passport(self, page, passport: str) -> None:
        if self.settings.passport_input_selector:
            locator = self._first_visible_locator(page, self.settings.passport_input_selector)
            if locator is not None:
                locator.fill(passport, timeout=3000)
                return
            self.log(f"[窗口{self.account.game_window_no}] 未找到通行证输入框 DOM 元素，改用 viewport 坐标")
        self._click_ratio(page, self.settings.passport_input_ratio, "点击通行证输入框")
        page.keyboard.press("Control+A")
        page.keyboard.type(passport, delay=25)

    def _is_notice_visible(self) -> bool:
        return self._selector_or_text_visible(self.settings.notice_selector, self.settings.notice_visible_text)

    def _run_game_steps_with_dm(self, page, passport: str) -> None:
        dm = DmClient(self.settings, lambda message: self.log(f"[窗口{self.account.game_window_no}] {message}"))
        title_keyword = self.settings.dm_window_title_keyword or page.title()
        try:
            dm.bind_browser_window(title_keyword)
            self._close_notice_with_dm(dm)
            self.update_status(self.account, "已关闭公告")
            self.update_status(self.account, "成功")
            self.log(f"[窗口{self.account.game_window_no}] 单窗口大漠测试完成：公告关闭成功")
        finally:
            dm.unbind()

    def _close_notice_with_dm(self, dm: DmClient) -> None:
        if not self.settings.notice_template_path:
            raise RuntimeError("未配置 notice_template_path，无法用找图校验公告是否关闭")
        for attempt in range(1, self.settings.notice_close_retries + 1):
            self._ensure_not_stopped()
            self.log(f"[窗口{self.account.game_window_no}] 尝试关闭公告（第{attempt}次）")
            dm.click_ratio(self.settings.notice_close_outside_ratio, "公告外区域")
            if dm.wait_until_template_gone(self.settings.notice_template_path, self.settings.state_check_timeout_ms):
                self.log(f"[窗口{self.account.game_window_no}] 公告关闭成功")
                return
            if attempt < self.settings.notice_close_retries:
                self.log(f"[窗口{self.account.game_window_no}] 公告仍存在，继续重试")
        self.log(f"[窗口{self.account.game_window_no}] 公告关闭失败")
        raise RuntimeError("公告关闭失败")

    def _close_notice_by_outside_click(self, page) -> None:
        for attempt in range(1, self.settings.notice_close_retries + 1):
            self._ensure_not_stopped()
            self.log(f"[窗口{self.account.game_window_no}] 尝试关闭公告（第{attempt}次）")
            self._click_ratio(page, self.settings.notice_close_outside_ratio, "点击公告外区域")
            if self._wait_state(page, lambda: not self._is_notice_visible()):
                self.log(f"[窗口{self.account.game_window_no}] 公告关闭成功")
                return
            if attempt < self.settings.notice_close_retries:
                self.log(f"[窗口{self.account.game_window_no}] 公告仍存在，继续重试")
        self.log(f"[窗口{self.account.game_window_no}] 公告关闭失败")
        raise RuntimeError("公告关闭失败")

    def _is_passport_dialog_visible(self) -> bool:
        return self._selector_or_text_visible(self.settings.passport_dialog_selector, self.settings.passport_dialog_visible_text)

    def _is_login_confirmed(self) -> bool:
        selector = self.settings.login_success_hidden_selector or self.settings.passport_dialog_selector
        text = self.settings.login_success_hidden_text or self.settings.passport_dialog_visible_text
        return not self._selector_or_text_visible(selector, text)

    def _selector_or_text_visible(self, selector: str, text: str) -> bool:
        if selector and self._first_visible_locator(self._page, selector) is not None:
            return True
        if text:
            return text in self._all_visible_text(self._page)
        return False

    def _first_visible_locator(self, page, selector: str):
        for frame in page.frames:
            try:
                locator = frame.locator(selector).first
                if locator.count() > 0 and locator.is_visible(timeout=500):
                    return locator
            except Exception:
                continue
        return None

    def _wait_state(self, page, predicate) -> bool:
        self._page = page
        waited_ms = 0
        step_ms = 250
        while waited_ms <= self.settings.state_check_timeout_ms:
            self._ensure_not_stopped()
            try:
                if predicate():
                    return True
            except Exception:
                pass
            self._wait_or_stop(page,step_ms)
            waited_ms += step_ms
        return False


def _remember_open_session(playwright: object, browser: object) -> None:
    with _OPEN_SESSIONS_LOCK:
        _OPEN_SESSIONS.append((playwright, browser))
