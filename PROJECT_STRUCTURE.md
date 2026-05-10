# 项目结构说明

**日期：2026-05-09**

---

## 1. 根目录文件

### 入口和配置

- [main.py](main.py) — 程序入口，创建并运行 `LauncherApp`
- [automation_settings.json](automation_settings.json) — 自动化参数（窗口大小、OCR 参数、点击坐标、Dm 参数）
### 工程化

- [scripts/build_exe.bat](scripts/build_exe.bat) — 自动打包脚本（测试→打包→验证）
- [requirements.txt](requirements.txt) — Python 依赖

### 核心业务代码

- [douluo_launcher/automation.py](douluo_launcher/automation.py) — `AccountRunner` 账号运行器
  - `run_game_flow()` — 完整单账号流程（7 步 + 重试）
  - `_extract_passport_from_login_window()` — 后台截图 + OCR 入口
  - `_ocr_passport_from_login_image()` — 全图 OCR 核心（多尺度+灰度）
  - `extract_hex_passport()` — 8 位 hex 提取 + OCR 字符纠错
  - `_capture_browser_client()` — 浏览器渲染区截图
  - `_locate_passport_button()` — 模板匹配定位
  - `_locate_passport_input_center()` — 视觉定位输入框
  - `_locate_confirm_button_center()` — 视觉定位确认按钮
  - `_dm_click_viewport()` / `_dm_type_text()` — Dm 子进程调用
  - `_tmp_path()` / `_clean_tmp()` / `_save_error_snapshots()` — 截图生命周期管理
  - 废弃方法（保留代码但不调用）：`_locate_qr_box()` 等二维码相关函数

- [douluo_launcher/config.py](douluo_launcher/config.py) — 配置和收藏夹读取
  - `load_settings()` / `load_accounts_from_bookmarks()`
  - 层级名称解析、游戏窗口号计算（收藏编号 + 偏移量）

- [douluo_launcher/gui.py](douluo_launcher/gui.py) — Tkinter GUI
  - `LauncherApp` — 主窗口，Treeview 账号表
  - `_serial_worker()` — Popen 子进程隔离，实时状态解析
  - `_queue_log()` / `_queue_status()` / `_queue_passport()` — 线程安全 UI 更新
  - `_set_status()` — 状态列 + 颜色标签更新
  - 按钮：单账号运行 / 当前层串行 / 全部串行 / 停止任务

- [douluo_launcher/dm_client.py](douluo_launcher/dm_client.py) — 窗口管理和截图
  - `select_login_window_by_game_no()` — 按游戏窗口号定位登录程序窗口
  - `capture_window_background()` — BitBlt 后台截图 + ImageGrab 回退
  - `WindowInfo` — 窗口信息 dataclass

- [dm_click_helper.py](dm_click_helper.py) — 32 位 Python Dm 点击/输入脚本
  - `click` 模式：MoveTo + LeftDown + 保持 + LeftUp
  - `type` 模式：clip.exe 剪贴板 + Dm Ctrl+V

### Dm 环境

- [test_dm_32bit.bat](test_dm_32bit.bat) — 32 位 Python 大漠环境测试脚本
- [verify_background_capture.py](verify_background_capture.py) — 后台截图遮挡验证

---

## 2. 调试目录

- [debug_ocr/](debug_ocr/) — 调试截图输出目录
  - `_tmp/` — 临时截图（自动清理）
  - `history/error_*/` — 失败现场保留
  - `template_passport_btn.png` — 按钮模板（永久）
  - `browser_pos.json` — 浏览器坐标缓存（永久）
  - `latest_ocr_success.png` — 最新 OCR 成功截图
  - 详见 [DEBUG_IMAGE_POLICY.md](DEBUG_IMAGE_POLICY.md)

---

## 3. 测试

- [tests/test_config.py](tests/test_config.py) — 收藏夹映射、设置读取
- [tests/test_automation_helpers.py](tests/test_automation_helpers.py) — 通行证文本提取、hex 纠错
- [tests/test_dm_client.py](tests/test_dm_client.py) — 窗口标题匹配

---

## 4. 文档

| 文档 | 说明 |
|------|------|
| [README.md](README.md) | 项目概述 |
| [MILESTONE_FRONTEND_SERIAL.md](MILESTONE_FRONTEND_SERIAL.md) | 当前里程碑 |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | 本文档 |
| [RUN_MODE.md](RUN_MODE.md) | 运行模式说明 |
| [GUI_STATUS_FLOW.md](GUI_STATUS_FLOW.md) | GUI 状态流转 |
| [OCR_SUCCESS.md](OCR_SUCCESS.md) | OCR 方案 |
| [CLICK_SOLUTION.md](CLICK_SOLUTION.md) | 点击方案 |
| [BUILD.md](BUILD.md) | 打包发布说明 |
| [DEBUG_IMAGE_POLICY.md](DEBUG_IMAGE_POLICY.md) | 截图管理策略 |
| [LOG_POLICY.md](LOG_POLICY.md) | 日志策略 |
| [CURRENT_ISSUES.md](CURRENT_ISSUES.md) | 当前问题和限制 |
| [NEXT_STEPS.md](NEXT_STEPS.md) | 后续方向 |
| [KNOWN_BUGS.md](KNOWN_BUGS.md) | 重复踩坑记录 |
| [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) | 项目开发规则 |
| [DOC_UPDATE_PROMPT.md](DOC_UPDATE_PROMPT.md) | 文档整理通用指令 |
