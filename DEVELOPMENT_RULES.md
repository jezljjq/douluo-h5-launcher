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

**前台串行稳定版 + 窗口管理区接入阶段**。优先级：稳定上号成功率 > 窗口定位融合 > UI 美化 > 打包。禁止大规模重构。

当前开发顺序：

1. 先稳定上号成功率。
2. 再做窗口管理排序结果与上号器窗口定位融合。
3. 再做 UI 美化。
4. 最后单独确认打包 exe。

UI 美化不得影响核心流程。

## 8. `subprocess.Popen` monkey-patch 规则

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

## 9. 每完成一个阶段必须更新文档

代码与文档必须同步。详见 [README.md](README.md) 文档索引。

---

## 10. 同类问题全局排查规则

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
