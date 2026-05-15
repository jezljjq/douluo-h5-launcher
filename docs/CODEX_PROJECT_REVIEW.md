# Codex 接手项目分析：斗罗大陆H5上号器

生成时间：2026-05-14

本次任务范围：只读分析项目，禁止修改业务代码、脚本、配置、打包流程和 UI；仅新增本文档。

## 1. 项目路径与仓库

- 本地路径：`D:\Ai\codex\上号器`
- Git 仓库：`https://github.com/jezljjq/douluo-h5-launcher.git`
- 项目开始要求：已执行 `code-review-graph build`
- 技能目录：`D:\Ai\skills`
- 注意：`D:\Ai\skills\code-review-graph\SKILL.md` 不存在，但本机存在 `code-review-graph.exe`，因此已直接执行命令。

`code-review-graph build` 结果：

```text
Full build: 11 files, 227 nodes, 2571 edges (postprocess=full)
FTS indexed: 225 nodes
Flows: 37
Communities: 4
```

## 2. 实际读取的文件

本次重点读取了以下文件：

- `main.py`
- `README.md`
- `CLAUDE.md`
- `PROJECT_STRUCTURE.md`
- `RUN_MODE.md`
- `BUILD.md`
- `CLICK_SOLUTION.md`
- `OCR_SUCCESS.md`
- `DESIGN_METHOD2.md`
- `automation_settings.json`
- `scripts/build_exe.bat`
- `dm_click_helper.py`
- `douluo_launcher/gui.py`
- `douluo_launcher/automation.py`
- `douluo_launcher/config.py`
- `douluo_launcher/dm_client.py`

同时读取了项目根目录文件清单和 `docs/` 状态；`docs/` 原本不存在。

## 3. 目录结构概览

核心目录和文件：

```text
D:\Ai\codex\上号器
├── main.py
├── automation_settings.json
├── dm_click_helper.py
├── scripts/
│   ├── build_exe.bat
│   └── test_qr_decode.py
├── douluo_launcher/
│   ├── __init__.py
│   ├── gui.py
│   ├── automation.py
│   ├── config.py
│   └── dm_client.py
├── debug_ocr/
│   └── template_passport_btn.png
├── tests/
│   ├── test_automation_helpers.py
│   ├── test_config.py
│   └── test_dm_client.py
└── docs/
    └── CODEX_PROJECT_REVIEW.md
```

重要运行产物：

- `logs/run_时间.log`：详细运行日志。
- `debug_ocr/_tmp/`：临时截图。
- `debug_ocr/_error/`：失败现场截图。
- `debug_ocr/browser_pos.json`：运行时浏览器渲染区坐标，供 32 位 Dm 子进程使用。

## 4. 程序入口

程序入口是：

```text
main.py
```

真实入口链路：

```text
main.py
→ douluo_launcher.gui.LauncherApp
→ LauncherApp.mainloop()
```

`main.py` 内容很薄，只创建 `LauncherApp` 并进入 Tkinter 主循环。

## 5. 关键模块定位

### UI

文件：`douluo_launcher/gui.py`

核心类：`LauncherApp`

职责：

- 构建 Tkinter 主界面。
- 提供方式一/方式二切换。
- 读取收藏夹或导入 CSV。
- 管理账号 Treeview、状态、通行证列、耗时列。
- 触发单账号、当前层串行、全部串行。
- 用后台线程执行串行任务。
- 用 `ui_queue` 将 worker 状态安全回到 UI 线程。
- 写运行日志到 `logs/run_时间.log`。

关键函数：

- `_build_widgets()`
- `_load_accounts()`
- `_import_csv()`
- `_run_selected_account()`
- `_run_level_serial()`
- `_run_all_serial()`
- `_start_serial_run()`
- `_serial_worker()`
- `_start_method2_serial()`
- `_drain_ui_queue()`
- `_set_status()`
- `_set_csv_status()`

### OCR 与通行证识别

文件：`douluo_launcher/automation.py`

核心类：`AccountRunner`

关键函数：

- `_extract_passport_from_login_window()`
- `detect_login_page_state()`
- `_quick_login_state()`
- `_ocr_passport_from_text_region()`
- `_ocr_passport_from_login_image()`
- `_ocr_passport_by_template_match()`
- `_crop_passport_hex_region()`
- `_ocr_chars_template_match()`
- `extract_hex_passport()`
- `extract_passport_from_text()`

当前正式路径是登录程序窗口截图后识别通行证，不从浏览器页面 OCR 通行证。

定位登录程序窗口依赖：

- `douluo_launcher.dm_client.select_login_window_by_game_no()`
- 标题匹配规则在 `window_title_matches_game_no()` 中，目前匹配类似 `H5-{窗口号}`。

### 登录程序窗口枚举与截图

文件：`douluo_launcher/dm_client.py`

关键内容：

- `WindowInfo`
- `list_visible_windows()`
- `window_title_matches_game_no()`
- `select_login_window_by_game_no()`
- `capture_window_background()`
- `capture_window_image()`

截图策略：

- 首选 BitBlt 后台截图。
- 对普通窗口可避免被遮挡影响。
- 失败时相关文档提到可回退 ImageGrab，但当前 `capture_window_background()` 内主要是 BitBlt 路径。

### 公告关闭

主要实现位置：`douluo_launcher/automation.py`

方式一当前主流程中，在 `run_game_flow()` 内直接对 canvas 右下角固定坐标点击：

```text
page.mouse.click(740, 680)
```

并执行两次，随后等待 `after_notice_wait_ms`。

历史/备用函数：

- `_close_notice_by_outside_click(page)`
- `_close_notice_with_dm(dm)`

方式二中关闭公告会更多次点击右下角和 canvas 中央。

### DM 点击与输入

主调用位置：`douluo_launcher/automation.py`

关键函数：

- `_write_browser_pos()`
- `_find_game_browser_window()`
- `_capture_browser_client()`
- `_locate_passport_button()`
- `_dm_chain()`
- `_dm_click_viewport()`
- `_dm_type_text()`

32 位 Dm 子进程脚本：

```text
dm_click_helper.py
```

脚本模式：

- `click`：前台移动鼠标并 LeftDown/LeftUp。
- `type`：设置剪贴板后 Dm Ctrl+V。
- `chain`：一次子进程中串起 `click | wait | type | click`，当前主流程使用此模式减少子进程启动开销。

重要限制：

- 不使用 Dm BindWindow。
- 当前是前台点击，会移动真实鼠标。
- 不支持并发、不支持遮挡点击。

### Playwright

主要实现位置：`douluo_launcher/automation.py`

使用方式：

- 在 `run_game_flow()` 和 `run_method2()` 中临时恢复原始 `subprocess.Popen`。
- 导入 `playwright.sync_api.sync_playwright` 后恢复 `_NoConsolePopen`。
- 启动 Chromium，打开游戏链接。

关键逻辑：

```text
_subprocess.Popen = _original_popen
from playwright.sync_api import sync_playwright
_subprocess.Popen = _NoConsolePopen
```

原因：项目全局 monkey-patch `subprocess.Popen` 用于隐藏控制台窗口，必须用 class 继承，且 Playwright 导入前要恢复原始 Popen，避免 asyncio 子类化失败。

### 配置与账号来源

文件：`douluo_launcher/config.py`

核心数据结构：

- `AccountConfig`
- `CSVAccount`
- `AutomationSettings`

关键函数：

- `app_root()`
- `project_root()`
- `compute_game_window_no()`
- `load_accounts_from_bookmarks()`
- `find_default_bookmark_file()`
- `load_settings()`
- `load_csv_accounts()`

窗口号规则：

```text
第一层：收藏 1-8 → 游戏窗口 1-8
第二层：收藏 1-8 → 游戏窗口 9-16
第三层：收藏 1-8 → 游戏窗口 17-24
第四层：收藏 1-8 → 游戏窗口 25-32
```

### 打包脚本

文件：

```text
scripts/build_exe.bat
```

流程：

1. 检测 Python。
2. 检测 PyInstaller。
3. 检测 `py -3.14-32`。
4. 运行单元测试。
5. 清理 `build/` 和 `dist/`。
6. PyInstaller `--onedir --noconsole` 打包。
7. 复制 `automation_settings.json`、`dm_click_helper.py`、`debug_ocr/template_passport_btn.png` 和文档。

注意：本次只读分析，没有执行该脚本，因为它会清理构建目录并生成产物。

## 6. 当前真实上号流程

当前主流程是方式一：收藏夹链接 + 登录程序 OCR 通行证 + 前台串行登录。

从 UI 触发到单账号执行：

```text
LauncherApp 按钮
→ _run_selected_account() / _run_level_serial() / _run_all_serial()
→ _start_serial_run()
→ _serial_worker()
→ AccountRunner.run_game_flow()
```

源码模式与 exe 模式有差异：

- 源码模式：`_serial_worker()` 为每个账号启动 Python 子进程，隔离 Playwright/asyncio 状态。
- exe 模式：`_serial_worker()` 同进程直接创建 `AccountRunner` 调用 `run_game_flow()`。

`run_game_flow()` 当前真实步骤：

1. 清理 `debug_ocr/_tmp/`。
2. 按游戏窗口号定位登录程序窗口。
3. BitBlt 截图登录程序窗口。
4. `detect_login_page_state()` 通过图像特征判断状态：
   - `logged_in`：跳过。
   - `qr_page`：继续 OCR。
   - 当前实现兜底把非 qr_page 视为已登录。
5. 对二维码页底部文字区域 OCR，提取 8 位 hex 通行证。
6. 文字区域 OCR 失败时尝试模板匹配，再回退全图 OCR。
7. 打开 Chromium 游戏页。
8. 等待 canvas 出现。
9. Playwright 点击 canvas 右下角关闭公告。
10. 查找浏览器窗口，写入 `debug_ocr/browser_pos.json`。
11. 截图浏览器渲染区并用模板匹配定位“通行证”按钮，坐标可缓存。
12. 计算输入框和确认按钮坐标。
13. 调用 `dm_click_helper.py chain`：
    - 点击通行证按钮。
    - 等待弹窗。
    - 点击输入框。
    - 粘贴通行证。
    - 点击确认。
14. 回到登录程序窗口做轻量状态轮询。
15. 如果 QR 消失，判定成功。
16. 如果通行证刷新或 QR 仍存在，最多重试 1 次完整流程。
17. 成功关闭浏览器；失败保留现场截图并记录日志。

方式二现状：

- UI 中已存在“账号密码 + 通行证上号”模式。
- CSV 导入已实现。
- `AccountRunner.run_method2()` 已实现账号密码登录后接通行证流程。
- password 只在内存中使用，日志只显示“已填写”。
- 方式二没有层级概念，全部串行执行有效 CSV 账号。

## 7. 稳定模块判断

根据 `README.md`、`CLAUDE.md` 和实现读取，以下模块属于当前稳定区，后续不应顺手改动：

- Tkinter GUI 状态刷新和 `ui_queue` 同步机制。
- 前台串行调度。
- 源码模式子进程隔离流程。
- exe 模式同进程流程。
- OCR 通行证识别入口和多级回退。
- `detect_login_page_state()` 登录程序窗口状态判断。
- `select_login_window_by_game_no()` 标题匹配定位。
- `capture_window_background()` 后台截图。
- 通行证按钮模板匹配。
- Dm 无绑定前台点击。
- `dm_click_helper.py` 32 位子进程点击/输入。
- Playwright 导入前恢复原始 Popen 的规则。
- 日志分流和调试截图生命周期。
- `scripts/build_exe.bat` 打包流程。

## 8. 当前风险与注意点

1. 窗口标题依赖较强。
   - 当前 `window_title_matches_game_no()` 主要依赖 `H5-{编号}`。
   - 如果登录程序窗口标题都变成 `斗罗大陆H5`，当前上号器无法按窗口号稳定定位目标窗口。

2. 当前流程是前台串行。
   - Dm 会移动真实鼠标。
   - 运行中不要操作鼠标。
   - 不支持真并发。

3. 打包脚本会删除 `build/` 和 `dist/`。
   - 本次任务未执行。
   - 后续打包前要先明确允许。

4. `capture_window_background()`、Dm 和 Playwright 都与 Windows 桌面状态强相关。
   - 权限、窗口遮挡、窗口尺寸、Chrome 子窗口句柄都可能影响结果。

5. 方式二虽然代码已经存在，但项目文档中对其状态描述有历史不一致。
   - `README.md` 上方表格说方式二稳定可用。
   - 后续章节仍保留“方式二暂未开发”的旧描述。
   - 本次未修改这些文档，只在本文记录真实代码现状。

## 9. 窗口管理器后续接入建议

窗口管理器最适合先作为“运行前预处理”接入，而不是直接侵入 OCR、DM、Playwright 主流程。

推荐接入点一：GUI 运行前按钮

- 文件：`douluo_launcher/gui.py`
- 位置：配置区或运行区新增按钮。
- 行为：启动/排列登录程序窗口后，再让用户点击现有“单账号运行 / 当前层串行 / 全部串行”。
- 优点：风险最低，不影响当前上号流程。

推荐接入点二：`_start_serial_run()` 前的可选预处理

- 文件：`douluo_launcher/gui.py`
- 函数：`_start_serial_run()`
- 在加载 settings 后、启动 worker 线程前，执行窗口枚举/排列。
- 只适合先做“排列已有窗口”，不建议一开始自动启动游戏程序。

推荐接入点三：登录窗口定位兼容层

- 文件：`douluo_launcher/dm_client.py`
- 函数：`select_login_window_by_game_no()`
- 未来如果窗口标题无编号，可在这里增加坐标排序映射：

```text
枚举所有标题含“斗罗大陆H5”的窗口
过滤 WindowsForms 类名和 320x540 附近尺寸
按 top 分行、按 left 排列
映射为窗口 1-32
返回指定 game_window_no 对应窗口
```

这是与当前窗口管理器最自然的长期融合点，因为 OCR 和状态判断都从这里拿登录程序窗口。

不建议的接入方式：

- 不要把窗口启动/排列逻辑直接塞进 `AccountRunner.run_game_flow()`。
- 不要修改 OCR、公告关闭、DM 链式点击、Playwright 导入规则。
- 不要在 Dm 点击过程中异步移动游戏窗口。
- 不要引入并发启动后立即并发上号。

## 10. 建议的下一步

如果后续要接入窗口管理器，建议分三阶段：

1. 只读兼容：新增窗口枚举诊断按钮，显示当前识别到的 `斗罗大陆H5` 登录窗口、标题、坐标、尺寸、推断窗口号。
2. 独立排列：在 GUI 中增加“排列登录窗口”按钮，仅移动窗口，不启动上号流程。
3. 运行前可选自动排列：在 `_start_serial_run()` 前加可选开关，排列完成后再进入现有串行流程。

每阶段都应单独验证：

- 1 个窗口。
- 8 个窗口。
- 31 个以上窗口。
- 标题带编号。
- 标题不带编号但坐标可排序。

