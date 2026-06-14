# 历史回归问题台账

本文件记录项目已经踩过、以后禁止回归的问题。每个问题都必须有文档规则、自动化测试和打包前检查覆盖。

核心规则：

- 每修一个 bug，必须补一条或更新一条回归测试。
- 没有回归测试的修复，不算完成。
- 回归测试失败时，禁止提交、禁止 push、禁止打包。
- 禁止把旧失败方案当作“重新尝试”继续开发，除非用户明确要求重新评估。

## 1. 槽位不完整覆盖问题

历史问题：

目标窗口数是 31，但当前只识别到 30 个窗口时，程序允许“重新生成槽位”或“刷新槽位映射”，导致 30 个窗口覆盖 31 个槽位，slot 29 丢失。

防回归规则：

- 当前窗口数 != `target_window_count` 时，禁止重新生成槽位。
- 当前窗口数 != `target_window_count` 时，禁止刷新槽位映射。
- 底层保存槽位函数必须支持 `expected_count` 硬校验。
- 修复窗口允许当前窗口数少 1，但只能修复目标 slot，不能覆盖全量槽位。

测试：

- `tests/test_window_slot_regression.py::WindowSlotRegressionTests::test_incomplete_30_windows_cannot_overwrite_31_slot_profile`
- `tests/test_window_manager.py::WindowManagerTests::test_save_current_windows_as_slots_blocks_expected_count_mismatch`
- `tests/test_window_manager.py::WindowManagerTests::test_refresh_window_slots_blocks_expected_count_mismatch`

## 2. 修复窗口不能要求重新生成槽位

历史问题：

窗口 29 被误关后，点击“修复窗口”，程序提示映射不存在，让用户重新生成槽位，最终污染槽位。

防回归规则：

- 修复 slot 时应优先读取当前 profile 槽位。
- 如果槽位缺失，应尝试从备份、legacy 槽位文件、当前窗口标题或固定 layout 参数推导坐标。
- 可推导时必须继续修复，不能要求用户重新生成槽位。
- 修复窗口只更新目标 slot，不更新整套槽位。

测试：

- `tests/test_window_slot_regression.py::WindowSlotRegressionTests::test_repair_missing_slot_updates_only_target_slot`
- `tests/test_window_manager.py::WindowManagerTests::test_resolve_repair_slot_uses_recent_backup_before_fixed_config`
- `tests/test_window_manager.py::WindowManagerTests::test_resolve_repair_slot_uses_fixed_config_without_writing_file`

## 3. 新会话 0 窗口启动问题

历史问题：

全部窗口关闭后重新打开 31 个，程序仍受旧槽位 profile 影响，导致不自动排列或弹 profile 不一致。

防回归规则：

- 当前 H5 窗口数为 0 时，批量启动视为 `new_session`。
- `new_session` 应忽略旧槽位阻塞。
- 启动完成后按当前 UI 参数排列、编号、保存新 profile。
- 不能弹 profile 不一致阻止新会话。

测试：

- `tests/test_window_slot_regression.py::WindowSlotRegressionTests::test_new_session_auto_arrange_does_not_validate_old_profile`

## 4. 9 窗口 / 31 窗口 profile 混用问题

历史问题：

笔记本 9 窗口或测试 profile 生成的槽位，被台式 31 窗口误用，导致排列错乱。

防回归规则：

- profile 必须包含 screen、dpi、scale、target_window_count、layout_mode、per_row、window_size、start、offset 等关键参数。
- profile 不一致时禁止恢复旧槽位。
- 不能用 9 窗口槽位恢复 31 窗口。
- 不能用 `row_count` profile 恢复 `fixed` profile。

测试：

- `tests/test_window_slot_regression.py::WindowSlotRegressionTests::test_profile_9_row_count_cannot_restore_31_fixed_layout`
- `tests/test_window_manager.py::WindowManagerTests::test_profile_slot_path_separates_window_count_and_mode`
- `tests/test_window_manager.py::WindowManagerTests::test_check_window_slots_compatibility_blocks_slot_count_mismatch`

## 5. 批量启动重复开窗口问题

历史问题：

当前已有 31 个窗口时，点击批量启动又打开 31 个，变成 62 个。

防回归规则：

- 批量启动前必须检测当前桌面 H5 窗口数量。
- 当前窗口数 >= 目标打开数量时，禁止继续批量启动。
- 提示用户使用排列、修复、重新生成槽位，而不是追加启动。

测试：

- `tests/test_window_slot_regression.py::WindowSlotRegressionTests::test_batch_launch_is_blocked_when_target_windows_already_exist`

## 6. 全部串行 / 当前层串行语义问题

历史问题：

用户在“存钻”层级点击全部串行，以为运行当前层，但程序去跑所有启用分组，最后找窗口 10。

防回归规则：

- 当前层串行：只运行当前层级。
- 全部串行：运行全部串行分组设置中启用的分组。
- 当前层级不是“全部”时点击全部串行，必须提示语义差异。
- 运行前必须生成 run_plan 并提前检查缺少窗口。
- 不能跑到一半才报窗口 10 不存在。

测试：

- `tests/test_window_slot_regression.py::WindowSlotRegressionTests::test_all_serial_plan_reports_missing_windows_before_any_run`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_current_group_plan_for_cunduan_uses_windows_1_to_9_only`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_all_serial_plan_reports_all_missing_windows_before_running`

## 7. 表格列错位问题

历史问题：

新增“参与全部串行”列后，Treeview `values` 顺序未同步，导致参与全部串行列显示通行证、本次通行证列显示成功、状态列显示耗时。

防回归规则：

- Treeview 列定义必须统一。
- insert values 顺序必须和 columns 一致。
- 更新状态、通行证、耗时时必须使用统一列定义或列名索引。
- UI 表格不能作为业务核心数据源。

测试：

- `tests/test_window_slot_regression.py::WindowSlotRegressionTests::test_table_values_stay_aligned_with_declared_columns`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_account_table_values_match_declared_column_order`

## 8. 收藏夹动态分组问题

历史问题：

程序写死第一层到第四层，导致“存钻”等目录读取不到。

防回归规则：

- 账号目录下真实子目录必须动态读取。
- 自定义分组如“存钻”必须能读取。
- 自定义账号标题如 `z1`、`z2` 不要求纯数字。
- 自定义分组按收藏夹原始顺序显示。
- `include_in_all` 只影响全部串行启用范围，不影响手动运行某个分组。

测试：

- `tests/test_window_slot_regression.py::WindowSlotRegressionTests::test_bookmark_custom_group_order_and_include_in_all_are_independent`
- `tests/test_config.py::ConfigTests::test_load_bookmarks_supports_dynamic_custom_groups_in_original_order`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_split_all_serial_accounts_only_enables_include_in_all_groups`

## 9. 配置区路径和收藏夹写死问题

历史问题：

客户不知道 `X5Game.exe`、桌面快捷方式、浏览器 `Bookmarks` 文件和账号目录的真实位置；程序如果继续要求手动输入 `账号` 根目录，会导致普通客户无法配置。

防回归规则：

- 游戏路径不能写死，必须支持 exe、lnk 快捷方式和游戏安装目录。
- `.lnk` 必须解析真实目标 exe，不能把 `.lnk` 本身保存为游戏路径。
- 收藏夹文件路径不能写死；Edge / Chrome `Default` 和 `Profile *` 只能作为候选。
- 账号目录不能强制叫 `账号`；必须扫描 Bookmarks 内所有包含有效游戏链接的目录。
- 游戏链接直接放在收藏栏或其它收藏夹时必须支持。
- 自动扫描不能静默覆盖用户保存选择；多个候选时必须由用户选择。
- 主界面必须保持客户模式：游戏程序、自动查找收藏夹、收藏夹候选、账号目录、读取账号。
- `Bookmarks` 原始路径、`bookmark_root_path`、兼容目录名和自动化设置路径必须放入默认折叠的高级配置。
- 收藏夹候选和账号目录候选必须显示客户可读文本，禁止把原始路径或内部 JSON root path 放在主界面下拉里。

测试：

- `tests/test_path_utils.py::PathUtilsTests::test_exe_path_is_accepted`
- `tests/test_path_utils.py::PathUtilsTests::test_lnk_resolves_to_target_exe`
- `tests/test_path_utils.py::PathUtilsTests::test_lnk_target_missing_is_rejected`
- `tests/test_path_utils.py::PathUtilsTests::test_lnk_target_not_exe_is_rejected`
- `tests/test_path_utils.py::PathUtilsTests::test_folder_finds_x5game_exe`
- `tests/test_path_utils.py::PathUtilsTests::test_folder_without_x5game_exe_is_rejected`
- `tests/test_path_utils.py::PathUtilsTests::test_invalid_file_uses_customer_friendly_message`
- `tests/test_bookmark_discovery.py::BookmarkDiscoveryTests::test_scans_edge_default_profile1_and_chrome_default`
- `tests/test_bookmark_discovery.py::BookmarkDiscoveryTests::test_multiple_bookmark_candidates_do_not_silently_override_saved_path`
- `tests/test_bookmark_discovery.py::BookmarkDiscoveryTests::test_direct_links_on_bookmark_bar_are_detected`
- `tests/test_bookmark_discovery.py::BookmarkDiscoveryTests::test_direct_links_on_other_bookmarks_are_detected`
- `tests/test_bookmark_discovery.py::BookmarkDiscoveryTests::test_root_name_not_account_is_detected_and_loadable`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_bookmark_file_candidate_label_hides_raw_path`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_game_program_status_uses_customer_text`

## 10. 收藏候选与账号目录错配问题

历史问题：

切换“收藏候选”后，账号目录下拉仍保留上一个 Bookmarks 文件扫描出的目录，导致界面出现 `Chrome - Default` 配 `Edge` 的 `收藏栏 / 账号 / 存钻`。读取时又退回按最后目录名“存钻”搜索，最终在错误的 Chrome Bookmarks 中找根目录，运行区还继续显示上一次成功加载的第一层账号。

防回归规则：

- 切换收藏候选 Bookmarks 文件时，必须清空账号目录候选、当前账号目录选择、`bookmark_root_path`、`bookmark_root_display_name` 和旧账号列表。
- 每个账号目录候选必须绑定自己的 `bookmark_file_path` 和结构化 `root_path`。
- 读取账号前必须校验账号目录候选所属 Bookmarks 文件与当前收藏候选一致。
- 读取账号必须使用结构化 `root_path` 定位目录，禁止只用显示文本最后一段目录名，例如“存钻”。
- 读取失败时必须清空或明确标记旧账号列表，不能让用户误以为下方第一层数据属于当前选择。
- 账号加载成功后，运行区层级和账号下拉必须来自当前账号数据；当前只读取 `存钻` 时，不能继续显示 `第一层`。

测试：

- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_bookmark_root_candidate_must_belong_to_current_bookmark_file`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_empty_accounts_do_not_show_hardcoded_first_layer`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_single_loaded_group_defaults_to_that_group`
- `tests/test_bookmark_discovery.py::BookmarkDiscoveryTests::test_same_named_directories_are_loaded_by_root_path_not_name`

## 11. 游戏路径拖拽闪退与管理员权限阻断

历史问题：

将桌面 `.lnk` 快捷方式拖进“游戏程序”输入框后，程序直接闪退。根因是原生 `WM_DROPFILES` 子类化 Tk / ttk 控件不稳定，崩溃发生在底层窗口过程，Python 无法正常捕获异常。

后续独立 POC 已验证公开库 `tkinterdnd2` 可以稳定接收拖入路径并解析 `.lnk -> E:\Program Files\DLH5\X5Game.exe`。主程序仍拖不进去的根因是 `main.py` 启动时自动管理员提权，Windows UIPI 会阻止普通资源管理器向管理员权限窗口拖入文件。

防回归规则：

- 禁止默认启用原生 `WM_DROPFILES` 游戏路径拖拽。
- 当前正式拖拽实现使用 `tkinterdnd2`，禁止回退到会闪退的原生 `WM_DROPFILES`。
- GUI 默认不得启动时自动管理员提权，否则普通资源管理器拖拽会被系统权限隔离拦截。
- 客户主路径支持拖入桌面游戏图标、`.lnk`、`.exe` 和游戏安装目录；“选择游戏图标/程序”按钮作为兜底。
- `.lnk` 必须解析 `TargetPath`，保存真实 exe，禁止保存 `.lnk`。
- 输入框和“已识别游戏程序”状态必须来自同一份路径，不能一个空、一个显示已识别。
- PyInstaller 打包必须收集 `tkinterdnd2` 资源，否则 exe 可能无法注册拖拽。

测试：

- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_raw_native_game_path_drag_drop_is_disabled_to_avoid_tk_crash`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_game_program_hint_reflects_tkinterdnd2_drag_support`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_game_path_drop_uses_first_dropped_path_and_drop_source`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_drop_invalid_file_uses_drag_wording`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_game_program_input_and_status_share_same_saved_path`
- `tests/test_gui_group_settings.py::GuiGroupSettingsTests::test_game_program_empty_path_has_empty_input_and_unselected_status`
- `tests/test_path_utils.py::PathUtilsTests::test_lnk_resolves_to_target_exe`
- `tests/test_main_startup.py::MainStartupTests::test_gui_startup_does_not_auto_elevate_so_file_drop_works`

## 12. 辅助软件标题误识别为游戏窗口

历史问题：

桌面同时存在 31 个真实 `X5Game.exe` 游戏窗口和 1 个辅助软件窗口。辅助软件标题以 `斗罗大陆H5` 开头，例如 `斗罗大陆H5 电脑版全自动辅助...`。旧逻辑用 `title.startswith("斗罗大陆")`、`"斗罗大陆H5" in title` 等模糊标题规则识别窗口，导致辅助软件被算成第 32 个窗口，排列窗口时报 `目标 31，当前 32`。

防回归规则：

- 窗口管理、槽位保存、槽位刷新、重排、补位、关闭、批量启动前检测、串行运行前预检必须统一使用 `douluo_launcher.window_manager.is_game_window()` / `list_game_windows()`。
- 配置了游戏程序路径时，必须读取 hwnd 所属进程 exe 路径，只有进程路径等于配置的 `X5Game.exe` 才能进入游戏窗口候选。
- 编号窗口标题只允许严格匹配 `^斗罗大陆H5-(\d+)号$`。
- 未编号窗口只允许在显式 `allow_unnumbered=True` 时识别精确标题 `斗罗大陆H5`。
- 标题包含 `辅助`、`全自动辅助`、`任务开关`、`公共设置`、`日常设置`、`代理设置`、`上号器`、`工具` 时必须排除。
- 禁止回退到包含匹配、前缀匹配或从标题中任意提取数字。

测试：

- `tests/test_window_manager.py::WindowManagerTests::test_is_game_window_uses_strict_title_and_excludes_helpers`
- `tests/test_window_manager.py::WindowManagerTests::test_is_game_window_filters_by_configured_game_exe_path`
- `tests/test_window_manager.py::WindowManagerTests::test_31_game_windows_plus_helper_counts_as_31`
