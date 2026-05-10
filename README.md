# 斗罗大陆H5上号器（前台串行稳定版）

**当前阶段：前台串行批量，已稳定可用。**

---

## 1. 项目定位

自动登录"斗罗大陆H5"游戏，支持最多 32 个账号（4 层 × 8 账号），前台串行逐个完成登录。

### 核心流程

```
登录程序窗口 OCR 提取通行证
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
| 登录程序 OCR | ✅ 稳定 | 全图 OCR + "本次通行证"匹配 + hex 纠错 | [OCR_SUCCESS.md](OCR_SUCCESS.md) |
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

---

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

### 方式一：收藏夹链接 + OCR 通行证

- 从浏览器收藏夹读取游戏入口链接
- 从登录程序窗口 OCR 提取通行证

### 方式二：CSV 配置文件 + OCR 通行证

- 通过 CSV 文件配置账号（`name,url,username,password`）
- 仍然需要先 OCR 通行证，不是只用账号密码
- password 不打印到日志，GUI 仅显示"已填写/未填写"

两种方式最终都走同一完整流程：OCR 通行证 → 打开游戏页 → 关闭公告 → 输入通行证 → 确认登录。

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
- [dm_click_helper.py](dm_click_helper.py) — 32 位 Dm 点击/输入脚本
- [automation_settings.json](automation_settings.json) — 自动化参数

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

---

## 10. 禁止事项

- 不要回退到二维码定位 + 裁剪 OCR 方案
- 不要从浏览器页面 OCR 通行证
- 不要用 Dm 7.2607 BindWindow（全模式崩溃）
- 不要使用 Playwright/CDP/PostMessage/SendMessage 点击 canvas
- 不要开启真并发（前台模式下不支持）
