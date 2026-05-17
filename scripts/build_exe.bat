@echo off
setlocal EnableExtensions

REM ASCII-only launcher. The real build logic is in UTF-8 PowerShell.
REM Keep this file as pure BAT. Do not paste Markdown or PyInstaller fragments here.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
exit /b %ERRORLEVEL%
