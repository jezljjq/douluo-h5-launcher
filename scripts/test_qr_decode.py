"""验证 OpenCV QR 解码能否替代 OCR 提取通行证。

用法：
    py scripts/test_qr_decode.py --window 9
    py scripts/test_qr_decode.py --window 1,2,3,4,5
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
from douluo_launcher.dm_client import list_visible_windows, capture_window_background


def decode_qr_from_image(image) -> tuple[str | None, str]:
    """对图像做多尺度 QR 解码，返回 (解码内容, 诊断信息)。"""
    cv_image = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    detector = cv2.QRCodeDetector()
    h, w = cv_image.shape[:2]

    messages: list[str] = []
    for factor in (1, 2, 3, 4):
        scaled = cv_image if factor == 1 else cv2.resize(cv_image, (w * factor, h * factor))
        try:
            data, bbox, straight_qrcode = detector.detectAndDecode(scaled)
        except Exception as exc:
            messages.append(f"  scale={factor}x: 异常 {exc}")
            continue

        if bbox is not None and len(bbox) > 0:
            pts = (bbox.astype(np.float64) / factor).astype(int)
            pw = pts[:, 0].max() - pts[:, 0].min()
            ph = pts[:, 1].max() - pts[:, 1].min()
            if data:
                messages.append(f"  scale={factor}x: 解码成功! bbox={pw}x{ph} data={data}")
                return data, "\n".join(messages)
            else:
                messages.append(f"  scale={factor}x: 检测到QR(bbox={pw}x{ph})但解码失败")
        else:
            messages.append(f"  scale={factor}x: 未检测到QR码")

    return None, "\n".join(messages)


def extract_hex_from_text(text: str) -> list[str]:
    """从文本中提取所有 8 位 hex 字符串。"""
    import re
    lowered = text.lower()
    # 直接找
    matches = set(re.findall(r"[a-f0-9]{8}", lowered))
    # OCR纠错后找
    fixed = lowered
    for old, new in [("l", "1"), ("o", "0"), ("s", "5"), ("i", "1"), ("g", "9"), ("z", "2")]:
        fixed = fixed.replace(old, new)
    matches.update(re.findall(r"[a-f0-9]{8}", fixed))
    # 去空格后找
    no_space = re.sub(r"\s+", "", fixed)
    matches.update(re.findall(r"[a-f0-9]{8}", no_space))
    return sorted(matches)


def test_window(game_window_no: int) -> dict:
    """测试单个窗口的 QR 解码。"""
    result = {
        "window": game_window_no,
        "hwnd": None,
        "title": "",
        "qr_data": None,
        "hex_from_qr": [],
        "diagnostic": "",
        "error": None,
    }

    # 1. 定位窗口
    windows = list_visible_windows("")
    target = None
    for w in windows:
        if f"H5-{game_window_no}-" in w.title:
            target = w
            break

    if target is None:
        result["error"] = f"未找到标题包含 H5-{game_window_no}- 的窗口"
        return result

    result["hwnd"] = target.hwnd
    result["title"] = target.title

    # 2. 截图
    image = capture_window_background(target).convert("RGB")

    # 3. 全图解码 QR
    qr_data, diagnostic = decode_qr_from_image(image)
    result["diagnostic"] = diagnostic
    result["qr_data"] = qr_data

    # 4. 提取 hex
    if qr_data:
        result["hex_from_qr"] = extract_hex_from_text(qr_data)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="验证 QR 解码能否替代 OCR")
    parser.add_argument(
        "--window", "-w",
        type=str,
        required=True,
        help="窗口号，多个用逗号分隔，如 1,2,3",
    )
    args = parser.parse_args()

    game_window_nos = [int(x.strip()) for x in args.window.split(",")]

    print("=" * 70)
    print("QR 解码验证 — 登录程序窗口")
    print("=" * 70)

    all_hex: dict[str, list[int]] = {}  # hex -> 出现窗口号
    success_count = 0

    for gn in game_window_nos:
        print(f"\n{'─' * 50}")
        print(f"窗口 {gn}")
        print(f"{'─' * 50}")

        r = test_window(gn)

        if r["error"]:
            print(f"  ❌ {r['error']}")
            continue

        print(f"  hwnd={r['hwnd']}  title={r['title']}")
        print(r["diagnostic"])

        if r["qr_data"]:
            print(f"  QR原始内容: {r['qr_data'][:200]}")
            if r["hex_from_qr"]:
                print(f"  提取hex: {', '.join(r['hex_from_qr'])}")
                for h in r["hex_from_qr"]:
                    all_hex.setdefault(h, []).append(gn)
                success_count += 1
            else:
                print(f"  ⚠️ 解码成功但内容中无8位hex")
        else:
            print(f"  ❌ 无法解码QR码")

    # 汇总
    print(f"\n{'=' * 70}")
    print("汇总")
    print(f"{'=' * 70}")
    print(f"测试窗口数: {len(game_window_nos)}")
    print(f"解码成功: {success_count}")

    if all_hex:
        print(f"\n提取到的hex通行证:")
        for h, windows in sorted(all_hex.items()):
            print(f"  {h} ← 窗口 {', '.join(str(w) for w in windows)}")
        print(f"\n请对比页面显示的'本次通行证'与上述hex是否一致。")
    else:
        print("\n未能从任何窗口的QR码中提取到hex。")
        print("QR解码方案不可行，应保留现有OCR方案。")


if __name__ == "__main__":
    main()
