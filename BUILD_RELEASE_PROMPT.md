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

D:\Ai\codex\上号器

然后执行：

```powershell
python --version
where python
python -m unittest discover -s tests -v
```

如果测试失败：

* 立即停止打包
* 输出失败原因
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
build_exe.bat
```

或：

```powershell
scripts\build_exe.bat
```

不要临时乱写打包命令，优先维护固定脚本。

---

## 四、exe 名称与输出目录

exe 名称：

```text
斗罗大陆H5上号器.exe
```

输出目录：

```text
dist\
```

最终可运行目录建议：

```text
dist\斗罗大陆H5上号器\
```

---

## 五、必须随 exe 保留的外部资源

不要把用户配置写死进 exe。

以下文件应放在 exe 同级目录，或按项目约定复制到 dist 对应目录：

* automation_settings.json
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
* build\
* __pycache__\
* *.pyc
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
10. 32 位大漠点击子进程是否仍能正常调用且不弹黑框。

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
