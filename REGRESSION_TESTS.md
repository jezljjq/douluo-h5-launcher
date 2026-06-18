# 防回归测试说明

本项目已经多次出现旧问题回归。以后任何修复都必须把对应历史问题固化到测试里。

## 必须执行的命令

提交、push、打包前必须执行：

```powershell
python -m compileall -q douluo_launcher main.py
python -m unittest discover -s tests -v
```

如果任一命令失败：

- 禁止提交
- 禁止 push
- 禁止打包
- 必须先修复失败原因，再重新运行完整命令

## 测试文件职责

| 文件 | 职责 |
|------|------|
| `tests/test_window_slot_regression.py` | 历史窗口槽位、串行语义、表格列、动态分组事故的显式防回归测试 |
| `tests/test_window_manager.py` | 窗口槽位底层数据结构、profile、兼容性、保存与修复逻辑、严格窗口识别过滤 |
| `tests/test_gui_group_settings.py` | 全部串行 / 当前层串行 run_plan、分组设置、表格列顺序、客户模式显示文案、收藏候选/账号目录绑定、游戏路径拖拽处理 |
| `tests/test_config.py` | 收藏夹读取、动态分组、窗口号映射、配置合并 |
| `tests/test_bookmark_discovery.py` | Edge/Chrome Bookmarks 自动扫描、账号目录候选、直接链接和 root path 兼容 |
| `tests/test_path_utils.py` | 游戏路径 exe/lnk/目录解析、drop 路径解析 |
| `tests/test_main_startup.py` | GUI 启动权限策略，防止自动管理员提权破坏资源管理器拖拽 |
| `tests/test_automation_helpers.py` | 通行证识别、Playwright 路径、Dm helper、登录状态判断 |
| `tests/test_dm_client.py` | Dm 坐标和窗口标题匹配 |

## 历史问题到测试映射

| 历史问题 | 主测试 |
|----------|--------|
| 槽位不完整覆盖问题 | `test_incomplete_30_windows_cannot_overwrite_31_slot_profile` |
| 修复窗口不能要求重新生成槽位 | `test_repair_missing_slot_updates_only_target_slot` |
| 新会话 0 窗口启动问题 | `test_new_session_auto_arrange_does_not_validate_old_profile` |
| 9 窗口 / 31 窗口 profile 混用问题 | `test_profile_9_row_count_cannot_restore_31_fixed_layout` |
| 批量启动重复开窗口问题 | `test_batch_launch_is_blocked_when_target_windows_already_exist` |
| 全部串行 / 当前层串行语义问题 | `test_all_serial_plan_reports_missing_windows_before_any_run` |
| 表格列错位问题 | `test_table_values_stay_aligned_with_declared_columns` |
| 收藏夹动态分组问题 | `test_bookmark_custom_group_order_and_include_in_all_are_independent` |
| 配置区路径和收藏夹写死问题 | `test_lnk_resolves_to_target_exe`, `test_invalid_file_uses_customer_friendly_message`, `test_scans_edge_default_profile1_and_chrome_default`, `test_root_name_not_account_is_detected_and_loadable`, `test_bookmark_file_candidate_label_hides_raw_path`, `test_game_program_status_uses_customer_text` |
| 收藏候选与账号目录错配问题 | `test_bookmark_root_candidate_must_belong_to_current_bookmark_file`, `test_empty_accounts_do_not_show_hardcoded_first_layer`, `test_single_loaded_group_defaults_to_that_group`, `test_same_named_directories_are_loaded_by_root_path_not_name` |
| 游戏路径拖拽闪退和管理员权限阻断问题 | `test_raw_native_game_path_drag_drop_is_disabled_to_avoid_tk_crash`, `test_game_program_hint_reflects_tkinterdnd2_drag_support`, `test_game_path_drop_uses_first_dropped_path_and_drop_source`, `test_drop_invalid_file_uses_drag_wording`, `test_gui_startup_does_not_auto_elevate_so_file_drop_works`, `test_apply_game_path_input_saves_resolved_exe_not_lnk`, `test_game_program_input_and_status_share_same_saved_path` |
| 辅助软件标题误识别为游戏窗口 / 编号后缀被误过滤 / 标题模板写死 / SetWindowPos 裸错误码 | `test_build_title_template_pattern_escapes_literal_text`, `test_dynamic_title_template_controls_detection`, `test_is_game_window_uses_strict_title_and_excludes_helpers`, `test_is_game_window_filters_by_configured_game_exe_path`, `test_process_mismatch_does_not_reject_numbered_title_with_matching_size`, `test_31_game_windows_plus_helper_counts_as_31`, `test_31_scan_login_windows_plus_helper_counts_as_31_with_process_mismatch`, `test_window_detection_diagnostics_include_reject_reason`, `test_tile_game_windows_reports_access_denied_diagnostics`, `test_regenerate_slots_does_not_save_when_move_fails` |
| 通行证按钮点击后弹窗未出现却继续输入 | `test_passport_button_cache_success_waits_for_dialog_before_input`, `test_passport_button_cache_failure_clears_cache_and_retemplates`, `test_passport_button_two_failed_clicks_raise_without_input`, `test_fast_dm_chain_path_is_disabled_until_dialog_is_verified`, `test_passport_button_click_must_be_inside_viewport` |

## 新 bug 修复流程

1. 先把 bug 写入 [ERROR_HISTORY.md](ERROR_HISTORY.md)。
2. 先补或更新失败场景测试。
3. 再修改代码让测试通过。
4. 更新 [REGRESSION_TESTS.md](REGRESSION_TESTS.md) 的映射。
5. 运行完整打包前检查命令。

没有测试的修复，不算完成。
