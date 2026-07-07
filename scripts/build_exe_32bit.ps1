$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Step([string]$Message) {
    Write-Host ""
    Write-Host $Message -ForegroundColor Cyan
}

function Remove-IfExists([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Copy-Directory([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) {
        Fail "Missing directory: $Source"
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) {
        Fail "robocopy failed: $Source -> $Destination"
    }
}

function Get-ChromiumDirs([string]$BrowsersDir) {
    if (-not (Test-Path -LiteralPath $BrowsersDir)) {
        return @()
    }
    return @(Get-ChildItem -LiteralPath $BrowsersDir -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue)
}

function Get-PlaywrightChromiumDirName32() {
    $code = @'
import json
from pathlib import Path
import playwright

root = Path(playwright.__file__).resolve().parent
candidates = [
    root / "driver" / "package" / "browsers.json",
    root.parent / "playwright" / "driver" / "package" / "browsers.json",
]
for path in candidates:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for browser in data.get("browsers", []):
            if browser.get("name") == "chromium":
                revision = str(browser.get("revision") or "").strip()
                if revision:
                    print("chromium-" + revision)
                    raise SystemExit(0)
raise SystemExit(2)
'@
    $tempScript = Join-Path $env:TEMP ("playwright_revision_32_" + [guid]::NewGuid().ToString("N") + ".py")
    Set-Content -LiteralPath $tempScript -Value $code -Encoding UTF8
    try {
        $result = (& py -3.14-32 $tempScript) 2>$null
        if ($LASTEXITCODE -eq 0) {
            return (($result | Select-Object -First 1) -as [string]).Trim()
        }
        return $null
    } finally {
        Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Test-Path -LiteralPath (Join-Path (Get-Location) "main.py")) {
    $ProjectRoot = Resolve-Path (Get-Location)
} else {
    $ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
}
Set-Location $ProjectRoot

$AppName = -join @([char]0x4E0A, [char]0x53F7, [char]0x5668)
$InternalBuildName = "Launcher"
$ReleaseDirName = "斗罗大陆H5上号器-v1.3.0"
$DistParent = Join-Path $ProjectRoot "dist"
$DistDir = Join-Path $DistParent $ReleaseDirName
$InternalExePath = Join-Path $DistDir "$InternalBuildName.exe"
$ExePath = Join-Path $DistDir "$AppName.exe"
$PlaywrightBrowsers = Join-Path $env:LOCALAPPDATA "ms-playwright"
$BundledPlaywrightBrowsers = Join-Path $DistDir "ms-playwright"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = Join-Path $DistParent ("Launcher_backup_" + $Timestamp)
$MainPy = Join-Path $ProjectRoot "main.py"
$AutomationSettingsPath = Join-Path $ProjectRoot "automation_settings.template.json"
$TemplatePassportPath = Join-Path $ProjectRoot "debug_ocr\template_passport_btn.png"
$DmClickHelperPath = Join-Path $ProjectRoot "dm_click_helper.py"

Write-Host "============================================"
Write-Host " $AppName - 32-bit official release build"
Write-Host " internal build name: $InternalBuildName"
Write-Host " output: $DistDir"
Write-Host "============================================"

Step "[1/8] Check required files"
if (-not (Test-Path -LiteralPath $MainPy)) {
    Fail "Missing required file: main.py"
}
if (-not (Test-Path -LiteralPath $AutomationSettingsPath)) {
    Fail "Missing required file: automation_settings.template.json"
}
if (-not (Test-Path -LiteralPath $TemplatePassportPath)) {
    Fail "Missing required file: debug_ocr\template_passport_btn.png"
}

Step "[2/8] Check 32-bit Python and PyInstaller"
& py -3.14-32 --version
if ($LASTEXITCODE -ne 0) {
    Fail "32-bit Python py -3.14-32 was not found."
}
$PythonInfo = (& py -3.14-32 -c "import sys, struct; print(sys.executable); print(str(struct.calcsize('P') * 8) + '-bit')")
if ($LASTEXITCODE -ne 0) {
    Fail "Unable to inspect py -3.14-32."
}
Write-Host "  python: $($PythonInfo[0])"
Write-Host "  arch: $($PythonInfo[1])"
& py -3.14-32 -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail "32-bit PyInstaller was not found. Install it with: py -3.14-32 -m pip install pyinstaller"
}
$PyInstallerVersion = (& py -3.14-32 -m PyInstaller --version)
Write-Host "  pyinstaller: $PyInstallerVersion"

Step "[3/8] Check Playwright Chromium for 32-bit Python"
if (-not (Test-Path -LiteralPath $PlaywrightBrowsers)) {
    Fail "Missing Playwright browser cache: $PlaywrightBrowsers. Run: py -3.14-32 -m playwright install chromium"
}
$ExpectedChromiumDirName = Get-PlaywrightChromiumDirName32
if ([string]::IsNullOrWhiteSpace($ExpectedChromiumDirName)) {
    $availableChromiumDirs = Get-ChromiumDirs $PlaywrightBrowsers | Sort-Object LastWriteTime -Descending
    if ($availableChromiumDirs.Count -eq 0) {
        Fail "No chromium-* directory found under $PlaywrightBrowsers."
    }
    $ExpectedChromiumDirName = $availableChromiumDirs[0].Name
    Write-Host "  warning: browsers.json revision not found; selected latest local Chromium: $ExpectedChromiumDirName"
} else {
    Write-Host "  expected Chromium from py -3.14-32 Playwright: $ExpectedChromiumDirName"
}
$SourceChromiumDir = Join-Path $PlaywrightBrowsers $ExpectedChromiumDirName
$SourceChromiumExe = Join-Path $SourceChromiumDir "chrome-win64\chrome.exe"
if (-not (Test-Path -LiteralPath $SourceChromiumExe)) {
    Fail "Missing 32-bit Playwright Chromium chrome.exe: $SourceChromiumExe. Run: py -3.14-32 -m playwright install chromium"
}
Write-Host "  source Chromium: $SourceChromiumExe"
$env:PLAYWRIGHT_BROWSERS_PATH = $PlaywrightBrowsers

Step "[4/8] Run 32-bit validation"
& py -3.14-32 -m compileall -q main.py douluo_launcher tests tools
if ($LASTEXITCODE -ne 0) {
    Fail "compileall failed."
}
& py -3.14-32 -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    Fail "unittest failed."
}

Step "[5/8] Backup existing official release directory"
New-Item -ItemType Directory -Force -Path $DistParent | Out-Null
if (Test-Path -LiteralPath $DistDir) {
    Copy-Directory $DistDir $BackupDir
    Write-Host "  backed up: $DistDir -> $BackupDir"
} else {
    Write-Host "  no existing dist\Launcher to back up"
}

Step "[6/8] Build main executable with py -3.14-32"
$MainWorkDir = Join-Path $ProjectRoot "build\launcher_32bit"
$MainSpecDir = Join-Path $ProjectRoot "build\launcher_32bit_spec"
Remove-IfExists $MainWorkDir
Remove-IfExists $MainSpecDir
$PyInstallerArgs = @(
    "--onedir",
    "--clean",
    "-y",
    "--noconsole",
    "--name", $InternalBuildName,
    "--distpath", $DistParent,
    "--workpath", $MainWorkDir,
    "--specpath", $MainSpecDir,
    "--add-data", "$AutomationSettingsPath;.",
    "--add-data", "$TemplatePassportPath;debug_ocr",
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
    $MainPy
)
& py -3.14-32 -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    Fail "32-bit PyInstaller main build failed."
}
$GeneratedDir = Join-Path $DistParent $InternalBuildName
if (-not (Test-Path -LiteralPath $GeneratedDir)) {
    Fail "PyInstaller output directory was not generated: $GeneratedDir"
}
if (Test-Path -LiteralPath $DistDir) {
    Remove-Item -LiteralPath $DistDir -Recurse -Force
}
Rename-Item -LiteralPath $GeneratedDir -NewName $ReleaseDirName
if (-not (Test-Path -LiteralPath $InternalExePath)) {
    Fail "Internal exe was not generated: $InternalExePath"
}
if (Test-Path -LiteralPath $ExePath) {
    Remove-Item -LiteralPath $ExePath -Force
}
Rename-Item -LiteralPath $InternalExePath -NewName "$AppName.exe"
Write-Host "  renamed: $InternalBuildName.exe -> $AppName.exe"

Step "[7/8] Copy official runtime resources"
Copy-Item -LiteralPath "automation_settings.template.json" -Destination $DistDir -Force
Write-Host "  copied: automation_settings.template.json"

Copy-Item -LiteralPath "dm_click_helper.py" -Destination $DistDir -Force
Write-Host "  copied: dm_click_helper.py"

Write-Host "  building: dm_click_helper.exe (32-bit)"
$HelperWorkDir = Join-Path $ProjectRoot "build\dm_click_helper_32bit"
$HelperSpecDir = Join-Path $ProjectRoot "build\dm_click_helper_32bit_spec"
Remove-IfExists $HelperWorkDir
Remove-IfExists $HelperSpecDir
& py -3.14-32 -m PyInstaller `
    --onefile `
    --clean `
    -y `
    --noconsole `
    --name dm_click_helper `
    --distpath $DistDir `
    --workpath $HelperWorkDir `
    --specpath $HelperSpecDir `
    $DmClickHelperPath
if ($LASTEXITCODE -ne 0) {
    Fail "dm_click_helper.exe 32-bit build failed."
}
if (-not (Test-Path -LiteralPath (Join-Path $DistDir "dm_click_helper.exe"))) {
    Fail "dm_click_helper.exe was not generated."
}

$DebugDir = Join-Path $DistDir "debug_ocr"
New-Item -ItemType Directory -Force -Path $DebugDir | Out-Null
Copy-Item -LiteralPath "debug_ocr\template_passport_btn.png" -Destination $DebugDir -Force
Write-Host "  copied: debug_ocr\template_passport_btn.png"

$TargetChromiumDir = Join-Path $BundledPlaywrightBrowsers $ExpectedChromiumDirName
Copy-Directory $SourceChromiumDir $TargetChromiumDir
$bundledChromiumDirs = Get-ChromiumDirs $BundledPlaywrightBrowsers
foreach ($dir in $bundledChromiumDirs) {
    if ($dir.Name -ne $ExpectedChromiumDirName) {
        Remove-Item -LiteralPath $dir.FullName -Recurse -Force
    }
}
$bundledChromiumDirs = Get-ChromiumDirs $BundledPlaywrightBrowsers
if ($bundledChromiumDirs.Count -ne 1) {
    Fail "Bundled Chromium directory count is invalid: $($bundledChromiumDirs.Count)"
}
$BundledChromiumExe = Join-Path $TargetChromiumDir "chrome-win64\chrome.exe"
if (-not (Test-Path -LiteralPath $BundledChromiumExe)) {
    Fail "Bundled Chromium chrome.exe is missing: $BundledChromiumExe"
}
Write-Host "  copied: ms-playwright\$ExpectedChromiumDirName"

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

Step "[8/8] Clean and verify official release directory"
Remove-IfExists (Join-Path $DistDir "logs")
Remove-IfExists (Join-Path $DistDir "slots")
Remove-IfExists (Join-Path $DistDir "debug_background")
Remove-IfExists (Join-Path $DistDir "debug_ocr_tmp")
Remove-IfExists (Join-Path $DebugDir "_tmp")
Remove-IfExists (Join-Path $DebugDir "history")
Remove-IfExists (Join-Path $DistDir "window_manager_settings.json")
Remove-IfExists (Join-Path $DistDir "window_slots.json")
Remove-IfExists (Join-Path $DistDir "live_result.json")
Remove-IfExists (Join-Path $DistDir "live_runner.log")
Get-ChildItem -LiteralPath $DistDir -Recurse -Filter "*.log" -File -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Filter "*.csv" -File -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Filter "window_slots*.json" -File -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Directory -Filter ".pytest_cache" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $DistDir -Recurse -Filter "*.pyc" -File -ErrorAction SilentlyContinue | Remove-Item -Force

if (-not (Test-Path -LiteralPath $ExePath)) {
    Fail "exe was not generated: $ExePath"
}
if (-not (Test-Path -LiteralPath (Join-Path $DistDir "dm_click_helper.exe"))) {
    Fail "dm_click_helper.exe missing after cleanup."
}
if (-not (Test-Path -LiteralPath (Join-Path $DebugDir "template_passport_btn.png"))) {
    Fail "template_passport_btn.png missing after cleanup."
}
if (-not (Test-Path -LiteralPath $BundledChromiumExe)) {
    Fail "bundled Chromium missing after cleanup: $BundledChromiumExe"
}
if (Test-Path -LiteralPath (Join-Path $DistDir "window_manager_settings.json")) {
    Fail "window_manager_settings.json must not be included in the release directory."
}

Write-Host ""
Write-Host "============================================"
Write-Host "32-bit release build completed."
Write-Host "  exe: $ExePath"
Write-Host "  dir: $DistDir"
Write-Host "  backup: $BackupDir"
Write-Host "  python: $($PythonInfo[0])"
Write-Host "  pyinstaller: $PyInstallerVersion"
Write-Host "  chromium: $ExpectedChromiumDirName"
Write-Host "============================================"
exit 0
