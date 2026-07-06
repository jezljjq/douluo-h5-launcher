@echo off
setlocal EnableExtensions
REM ASCII-only launcher. The real 32-bit build logic is in UTF-8 PowerShell.
pushd "%~dp0.."
where pwsh.exe >nul 2>nul
if %ERRORLEVEL%==0 (
    pwsh.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build_exe_32bit.ps1"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build_exe_32bit.ps1"
)
set BUILD_EXIT_CODE=%ERRORLEVEL%
popd
exit /b %BUILD_EXIT_CODE%
