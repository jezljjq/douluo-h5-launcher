# OCR 裁剪错误分析与修复方案

**日期：2026-05-08**
**状态：待确认后执行**

---

## 1. 项目对象关系

### 三层独立对象

```
收藏夹 (Chrome/Edge Bookmarks)
└── 根目录: "账号"
    ├── 第一层 (offset=0)  → 收藏编号 1~8
    ├── 第二层 (offset=8)  → 收藏编号 1~8
    ├── 第三层 (offset=16) → 收藏编号 1~8
    └── 第四层 (offset=24) → 收藏编号 1~8
```

| 对象 | 用途 | 关键属性 | 当前阶段 |
|------|------|----------|----------|
| **收藏链接** (Bookmark URL) | 浏览器游戏入口地址 | 层级 + 收藏编号 | 已正确读取 |
| **登录程序窗口** (Login Program Window) | OCR 目标，含二维码+通行证 | 标题含 `H5-{游戏窗口号}` | 定位正确 ✅ |
| **浏览器正式游戏页** (Browser Game Page) | Playwright 打开收藏链接后的页面 | 无二维码，无通行证 | 暂停使用 ⏸️ |

### 映射规则

```
收藏编号 ≠ 游戏窗口号

游戏窗口号 = 收藏编号 + 层级偏移量

第一层 offset = 0   → 游戏窗口 1-8
第二层 offset = 8   → 游戏窗口 9-16
第三层 offset = 16  → 游戏窗口 17-24
第四层 offset = 24  → 游戏窗口 25-32

例: 第二层 收藏1 → 游戏窗口号 9
```

### 当前主流程（仅测试子集）

```
第二层 收藏1 → 游戏窗口号 9
→ win32gui 枚举所有可见窗口
→ 标题匹配 "H5-9" (window_title_matches_game_no)
→ 选中登录程序窗口 (select_login_window_by_game_no)
→ ImageGrab.grab(GetWindowRect) 截图 (capture_window_image)
→ _locate_qr_box() 定位二维码
→ _passport_crop_box_from_qr() 计算红条裁剪坐标
→ 多尺度 OCR 变体识别 8 位十六进制通行证
```

---

## 2. 当前 OCR 裁剪错误分析

### 现象

| 文件 | 内容 | 状态 |
|------|------|------|
| `*_01_login_window_full.png` | 登录程序窗口完整截图，含二维码和红条 | ✅ 正确 |
| `*_02_passport_region_crop.png` | 裁到了标题文字 "扫码登录斗罗大陆" | ❌ 错误 |
| 正确目标 | 裁到二维码下方红条 "本次通行证：xxxxxxxx" | 待修复 |

### 已排除的问题

- ❌ 不是浏览器 OCR 问题
- ❌ 不是窗口定位问题（`select_login_window_by_game_no` 正确匹配 `H5-9`）
- ❌ 不是 Playwright 截图问题
- ❌ 不是大漠问题
- ❌ 不是 OCR 精度/参数问题

### 根因分析

**问题函数：`_locate_qr_box()` — [automation.py:594-630](douluo_launcher/automation.py#L594-L630)**

该函数通过滑动窗口搜索"暗像素密度 12%~65% 的正方形区域"来定位二维码。
算法流程：

```
1. 图像转灰度
2. 构建积分图（像素值 < 110 视为暗像素）
3. 遍历 size ∈ [90, max_size]（步长 20）
4.   遍历 top  ∈ [0.08*H, 0.78*H]
5.     遍历 left ∈ [0.05*W, 0.95*W]
6.       计算窗口内暗像素密度
7.       密度在 12%~65% 范围内 → 综合中心权重+尺寸权重打分
8. 返回得分最高的正方形
```

**为什么裁到标题区域：**

1. **没有 QR 码专属特征约束** — 算法只检查"暗像素密度 12%~65%"，任何满足此密度的暗色 UI 元素（标题面板、背景色块、粗体文字区域）都可能被误判为二维码。

2. **搜索从上方开始** — 搜索 y 范围是 `0.08*height` 到 `0.78*height`，从低 y 向高 y 扫描。如果标题区域附近有暗色面板先被扫到且得分够高，就被选为"最佳二维码"。

3. **`passport_region_y_offset` 只有 5 像素** — [automation_settings.json:44](automation_settings.json#L44)。即使检测到的 `qr_bottom` 位于标题区域底部，`qr_bottom + 5` 也只向下偏移 5px，裁剪窗口顶部仍在标题范围内。

4. **步长粗搜索可能漏掉真正的 QR 码** — `step = max(8, size // 8)`，对于 100px 的窗口步长为 12px，可能恰好跳过 QR 码位置。

### 证据链

```
_locate_qr_box() 返回错误 box（标题面板而非 QR 码）
  → _passport_crop_box_from_qr(qr_box, image_size)
  → crop_top = qr_bottom + 5（仍然在标题区域附近）
  → crop_bottom = crop_top + 45
  → 裁剪结果 = 标题文字 "扫码登录斗罗大陆"
```

---

## 3. 修复方案

### 总策略

**用 OpenCV QRCodeDetector 替换暗像素密度搜索。** 当前环境已安装 `opencv-python==4.13.0.92`，`cv2.QRCodeDetector` 是专门检测真实 QR 码的算法，它识别 QR 码三处定位图案（1:1:3:1:1 比例），不会被标题文字或暗色面板欺骗。

### 修改文件

- **主改：** [douluo_launcher/automation.py](douluo_launcher/automation.py) — `_locate_qr_box()` 方法（第 594-630 行）
- **新增：** 同文件新增 `_locate_qr_box_fallback()` 回退方法
- **不改：** `dm_client.py`、`config.py`、`gui.py`、OCR 参数、`automation_settings.json`

### 改动 1：重写 `_locate_qr_box()`

```python
def _locate_qr_box(self, image) -> tuple[int, int, int, int] | None:
    """用 OpenCV QRCodeDetector 定位二维码，失败时回退到暗像素搜索"""
    import cv2
    import numpy as np

    # RGB → BGR（OpenCV 格式）
    cv_image = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    detector = cv2.QRCodeDetector()

    # QRCodeDetector 即使无法解码，也能返回定位框 bbox
    try:
        data, bbox, _ = detector.detectAndDecode(cv_image)
    except Exception:
        bbox = None

    if bbox is not None and len(bbox) > 0:
        pts = bbox.astype(int)
        left = max(0, pts[:, 0].min())
        top = max(0, pts[:, 1].min())
        right = min(image.width, pts[:, 0].max())
        bottom = min(image.height, pts[:, 1].max())
        if right - left >= 50 and bottom - top >= 50:
            self.log(
                f"[窗口{self.account.game_window_no}] OpenCV QR 检测成功: "
                f"({left},{top},{right},{bottom}) 解码={data or '失败'}"
            )
            return (left, top, right, bottom)

    # 回退：原暗像素搜索
    self.log(f"[窗口{self.account.game_window_no}] OpenCV QR 检测失败，回退到暗像素搜索")
    return self._locate_qr_box_fallback(image)
```

### 改动 2：新增 `_locate_qr_box_fallback()`

保留原算法但加约束——只搜索图像中段（y 范围收窄到 0.15~0.65），排除顶部标题区域和底部空白。

```python
def _locate_qr_box_fallback(self, image) -> tuple[int, int, int, int] | None:
    """暗像素密度搜索（回退方案），搜索范围收窄到图像中段"""
    gray = image.convert("L")
    width, height = gray.size
    pixels = gray.load()

    # 构建积分图
    integral = [[0] * (width + 1) for _ in range(height + 1)]
    for y in range(height):
        row_sum = 0
        for x in range(width):
            row_sum += 1 if pixels[x, y] < 110 else 0
            integral[y + 1][x + 1] = integral[y][x + 1] + row_sum

    def dark_sum(l, t, r, b):
        return integral[b][r] - integral[t][r] - integral[b][l] + integral[t][l]

    min_size = max(90, int(min(width, height) * 0.15))
    max_size = max(min_size + 1, int(min(width, height) * 0.45))
    best_score = -1.0
    best_box = None
    center_x = width / 2

    for size in range(min_size, max_size + 1, 20):
        step = max(8, size // 8)
        # 关键修改：搜索范围收窄到 0.15~0.65，排除顶部标题区域
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
                    1 - min(1, abs((left + size / 2) - center_x) / center_x) * 0.35
                )
                size_weight = size / max_size
                score = density * center_weight * (0.6 + size_weight)
                if score > best_score:
                    best_score = score
                    best_box = (left, top, left + size, top + size)

    return best_box
```

### 改动 3：新增 debug 画框输出

在 `_ocr_passport_from_login_image()` 中，裁剪完成后输出一张带标注框的调试图。

```python
def _draw_debug_boxes(self, image, qr_box, crop_box, prefix, debug_dir):
    """在完整截图上画出 qr_box(蓝) 和 passport_crop_box(红)"""
    from PIL import ImageDraw

    draw_img = image.copy().convert("RGB")
    draw = ImageDraw.Draw(draw_img)

    # 蓝色 = QR box
    draw.rectangle(qr_box, outline="blue", width=2)
    # 红色 = passport crop box
    draw.rectangle(crop_box, outline="red", width=2)
    # 黄色虚线 = qr_bottom 基准线
    _, _, _, qr_bottom = qr_box
    draw.line([(0, qr_bottom), (image.width, qr_bottom)], fill="yellow", width=1)

    debug_path = debug_dir / f"{prefix}_debug_boxes.png"
    draw_img.save(debug_path)
    self.log(f"[窗口{self.account.game_window_no}] 调试框已保存: {debug_path}")
```

在 `_ocr_passport_from_login_image()` 第 497 行 `crop.save(crop_path)` 之后插入调用：

```python
self._draw_debug_boxes(raw_image, qr_box, crop_box, prefix, debug_dir)
```

### 不改的内容

| 文件/配置 | 原因 |
|-----------|------|
| `_passport_crop_box_from_qr()` | 公式 `qr_bottom + y_offset` 本身正确，问题在输入 |
| `passport_region_x_margin=20` | 横向边距合理 |
| `passport_region_y_offset=5` | QR 底部到红条间距合理 |
| `passport_region_height=45` | 红条高度合理 |
| OCR 白名单、阈值、二值化参数 | 裁剪正确后再调 |
| `dm_client.py` | 窗口定位已正确 |
| `config.py` | 映射关系已正确 |
| `gui.py` | GUI 逻辑已正确 |

---

## 4. 验证方案

### Step 1 — 肉眼验证裁剪框

```
1. python main.py
2. 点击 "测试第二层收藏1通行证"
3. 打开 debug_ocr/ 最新 *_debug_boxes.png
4. 检查:
   - 蓝色框 = 严格包围二维码的黑白方块（不含标题文字）✅
   - 黄色线 = qr_bottom，应在二维码底部边缘 ✅
   - 红色框 = 完整覆盖 "本次通行证：xxxxxxxx" 红条 ✅
5. 打开 *_02_passport_region_crop.png
6. 检查: 看到红底白字/黑字 "本次通行证：xxxxxxxx" ✅
```

### Step 2 — OCR 识别验证

```
1. 查看 GUI 日志中 OCR 变体输出
2. 确认至少一个变体返回非 None 的 8 位 hex
   例: "OCR 变体 scale3_gray_no_binary: 文本=... 候选=a1b2c3d4"
3. 打开 *_07_ocr_final_input.png
4. 检查: 清晰可辨的 "本次通行证：xxxxxxxx"
```

### 判定标准

| 检查项 | 通过标准 |
|--------|----------|
| `*_debug_boxes.png` 蓝框 | 包围二维码本体 |
| `*_debug_boxes.png` 红框 | 包围红条文字 |
| `*_02_passport_region_crop.png` | 肉眼可见 "本次通行证" |
| OCR 结果 | `extract_hex_passport()` 返回非 None |

**四个全部通过 → 裁剪修复成功 → 可进入后续 OCR 精度微调**

---

## 5. 修复后禁止事项

OCR 裁剪稳定前，继续暂停：
- Playwright 页面 OCR
- 浏览器截图
- 大漠点击
- 公告关闭
- 通行证输入
- 批量运行
- 多窗口并发

OCR 稳定后，按 [NEXT_STEPS.md](NEXT_STEPS.md) 顺序恢复后续流程。
