# 通行证获取与 OCR 兜底方案

**日期：2026-05-08**
**最近更新：2026-05-17**
**状态：复制优先，OCR 兜底；OCR 不再低置信度放行**

> 重要更新：OCR 不再作为第一优先级。当前通行证获取先尝试从登录程序窗口双击选中 8 位通行证并 `Ctrl+C` 复制，复制失败后才进入 OCR 兜底。

> 收尾规则：已登录窗口、公告界面、游戏界面不能继续 OCR。只有明确 `qr_page` 才允许复制通行证或 OCR；`unknown`、截图失败、二维码页仍存在都不能判成功。后续修改前需按 `D:\Ai\skills\launcher-regression-guard\SKILL.md` 做防回归检查。

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

## 2. 当前正式方案

### 核心流程

```
登录程序窗口完整截图（BitBlt 后台截图 + ImageGrab 回退）
→ 判断为二维码登录页
→ 双击底部通行证文本区域并 Ctrl+C
→ 读取剪贴板中的 8 位 hex 通行证
→ 复制失败时进入 OCR 兜底
→ OCR 通过候选票数、字符级投票和混淆字符检查后才可接受
```

### 关键特性

- **复制优先** — 成功复制时直接采用剪贴板结果
- **OCR 兜底** — 仅在复制失败时启用
- **宁可失败，不假成功** — OCR 不确定时不得继续输入通行证
- **混淆字符强拦截** — 同一位置出现 `c/e` 竞争时必须失败或进入人工处理

### OCR 风险背景

OCR 存在单字符误识别风险，例如：

| 真实通行证 | 错误结果 | 错误位置 |
|------------|----------|----------|
| `4425cbaa` | `4425ebaa` | `c` 被识别为 `e` |

因此 OCR 不再作为第一优先级。复制成功时直接使用复制结果；复制失败时才进入 OCR。OCR 低置信度、候选不一致、字符级投票不一致或出现 `c/e` 竞争时，必须失败，不能继续输入。

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

## 4. OCR 兜底规则（2026-05-15 更新）

OCR 兜底不再第一个成功就返回，也不再低票数接受最佳候选。当前规则：

1. 收集所有 OCR 变体的候选结果。
2. 输出每个候选结果和候选票数。
3. 对 8 位通行证逐位做字符级投票。
4. 输出每一位字符投票结果。
5. 输出存疑位置。
6. 输出是否接受。
7. 输出失败类型。

新增失败类型：

| 失败类型 | 触发条件 |
|----------|----------|
| `OCR_LOW_CONFIDENCE` | 总票数不足、候选不一致、逐位投票不一致 |
| `OCR_AMBIGUOUS_CHAR` | 某一位同时出现 `c` 和 `e` 竞争 |

原则：**宁可真实失败，也不要错误输入通行证。**

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

当前纠错管线仍可用于 OCR 候选提取，但最终是否接受必须经过候选投票和字符级投票。`c/e` 竞争属于高风险误识别，必须判定为 `OCR_AMBIGUOUS_CHAR`，不能自动选择其中一个。

---

## 5. 代码位置

| 文件 | 函数/方法 | 说明 |
|------|-----------|------|
| `douluo_launcher/automation.py` | `_extract_passport_from_login_window()` | 后台截图 + OCR 入口 |
| `douluo_launcher/automation.py` | `_copy_passport_from_login_window()` | 复制优先获取通行证 |
| `douluo_launcher/automation.py` | `_decide_ocr_candidate()` | OCR 候选票数、字符级投票、失败类型判定 |
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
- ❌ OCR 低置信度时继续输入通行证
- ❌ `c/e` 混淆时自动猜测一个结果
# 通行证与校验安全补充（2026-05-17）

当前仍保持以下规则：

- 通行证获取优先复制，复制失败才进入 OCR 兜底。
- OCR 不再低置信度直接接受。
- `c/e` 等混淆字符必须失败或进入人工处理。
- 单账号运行仍执行完整校验。
- 当前层串行 / 全部串行虽然改为快速提交 + 统一校验，但统一校验仍然坚持：
  - `logged_in` 才成功
  - `qr_page` 不成功
  - `unknown` 不成功
  - 截图失败不成功

已验证：9 个单层账号批量快速登录 + 统一校验最终全部成功，总 9，成功 9，失败 0。

---
