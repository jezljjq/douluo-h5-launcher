# 上号器 release build script. UTF-8 PowerShell handles Chinese paths and exe names.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message"
    exit 1
}

function Step([string]$Message) {
    Write-Host ""
    Write-Host $Message
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

$AppName = "上号器"
$InternalBuildName = "Launcher"
$DistDir = Join-Path $ProjectRoot "dist\$InternalBuildName"
$InternalExePath = Join-Path $DistDir "$InternalBuildName.exe"
$ExePath = Join-Path $DistDir "$AppName.exe"
$PlaywrightBrowsers = Join-Path $env:LOCALAPPDATA "ms-playwright"
$env:PLAYWRIGHT_BROWSERS_PATH = $PlaywrightBrowsers

Write-Host "============================================"
Write-Host " $AppName - release build"
Write-Host " internal build name: $InternalBuildName"
Write-Host " mode: foreground serial"
Write-Host "============================================"

Step "[0/7] Validate build context"
if (-not (Test-Path -LiteralPath "main.py")) {
    Fail "main.py not found. Please run from project root or scripts directory."
}
if (-not (Test-Path -LiteralPath "automation_settings.json")) {
    Fail "Missing required file: automation_settings.json"
}
if (-not (Test-Path -LiteralPath "debug_ocr\template_passport_btn.png")) {
    Fail "Missing required file: debug_ocr\template_passport_btn.png"
}
Write-Host "  project root: $ProjectRoot"
Write-Host "  Playwright browsers: $PlaywrightBrowsers"

Step "[1/7] Check Python and PyInstaller"
& python --version
if ($LASTEXITCODE -ne 0) {
    Fail "Python was not found in PATH."
}

& pyinstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail "PyInstaller was not found. Install it with: pip install pyinstaller"
}
$PyInstallerVersion = (& pyinstaller --version)
Write-Host "  pyinstaller: $PyInstallerVersion"

& py -3.14-32 --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] 32-bit Python py -3.14-32 was not found. Dm click helper will be unavailable until it is installed."
} else {
    Write-Host "  32-bit Python: OK"
}

Step "[2/7] Check Playwright Chromium location"
if (-not (Test-Path -LiteralPath $PlaywrightBrowsers)) {
    Write-Host "[WARN] $PlaywrightBrowsers does not exist."
    Write-Host "[INFO] Installing Chromium into LOCALAPPDATA ms-playwright cache."
    & python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Fail "Playwright Chromium install failed. The exe may not be able to launch browser automation."
    }
} else {
    Write-Host "  using LOCALAPPDATA ms-playwright cache"
}

Step "[3/7] Run tests"
& python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    Fail "Unit tests failed. Build stopped."
}
Write-Host "  tests: OK"

Step "[4/7] Clean previous build outputs"
foreach ($Path in @("build", "dist")) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}
Write-Host "  cleaned: build, dist"

Step "[5/7] Run PyInstaller"
$PyInstallerArgs = @(
    "--onedir",
    "--clean",
    "-y",
    "--noconsole",
    "--name", $InternalBuildName,
    "--add-data", "automation_settings.json;.",
    "--add-data", "debug_ocr\template_passport_btn.png;debug_ocr",
    "--hidden-import", "PIL",
    "--hidden-import", "pytesseract",
    "--hidden-import", "cv2",
    "--hidden-import", "win32com",
    "--hidden-import", "win32gui",
    "--hidden-import", "win32con",
    "--hidden-import", "playwright.sync_api",
    "--hidden-import", "douluo_launcher",
    "--hidden-import", "douluo_launcher.config",
    "--hidden-import", "douluo_launcher.automation",
    "--hidden-import", "douluo_launcher.dm_client",
    "--hidden-import", "douluo_launcher.gui",
    "main.py"
)
& pyinstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    Fail "PyInstaller build failed."
}

Step "[6/7] Copy runtime resources"
if (-not (Test-Path -LiteralPath $DistDir)) {
    Fail "Dist directory was not generated: $DistDir"
}
if (-not (Test-Path -LiteralPath $InternalExePath)) {
    Fail "Internal exe was not generated: $InternalExePath"
}
if (Test-Path -LiteralPath $ExePath) {
    Remove-Item -LiteralPath $ExePath -Force
}
Rename-Item -LiteralPath $InternalExePath -NewName "$AppName.exe"
Write-Host "  renamed: $InternalBuildName.exe -> $AppName.exe"

Copy-Item -LiteralPath "automation_settings.json" -Destination $DistDir -Force
Write-Host "  copied: automation_settings.json"

Copy-Item -LiteralPath "dm_click_helper.py" -Destination $DistDir -Force
Write-Host "  copied: dm_click_helper.py"

$DebugDir = Join-Path $DistDir "debug_ocr"
$TmpDir = Join-Path $DebugDir "_tmp"
$LogsDir = Join-Path $DistDir "logs"
New-Item -ItemType Directory -Force -Path $DebugDir, $TmpDir, $LogsDir | Out-Null
Copy-Item -LiteralPath "debug_ocr\template_passport_btn.png" -Destination $DebugDir -Force
Write-Host "  copied: debug_ocr\template_passport_btn.png"

$Docs = @(
    "README.md",
    "RUN_MODE.md",
    "OCR_SUCCESS.md",
    "CLICK_SOLUTION.md",
    "CURRENT_ISSUES.md",
    "NEXT_STEPS.md",
    "BUILD.md",
    "BUILD_RELEASE_PROMPT.md"
)
foreach ($Doc in $Docs) {
    if (Test-Path -LiteralPath $Doc) {
        Copy-Item -LiteralPath $Doc -Destination $DistDir -Force
    }
}
Write-Host "  copied: documentation"

Step "[7/7] Verify build output"
if (-not (Test-Path -LiteralPath $ExePath)) {
    Fail "exe was not generated: $ExePath"
}

Write-Host "============================================"
Write-Host " Build succeeded"
Write-Host "============================================"
Write-Host "  exe: $ExePath"
Write-Host "  dir: $DistDir"
Write-Host ""
Write-Host "Runtime notes:"
Write-Host "  Playwright Chromium uses: $PlaywrightBrowsers"
Write-Host "  Dm click helper requires 32-bit Python py -3.14-32 and registered Dm COM."
exit 0
