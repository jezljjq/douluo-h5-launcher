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

