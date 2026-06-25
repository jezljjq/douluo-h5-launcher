# 项目开发规则

**适用范围**：斗罗大陆H5上号器项目。每次开发都必须遵守。

---

## 1. 文档任务默认禁止修改代码

当用户说"整理文档""更新文档""完善文档""同步文档""生成交接文档""更新项目说明""文档收尾"时，必须先读取并执行 [DOC_UPDATE_PROMPT.md](DOC_UPDATE_PROMPT.md)。

文档整理任务请先阅读并遵守 [DOC_UPDATE_PROMPT.md](DOC_UPDATE_PROMPT.md)。

打包发布任务请先阅读并遵守 [BUILD_RELEASE_PROMPT.md](BUILD_RELEASE_PROMPT.md)。

- 用户要求"更新文档"时，只允许修改 `.md` 文件
- 禁止修改 `.py`、`.bat`、`.json`、启动脚本、配置文件
- 文档任务只允许改文档，不允许顺手改代码
- 如发现代码 bug，必须先说明问题并等待用户确认后再修改
- 修改前必须列出计划修改文件清单
- 修改后必须运行回归验证
- 打包必须单独确认，不得在普通开发任务中自动打包

## 2. 修改前声明范围

每次开发前明确：
- 本次修改哪些模块
- 哪些模块禁止改动

## 3. 禁止无关重构

修改功能时只能修改当前目标相关代码。禁止为修小问题重写整个流程。

## 4. 已稳定模块禁止随意修改

以下模块已稳定，除非确认存在 bug，否则禁止重构：
- 通行证复制优先获取逻辑
- OCR 兜底与低置信度拦截逻辑
- 模板匹配按钮定位
- Dm 前台点击
- 公告关闭
- 登录校验
- GUI 状态刷新
- Playwright 初始化
- 通行证输入和确认逻辑
- `dm_client.py` 中已验证的窗口截图和大漠诊断逻辑
- `dm_click_helper.py`

任何修改前必须说明修改范围；任何修改后必须说明验证结果。

### 停止任务与关闭程序清理规则

停止任务机制已修复并验证通过，禁止回退：

- 点击“停止任务”后，不能只设置 `stop_event`。
- 必须强制终止当前账号运行子进程。
- 必须清理 `dm_click_helper.py` 子进程。
- 必须清理本次 Playwright/Chromium 相关进程。
- 必须保证不再继续后续账号。

关闭程序机制已修复并验证通过：

- 点击窗口右上角关闭时，必须先执行停止任务和子进程清理。
- GUI 关闭后，不允许残留子进程继续移动鼠标。
- 必须避免 `_drain_ui_queue` 在窗口关闭后继续 `after` 回调。

安全边界：

- 禁止只做协作式 `stop_event`，不清理实际子进程。
- 禁止误杀所有 `python.exe`，只能清理本项目相关子进程。

## 5. 每次修改后必须回归验证

修改完成后重新验证：
- OCR 提取
- 公告关闭
- 通行证按钮定位
- 输入通行证
- 确认登录
- GUI 状态刷新
- 串行流程

## 6. 废弃方案禁止回退

以下方案已确认不可用，禁止重新尝试：
- 二维码裁剪定位 OCR
- Playwright canvas click
- CDP dispatchMouseEvent
- SendMessage / PostMessage
- Dm BindWindow（7.2607 + Win11 全模式崩溃）

## 7. 当前项目阶段

**前台串行阶段性完成版 + 窗口管理区接入完成**。方式一、方式二、源码模式、exe 模式均已完成当前阶段验证。优先级：保持稳定 > 31 窗口长期验证 > 窗口定位融合 > UI 美化。禁止大规模重构。

当前开发顺序：

1. 先稳定上号成功率。
2. 再做窗口管理排序结果与上号器窗口定位融合。
3. 再做 UI 美化。
4. 最后单独确认打包 exe。

UI 美化不得影响核心流程。

### 防回归技能

已新增技能：`D:\Ai\skills\launcher-regression-guard\SKILL.md`。

修改上号器相关代码前必须优先检查：

- 已登录窗口不能继续 OCR。
- 已进入游戏 / 公告界面必须优先识别为 `logged_in`。
- 只有明确 `qr_page` 才允许复制通行证或 OCR。
- `unknown`、截图失败、二维码页仍存在都不能判成功。
- OCR 低置信度和 `c/e` 混淆不能直接接受。
- 停止任务必须终止子进程，关闭程序后不能继续移动鼠标。
- 源码模式和 exe 模式资源路径必须一致。
- 单层账号和四层账号不能混用。
- 固定参数排列和行数列数排列参数必须分开记忆。
- 存在 `window_slots.json` 时，普通“排列窗口”必须按槽位恢复布局，不能按 `hwnd` / 枚举顺序重新排序。
- `window_slots.json` 是当前批次窗口槽位快照，不是永久配置；长期窗口排列参数必须以 `window_manager_settings.json` 为准。
- `window_slots.json` 必须保存环境信息、DPI、缩放比例、屏幕分辨率和 `layout_params`；不同显示环境或布局参数不一致时必须记录/提示，不能静默覆盖槽位。
- 游戏窗口识别必须统一使用 `window_manager.is_game_window()` / `list_game_windows()`；禁止用 `title.startswith("斗罗大陆")`、`"斗罗大陆H5" in title` 等模糊标题匹配。
- 辅助/工具/上号器等排除关键字必须优先排除；配置了游戏程序路径时，hwnd 进程 exe 路径等于配置的 `X5Game.exe` 是强确认条件，但进程路径不匹配不能一票否决。
- 编号游戏窗口标题必须从当前 UI 标题模板动态生成正则，模板中的 `{index}` / `{number}` 才是编号位置；模板其它字符必须转义，允许 `-运行状态` 后缀。禁止在识别规则里写死 `斗罗大陆H5`。
- `SetWindowPos` 错误码 5 必须提示 Windows 拒绝访问和权限不一致原因；排列或重新生成槽位只要有任意移动失败，必须停止保存，禁止写槽位。
- 窗口识别失败或数量异常时，必须能在 `logs/window_detection_detail.log` 看到候选窗口的 hwnd/title/class_name/pid/process_path/rect/accept/reject/reason。
- “刷新槽位映射”只能扫描当前带编号窗口并保存 `hwnd`、标题、位置和尺寸，禁止移动窗口、重命名窗口、启动新窗口或覆盖无关槽位。
- 修复单个 slot 时，如果历史位置缺失，必须按顺序尝试：`window_slots.json` → 当前窗口标题编号补齐 → 固定排列参数推导；不能直接全局重排。
- “重新生成槽位”必须是单独高风险入口，并且需要二次确认后才允许全局排列、全局编号和覆盖 `window_slots.json`。
- 全部 H5 窗口关闭后重新批量启动时，必须按当前 `window_manager_settings.json` 重新生成槽位，禁止沿用旧 `hwnd` 快照。
- `window_slots.json` 是本地运行状态文件，不提交 Git，不进入发布包。
- 禁止写死窗口坐标、编号、分辨率、DPI、缩放比例、窗口数量、路径或槽位号。
- 游戏路径不能写死；必须支持拖入或选择 exe、lnk 快捷方式和游戏安装目录，快捷方式只能保存解析后的真实 exe。
- 当前正式拖拽方案是公开库 `tkinterdnd2`。原生 `WM_DROPFILES` 拖拽实现已导致 Tk 窗口闪退，禁止启用、禁止回退。
- Windows 会阻止普通资源管理器向管理员权限窗口拖入文件；GUI 默认不得在启动时自动管理员提权，否则会破坏游戏图标拖拽。
- 游戏图标拖拽只能使用 `tkinterdnd2`、`windnd` 或公开 Windows API 的独立实现；禁止反编译、破解、复制或提取任何第三方闭源脚本/程序实现。
- 配置区默认必须是客户模式：普通客户只需要点击“选择游戏图标/程序”、点击“自动查找收藏夹”、选择账号目录、点击“读取账号”。
- `Bookmarks` 原始路径、`bookmark_root_path`、兼容目录名、自动化设置路径和每层数量属于高级配置，必须默认折叠，禁止堆在主界面。
- 收藏夹候选下拉只能显示 `Edge - Default - 发现 N 个账号目录` 这类客户可读文本，禁止直接显示 `C:\Users\...\Bookmarks` 原始路径。
- 账号目录下拉只能显示 `收藏栏 / 斗罗大陆 - 31个账号，包含4个分组` 这类客户可读文本，禁止显示内部 JSON root path。
- 收藏夹路径是用户配置，不是自动推断结果；启动时必须优先读取 `automation_settings.json` 中上次保存的 `bookmark_file`。
- Chrome / Edge 自动探测只能作为候选提示，禁止因为 Chrome Bookmarks 存在就静默覆盖用户保存路径。
- 多个 Bookmarks 或账号目录候选时必须让用户选择；只有保存路径缺失且唯一候选时才允许自动选择并记录日志。
- 保存配置时必须保留 `bookmark_file`、`bookmark_browser`、`bookmark_profile`、`bookmark_root_path`、`bookmark_root_display_name`。
- 切换收藏候选时必须清空旧账号目录候选和旧账号列表；禁止出现 Chrome 候选配 Edge 账号目录。
- 账号目录候选必须绑定 `bookmark_file_path` 和结构化 `root_path`；读取前必须校验它属于当前 Bookmarks 文件。
- 读取账号必须用结构化 `root_path` 定位目录，禁止只用显示文本最后一段目录名如 `存钻`。
- 读取失败时必须清空或明确标记旧账号列表，禁止继续静默显示上一次成功读取的 `第一层` 数据。
- 运行区层级必须来自当前已加载账号；未读取时不能显示硬编码 `第一层`，只加载 `存钻` 时默认层级应切到 `存钻`。
- 读取收藏夹失败时必须记录当前 Bookmarks 路径和检测到的一级目录。
- exe 模式必须读取 exe 同级 `automation_settings.json`，不能用源码配置或默认 Chrome 路径覆盖用户配置。
- 收藏夹账号目录不能强制叫 `账号`；必须允许从 Bookmarks 内扫描出的账号目录候选下拉选择。
- 游戏链接直接放在收藏栏或其它收藏夹时必须支持，不能因为没有目录就判失败。
- 老配置 `bookmark_root_name="账号"` 仍需尽量兼容，但保存了 `bookmark_root_path` 时必须优先按路径恢复。
- 根目录下纯数字收藏项作为 `单层账号`；根目录下非数字收藏项必须跳过并记录日志。
- 自定义分组内账号标题不要求纯数字，必须按收藏夹原始顺序读取和映射窗口，禁止强行数字排序。
- `层级=全部` 必须显示过滤后的全部串行范围，只包含 `include_in_all=true` 的分组账号；不能显示未勾选分组。
- `全部串行` 必须直接使用与 `层级=全部` 一致的过滤后账号列表，禁止 UI 显示一套、实际运行另一套。
- 当前层级为 `全部` 时点击 `当前层串行`，也只运行当前列表中显示的 `include_in_all=true` 账号。
- 新发现分组默认 `include_in_all=false`，禁止自动加入全部串行。
- 未勾选分组仍必须允许 `当前层串行` 和 `单账号运行`。
- 如果没有任何分组勾选 `include_in_all`，`层级=全部` 的账号列表必须为空，并提示“当前没有勾选参与全部串行的账号”。
- 方式一账号表列顺序统一为：`层级 / 收藏编号 / 窗口号 / 参与全部串行 / 本次通行证 / 链接 / 状态 / 耗时`。
- 更新账号表时必须使用统一列定义或列名索引，禁止用旧硬编码下标把通行证、状态、耗时写入错误列。
- UI 表格只能作为展示层，禁止把 Treeview values 下标作为上号业务数据源。
- GUI 日志区必须保留可见高度：默认窗口 1160x820，最小窗口 1080x760；日志区显示 8 行，容器固定最小高度，缩小时不得被账号表格压缩到不可见。
- “打开日志目录”按钮必须保留在日志区右上角；日志追加后必须自动滚动到底部。

## 8. 后台登录模式规则

- 默认运行模式必须保持 `前台辅助模式`，禁止把未完整验证的后台链路设为默认。
- `BackgroundOperator` 禁止调用全局 `MoveTo`、`LeftClick`、全局键盘输入或 `SetForegroundWindow`。
- 后台点击和后台输入必须先通过 `tools/background_operator_probe.py` 在真实单窗口验证，未验证通过前只能标记为实验能力。
- 后台方式一单账号、后台当前层串行、后台全部串行均复用 `BackgroundSingleAccountRunner`；后台串行并发固定为 1，禁止在当前阶段开启后台并发。
- 后台当前层串行已完成 `存钻` 前 2 个账号小范围 live 验证；后台全部串行已接入但等待更大范围 live 验证。
- 后台串行中，单个账号失败必须继续下一个；只有用户停止、依赖预检失败、读取设置失败或运行前预检失败才中断整轮。
- 后台成功窗口默认保留，方便人工确认；停止后台任务时不得清理已打开成功窗口。
- 后台模式禁止 WM_GETTEXT、UIA、后台 Ctrl+C、剪贴板 marker、剪贴板读取和剪贴板恢复；真实验证失败后不得恢复。
- 选择 `后台登录模式（实验）` 但遇到未接入路径时，必须明确日志提示并阻止，禁止静默 fallback。
- 黑屏保护当前只允许保留接口，未验证后台截图/点击/输入前禁止接入默认登录流程。

## 9. `subprocess.Popen` monkey-patch 规则

`automation.py` 模块级 monkey-patch 覆盖 `subprocess.Popen` 用于注入 `CREATE_NO_WINDOW`（抑制 pytesseract 等第三方库子进程黑框）。

**必须遵守**：
- 必须用 **class 继承**，禁止用 function 替换
- `from playwright.sync_api import sync_playwright` 前必须临时恢复原始 Popen，导入后恢复补丁
- 违反此规则会导致 asyncio 子类化失败（`TypeError: function() argument 'code' must be code, not str`）

```python
# ✅ 正确：class 继承
_original_popen = _subprocess.Popen
class _NoConsolePopen(_original_popen):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("creationflags", _subprocess.CREATE_NO_WINDOW)
        super().__init__(*args, **kwargs)
_subprocess.Popen = _NoConsolePopen

# ❌ 错误：function 替换（会导致 asyncio 崩溃）
_subprocess.Popen = lambda *a, **kw: _original_popen(*a, **{**kw, "creationflags": ...})
```

## 10. 每完成一个阶段必须更新文档

代码与文档必须同步。详见 [README.md](README.md) 文档索引。

---

## 10.1 防回归硬规则

历史事故统一登记在 [ERROR_HISTORY.md](ERROR_HISTORY.md)，自动化测试映射见 [REGRESSION_TESTS.md](REGRESSION_TESTS.md)。

- 每修一个 bug，必须补一条或更新一条回归测试。
- 没有回归测试的修复，不算完成。
- 如果某个问题无法自动化测试，必须在文档中说明原因，并给出人工验证步骤。
- 修复旧问题时必须先检查 [ERROR_HISTORY.md](ERROR_HISTORY.md)，确认是否已有同类事故。
- 新增测试应优先覆盖逻辑边界，避免依赖真实游戏窗口、真实账号、真实截图。
- 防回归测试失败时，禁止提交、禁止 push、禁止打包。

提交、push、打包前必须执行：

```powershell
python -m compileall -q douluo_launcher main.py
python -m unittest discover -s tests -v
```

---

## 11. 同类问题全局排查规则

修 bug 时不能只修当前看到的一处。必须先判断问题类型，然后全项目搜索同类风险点，避免修 A 漏 B。

### 修复前必须全局搜索

发现一个 bug 后，先搜索同类代码。例如：

**子进程弹黑框类**：搜索 `subprocess.run`、`subprocess.Popen`、`py -3.14-32`、`dm_click_helper`、`CREATE_NO_WINDOW`、`shell=True`、`python` 子进程、`taskkill`

**OCR 类**：搜索 `extract_passport`、`extract_hex`、`pytesseract`、`OCR`、`ocr`、`本次通行证`

**Dm 点击类**：搜索 `DM_CLICK`、`dm_click`、`MoveTo`、`LeftClick`、`dm_click_helper`、`大漠`

**日志类**：搜索 `log(`、`file_log`、`status_fn`、`print(`

**Playwright 类**：搜索 `sync_playwright`、`browser`、`page`、`context`、`new_page`、`close`、`stop`

### 修复前必须输出排查结果

每次修复前必须先输出：

1. 本次问题类型
2. 全局搜索了哪些关键字
3. 找到哪些相关位置
4. 准备修改哪些文件/函数
5. 哪些相关位置不修改，以及原因

### 禁止只修一个点就说完成

禁止：看到报错 → 修一个位置 → 不搜索其它 → 说修好了。

必须是：看到报错 → 判断类型 → 全项目搜索 → 列出所有位置 → 一次性处理 → 验证。

### 修复后必须验证同类场景

- 当前 bug 是否修复
- 同类场景是否也修复
- 已稳定功能是否没有回退

### 完成前必须汇报

说"修好了"之前必须告知：搜索了哪些关键字、找到几处、修改几处、保留几处及原因、回归验证结果。
# 收尾阶段规则补充（2026-05-17）

- 当前已验证文件级通行证弹窗坐标缓存、合并 Dm chain、批量快速登录 + 统一校验。
- 单账号运行必须保留完整校验逻辑。
- 当前层串行 / 全部串行可以使用快速提交 + 统一校验，但不能放宽成功判断。
- `qr_page`、`unknown`、截图失败都不能判成功。
- 统一校验失败账号只重登失败账号，不允许无故全量重跑。
- 通行证复制优先、OCR 兜底、公告关闭、Dm 点击、Playwright 初始化、登录校验属于稳定链路，禁止无关重构。
- 文档任务只允许改文档，不允许顺手改代码。
- 打包必须单独确认，不得在普通开发任务中自动打包。

---
