# 打包发布说明

**当前版本：斗罗大陆H5上号器 - Dm 合并链式调用版**
**最后打包：2026-05-13，PyInstaller 6.20.0，11 tests OK，冷启动 ~9.5s / warm ~7.5s**

---

## 1. 环境要求

### 打包环境

| 工具 | 版本 | 安装 |
|------|------|------|
| Python (64-bit) | 3.14.2 | 系统默认 `python` |
| Python (32-bit) | 3.14.4 | `py -3.14-32` 可调用 |
| PyInstaller | 6.20.0+ | `pip install pyinstaller` |
| Tesseract OCR | 任意 | 需在 PATH 中或配置路径 |

### 依赖检查

```powershell
python --version
pyinstaller --version
py -3.14-32 --version      # 可选，大漠子进程需要
pip install -r requirements.txt
```

---

## 2. 打包命令

```powershell
cd D:\Ai\codex\上号器
.\scripts\build_exe.bat
```

### 打包流程

```
[1/5] 检测 Python 环境
[2/5] 运行单元测试（11 个）
[3/5] 清理 build/ 和 dist/
[4/5] PyInstaller 打包
[5/5] 复制外部资源文件
```

### 测试失败时

打包脚本会在测试失败时停止，输出失败原因。修复测试后重新运行。

---

## 3. 输出位置

```
dist/斗罗大陆H5上号器/
├── 斗罗大陆H5上号器.exe       ← 主程序
├── automation_settings.json  ← 自动化配置（可修改）
├── dm_click_helper.py        ← Dm 点击脚本（32 位子进程调用）
├── debug_ocr/
│   ├── template_passport_btn.png  ← 按钮模板
│   ├── browser_pos.json           ← 运行时坐标缓存
│   └── _tmp/                      ← 临时截图
├── README.md / RUN_MODE.md / BUILD.md / ...  ← 文档
└── _internal/                  ← PyInstaller 运行库
```

---

## 4. 运行依赖

### exe 模式

- exe 自动检测运行环境，单账号和批量均走同进程直接调用
- 需要 Tesseract OCR 在系统 PATH 中
- Dm 点击需要 32 位 Python (`py -3.14-32`) 和 `dm_click_helper.py` 在 exe 同级目录

### 源码模式

- 串行批量使用子进程隔离架构（Playwright asyncio 隔离）
- 需要 Python 64-bit + 32-bit 双环境

---

## 5. 配置文件

以下文件在 exe 同级目录，可直接编辑，无需重新打包：

| 文件 | 说明 |
|------|------|
| `automation_settings.json` | 自动化参数（窗口大小、OCR、点击坐标等） |
| `debug_ocr/browser_pos.json` | 运行时浏览器坐标缓存（自动生成） |

---

## 6. 手动打包命令

如需自定义 PyInstaller 参数：

```powershell
pyinstaller --onedir --noconsole --name "斗罗大陆H5上号器" ^
    --add-data "automation_settings.json;." ^
    --add-data "debug_ocr\template_passport_btn.png;debug_ocr" ^
    --hidden-import PIL --hidden-import pytesseract --hidden-import cv2 ^
    --hidden-import win32com --hidden-import win32gui --hidden-import win32con ^
    --hidden-import playwright.sync_api ^
    --hidden-import douluo_launcher ^
    main.py
```

---

## 7. 常见问题

### 打包后运行报错 "No module named xxx"

在 `--hidden-import` 中添加缺失的模块名，重新打包。

### 打包后找不到 automation_settings.json

确认 exe 运行目录与 `automation_settings.json` 在同一目录。

### 串行批量模式不工作

如果在源码模式下运行，请确认从项目根目录启动：`cd D:\Ai\codex\上号器 && python main.py`。
exe 模式下批量自动走同进程调用，无需额外 Python。

### 点"全部串行"报 `function() argument 'code' must be code, not str`

已修复：模块级 `subprocess.Popen` monkey-patch 由 function 替换改为 class 继承（`_NoConsolePopen`），Playwright 导入前临时恢复原始 Popen 让 asyncio 正确子类化（2026-05-12）。

### 重试时"通行证未刷新"跳过完整流程

已修复：重试时不再因通行证相同而跳过，始终走完整浏览器流程（关旧浏览器→开新浏览器→公告→按钮→输入→确认→校验）（2026-05-12）。

### Tesseract OCR 报错

确认 Tesseract 已安装且在 PATH 中。或手动设置：在代码中指定 `pytesseract.pytesseract.tesseract_cmd`。

### 大漠点击不工作

确认 32 位 Python (`py -3.14-32`) 可用，且大漠 7.2607 已注册。

### exe 弹黑色命令行窗口

已修复：全项目显式子进程调用加 `CREAT_NO_WINDOW` + `automation.py` 模块级 monkey-patch `subprocess.Popen` 覆盖 pytesseract→tesseract.exe 等第三方库内部调用（2026-05-11）。

### 通行证按钮模板读不到

已修复：`cv2.imread()` 不支持中文绝对路径，改用 `cv2.imdecode(np.fromfile(...))`（2026-05-10）。

### Playwright 找不到 Chromium

已修复：exe 模式自动设置 `PLAYWRIGHT_BROWSERS_PATH=%LOCALAPPDATA%\ms-playwright`（2026-05-10）。
