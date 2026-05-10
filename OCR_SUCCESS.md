# OCR 通行证提取：最终稳定方案

**日期：2026-05-08**
**最近更新：2026-05-09**
**状态：已稳定，禁止回退**

---

## 1. 废弃方案：二维码定位 + 裁剪

### 原方案

```
登录程序窗口截图
→ 定位二维码（_locate_qr_box / OpenCV QRCodeDetector）
→ 从二维码底部向下偏移裁剪（_passport_crop_box_from_qr）
→ 对裁剪区域做多尺度 OCR 变体
```

### 废弃原因

| 原因 | 说明 |
|------|------|
| 二维码位置不稳定 | 随窗口内容/UI变化，不是固定业务锚点 |
| 裁剪容易偏移 | `qr_bottom + y_offset` 对不同窗口/分辨率不同 |
| 实际业务锚点不是二维码 | "本次通行证"才是固定业务文本 |
| OpenCV QRCodeDetector 检出率不稳定 | 320x540 小窗口上原始尺寸检测失败 |
| 暗像素密度搜索不可靠 | 任何满足 12%~65% 暗像素密度的 UI 元素都可能误判 |

---

## 2. 最终正式方案

### 核心流程

```
登录程序窗口完整截图（BitBlt 后台截图 + ImageGrab 回退）
→ 多尺度全图 OCR（Tesseract chi_sim+eng, --psm 6/3）
→ 三层正则匹配提取 8 位 hex 通行证
```

### 关键特性

- **不定位二维码** — 不依赖任何视觉元素位置
- **不裁剪图像** — OCR 直接处理整张图
- **不猜区域** — 固定业务文本"本次通行证"是唯一锚点

### OCR 参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 引擎 | Tesseract | |
| 语言 | `chi_sim+eng` | 中文+英文混合 |
| PSM | 6 或 3 | 6=均匀文本块, 3=全自动 |
| 缩放 | 1x, 2x | 原图+放大提高识别率 |
| 灰度 | 自适应对比度增强 | 仅在 RGB 未匹配时使用 |

---

## 3. 三层正则提取规则

按优先级：

```
方式1: 匹配 "本次通行证" 中文文本识别
  正则: 本次通行证\s*[:：]\s*([A-Za-z0-9_-]+)
  函数: extract_passport_from_text()
  说明: Tesseract 正确识别"本次通行证"中文时最可靠

方式2: 冒号后宽松捕获 + 纠错管线
  正则: :\s*(\S{7,10})(?:\s|$)
  函数: extract_hex_passport(m.group(1))
  说明: 中文乱码但数字可读时的模式，捕获后走完整纠错管线

方式3: extract_hex_passport() 内置纠错
  - 原始文本中直接搜索 8 位连续 hex [a-f0-9]{8}
  - OCR 字符纠错: l→1, o→0, s→5, i→1, g→9, z→2, t→1
  - OCR Unicode 符号纠错: €→c, ¢→c, £→e, ¥→y, $→s
  - 去空格/换行后重试
```

### 实测触发记录

```
OCR 完整文本: ": Or AERIS Ab ARYUEATIE: 74170d6d 2FUME RAMA | wRE"
方式1 未匹配（"本次通行证" 被 OCR 读成 "ARYUEATIE"）
方式2 匹配成功 → 提取 74170d6d
```

```
OCR 完整文本: "ARIBITIE: €4129354 AF MERAR MH LARAD"
方式1 未匹配（"本次通行证" 被 OCR 读成 "ARIBITIE"）
方式2 捕获 "€4129354" → 走纠错 → €→c → "c4129354" → 有效 hex
```

```
OCR 完整文本: "AURIBATIE: 4acaccal = EFUB ERAD HLM RDE"
方式1 未匹配
方式2 捕获 "4acaccal" → 走纠错 → l→1 → "4acacca1" → 有效 hex
```

---

## 4. OCR 投票机制（2026-05-11 新增）

全图 OCR 不再第一个成功就返回。改为收集所有变体（8 种 scale×psm×灰度组合）的结果后投票：

1. 收集所有变体的 OCR 结果，统计每个 hex 值的出现次数
2. **优先选包含 a-f 字母的结果**（避免全数字的 d→0 误判）
3. 同条件下取出现次数最多的值
4. 日志输出投票详情：共 N 种结果，选择 xxx（票数 m/total）

### 成功率

基于多次串行测试统计：

| 匹配方式 | 占比 | 说明 |
|----------|------|------|
| 方式1（本次通行证） | ~15% | Tesseract 正确识别中文 |
| 方式2（冒号+纠错） | ~80% | 中文乱码但冒号和数字可读 |
| OCR 完全失败 | ~5% | 投票后失败率降低（原 ~10%） |

### 失败场景

- 窗口被拖动/遮挡导致截图异常
- 登录程序窗口字体/颜色变化
- Tesseract 读取到极不可辨认的字符组合

### 已知 OCR 字符混淆

基于实测发现 Tesseract 在读取登录程序窗口时存在字符混淆：

| 实际字符 | OCR 误读 | 示例 |
|----------|----------|------|
| d | 0 | `00d57777` → `00057777` |
| f | 7 | `3f45f638` → `37457638` |
| c | € / ¢ / C | `c4129354` → `€4129354` |
| e | £ | `e2f5305a` → `£2f5305a` |
| 1 | l / t | `1abc` → `labc` / `tabc` |
| 0 | o / O | `0abc` → `oabc` |

当前纠错管线（`extract_hex_passport`）已覆盖 l→1, o→0, s→5, i→1, g→9, z→2, t→1 以及 Unicode 符号 €→c, £→e, ¢→c, ¥→y, $→s。

**d→0 和 f→7 的混淆**不加入全局纠错（d/f 是合法 hex 字符），但登录失败后通过 `_generate_passport_candidates` 生成互换候选（含 7↔f、d 暂未覆盖）。

---

## 5. 代码位置

| 文件 | 函数/方法 | 说明 |
|------|-----------|------|
| `douluo_launcher/automation.py` | `_extract_passport_from_login_window()` | 后台截图 + OCR 入口 |
| `douluo_launcher/automation.py` | `_ocr_passport_from_login_image()` | 全图 OCR 核心（多尺度+灰度） |
| `douluo_launcher/automation.py` | `extract_passport_from_text()` | 方式1 正则匹配 |
| `douluo_launcher/automation.py` | `extract_hex_passport()` | 方式3 hex 提取 + 字符纠错 |
| `douluo_launcher/dm_client.py` | `capture_window_background()` | 后台截图（BitBlt + 回退） |
| `douluo_launcher/dm_client.py` | `select_login_window_by_game_no()` | 按游戏窗口号定位登录程序窗口 |

### 实验性方法（保留代码，当前不作为主方案）

| 文件 | 函数/方法 | 说明 |
|------|-----------|------|
| `douluo_launcher/automation.py` | `_crop_passport_hex_region()` | 粉色横条定位 + 裁剪通行证文字区域 |
| `douluo_launcher/automation.py` | `_ocr_chars_template_match()` | 16 字符滑动窗口模板匹配 |

---

## 6. OCR 调试方式

1. 查看 `debug_ocr/latest_ocr_success.png` — 最新一次成功识别的截图
2. 查看 `debug_ocr/history/error_*/` — 失败时的截图现场
3. 查看 GUI 日志中的 OCR 原始文本输出（每个 scale/psm 变体）

---

## 7. 废弃函数（保留代码但不调用）

以下函数在 `automation.py` 中保留但当前 OCR 流程不再调用：

- `_locate_qr_box()` — 二维码定位
- `_locate_qr_box_fallback()` — 暗像素搜索回退
- `_passport_crop_box_from_qr()` — 二维码底部偏移裁剪
- `_find_red_bar_below_qr()` — 红色横条扫描
- `_draw_debug_boxes()` — 调试框绘制

---

## 8. 禁止事项

- ❌ 先定位二维码再裁剪区域做 OCR
- ❌ 从浏览器页面截图做 OCR（登录程序窗口 ≠ 浏览器页面）
- ❌ 从 Playwright page 截图 OCR 通行证
- ❌ 从 URL/DOM/iframe 提取通行证
- ❌ 使用任何需要二维码位置的裁剪逻辑
