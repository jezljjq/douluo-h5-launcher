# 里程碑：前台串行稳定版

**日期：2026-05-12**
**版本：v1.0.1 前台串行稳定版**

---

## 1. 版本概述

斗罗大陆H5上号器首个稳定版本。实现从登录程序窗口 OCR 提取通行证、浏览器打开游戏页、关闭公告、模板匹配定位按钮、Dm 前台点击、剪贴板输入通行证、视觉定位确认按钮、登录校验的完整自动化流程。

支持单账号、当前层串行、全部串行三种运行模式。

---

## 2. 已完成功能

### 核心流程

| 步骤 | 功能 | 方案 | 状态 |
|------|------|------|------|
| 1 | OCR 通行证提取 | 全图 OCR + 三层正则 + 字符纠错 + 多变体投票（优先 a-f） | ✅ |
| 2 | 打开游戏页 | Playwright Chromium | ✅ |
| 3 | 关闭公告 | canvas 右下角固定坐标点击 | ✅ |
| 4 | 通行证按钮定位 | OpenCV 模板匹配 (TM_CCOEFF_NORMED) | ✅ |
| 5 | 弹窗视觉校验 | 灰色面板检测 + 输入框轮廓 + 黄色按钮 | ✅ |
| 6 | 输入通行证 | clip.exe 剪贴板 + Dm Ctrl+V | ✅ |
| 7 | 确认按钮定位 | 视觉黄色按钮检测 (y最小+x最大) | ✅ |
| 8 | 登录校验 | 回到登录程序窗口 OCR 检查 QR 是否消失 | ✅ |
| 9 | 失败自动重试 | 任意步骤失败重试 1 次 | ✅ |

### GUI

| 功能 | 说明 |
|------|------|
| 账号表格 | Treeview 展示层级/收藏编号/窗口号/通行证/链接/状态 |
| 状态颜色 | 蓝色(running)/绿色(success)/红色(failed)/橙色(retry) |
| 实时刷新 | 源码模式 Popen 逐行读取 / exe 模式同进程回调，UI 队列更新 |
| 日志区域 | GUI 简洁日志 + `logs/run_时间.log` 完整日志 |
| GUI 居中 | 启动时自动屏幕居中 |
| 停止响应 | 200ms 内响应停止按钮（所有等待可中断） |
| 耗时统计 | 每步骤 `perf_counter` + 投票详情日志 |
| 速度优化 | Dm 链式调用、截图按需保存、已登录快速跳过、等待缩减 |

### 运行模式

| 模式 | 说明 |
|------|------|
| 单账号运行 | 下拉框选择，运行一个账号 |
| 当前层串行 | 选择层级，串行运行该层 1-8 |
| 全部串行 | 串行运行所有已加载账号（最多 32） |

### 工程化

| 项目 | 说明 |
|------|------|
| 单元测试 | 11 tests OK |
| 调试截图管理 | `_tmp/` + `_error/` + `latest_ocr_success.png` |
| 文档 | 12 个 Markdown 文档覆盖架构/方案/问题/计划 |
| 打包 | PyInstaller + build_exe.bat 自动化 |

---

## 3. 当前限制

| 限制 | 影响 | 原因 |
|------|------|------|
| 前台模式 | 运行时会移动鼠标 | Dm 无绑定前台点击 |
| 严格串行 | 32 账号约需 16 分钟 | 前台点击不能并发 |
| 非后台 | 窗口必须可见 | 无后台点击方案 |
| Win11 + Dm 7.2607 | BindWindow 全模式崩溃 | 大漠版本不兼容 |
| 32 位 Python 依赖 | 需双 Python 环境 | Dm 仅 32 位可用 |
| Dm 点击需 32 位 Python | exe 批量仍需 `py -3.14-32` | Dm 仅 32 位可用 |

---

## 4. 已废弃方案

| 方案 | 废弃原因 |
|------|----------|
| 二维码定位 + 裁剪 OCR | 位置不稳定，不是可靠锚点 |
| Playwright canvas click | isTrusted 检测拦截 |
| CDP dispatchMouseEvent | isTrusted 检测拦截 |
| SendMessage/PostMessage | Chrome GPU 渲染绕过消息机制 |
| Dm BindWindow | 36/36 全模式崩溃 (Win11) |
| Dm OpenClipboard API | 多进程句柄冲突 |
| Dm KeyPressChar 逐字输入 | 焦点不确定 |

---

## 5. 测试结果

```
python -m unittest discover -s tests -v
Ran 11 tests in 0.008s — OK
```

测试覆盖：收藏夹映射、通行证提取、hex 纠错、窗口标题匹配、坐标换算。

---

## 6. 打包

```
scripts\build_exe.bat  →  dist\斗罗大陆H5上号器\斗罗大陆H5上号器.exe
```

打包工具：PyInstaller 6.20.0
模式：--onedir --noconsole

**exe 模式已知限制**：
- 需 `py -3.14-32` 用于 Dm 点击（32 位 Python 依赖）
- 需 Tesseract OCR 在系统 PATH
- `cv2.imread()` 改用 `cv2.imdecode()` 兼容中文路径
- Dm 子进程禁用控制台窗口（`CREATE_NO_WINDOW`）
- Playwright 浏览器路径通过 `PLAYWRIGHT_BROWSERS_PATH` 环境变量指定

---

## 7. 下一步

详见 [NEXT_STEPS.md](NEXT_STEPS.md)

- 短期：验证第四层串行、增加汇总统计
- 中期：真后台模式（Dm 新版本 / DD 虚拟驱动）
- 长期：完全 32 位环境、分辨率自适应、独占 exe
