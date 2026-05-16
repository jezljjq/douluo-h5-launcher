# 斗罗大陆H5上号器（前台串行稳定版）

**当前阶段：前台串行模式，方式一和方式二均已接入；窗口管理区已接入。方式一单层 9 账号已验证“快速提交 + 统一校验”最终全部成功。**

> 项目级开发规则见 [CLAUDE.md](CLAUDE.md)。

---

## 1. 项目定位

自动登录"斗罗大陆H5"游戏，支持最多 32 个账号（4 层 × 8 账号），前台串行逐个完成登录。

### 核心流程

```
登录程序窗口复制优先获取通行证（OCR 兜底）
→ 浏览器打开游戏页
→ 关闭公告
→ 模板匹配定位通行证按钮
→ Dm 前台点击打开弹窗
→ 剪贴板粘贴输入通行证
→ 视觉定位确认按钮并点击
→ 回到登录程序窗口校验 QR 码是否消失
→ 成功 / 失败重试
```

---

## 2. 当前已完成

| 模块 | 状态 | 方案 | 文档 |
|------|------|------|------|
| 通行证获取 | ✅ 已调整 | 复制优先，OCR 兜底；OCR 不再低置信度放行 | [OCR_SUCCESS.md](OCR_SUCCESS.md) |
| 后台截图 | ✅ 稳定 | BitBlt + ImageGrab 回退 | [OCR_SUCCESS.md](OCR_SUCCESS.md) |
| 通行证按钮定位 | ✅ 稳定 | OpenCV 模板匹配 | [CLICK_SOLUTION.md](CLICK_SOLUTION.md) |
| Dm 前台点击 | ✅ 稳定 | Dm 无绑定 MoveTo + LeftDown/LeftUp | [CLICK_SOLUTION.md](CLICK_SOLUTION.md) |
| 剪贴板粘贴输入 | ✅ 稳定 | clip.exe + Dm Ctrl+V | [CLICK_SOLUTION.md](CLICK_SOLUTION.md) |
| 公告关闭 | ✅ 稳定 | Playwright canvas 右下角点击 | — |
| 确认按钮定位 | ✅ 稳定 | 视觉黄色按钮检测（y最小+x最大） | [CLICK_SOLUTION.md](CLICK_SOLUTION.md) |
| 单账号完整流程 | ✅ 稳定 | 7 步流程 + 失败自动重试 | — |
| 前台串行批量 | ✅ 稳定 | Popen 子进程隔离 + 实时状态同步 | [RUN_MODE.md](RUN_MODE.md) |
| GUI 状态同步 | ✅ 稳定 | Treeview + 颜色标签 + 实时刷新 | [GUI_STATUS_FLOW.md](GUI_STATUS_FLOW.md) |
| 调试截图管理 | ✅ 已整理 | _tmp / history / latest_* 三级管理 | [DEBUG_IMAGE_POLICY.md](DEBUG_IMAGE_POLICY.md) |
| 失败重试 | ✅ 已实现 | 任意失败自动重试 1 次 | — |
| 收藏夹映射 | ✅ 稳定 | 4层×8编号→游戏窗口号1-32 | — |
| 方式二（账号密码+通行证） | ✅ 稳定 | CSV导入+Playwright DOM登录+Dm输入 | [DESIGN_METHOD2.md](DESIGN_METHOD2.md) |
| CSV 导入 | ✅ 稳定 | encoding 自动检测 + 路径记忆 | — |
| 耗时统计 | ✅ 已实现 | 分阶段计时 + 日志+表格双显示 | — |
| 截图/日志清理 | ✅ 已实现 | _error/ 保留10张，logs/ 保留2份 | — |
| 窗口管理区 | ✅ 已接入 | 批量启动、识别、排列、关闭、重命名、参数记忆 | [docs/WINDOW_MANAGER_AND_PASSPORT_MILESTONE.md](docs/WINDOW_MANAGER_AND_PASSPORT_MILESTONE.md) |
| 停止任务/关闭清理 | ✅ 已验证 | 停止时终止账号子进程、清理 dm_click_helper.py 和 Chromium | [CLICK_SOLUTION.md](CLICK_SOLUTION.md) |
| 通行证弹窗坐标缓存 | ✅ 已验证 | `debug_ocr/passport_dialog_pos_cache.json` 按 viewport 缓存 button/input/confirm，跨账号/子进程复用 | [CLICK_SOLUTION.md](CLICK_SOLUTION.md) |
| 批量快速登录 + 统一校验 | ✅ 已验证 | 当前层/全部串行先快速提交，统一校验后只重登失败账号；9 个单层账号最终 9/9 成功 | [docs/LAUNCHER_FINAL_MILESTONE.md](docs/LAUNCHER_FINAL_MILESTONE.md) |

### 2.1 当前窗口管理区能力

窗口管理功能已经从独立工具迁入上号器内部模块。上号器不应依赖独立项目 `DLH5WindowManager` 的本地路径；即使独立项目移动或删除，上号器内部窗口管理功能理论上也不应受影响。

当前窗口管理区支持：

- 游戏路径
- 打开数量
- 启动间隔(ms)
- 启动后自动排列
- 排列后自动编号标题
- 标题模板
- 重命名
- 窗口宽度
- 窗口高度
- 每行数量
- 起点 X
- 起点 Y
- 横向偏移
- 纵向偏移
- 批量启动窗口
- 识别窗口
- 排列窗口
- 关闭窗口

窗口管理参数记忆保存到上号器项目内部独立配置文件 `window_manager_settings.json`。该能力已代码实现，但暂未现场验证，不能写作“实机验证通过”。

---

## 2.2 快速登录缓存与统一校验（2026-05-17）

当前方式一批量串行已接入：

- 通行证弹窗坐标文件缓存：`debug_ocr/passport_dialog_pos_cache.json`。
- 缓存 key 使用浏览器真实 viewport，例如 `960x720`。
- 缓存内容包含通行证按钮、输入框、确认按钮坐标和更新时间。
- 命中缓存后使用合并 Dm chain：
  `click 通行证按钮 → wait → click 输入框 → type 通行证 → click 确认`。
- 当前层串行 / 全部串行使用“快速提交 + 统一校验 + 失败重登”。
- 单账号运行仍保留完整校验逻辑。
- `重新次数` 用于限制统一校验和失败重登轮数；全部成功会提前结束。

已验证结果：

- 已读取通行证弹窗坐标缓存。
- 已使用合并 Dm chain，合并 chain 耗时约 `2.4s`。
- 9 个单层账号批量快速登录 + 统一校验最终全部成功。
- 最终结果：总 9，成功 9，失败 0。

安全规则：

- `qr_page` 不能判成功。
- `unknown` 不能判成功。
- 截图失败不能判成功。
- 只有明确 `logged_in` 才能成功。
- 失败账号只重登失败账号，不全量重跑。

---

## 2.5 最近修复（2026-05-12/13/14）

| 问题 | 修复 |
|------|------|
| `subprocess.Popen` monkey-patch 导致 asyncio 崩溃 | function→class 继承（`_NoConsolePopen`），Playwright 导入前恢复原始 Popen |
| 重试时相同通行证跳过完整流程 | 删除跳过逻辑，重试始终走完整浏览器流程 |
| exe 启动有黑框 | 切换 `--noconsole` 引导器 |
| 登录程序窗口状态判断不稳定 | 新增 `detect_login_page_state` 图像特征检测 |
| 二维码页 OCR 被 QR 码干扰 | 确认 qr_page 后优先用底部文字区域 OCR |
| 日志路径不统一 | 新增 `project_root()`，exe 模式日志也落到项目根 `logs/` |
| 方式一失败状态不更新 | `run_game_flow` retry=1 缺少 `raise RuntimeError` |
| 方式二 finally 固定 sleep(3) | 已登录账号不打开浏览器也等3s → 有浏览器才等2s |
| CSV 耗时列偏移 | `values[-1]` 指向 timing 列 → 改为显式 `values[6]` |
| OCR hex 字符混淆 c↔0/e | 通行证获取已改为复制优先；OCR 兜底遇到低置信度或 c/e 竞争必须失败 |
| 停止任务后仍可能继续移动鼠标 | 已修复：停止按钮会强制终止当前账号子进程、清理 `dm_click_helper.py` 和 `chromium.exe` |
| 关闭 GUI 后仍可能残留子进程 | 已修复：窗口关闭会先执行停止和清理，并避免 `_drain_ui_queue` 继续 after 回调 |

## 3. 当前架构

```
┌─────────────────────────────────────────────────┐
│  64-bit Python (主进程)                          │
│  ├── Tkinter GUI (LauncherApp)                  │
│  ├── Playwright (浏览器管理)                      │
│  ├── Tesseract OCR (全图通行证提取)               │
│  ├── OpenCV (模板匹配 + 视觉定位)                  │
│  └── BitBlt (后台截图)                           │
│       │                                          │
│       ▼ 写 browser_pos.json                      │
│  32-bit Python (Dm 子进程)                       │
│  ├── dm.MoveTo + LeftDown/LeftUp (前台点击)       │
│  └── clip.exe + dm.KeyDown(Ctrl+V) (剪贴板输入)   │
│                                                  │
│  前台串行：Popen 子进程逐账号隔离 Playwright        │
└─────────────────────────────────────────────────┘
```

---

## 4. 对象关系

- 收藏编号只用于读取收藏夹链接
- 游戏窗口号 = 收藏编号 + 层级偏移量（第一层+0, 第二层+8, 第三层+16, 第四层+24）
- 登录程序窗口标题如 `斗罗大陆H5-9-伊导科技`，按游戏窗口号匹配
- 二维码和通行证只存在于登录程序窗口（WindowsForms 桌面应用）
- 浏览器游戏页面只有游戏 canvas 和 UI 按钮

---

## 5. 两种上号方式

### 方式一：收藏夹链接 + 通行证上号（✅ 已开发，当前主流程）

- 从浏览器收藏夹读取游戏入口链接
- 从登录程序窗口优先复制 8 位通行证，复制失败才进入 OCR 兜底
- 支持单账号、当前层串行、全部串行

### 方式二：CSV 配置文件 + 账号密码 + 通行证上号（✅ 已开发）

- 通过 CSV 文件配置账号（`name,url,username,password`）
- 仍然需要先从登录程序窗口获取通行证，不是只用账号密码
- 通行证获取同样遵循复制优先、OCR 兜底
- password 不打印到日志，GUI 仅显示"已填写/未填写"
- 支持单账号和串行批量

### 通行证获取优先级

1. 第一优先级：双击选中登录窗口中的 8 位通行证，`Ctrl+C` 复制，读取剪贴板。
2. 第二优先级：复制失败后才进入 OCR 兜底。

OCR 不再作为第一优先级。原因是 OCR 存在单字符误识别风险，例如真实值 `4425cbaa` 可能被识别为 `4425ebaa`，错误位置为 `c` 被识别为 `e`。复制成功时直接使用复制结果；复制失败时才进入 OCR。OCR 低置信度时不得继续输入通行证，存在 `c/e` 等混淆时必须失败或进入人工处理，不能假成功。

---

## 6. 运行方式

详见 [RUN_MODE.md](RUN_MODE.md)。

```powershell
cd D:\Ai\codex\上号器
python main.py
```

GUI 按钮：
- **单账号运行** — 运行下拉框选中的账号
- **当前层串行** — 逐个运行当前选择层级全部账号
- **全部串行** — 逐个运行所有已加载账号

### 打包发布

```powershell
.\scripts\build_exe.bat
```

输出：`dist/斗罗大陆H5上号器/斗罗大陆H5上号器.exe`

详见 [BUILD.md](BUILD.md)。

---

## 7. 项目结构

详见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。

核心文件：
- [main.py](main.py) — 程序入口
- [douluo_launcher/gui.py](douluo_launcher/gui.py) — Tkinter GUI
- [douluo_launcher/automation.py](douluo_launcher/automation.py) — 账号运行流程
- [douluo_launcher/config.py](douluo_launcher/config.py) — 配置和收藏夹读取
- [douluo_launcher/dm_client.py](douluo_launcher/dm_client.py) — 窗口管理和后台截图
- [douluo_launcher/window_manager.py](douluo_launcher/window_manager.py) — 登录窗口批量启动、识别、排列、关闭、重命名
- [douluo_launcher/window_manager_settings.py](douluo_launcher/window_manager_settings.py) — 窗口管理参数记忆
- [dm_click_helper.py](dm_click_helper.py) — 32 位 Dm 点击/输入脚本
- [automation_settings.json](automation_settings.json) — 自动化参数

**运行必要目录**：
- `debug_ocr/` — 运行必须（含 `template_passport_btn.png`、`browser_pos.json`）
- `logs/` — 日志目录（运行时自动创建）

**临时目录**（可清理）：
- `debug_ocr/_tmp/` — 临时截图（自动清理）
- `_cleanup_pending/` — 归档待清理文件，确认无问题后可删除

---

## 8. 依赖环境

```text
主 Python: 3.14.2, 64 位（Playwright + GUI）
32-bit Python: 3.14.4, py -3.14-32（Dm 插件）
Playwright: 1.59.0（Chromium）
Tesseract OCR: 需独立安装
OpenCV: 4.13.0（模板匹配 + 视觉定位）
大漠: 7.2607（仅限 32 位，无绑定前台模式）
```

---

## 9. 文档索引

按阅读顺序：

1. 本文档 — 项目概述
2. [MILESTONE_FRONTEND_SERIAL.md](MILESTONE_FRONTEND_SERIAL.md) — 当前里程碑
3. [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) — 文件结构
4. [RUN_MODE.md](RUN_MODE.md) — 运行模式说明
5. [GUI_STATUS_FLOW.md](GUI_STATUS_FLOW.md) — GUI 状态流转
6. [OCR_SUCCESS.md](OCR_SUCCESS.md) — OCR 方案
7. [CLICK_SOLUTION.md](CLICK_SOLUTION.md) — 点击方案
8. [BUILD.md](BUILD.md) — 打包发布
9. [DEBUG_IMAGE_POLICY.md](DEBUG_IMAGE_POLICY.md) — 截图管理策略
10. [LOG_POLICY.md](LOG_POLICY.md) — 日志策略
11. [CURRENT_ISSUES.md](CURRENT_ISSUES.md) — 当前问题和限制
12. [NEXT_STEPS.md](NEXT_STEPS.md) — 后续方向
13. [KNOWN_BUGS.md](KNOWN_BUGS.md) — 重复踩坑记录
14. [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) — 项目开发规则
15. [DOC_UPDATE_PROMPT.md](DOC_UPDATE_PROMPT.md) — 文档整理通用指令（每次整理文档前必读）
16. [BUILD_RELEASE_PROMPT.md](BUILD_RELEASE_PROMPT.md) — 打包发布通用指令（每次打包前必读）
17. [docs/WINDOW_MANAGER_AND_PASSPORT_MILESTONE.md](docs/WINDOW_MANAGER_AND_PASSPORT_MILESTONE.md) — 窗口管理与通行证阶段总结

---

## 10. 禁止事项

- 不要回退到二维码定位 + 裁剪 OCR 方案
- 不要从浏览器页面 OCR 通行证
- 不要用 Dm 7.2607 BindWindow（全模式崩溃）
- 不要使用 Playwright/CDP/PostMessage/SendMessage 点击 canvas
- 不要开启真并发（前台模式下不支持）
- 文档任务只允许改文档，不要顺手改业务代码
- 打包必须单独确认，不得在普通开发任务中自动打包
- 停止任务不能只设置 `stop_event`，必须同步清理当前账号子进程、`dm_click_helper.py` 和本次 Playwright/Chromium 相关进程
- 禁止误杀所有 `python.exe`，只能清理本项目记录的子进程或命令行明确包含 `dm_click_helper.py` 的进程
