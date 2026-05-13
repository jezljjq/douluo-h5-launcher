# 当前问题和限制

**日期：2026-05-13**

---

## 0. 2026-05-13 速度优化记录

### 优化成果

单账号 QR 登录耗时从 ~17.8s → 10.5s → **7.5s**（-58%，warm start）。冷启动 ~9.5s。

| 步骤 | 优化前 | 优化后 | 手段 |
|------|--------|--------|------|
| 打开页面 | 2.9s | 0.9s | canvas 轮询替代固定 2s 等待 |
| 关闭公告 | 1.3s | 0.6s | 减少固定 sleep |
| 点击+输入 | 2.5+2.4=4.9s | 4.1s | Dm 合并链式调用（按钮+输入一次子进程） |
| 校验 | 0.2s | 0.2-0.4s | 快速状态检测 + 10s 时间预算 |

### 关键改动
- `dm_click_helper.py` 链式调用支持 `wait` 步骤
- 按钮点击+输入合并为一次 `_dm_chain` 调用（省一次 32位Python 子进程启动）
- `detect_login_page_state`：else 分支改为 `logged_in`（非二维码即已登录）
- `_quick_login_state()`：仅截图+图像特征，不做 OCR
- `_is_passport_dialog_visible_by_ocr`：视觉检测在前 + gray_ratio<0.10 快速排除
- `passport_btn_viewport` 回退坐标修正为 `(683,234)`
- `passport_input_ratio` / `confirm_button_ratio` 根据实际位置校准
- OCR 失败二次确认后弹窗手动输入（首次失败也会触发）

---

## 0. 2026-05-12 修复记录

### 已修复：`subprocess.Popen` monkey-patch 导致 Playwright/asyncio 崩溃

**症状**：点"全部串行"后报 `TypeError: function() argument 'code' must be code, not str`

**根因**：`automation.py` 模块级 `subprocess.Popen = _no_console_popen` 用 function 替换了 class，导致 asyncio 的 `windows_utils.Popen(subprocess.Popen)` 继承失败。

**修复**：
1. 用 class 继承替代 function：`class _NoConsolePopen(_original_popen)` 保持 Popen 是类
2. Playwright 导入前临时恢复原始 Popen，导入后恢复补丁（`run()` 和 `run_game_flow()` 两处）

### 已修复：重试时相同通行证跳过完整浏览器流程

**症状**：第1次登录失败 → 重试时 OCR 读到相同通行证 → 直接抛异常跳过，不重新打开浏览器

**修复**：删除"相同通行证→跳过"的检查，重试始终走完整浏览器流程（关旧浏览器→开新→公告→按钮→输入→确认→校验）

### 运行效果

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 成功率 (31账号) | 24/31 (77%) | 29/31 (94%) |
| 耗时 | 843秒 | 366秒 |

---

## 1. 当前已知限制

### 前台模式限制

| 限制 | 影响 | 说明 |
|------|------|------|
| 非后台运行 | 运行时不能操作电脑 | Dm 前台点击必须独占鼠标 |
| 非真并发 | 32 个账号需严格串行完成 | 前台点击不能并发 |
| 鼠标会物理移动 | 干扰用户正常工作 | 临时方案，后续需升级为真后台 |
| 窗口必须可见 | 不能最小化或遮挡 | Dm MoveTo 需要可见屏幕坐标 |

### 当前风险

| 风险 | 影响 | 说明 |
|------|------|------|
| 登录程序窗口状态判断 | 二维码页可能误判为已登录 | `detect_login_page_state` 依赖阈值调优 |
| OCR 通行证识别 | 部分截图 OCR 质量不稳定 | 文字区域 OCR + 全图 OCR 兜底 |
| 窗口标题变化 | `H5-{n}-` 格式可能改变 | 后续需支持坐标排序映射 |

### 方式二暂不开发

- 方式二（账号密码 + 通行证上号）暂未开发
- `密码.csv` 保留在本地用于后续开发，已配置 .gitignore 不提交

### Chrome Canvas 限制

| 限制 | 影响 | 说明 |
|------|------|------|
| isTrusted 检测 | Playwright/CDP 合成事件全部被拦截 | Chrome 安全策略，无法绕过 |
| GPU 渲染管线 | SendMessage/PostMessage 不转发到游戏 | Chrome 绕过 Windows 消息机制 |
| Dm BindWindow 崩溃 | 7.2607 + Win11 = SIGSEGV | 36/36 全模式崩溃，无法后台绑定 |

### 其他限制

| 限制 | 影响 |
|------|------|
| 需 32 位 Python 子进程 | 环境依赖复杂，需同时安装 64/32 两个 Python |
| 分辨率适配 | 当前仅验证 960×720 viewport |
| OCR 偶发失败 | ~5% 概率需重试，投票+候选互换已覆盖大部分场景（已知 f↔7 混淆） |

---

## 2. 已验证不可用的方案

| 方案 | 测试结果 | 不可用原因 |
|------|----------|------------|
| Dm 7.2607 BindWindow | 36/36 崩溃 | Win11 不兼容 |
| Playwright canvas click | 全部被拦截 | isTrusted 检测 |
| CDP Input.dispatchMouseEvent | 全部被拦截 | isTrusted 检测 |
| PostMessage WM_LBUTTONDOWN | 无效果 | Chrome 不转发 |
| SendMessage 到 Chrome_RenderWidgetHostHWND | 无效果 | GPU 渲染绕过 |
| JS 注入覆盖 isTrusted | 无效 | 注入时机太晚/额外检测 |
| 二维码定位 + 裁剪 OCR | 不稳定 | 位置不固定 |
| Dm OpenClipboard API | 句柄无效 | 多进程冲突 |
| Dm KeyPressChar 逐字输入 | 焦点不确定 | 窗口可能不在前台 |

---

## 3. 当前可用但有限制的方案

| 方案 | 限制 |
|------|------|
| Dm 无绑定前台点击 | 会移动鼠标，需独占 |
| clip.exe + Dm Ctrl+V 粘贴 | 需浏览器在前台 |
| BitBlt 后台截图 | 部分窗口可能黑屏，需 ImageGrab 回退 |
| Tesseract 全图 OCR | ~10% 失败率，自动重试覆盖 |
| Popen 子进程隔离（仅源码模式） | 每个账号需启动新 Python 进程（~2s 开销）；exe 模式同进程调用无需此开销 |

---

## 4. 当前必须遵守

- 不要回退二维码定位/裁剪 OCR
- 不要对浏览器页面 OCR 通行证
- 不要继续尝试 Dm BindWindow（当前版本不兼容 Win11）
- 不要使用 Playwright/CDP/PostMessage/SendMessage 点击游戏 canvas
- 不要开启真并发（前台模式不支持）

---

## 5. 分辨率与窗口尺寸依赖

### 当前版本定位

**当前窗口尺寸稳定版，不是完全自适应分辨率版本。**

### 浏览器 viewport

- 固定为 **960×720**，通过 `automation_settings.json` 的 `window_width` / `window_height` 配置
- Playwright 启动参数 `--window-size` 和 `viewport` 均使用此配置
- 模板匹配、视觉定位的 ROI 区域基于 viewport 比例计算（支持调整配置值，但仅在 960×720 下验证过）

### 登录程序窗口

- WindowsForms 窗口固定 **320×540**，由登录程序自身决定
- OCR 截图按窗口实际尺寸（`capture_window_background` 自适应）
- 标题匹配规则：`斗罗大陆H5-{游戏窗口号}-`（如 `斗罗大陆H5-9-伊导科技`）

### 固定坐标/区域

| 项目 | 类型 | 说明 |
|------|------|------|
| 模板匹配 | 固定模板 27×36 | `template_passport_btn.png`，仅在 960×720 下提取 |
| 按钮回退坐标 | 固定 viewport 坐标 | `passport_btn_viewport: (683, 290)`，模板匹配失败时使用 |
| 公告关闭 | 固定 canvas 坐标 | `page.mouse.click(740, 680)`，非比例计算 |
| 输入框/确认按钮 | **比例计算** | `window_width * ratio`，配置可调但仅验证 960×720 |
| 视觉定位 ROI | **比例计算** | `int(width * 0.25)` 等，配置无关但未在其他分辨率测试 |
| 窗口排列 | 固定间距 | `gap_x=20, gap_y=40`，仅适用于 960×720 |

### 后续如需支持不同分辨率

需单独处理：
- 模板按比例缩放匹配（`cv2.matchTemplate` 多尺度）
- 公告关闭改为比例坐标或视觉定位
- 按钮回退坐标按 viewport 比例重新计算
- 在不同分辨率下重新验证视觉定位 ROI

---

## 6. 窗口定位方式

### 自动枚举 + 标题匹配（非写死 hwnd）

1. 根据层级和收藏编号计算游戏窗口号（如 第二层 收藏1 → 窗口9）
2. `select_login_window_by_game_no(game_window_no)` 枚举当前系统所有可见窗口
3. 按标题匹配规则 `H5-{number}-` 自动选中对应登录程序窗口
4. 浏览器窗口同样自动枚举：`_find_game_browser_window()` 按标题关键词匹配

窗口句柄不在代码中写死，运行时自动获取。但如果窗口标题格式变化（如不再包含 `H5-{number}-`），需调整 `window_title_matches_game_no` 中的匹配规则。
