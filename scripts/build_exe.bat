@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo  斗罗大陆H5上号器 - 打包脚本
echo  前台串行稳定版
echo ============================================
echo.

cd /d "%~dp0\.."

REM ---- 检测 Python 环境 ----
echo [1/6] 检测 Python 环境
python --version
if %ERRORLEVEL% neq 0 (
    echo [FAIL] 未找到 python，请确认 Python 已安装且在 PATH 中
    exit /b 1
)
echo   python: OK

pyinstaller --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [FAIL] 未找到 pyinstaller，请先执行: pip install pyinstaller
    exit /b 1
)
echo   pyinstaller: OK

echo   py -3.14-32 --version
py -3.14-32 --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARN] 未找到 32 位 Python (py -3.14-32)，Dm 点击将不可用
) else (
    echo   32-bit Python: OK
)
echo.

REM ---- 运行单元测试 ----
echo [2/6] 运行单元测试
python -m unittest discover -s tests -v
if %ERRORLEVEL% neq 0 (
    echo.
    echo [FAIL] 单元测试未通过，停止打包。
    echo 请先修复失败的测试再重新打包。
    exit /b 1
)
echo   测试全部通过
echo.

REM ---- 清理旧构建 ----
echo [3/6] 清理旧构建目录
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo   已清理
echo.

REM ---- PyInstaller 打包 ----
echo [4/6] PyInstaller 打包（--noconsole 模式）
pyinstaller ^
    --onedir ^
    --noconsole ^
    --name "斗罗大陆H5上号器" ^
    --add-data "automation_settings.json;." ^
    --add-data "debug_ocr\template_passport_btn.png;debug_ocr" ^
    --hidden-import PIL ^
    --hidden-import pytesseract ^
    --hidden-import cv2 ^
    --hidden-import win32com ^
    --hidden-import win32gui ^
    --hidden-import win32con ^
    --hidden-import playwright.sync_api ^
    --hidden-import douluo_launcher ^
    --hidden-import douluo_launcher.config ^
    --hidden-import douluo_launcher.automation ^
    --hidden-import douluo_launcher.dm_client ^
    --hidden-import douluo_launcher.gui ^
    main.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [FAIL] PyInstaller 打包失败
    exit /b 1
)
echo.

REM ---- 复制外部资源 ----
echo [5/6] 复制外部资源到 dist\

set DIST_DIR=dist\斗罗大陆H5上号器

REM 配置文件（exe 同级目录，运行时通过 app_root() 读取）
copy automation_settings.json "%DIST_DIR%\" >nul
echo   copy: automation_settings.json

REM Dm 点击脚本（32 位 Python 子进程调用，app_root() 定位）
copy dm_click_helper.py "%DIST_DIR%\" >nul
echo   copy: dm_click_helper.py

REM 按钮模板（运行时模板匹配读取）
if not exist "%DIST_DIR%\debug_ocr" mkdir "%DIST_DIR%\debug_ocr"
copy debug_ocr\template_passport_btn.png "%DIST_DIR%\debug_ocr\" >nul
echo   copy: debug_ocr\template_passport_btn.png

REM 运行时临时截图目录
if not exist "%DIST_DIR%\debug_ocr\_tmp" mkdir "%DIST_DIR%\debug_ocr\_tmp

REM 文档
for %%f in (README.md OCR_SUCCESS.md CLICK_SOLUTION.md RUN_MODE.md CURRENT_ISSUES.md NEXT_STEPS.md BUILD.md) do (
    if exist %%f copy %%f "%DIST_DIR%\" >nul
)
echo   copy: 文档

echo   资源文件已复制
echo.

REM ---- 验证 ----
echo [6/6] 验证打包结果
if exist "%DIST_DIR%\斗罗大陆H5上号器.exe" (
    echo ============================================
    echo  打包成功
    echo ============================================
    echo.
    echo   exe: %DIST_DIR%\斗罗大陆H5上号器.exe
    echo   目录: %CD%\%DIST_DIR%
    echo.
    echo  运行方式:
    echo    1. 进入 %DIST_DIR%\
    echo    2. 双击 斗罗大陆H5上号器.exe
    echo.
    echo  注意: exe 模式串行批量使用同进程调用（非子进程隔离）。
    echo       Playwright 连续多次运行如有异常请重启 exe。
    echo       Dm 点击需要系统安装 32 位 Python (py -3.14-32)。
    exit /b 0
) else (
    echo [FAIL] exe 未生成
    exit /b 1
)
