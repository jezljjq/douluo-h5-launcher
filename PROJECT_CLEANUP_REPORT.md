# PROJECT_CLEANUP_REPORT

生成时间：2026-07-07  
范围：只读清点当前项目目录，不实际删除任何文件。  
约束：所有“建议删除”仅表示后续人工确认后的清理候选，本报告不执行删除、移动、归档或回滚。

## 结论摘要

- 当前主要源码入口是 `main.py`，主包是 `douluo_launcher/`。
- 当前发布脚本 `scripts/build_exe.ps1` / `scripts/build_exe_32bit.ps1` 直接用 PyInstaller 参数构建 `main.py`，没有直接调用 spec 文件。
- `tests/test_release_packaging.py` 会读取 `Launcher.spec`，且 `Launcher.spec` 使用 `automation_settings.template.json`，因此它目前属于发布校验相关文件，建议保留并人工确认后再决定是否改为唯一 spec。
- `.spec`、`ShangHaoQi.spec`、`上号器.spec`、`斗罗大陆H5上号器.spec` 仍引用 `automation_settings.json`，有打包私有配置的风险，建议归档或废弃前人工确认。
- `dist/` 下存在多个历史发布输出和 backup 目录，属于最明显的清理候选，但可能包含可回退版本，删除前需要人工确认。

## 1. Python 源码文件清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `main.py` | 主入口 | 是 | 否 | 否 | GUI 启动入口，发布脚本构建目标 | 高 | 否 |
| `dm_click_helper.py` | 运行时辅助进程 | 是 | 否 | 否 | 32 位大漠点击辅助，发布脚本会复制/构建 | 高 | 否 |
| `douluo_launcher/__init__.py` | 包入口 | 是 | 否 | 否 | Python 包标识 | 中 | 否 |
| `douluo_launcher/automation.py` | 核心自动化 | 是 | 否 | 否 | 前台登录、OCR、Playwright 关键逻辑 | 高 | 否 |
| `douluo_launcher/background_capability.py` | 后台能力报告 | 是 | 否 | 否 | 后台模式能力检查相关 | 中 | 否 |
| `douluo_launcher/background_login.py` | 后台登录 | 是 | 否 | 否 | 后台登录实验功能 | 高 | 否 |
| `douluo_launcher/client_batch_store.py` | 客户端批次持久化 | 是 | 否 | 否 | P5/P6 批次恢复与修复核心 | 高 | 否 |
| `douluo_launcher/client_cdp.py` | CDP 工具 | 是 | 否 | 否 | 客户端直登和加速总控依赖 | 高 | 否 |
| `douluo_launcher/client_direct_login.py` | 客户端直登 | 是 | 否 | 否 | 客户端直登主流程 | 高 | 否 |
| `douluo_launcher/client_speed_panel.py` | 加速总控 | 是 | 否 | 否 | P6 加速面板逻辑 | 高 | 否 |
| `douluo_launcher/config.py` | 配置加载 | 是 | 否 | 否 | 账号、设置、路径初始化 | 高 | 否 |
| `douluo_launcher/dm_client.py` | 大漠/窗口辅助 | 是 | 否 | 否 | 截图、窗口识别、坐标转换 | 高 | 否 |
| `douluo_launcher/gui.py` | Tkinter 主 GUI | 是 | 否 | 否 | 当前主界面和批量流程核心 | 高 | 否 |
| `douluo_launcher/gui_pyside6.py` | PySide6 旧/实验 GUI | 否 | 是 | 否 | 未被当前代码 import，可能是历史 UI 实验 | 中 | 是 |
| `douluo_launcher/path_utils.py` | 路径工具 | 是 | 否 | 否 | 游戏程序路径解析和拖放路径解析 | 中 | 否 |
| `douluo_launcher/qt_styles.py` | Qt 样式 | 否 | 是 | 否 | 与 `gui_pyside6.py` 相关，未被当前代码 import | 中 | 是 |
| `douluo_launcher/version.py` | 版本号 | 是 | 否 | 否 | 发布测试和界面版本依赖 | 中 | 否 |
| `douluo_launcher/window_manager.py` | 窗口管理 | 是 | 否 | 否 | 窗口枚举、排列、槽位核心 | 高 | 否 |
| `douluo_launcher/window_manager_settings.py` | 窗口管理设置 | 是 | 否 | 否 | 窗口管理参数持久化 | 中 | 否 |
| `douluo_launcher/window_operator.py` | 窗口操作抽象 | 是 | 否 | 否 | 前台/后台窗口操作统一接口 | 高 | 否 |
| `debug_background/live_keepalive_runner.py` | 调试源码 | 否 | 是 | 否 | 未被 import，属于后台调试目录 | 中 | 是 |

## 2. 测试文件清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `tests/test_automation_helpers.py` | 单元测试 | 是 | 否 | 否 | 自动化/OCR 工具回归 | 中 | 否 |
| `tests/test_background_capability.py` | 单元测试 | 是 | 否 | 否 | 后台能力报告回归 | 中 | 否 |
| `tests/test_background_login.py` | 单元测试 | 是 | 否 | 否 | 后台登录流程回归 | 高 | 否 |
| `tests/test_background_operator_probe.py` | 单元测试 | 是 | 否 | 否 | 后台探针工具回归 | 中 | 否 |
| `tests/test_bookmark_discovery.py` | 单元测试 | 是 | 否 | 否 | 书签发现逻辑回归 | 中 | 否 |
| `tests/test_client_batch_store.py` | 单元测试 | 是 | 否 | 否 | 批次持久化核心回归 | 高 | 否 |
| `tests/test_client_cdp.py` | 单元测试 | 是 | 否 | 否 | CDP 消息和端口逻辑回归 | 高 | 否 |
| `tests/test_client_direct_login.py` | 单元测试 | 是 | 否 | 否 | 客户端直登核心回归 | 高 | 否 |
| `tests/test_client_speed_panel.py` | 单元测试 | 是 | 否 | 否 | 加速总控回归 | 高 | 否 |
| `tests/test_config.py` | 单元测试 | 是 | 否 | 否 | 配置与用户数据目录回归 | 高 | 否 |
| `tests/test_debug_background_ocr.py` | 单元测试 | 是 | 否 | 否 | 调试 OCR 工具回归 | 中 | 否 |
| `tests/test_dm_client.py` | 单元测试 | 是 | 否 | 否 | 大漠窗口工具回归 | 高 | 否 |
| `tests/test_gui_group_settings.py` | GUI 单元测试 | 是 | 否 | 否 | 当前最大 GUI 回归集，P7 已覆盖 | 高 | 否 |
| `tests/test_live_background_serial_limit2.py` | 工具测试 | 是 | 否 | 否 | live 工具逻辑回归 | 中 | 是 |
| `tests/test_main_startup.py` | 单元测试 | 是 | 否 | 否 | 主入口启动防回归 | 中 | 否 |
| `tests/test_path_utils.py` | 单元测试 | 是 | 否 | 否 | 路径解析回归 | 中 | 否 |
| `tests/test_release_packaging.py` | 发布测试 | 是 | 否 | 否 | v1.3.0、Launcher.spec、模板配置校验 | 高 | 否 |
| `tests/test_window_manager.py` | 单元测试 | 是 | 否 | 否 | 窗口管理核心回归 | 高 | 否 |
| `tests/test_window_operator.py` | 单元测试 | 是 | 否 | 否 | 窗口操作抽象回归 | 高 | 否 |
| `tests/test_window_slot_regression.py` | 回归测试 | 是 | 否 | 否 | 窗口槽位事故防回归 | 高 | 否 |

## 3. 文档文件清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `README.md` | 主文档 | 是 | 否 | 否 | 用户和开发入口文档 | 高 | 否 |
| `BUILD.md` | 发布文档 | 是 | 否 | 否 | 当前 v1.3.0 打包说明 | 高 | 否 |
| `PROJECT_STRUCTURE.md` | 结构说明 | 是 | 否 | 否 | 项目结构参考 | 中 | 否 |
| `DEVELOPMENT_RULES.md` | 开发规则 | 是 | 否 | 否 | 防回归和安全规则 | 高 | 否 |
| `REGRESSION_TESTS.md` | 回归说明 | 是 | 否 | 否 | 回归测试索引 | 高 | 否 |
| `BACKGROUND_CAPABILITY.md` | 能力文档 | 是 | 否 | 否 | 后台能力说明 | 中 | 否 |
| `CLICK_SOLUTION.md` | 方案文档 | 是 | 否 | 否 | 点击、停止清理关键历史 | 高 | 否 |
| `DEBUG_IMAGE_POLICY.md` | 调试图片策略 | 是 | 否 | 否 | debug_ocr 清理策略 | 中 | 否 |
| `LOG_POLICY.md` | 日志策略 | 是 | 否 | 否 | 日志保留说明 | 中 | 否 |
| `UI_RULES.md` | UI 规则 | 是 | 否 | 否 | UI 调整约束 | 中 | 否 |
| `RUN_MODE.md` | 运行模式 | 是 | 否 | 否 | 前台/后台/直登模式说明 | 中 | 否 |
| `CURRENT_ISSUES.md` | 历史问题 | 否 | 是 | 否 | 历史问题较多，保留价值偏追溯 | 中 | 是 |
| `KNOWN_BUGS.md` | 已知问题 | 否 | 是 | 否 | 可能与当前 README 重复 | 中 | 是 |
| `ERROR_HISTORY.md` | 错误历史 | 否 | 是 | 否 | 历史排障记录，可归档 | 中 | 是 |
| `NEXT_STEPS.md` | 旧下一步 | 否 | 是 | 否 | 可能被 v1.3.0 计划取代 | 中 | 是 |
| `PROJECT_HEALTH_CHECK.md` | 健康检查 | 是 | 否 | 否 | 当前未跟踪但可作为审计输入 | 中 | 是 |
| `BUILD_RELEASE_PROMPT.md` | 发布提示词 | 否 | 是 | 否 | 与 BUILD.md 部分重复 | 低 | 是 |
| `DOC_UPDATE_PROMPT.md` | 文档提示词 | 否 | 是 | 否 | 开发辅助文档 | 低 | 是 |
| `DESIGN.md` | 旧设计 | 否 | 是 | 否 | 历史设计材料 | 低 | 是 |
| `DESIGN_METHOD2.md` | 旧方式二设计 | 否 | 是 | 否 | 历史方式二设计材料 | 低 | 是 |
| `GUI_STATUS_FLOW.md` | 状态流文档 | 否 | 是 | 否 | 可能已被 README/测试覆盖 | 中 | 是 |
| `MILESTONE_FRONTEND_SERIAL.md` | 阶段总结 | 否 | 是 | 否 | 里程碑归档候选 | 低 | 是 |
| `OCR_CROP_ANALYSIS.md` | OCR 分析 | 否 | 是 | 否 | 历史分析文档 | 低 | 是 |
| `OCR_SUCCESS.md` | OCR 成功记录 | 否 | 是 | 否 | 历史验证记录 | 低 | 是 |
| `CLAUDE.md` | 外部助手上下文 | 否 | 是 | 否 | 可能是旧工具上下文，归档前确认 | 中 | 是 |
| `AGENTS.md` | Codex 项目规则 | 是 | 否 | 否 | 当前工作规则文件 | 高 | 否 |
| `上号器_Gemini_UI开发说明.md` | Gemini/旧 UI 文档 | 否 | 是 | 否 | P8 特别点名的旧 UI 文档候选 | 低 | 是 |
| `docs/V1.3.0_RELEASE_PLAN.md` | 发布计划 | 是 | 否 | 否 | 当前 P0-P8 依据 | 高 | 否 |
| `docs/CLIENT_DIRECT_BATCH_PLAN.md` | 客户端批次计划 | 是 | 否 | 否 | 客户端直登批次设计依据 | 中 | 是 |
| `docs/CLIENT_DIRECT_UI_FINAL_PLAN.md` | 客户端 UI 计划 | 是 | 否 | 否 | 客户端直登 UI 收尾依据 | 中 | 是 |
| `docs/CODEX_PROJECT_REVIEW.md` | 项目审查 | 否 | 是 | 否 | 历史接手分析 | 低 | 是 |
| `docs/LAUNCHER_FINAL_MILESTONE.md` | 里程碑 | 否 | 是 | 否 | 阶段总结，可归档 | 低 | 是 |
| `docs/WINDOW_MANAGER_AND_PASSPORT_MILESTONE.md` | 窗口/通行证里程碑 | 否 | 是 | 否 | 阶段总结，可归档 | 低 | 是 |
| `docs/WINDOW_MANAGER_INTEGRATION_PLAN.md` | 窗口管理计划 | 否 | 是 | 否 | 已实现内容较多，可归档前确认 | 中 | 是 |

## 4. 打包脚本清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `scripts/build_exe.ps1` | 发布脚本 | 是 | 否 | 否 | 当前主发布脚本 | 高 | 否 |
| `scripts/build_exe.bat` | 发布脚本入口 | 是 | 否 | 否 | ASCII-only 启动器 | 中 | 否 |
| `scripts/build_exe_32bit.ps1` | 32 位发布脚本 | 是 | 否 | 否 | 32 位 Python/辅助 exe 构建 | 高 | 否 |
| `scripts/build_exe_32bit.bat` | 32 位发布入口 | 是 | 否 | 否 | 32 位构建启动器 | 中 | 否 |
| `scripts/test_qr_decode.py` | 调试脚本 | 否 | 是 | 否 | 未被 import，偏手工调试 | 低 | 是 |

## 5. spec 文件清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `Launcher.spec` | PyInstaller spec | 是 | 否 | 否 | 发布测试读取；使用模板配置；名称和当前 `dist/Launcher` 报错路径相关 | 高 | 是 |
| `.spec` | PyInstaller spec | 否 | 是 | 否 | 隐藏通用文件，仍引用私有 `automation_settings.json` | 高 | 是 |
| `ShangHaoQi.spec` | PyInstaller spec | 否 | 是 | 否 | 旧英文名 spec，仍引用私有配置 | 高 | 是 |
| `上号器.spec` | PyInstaller spec | 否 | 是 | 否 | 旧中文名 spec，疑似历史重复 | 中 | 是 |
| `斗罗大陆H5上号器.spec` | PyInstaller spec | 否 | 是 | 否 | 旧完整中文名 spec，疑似历史重复 | 中 | 是 |

特别确认：当前 `scripts/build_exe.ps1` 直接调用 `pyinstaller @PyInstallerArgs` 并构建 `main.py`，不是调用 `Launcher.spec`。但 `tests/test_release_packaging.py` 明确检查 `Launcher.spec`，所以 `Launcher.spec` 当前仍是发布校验资产。

## 6. 配置模板清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `automation_settings.template.json` | 配置模板 | 是 | 否 | 否 | 发布包应携带模板配置 | 高 | 否 |
| `accounts.sample.csv` | 示例配置 | 是 | 否 | 否 | 用户账号 CSV 示例 | 中 | 否 |
| `bookmarks.sample.json` | 示例配置 | 是 | 否 | 否 | 书签 JSON 示例 | 中 | 否 |
| `requirements.txt` | 依赖清单 | 是 | 否 | 否 | 开发/运行依赖入口 | 高 | 否 |
| `.gitignore` | Git 配置 | 是 | 否 | 否 | 忽略运行时和构建产物 | 高 | 否 |

## 7. 运行时文件清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `automation_settings.json` | 私有运行配置 | 否 | 是 | 否 | 本机配置，不应打入发布包；可能含真实路径 | 高 | 是 |
| `window_manager_settings.json` | 运行配置 | 是 | 否 | 否 | 当前窗口管理参数记忆 | 中 | 是 |
| `window_slots.json` | 运行数据 | 否 | 是 | 否 | 当前机器窗口槽位快照，可能随环境变化 | 中 | 是 |
| `csv_last_path.txt` | 运行状态 | 否 | 是 | 否 | 最近 CSV 路径状态 | 低 | 是 |
| `存钻小号.csv` | 本地账号数据 | 否 | 是 | 否 | 真实/半真实账号数据风险 | 高 | 是 |
| `大号游戏账号.csv` | 本地账号数据 | 否 | 是 | 否 | 真实/半真实账号数据风险 | 高 | 是 |
| `账号密码表.csv` | 本地账号数据 | 否 | 是 | 否 | 真实/半真实账号数据风险 | 高 | 是 |
| `logs/` | 运行日志目录 | 否 | 是 | 否 | 可用于排障，但不是源码资产 | 中 | 是 |
| `slots/` | 运行槽位目录 | 否 | 是 | 否 | 环境相关运行数据 | 中 | 是 |

## 8. 调试脚本清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `tools/background_operator_probe.py` | 调试/探针脚本 | 是 | 否 | 否 | 有测试覆盖，后台输入能力探针 | 中 | 是 |
| `tools/debug_background_ocr.py` | 调试脚本 | 是 | 否 | 否 | 有测试覆盖，后台 OCR 调试 | 中 | 是 |
| `tools/drag_drop_poc.py` | POC 脚本 | 否 | 是 | 否 | 未被 import，拖放实验工具 | 低 | 是 |
| `tools/live_background_serial_limit2.py` | live 调试脚本 | 是 | 否 | 否 | 有测试覆盖，后台串行并发限制验证 | 中 | 是 |
| `tools/live_client_direct_login_once.py` | live 调试脚本 | 否 | 是 | 否 | 未被 import，新直登现场脚本 | 中 | 是 |
| `tools/live_client_direct_login_batch.py` | live 调试脚本 | 否 | 是 | 否 | 未被 import，新直登批量现场脚本 | 中 | 是 |
| `tools/run_launcher_source.bat` | 启动辅助 | 是 | 否 | 否 | 源码模式快速启动 | 低 | 是 |
| `tools/run_drag_drop_poc.bat` | POC 启动辅助 | 否 | 是 | 否 | 与拖放 POC 配套 | 低 | 是 |

## 9. 历史备份目录清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `backup_before_v130_20260707_162052/` | 发布前备份 | 否 | 是 | 否 | v1.3.0 前备份，短期保留或归档 | 高 | 是 |
| `_cleanup_pending/` | 待清理归档 | 否 | 是 | 否 | 已标记为待清理，需人工确认内容 | 中 | 是 |
| `WIP_before_client_batch_fix.patch` | WIP 备份 | 否 | 是 | 否 | 历史补丁备份 | 中 | 是 |
| `WIP_before_client_batch_fix_status.txt` | WIP 状态 | 否 | 是 | 否 | 历史状态备份 | 低 | 是 |
| `WIP_before_client_direct_ui.patch` | WIP 备份 | 否 | 是 | 否 | 历史补丁备份 | 中 | 是 |
| `WIP_before_client_direct_ui_status.txt` | WIP 状态 | 否 | 是 | 否 | 历史状态备份 | 低 | 是 |
| `dist/Launcher_backup_*/` | 打包备份 | 否 | 是 | 否 | 多个历史打包备份，体积大 | 中 | 是 |
| `dist/LauncherStable20260629/` | 稳定版备份 | 否 | 是 | 否 | 可能是手工稳定版留档 | 高 | 是 |

## 10. 临时文件清单

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `__pycache__/` | Python 缓存 | 否 | 否 | 是 | 可再生成 | 低 | 是 |
| `build/` | PyInstaller 构建缓存 | 否 | 否 | 是 | 可由打包脚本再生成 | 中 | 是 |
| `dist/Launcher/` | 当前/残留打包输出 | 否 | 是 | 否 | 可能是失败或中间输出，删除前确认是否仍需排障 | 中 | 是 |
| `dist/斗罗大陆H5上号器-v1.2.0/` | 旧发布输出 | 否 | 是 | 否 | 旧版本发布包，可归档 | 中 | 是 |
| `.code-review-graph/` | 分析缓存 | 否 | 是 | 否 | 代码审查工具缓存 | 低 | 是 |
| `debug_background/` | 调试目录 | 否 | 是 | 否 | 后台调试产物/脚本混合 | 中 | 是 |
| `debug_client_direct/` | 调试目录 | 否 | 是 | 否 | 客户端直登调试产物 | 中 | 是 |
| `debug_login_chain/` | 调试目录 | 否 | 是 | 否 | 登录链路调试产物 | 中 | 是 |
| `debug_ocr/` | 调试目录 | 是 | 否 | 否 | 含 `template_passport_btn.png`，发布脚本依赖 | 高 | 是 |

## 11. 未被 import 的 Python 文件

检查方式：对工作区 Python 文件做 AST import 扫描，排除 `build/`、`dist/`、`__pycache__/`、`.git/`、`_cleanup_pending/`。

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `debug_background/live_keepalive_runner.py` | 未被 import | 否 | 是 | 否 | 调试运行器，可能只能手工运行 | 中 | 是 |
| `douluo_launcher/gui_pyside6.py` | 未被 import | 否 | 是 | 否 | 旧/实验 Qt GUI | 中 | 是 |
| `douluo_launcher/qt_styles.py` | 未被 import | 否 | 是 | 否 | Qt GUI 配套样式 | 中 | 是 |
| `scripts/test_qr_decode.py` | 未被 import | 否 | 是 | 否 | 手工 QR 调试脚本 | 低 | 是 |
| `tools/drag_drop_poc.py` | 未被 import | 否 | 是 | 否 | 拖放 POC | 低 | 是 |
| `tools/live_client_direct_login_batch.py` | 未被 import | 否 | 是 | 否 | 现场调试脚本，不是库模块 | 中 | 是 |
| `tools/live_client_direct_login_once.py` | 未被 import | 否 | 是 | 否 | 现场调试脚本，不是库模块 | 中 | 是 |

说明：未被 import 不等于无用。`tools/`、`scripts/`、`debug_background/` 内文件可能设计为命令行直接运行。

## 12. 可能重复的 spec 文件

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `Launcher.spec` | 当前候选 spec | 是 | 否 | 否 | 通过发布测试校验，使用模板配置 | 高 | 是 |
| `.spec` | 重复 spec | 否 | 是 | 否 | 文件名不可读且引用私有配置 | 高 | 是 |
| `ShangHaoQi.spec` | 重复 spec | 否 | 是 | 否 | 旧英文名，引用私有配置 | 高 | 是 |
| `上号器.spec` | 重复 spec | 否 | 是 | 否 | 中文名旧版本，需确认是否还有手工打包依赖 | 中 | 是 |
| `斗罗大陆H5上号器.spec` | 重复 spec | 否 | 是 | 否 | 中文完整名旧版本，需确认是否还有手工打包依赖 | 中 | 是 |

## 13. 可能重复的打包输出目录

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `dist/Launcher/` | PyInstaller 输出 | 否 | 是 | 否 | 与当前发布目录命名不一致，可能是失败排障残留 | 中 | 是 |
| `dist/斗罗大陆H5上号器-v1.2.0/` | 旧发布输出 | 否 | 是 | 否 | v1.2.0 旧发布目录 | 中 | 是 |
| `dist/Launcher_backup_20260629_151501/` | 打包备份 | 否 | 是 | 否 | 历史备份输出 | 中 | 是 |
| `dist/Launcher_backup_20260629_151606/` | 打包备份 | 否 | 是 | 否 | 历史备份输出 | 中 | 是 |
| `dist/Launcher_backup_20260629_151721/` | 打包备份 | 否 | 是 | 否 | 历史备份输出 | 中 | 是 |
| `dist/Launcher_backup_20260629_151818/` | 打包备份 | 否 | 是 | 否 | 历史备份输出 | 中 | 是 |
| `dist/Launcher_backup_20260629_151928/` | 打包备份 | 否 | 是 | 否 | 历史备份输出 | 中 | 是 |
| `dist/Launcher_backup_20260706_020904/` | 打包备份 | 否 | 是 | 否 | 历史备份输出 | 中 | 是 |
| `dist/Launcher_backup_20260706_102442/` | 打包备份 | 否 | 是 | 否 | 历史备份输出 | 中 | 是 |
| `dist/LauncherStable20260629/` | 稳定版输出 | 否 | 是 | 否 | 稳定版留档，删除风险高于普通 backup | 高 | 是 |

## 14. 可能不用的 debug 目录

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `debug_background/` | debug 目录 | 否 | 是 | 否 | 后台调试产物，含未被 import 的运行器 | 中 | 是 |
| `debug_client_direct/` | debug 目录 | 否 | 是 | 否 | 客户端直登调试产物 | 中 | 是 |
| `debug_login_chain/` | debug 目录 | 否 | 是 | 否 | 登录链路调试产物 | 中 | 是 |
| `debug_ocr/` | debug/资源目录 | 是 | 否 | 否 | 发布脚本依赖 `debug_ocr/template_passport_btn.png` | 高 | 是 |

## 15. 可能不用的 Gemini/旧 UI 文档

| 路径 | 类型 | 建议保留 | 建议归档 | 建议删除 | 理由 | 风险 | 人工确认 |
|---|---|---:|---:|---:|---|---|---:|
| `上号器_Gemini_UI开发说明.md` | Gemini/旧 UI 文档 | 否 | 是 | 否 | P8 特别点名，可能已被当前 Tkinter GUI 和 README 取代 | 低 | 是 |
| `douluo_launcher/gui_pyside6.py` | 旧/实验 UI 源码 | 否 | 是 | 否 | 当前主入口不 import，疑似旧 UI 尝试 | 中 | 是 |
| `douluo_launcher/qt_styles.py` | 旧/实验 UI 样式 | 否 | 是 | 否 | 与 PySide6 UI 配套，当前未被 import | 中 | 是 |
| `DESIGN.md` | 旧设计文档 | 否 | 是 | 否 | 体量较大，可能与当前实现不完全一致 | 低 | 是 |
| `DESIGN_METHOD2.md` | 旧方式二设计 | 否 | 是 | 否 | 历史设计资料 | 低 | 是 |

## 后续建议

1. 先把 `Launcher.spec` 与 `scripts/build_exe.ps1` 的职责定清：要么脚本继续作为唯一真实构建入口，spec 只做校验资产；要么改脚本显式使用 `Launcher.spec`。
2. 对所有真实账号 CSV 和本机 JSON 配置做敏感信息审查，再决定是否纳入版本库或迁到本机私有目录。
3. 对 `dist/` 和 `build/` 的清理应在确认没有运行中的 exe、没有需要回退的稳定包后进行。
4. 对 `gui_pyside6.py` / `qt_styles.py` / Gemini 旧 UI 文档建议先归档一个版本周期，再删除。
5. 对 `_cleanup_pending/`、WIP patch、历史 milestone 文档建议统一移动到 `docs/archive/` 或外部归档目录，而不是直接删除。
