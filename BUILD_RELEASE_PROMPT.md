# 打包发布通用指令

当用户要求"打包""生成 exe""发布版本""重新打包""打包发布""里程碑打包"时，必须优先读取本文件，并严格执行。

---

## 一、任务边界

本任务只允许做：

* 测试
* 打包
* 复制必要资源
* 更新打包相关文档
* 生成发布说明

默认禁止修改业务代码。

禁止修改：

* OCR 逻辑
* Dm 点击逻辑
* Playwright 流程
* 串行流程
* 已登录判断
* CSV 登录逻辑
* GUI 业务逻辑
* 通行证识别逻辑
* 候选通行证重试逻辑

如果打包过程中发现代码问题：

只能先记录到文档里，
不能直接修改代码。

如确实需要修改代码，必须先单独说明问题，等待用户确认后再改。

---

## 二、打包前检查

打包前必须确认当前目录：

<项目路径>

然后执行：

```powershell
python --version
where python
python -m compileall -q douluo_launcher main.py
python -m unittest discover -s tests -v
```

如果编译检查或测试失败：

* 立即停止打包
* 输出失败原因
* 禁止提交
* 禁止 push
* 不生成 exe
* 不尝试绕过测试

---

## 三、打包工具

使用 PyInstaller 打包。

如果未安装：

```powershell
pip install pyinstaller
```

推荐使用项目内打包脚本：

```powershell
scripts\build_exe.bat
```

脚本是唯一推荐入口。不要临时拼接 PyInstaller 命令；如果打包参数需要变化，先维护 `scripts\build_exe.ps1`，再通过 `scripts\build_exe.bat` 重新执行脚本。

### 打包脚本卫生规则

`scripts\build_exe.bat` 必须保持纯 bat 脚本，并且只作为 ASCII-only 启动器调用 `scripts\build_exe.ps1`：

* 不允许混入 Markdown 文档内容。
* 不允许混入普通说明文字，除非使用 `REM` 或 `echo`。
* 中文说明、中文路径、中文 exe 名不要交给 `cmd` 多行解析，放到 UTF-8 PowerShell 脚本中处理。
* 所有路径必须加双引号。
* 如 bat 中存在多行命令，必须使用正确的 `^` 续行；当前推荐做法是不要在 bat 中写 PyInstaller 多行命令。
* 不允许出现断裂参数，例如某个 png、md、exe 文件名被单独当命令执行。
* 脚本失败时必须输出 `[FAIL]` 并 `exit /b 1`，禁止假成功。
* 禁止通过改英文软件名、目录名、业务名来绕过中文编码问题。

### Playwright 浏览器策略

当前发布包必须内置 Playwright Chromium：

```text
dist\Launcher\ms-playwright\chromium-*\chrome-win64\chrome.exe
```

打包脚本只在打包机器读取 `%LOCALAPPDATA%\ms-playwright` 作为源目录，并复制当前 Playwright 实际需要的单个 Chromium revision 到 `dist\Launcher\ms-playwright`。脚本必须优先读取 Playwright Python 包内的 `driver\package\browsers.json` 来确定 `chromium` revision，例如 `chromium-1217`；不得把本机缓存中的所有 `chromium-*` 全量复制进发布包。

打包完成后，`dist\Launcher\ms-playwright\chromium-*\chrome-win64\chrome.exe` 必须且只能匹配到 1 个。如果检测到多个 `chromium-*`，脚本必须清理旧版本或失败，禁止静默发布多个 Chromium 目录。目标机器不需要安装 Python、pip、Playwright 或 Chromium，也不应该执行 `python -m playwright install chromium`。

如果打包机器缺少 Chromium 缓存，脚本必须失败并提示先在打包机器执行：

```powershell
python -m playwright install chromium
```

exe 运行时优先设置：

```text
PLAYWRIGHT_BROWSERS_PATH=<exe所在目录>\ms-playwright
```

禁止让 exe 依赖不存在的 `_internal\.local-browsers`，也禁止依赖任何固定用户目录。

### Dm helper 策略

当前发布包必须内置 32 位 `dm_click_helper.exe`：

```text
dist\Launcher\dm_click_helper.exe
```

打包脚本在打包机器使用 `py -3.14-32 -m PyInstaller` 生成该 helper。目标机器不需要安装 Python 或 32 位 Python；但大漠 COM 仍必须在目标机器可用。源码模式仍保留 `dm_click_helper.py` 作为开发回退。

---

## 四、exe 名称与输出目录

exe 名称：

```text
上号器.exe
```

输出目录：

```text
dist\
```

最终可运行目录建议：

```text
dist\Launcher\
```

说明：内部打包目录和 PyInstaller 内部名称可以使用英文 `Launcher`，避免 Windows `cmd` 对中文目录名、spec 名和中间构建路径解析不稳定。发布包最终 exe 文件名必须保持中文 `上号器.exe`。若中文 exe 名处理不稳定，应修复脚本本身，优先使用 UTF-8 PowerShell 脚本和参数数组。GUI 窗口标题仍显示为“上号器 — 前台串行模式”。

---

## 五、必须随 exe 保留的外部资源

不要把用户配置写死进 exe。

以下文件应放在 exe 同级目录，或按项目约定复制到 dist 对应目录：

* automation_settings.json
* dm_click_helper.exe
* dm_click_helper.py
* ms-playwright\
* debug_ocr\template_passport_btn.png
* README.md
* RUN_MODE.md
* OCR_SUCCESS.md
* CLICK_SOLUTION.md
* CURRENT_ISSUES.md
* NEXT_STEPS.md
* BUILD.md
* MILESTONE_FRONTEND_SERIAL.md

如存在示例配置，也要保留：

* automation_settings.sample.json
* accounts.sample.csv
* bookmarks.sample.json

---

## 六、禁止打包进去或提交的内容

不要把以下内容打进发布包：

* logs\
* debug_ocr\_tmp\
* debug_ocr\history\
* window_slots.json
* slots\
* build\
* __pycache__\
* *.pyc
* *.log
* .venv\
* venv\
* 真实账号密码 CSV
* 包含真实 token / password 的文件
* 临时截图
* 调试失败现场

---

## 七、打包后验证

打包完成后必须验证：

1. exe 是否生成。
2. 双击 exe 是否能启动。
3. 启动后是否没有黑色 py.exe 控制台窗口。
4. 是否能读取收藏夹。
5. 是否能读取 automation_settings.json。
6. 是否能找到 debug_ocr\template_passport_btn.png。
7. 是否能创建 logs 目录。
8. 是否能创建 debug_ocr\_tmp 目录。
9. 单账号流程是否能正常启动。
10. 是否能找到 exe 同级 `dm_click_helper.exe`。
11. 32 位大漠点击 helper 是否仍能正常调用且不弹黑框。

如验证失败：

* 不要直接修改业务代码
* 先记录失败原因
* 输出错误日志路径
* 等待用户确认后再修复

---

## 八、发布说明

每次打包完成后，生成或更新发布说明。

建议更新：

* BUILD.md
* MILESTONE_FRONTEND_SERIAL.md
* NEXT_STEPS.md
* README.md

发布说明必须包含：

* 打包时间
* 当前版本名称
* exe 输出路径
* 测试是否通过
* 打包是否成功
* 当前功能状态
* 当前限制
* 已知问题
* 下一步计划

---

## 九、当前版本限制必须写清

当前版本属于：

```text
前台串行稳定版
```

限制：

* 会移动鼠标
* 不支持真后台
* 不支持真并发
* 批量只能串行
* Dm BindWindow 已确认不可用，禁止回退重试

---

## 十、输出要求

打包完成后必须输出：

1. 是否测试通过
2. 是否打包成功
3. exe 文件路径
4. 打包脚本路径
5. 修改了哪些文档
6. 是否修改了业务代码
7. 是否发现问题但未修改
8. 当前发布包是否可直接运行

---

## 十一、强制规则

如果本次任务修改了任何业务代码，必须立即说明：

* 修改了什么文件
* 为什么必须修改
* 是否经过用户确认
* 是否已做回归测试

除非用户明确授权，否则打包发布任务不得修改业务代码。
