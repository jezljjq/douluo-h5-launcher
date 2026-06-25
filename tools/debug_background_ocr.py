from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PIL import Image

from douluo_launcher.automation import AccountRunner, extract_passport_from_login_image
from douluo_launcher.config import AccountConfig, app_root, load_settings


def _default_settings_path() -> Path:
    return app_root() / "automation_settings.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线调试后台登录窗口本次通行证 OCR")
    parser.add_argument("image", help="后台失败截图，例如 debug_background\\latest_ocr_input.png")
    parser.add_argument("--window-index", type=int, default=1, help="日志用窗口编号，默认 1")
    parser.add_argument("--debug-dir", default=str(app_root() / "debug_background"), help="latest_ocr_* 输出目录")
    parser.add_argument("--settings", default=str(_default_settings_path()), help="automation_settings.json 路径")
    args = parser.parse_args(argv)

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"截图不存在: {image_path}")
        return 2

    settings = load_settings(args.settings)
    image = Image.open(image_path).convert("RGB")
    logs: list[str] = []
    account = AccountConfig("后台OCR调试", 1, int(args.window_index), "about:blank")
    runner = AccountRunner(
        account,
        settings,
        stop_event=threading.Event(),
        log=logs.append,
        update_status=lambda _account, _status: None,
    )

    login_state = "unknown"
    metrics: dict[str, object] = {}
    try:
        login_state, metrics = runner.detect_login_page_state(image)
    except Exception as exc:
        metrics = {"state_detect_error": str(exc)}

    result = extract_passport_from_login_image(
        image,
        runner=runner,
        window_index=int(args.window_index),
        debug_dir=Path(args.debug_dir),
        mode="offline",
        raw_path=image_path,
        login_context={
            "hwnd": 0,
            "title": str(image_path),
            "login_page_state": login_state,
            "qr_box": metrics.get("qr_box"),
            "fallback_qr_box": metrics.get("fallback_qr_box"),
            "red_bar_box": metrics.get("passport_bar_box"),
        },
        save_debug_artifacts=True,
    )

    print(f"image: {image_path}")
    print(f"image_size: {image.size[0]}x{image.size[1]}")
    print(f"login_page_state: {login_state}")
    print(f"text_region_box: {result.text_region_box}")
    print(f"preprocessed: {result.preprocessed_path}")
    if result.context_path:
        print(f"context: {result.context_path}")
    print(f"passport: {result.passport or '未识别'}")
    print("ocr_raw_output:")
    print(result.raw_output)
    if logs:
        print("runner_logs:")
        for line in logs:
            print(line)
    return 0 if result.passport else 1


if __name__ == "__main__":
    raise SystemExit(main())
