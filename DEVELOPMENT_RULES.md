# 项目开发规则

**适用范围**：斗罗大陆H5上号器项目。每次开发都必须遵守。

---

## 1. 文档任务默认禁止修改代码

当用户说"整理文档""更新文档""完善文档""同步文档""生成交接文档""更新项目说明""文档收尾"时，必须先读取并执行 [DOC_UPDATE_PROMPT.md](DOC_UPDATE_PROMPT.md)。

文档整理任务请先阅读并遵守 [DOC_UPDATE_PROMPT.md](DOC_UPDATE_PROMPT.md)。

打包发布任务请先阅读并遵守 [BUILD_RELEASE_PROMPT.md](BUILD_RELEASE_PROMPT.md)。

- 用户要求"更新文档"时，只允许修改 `.md` 文件
- 禁止修改 `.py`、`.bat`、`.json`、启动脚本、配置文件
- 如发现代码 bug，必须先说明问题并等待用户确认后再修改
- 修改前必须列出计划修改文件清单
- 修改后必须运行回归验证

## 2. 修改前声明范围

每次开发前明确：
- 本次修改哪些模块
- 哪些模块禁止改动

## 3. 禁止无关重构

修改功能时只能修改当前目标相关代码。禁止为修小问题重写整个流程。

## 4. 已稳定模块禁止随意修改

以下模块已稳定，除非确认存在 bug，否则禁止重构：
- OCR 通行证提取
- 模板匹配按钮定位
- Dm 前台点击
- 公告关闭
- 登录校验
- GUI 状态刷新
- Playwright 初始化

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

**前台串行稳定版**。优先级：稳定性 > 新功能。禁止大规模重构。

## 8. 每完成一个阶段必须更新文档

代码与文档必须同步。详见 [README.md](README.md) 文档索引。

---

## 9. 同类问题全局排查规则

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
