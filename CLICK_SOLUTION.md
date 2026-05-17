# 点击方案记录

**日期：2026-05-08**
**最近更新：2026-05-17**
**状态：前台模式已稳定，Dm 无绑定点击 + 剪贴板粘贴通过实机验证**

> 收尾状态：文件级通行证弹窗坐标缓存和合并 Dm chain 已验证生效；停止任务和关闭程序清理子进程已修复。后续修改点击、输入、停止清理前必须按 `D:\Ai\skills\launcher-regression-guard\SKILL.md` 做防回归检查。

---

## 1. 已废弃/不可用方案

### 浏览器层点击

| 方案 | 结果 | 失败原因 |
|------|------|----------|
| Playwright `page.mouse.click` | ❌ | Canvas 游戏 `isTrusted` 检测拦截 |
| Playwright `locator.click` | ❌ | 同上 |
| CDP `Input.dispatchMouseEvent` | ❌ | 同上 |
| JS 注入覆盖 `isTrusted` | ❌ | `add_init_script` 注入时机太晚 / 游戏使用额外检测 |

### 系统消息点击

| 方案 | 结果 | 失败原因 |
|------|------|----------|
| PostMessage WM_LBUTTONDOWN | ❌ | Chrome GPU 渲染管线绕过 Windows 消息机制 |
| SendMessage 到 Chrome_RenderWidgetHostHWND | ❌ | 同上 |
| SendMessage 到 Intermediate D3D Window | ❌ | 同上 |

### 大漠后台绑定

| 方案 | 结果 | 失败原因 |
|------|------|----------|
| Dm BindWindow（全模式） | ❌ | 36/36 崩溃（3 窗口 × 12 模式），7.2607 与 Win11 不兼容 |
| Dm BindWindowEx | ❌ | 同上 |

---

## 2. 当前正式方案：大漠无绑定前台点击

### 原理

Dm 不需要 BindWindow 即可调用内核级屏幕操作：

- `dm.MoveTo(x, y)` — 移动鼠标到屏幕坐标
- `dm.LeftDown()` / `dm.LeftUp()` — 按下、保持 120-150ms、抬起
- `dm.KeyDown(17)` + `dm.KeyPress(86)` + `dm.KeyUp(17)` — Ctrl+V 粘贴

这些操作通过内核级输入模拟，canvas 游戏无法区分与真实用户点击的差异。

### 实现架构

```
64-bit Python（Playwright 浏览器管理 + OCR + 模板匹配）
    ↓ 写 browser_pos.json（浏览器渲染区屏幕坐标）
    ↓ 子进程调用 dm_click_helper.py
32-bit Python（Dm 点击/输入子进程）
    ↓ 读 browser_pos.json
    ↓ win32gui.ShowWindow + SetForegroundWindow（前置浏览器）
    ↓ dm.MoveTo + LeftDown + 延迟 + LeftUp（点击）
    ↓ clip.exe + dm.KeyDown(Ctrl) + KeyPress(V) + KeyUp(Ctrl)（粘贴输入）
```

### 关键文件

| 文件 | 说明 |
|------|------|
| `dm_click_helper.py` | 32 位 Dm 前台点击/输入脚本，支持 `click`、`type`、`chain` 三种模式 |
| `debug_ocr/browser_pos.json` | 浏览器渲染窗口屏幕坐标缓存，含 `hwnd/cx/cy` |
| `douluo_launcher/automation.py:_dm_click_viewport()` | 发起 Dm 前台点击 |
| `douluo_launcher/automation.py:_dm_type_text()` | 发起 Dm 剪贴板粘贴输入 |
| `douluo_launcher/automation.py:_dm_chain()` | 链式调用：一次子进程执行 click+type+click 多步操作 |

### 稳定模块说明

Dm 点击、剪贴板粘贴输入、Playwright 初始化、公告关闭、通行证输入和确认逻辑均属于当前稳定链路。除非有明确 bug 和用户确认，不要在窗口管理、文档、UI 美化等任务中顺手修改这些流程。

当前通行证文本获取已改为“复制优先，OCR 兜底”。这里的剪贴板粘贴输入仍用于浏览器通行证弹窗输入，和登录程序窗口复制通行证是两个不同环节。

### 停止与关闭清理机制

停止任务机制已修复并验证通过：

- 点击“停止任务”后，不再只是设置 `stop_event`。
- 会强制终止当前账号运行子进程。
- 会清理命令行包含 `dm_click_helper.py` 的 32 位大漠点击子进程。
- 会清理本次 Playwright/Chromium 相关进程。
- 不再继续后续账号。

关闭程序机制已修复并验证通过：

- 点击窗口右上角关闭时，会先执行停止任务和子进程清理。
- GUI 关闭后，不允许残留子进程继续移动鼠标。
- `_drain_ui_queue` 在窗口关闭后不再继续 `after` 回调。

清理规则：禁止误杀所有 `python.exe`，只能清理本项目记录的账号子进程，或命令行明确包含 `dm_click_helper.py` 的进程。

### 链式调用（速度优化）

为减少 32 位 Python 子进程冷启动开销（~1s/次），输入流程使用 `chain` 模式合并多步操作：

```
py -3.14-32 dm_click_helper.py chain "click,473,290,120|type,abc12345"
```

一次子进程调用完成点击输入框+输入文本，节省 ~1s。候选重试更进一步合并输入+确认为单链。`creationflags=CREATE_NO_WINDOW` 防止弹黑框。

### 坐标计算

```
1. 枚举 Chrome 顶层窗口 → 找到游戏浏览器窗口（标题含 "7tu7tu" 或 "7兔" 或 "斗罗"）
2. 枚举子窗口 → 找到 Chrome_RenderWidgetHostHWND
3. GetWindowRect → 获取渲染窗口屏幕坐标 (cx, cy)
4. 写入 debug_ocr/browser_pos.json
5. 对同一渲染窗口截图并裁剪渲染区（Chrome_RenderWidgetHostHWND rect）
6. 模板匹配 → 获取按钮 viewport 坐标 (vx, vy)
7. 屏幕坐标 = (cx + vx, cy + vy)
8. Dm MoveTo + LeftDown + 延迟 + LeftUp
```

### 坐标系修正（2026-05-09）

关键修正：截图和点击必须使用同一坐标系。

- 旧代码：截图裁 Chrome 客户区（含地址栏），点击原点用 Chrome_RenderWidgetHostHWND 渲染区 → 坐标偏移 87px
- 当前代码：截图裁 Chrome_RenderWidgetHostHWND 渲染区，点击原点也用同一渲染区 → 坐标统一

这个修正已通过实机端到端验证。

---

## 3. 通行证按钮定位：模板匹配

### 为什么不用 OCR 中文定位

Tesseract `chi_sim+eng` 无法识别 canvas 游戏渲染的中文字符。

### 模板匹配方案

| 项目 | 值 |
|------|-----|
| 模板文件 | `debug_ocr/template_passport_btn.png` |
| 模板尺寸 | 27×36 像素 |
| 匹配算法 | `cv2.TM_CCOEFF_NORMED` |
| 阈值 | score >= 0.6 |
| 回退坐标 | `automation_settings.json` 的 `passport_btn_viewport` |
| 点击策略 | 5 个备选点（中心、下偏移28/42、左右偏移）依次尝试 |

### 通行证弹窗视觉校验

点击按钮后，不单靠 OCR 判断弹窗是否出现。联合使用：

- `_looks_like_passport_dialog()` — 灰色面板像素占比检测
- `_locate_passport_input_center()` — 深灰输入框轮廓定位
- `_locate_confirm_button_center()` — 黄色按钮检测（选 y 最小候选避免误选"进入游戏"）

---

## 4. 当前版本定位

### 前台串行模式

| 项目 | 说明 |
|------|------|
| 版本定位 | **前台串行模式** |
| 点击方式 | Dm 无绑定前台点击（会短暂移动鼠标） |
| 输入方式 | clip.exe 剪贴板 + Dm Ctrl+V 粘贴 |
| 并发能力 | **不支持**。严格串行：账号1 完成 → 账号2 开始 |
| 后台运行 | **不支持**。需要窗口在屏幕上可见 |
| 遮挡运行 | **不支持**。窗口被遮挡时点击可能失败 |
| GUI 标题 | "上号器 — 前台串行模式" |

### 限制

| 限制 | 说明 |
|------|------|
| 会短暂移动鼠标 | Dm MoveTo + LeftDown/LeftUp 物理移动光标 |
| 运行期间勿操作鼠标 | 用户鼠标移动会干扰 Dm 点击位置 |
| 不支持真后台点击 | 无法在窗口遮挡/最小化时点击 |
| 需要 32 位 Python 子进程 | Playwright 无法在 32 位 Python 安装 |
| 坐标暂不做分辨率适配 | 当前按 960×720 viewport |
| exe 模式子进程弹黑框 | 已通过 `subprocess.CREATE_NO_WINDOW` 修复 |
| cv2.imread 中文路径 | 已改为 `cv2.imdecode(np.fromfile(...))` 修复 |

---

## 5. exe 模式特殊处理

exe 打包后（PyInstaller --onedir --windowed），点击流程有以下调整：

1. **全局子进程隐藏控制台**：所有显式子进程调用添加 `CREAT_NO_WINDOW`，且 `automation.py` 模块级 monkey-patch `subprocess.Popen` 覆盖 pytesseract→tesseract.exe 等第三方库内部调用。

2. **模板读取兼容中文路径**：`cv2.imread()` 不支持中文路径，改用 `cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)`。

3. **截图前强制浏览器前置**：`_capture_browser_client()` 调用前执行 `BringWindowToTop` + `SetForegroundWindow`，防止 Tkinter GUI 窗口抢焦点导致 ImageGrab 截到桌面。

---

## 6. 后续方向

- 大漠新版本（当前 7.2607，需确认是否有 Win11 兼容版本）
- 64 位大漠插件注册（当前仅 32 位 ProgID 可用）
- DD 虚拟驱动等真后台替代方案

---

## 7. 禁止事项

- ❌ 不要继续尝试 Dm 7.2607 BindWindow（已确认全模式崩溃）
- ❌ 不要使用 PostMessage/SendMessage 做 Chrome canvas 点击
- ❌ 不要使用 Playwright/CDP 合成事件做 canvas 点击
- ❌ 不要把停止任务实现成只设置 `stop_event`
- ❌ 不要用杀全部 `python.exe` 的方式清理子进程
- ⚠️ Dm 无绑定前台点击是当前的唯一可用方案，后续可升级为真后台方案
- ⚠️ UI 美化不得影响 Dm 点击、输入、确认和校验链路
# 点击与输入加速补充（2026-05-17）

当前方式一批量上号已使用通行证弹窗坐标文件缓存：

- 缓存文件：`debug_ocr/passport_dialog_pos_cache.json`
- 缓存 key：浏览器真实 viewport，例如 `960x720`
- 缓存内容：通行证按钮坐标、输入框坐标、确认按钮坐标、更新时间
- 作用：源码模式下不同账号子进程也能复用弹窗坐标

命中缓存后使用合并 Dm chain：

```text
click 通行证按钮
wait
click 输入框
type 通行证
click 确认
```

已验证：

- 能读取通行证弹窗坐标缓存。
- 能使用合并 Dm chain。
- 合并 Dm chain 耗时约 `2.4s`。
- 9 个单层账号批量快速登录 + 统一校验最终全部成功。

安全边界：

- 合并 Dm chain 只优化点击/输入调用方式。
- 不修改通行证复制优先逻辑。
- 不修改 OCR 兜底规则。
- 不修改登录成功校验规则。
- `qr_page`、`unknown`、截图失败都不能判成功。

---
