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

function Get-ChromiumDirs([string]$BrowsersDir) {
    if (-not (Test-Path -LiteralPath $BrowsersDir)) {
        return @()
    }
    return @(Get-ChildItem -LiteralPath $BrowsersDir -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue)
}

function Get-PlaywrightChromiumDirName() {
    $code = @'
import json
from pathlib import Path
import playwright

path = Path(playwright.__file__).resolve().parent / 'driver' / 'package' / 'browsers.json'
data = json.loads(path.read_text(encoding='utf-8'))
for browser in data.get("browsers", []):
    if browser.get('name') == 'chromium':
        revision = str(browser.get('revision') or '').strip()
        if revision:
            print('chromium-' + revision)
            raise SystemExit(0)
raise SystemExit(2)
'@
    $tempScript = Join-Path ([System.IO.Path]::GetTempPath()) ("launcher_playwright_revision_{0}.py" -f ([System.Guid]::NewGuid().ToString("N")))
    try {
        Set-Content -LiteralPath $tempScript -Value $code -Encoding UTF8
        $output = & python $tempScript 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($output)) {
            return $null
        }
        return ($output | Select-Object -First 1).Trim()
    } finally {
        if (Test-Path -LiteralPath $tempScript) {
            Remove-Item -LiteralPath $tempScript -Force
        }
    }
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
$ReleaseDirName = "斗罗大陆H5上号器-v1.3.0"
$DistDir = Join-Path $ProjectRoot "dist\$ReleaseDirName"
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
if (-not (Test-Path -LiteralPath "automation_settings.template.json")) {
    Fail "Missing required file: automation_settings.template.json"
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
$ExpectedChromiumDirName = Get-PlaywrightChromiumDirName
if ([string]::IsNullOrWhiteSpace($ExpectedChromiumDirName)) {
    $availableChromiumDirs = Get-ChromiumDirs $PlaywrightBrowsers | Sort-Object Name
    if ($availableChromiumDirs.Count -eq 0) {
        Fail "无法从 Playwright browsers.json 识别 Chromium revision，且本地没有 chromium-* 目录。请先执行: python -m playwright install chromium"
    }
    $expectedDir = $availableChromiumDirs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $ExpectedChromiumDirName = $expectedDir.Name
    Write-Host "  warning: browsers.json revision not found; selected latest local Chromium: $ExpectedChromiumDirName"
} else {
    Write-Host "  expected Chromium from Playwright browsers.json: $ExpectedChromiumDirName"
}
$SourceChromiumDir = Join-Path $PlaywrightBrowsers $ExpectedChromiumDirName
$SourceChromiumExe = Join-Path $SourceChromiumDir "chrome-win64\chrome.exe"
if ($null -eq $SourceChromiumExe) {
    Fail "打包机器缺少 Playwright Chromium chrome.exe. 请先在打包机器执行: python -m playwright install chromium"
}
if (-not (Test-Path -LiteralPath $SourceChromiumExe)) {
    Fail "打包机器缺少当前 Playwright 需要的 Chromium: $SourceChromiumExe. 请先执行: python -m playwright install chromium"
}
$allSourceChromiumDirs = Get-ChromiumDirs $PlaywrightBrowsers | Sort-Object Name
$excludedChromiumDirs = @($allSourceChromiumDirs | Where-Object { $_.Name -ne $ExpectedChromiumDirName } | ForEach-Object { $_.Name })
Write-Host "  source browsers: $PlaywrightBrowsers"
Write-Host "  selected Chromium dir: $ExpectedChromiumDirName"
if ($excludedChromiumDirs.Count -gt 0) {
    Write-Host "  excluded old Chromium dirs: $($excludedChromiumDirs -join ', ')"
} else {
    Write-Host "  excluded old Chromium dirs: none"
}
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
    "--distpath", (Join-Path $ProjectRoot "dist"),
    "--add-data", "automation_settings.template.json;.",
    "--add-data", "debug_ocr\template_passport_btn.png;debug_ocr",
    "--collect-all", "tkinterdnd2",
    "--hidden-import", "PIL",
    "--hidden-import", "pytesseract",
    "--hidden-import", "cv2",
    "--hidden-import", "tkinterdnd2",
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
$GeneratedDir = Join-Path $ProjectRoot "dist\$InternalBuildName"
if (-not (Test-Path -LiteralPath $GeneratedDir)) {
    Fail "PyInstaller output directory was not generated: $GeneratedDir"
}
if (Test-Path -LiteralPath $DistDir) {
    Remove-Item -LiteralPath $DistDir -Recurse -Force
}
Rename-Item -LiteralPath $GeneratedDir -NewName $ReleaseDirName

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

Copy-Item -LiteralPath "automation_settings.template.json" -Destination $DistDir -Force
Write-Host "  copied: automation_settings.template.json"

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

Write-Host "  copying: selected ms-playwright Chromium"
Remove-IfExists $BundledPlaywrightBrowsers
New-Item -ItemType Directory -Force -Path $BundledPlaywrightBrowsers | Out-Null
$BundledChromiumDir = Join-Path $BundledPlaywrightBrowsers $ExpectedChromiumDirName
Copy-Directory $SourceChromiumDir $BundledChromiumDir
$bundledChromiumDirs = Get-ChromiumDirs $BundledPlaywrightBrowsers | Sort-Object Name
if ($bundledChromiumDirs.Count -gt 1) {
    $unexpected = @($bundledChromiumDirs | Where-Object { $_.Name -ne $ExpectedChromiumDirName })
    foreach ($dir in $unexpected) {
        Write-Host "  removing unexpected Chromium dir from release: $($dir.Name)"
        Remove-Item -LiteralPath $dir.FullName -Recurse -Force
    }
    $bundledChromiumDirs = Get-ChromiumDirs $BundledPlaywrightBrowsers | Sort-Object Name
}
if ($bundledChromiumDirs.Count -ne 1) {
    Fail "发布包 ms-playwright 中 Chromium 目录数量异常：$($bundledChromiumDirs.Count)。必须且只能有 1 个 chromium-*。"
}
$BundledChromiumExe = Join-Path $bundledChromiumDirs[0].FullName "chrome-win64\chrome.exe"
if ($null -eq $BundledChromiumExe) {
    Fail "Copied ms-playwright but no Chromium chrome.exe was found under $BundledPlaywrightBrowsers"
}
if (-not (Test-Path -LiteralPath $BundledChromiumExe)) {
    Fail "Copied selected Chromium but chrome.exe was not found: $BundledChromiumExe"
}
Write-Host "  copied: ms-playwright"
Write-Host "  bundled Chromium dirs count: $($bundledChromiumDirs.Count)"
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
