from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from ctypes import wintypes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from douluo_launcher.config import (
    AccountConfig,
    AutomationSettings,
    app_root,
    load_accounts_from_bookmark_root,
    load_accounts_from_bookmarks,
    load_settings,
)
from douluo_launcher.automation import extract_passport_from_login_image
from douluo_launcher.background_login import BackgroundSingleAccountRunner, _LoginWindowSnapshot
from douluo_launcher.window_manager import (
    SMTO_ABORTIFHUNG,
    WM_CLOSE,
    get_window_class_name,
    get_window_process_path,
    get_window_process_id,
    get_window_rect,
    launch_game_process,
    list_game_windows,
    user32,
)
from douluo_launcher.window_manager_settings import load_window_manager_settings
from douluo_launcher.window_operator import BackgroundOperator, build_probe_result, images_changed


DEFAULT_DEBUG_DIR = app_root() / "debug_background"
DEFAULT_CLICK_POINT = (160, 270)
DEFAULT_PASSPORT_BUTTON_RATIO = (0.90, 0.50)
DEFAULT_INPUT_BOX_RATIO = (0.50, 0.55)
DEFAULT_INPUT_TEXT = "a1b2c3d4"
DEFAULT_LAUNCH_WAIT_SECONDS = 20.0
DEFAULT_AFTER_LAUNCH_WAIT_SECONDS = 2.5
DEFAULT_AFTER_GAME_URL_WAIT_SECONDS = 6.0
POLL_INTERVAL_SECONDS = 0.5
INPUT_METHODS = ("wm_char", "key_sequence", "send_message")
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102


@dataclass
class BrowserProbeSession:
    playwright: object
    browser: object
    page: object

    def close(self) -> None:
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self.playwright.stop()
        except Exception:
            pass


def parse_point(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    raw = value.replace("，", ",").strip()
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("坐标格式应为 x,y，例如 260,420")
    return int(parts[0]), int(parts[1])


def point_from_ratio(image, ratio: tuple[float, float]) -> tuple[int, int]:
    width, height = image.size
    return (
        max(0, min(width - 1, int(width * ratio[0]))),
        max(0, min(height - 1, int(height * ratio[1]))),
    )


def pick_probe_hwnd(explicit_hwnd: int | None, title_template: str, game_exe_path: str) -> tuple[int | None, str]:
    if explicit_hwnd:
        return int(explicit_hwnd), f"使用指定 hwnd={explicit_hwnd}"
    windows = list_game_windows(
        title_template=title_template,
        game_exe_path=game_exe_path or None,
        allow_unnumbered=False,
        expected_window_size=None,
    )
    if not windows:
        return None, "未识别到编号游戏窗口，请用 --hwnd 指定窗口"
    first = windows[0]
    return int(first.hwnd), f"自动选择第一个游戏窗口 hwnd={first.hwnd} title={first.title}"


def scan_probe_windows(title_template: str, game_exe_path: str):
    return list_game_windows(
        title_template=title_template,
        game_exe_path=game_exe_path or None,
        allow_unnumbered=True,
        expected_window_size=None,
    )


def normalize_path_for_compare(path: str | Path | None) -> str:
    return str(path or "").strip().strip('"').replace("/", "\\").lower()


def select_account_url(accounts: list[AccountConfig], account_layer: str, account_index: int) -> str:
    clean_layer = str(account_layer or "").strip()
    wanted_index = int(account_index)
    for account in accounts:
        if account.level == clean_layer and int(account.bookmark_no) == wanted_index:
            return account.url
    raise ValueError(f"未找到收藏夹账号链接：层级={clean_layer} 编号={wanted_index}")


def load_bookmark_account_url(
    *,
    bookmark_url: str,
    account_layer: str,
    account_index: int | None,
    settings_path: str | Path,
) -> tuple[str, str]:
    direct_url = str(bookmark_url or "").strip()
    if direct_url:
        return direct_url, "使用 --bookmark-url 指定链接"
    if not account_layer or account_index is None:
        raise ValueError("缺少 --bookmark-url，或 --account-layer / --account-index")
    settings = load_settings(settings_path)
    if not settings.bookmark_file:
        raise ValueError(f"配置中没有 bookmark_file，无法读取收藏夹账号：{settings_path}")
    if settings.bookmark_root_path:
        accounts = load_accounts_from_bookmark_root(
            settings.bookmark_file,
            settings.bookmark_root_path,
            settings.level_names,
            account_group_settings=settings.account_group_settings,
        )
    else:
        accounts = load_accounts_from_bookmarks(
            settings.bookmark_file,
            settings.bookmark_root_name,
            settings.level_names,
            account_group_settings=settings.account_group_settings,
        )
    url = select_account_url(accounts, account_layer, int(account_index))
    return url, f"从收藏夹读取账号链接：层级={account_layer} 编号={account_index}"


def select_new_test_window(
    before_hwnds: set[int],
    after_windows,
    *,
    game_exe_path: str = "",
    process_path_getter=get_window_process_path,
):
    new_windows = [window for window in after_windows if int(window.hwnd) not in before_hwnds]
    expected_path = normalize_path_for_compare(game_exe_path)
    if expected_path:
        for window in new_windows:
            try:
                actual_path = normalize_path_for_compare(process_path_getter(int(window.hwnd)))
            except Exception:
                actual_path = ""
            if actual_path == expected_path:
                return window
    for window in new_windows:
        return window
    return None


def scan_browser_windows():
    try:
        from douluo_launcher.dm_client import list_browser_windows

        return list_browser_windows("")
    except Exception:
        return []


def select_new_browser_window(before_hwnds: set[int], after_windows):
    new_windows = [window for window in after_windows if int(window.hwnd) not in before_hwnds]
    for window in new_windows:
        return window
    return None


def wait_for_new_browser_window(
    *,
    before_hwnds: set[int],
    timeout_seconds: float = DEFAULT_LAUNCH_WAIT_SECONDS,
):
    deadline = time.time() + float(timeout_seconds)
    last_windows = []
    while time.time() < deadline:
        last_windows = scan_browser_windows()
        new_window = select_new_browser_window(before_hwnds, last_windows)
        if new_window is not None:
            return new_window, last_windows
        time.sleep(POLL_INTERVAL_SECONDS)
    return None, last_windows


def wait_for_new_test_window(
    *,
    before_hwnds: set[int],
    title_template: str,
    game_exe_path: str,
    timeout_seconds: float = DEFAULT_LAUNCH_WAIT_SECONDS,
):
    deadline = time.time() + float(timeout_seconds)
    last_windows = []
    while time.time() < deadline:
        last_windows = scan_probe_windows(title_template, game_exe_path)
        new_window = select_new_test_window(
            before_hwnds,
            last_windows,
            game_exe_path=game_exe_path,
        )
        if new_window is not None:
            return new_window, last_windows
        time.sleep(POLL_INTERVAL_SECONDS)
    return None, last_windows


def close_test_window(
    hwnd: int,
    *,
    user32=user32,
    timeout_seconds: float = 5.0,
) -> bool:
    hwnd = int(hwnd)
    posted = bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
    if not posted:
        return False
    deadline = time.time() + float(timeout_seconds)
    timeout_sent = False
    while time.time() < deadline:
        try:
            if not bool(user32.IsWindow(hwnd)):
                return True
        except Exception:
            return True
        if not timeout_sent and hasattr(user32, "SendMessageTimeoutW"):
            timeout_sent = True
            try:
                result = wintypes.DWORD()
                user32.SendMessageTimeoutW(
                    wintypes.HWND(hwnd),
                    WM_CLOSE,
                    0,
                    0,
                    SMTO_ABORTIFHUNG,
                    1000,
                    ctypes.byref(result),
                )
            except Exception:
                pass
        time.sleep(0.1)
    return False


def window_summary(window) -> dict[str, object]:
    return {"hwnd": int(window.hwnd), "title": str(window.title)}


def enum_child_windows(hwnd: int) -> list[dict[str, object]]:
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
            title = _get_window_text(child)
        except Exception:
            title = ""
        try:
            pid = get_window_process_id(child)
        except Exception:
            pid = 0
        children.append(
            {
                "hwnd": child,
                "class_name": class_name,
                "title": title,
                "rect": rect_payload,
                "pid": int(pid or 0),
            }
        )
        return True

    try:
        user32.EnumChildWindows(int(hwnd), callback, 0)
    except Exception:
        return children
    return children


def _get_window_text(hwnd: int) -> str:
    import ctypes

    length = int(user32.GetWindowTextLengthW(int(hwnd)))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(int(hwnd), buffer, length + 1)
    return buffer.value


def candidate_input_hwnds(top_hwnd: int, children: list[dict[str, object]], target_child: int | None = None) -> list[int]:
    if target_child:
        return [int(target_child)]
    candidates = [int(top_hwnd)]
    preferred_keywords = ("Chrome", "Chromium", "WebView", "RenderWidget", "Internet Explorer", "Qt", "Cef")
    for child in children:
        class_name = str(child.get("class_name", ""))
        if any(keyword.lower() in class_name.lower() for keyword in preferred_keywords):
            candidates.append(int(child["hwnd"]))
    for child in children:
        hwnd = int(child["hwnd"])
        if hwnd not in candidates:
            candidates.append(hwnd)
    return candidates


def input_method_labels(value: str) -> list[str]:
    method = str(value or "wm_char").strip().lower()
    if method == "all":
        return list(INPUT_METHODS)
    if method not in INPUT_METHODS:
        raise argparse.ArgumentTypeError(f"--input-method 仅支持 {', '.join((*INPUT_METHODS, 'all'))}")
    return [method]


def crop_input_box_region(image, point: tuple[int, int]):
    width, height = image.size
    x, y = point
    crop_width = max(160, int(width * 0.34))
    crop_height = max(45, int(height * 0.10))
    left = max(0, int(x - crop_width // 2))
    top = max(0, int(y - crop_height // 2))
    right = min(width, left + crop_width)
    bottom = min(height, top + crop_height)
    return image.crop((left, top, right, bottom))


def render_child_info(children: list[dict[str, object]]) -> dict[str, object] | None:
    for child in children:
        class_name = str(child.get("class_name", ""))
        if "Chrome_RenderWidgetHostHWND".lower() in class_name.lower():
            return child
    return None


def translate_window_point_to_child(
    top_hwnd: int,
    child: dict[str, object] | None,
    point: tuple[int, int],
) -> tuple[int, tuple[int, int], str]:
    if not child:
        return int(top_hwnd), (int(point[0]), int(point[1])), "top_window"
    try:
        top_rect = get_window_rect(int(top_hwnd))
        child_rect = child.get("rect", [0, 0, 0, 0])
        child_left, child_top, child_right, child_bottom = [int(value) for value in child_rect]
        offset_x = child_left - int(top_rect.left)
        offset_y = child_top - int(top_rect.top)
        child_x = int(point[0]) - offset_x
        child_y = int(point[1]) - offset_y
        if 0 <= child_x <= child_right - child_left and 0 <= child_y <= child_bottom - child_top:
            return int(child["hwnd"]), (child_x, child_y), "render_child"
    except Exception:
        pass
    return int(top_hwnd), (int(point[0]), int(point[1])), "top_window"


def background_click_window_point(
    operator: BackgroundOperator,
    top_hwnd: int,
    point: tuple[int, int],
    children: list[dict[str, object]],
):
    target_hwnd, target_point, target_kind = translate_window_point_to_child(
        top_hwnd,
        render_child_info(children),
        point,
    )
    result = operator.click(target_hwnd, target_point[0], target_point[1])
    detail = {
        "source_point": [int(point[0]), int(point[1])],
        "target_hwnd": int(target_hwnd),
        "target_point": [int(target_point[0]), int(target_point[1])],
        "target_kind": target_kind,
        "result": result.detail,
    }
    return result, detail


def detect_blocking_overlay(image) -> bool:
    text = ocr_image_text(image)
    normalized = str(text or "").replace(" ", "")
    if any(marker in normalized for marker in ("公告", "选择区服", "最近登录")):
        return True
    return detect_large_center_gray_panel(image)


def detect_large_center_gray_panel(image) -> bool:
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


def close_blocking_overlay_like_notice(
    *,
    operator: BackgroundOperator,
    hwnd: int,
    first_image,
    children: list[dict[str, object]],
    output_dir: Path,
    max_attempts: int = 3,
) -> tuple[bool, object, list[str]]:
    notes: list[str] = []
    current = first_image
    current.save(output_dir / "blocking_overlay_before.png")
    if not detect_blocking_overlay(current):
        notes.append("未检测到公告/区服等阻塞弹窗")
        return True, current, notes
    ratios = ((0.22, 0.18), (0.78, 0.18), (0.78, 0.80))
    for attempt in range(1, int(max_attempts) + 1):
        point = point_from_ratio(current, ratios[(attempt - 1) % len(ratios)])
        click_result, detail = background_click_window_point(operator, hwnd, point, children)
        notes.append(f"尝试关闭阻塞弹窗（第{attempt}次）point={point} detail={detail}")
        time.sleep(0.5)
        try:
            after = operator.screenshot(hwnd)
            after.save(output_dir / f"blocking_overlay_after_{attempt}.png")
        except Exception as exc:
            notes.append(f"关闭阻塞弹窗后截图失败：{exc}")
            continue
        if click_result.success and not detect_blocking_overlay(after):
            notes.append("阻塞弹窗关闭成功")
            return True, after, notes
        current = after
    notes.append("阻塞弹窗关闭失败")
    close_point = estimate_center_overlay_close_point(current)
    if close_point is not None:
        click_result, detail = background_click_window_point(operator, hwnd, close_point, children)
        notes.append(f"外点关闭失败，尝试点击阻塞弹窗关闭点 point={close_point} detail={detail}")
        time.sleep(0.5)
        try:
            after_close = operator.screenshot(hwnd)
            after_close.save(output_dir / "blocking_overlay_after_close_button.png")
            if click_result.success and not detect_blocking_overlay(after_close):
                notes.append("阻塞弹窗关闭点点击成功")
                return True, after_close, notes
            current = after_close
        except Exception as exc:
            notes.append(f"点击阻塞弹窗关闭点后截图失败：{exc}")
    return False, current, notes


def estimate_center_overlay_close_point(image) -> tuple[int, int] | None:
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
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        best: tuple[int, int, int, int, int] | None = None
        for index in range(1, count):
            x, y, w, h, area = [int(value) for value in stats[index]]
            if area < width * height * 0.04:
                continue
            if w < width * 0.20 or h < height * 0.20:
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


def locate_passport_button_by_template(image, template_path: Path | None = None) -> tuple[tuple[int, int] | None, float | None]:
    path = template_path or (app_root() / "debug_ocr" / "template_passport_btn.png")
    if not path.exists():
        return None, None
    try:
        import cv2
        import numpy as np

        source = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        template_bytes = np.fromfile(str(path), dtype=np.uint8)
        template = cv2.imdecode(template_bytes, cv2.IMREAD_COLOR)
        if template is None or template.size == 0:
            return None, None
        result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        center = (int(max_loc[0] + template.shape[1] / 2), int(max_loc[1] + template.shape[0] / 2))
        if float(max_val) < 0.55:
            return None, float(max_val)
        return center, float(max_val)
    except Exception:
        return None, None


def verify_input_text_visible(image, expected_text: str, *, ocr_func=None) -> bool:
    expected = "".join(ch for ch in str(expected_text or "").lower() if ch.isalnum())
    if not expected:
        return False
    try:
        if ocr_func is None:
            import pytesseract

            text = pytesseract.image_to_string(image, lang="eng", config="--psm 6")
        else:
            text = ocr_func(image)
    except Exception:
        return False
    normalized = "".join(ch for ch in str(text or "").lower() if ch.isalnum())
    return expected in normalized


def input_box_has_visual_text_change(before_crop, after_crop) -> bool:
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
        diff = np.abs(after_brightness.astype("float32") - before_brightness.astype("float32"))
        changed_in_field = int(((diff > 18) & dark_field_mask).sum())
        before_light = int(((before_brightness > 130) & dark_field_mask).sum())
        after_light = int(((after_brightness > 130) & dark_field_mask).sum())
        return bool(changed_in_field >= 20 and after_light > before_light + 8)
    except Exception:
        return images_changed(before_crop, after_crop, threshold=0.003)


def ocr_image_text(image, *, lang: str = "chi_sim+eng") -> str:
    try:
        import pytesseract

        return pytesseract.image_to_string(image, lang=lang, config="--psm 6")
    except Exception:
        return ""


def classify_game_page_text(text: str) -> str:
    normalized = str(text or "").replace(" ", "")
    if "本次通行证" in normalized or "扫码登录" in normalized:
        return "login_qr_page"
    formal_markers = ("进入游戏", "公告", "用户协议", "隐私政策", "选服")
    if any(marker in normalized for marker in formal_markers):
        return "formal_game_page"
    return "unknown"


def classify_game_page_image(image) -> tuple[str, str]:
    text = ocr_image_text(image)
    return classify_game_page_text(text), text


def build_passport_copy_context(
    *,
    hwnd: int,
    title: str,
    image_size: tuple[int, int] | list[int] | None,
    method_results: list[dict[str, object]],
    child_hwnd_list: list[dict[str, object]],
    clipboard_used: bool,
    clipboard_restored: bool,
    final_reason: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    context: dict[str, object] = {
        "hwnd": int(hwnd),
        "title": str(title),
        "image_size": list(image_size) if image_size is not None else None,
        "method_results": method_results,
        "child_hwnd_list": child_hwnd_list,
        "clipboard_used": bool(clipboard_used),
        "clipboard_restored": bool(clipboard_restored),
        "final_reason": str(final_reason),
    }
    if extra:
        context.update(extra)
    return context


def save_passport_copy_failure_artifacts(
    *,
    output_dir: Path,
    image,
    context: dict[str, object],
    log_lines: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if image is not None:
        image.save(output_dir / "latest_passport_copy_input.png")
    (output_dir / "latest_passport_copy_context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "latest_passport_copy.log").write_text(
        "\n".join(str(line) for line in log_lines),
        encoding="utf-8",
    )


def wait_for_login_passport_page(
    *,
    hwnd: int,
    title: str,
    output_dir: Path,
    operator: BackgroundOperator | object | None = None,
    state_detector=None,
    timeout_seconds: float = 30.0,
    interval_seconds: float = 1.0,
    sleep_func=time.sleep,
) -> tuple[_LoginWindowSnapshot | None, dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    active_operator = operator or BackgroundOperator()
    detector = state_detector or (lambda _image: ("unknown", {"final_reason": "no_state_detector"}))
    interval = max(0.1, float(interval_seconds))
    attempts_limit = max(1, int(float(timeout_seconds) / interval))
    latest_image = None
    latest_metrics: dict[str, object] = {}
    latest_state = "unknown"
    latest_error = ""

    for attempt in range(1, attempts_limit + 1):
        try:
            latest_image = active_operator.screenshot(int(hwnd)).convert("RGB")
            latest_image.save(output_dir / "latest_passport_copy_input.png")
            latest_state, metrics = detector(latest_image)
            latest_metrics = dict(metrics or {})
        except Exception as exc:
            latest_error = str(exc)
            latest_state = "unknown"
            latest_metrics = {"final_reason": latest_error}

        has_passport_region = bool(
            latest_metrics.get("passport_bar_box")
            or latest_metrics.get("red_bar_box")
            or latest_metrics.get("fallback_qr_box")
        )
        qr_detected = str(latest_state) == "qr_page"
        context = {
            "hwnd": int(hwnd),
            "title": str(title),
            "attempts": attempt,
            "timeout_seconds": float(timeout_seconds),
            "interval_seconds": interval,
            "qr_page_detected": bool(qr_detected),
            "passport_region_detected": bool(has_passport_region),
            "state": str(latest_state),
            "metrics": latest_metrics,
            "image_size": list(latest_image.size) if latest_image is not None else None,
            "final_reason": str(latest_metrics.get("final_reason") or latest_error or latest_state),
        }
        if latest_image is not None and (qr_detected or has_passport_region):
            snapshot = _LoginWindowSnapshot(
                hwnd=int(hwnd),
                title=str(title),
                image=latest_image,
                raw_path=output_dir / "latest_passport_copy_input.png",
                state=str(latest_state),
                metrics=latest_metrics,
            )
            return snapshot, context

        if attempt < attempts_limit:
            sleep_func(interval)

    timeout_context = {
        "hwnd": int(hwnd),
        "title": str(title),
        "attempts": attempts_limit,
        "timeout_seconds": float(timeout_seconds),
        "interval_seconds": interval,
        "qr_page_detected": False,
        "passport_region_detected": False,
        "state": str(latest_state),
        "metrics": latest_metrics,
        "image_size": list(latest_image.size) if latest_image is not None else None,
        "final_reason": "launch_timeout",
    }
    if latest_image is not None:
        latest_image.save(output_dir / "latest_launch_timeout.png")
    (output_dir / "latest_launch_timeout_context.json").write_text(
        json.dumps(timeout_context, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return None, timeout_context


def verify_passport_copy_on_window(
    *,
    hwnd: int,
    title: str,
    output_dir: Path,
    wait_timeout_seconds: float = 30.0,
    wait_interval_seconds: float = 1.0,
) -> tuple[dict[str, object], int]:
    logs: list[str] = []
    account = AccountConfig("真实窗口验证", 0, int(hwnd), "")
    runner = BackgroundSingleAccountRunner(
        account,
        AutomationSettings(),
        threading.Event(),
        log=logs.append,
        update_status=lambda _account, _status: None,
    )
    snapshot, wait_context = wait_for_login_passport_page(
        hwnd=int(hwnd),
        title=str(title),
        output_dir=output_dir,
        operator=runner.operator,
        state_detector=runner._helper.detect_login_page_state,
        timeout_seconds=wait_timeout_seconds,
        interval_seconds=wait_interval_seconds,
    )

    if snapshot is None:
        context = build_passport_copy_context(
            hwnd=int(hwnd),
            title=str(title),
            image_size=wait_context.get("image_size"),  # type: ignore[arg-type]
            method_results=[],
            child_hwnd_list=[],
            clipboard_used=False,
            clipboard_restored=True,
            final_reason=str(wait_context.get("final_reason") or "launch_timeout"),
            extra={"wait_context": wait_context, "ocr_fallback_used": False, "passport": ""},
        )
        (output_dir / "latest_passport_copy.log").write_text("\n".join(logs), encoding="utf-8")
        return {
            "independent_test_window_started": True,
            "test_window": {"hwnd": int(hwnd), "title": str(title)},
            "qr_page_detected": False,
            "wm_gettext_success": False,
            "uia_success": False,
            "background_copy_success": False,
            "clipboard_used": False,
            "clipboard_restored": True,
            "ocr_fallback_used": False,
            "passport": "",
            "final_hex_found": False,
            "context": context,
            "logs": logs,
        }, 3

    copy_result = runner._try_background_passport_copy(snapshot)
    details = dict(copy_result.details or {})
    method_results = list(details.get("method_results") or [])
    child_hwnd_list = runner._window_children(int(hwnd))
    passport = str(copy_result.passport or "").lower()
    ocr_fallback_used = False
    ocr_error = ""
    if not passport:
        ocr_fallback_used = True
        try:
            ocr_result = extract_passport_from_login_image(
                snapshot.image,
                runner=runner._helper,
                window_index=int(hwnd),
                debug_dir=output_dir,
                mode="background",
                raw_path=snapshot.raw_path,
                login_context={
                    "hwnd": int(hwnd),
                    "title": str(title),
                    "login_page_state": snapshot.state,
                    "qr_box": snapshot.metrics.get("qr_box"),
                    "fallback_qr_box": snapshot.metrics.get("fallback_qr_box"),
                    "red_bar_box": snapshot.metrics.get("passport_bar_box"),
                },
                save_failure_artifacts=True,
            )
            passport = str(ocr_result.passport or "").lower()
        except Exception as exc:
            ocr_error = str(exc)

    wm_gettext_success = any(
        result.get("method") == "wm_gettext" and bool(result.get("success")) for result in method_results
    )
    uia_success = any(result.get("method") == "uia" and bool(result.get("success")) for result in method_results)
    background_copy_success = bool(copy_result.success and copy_result.passport)
    final_reason = (
        "background_copy_read_success"
        if background_copy_success
        else str(copy_result.error or ocr_error or "background_copy_read_failed")
    )
    context = build_passport_copy_context(
        hwnd=int(hwnd),
        title=str(title),
        image_size=snapshot.image.size,
        method_results=method_results,
        child_hwnd_list=child_hwnd_list,
        clipboard_used=bool(copy_result.clipboard_used),
        clipboard_restored=bool(copy_result.clipboard_restored),
        final_reason=final_reason,
        extra={
            "wait_context": wait_context,
            "ocr_fallback_used": bool(ocr_fallback_used),
            "passport": passport,
            "copy_method": str(copy_result.method or ""),
            "ocr_error": ocr_error,
            "calls_set_foreground_window": bool(runner.operator.calls_set_foreground_window),
            "mouse_stolen": bool(runner.operator.uses_global_mouse),
            "keyboard_stolen": bool(runner.operator.uses_global_keyboard),
        },
    )
    if not background_copy_success:
        save_passport_copy_failure_artifacts(
            output_dir=output_dir,
            image=snapshot.image,
            context=context,
            log_lines=logs,
        )
    else:
        (output_dir / "latest_passport_copy.log").write_text("\n".join(logs), encoding="utf-8")

    result = {
        "independent_test_window_started": True,
        "test_window": {"hwnd": int(hwnd), "title": str(title)},
        "qr_page_detected": bool(wait_context.get("qr_page_detected")),
        "wm_gettext_success": bool(wm_gettext_success),
        "uia_success": bool(uia_success),
        "background_copy_success": bool(background_copy_success),
        "clipboard_used": bool(copy_result.clipboard_used),
        "clipboard_restored": bool(copy_result.clipboard_restored),
        "ocr_fallback_used": bool(ocr_fallback_used),
        "passport": passport,
        "final_hex_found": bool(passport),
        "calls_set_foreground_window": bool(runner.operator.calls_set_foreground_window),
        "mouse_stolen": bool(runner.operator.uses_global_mouse),
        "keyboard_stolen": bool(runner.operator.uses_global_keyboard),
        "context": context,
        "logs": logs,
    }
    return result, 0 if background_copy_success else 1


def detect_notice_overlay(image) -> bool:
    text = ocr_image_text(image)
    return "公告" in text


def detect_passport_input_panel(image) -> bool:
    text = ocr_image_text(image)
    normalized = str(text or "").replace(" ", "")
    return ("通行证" in normalized and ("登录" in normalized or "确认" in normalized)) or (
        locate_passport_input_box(image) is not None and detect_large_center_gray_panel(image)
    )


def locate_passport_input_box(image) -> tuple[int, int] | None:
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
            x, y, w, h, area = [int(value) for value in stats[index]]
            if area < 500:
                continue
            if w < width * 0.10 or h < 12:
                continue
            if h > height * 0.08:
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


def send_text_with_method(hwnd: int, text: str, method: str, *, user32=user32) -> tuple[bool, dict[str, object]]:
    hwnd = int(hwnd)
    method = str(method)
    text = str(text)
    failures = 0
    if method == "wm_char":
        for char in text:
            if not bool(user32.PostMessageW(hwnd, WM_CHAR, ord(char), 0)):
                failures += 1
        return failures == 0, {"method": method, "failed_count": failures, "target_hwnd": hwnd}
    if method == "key_sequence":
        for char in text:
            vk = ord(char.upper()) if len(char) == 1 and char.isalnum() else ord(char)
            ok_down = bool(user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0))
            ok_char = bool(user32.PostMessageW(hwnd, WM_CHAR, ord(char), 0))
            ok_up = bool(user32.PostMessageW(hwnd, WM_KEYUP, vk, 0))
            if not (ok_down and ok_char and ok_up):
                failures += 1
        return failures == 0, {"method": method, "failed_count": failures, "target_hwnd": hwnd}
    if method == "send_message":
        for char in text:
            try:
                result = user32.SendMessageW(hwnd, WM_CHAR, ord(char), 0)
                ok = result is not None
            except Exception:
                ok = False
            if not ok:
                failures += 1
        return failures == 0, {"method": method, "failed_count": failures, "target_hwnd": hwnd}
    raise ValueError(f"未知输入方法: {method}")


def launch_game_process_with_url(game_path: str, url: str) -> tuple[bool, int, str]:
    cleaned_path = str(game_path or "").strip().strip('"')
    cleaned_url = str(url or "").strip()
    if not cleaned_path:
        return False, 0, "缺少 game exe 路径"
    if not cleaned_url:
        return False, 0, "缺少 bookmark url"
    path = Path(cleaned_path)
    working_dir = str(path.parent) if path.parent else None
    try:
        result = int(
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "open",
                str(path),
                cleaned_url,
                working_dir,
                1,
            )
        )
    except Exception as exc:
        return False, 0, str(exc)
    if result > 32:
        return True, result, ""
    return False, result, f"ShellExecuteW 返回码 {result}"


def ensure_playwright_browsers_path_for_probe() -> Path | None:
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
    points_to_packaged_default = "_internal" in current_lower and ".local-browsers" in current_lower
    if not current or points_to_packaged_default:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(expected)
    return expected


def launch_browser_session_with_url(
    *,
    url: str,
    browser_name: str,
    window_width: int,
    window_height: int,
    timeout_ms: int,
) -> BrowserProbeSession:
    ensure_playwright_browsers_path_for_probe()
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        launcher = getattr(playwright, browser_name or "chromium")
        browser = launcher.launch(
            headless=False,
            args=[
                f"--window-size={int(window_width)},{int(window_height)}",
                "--window-position=100,100",
            ],
        )
        page = browser.new_page(viewport={"width": int(window_width), "height": int(window_height)})
        page.goto(str(url), wait_until="domcontentloaded", timeout=int(timeout_ms))
        return BrowserProbeSession(playwright=playwright, browser=browser, page=page)
    except Exception:
        try:
            playwright.stop()
        except Exception:
            pass
        raise


def make_probe_run_dir(base_output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = base_output_dir / f"run_{timestamp}"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = base_output_dir / f"run_{timestamp}_{suffix}"
    return candidate


def run_probe(
    *,
    hwnd: int,
    output_dir: Path,
    click_point: tuple[int, int] | None = None,
    input_text: str = "",
    open_passport_panel: bool = False,
    passport_button_point: tuple[int, int] | None = None,
    input_box_point: tuple[int, int] | None = None,
    input_method: str = "wm_char",
    target_child: int | None = None,
    dump_children: bool = False,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    operator = BackgroundOperator()
    notes: list[str] = []
    screenshot_ok = False
    click_ok = False
    input_ok = False
    open_dialog_ok = False
    notice_closed = False
    passport_button_clicked = False
    passport_input_panel_detected = False
    input_text_sent = False
    input_effect_detected = False
    input_verify_method = "not_tested"
    reason = ""
    input_box_clicked = False
    input_focus_effect_detected = False
    input_box_region_found = False
    detected_input_box_point: tuple[int, int] | None = None
    page_state = "unknown"
    page_ocr_text = ""
    before = None
    children = enum_child_windows(hwnd)

    try:
        before = operator.screenshot(hwnd)
        before.save(output_dir / "screenshot_before.png")
        page_state, page_ocr_text = classify_game_page_image(before)
        (output_dir / "page_ocr.txt").write_text(page_ocr_text, encoding="utf-8")
        screenshot_ok = True
        notes.append(f"后台截图成功，已保存 screenshot_before.png，页面阶段={page_state}")
    except Exception as exc:
        notes.append(f"后台截图失败：{exc}")

    if screenshot_ok and open_passport_panel:
        if page_state == "login_qr_page":
            reason = "formal_game_page_not_detected"
            notes.append("当前仍是登录程序二维码页，不测试通行证输入面板")
        else:
            overlay_closed, after_overlay, overlay_notes = close_blocking_overlay_like_notice(
                operator=operator,
                hwnd=hwnd,
                first_image=before,
                children=children,
                output_dir=output_dir,
            )
            notes.extend(overlay_notes)
            notice_closed = bool(overlay_closed)
            notice_before = after_overlay
            notice_before.save(output_dir / "notice_before.png")
            notice_visible_before = detect_notice_overlay(notice_before)
            if not overlay_closed:
                reason = "blocking_overlay_not_closed"
                notes.append("阻塞弹窗未关闭，不点击通行证按钮")

            dialog_before = operator.screenshot(hwnd)
            dialog_before.save(output_dir / "passport_dialog_before.png")
            if overlay_closed:
                template_point, template_score = locate_passport_button_by_template(dialog_before)
                passport_point = passport_button_point or template_point or point_from_ratio(dialog_before, DEFAULT_PASSPORT_BUTTON_RATIO)
                dialog_click, click_detail = background_click_window_point(operator, hwnd, passport_point, children)
                passport_button_clicked = bool(dialog_click.success)
                notes.append(
                    f"尝试后台点击通行证按钮 point={passport_point} "
                    f"template_score={template_score} detail={click_detail}"
                )
                time.sleep(0.8)
                try:
                    dialog_after = operator.screenshot(hwnd)
                    dialog_after.save(output_dir / "passport_dialog_after.png")
                    open_dialog_ok = bool(dialog_click.success and images_changed(dialog_before, dialog_after, threshold=0.001))
                    detected_input_box_point = locate_passport_input_box(dialog_after)
                    input_box_region_found = detected_input_box_point is not None
                    passport_input_panel_detected = bool(
                        open_dialog_ok and (detect_passport_input_panel(dialog_after) or input_box_region_found)
                    )
                    if not passport_input_panel_detected:
                        notes.append("通行证输入面板未检测到；不继续测试后台输入")
                except Exception as exc:
                    notes.append(f"通行证弹窗点击后截图失败：{exc}")

    effective_click_point = click_point
    if effective_click_point is None and not open_passport_panel:
        effective_click_point = None

    if screenshot_ok and effective_click_point is not None:
        x, y = effective_click_point
        click_result, click_detail = background_click_window_point(operator, hwnd, (x, y), children)
        notes.append(f"后台点击消息：{click_result.message} detail={click_detail}")
        time.sleep(0.3)
        try:
            after_click = operator.screenshot(hwnd)
            after_click.save(output_dir / "screenshot_after_click.png")
            click_ok = bool(click_result.success and images_changed(before, after_click, threshold=0.001))
            if click_result.success and not click_ok:
                notes.append("点击消息已发送，但前后截图未检测到变化；暂不判定后台点击生效")
        except Exception as exc:
            notes.append(f"点击后截图失败：{exc}")
    elif effective_click_point is None:
        notes.append("未提供 --click x,y，跳过后台点击生效验证")

    if screenshot_ok and input_text and not open_passport_panel:
        reason = "passport input panel only appears after opening bookmark game url"
        notes.append("未打开正式游戏页/通行证输入面板，跳过后台输入专项验证")
    elif screenshot_ok and input_text and open_passport_panel and not passport_input_panel_detected:
        if not reason:
            reason = "passport_input_panel_not_detected"
        notes.append("通行证输入面板未出现，跳过后台输入专项验证")
    elif screenshot_ok and input_text:
        focus_before = operator.screenshot(hwnd)
        focus_before.save(output_dir / "input_before.png")
        input_point = input_box_point or detected_input_box_point or locate_passport_input_box(focus_before) or point_from_ratio(focus_before, DEFAULT_INPUT_BOX_RATIO)
        input_box_region_found = bool(input_box_region_found or locate_passport_input_box(focus_before) is not None)
        crop_input_box_region(focus_before, input_point).save(output_dir / "input_box_before.png")
        focus_click, focus_detail = background_click_window_point(operator, hwnd, input_point, children)
        input_box_clicked = bool(focus_click.success)
        notes.append(f"后台点击输入框 point={input_point} detail={focus_detail}")
        time.sleep(0.3)
        try:
            focus_after = operator.screenshot(hwnd)
            focus_after.save(output_dir / "input_focus_after.png")
            input_focus_effect_detected = images_changed(focus_before, focus_after, threshold=0.001)
            if not input_focus_effect_detected:
                notes.append("后台点击输入框后未检测到焦点/高亮截图变化；仍继续尝试各 hwnd 输入，但不标记聚焦成功")
        except Exception as exc:
            notes.append(f"输入框点击后截图失败：{exc}")

        method_results: list[dict[str, object]] = []
        methods = input_method_labels(input_method)
        target_hwnds = candidate_input_hwnds(hwnd, children, target_child)
        for target_hwnd in target_hwnds:
            for method in methods:
                before_method = operator.screenshot(hwnd)
                ok_sent, detail = send_text_with_method(target_hwnd, input_text, method)
                time.sleep(0.3)
                after_input = operator.screenshot(hwnd)
                method_name = f"input_after_{target_hwnd}_{method}.png"
                after_input.save(output_dir / method_name)
                input_box_before_method = crop_input_box_region(before_method, input_point)
                input_box_after = crop_input_box_region(after_input, input_point)
                input_box_after.save(output_dir / f"input_box_after_{target_hwnd}_{method}.png")
                image_changed = images_changed(before_method, after_input, threshold=0.001)
                box_changed = images_changed(input_box_before_method, input_box_after, threshold=0.001)
                text_visible = verify_input_text_visible(input_box_after, input_text) or verify_input_text_visible(after_input, input_text)
                visual_text_changed = input_box_has_visual_text_change(input_box_before_method, input_box_after)
                real_success = bool(ok_sent and (text_visible or visual_text_changed))
                method_result = {
                    "target_hwnd": int(target_hwnd),
                    "method": method,
                    "message_sent": bool(ok_sent),
                    "image_changed": bool(image_changed),
                    "input_box_changed": bool(box_changed),
                    "text_visible_by_ocr": bool(text_visible),
                    "visual_text_changed": bool(visual_text_changed),
                    "real_success": bool(real_success),
                    "detail": detail,
                    "screenshot": method_name,
                }
                method_results.append(method_result)
                input_text_sent = bool(input_text_sent or ok_sent)
                input_effect_detected = bool(input_effect_detected or box_changed or text_visible)
                if real_success:
                    input_ok = True
                    input_verify_method = "ocr" if text_visible else "screenshot_diff"
        (output_dir / "input_probe_result.json").write_text(
            json.dumps(
                {
                    "input_box_clicked": input_box_clicked,
                    "input_focus_effect_detected": input_focus_effect_detected,
                    "target_hwnds": target_hwnds,
                    "children": children,
                    "method_results": method_results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if not input_ok:
            notes.append("所有后台输入方案均未通过 OCR/截图真实输入验证")
            if input_effect_detected:
                input_verify_method = "screenshot_diff"
    elif not input_text:
        notes.append("未提供 --input-text，跳过后台输入生效验证")

    try:
        process_path = get_window_process_path(hwnd)
        notes.append(f"目标进程：{process_path or '未知'}")
    except Exception as exc:
        notes.append(f"目标进程读取失败：{exc}")

    result = build_probe_result(
        background_screenshot=screenshot_ok,
        background_click=click_ok,
        background_input=input_ok,
        mouse_stolen=False,
        keyboard_stolen=False,
        notes="；".join(notes),
    )
    result["passport_dialog_opened"] = bool(open_dialog_ok)
    result["game_page_state"] = page_state
    result["formal_game_page_detected"] = page_state == "formal_game_page"
    result["login_qr_page_detected"] = page_state == "login_qr_page"
    result["notice_closed"] = bool(notice_closed)
    result["passport_button_clicked"] = bool(passport_button_clicked)
    result["passport_input_panel_detected"] = bool(passport_input_panel_detected)
    result["input_box_clicked"] = bool(input_box_clicked)
    result["input_focus_effect_detected"] = bool(input_focus_effect_detected)
    result["input_box_region_found"] = bool(input_box_region_found)
    result["input_text"] = str(input_text or "")
    result["input_text_sent"] = bool(input_text_sent)
    result["input_effect_detected"] = bool(input_effect_detected)
    result["input_verify_method"] = input_verify_method
    if reason:
        result["reason"] = reason
    if dump_children or children:
        result["child_windows"] = children
    return result


def launch_test_window_and_probe(
    *,
    game_exe_path: str,
    title_template: str,
    output_dir: Path,
    click_point: tuple[int, int] | None,
    input_text: str,
    close_after: bool,
    open_game_url: bool = False,
    bookmark_url: str = "",
    account_layer: str = "",
    account_index: int | None = None,
    settings_path: str | Path = app_root() / "automation_settings.json",
    open_passport_panel: bool = False,
    passport_button_point: tuple[int, int] | None = None,
    input_box_point: tuple[int, int] | None = None,
    input_method: str = "wm_char",
    target_child: int | None = None,
    dump_children: bool = False,
    timeout_seconds: float = DEFAULT_LAUNCH_WAIT_SECONDS,
) -> tuple[dict[str, object], int]:
    notes: list[str] = []
    output_dir = make_probe_run_dir(output_dir)
    before_windows = scan_probe_windows(title_template, game_exe_path)
    before_hwnds = {int(window.hwnd) for window in before_windows}
    notes.append(f"启动前游戏窗口 hwnd={sorted(before_hwnds)}")
    before_browser_windows = scan_browser_windows()
    before_browser_hwnds = {int(window.hwnd) for window in before_browser_windows}
    if open_game_url:
        notes.append(f"启动前浏览器窗口 hwnd={sorted(before_browser_hwnds)}")

    resolved_url = ""
    url_note = ""
    settings = None
    if open_game_url:
        try:
            settings = load_settings(settings_path)
            resolved_url, url_note = load_bookmark_account_url(
                bookmark_url=bookmark_url,
                account_layer=account_layer,
                account_index=account_index,
                settings_path=settings_path,
            )
            notes.append(url_note)
        except Exception as exc:
            result = build_probe_result(
                background_screenshot=False,
                background_click=False,
                background_input=False,
                mouse_stolen=False,
                keyboard_stolen=False,
                notes="；".join(notes + [f"读取收藏夹账号链接失败：{exc}"]),
            )
            result["game_url_opened"] = False
            result["reason"] = str(exc)
            result["test_window"] = None
            result["test_window_closed"] = False
            result["output_dir"] = str(output_dir)
            return result, 2

    browser_session: BrowserProbeSession | None = None
    if open_game_url:
        try:
            assert settings is not None
            browser_session = launch_browser_session_with_url(
                url=resolved_url,
                browser_name=settings.browser,
                window_width=settings.window_width,
                window_height=settings.window_height,
                timeout_ms=settings.page_load_timeout_ms,
            )
            launch_success = True
            shell_result = 0
            launch_error = ""
            notes.append(
                "使用 Playwright 独立浏览器打开正式游戏链接；"
                "不再把 URL 参数传给 X5Game.exe"
            )
        except Exception as exc:
            launch_success = False
            shell_result = 0
            launch_error = str(exc)
            notes.append(f"打开正式游戏链接失败：{exc}")
    else:
        launch_result = launch_game_process(game_exe_path)
        launch_success = launch_result.success
        shell_result = launch_result.shell_result
        launch_error = launch_result.error
        notes.append(
            "启动测试窗口："
            f"success={launch_success} shell_result={shell_result} "
            f"error={launch_error or '无'}"
        )
    if not launch_success:
        result = build_probe_result(
            background_screenshot=False,
            background_click=False,
            background_input=False,
            mouse_stolen=False,
            keyboard_stolen=False,
            notes="；".join(notes),
        )
        result["game_url_opened"] = False
        result["test_window"] = None
        result["test_window_closed"] = False
        result["output_dir"] = str(output_dir)
        return result, 1

    if open_game_url:
        test_window, after_windows = wait_for_new_browser_window(
            before_hwnds=before_browser_hwnds,
            timeout_seconds=timeout_seconds,
        )
        after_hwnds = {int(window.hwnd) for window in after_windows}
        notes.append(f"启动后浏览器窗口 hwnd={sorted(after_hwnds)}")
        notes.append(f"新增浏览器 hwnd 差集={sorted(after_hwnds - before_browser_hwnds)}")
        target_window_kind = "browser_game_page"
    else:
        test_window, after_windows = wait_for_new_test_window(
            before_hwnds=before_hwnds,
            title_template=title_template,
            game_exe_path=game_exe_path,
            timeout_seconds=timeout_seconds,
        )
        after_hwnds = {int(window.hwnd) for window in after_windows}
        notes.append(f"启动后游戏窗口 hwnd={sorted(after_hwnds)}")
        notes.append(f"新增 hwnd 差集={sorted(after_hwnds - before_hwnds)}")
        target_window_kind = "login_program"

    if test_window is None:
        if browser_session is not None:
            browser_session.close()
        result = build_probe_result(
            background_screenshot=False,
            background_click=False,
            background_input=False,
            mouse_stolen=False,
            keyboard_stolen=False,
            notes="；".join(notes + ["未在超时时间内找到新增测试窗口"]),
        )
        result["test_window"] = None
        result["test_window_closed"] = False
        result["output_dir"] = str(output_dir)
        return result, 2

    if open_game_url:
        time.sleep(DEFAULT_AFTER_GAME_URL_WAIT_SECONDS)
    elif input_text or open_passport_panel:
        result = build_probe_result(
            background_screenshot=False,
            background_click=False,
            background_input=False,
            mouse_stolen=False,
            keyboard_stolen=False,
            notes="；".join(
                notes
                + ["未打开正式游戏链接，通行证输入面板不会出现在初始登录窗口，已跳过后台输入专项验证"]
            ),
        )
        result["game_url_opened"] = False
        result["reason"] = "passport input panel only appears after opening bookmark game url"
        result["test_window"] = window_summary(test_window)
        result["before_hwnds"] = sorted(before_hwnds)
        result["after_hwnds"] = sorted(after_hwnds)
        closed = False
        if close_after:
            closed = close_test_window(int(test_window.hwnd))
            notes.append(f"已发送关闭测试窗口消息 hwnd={test_window.hwnd} result={closed}")
        result["test_window_closed"] = bool(closed)
        result["output_dir"] = str(output_dir)
        return result, 0

    effective_click = click_point if click_point is not None else (None if open_passport_panel else DEFAULT_CLICK_POINT)
    effective_input = input_text or (DEFAULT_INPUT_TEXT if open_passport_panel else "")
    probe_result = run_probe(
        hwnd=int(test_window.hwnd),
        output_dir=output_dir,
        click_point=effective_click,
        input_text=effective_input,
        open_passport_panel=bool(open_passport_panel),
        passport_button_point=passport_button_point,
        input_box_point=input_box_point,
        input_method=input_method,
        target_child=target_child,
        dump_children=dump_children,
    )
    probe_result["game_url_opened"] = bool(open_game_url)
    probe_result["target_window_kind"] = target_window_kind
    probe_result["bookmark_url_source"] = url_note
    probe_result["bookmark_url"] = resolved_url
    probe_result["test_window"] = window_summary(test_window)
    probe_result["before_hwnds"] = sorted(before_hwnds)
    probe_result["after_hwnds"] = sorted(after_hwnds)
    probe_result["before_browser_hwnds"] = sorted(before_browser_hwnds)
    if open_game_url:
        probe_result["after_browser_hwnds"] = sorted(after_hwnds)
    probe_result["test_click_point"] = list(effective_click) if effective_click is not None else None
    probe_result["test_input_text"] = effective_input
    probe_result["output_dir"] = str(output_dir)

    closed = False
    if close_after:
        if browser_session is not None:
            browser_session.close()
            time.sleep(0.5)
            try:
                closed = not bool(user32.IsWindow(int(test_window.hwnd)))
            except Exception:
                closed = True
            notes.append(f"已关闭 Playwright 测试浏览器 hwnd={test_window.hwnd} result={closed}")
        else:
            closed = close_test_window(int(test_window.hwnd))
            notes.append(f"已发送关闭测试窗口消息 hwnd={test_window.hwnd} result={closed}")
    probe_result["test_window_closed"] = bool(closed)
    probe_result["notes"] = "；".join(notes + [str(probe_result.get("notes", ""))])
    return probe_result, 0 if probe_result.get("background_screenshot") else 1


def launch_test_window_and_verify_passport_copy(
    *,
    game_exe_path: str,
    title_template: str,
    output_dir: Path,
    close_after: bool = True,
    launch_timeout_seconds: float = DEFAULT_LAUNCH_WAIT_SECONDS,
    passport_wait_timeout_seconds: float = 30.0,
) -> tuple[dict[str, object], int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    before_windows = scan_probe_windows(title_template, game_exe_path)
    before_hwnds = {int(window.hwnd) for window in before_windows}
    notes.append(f"启动前游戏窗口 hwnd={sorted(before_hwnds)}")

    launch_result = launch_game_process(game_exe_path)
    notes.append(
        "启动测试窗口："
        f"success={launch_result.success} shell_result={launch_result.shell_result} "
        f"error={launch_result.error or '无'}"
    )
    if not launch_result.success:
        result = {
            "independent_test_window_started": False,
            "test_window": None,
            "qr_page_detected": False,
            "wm_gettext_success": False,
            "uia_success": False,
            "background_copy_success": False,
            "clipboard_used": False,
            "clipboard_restored": True,
            "ocr_fallback_used": False,
            "passport": "",
            "final_hex_found": False,
            "calls_set_foreground_window": False,
            "mouse_stolen": False,
            "keyboard_stolen": False,
            "before_hwnds": sorted(before_hwnds),
            "after_hwnds": sorted(before_hwnds),
            "test_window_closed": False,
            "notes": "；".join(notes),
            "output_dir": str(output_dir),
        }
        return result, 1

    test_window = None
    after_windows = []
    verify_result: dict[str, object] | None = None
    exit_code = 1
    try:
        test_window, after_windows = wait_for_new_test_window(
            before_hwnds=before_hwnds,
            title_template=title_template,
            game_exe_path=game_exe_path,
            timeout_seconds=launch_timeout_seconds,
        )
        after_hwnds = {int(window.hwnd) for window in after_windows}
        notes.append(f"启动后游戏窗口 hwnd={sorted(after_hwnds)}")
        notes.append(f"新增 hwnd 差集={sorted(after_hwnds - before_hwnds)}")
        if test_window is None:
            verify_result = {
                "independent_test_window_started": False,
                "test_window": None,
                "qr_page_detected": False,
                "wm_gettext_success": False,
                "uia_success": False,
                "background_copy_success": False,
                "clipboard_used": False,
                "clipboard_restored": True,
                "ocr_fallback_used": False,
                "passport": "",
                "final_hex_found": False,
                "calls_set_foreground_window": False,
                "mouse_stolen": False,
                "keyboard_stolen": False,
                "reason": "new_test_window_not_found",
            }
            exit_code = 2
        else:
            verify_result, exit_code = verify_passport_copy_on_window(
                hwnd=int(test_window.hwnd),
                title=str(test_window.title),
                output_dir=output_dir,
                wait_timeout_seconds=passport_wait_timeout_seconds,
                wait_interval_seconds=1.0,
            )
        verify_result["before_hwnds"] = sorted(before_hwnds)
        verify_result["after_hwnds"] = sorted(after_hwnds)
        verify_result["output_dir"] = str(output_dir)
        verify_result["_inner_notes"] = str(verify_result.get("notes", ""))
        return verify_result, exit_code
    finally:
        if verify_result is not None and test_window is not None:
            closed = False
            if close_after:
                closed = close_test_window(int(test_window.hwnd))
                notes.append(f"已发送关闭测试窗口消息 hwnd={test_window.hwnd} result={closed}")
            verify_result["test_window_closed"] = bool(closed)
            try:
                verify_result["test_window_residual"] = bool(user32.IsWindow(int(test_window.hwnd)))
            except Exception:
                verify_result["test_window_residual"] = not bool(closed)
            inner_notes = str(verify_result.pop("_inner_notes", ""))
            verify_result["notes"] = "；".join(note for note in [*notes, inner_notes] if note)


def main(argv: list[str] | None = None) -> int:
    settings, _ = load_window_manager_settings()
    parser = argparse.ArgumentParser(description="后台登录模式最小验证脚本")
    parser.add_argument("--hwnd", type=int, default=0, help="指定游戏窗口 hwnd；不传则自动选择第一个编号游戏窗口")
    parser.add_argument("--title-template", default=settings.title_template, help="窗口标题模板，默认读取窗口管理配置")
    parser.add_argument("--game-exe-path", "--game-exe", dest="game_exe_path", default=settings.game_path, help="游戏 exe 路径，默认读取窗口管理配置")
    parser.add_argument("--launch-test-window", action="store_true", help="启动一个独立测试游戏窗口并用 hwnd 差集定位")
    parser.add_argument("--verify-passport-copy", action="store_true", help="只验证新增登录窗口后台复制/读取本次通行证")
    parser.add_argument("--close-after", action="store_true", help="测试完成后只关闭本次新增测试窗口")
    parser.add_argument("--bookmark-url", default="", help="直接指定收藏夹账号链接")
    parser.add_argument("--account-layer", default="", help="从收藏夹账号列表读取指定层级")
    parser.add_argument("--account-index", type=int, default=None, help="从收藏夹账号列表读取指定收藏编号")
    parser.add_argument("--settings-path", default=str(app_root() / "automation_settings.json"), help="上号器配置文件路径")
    parser.add_argument("--open-game-url", action="store_true", help="用测试窗口打开正式游戏账号链接")
    parser.add_argument("--open-passport-panel", action="store_true", help="尝试关闭公告并点击右侧通行证按钮")
    parser.add_argument("--click", type=parse_point, default=None, help="后台点击测试坐标，客户区坐标 x,y")
    parser.add_argument("--passport-button", type=parse_point, default=None, help="通行证按钮客户区坐标 x,y")
    parser.add_argument("--input-box", type=parse_point, default=None, help="通行证输入框客户区坐标 x,y")
    parser.add_argument("--input-text", default="", help=f"后台输入测试文本，建议 8 位 hex，默认 {DEFAULT_INPUT_TEXT}")
    parser.add_argument("--input-method", default="wm_char", help="wm_char / key_sequence / send_message / all")
    parser.add_argument("--target-child", type=int, default=None, help="指定输入消息目标子 hwnd")
    parser.add_argument("--dump-children", action="store_true", help="输出测试窗口子 hwnd 列表")
    parser.add_argument("--output-dir", default=str(DEFAULT_DEBUG_DIR), help="调试图片输出目录")
    parser.add_argument("--launch-timeout", type=float, default=DEFAULT_LAUNCH_WAIT_SECONDS, help="等待新增测试窗口秒数")
    parser.add_argument("--passport-wait-timeout", type=float, default=30.0, help="等待登录二维码页秒数")
    args = parser.parse_args(argv)

    if args.launch_test_window and args.verify_passport_copy:
        result, exit_code = launch_test_window_and_verify_passport_copy(
            game_exe_path=str(args.game_exe_path or ""),
            title_template=str(args.title_template or ""),
            output_dir=Path(args.output_dir),
            close_after=bool(args.close_after),
            launch_timeout_seconds=float(args.launch_timeout),
            passport_wait_timeout_seconds=float(args.passport_wait_timeout),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code

    if args.launch_test_window:
        result, exit_code = launch_test_window_and_probe(
            game_exe_path=str(args.game_exe_path or ""),
            title_template=str(args.title_template or ""),
            output_dir=Path(args.output_dir),
            click_point=args.click,
            input_text=str(args.input_text or ""),
            close_after=bool(args.close_after),
            open_game_url=bool(args.open_game_url),
            bookmark_url=str(args.bookmark_url or ""),
            account_layer=str(args.account_layer or ""),
            account_index=args.account_index,
            settings_path=str(args.settings_path or ""),
            open_passport_panel=bool(args.open_passport_panel),
            passport_button_point=args.passport_button,
            input_box_point=args.input_box,
            input_method=str(args.input_method or "wm_char"),
            target_child=args.target_child,
            dump_children=bool(args.dump_children),
            timeout_seconds=float(args.launch_timeout),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code

    hwnd, pick_note = pick_probe_hwnd(
        int(args.hwnd or 0) or None,
        str(args.title_template or ""),
        str(args.game_exe_path or ""),
    )
    if hwnd is None:
        result = build_probe_result(
            background_screenshot=False,
            background_click=False,
            background_input=False,
            mouse_stolen=False,
            keyboard_stolen=False,
            notes=pick_note,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    result = run_probe(
        hwnd=int(hwnd),
        output_dir=Path(args.output_dir),
        click_point=args.click,
        input_text=str(args.input_text or ""),
        open_passport_panel=bool(args.open_passport_panel),
        passport_button_point=args.passport_button,
        input_box_point=args.input_box,
        input_method=str(args.input_method or "wm_char"),
        target_child=args.target_child,
        dump_children=bool(args.dump_children),
    )
    result["notes"] = f"{pick_note}；{result['notes']}"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["background_screenshot"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
