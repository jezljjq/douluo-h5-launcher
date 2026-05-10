"""后台截图遮挡验证脚本。

用法：
    python verify_background_capture.py

步骤：
    1. 先验证 BitBlt 正常截图（窗口可见时）
    2. 提示用户用其他窗口遮挡登录程序窗口
    3. BitBlt 截图 + OCR 验证
    4. 对比 ImageGrab（前台截图）看区别
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from douluo_launcher.dm_client import (
    select_login_window_by_game_no,
    capture_window_image,
    capture_window_background,
)

GAME_WINDOW_NO = 9
DEBUG_DIR = Path("debug_ocr")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def ocr_image(img, label="") -> str:
    """全图 OCR 返回文本"""
    try:
        import pytesseract
    except Exception:
        return "<tesseract 不可用>"

    for scale in (1, 2):
        if scale > 1:
            s_img = img.resize((img.width * scale, img.height * scale))
        else:
            s_img = img
        for psm in (6, 3):
            try:
                text = pytesseract.image_to_string(
                    s_img, lang="chi_sim+eng", config=f"--psm {psm}"
                )
            except Exception:
                continue
            if text.strip():
                return text.strip()[:200]
    return "<OCR 无结果>"


def extract_hex(text: str) -> str | None:
    import re

    # 冒号后 8 位 hex
    m = re.search(r":\s*([a-fA-F0-9]{8})(?:\s|$)", text)
    if m:
        return m.group(1).lower()
    # 全文 8 位 hex
    m = re.search(r"[a-f0-9]{8}", text.lower())
    if m:
        return m.group(0)
    return None


def main():
    selected, _ = select_login_window_by_game_no(GAME_WINDOW_NO)
    if selected is None:
        print(f"未找到游戏窗口 {GAME_WINDOW_NO}")
        return 1

    print(f"窗口: hwnd={selected.hwnd}, title={selected.title}")
    print(f"位置: ({selected.left},{selected.top})-({selected.right},{selected.bottom})")
    print()

    # === 第1步：正常截图（窗口可见） ===
    print("=" * 50)
    print("第1步：BitBlt 正常截图（窗口应可见）")
    print("=" * 50)

    img_bg = capture_window_background(selected)
    bg_path = DEBUG_DIR / "verify_bitblt_normal.png"
    img_bg.save(bg_path)
    print(f"BitBlt 截图已保存: {bg_path} ({img_bg.size})")

    text_bg = ocr_image(img_bg)
    hex_bg = extract_hex(text_bg)
    print(f"OCR 文本: {text_bg[:150]}")
    print(f"提取 hex: {hex_bg}")

    img_fg = capture_window_image(selected)
    fg_path = DEBUG_DIR / "verify_imagegrab_normal.png"
    img_fg.save(fg_path)
    text_fg = ocr_image(img_fg)
    hex_fg = extract_hex(text_fg)
    print(f"ImageGrab hex: {hex_fg}")

    print()

    # === 第2步：遮挡测试 ===
    print("=" * 50)
    print("第2步：遮挡测试")
    print("=" * 50)
    input("请用其他窗口完全盖住登录程序窗口，然后按回车继续...")

    img_bg2 = capture_window_background(selected)
    bg_path2 = DEBUG_DIR / "verify_bitblot_occluded.png"
    img_bg2.save(bg_path2)
    print(f"BitBlt 遮挡截图已保存: {bg_path2} ({img_bg2.size})")

    text_bg2 = ocr_image(img_bg2)
    hex_bg2 = extract_hex(text_bg2)
    print(f"OCR 文本: {text_bg2[:150]}")
    print(f"提取 hex: {hex_bg2}")

    img_fg2 = capture_window_image(selected)
    fg_path2 = DEBUG_DIR / "verify_imagegrab_occluded.png"
    img_fg2.save(fg_path2)
    text_fg2 = ocr_image(img_fg2)
    hex_fg2 = extract_hex(text_fg2)
    print(f"ImageGrab OCR 文本: {text_fg2[:150]}")
    print(f"ImageGrab hex: {hex_fg2}")

    print()
    print("=" * 50)
    print("对比结果")
    print("=" * 50)
    print(f"BitBlt 正常:     hex={hex_bg}")
    print(f"BitBlt 遮挡后:   hex={hex_bg2}")
    print(f"ImageGrab 正常:  hex={hex_fg}")
    print(f"ImageGrab 遮挡后: hex={hex_fg2}")
    print()

    if hex_bg2 and hex_bg2 == hex_bg:
        print("✅ 遮挡后 BitBlt 仍能正确 OCR 通行证 — 后台截图成功！")
    elif hex_bg2:
        print(f"⚠️  遮挡后 BitBlt 识别到 hex={hex_bg2}（可能与正常值 {hex_bg} 不同，二维码可能已刷新）")
    else:
        print("❌ 遮挡后 BitBlt 无法 OCR — 此窗口可能使用 DirectX 渲染，需要 Dm 后台绑定")

    if hex_fg2:
        print("❌ ImageGrab 遮挡后仍能截图（说明窗口未被完全遮挡，请重试）")
    else:
        print("   ImageGrab 遮挡后截图失败（预期行为）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
