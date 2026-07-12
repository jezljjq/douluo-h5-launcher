# Agent Status

Status: v1.4.20-formal-exe-built-and-source-pushed-awaiting-user-live-validation
Version: 1.4.20
Updated: 2026-07-12

## v1.4.20 Final Packaged Migration Fix And Formal Rebuild

### 修改文件

- `douluo_launcher/config.py`、`direct_link_refresh.py`、`direct_link_login.py`
- `tests/test_config.py`、`test_direct_link_refresh.py`、`test_direct_link_login.py`、`test_refresh_client_direct_links_http_mode.py`
- 保留并验证 `douluo_launcher/gui.py` 既有快捷键弹窗居中修复及对应 GUI 测试
- `README.md`、`BUILD.md`、实机记录、`.ai-bridge/current-plan.md`、`agent-status.md`、`execution-log.jsonl`

### 结果

- frozen 根目录不再上溯开发仓库；cwd、父目录和仓库数据不再进入迁移候选。发布内部兼容位置、当前用户旧 APPDATA 和显式覆盖保持可用，逐文件 resolve 越界会跳过。
- 源码模式项目内 `上号器数据` 行为保持；冻结态缺 HAR 时在 Playwright 前停止。
- Focused 迁移/HAR/GUI/发布测试通过；full `591 run, 572 passed, 19 skipped, 0 failed`。构建脚本内部完整测试再次通过。
- `py_compile`、`compileall`、`git diff --check`、32 位源码启动 6 秒、TIMER 与两份保护备份哈希核对通过。
- `scripts\build_exe.bat` 最终正式重构建成功。EXE `9,275,918` bytes，SHA-256 `048345665E198BA9E694D5A6D29A63A9DB12327C6367990A162E3B306349B2CB`；旧阻塞构建已废弃。
- 发布目录 1,916 文件/732,038,521 bytes；Chromium 仅 `chromium-1217`；dm helper 为 32 位；禁入项及敏感文本扫描 0。
- 仓库内和仓库外两套隔离 EXE 均存活 12 秒、标题正确、临时 APPDATA 无真实账号/链接/canary、发布目录零新增。

### 待用户实机

- 正式 EXE 下刷新地址、账号管理、多倍率快捷键弹窗和快捷键真实注册触发。
- 正式 EXE 下真实收藏夹同步（不得在自动烟雾中写真实 Bookmarks）。
- 正式 EXE 下 9/31 窗、HWND/PID/CDP 归属及加速器流程。
- 自动化和 EXE 烟雾通过不等于 `release-validated`。

## v1.4.20 Dev Data Migration Fix Authorized

- 用户已明确授权只修复打包态开发数据迁移越界问题，并重新打包、重新执行发布安全检查；版本保持 v1.4.20。
- 授权范围限定为 `config.py` / `direct_link_refresh.py` 及其测试、发布文档和 bridge 状态，不得借机修改 9/31 窗、收藏夹整批写入、账号参与、快捷键或加速器核心逻辑。
- 打包态不得通过 `project_root()`、当前工作目录或开发仓库路径探测并迁移真实 `上号器数据`。源码模式现有项目内数据读取行为可继续保留。
- 允许的打包态迁移源只能来自 EXE 自身发布目录内明确允许的旧版兼容位置，或用户明确指定的数据目录；默认不得扫描 EXE 目录之外的仓库、cwd、父目录或兄弟目录。
- ChatGPT/CodexPro 不能启动 Codex；当前等待用户手动启动 Codex。
- 用户补充确认：`多倍率快捷键设置` 弹窗当前会落到屏幕左上角，未相对主窗口居中。本轮同时允许只修复该弹窗定位：相对主窗口居中、按父窗口所在显示器工作区夹取，保持现有模态关系、4 行配置、注册/保存/回滚逻辑不变。
- ChatGPT 已直接完成该 UI 源码修复：弹窗创建后先 `withdraw()`，控件完成后复用 `_position_dialog_relative_to_owner(dialog, self)`，随后 `deiconify/lift/focus/grab_set`；并补充源码顺序断言。用户已完成源码实机确认，弹窗定位正常。
- 用户现已明确授权 Codex 完成打包态数据迁移安全修复、更新发布文档、运行全部验证、重新正式打包，并在发布安全检查通过后提交和推送 Git。Git 提交必须排除真实账号、直登链接、用户配置、Bookmarks、备份、日志、CSV、运行缓存、dist/build 产物及其它私有数据。

## v1.4.20 Formal EXE Built - Release Check Blocked

- 已修正动态版本发布目录、spec 隔离和文档旧 v1.3.0；未修改业务逻辑，未升版本。
- `scripts\build_exe.bat` 最终构建退出码 0。发布 focused 7 项通过；完整测试 584 项，567 通过、17 预期跳过、0 失败；编译与 diff 检查通过。
- EXE：`dist/斗罗大陆H5上号器-v1.4.20/上号器.exe`，9,274,931 bytes，SHA-256 `7E9CFE70C3F8F8C3673AD496EBBB2D2CEE39E32CB9D3DC7A33587D361308984A`。发布目录 1,916 文件，732,037,240 bytes。
- `chromium-1217` 仅 1 份，`chrome.exe` 存在；`dm_click_helper.exe` 存在且为 32-bit。禁止文件 0，绝对路径/敏感文本 0；PyInstaller 归档中 `requests` 命中 18 项。
- EXE 在临时 `%APPDATA%` 下运行 12 秒，标题为 `斗罗大陆H5上号器 - 客户端直登批次版 v1.4.20`，发布目录无新运行时文件。
- 阻塞：打包态 `project_root()` 回溯到开发仓库，`legacy_refresh_data_dirs()` 因此读取仓库 `上号器数据`，并把真实账号/链接复制到本次临时 APPDATA。发布包本身未携带这些数据，原数据未修改。
- 修复需要修改 `config.py/direct_link_refresh.py` 打包态业务迁移逻辑；根据本轮授权已停止。未执行 EXE 弹窗、9/31 窗、真实收藏夹或快捷键验收，不得标记为发布验证通过。
- TIMER 长度 23657、SHA-256 `0c65cbbd7eddd969225668f740a7b16ada1ff17f281b3c3b9efb6620ddc544a5`。两份受保护 Bookmarks 备份哈希前后不变。

## v1.4.20 Formal EXE Packaging Authorized

- 用户已明确授权开始正式 EXE 打包与 EXE 最终回归。
- ChatGPT/CodexPro 不能实际启动 Codex；当前等待用户手动启动 Codex。
- 打包前必须先修正 `scripts/build_exe.ps1` 和 `BUILD.md` 中仍硬编码的 `v1.3.0` 发布目录/说明，使其与 `APP_VERSION=1.4.20` 同步或改为动态读取版本。
- 只允许使用 `scripts/build_exe.bat` 作为正式入口，不临时拼接 PyInstaller 命令。
- 发布包不得包含真实账号、密码、直登链接、用户配置、Bookmarks、备份、日志、CSV、运行缓存或其它开发机私有数据。
- 完成打包后必须执行 EXE 启动、版本标题、配置目录、依赖、收藏夹默认不写、现有链接同步入口和基础 9/31 窗回归；结果未验证前不得声称正式发布完成。

## v1.4.20 Source Completed - Stable Bookmark Root Identity

### 修改文件

- `douluo_launcher/config.py`、`direct_link_refresh.py`、`gui.py`、`version.py`
- `automation_settings.template.json`、`README.md`
- `tests/test_bookmark_writeback.py`、`test_gui_refresh_address.py`、`test_config.py`、`test_release_packaging.py`
- `docs/上号器_v1.4.16_实机测试记录_20260712.md`、`.ai-bridge/current-plan.md`、`.ai-bridge/agent-status.md`

### 实施结果

- 根目录优先使用持久化 GUID 在全树中唯一查找；无 GUID 时按名称唯一迁移；旧 `children/N` 不再生成伪绑定。
- 成功恢复或创建后持久化 `bookmark_root_guid/name/path/parent_path`。根不存在时，只有父节点明确且用户确认才在同一事务创建。
- 新增“同步现有链接到收藏夹”：读取账号库和 `direct_links.enc.json`，不调用 HTTP capturer、Playwright，不重新生成 token 或修改密码。
- 整批单次读取、备份、临时写入、哈希检查、原子替换和复读验证保持；账号收藏项 GUID 映射继续生效。

### 验证

- Focused：收藏夹 22、刷新 GUI 19、直登存储 25、CLI/回退 10、配置 23、发布断言 5，共 104 项，全部通过。
- Full：`582 run, 565 passed, 17 skipped, 0 failed`。
- `py_compile`、`compileall`、`git diff --check` 通过；32 位源码启动 6 秒仍存活。
- `TIMER_HOOK_SCRIPT` 长度 `23657`，SHA-256 `0c65cbbd7eddd969225668f740a7b16ada1ff17f281b3c3b9efb6620ddc544a5`，未变。
- 两份受保护备份前后哈希不变；所有收藏夹测试使用临时 Bookmarks，未写用户真实 Bookmarks；未打包 EXE。

### 收藏夹实机结果

- 用户已完成真实 Edge 实机验证，现有本地链接首次同步与第二次同步均正常。
- 首次同步完成新增，第二次同步命中已有收藏项更新；Edge 重启后未出现整套重复。
- “同步现有链接到收藏夹”未重新执行 HTTP 登录，也未启动 Playwright。
- 本轮收藏夹根身份、整批写入和重复防护可判定为实机通过。

### 其余实机结果

- 刷新地址弹窗布局正常；勾选“刷新成功后同步/导入收藏夹”后才写收藏夹，当前 UI 不构成阻塞。
- 9 窗准备、排列、登录以及多倍率快捷键往返实机正常。
- 31 窗准备、排列和登录正常；使用“关闭本批客户端”关闭全部 31 个窗口后，再执行“修复本批窗口”能够正常补开并恢复。
- Reload/Back/Forward/BFCache 后自动恢复加速面板已明确取消，不再作为验收项。

### 剩余事项

- 当前源码实机验收已完成，等待用户决定是否进入正式 EXE 打包与 EXE 最终回归。

## v1.4.19 Documentation Ready

## v1.4.19 Source Completed

### 修改文件

- `douluo_launcher/direct_link_refresh.py`、`direct_link_login.py`、`client_login_accounts.py`、`gui.py`、`version.py`
- `tools/refresh_client_direct_links.py`、`tools/inspect_bookmarks.py`
- `tests/test_bookmark_writeback.py`、`test_client_login_accounts.py`、`test_gui_refresh_address.py`、`test_refresh_client_direct_links_http_mode.py`、`test_inspect_bookmarks.py`、`test_release_packaging.py`
- `README.md`、`docs/上号器_v1.4.16_实机测试记录_20260712.md`、`.ai-bridge/current-plan.md`、`.ai-bridge/agent-status.md`

### 实施结果

- 收藏夹默认不写；勾选同步/导入后，先刷新全部账号，再生成整批更新/新增/冲突/跳过计划并且最多替换一次。
- 已有节点仅改 URL；缺失节点按完整路径新增；稳定 GUID 映射缺失、根身份漂移、重复路径或外部哈希变化时整批不写。
- 缺 `requests` 在 worker 启动前停止；HTTP 失败只在用户明确确认后回退 Playwright。
- 账号暂时消失不再删状态；无历史状态默认参与；旧 `seen_keys` 不再影响默认值。表格已多选，支持选中与当前筛选批量加入/移出，一次批量仅保存一次。
- `tools/inspect_bookmarks.py` 默认只读预览；恢复要求 `--confirm` 并先备份当前文件；不自动去重。

### 验证

- Focused：收藏夹 17、账号参与 6、刷新 GUI 18、CLI/回退 10、检查/恢复 2，全部通过。
- Full：`python -m unittest discover -s tests -v` -> `576 run, 559 passed, 17 skipped, 0 failed`。
- `py_compile`、`python -m compileall -q main.py douluo_launcher tests tools`、`git diff --check` 通过；仅有已有 CRLF 警告。
- 32 位项目解释器源码启动：`D:\Dev\Python\Python314-32\python.exe main.py` 启动 6 秒仍存活，随后仅停止诊断进程。
- `TIMER_HOOK_SCRIPT`：长度 `23657`，SHA-256 `0c65cbbd7eddd969225668f740a7b16ada1ff17f281b3c3b9efb6620ddc544a5`，未变。
- 两份受保护备份哈希未变；未写真实 Bookmarks，未打包 EXE。

### 待实机

- Edge 关闭/同步状态下的 49 账号“已有+新增”单次写回、重启后不复制、第二次刷新命中原 GUID。
- 真实缺 `requests` 提示不弹浏览器，真实 HTTP 失败的确认/取消回退。
- 真实 49 账号首次全参与、多选/筛选批量操作和重启后状态恢复。
- 9/31 窗与 X5Game 回归未本轮重测；自动化通过不等于实机通过。

## v1.4.18 Live Blocker - Edge Bookmark Duplication

- 32 位源码刷新时因缺少 `requests` 自动回退 Playwright，用户中途停止；随后 64 位源码纯 HTTP 全量刷新成功。
- 64 位本轮日志中每个账号只执行一次刷新和一次 `bookmark_success`，但 Edge 收藏夹出现大量成对重复，连本轮未处理的旧数字收藏项 `1/2/3/...` 也重复。
- 本轮自动备份 `Bookmarks_Edge_Default_20260712_172302_602736.json` 在写入前仍只有一份命名账号；旧数字项带 `source=sync`。因此当前证据不支持“刷新循环执行了两遍”。
- 用户确认以前版本执行同类刷新未发生重复，因此应优先按近期收藏夹写回回归调查：当前版本新增了路径未命中时自动创建节点，同时仍按账号逐次完整替换 `Bookmarks`；Edge 同步/`Bookmarks.bak` 恢复可能是放大因素，但不能作为唯一归因。继续排查结构路径 `roots/bookmark_bar/children/N` 漂移、自动创建和逐账号整文件写回的组合风险。
- 当前禁止继续“刷新全部”和直接写真实 Bookmarks；保留 17:12、17:23 两份自动备份，不自动猜测删除重复项。
- 安全修复方向：批量开始前依赖/同步预检；缺依赖不自动回退浏览器；整批一次原子写入；根目录 GUID+名称+结构联合校验；写入前后严格唯一性验证；同步状态未知时仅刷新本地直登链接。
- 当前只做分析和文档登记，未授权 Codex 修改业务代码；v1.4.18 不得打包正式 EXE。

## v1.4.18 Source Startup Regression Fixed

- 症状：存在旧 `speed_panel_hotkey` 时，`LauncherApp.__init__()` 在 `_build_widgets()` 之前执行 `_apply_settings_defaults()`；迁移提示直接调用 `_log()`，但 `log_text` 尚未创建，导致源码模式以 `AttributeError` 退出。
- 根因修复：新增 `_log_or_defer_startup()`。启动控件尚未创建时把提示写入既有 `_user_data_startup_logs` 缓冲；日志控件存在后仍正常调用 `_log()`。无效多倍率配置提示与旧单快捷键迁移提示统一使用该安全入口。
- 新增 2 项回归测试，覆盖日志控件创建前缓存、创建后直接输出。
- `python -m py_compile douluo_launcher/gui.py`：通过。
- `python -m unittest discover -s tests -p "test_gui_group_settings.py" -v`：149 项，132 通过、17 项预期跳过、0 失败。
- 32 位源码启动现场验证：`py -3.14-32 main.py` 启动 5 秒后仍存活，未再在构造阶段退出；随后只停止本次诊断进程。
- 完整测试 `python -m unittest discover -s tests`：569 项，552 通过、17 项预期跳过、0 失败。
- 未打包正式 EXE。

## v1.4.18 Multi-rate Hotkey Source Completed

### 修改文件

- `douluo_launcher/client_speed_hotkey.py`：多 hotkey ID、单消息线程、整套原子替换与回滚。
- `douluo_launcher/gui.py`：删除旧快捷键整行，增加入口按钮和四行模态弹窗，接入真实 `speed_rate` 判断。
- `douluo_launcher/config.py`、`automation_settings.template.json`：新增结构化 `speed_rate_hotkeys`，旧 `speed_panel_hotkey` 保留为空但不再注册。
- `douluo_launcher/version.py`、`README.md`、`tests/test_client_speed_hotkey.py`、`tests/test_gui_group_settings.py`、`tests/test_config.py`、`tests/test_release_packaging.py` 及本实机记录同步到 v1.4.18。

### 注册架构与原子回滚

- 一个 `WindowsSpeedHotkey` 管理器只创建一个守护消息线程和一个 `GetMessageW` 循环；四组组合使用从 `0x5348` 起的稳定 hotkey ID，回调直接携带对应倍率。重复保存复用同一线程，不创建四个线程，不轮询键盘。
- 替换时先标准化四行、校验正倍率、非空主键和内部重复组合。消息线程注销旧映射后尝试注册整套新映射；任一项失败时注销本次已成功的新项并重新注册旧映射，错误包含具体组合和 Windows 1409。只有整套注册成功后 GUI 才保存配置。
- 若注册成功但磁盘保存失败，GUI 再调用整套替换恢复旧配置，弹窗保持打开，不更新内存配置。

### 倍率切换规则

- 快捷键从加速总控当前唯一作用范围读取 bindings；只有目标集合非空且所有 binding 的真实 `speed_rate` 都等于该行倍率时才恢复 `1.0`，否则统一应用该行倍率。因此支持 `1→3→6→1`、`6→3→1`、混合倍率统一以及切换作用范围后的正确判断，不使用旧全局布尔状态。
- 实际应用继续调用现有 `run_speed_control_batch` 和逐 binding 所有权校验；非阻塞锁继续阻止快速按键叠加批量任务。

### 测试命令与真实结果

- `python -m py_compile douluo_launcher/client_speed_hotkey.py douluo_launcher/gui.py douluo_launcher/config.py douluo_launcher/version.py`：通过。
- `python -m compileall -q douluo_launcher tools`：通过。
- Focused tests：多快捷键 9、加速总控 8、GUI 邻近回归 147（17 项旧功能预期跳过）、配置 23、发布断言 5，0 失败。
- `python -m unittest discover -s tests`：567 项，550 通过、17 项预期跳过、0 失败。
- `git diff --check`：通过，仅显示工作区既有 CRLF 转换警告。
- `TIMER_HOOK_SCRIPT` SHA-256 仍为 `0c65cbbd7eddd969225668f740a7b16ada1ff17f281b3c3b9efb6620ddc544a5`，长度仍为 `23657`，核心算法未修改。

### 仍需实机验证

- 仍需 Windows/X5Game 实机验证：四组同时注册、1409 冲突提示、保存后立即生效、四种作用范围、9/31 窗倍率跳转与恢复、快速连按不叠加，以及关闭程序后全部注销。
- 仍需人工确认弹窗视觉尺寸、四行控件基线、模态交互和单键快捷键在正常输入场景的可用性；自动化测试不等于真实 Windows/X5Game 验收。
- 未开发已取消的宿主侧生命周期守护；未打包正式 EXE。

## v1.4.17 Source Fixes Completed

- 快捷键已从树形面板显隐改为倍率往返：首次对加速总控当前四种作用范围之一应用设定倍率，再次恢复 `1.0`；非阻塞锁避免快速连续按键叠加，逐 binding 继续走既有 HWND/PID/X5Game/CDP 校验与批量倍率服务。
- 快捷键 UI 已移动到加速总控第二行且不复制作用范围；账号配置收回高度。“刷新地址”已移动到账号来源行与“账号管理”并列，原回调和刷新业务逻辑未改。
- “游戏程序/排列方式”使用相同宽度、左对齐标签列，路径输入仍随剩余宽度伸缩，其余窗口管理逻辑未改。
- 关闭本批后最多轮询 5 秒等待 PID 退出；只对同批次、同旧 PID、30 秒内刚关闭且历史 HWND/CDP 均失效的 `pid_not_x5game` 允许补开，防止把一般进程异常或 PID 复用无条件补开。
- 页面守护增加了幂等调度和文档根节点替换观察，源码目标是覆盖 Back/Forward、Reload、BFCache `pageshow` 及 DOM 根替换；但真实 X5Game Back/Forward 实机复验未通过，不能视为已完成。
- v1.4.15 的 `mouseenter -> cancelScheduledCollapse`、定时器执行前 `panel.matches(':hover')` 与 360ms 延迟仍保留；v1.4.16 历史 HWND、原端口和完整归属验证未改；`TIMER_HOOK_SCRIPT` 核心算法未改。

## v1.4.17 Verification

- `python -m compileall -q douluo_launcher tools` 与变更文件 `py_compile` 通过。
- Focused：快捷键 6、加速总控 8、加速面板/生命周期 46、刷新地址 GUI 18、修复业务状态 2、GUI 邻近回归 144（其中 17 项旧功能删除预期跳过）、发布断言 5，均无失败。
- 完整测试 `python -m unittest discover -s tests`：560 项，543 通过、17 项预期跳过、0 失败。
- 当时曾列出 9/9、31/31 的“关闭本批 → 立即修复”、四种快捷键范围倍率往返、两处布局和 Back/Forward/BFCache 生命周期；其中 Back/Forward/BFCache 自动恢复已在下方 Known Limitation 中明确取消，不再作为验收项。
- 未打包正式 EXE。

## v1.4.17 Known Limitation - Back/Forward Guard

- 实机按“5x → Back 到扫码页 → Forward 返回游戏”复验后，我们的树形加速器未恢复，游戏原生橙色加速入口重新出现。
- 当前实现仍依赖页面内部 JavaScript 的 `pageshow/popstate/load/MutationObserver` 自守护；登录流程结束后 CDP 在 `finally` 中关闭，页面或 target 被替换后缺少宿主侧重新注入者。
- 用户决定不再开发常驻宿主侧生命周期守护，避免给后续总工程增加轮询、永久 CDP 连接、线程、句柄和内存开销。
- 已确认现有“修复本批窗口”可重新完成 CDP 校验与加速器注入；Back/Forward 后若面板消失，使用该操作恢复。
- 本项作为已知限制接受，不再阻塞收尾，不升 v1.4.18；其余 v1.4.17 项目继续分别复验，未打包正式 EXE。

## Newly Recorded Enhancement - Multi-rate Hotkey Dialog

- 用户提出在加速总控 `500` 预设按钮右侧增加“快捷键设置”按钮，点击后弹出多倍率快捷键配置窗口。
- 每行配置“目标倍率 + 修饰键 + 主键”，例如 `3x=Alt+2`、`6x=Alt+3`；倍率可编辑，组合键继续支持现有修饰键及 `A-Z/0-9/F1-F12`。
- 每组快捷键自身按“该倍率 ↔ 1.0”切换；不同快捷键之间可直接跳倍率，例如 `1x → Alt+2=3x → Alt+3=6x → 再按 Alt+3=1x`。判断依据目标 binding 的真实 `speed_rate`，不能只记上一次按键状态。
- 新弹窗完全替代主界面现有单一快捷键整行；原修饰键、主键、当前组合、应用、清除控件全部移除，仅在加速总控 `500` 右侧保留“快捷键设置”按钮，并收回第二行高度。
- 旧 `speed_panel_hotkey` 不再后台自动注册，避免出现隐藏快捷键；底层解析、`RegisterHotKey`、`MOD_NOREPEAT` 和消息循环能力继续复用。
- 点击弹窗“确定”后，应一次性校验并注册全部组合，注册成功后立即生效且无需重启；“取消”不修改当前配置。
- 任意组合无效、重复或发生 Windows `RegisterHotKey` 冲突时，不允许保存半套配置，并应回滚原有整套快捷键。
- 多组快捷键必须共用一个 Windows 消息循环和多个 hotkey ID，不增加轮询或每组独立线程；按下后复用加速总控当前作用范围和逐 binding 归属校验。
- 当前仅完成需求登记，未修改业务代码、未升版本、未打包 EXE。

## v1.4.16 Completed

- 修复旧版本客户端批次无法恢复：常规窗口扫描未匹配时，不再直接用历史 PID 判定 `pid_not_x5game`，而是通过历史 HWND 重新读取当前真实 PID。
- 历史 HWND 回查重新执行 X5Game 进程名、监听端口 owner/process tree 和 CDP endpoint 完整归属验证；只有结果为 `verified` 且端口与原 binding 一致时才迁移。
- 回查结果一对一使用，拒绝 HWND 复用但端口变化的窗口；不根据通用标题、账号顺序或连续端口猜测。
- 修复成功后更新真实 PID/HWND/CDP 归属信息，只保留真正的已就绪/已排列/已登录业务状态；上一次失败修复写入的 `pid_not_x5game` 等错误不会再次覆盖成功结果。新增安全诊断日志，不输出直登链接或敏感参数。
- 新增 4 项回归用例：旧 PID 迁移成功、HWND/端口不一致拒绝迁移、旧窗口错误状态不回写、真实登录状态继续保留；版本、README、发布断言和实机记录同步到 1.4.16。未打包正式 EXE。

## v1.4.16 Verification

- 代码级根因已确认，来源于用户提供的真实日志：常规扫描 0、历史 HWND 存在、9 个 binding 全部被旧 PID 检查判为 `pid_not_x5game`。
- CodexPro 本地命令执行仍因 `spawn bash ENOENT` 未能运行 focused/full tests；这属于执行环境不可用，不代表测试通过或失败。
- 需使用上一个版本仍在运行的真实批次重新执行“修复本批窗口”，确认日志出现历史 HWND 回查，9 个 binding 恢复为就绪且 PID/CDP 归属正确。
- 树形加速器 v1.4.15 误收起修复仍待同轮实机复验；正式 EXE 未打包。

## v1.4.17 Completed Scope - 5 Fixes + 2 Regression Guards

- 快捷键已改为倍率往返开关：第一次应用加速总控设定倍率，第二次恢复 `1.0`，第三次再次应用设定倍率；继续复用加速总控四种作用范围。UI 已从“账号配置”移动到“加速总控”第二行，并直接复用现有作用范围；账号配置已收回多余高度。
- “关闭本批客户端”后立即修复的 8/9 问题已增加退出轮询与安全补开条件；普通 `pid_not_x5game` 不会被无条件放行。
- 窗口管理“游戏程序/排列方式”两行已统一标签列和起始位置，路径框继续按剩余宽度伸缩，窗口管理业务逻辑未改。
- “刷新地址”入口已从“工作模式”移动到“账号配置”的账号来源一行，与“账号管理”并列；原刷新业务逻辑保持不变。
- Back → Forward/BFCache 生命周期守护已补充幂等调度和文档根节点观察，用于恢复我们的树形面板并重新抑制原生入口；`TIMER_HOOK_SCRIPT` 核心算法未修改。
- 本轮 5 项源码修复及 v1.4.15、v1.4.16 两项回归保护均已完成自动化验证，共 7 个跟踪项；当前等待 X5Game 实机复验，未打正式 EXE。

## v1.4.15 Completed

- 修复树形加速器误收起：`mouseleave` 产生的 360ms 延迟收起任务，在鼠标重新进入面板时会立即取消；定时器到期前还会检查 `panel.matches(':hover')`，鼠标实际仍在面板范围内时不会收起。
- 保留真正移出后的延迟收起；未改为永久展开，也未改变根标签点击、快捷键切换、拖动、倍率步进、预设按钮或倍率核心算法。
- 新增回归断言，要求树形面板注册 `mouseenter -> cancelScheduledCollapse`，防止后续删除取消逻辑。
- 版本、README 和发布断言同步到 1.4.15。未打包正式 EXE。

## v1.4.15 Verification

- 代码级根因已确认：旧实现只在 `mouseleave` 时安排收起，没有在重新进入时取消定时器。
- CodexPro 本地命令执行当前因 `spawn bash ENOENT` 未能运行 focused/full tests；这属于执行环境不可用，不代表测试通过或失败。
- 仍需 X5Game 实机确认：人物移动、鼠标在根标签与分支按钮间移动时不再误收起，真实移出后仍按 360ms 延迟收起。
- 正式 EXE 未打包。

## v1.4.14 Completed

- 修复待登录范围：候选来自当前活动批次，排除真实登录成功状态，并要求 binding 的 HWND/PID/CDP 已准备且存活；“已排列/客户端已就绪”不再因展示字符串被排除。
- 快捷键 UI 改为一个组合修饰键下拉和一个可编辑主键下拉；支持单键、标准化、真实注册失败提示、旧配置迁移，并复用加速总控四种作用范围逐 binding 切换树形面板。
- 树形面板根标签加入 5px 拖动阈值、pointer capture、viewport 夹取和拖动后 click 抑制；位置不持久化，DOM 重建仍从默认左上角创建。
- 账号管理拆为状态/分组两个下拉并组合过滤；主账号表收口为五列，读取有效 HWND 的 Win32 标题，重命名成功后同步 record/binding title。
- 窗口管理压缩为两行并改短文案；旧启动项和旧“窗口操作”整行不再创建。客户端直登批次区的准备、排列、修复、识别、关闭等入口及公共底层能力保留。
- 版本、窗口标题来源、README 和发布断言同步到 1.4.14。未打包正式 EXE。

## v1.4.14 Root Causes

- 待登录范围只匹配固定展示状态集合，排列/就绪会覆盖原状态。
- 快捷键 worker 仍按前台 HWND 唯一匹配，没有读取加速总控范围。
- 树形根标签只有 click 监听，没有拖动状态机。
- 账号管理将状态值和动态分组拼进同一个筛选框。
- 主表仍按旧八列生成，窗口号来自账号配置而非 binding 的真实窗口。
- 窗口管理源码仍实际创建旧启动区和旧窗口操作按钮行。

## v1.4.14 Verification

- Focused: hotkey 6、speed panel 45、release 5、GUI hotkey 2、login scope 4，全部通过。
- GUI adjacent: 141 run，124 passed，17 skipped，0 failed。
- Full suite: `python -m unittest discover -s tests -q` -> 552 run，535 passed，17 skipped，0 failed。
- Real LauncherApp construction: `LAUNCHER_APP_CONSTRUCTED 斗罗大陆H5上号器 - 客户端直登批次版 v1.4.14`。
- `TIMER_HOOK_SCRIPT` SHA-256 remains `0c65cbbd7eddd969225668f740a7b16ada1ff17f281b3c3b9efb6620ddc544a5`, length 23657.
- All stateful tests used isolated temporary APPDATA. Formal EXE packaging was not run.

## v1.4.14 External Validation Required

- 实机验证已就绪/已排列账号可手动进入游戏且已登录账号不重登。
- 实机验证四种快捷键范围、单键提示、冲突/替换/清除、长按不重复及逐窗口失败隔离。
- 实机验证树形面板拖动、边界夹取、点击/拖动区分以及 Reload/Back/Forward/导航/DOM 重建复位。
- 视觉确认账号管理双筛选、主表真实标题和 1080x820/1160x940 两行窗口管理布局。
- 回归 9/31 窗并发 8、缺窗原槽位、连续端口、5x/1x、窗口生命周期；存钻第 9 窗登录仍需完整汇总闭环。

## v1.4.14 Planned From Live Validation

- Requirements are confirmed and documented. The user will personally tell Codex when to begin; no business-code changes or formal EXE build are authorized before that instruction.
- Fix manual prepared-login scope so valid current-batch bindings in “客户端已就绪/已排列” remain eligible when they have not logged in; do not rely only on display-status strings.
- Replace the v1.4.13 two-modifier-plus-main-key hotkey UI with one combined-modifier dropdown (`None/Ctrl/Alt/Shift/Ctrl+Alt/Ctrl+Shift/Alt+Shift/Ctrl+Alt+Shift`) plus one editable main-key combobox. The main key supports dropdown selection or direct input for A-Z/0-9/F1-F12 with trimming, uppercasing, validation, and legacy migration.
- Change the accelerator hotkey target from foreground-only to the shared speed-control scope: current batch, selected windows, all live batches, or CDP-available windows. The hotkey still toggles panels only and must not change rates.
- Restore tree-panel movement by dragging the compact rate root, with click/drag separation and viewport clamping; do not persist the position, and reset to the default top-left after reopen, navigation, reload, or DOM rebuild; do not restore the old large panel.
- Split account-manager filtering into independent status and group dropdowns with combined filtering.
- Simplify the main account table to level, bookmark number, real bound-window title, include-in-all, and status. Remove passport/link/timing display columns without removing their backend data or logs; window title remains display-only and must not replace ownership checks.
- Preserve the confirmed per-virtual-desktop title scheme: desktop/batch 1 uses 1-9, desktop/batch 2 uses 1-31, and desktop/batch 3 uses 1-9. Duplicate titles across virtual desktops are intentional; do not convert them to global 1-49. Only keep the displayed binding title synchronized with the actual Win32 title.
- Complete the already confirmed two-row window-management layout, rename the two labels, and truly remove the legacy window-operation row while retaining all client-direct shared backend capabilities.
- These items are one v1.4.14 scope. Business code has not started, and no formal EXE has been built.

## v1.4.13 Completed

- Rebuilt the accelerator hotkey UI as two modifier dropdowns plus one A-Z/0-9/F1-F12 main-key dropdown, with normalized preview, exact validation, apply, clear, persistence, and legacy string migration.
- Fixed the Win32 hotkey path by explicitly creating the listener thread message queue before registration and logging registration, WM_HOTKEY receipt, dispatch failures, foreground-binding rejection, ownership rejection, and CDP toggle results. MOD_NOREPEAT and unregister-on-change/clear/exit remain enforced.
- Changed the tree root to the confirmed current rate, implemented fixed-point 0.1 stepping below 1x and 1.0 stepping at/above 1x with a 0.1x floor, and removed mouseenter expansion while preserving root click and mouseleave delayed collapse.
- Fixed manual “执行登录并进入游戏” to pass auto_enter_game=True. The checkbox now controls only the one-click prepare/arrange/login continuation.
- Removed the advanced-config button/frame/state, per-group count controls, exposed port/speed-panel technical settings, legacy method2 CSV UI/workers, legacy foreground/OCR mode entry, and background/foreground serial workers.
- Unified the main account source on refresh-data AccountsStore. bookmark_path now derives 默认组 / 单层账号 / dynamic parent groups without numeric-name or fixed-count filters.
- Added an independent login roster storing only stable hashed identity, participation, seen-state, and global order. Account manager supports required filters, masked links, move up/down, join, and non-destructive removal.
- Changed refresh-address destructive wording to “移除账号” with an explicit resource-boundary confirmation, and reconciles the login roster after refresh/removal.
- Bookmark writeback now updates one unique target, creates missing folders and the final URL node, keeps empty paths local-only, and blocks duplicate-name conflicts.
- Fixed the source-mode startup regression caused by the removed advanced bookmark UI: startup now loads the refresh-address account library directly and no longer scans the deleted `_method1_root_combo` control.
- Updated APP_VERSION, title source, README, and release assertions to v1.4.13. No formal EXE was built.

## v1.4.13 Root Causes

- Manual prepared login reused the one-click checkbox value at the final worker boundary, so a deliberate manual click still sent auto_enter_game=False.
- The speed tree used a fixed root label, preset-index stepping, and a panel mouseenter handler, so the visible value and plus/minus behavior did not represent the applied numeric rate.
- The hotkey listener did not explicitly create its thread message queue and swallowed dispatch exceptions, making a successful RegisterHotKey result neither sufficient nor diagnosable.
- The main account list still came from bookmark scanning plus level_counts, while method2 and compatibility controls could re-activate separate account sources and execution workers.
- Bookmark writeback treated a missing path as terminal instead of safely constructing the missing folder/item chain.
- `_load_default_config_if_present()` still followed the deleted bookmark-scanning startup path and unconditionally reached `_method1_root_combo`, causing source mode to raise `AttributeError` while constructing `LauncherApp`.

## v1.4.13 Verification

- Speed panel/hotkey focused: 58 passed, 0 failed.
- Login-roster focused: 4 passed, 0 failed.
- Bookmark writeback focused: 14 passed, 0 failed.
- Direct-link refresh focused: 25 passed, 0 failed.
- Refresh-address GUI focused: 18 passed, 0 failed.
- GUI adjacent regression with isolated temporary APPDATA: 143 run, 126 passed, 17 skipped, 0 failed. All skips are obsolete v1.4.13-removed legacy/background/method2 behavior tests.
- Release assertions: 5 passed; config: 22 passed; prepared direct login: 18 passed; client batch: 31 passed.
- Full `python -m unittest discover -s tests` with isolated temporary APPDATA: 553 run in 20.589s, 536 passed, 17 skipped, 0 failures/errors.
- Source startup smoke: `python main.py` remained alive for 8 seconds with no stderr/traceback; only the diagnostic process was then stopped.
- `python -m compileall -q douluo_launcher tests main.py` -> exit code 0.
- Changed-file `python -m py_compile ...` -> exit code 0.
- `git diff --check` -> exit code 0 with existing CRLF conversion warnings only.
- TIMER_HOOK_SCRIPT SHA-256 before/after: `0c65cbbd7eddd969225668f740a7b16ada1ff17f281b3c3b9efb6620ddc544a5`; length 23657. Core algorithm unchanged.
- All stateful test runs used an isolated temporary APPDATA and did not touch the user's real configuration.
- No formal EXE was built.

## v1.4.13 External Validation Required

- Real Windows hotkey registration/trigger, replacement, clear, conflict reporting, long-press no-repeat, and foreground/non-binding isolation.
- Tree root values and plus/minus boundaries at 0.1/0.9/1/2/5/50/500 after initial load, click-only open, mouseleave collapse, Reload/Back/Forward/navigation/dynamic rebuild.
- Unchecked one-click stops before entering the game, followed by manual “执行登录并进入游戏” entering the game in the same bound window.
- Account-manager ordering and participation: 单层账号 9 on desktop 1; 全部 31 selected groups on desktop 2 without re-running the single-layer accounts.
- Bookmark unique update, missing nested path creation, empty-path local-only, duplicate conflict, and browser-running safety against a real Bookmarks file.
- Confirm no regression to 9/31 concurrency-8 HWND/PID/CDP ownership, missing-window slot preservation, continuous port allocation, 5x/1x batch switching, or any window visibility/minimize/position/size/Z-order behavior.
- Source-mode create/show startup smoke passed; full visual interaction and formal EXE packaging remain blocked pending live acceptance.

## Previous v1.4.11 Completed

- Added truthful native speed UI states with DOM-remove-first and CSS fallback behavior.
- Reduced dynamic native-UI handling to one debounced observer and removed permanent broad polling.
- Removed global context-menu interception from defaults, effective GUI options, template settings, and injected guards.
- Added a shared speed-control backend with full CDP ownership validation before apply.
- Moved multi-binding speed work off the GUI thread; stop prevents subsequent starts and one failure continues.
- Treats `ok=false` as failure; only confirmed success persists `speed_rate`; business/login/window status remains unchanged.
- Preserved 1x/2/5/50/500, target scopes, window lifecycle, and the timer-hook core algorithm.
- Updated version metadata, title source, README, task plan, current plan, and release assertions to v1.4.11.

## v1.4.11 Verification

- Baseline full suite: 504 passed.
- Focused native speed UI: 39 passed.
- Shared speed control: 6 passed.
- GUI group regression: 133 passed; refresh-address GUI regression: 17 passed.
- Batch regression: 31 passed; config: 21 passed; direct login: 16 passed.
- Release assertions: 5 passed.
- Final `python -m compileall -q main.py douluo_launcher tests tools` -> exit code 0.
- Final `python -m unittest discover -s tests -q` -> 519 passed in 13.446s, 0 failures, 0 skips.
- `git diff --check` -> exit code 0 with existing CRLF conversion warnings only.
- Node syntax compilation passed for the native-UI script, navigation guard, and combined new-document script.
- Timer-hook core normalized comparison -> unchanged, 23685 characters before and after.

## v1.4.11 External Validation

- Real X5Game 1/2/9-window validation has not been run and must not be reported as passed.
- Validate native UI handling after initial load, Reload, Back, Forward, navigation, and dynamic rebuild.
- Validate selected/current-batch/all-live targeting, full ownership isolation, stop behavior, failure continuation, and successful-rate persistence.
- Observe 1x/2x/5x/50x/500x short runs and recovery to 1x; automated tests do not establish disconnect stability.
- Formal EXE packaging was intentionally not executed.

## Previous v1.4.10 Completed

- Fixed the v1.4.9 CDP concurrency ownership false negative: exact `owner_pid == window_pid` now verifies the process relation without a Toolhelp process snapshot.
- Preserved endpoint authenticity probing after same-PID verification; endpoint failure still blocks the binding before `Page.navigate`.
- Kept process-tree validation for different PIDs, including legal ancestor/descendant acceptance and unrelated-tree rejection.
- Added serialized process snapshots, at most 3 attempts with 50ms/100ms backoff, and safe diagnostics for attempts, exception summary, Windows error code, endpoint state, and final state.
- Added 31-binding concurrency-8 regression coverage without lowering or bypassing the existing concurrency limit.
- Synchronized version metadata, visible title source, README, release assertion, v1.4.10 task result, and current plan to v1.4.10.

- Restored the v1.3 resident-window login lifecycle. `minimize_during_login` now defaults to `False`, and the normal prepared-login path no longer minimizes or restores windows on success, failure, timeout, or stop.
- Added strict CDP ownership validation: `HWND -> window PID -> TCP listener owner PID/direct process tree -> CDP endpoint` during local scan/restore and again immediately before `Page.navigate`.
- Removed local-scan candidate-port generation and history/title/base-port/slot inference. Ownership failures block only the affected binding; duplicate verified ports are marked as conflicts.
- Persisted CDP owner PID/status plus stable account identity and link status in batch bindings.
- Local-scanned batches map deterministic slots against account-library order and inject latest links through `account_key`, `refresh_account_name`, `bookmark_path`, and `slot_index`; generic X5Game titles are display-only.
- Added unique bookmark-path resolution for refresh records whose stored names differ from bookmark account names. Duplicate paths, duplicate slots, identity conflicts, and count mismatches are blocked rather than guessed.
- Synchronized version metadata, README, release assertion, v1.4.9 plan, and current plan to v1.4.9.

## Previous Verification

- v1.4.10 baseline: `python -m unittest discover -s tests -v` -> 497 passed.
- CDP ownership focused suite -> 13 passed.
- Client direct login focused suite -> 16 passed.
- GUI adjacent regression -> 130 passed.
- Release packaging assertions -> 4 passed, including the main-window `APP_VERSION` title source.
- Final `python -m compileall -q main.py douluo_launcher tests tools` -> exit code 0.
- Final `python -m unittest discover -s tests -q` -> 504 passed in 13.395s, 0 failures, 0 skips.
- Windows API source-runtime check successfully read the TCP listener table and process-parent snapshot.

- Baseline: `python -m unittest discover -s tests -v` -> 479 passed.
- Problem 1 focused regression -> 13 passed; phase full suite -> 480 passed.
- Final resident-window focused suite -> 15 passed, explicitly covering success, failure, timeout, and stop.
- Problem 2 related regression -> 181 passed; phase full suite -> 492 passed.
- Problem 3 related regression -> 208 passed; phase full suite -> 495 passed.
- Release packaging assertions -> 3 passed.
- Final `python -m compileall -q main.py douluo_launcher tests tools` -> exit code 0.
- Final `python -m unittest discover -s tests -v` -> 497 passed in 17.399s, 0 failures.
- Windows API source-runtime check successfully read the TCP listener table and process-parent snapshot.
- `git diff --check` -> no whitespace errors; only existing CRLF conversion warnings.

## Previous External Validation

- Real X5Game 31-window concurrency-8 validation has not been run and must not be reported as passed.
- Required live acceptance: run 9 windows at concurrency 8, then 31 windows at concurrency 8 for multiple rounds; verify 31/31 preparation, ownership and login, no random `cdp_owner_unverified`, no wrong-window navigation, and no visibility/geometry/Z-order changes.
- EXE packaging was intentionally not executed.
- Synchronizer, accelerator/speed engine, OCR, passport, auction, YOLO, method 1/method 2 stable core, and window arrangement algorithm were intentionally untouched.

## Workspace Safety

- Existing unrelated uncommitted changes were preserved; no reset, checkout, bulk deletion, or overwrite was performed.
- User CSV, browser Bookmarks, backups, logs, and historical summaries were not modified.
