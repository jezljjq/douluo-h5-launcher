from __future__ import annotations

import re
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir

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


class AccountRunner:
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

    def run(self) -> bool:
        playwright = None
        browser = None
        keep_open = False
        try:
            self._ensure_not_stopped()
            self.update_status(self.account, "打开中")
            self._vlog("debug", f"[窗口{self.account.game_window_no}] 打开链接: {self.account.url}")

            from playwright.sync_api import sync_playwright

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
            page.wait_for_timeout(self.settings.qr_login_page_wait_ms)
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
            page.wait_for_timeout(self.settings.after_passport_extract_wait_ms)
            self._ensure_not_stopped()

            self.log(f"[窗口{self.account.game_window_no}] 等待游戏页面加载")
            page.wait_for_timeout(self.settings.after_goto_wait_ms)
            if self.settings.dm_enabled:
                self._run_game_steps_with_dm(page, passport)
                keep_open = True
                _remember_open_session(playwright, browser)
                return True

            self._close_notice_by_outside_click(page)
            self.update_status(self.account, "已关闭公告")
            page.wait_for_timeout(self.settings.after_notice_wait_ms)
            self._ensure_not_stopped()

            self.log(f"[窗口{self.account.game_window_no}] 尝试点击通行证按钮")
            self._click_target(page, self.settings.passport_button_selector, self.settings.passport_button_ratio, "通行证按钮")
            if not self._wait_state(page, self._is_passport_dialog_visible):
                self.log(f"[窗口{self.account.game_window_no}] 通行证弹窗未出现")
                raise RuntimeError("通行证弹窗未出现")
            self.log(f"[窗口{self.account.game_window_no}] 通行证弹窗已出现")
            page.wait_for_timeout(self.settings.after_passport_button_wait_ms)
            self._ensure_not_stopped()

            self.log(f"[窗口{self.account.game_window_no}] 尝试输入通行证")
            self._fill_passport(page, passport)
            self.update_status(self.account, "已输入通行证")
            self.log(f"[窗口{self.account.game_window_no}] 输入通行证成功")
            self._ensure_not_stopped()

            self.log(f"[窗口{self.account.game_window_no}] 尝试点击确认")
            self._click_target(page, self.settings.confirm_button_selector, self.settings.confirm_button_ratio, "确认按钮")
            page.wait_for_timeout(self.settings.after_submit_wait_ms)
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

    def run_game_flow(self) -> bool:
        """完整单账号流程：OCR通行证 → 打开游戏页 → 关闭公告 → 输入通行证 → 确认。

        成功时关闭浏览器，失败时保留浏览器便于排查。
        通行证过期自动刷新重试（最多1次）。
        """
        playwright = None
        browser = None
        keep_open = True
        passport = None

        for retry in range(2):
            try:
                self._clean_tmp()
                # === 步骤1：OCR 提取通行证 ===
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
                        # 等 2 秒再试一次，仍无二维码则视为登录成功
                        self.log(
                            f"[窗口{self.account.game_window_no}] "
                            f"重试OCR未检测到通行证，等待后二次确认"
                        )
                        import time as _t3
                        _t3.sleep(2)
                        new_passport2, _ = self._extract_passport_from_login_window()
                        if new_passport2 is None:
                            self.update_status(self.account, "成功")
                            self.log(f"[窗口{self.account.game_window_no}] 登录成功（QR码消失）")
                            keep_open = False
                            self._clean_tmp()
                            return True
                        new_passport = new_passport2
                    elif retry == 0:
                        # 首次 OCR 返回空：已登录 / 窗口无QR码
                        # 等 2 秒再确认一次
                        self.log(
                            f"[窗口{self.account.game_window_no}] "
                            f"未检测到通行证，可能已登录，等待二次确认"
                        )
                        import time as _t3
                        _t3.sleep(2)
                        new_passport2, _ = self._extract_passport_from_login_window()
                        if new_passport2 is None:
                            self.update_status(self.account, "成功")
                            self.log(f"[窗口{self.account.game_window_no}] 已登录（无QR码）")
                            keep_open = False
                            self._clean_tmp()
                            return True
                        new_passport = new_passport2
                    elif self.request_passport is not None:
                        new_passport = self.request_passport(self.account)
                if not new_passport:
                    raise RuntimeError("未能提取通行证")
                if passport is not None and new_passport == passport:
                    raise RuntimeError(
                        f"登录失败，通行证未刷新 ({passport})，登录程序窗口仍显示QR页面"
                    )
                passport = new_passport
                self.log(f"[窗口{self.account.game_window_no}] 通行证: {passport} (来源={source})")
                if self.passport_found is not None:
                    self.passport_found(self.account, passport)
                self.update_status(self.account, "已提取通行证")
                self._clean_tmp()

                # === 步骤2：打开浏览器游戏页 ===
                self._ensure_not_stopped()
                self.update_status(self.account, "打开中")
                self._vlog("debug", f"[窗口{self.account.game_window_no}] 打开链接: {self.account.url}")
                from playwright.sync_api import sync_playwright
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
                page.wait_for_timeout(self.settings.after_goto_wait_ms)
                self._ensure_not_stopped()

                # === 步骤3：关闭公告 ===
                self.update_status(self.account, "关闭公告")
                for _ in range(2):
                    page.mouse.click(740, 680)
                    page.wait_for_timeout(300)
                page.wait_for_timeout(600)
                self.update_status(self.account, "已关闭公告")
                self.log(f"[窗口{self.account.game_window_no}] 公告已关闭（canvas 右下角点击）")
                page.wait_for_timeout(self.settings.after_notice_wait_ms)
                self._ensure_not_stopped()

                # === 步骤4：点击通行证按钮（带重试，容错鼠标干扰） ===
                self.log(f"[窗口{self.account.game_window_no}] 定位并点击通行证按钮")
                dialog_visible = False
                for btn_retry in range(3):
                    browser_hwnd = self._find_game_browser_window()
                    if browser_hwnd is None:
                        self.log(f"[窗口{self.account.game_window_no}] 未找到浏览器窗口，等待后重试...")
                        page.wait_for_timeout(1000)
                        continue
                    self._write_browser_pos(browser_hwnd)
                    _client = self._capture_browser_client(browser_hwnd, "flow_step4_button_match_source.png")
                    btn_pos = self._locate_passport_button(_client)
                    if btn_pos is None:
                        self.log(f"[窗口{self.account.game_window_no}] 模板匹配失败（可能被遮挡），重试截图定位...")
                        page.wait_for_timeout(500)
                        continue
                    for click_i, (vx, vy) in enumerate(self._passport_button_click_points(btn_pos), start=1):
                        self.log(f"[窗口{self.account.game_window_no}] 点击通行证按钮（第{click_i}次）: viewport({vx},{vy})")
                        if not self._dm_click_viewport(vx, vy, "通行证按钮", hold_ms=150):
                            continue
                        page.wait_for_timeout(500)
                        after_click = self._capture_browser_client(browser_hwnd, f"flow_step4_after_passport_click_{click_i}.png")
                        if self._is_passport_dialog_visible_by_ocr(after_click):
                            dialog_visible = True
                            break
                        self.log(f"[窗口{self.account.game_window_no}] 弹窗未出现")
                    if dialog_visible:
                        break
                    self.log(f"[窗口{self.account.game_window_no}] 第{btn_retry+1}轮点击未触发弹窗，重新定位...")
                if not dialog_visible and not self._wait_state(page, self._is_passport_dialog_visible):
                    raise RuntimeError("通行证弹窗未出现（已重试3轮）")
                self.log(f"[窗口{self.account.game_window_no}] 通行证弹窗已出现")
                page.wait_for_timeout(self.settings.after_passport_button_wait_ms)
                self._ensure_not_stopped()
                dialog_image = self._capture_browser_client(browser_hwnd, "flow_step4_dialog_visible.png")

                # === 步骤5：输入通行证 ===
                self.update_status(self.account, "输入中")
                self.log(f"[窗口{self.account.game_window_no}] 输入通行证: {passport}")
                input_center = self._locate_passport_input_center(dialog_image)
                if input_center is None:
                    input_center = (
                        int(self.settings.window_width * self.settings.passport_input_ratio[0]),
                        int(self.settings.window_height * self.settings.passport_input_ratio[1]),
                    )
                    self.log(f"[窗口{self.account.game_window_no}] 未视觉定位到输入框，回退坐标: {input_center}")
                input_x, input_y = input_center
                if not self._dm_click_viewport(input_x, input_y, "通行证输入框", hold_ms=120):
                    raise RuntimeError("Dm 点击通行证输入框失败")
                page.wait_for_timeout(300)
                if not self._dm_type_text(passport):
                    raise RuntimeError("Dm 输入通行证失败")
                page.wait_for_timeout(800)
                self.update_status(self.account, "已输入通行证")
                self.log(f"[窗口{self.account.game_window_no}] 输入通行证成功（Dm 剪贴板粘贴）")
                self._ensure_not_stopped()

                # === 步骤6：点击确认 ===
                self.log(f"[窗口{self.account.game_window_no}] 点击确认按钮")
                input_check = self._capture_browser_client(browser_hwnd, "flow_step5_after_input.png")
                confirm_center = self._locate_confirm_button_center(input_check)
                if confirm_center is None:
                    confirm_center = (
                        int(self.settings.window_width * self.settings.confirm_button_ratio[0]),
                        int(self.settings.window_height * self.settings.confirm_button_ratio[1]),
                    )
                    self.log(f"[窗口{self.account.game_window_no}] 未视觉定位到确认按钮，回退坐标: {confirm_center}")
                confirm_x, confirm_y = confirm_center
                if not self._dm_click_viewport(confirm_x, confirm_y, "确认按钮", hold_ms=150):
                    raise RuntimeError("Dm 点击确认按钮失败")
                page.wait_for_timeout(self.settings.after_submit_wait_ms)

                # === 步骤7：校验登录成功 ===
                page.wait_for_timeout(2000)
                self.log(f"[窗口{self.account.game_window_no}] 校验登录程序窗口：检测QR页面是否消失")
                login_passport_after, _ = self._extract_passport_from_login_window()
                if login_passport_after is None:
                    self.update_status(self.account, "成功")
                    self.log(f"[窗口{self.account.game_window_no}] 登录成功（QR码消失）")
                    keep_open = False
                    self._clean_tmp()
                    return True

                # QR页面仍存在 → 检查通行证是否刷新
                if login_passport_after != passport and retry == 0:
                    self.log(
                        f"[窗口{self.account.game_window_no}] 通行证已刷新: "
                        f"{passport} → {login_passport_after}，重试"
                    )
                    self._cleanup_for_retry(browser, playwright)
                    browser = None
                    playwright = None
                    continue  # 重新OCR+登录

                # 通行证相同 → 等待窗口刷新后再 OCR 一次确认
                self.log(
                    f"[窗口{self.account.game_window_no}] 通行证未刷新({passport})，"
                    f"等待 {self.settings.after_submit_wait_ms}ms 后重新确认"
                )
                page.wait_for_timeout(self.settings.after_submit_wait_ms)
                login_passport_after2, _ = self._extract_passport_from_login_window()
                if login_passport_after2 is None:
                    self.update_status(self.account, "成功")
                    self.log(f"[窗口{self.account.game_window_no}] 登录成功（二次确认QR码消失）")
                    keep_open = False
                    self._clean_tmp()
                    return True
                if login_passport_after2 != passport and retry == 0:
                    self.log(
                        f"[窗口{self.account.game_window_no}] 通行证已刷新(二次确认): "
                        f"{passport} → {login_passport_after2}，重试"
                    )
                    self._cleanup_for_retry(browser, playwright)
                    browser = None
                    playwright = None
                    continue

                # 两次确认都是相同通行证 → 尝试 OCR 候选替换
                candidates = self._generate_passport_candidates(passport)
                if candidates:
                    self.log(
                        f"[窗口{self.account.game_window_no}] "
                        f"OCR 可能误读，尝试候选: {', '.join(candidates[:3])}"
                    )
                    for cand in candidates[:3]:
                        self._dm_click_viewport(input_x, input_y, "输入框(候选)", hold_ms=120)
                        page.wait_for_timeout(200)
                        self._dm_type_text(cand)
                        page.wait_for_timeout(800)
                        self._dm_click_viewport(confirm_x, confirm_y, "确认(候选)", hold_ms=150)
                        page.wait_for_timeout(3000)
                        cand_verify, _ = self._extract_passport_from_login_window()
                        if cand_verify is None:
                            self.update_status(self.account, "成功")
                            self.log(
                                f"[窗口{self.account.game_window_no}] "
                                f"候选 {cand} 登录成功"
                            )
                            keep_open = False
                            self._clean_tmp()
                            return True
                        self.log(
                            f"[窗口{self.account.game_window_no}] 候选 {cand} 未成功"
                        )
                raise RuntimeError(
                    f"登录失败，登录程序窗口仍显示QR页面 (passport={login_passport_after2})"
                )

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

    _LOG_LEVELS = {"quiet": 0, "normal": 1, "debug": 2}

    def _vlog(self, level: str, msg: str) -> None:
        if self._LOG_LEVELS.get(level, 1) <= self._LOG_LEVELS.get(self.settings.log_level, 1):
            self.log(msg)

    @staticmethod
    def _generate_passport_candidates(passport: str) -> list[str]:
        """OCR 常见混淆字符的候选替换。最多返回 3 个。"""
        swaps = {
            "c": "e", "e": "c",
            "0": "o", "o": "0",
            "1": "l", "l": "1",
            "5": "s", "s": "5",
            "8": "b", "6": "b", "b": ["8", "6"],
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
        _sp.run(["taskkill", "/f", "/im", "chromium.exe"], capture_output=True)
        _sp.run(["taskkill", "/f", "/im", "chrome.exe"], capture_output=True)
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
        """失败时移动 _tmp/ 内容到 _error/，保留排查现场"""
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
            page.wait_for_timeout(step_ms)
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

        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        prefix = f"login_hwnd{selected.hwnd}_{stamp}"
        raw_path = self._tmp_path(f"{prefix}_01_login_window_full.png")
        image = capture_window_background(selected).convert("RGB")
        image.save(raw_path)
        self._vlog("debug", f"[窗口{self.account.game_window_no}] 后台截图 hwnd={selected.hwnd} title={selected.title}")
        self._vlog("debug", f"[窗口{self.account.game_window_no}] 临时截图已保存: _tmp/{raw_path.name}")

        passport = self._ocr_passport_from_login_image(image, prefix, raw_path)
        if passport:
            return passport, "ocr"
        return None, ""

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
        try:
            font = ImageFont.truetype("consola.ttf", font_size)
        except Exception:
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
                m = re.search(r":\s*(\S{7,10})(?:\s|$)", text)
                if m:
                    hex_val = extract_hex_passport(m.group(1))
                    if hex_val:
                        self.log(f"[窗口{self.account.game_window_no}] 全图OCR灰度成功(冒号模式): {hex_val}")
                        _add_result(hex_val, gray.copy())

        if not results:
            self.log(f"[窗口{self.account.game_window_no}] 全图OCR未能识别到8位hex通行证")
            return None

        # 投票策略：优先选包含 a-f 的结果（避免全数字 d→0 误判）
        mixed = {k: v for k, v in results.items() if any(c in "abcdef" for c in k)}
        candidates = mixed if mixed else results
        # 按出现次数降序取最佳
        best = max(candidates, key=lambda k: candidates[k])
        self.log(
            f"[窗口{self.account.game_window_no}] OCR投票: "
            f"共{len(results)}种结果, "
            f"选择 {best} (票数={candidates[best]}/{sum(results.values())})"
        )

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

    def _locate_qr_box(self, image) -> tuple[int, int, int, int] | None:
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
        pixels = rgb.load()

        scan_start = qr_bottom
        scan_end = min(height, qr_bottom + 120)

        best_top = None
        best_bottom = None
        best_red_count = 0

        # 逐行扫描，统计每行红色像素占比
        min_red_ratio = 0.15
        consecutive_red_rows = 0
        streak_start = None

        for y in range(scan_start, scan_end):
            red_count = 0
            row_width = width - 40  # 左右各留 20px margin
            for x in range(20, width - 20):
                r, g, b = pixels[x, y]
                if r > 100 and r > g * 1.3 and r > b * 1.3:
                    red_count += 1
            red_ratio = red_count / max(row_width, 1)

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
        import time as _t
        _t.sleep(0.1)

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
        if file_name:
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

    def _locate_passport_button(self, screenshot) -> tuple[int, int] | None:
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
        if max_val < 0.6:
            self.log(
                f"[窗口{self.account.game_window_no}] 模板匹配得分过低: {max_val:.3f}，"
                f"回退已知坐标"
            )
            known = self.settings.passport_btn_viewport
            if known and known[0] > 0:
                return (known[0], known[1])
            return None
        th, tw = template.shape[:2]
        center_x = max_loc[0] + tw // 2
        center_y = max_loc[1] + th // 2
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
            page.wait_for_timeout(step_ms)
            waited_ms += step_ms
        return False


def _remember_open_session(playwright: object, browser: object) -> None:
    with _OPEN_SESSIONS_LOCK:
        _OPEN_SESSIONS.append((playwright, browser))
