# 窗口管理器合并实施方案

生成时间：2026-05-14

本方案仅基于以下两份接手文档生成：

- `D:\Ai\codex\上号器\docs\CODEX_PROJECT_REVIEW.md`
- `D:\Ai\codex\DLH5WindowManager\docs\CODEX_WINDOW_MANAGER_REVIEW.md`

本次不写代码、不迁入代码、不修改 UI、不修改 OCR/DM/Playwright/通行证/公告关闭/输入确认/校验逻辑。

## 1. 当前两个项目现状

### 上号器现状

项目路径：

```text
D:\Ai\codex\上号器
```

程序入口：

```text
main.py
→ douluo_launcher.gui.LauncherApp
→ LauncherApp.mainloop()
```

核心主流程是方式一：收藏夹链接 + 登录程序窗口 OCR 通行证 + Playwright 打开游戏页 + 公告关闭 + Dm 前台点击通行证按钮 + 剪贴板粘贴输入通行证 + Dm 点击确认 + 回到登录程序窗口校验 QR 是否消失。

真实调用链：

```text
LauncherApp 按钮
→ _run_selected_account() / _run_level_serial() / _run_all_serial()
→ _start_serial_run()
→ _serial_worker()
→ AccountRunner.run_game_flow()
```

稳定模块：

- `douluo_launcher/gui.py` 中的 Tkinter UI 状态刷新和 `ui_queue` 同步。
- 前台串行调度。
- 源码模式子进程隔离流程。
- exe 模式同进程流程。
- `douluo_launcher/automation.py` 中的 OCR 通行证识别链路。
- `detect_login_page_state()` 登录程序窗口状态判断。
- `douluo_launcher/dm_client.py::select_login_window_by_game_no()` 当前标题编号匹配。
- `capture_window_background()` 后台截图。
- 通行证按钮模板匹配。
- Dm 无绑定前台点击和 `dm_click_helper.py`。
- Playwright 导入前恢复原始 `Popen` 的规则。
- 日志和 `debug_ocr` 截图生命周期。
- `scripts/build_exe.bat` 打包流程。

### 窗口管理器现状

项目路径：

```text
D:\Ai\codex\DLH5WindowManager
```

程序入口：

```text
app.py
→ ensure_admin_on_startup()
→ WindowManagerApp().mainloop()
```

核心模块：

```text
window_manager.py
```

核心能力：

- Windows API 枚举标题包含 `斗罗大陆H5` 的可见窗口。
- 从标题提取数字编号。
- 按数字编号排序。
- 计算平铺坐标。
- 使用 `SetWindowPos` 设置窗口位置和大小。
- 使用 `SetWindowTextW` 修改窗口标题。
- 使用 `SendMessageTimeoutW(WM_CLOSE)` 批量关闭窗口。

可迁入代码：

- `window_manager.py` 中无 Tkinter、无 Playwright、无 OCR、无 Dm 依赖的 Windows API 代码。

不适合迁入代码：

- `app.py` 独立 Tkinter UI。
- `WindowManagerApp`。
- 独立 `mainloop`。
- `settings.json` 配置体系。
- 自动管理员启动逻辑。
- PyInstaller spec 和独立 exe 打包方案。

## 2. 合并原则

1. 只迁入窗口管理器 `window_manager.py` 中的无 UI Windows API 代码。
2. 不迁入窗口管理器 `app.py`。
3. 不把窗口管理器 `mainloop` 合并进上号器。
4. 不强行拼接两个 Tkinter UI。
5. 不迁入窗口管理器 `settings.json` 配置体系。
6. 不默认迁入自动管理员启动逻辑。
7. 不默认重命名游戏窗口标题。
8. 不修改上号器稳定模块：
   - OCR。
   - Dm 点击。
   - Playwright。
   - 通行证识别。
   - 公告关闭。
   - 输入确认。
   - 登录校验。
   - 打包脚本。
9. 合并后的窗口管理能力必须作为 `window_manager` 独立模块存在。
10. 第一阶段只做模块迁入和测试，不接入自动上号流程。

## 3. 目标目录设计

建议新增文件：

```text
D:\Ai\codex\上号器\douluo_launcher\window_manager.py
```

模块边界：

```text
douluo_launcher/window_manager.py
```

只负责：

- 登录程序窗口枚举。
- 编号提取。
- 数字排序。
- 坐标计算。
- 窗口移动和尺寸设置。
- 窗口标题修改。
- 窗口关闭。

不负责：

- Tkinter UI。
- 上号流程。
- OCR。
- Playwright。
- Dm 点击。
- 通行证输入。
- 公告关闭。
- 登录校验。
- 打包。

## 4. 第一阶段合并内容

第一阶段只新增独立模块，不接入 UI，不接入上号流程。

迁入数据结构：

- `GameWindow`
- `TileConfig`
- `TileResult`
- `CloseResult`
- `RenameResult`

迁入函数：

- `extract_window_number()`
- `sort_game_windows()`
- `calculate_tile_position()`
- `list_game_windows()`
- `tile_game_windows()`
- `rename_game_windows()`
- `close_game_windows()`

第一阶段建议同时迁入必要常量：

- `GAME_TITLE_KEYWORD`
- `SWP_NOZORDER`
- `SWP_NOACTIVATE`
- `WM_CLOSE`
- `SMTO_ABORTIFHUNG`

第一阶段模块要求：

- 不依赖 `app.py`。
- 不依赖 Tkinter。
- 不读写 `settings.json`。
- 不自动请求管理员权限。
- 不自动重命名窗口。
- 所有函数返回结构化结果，调用方自行记录日志。

## 5. 第一阶段不做内容

第一阶段明确不做：

- 不接入自动上号。
- 不修改 `AccountRunner.run_game_flow()`。
- 不修改 OCR。
- 不修改 Dm 点击。
- 不修改 Playwright。
- 不修改公告关闭。
- 不修改输入确认。
- 不修改登录校验。
- 不修改打包脚本。
- 不修改 `.bat`。
- 不修改 `.json`。
- 不默认重命名窗口标题。
- 不默认管理员重启。
- 不新增窗口管理 UI。
- 不新增运行前自动排列。
- 不改 `select_login_window_by_game_no()`。

## 6. 第二阶段 UI 接入方案

第二阶段才考虑在 `douluo_launcher/gui.py` 中增加窗口管理区域；本阶段只规划，不写代码。

建议新增区域：

```text
窗口管理
```

建议按钮：

- `识别登录窗口`
- `排列登录窗口`
- `关闭登录窗口`

### 识别登录窗口

行为：

1. 调用 `window_manager.list_game_windows()`。
2. 显示识别到的窗口数量。
3. 在 GUI 日志中列出：
   - hwnd
   - title
   - number

边界：

- 只读，不移动窗口。
- 不修改标题。
- 不进入上号流程。

### 排列登录窗口

行为：

1. 使用默认或配置中的 `TileConfig`。
2. 调用 `window_manager.tile_game_windows()`。
3. GUI 日志记录每个窗口的目标坐标和结果。

边界：

- 只移动标题包含 `斗罗大陆H5` 的登录窗口。
- 不启动游戏程序。
- 不改标题。
- 不触发 OCR/DM/Playwright。

### 关闭登录窗口

行为：

1. 调用 `window_manager.close_game_windows()`。
2. 使用 `WM_CLOSE` 正常关闭窗口。
3. GUI 日志记录每个窗口关闭消息是否发送成功。

边界：

- 不强杀进程。
- 不删除文件。
- 不影响浏览器窗口。

## 7. 第三阶段定位兼容方案

第三阶段增强：

```text
douluo_launcher/dm_client.py
select_login_window_by_game_no()
```

原则：

1. 优先保留现有 `H5-{编号}` 标题匹配。
2. 只有现有标题编号匹配失败时，才启用窗口管理器枚举兼容策略。
3. 兼容策略必须增加过滤，不直接相信 `hwnd` 顺序。
4. 最终按坐标映射窗口 1-32。

建议兼容流程：

```text
select_login_window_by_game_no(game_window_no)
├─ 1. 保持现有 window_title_matches_game_no() 匹配
│    └─ 成功：直接返回
├─ 2. 失败后枚举标题包含“斗罗大陆H5”的可见窗口
├─ 3. 过滤窗口类名
│    └─ 优先 WindowsForms10.Window.8.app.*
├─ 4. 过滤窗口尺寸
│    └─ 接近 320x540 或可配置容差
├─ 5. 按坐标分行
│    └─ top 接近的归为同一行
├─ 6. 每行按 left 从小到大排序
├─ 7. 映射窗口号
│    └─ 第一行 1-8，第二行 9-16，第三行 17-24，第四行 25-32
└─ 8. 返回 game_window_no 对应窗口
```

为什么不能只用窗口管理器当前排序：

- 当前窗口管理器无编号时会退化为标题 + hwnd 排序。
- hwnd 顺序不稳定。
- 上号器需要严格按游戏窗口号找到对应登录程序窗口。

第三阶段必须补充的能力：

- 类名过滤。
- 尺寸过滤。
- 坐标排序。
- 行列映射。
- 兼容失败时详细日志。

## 8. 风险清单

### UI 冲突

风险：窗口管理器 `app.py` 是独立 Tkinter 应用，直接合并会和上号器 `LauncherApp` 冲突。

控制：不迁入 `app.py`，只在上号器现有 UI 中规划独立按钮。

### 配置冲突

风险：窗口管理器使用 `settings.json`，上号器使用 `automation_settings.json`。

控制：第一阶段不迁配置；后续如需配置，优先扩展上号器现有配置或设计独立但明确的窗口管理配置。

### 日志冲突

风险：窗口管理器自带 Tkinter 日志区，上号器已有 GUI 日志和文件日志。

控制：迁入模块不直接写 GUI；只返回结果，由上号器调用方写日志。

### 管理员权限冲突

风险：窗口管理器自动管理员启动可能改变上号器运行权限，影响 Playwright、Dm、路径和打包行为。

控制：第一阶段不迁入自动管理员启动；遇到 `错误码 5` 时只提示权限不足。

### 标题重命名风险

风险：默认重命名窗口标题可能影响上号器现有标题匹配、用户外部工具或登录程序自身逻辑。

控制：不默认重命名。后续只作为手动按钮或明确勾选项。

### hwnd 顺序不稳定风险

风险：无编号窗口如果按 hwnd 排序，可能导致窗口号映射错误。

控制：第三阶段必须使用 top/left 坐标映射，不依赖 hwnd 排序。

### Playwright/DM/OCR 被误改风险

风险：把窗口启动/排列塞进 `run_game_flow()` 会扩大失败面。

控制：不修改 `automation.py` 主流程；窗口管理只作为运行前独立步骤或定位兼容层。

### 打包依赖风险

风险：新增模块后打包脚本可能需要 hidden import 或资源处理，但过早修改打包脚本会引入新风险。

控制：第一阶段先源码测试导入；打包脚本改动另开任务，且必须先读 `BUILD_RELEASE_PROMPT.md`。

## 9. 测试计划

### 第一阶段：模块迁入后

只导入模块测试：

```powershell
python -m py_compile douluo_launcher/window_manager.py
python - <<'PY'
from douluo_launcher import window_manager
print(window_manager.GAME_TITLE_KEYWORD)
PY
```

纯函数测试：

- `extract_window_number("斗罗大陆H5-1号甲战区") == 1`
- `extract_window_number("斗罗大陆H5-31号甲战区") == 31`
- `extract_window_number("斗罗大陆H5") is None`
- `sort_game_windows()` 验证 `1、2、10、11`
- `calculate_tile_position()` 验证 31+ 坐标。

枚举窗口测试：

- 手动打开 1 个登录窗口。
- 调用 `list_game_windows()`。
- 确认识别标题、hwnd、number。

排列窗口测试：

- 打开 3 个窗口。
- 使用 `TileConfig(width=320, height=540, ...)`。
- 调用 `tile_game_windows()`。
- 确认窗口位置和大小。

关闭窗口测试：

- 打开 1-3 个测试窗口。
- 调用 `close_game_windows()`。
- 确认只发送正常关闭消息，不强杀。

### 第二阶段：UI 接入后

识别按钮测试：

- 点击“识别登录窗口”。
- GUI 日志显示窗口数量和 hwnd/title/number。
- 不改变窗口状态。

排列按钮测试：

- 点击“排列登录窗口”。
- GUI 日志显示每个窗口坐标和结果。
- 不触发上号流程。

关闭按钮测试：

- 点击“关闭登录窗口”。
- GUI 日志显示关闭结果。
- 无响应窗口只记录失败。

### 第三阶段：定位兼容后

标题编号回归：

- 窗口标题为 `斗罗大陆H5-1-...`。
- 确认仍走原有标题匹配。

无编号标题测试：

- 多窗口标题均为 `斗罗大陆H5`。
- 通过类名、尺寸、坐标排序映射窗口 1-32。

31 窗口排列测试：

- 打开 31 个以上窗口。
- 排列窗口。
- 验证第 31/32 个窗口坐标正确。

原上号器回归：

- 单账号运行。
- 当前层串行。
- 全部串行前至少抽样验证。
- 方式二 CSV 单账号和全部串行如当前仍在使用，也需要抽样回归。

稳定模块回归重点：

- OCR 能识别通行证。
- Dm 链式点击正常。
- Playwright 能打开页面。
- 公告关闭仍有效。
- 登录校验仍按 QR 消失判断。

## 10. 回滚方案

第一阶段回滚：

```text
删除 douluo_launcher/window_manager.py
删除对应测试文件（如果新增）
```

第二阶段回滚：

```text
移除 gui.py 中新增窗口管理区域
移除“识别登录窗口 / 排列登录窗口 / 关闭登录窗口”按钮和回调
```

第三阶段回滚：

```text
恢复 dm_client.py 中 select_login_window_by_game_no()
恢复 window_title_matches_game_no() 原行为
移除坐标映射兼容逻辑
```

关键保证：

- 不影响 `automation.py`。
- 不影响 `AccountRunner.run_game_flow()`。
- 不影响 OCR、DM、Playwright、通行证、公告关闭、输入确认、校验逻辑。
- 不影响打包脚本。

## 11. 推荐执行顺序

建议下一步只开始第一阶段代码迁入：

1. 新增 `douluo_launcher/window_manager.py`。
2. 只迁入无 UI Windows API 代码。
3. 新增或更新测试，只测纯函数和模块导入。
4. 不改 GUI。
5. 不改 `dm_client.py`。
6. 不改 `automation.py`。

第一阶段完成并通过测试后，再进入第二阶段 UI 接入规划实现。

