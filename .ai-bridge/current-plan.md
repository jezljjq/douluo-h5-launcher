# v1.4.20 收藏夹稳定根身份与现有链接同步

Updated: 2026-07-12
Workspace: D:\Ai\codex\上号器
Target agent: Codex (codex)

## Plan

项目路径：`D:\Ai\codex\上号器`

正式计划文档：`docs/上号器_v1.4.19_收藏夹安全导入与账号批量参与修复计划_20260712.md`

当前阶段：v1.4.20 打包态开发数据迁移越界已修复，完整测试、正式重构建、发布安全扫描及两组隔离 EXE 12 秒启动均通过；多倍率快捷键弹窗源码居中已由用户确认。下一步仅剩显式暂存本轮相关源码、测试与文档后提交并推送当前分支。正式 EXE 下的 9/31 窗、真实收藏夹、刷新/账号管理弹窗和快捷键注册触发仍待用户最终实机验证。

目标版本：`v1.4.20`。

## v1.4.20 Implementation result

- 根目录优先持久化 GUID 全树唯一恢复；无 GUID 时按名称唯一迁移；旧下标不再生成伪 GUID。
- 根不存在时，仅在父节点明确且用户确认后于同一事务创建并绑定。
- 新增“同步现有链接到收藏夹”，不执行 HTTP/Playwright，直接复用已保存链接。
- Focused 104 项通过；full suite `582 run, 565 passed, 17 skipped, 0 failed`。
- `py_compile`、`compileall`、`git diff --check`、32 位源码启动、TIMER 哈希和保护备份哈希核对通过。

本轮只处理两个问题：

1. 刷新地址后 Edge 收藏夹大量成对重复；
2. 直登账号管理首次或重新导入账号后变成未参与，并且当前只能逐个加入。

## 一、收藏夹重复修复

### 已知事实

- 当前 `BookmarkUrlUpdater.update()` 每成功一个账号就重新读取、备份并完整替换一次 Edge `Bookmarks`。
- 当前版本新增了“路径找不到时自动创建目录和最终收藏项”；早期版本路径不存在时只返回 `bookmark_not_found`。
- 本轮实机日志中每个账号只刷新和写回一次，但最终连未参与本轮刷新的旧数字收藏项也成对重复。
- 以前版本做过同类刷新，没有出现重复，所以优先按近期写回回归处理；Edge 同步/`Bookmarks.bak` 可能是放大因素，但不能作为唯一归因。

### 修复原则

1. 必须保留用户需要的“导入收藏夹”能力，不能把刷新功能改成永远只写本地直登库。
2. 刷新地址弹窗提供明确选项：`刷新成功后同步/导入收藏夹`。用户勾选后，本批刷新完成时一次性执行收藏夹更新与缺失项导入；取消勾选时仅更新本地直登链接库。该选项应记忆用户上次选择。
3. 收藏夹动作分为两类，但共用同一次整批事务：
   - 已存在且完整路径唯一命中的收藏项：原位更新 URL，保留原 GUID、ID 和其它字段；
   - 完整路径缺失的账号：按账号配置中的明确 `bookmark_path` 导入缺失收藏项，必要时创建缺失分组目录，但只能在已验证的账号根目录内执行。
4. 导入缺失项前必须先生成整批计划并显示摘要：`更新 N、新增 M、冲突 K、跳过 S`。唯一性判断以规范化完整收藏夹路径为准；不同分组下允许同名叶子，例如 `账号/第一层/1` 与 `账号/第二层/1` 均合法。只有同一完整路径出现多个节点、同一父目录出现同名同类型节点、历史 GUID 映射与该完整路径冲突或根目录不一致时，才标记冲突并阻止本批写回。
5. 为程序创建或确认过的收藏项保存稳定映射，例如 `account_key -> bookmark GUID + 规范路径`。后续刷新优先用 GUID、名称和规范路径联合确认原节点；映射存在但 GUID 找不到时不得自动再创建。
6. 依赖预检在批量开始前完成。缺少 `requests` 属于环境错误，直接提示并停止；不得自动弹出 Playwright 浏览器。
7. `auto` 模式只有在依赖完整且真实 HTTP 登录失败时才允许建议回退 Playwright；回退前必须由用户明确确认，不能静默打开浏览器。
8. 收藏夹同步/导入采用整批处理：
   - 先收集本批所有成功直登 URL；
   - 一次读取 Bookmarks；
   - 一次生成更新/新增/冲突计划；
   - 一次唯一性校验；
   - 一次原始备份；
   - 一次临时文件写入；
   - 一次原子替换。
9. 创建缺失分组或收藏项时，必须保证父路径逐级唯一。不同父目录下允许同名收藏项；例如每个分组都可以有名称为 `1` 的账号。只有同一父目录存在同名同类型节点、同名文件夹与 URL 类型冲突，或同一规范化完整路径出现多个节点时才停止，不能为了完成导入而在同一路径追加重复节点。
10. 根目录身份不能只依赖 `roots/bookmark_bar/children/N`。应保存并校验：
   - 根目录 GUID；
   - 目录名称；
   - 结构路径；
   三者不一致时停止写回。
11. 写入前检查：
   - 同父目录同名节点；
   - 完整路径多个匹配；
   - GUID 冲突；
   - 根目录漂移；
   - Bookmarks 在操作期间被外部修改。
12. 开始处理时记录原始文件哈希；最终替换前再次比较，若文件已变化则放弃写入，防止与 Edge/同步并发覆盖。
13. 写入后重新读取并验证每个目标路径严格只有一个节点且 URL 正确；验证失败恢复原文件。
14. 检测浏览器运行时禁止写回；同步状态无法安全确认时也应跳过并提示“仅本地链接已更新”。
15. 为当前污染数据提供独立的“收藏夹检查/恢复”工具：
   - 默认只读、只预览；
   - 对比当前 Bookmarks、Bookmarks.bak 和选定备份；
   - 输出重复节点的父路径、名称、GUID、URL、来源和建议保留项；
   - 不自动按名称删一半；
   - 恢复前再次备份当前文件；
   - 只有用户明确确认后才执行恢复或去重。
16. 保留并保护：
   - `上号器数据/backups/Bookmarks_Edge_Default_20260712_171250_423586.json`
   - `上号器数据/backups/Bookmarks_Edge_Default_20260712_172302_602736.json`

### 收藏夹测试

至少覆盖：

- 缺少 requests 时批量在第一条账号前停止，不打开 Playwright；
- 勾选“刷新后同步/导入收藏夹”时，刷新完成后执行一次整批事务；取消勾选时只更新本地直登库；
- 已存在路径只更新 URL 并保留原 GUID/ID；
- 缺失路径在父目录和账号名称均无冲突时可安全导入；
- 不同分组下同名账号允许导入；只有同一完整路径重复、同一父目录同名同类型、历史 GUID 与该完整路径冲突或父路径不唯一时阻止整批写入；
- 程序创建的收藏项在第二次刷新时必须命中原 GUID，不能再次新增；
- 整批 49 条只执行一次文件替换；
- 路径冲突时整批不写；
- 根 GUID/名称/结构路径不一致时整批不写；
- 外部修改哈希变化时放弃替换；
- 写后严格唯一性验证；
- 保存失败恢复原文件；
- 停止任务后不再产生后续收藏夹写入；
- 预览工具不修改真实文件；
- 不复发旧数字收藏项整套复制。

## 二、直登账号管理参与状态修复

### 已知根因

`LoginAccountRosterStore.reconcile()` 当前会：

- 把不在当前账号库中的 `_states` 删除；
- 但 `_seen` 永久保留历史 key；
- 同一个账号删除后重新导入时，状态已被删但 key 仍在 `_seen`；
- 新建状态使用 `included = key not in _seen`，因此被误设为 `False/未参与`。

GUI 当前 `Treeview(selectmode="browse")` 只能单选，加入/移除按钮也只处理一条记录，所以大量账号需要逐个点击。

### 修复要求

1. 新账号默认参与上号。
2. 删除后重新导入同一账号时，应恢复该账号最近一次明确参与状态；如果没有明确状态，默认参与。
3. 不再使用 `_seen` 决定默认 `included=False`。
4. 账号暂时从刷新账号库消失时，不要立刻丢弃其参与状态；保留稳定 key 对应的状态，以便重新导入时恢复。
5. 旧 `seen_keys` 配置兼容读取，但不再影响默认参与判断；后续保存可逐步迁移到新 schema。
6. 直登账号管理表格改为多选：`selectmode="extended"`。
7. 增加批量操作：
   - `选中账号加入上号列表`；
   - `选中账号移出上号列表`；
   - `当前筛选全部加入`；
   - `当前筛选全部移出`；
   - 可保留单账号操作，但不能要求逐个点。
8. 批量变更应一次更新内存、一次原子保存、一次刷新表格，不要每条保存一次。
9. 当前筛选包括状态筛选与分组筛选；“当前筛选全部加入”只作用于当前可见结果。
10. 批量操作前显示影响数量；操作后状态栏或日志显示成功数量。
11. 不删除刷新账号、不删除直登链接，只修改是否参与上号和顺序。
12. 首次导入 49 个账号后，默认应全部为已参与；用户仍可批量移除不需要的账号。

### 账号管理测试

至少覆盖：

- 首次导入账号默认全部参与；
- 删除账号后重新导入，恢复最近一次明确状态；
- 没有历史状态时默认参与；
- 旧 `seen_keys` 不再把账号误设为未参与；
- 多选加入/移除；
- 当前筛选全部加入/移除；
- 批量操作只保存一次；
- 关闭重开后参与状态保持；
- 排序和参与状态互不破坏；
- 主界面重新加载后参与账号数量正确。

## 三、版本与边界

- 用户授权后版本升为 `v1.4.19`。
- 同步 `version.py`、窗口标题、README、发布断言、实机记录、`.ai-bridge/agent-status.md`。
- 不在本轮切换 64 位架构；32/64 位迁移单独立项。
- 不修改加速器核心倍率脚本，不修改 9/31 窗排列、HWND/PID/CDP 归属逻辑。
- 不自动删除用户现有重复收藏夹。
- 不执行 `git reset`、`git checkout`，不清理无关工作区文件。
- 完成源码、focused tests、完整测试和文档同步后停止，暂不打包正式 EXE。

完成后等待实机验证：

- 默认刷新不再改浏览器收藏夹；
- 显式同步整批只写一次且不产生重复；
- 缺 requests 不弹浏览器；
- 新导入账号默认全部参与；
- 多选和当前筛选批量加入/移除正常。

## Implementation result (2026-07-12)

- 版本已升至 `v1.4.19`；收藏夹改为整批单次原子写入，账号参与状态与批量操作已完成。
- Focused：收藏夹 17、账号参与 6、刷新 GUI 18、CLI/回退 10、检查恢复 2，全部通过。
- Full suite：`576 run, 559 passed, 17 skipped, 0 failed`。
- `py_compile`、`compileall`、`git diff --check` 均通过；32 位 `D:\Dev\Python\Python314-32\python.exe main.py` 启动 6 秒仍存活。
- `TIMER_HOOK_SCRIPT` 保持长度 `23657`、SHA-256 `0c65cbbd7eddd969225668f740a7b16ada1ff17f281b3c3b9efb6620ddc544a5`。
- 未写入真实 Bookmarks，未动受保护备份，未打包 EXE；自动化通过不等于实机通过。

## Implementation contract

- Work from this plan in small, reviewable steps.
- Keep edits scoped to the requested task and existing project conventions.
- Run focused verification before handing work back.
- Update .ai-bridge/agent-status.md with files touched, checks run, results, blockers, and review notes.
- Save the final review diff to .ai-bridge/implementation-diff.patch when practical.
- Append notable execution events to .ai-bridge/execution-log.jsonl when the implementation agent supports logging.

---

# 开始实施 v1.4.19

Updated: 2026-07-12T10:07:19.790Z
Workspace: D:\Ai\codex\上号器
Target agent: Codex (codex)

## Plan

## 用户授权执行（2026-07-12）

用户已明确授权开始修复。现在按本文件前述完整计划及 `docs/上号器_v1.4.19_收藏夹安全导入与账号批量参与修复计划_20260712.md` 实施。

实施要求：
- 先读取 `AGENTS.md`、相关 workspace Skills、正式计划文档和实机测试记录；
- 只处理收藏夹安全批量导入/更新、HTTP 依赖预检/显式 Playwright 回退、直登账号默认参与与批量操作；
- 版本升至 v1.4.19，并同步代码、测试、README、实机记录和状态文档；
- 保留 9/31 窗、HWND/PID/CDP、排列、端口、加速器与 TIMER_HOOK_SCRIPT 既有稳定逻辑；
- 不自动清理或恢复用户真实收藏夹；不覆盖 17:12、17:23 两份备份；
- 完成 focused tests、完整测试、源码启动验证和文档同步后停止；
- 不打包正式 EXE。

## Implementation contract

- Work from this plan in small, reviewable steps.
- Keep edits scoped to the requested task and existing project conventions.
- Run focused verification before handing work back.
- Update .ai-bridge/agent-status.md with files touched, checks run, results, blockers, and review notes.
- Save the final review diff to .ai-bridge/implementation-diff.patch when practical.
- Append notable execution events to .ai-bridge/execution-log.jsonl when the implementation agent supports logging.
