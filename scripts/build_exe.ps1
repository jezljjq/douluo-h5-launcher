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

function Find-ChromiumExe([string]$BrowsersDir) {
    if (-not (Test-Path -LiteralPath $BrowsersDir)) {
        return $null
    }
    $matches = Get-ChildItem -LiteralPath $BrowsersDir -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Join-Path $_.FullName "chrome-win64\chrome.exe"
        } |
        Where-Object {
            Test-Path -LiteralPath $_
        } |
        Select-Object -First 1
    return $matches
}

function Copy-Directory([string]$Source, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /NFL /NDL /NJH /NJS /NP
    $code = $LASTEXITCODE
    if ($code -gt 7) {
        Fail "robocopy failed from $Source to $Destination with exit code $code"
    }
    $global:LASTEXITCODE = 0
}

function Remove-IfExists([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

$AppName = "上号器"
$InternalBuildName = "Launcher"
$DistDir = Join-Path $ProjectRoot "dist\$InternalBuildName"
$InternalExePath = Join-Path $DistDir "$InternalBuildName.exe"
$ExePath = Join-Path $DistDir "$AppName.exe"
$PlaywrightBrowsers = Join-Path $env:LOCALAPPDATA "ms-playwright"
$BundledPlaywrightBrowsers = Join-Path $DistDir "ms-playwright"

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
    Fail "32-bit Python py -3.14-32 was not found. It is required on the build machine to package dm_click_helper.exe."
}
& py -3.14-32 -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail "32-bit PyInstaller was not found. Install it on the build machine with: py -3.14-32 -m pip install pyinstaller"
}
Write-Host "  32-bit Python/PyInstaller: OK"

Step "[2/7] Check Playwright Chromium location"
if (-not (Test-Path -LiteralPath $PlaywrightBrowsers)) {
    Fail "打包机器缺少 Playwright Chromium: $PlaywrightBrowsers. 请先在打包机器执行: python -m playwright install chromium"
}
$SourceChromiumExe = Find-ChromiumExe $PlaywrightBrowsers
if ($null -eq $SourceChromiumExe) {
    Fail "打包机器缺少 Playwright Chromium chrome.exe. 请先在打包机器执行: python -m playwright install chromium"
}
Write-Host "  source browsers: $PlaywrightBrowsers"
Write-Host "  source Chromium: $SourceChromiumExe"
$env:PLAYWRIGHT_BROWSERS_PATH = $PlaywrightBrowsers

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

Write-Host "  building: dm_click_helper.exe (32-bit)"
$HelperBuildDir = Join-Path $ProjectRoot "build\dm_click_helper"
$HelperSpecDir = Join-Path $ProjectRoot "build\dm_click_helper_spec"
& py -3.14-32 -m PyInstaller `
    --onefile `
    --clean `
    -y `
    --noconsole `
    --name "dm_click_helper" `
    --distpath $DistDir `
    --workpath $HelperBuildDir `
    --specpath $HelperSpecDir `
    "dm_click_helper.py"
if ($LASTEXITCODE -ne 0) {
    Fail "32-bit dm_click_helper.exe build failed."
}
$HelperExe = Join-Path $DistDir "dm_click_helper.exe"
if (-not (Test-Path -LiteralPath $HelperExe)) {
    Fail "dm_click_helper.exe was not generated: $HelperExe"
}
Write-Host "  bundled: dm_click_helper.exe"

$DebugDir = Join-Path $DistDir "debug_ocr"
New-Item -ItemType Directory -Force -Path $DebugDir | Out-Null
Copy-Item -LiteralPath "debug_ocr\template_passport_btn.png" -Destination $DebugDir -Force
Write-Host "  copied: debug_ocr\template_passport_btn.png"

Write-Host "  copying: ms-playwright browser cache"
Copy-Directory $PlaywrightBrowsers $BundledPlaywrightBrowsers
Get-ChildItem -LiteralPath $BundledPlaywrightBrowsers -Directory -Filter "mcp-chrome-*" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
$BundledChromiumExe = Find-ChromiumExe $BundledPlaywrightBrowsers
if ($null -eq $BundledChromiumExe) {
    Fail "Copied ms-playwright but no Chromium chrome.exe was found under $BundledPlaywrightBrowsers"
}
Write-Host "  copied: ms-playwright"
Write-Host "  bundled Chromium: $BundledChromiumExe"

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

Write-Host "  cleaning release-only runtime artifacts"
Remove-IfExists (Join-Path $DistDir "logs")
Remove-IfExists (Join-Path $DebugDir "_tmp")
Remove-IfExists (Join-Path $DebugDir "history")
Remove-IfExists (Join-Path $DistDir "slots")
Remove-IfExists (Join-Path $DistDir "window_slots.json")
Get-ChildItem -LiteralPath $DistDir -Recurse -Filter "*.log" -File -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Filter "*.csv" -File -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Filter "window_slots*.json" -File -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Directory -Filter ".pytest_cache" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Filter "*.pyc" -File -ErrorAction SilentlyContinue | Remove-Item -Force

Step "[7/7] Verify build output"
if (-not (Test-Path -LiteralPath $ExePath)) {
    Fail "exe was not generated: $ExePath"
}
if (-not (Test-Path -LiteralPath $BundledChromiumExe)) {
    Fail "bundled Chromium missing after cleanup: $BundledChromiumExe"
}

Write-Host "============================================"
Write-Host " Build succeeded"
Write-Host "============================================"
Write-Host "  exe: $ExePath"
Write-Host "  dir: $DistDir"
Write-Host "  bundled browsers: $BundledPlaywrightBrowsers"
Write-Host ""
Write-Host "Runtime notes:"
Write-Host "  Playwright Chromium is bundled in the release directory."
Write-Host "  Dm click helper is bundled as dm_click_helper.exe. Dm COM still must be registered on the target machine."
exit 0
