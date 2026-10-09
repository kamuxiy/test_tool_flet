# Package Test Tool Flet into a single dist\test_tool_flet\ folder.
# Mirrors 打包为exe.bat for local Windows use and GitHub Actions.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "============================================"
Write-Host " Test Tool Flet - package script"
Write-Host " Output: dist\test_tool_flet\  (single folder)"
Write-Host "============================================"

function Require-Path([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "[ERROR] missing $Label : $Path"
    }
}

Require-Path (Join-Path $Root "assets\languages.py") "assets/languages.py"
Require-Path (Join-Path $Root "scrcpy-win64-v2.7\scrcpy.exe") "scrcpy"
Require-Path (Join-Path $Root "perf_all_in_one\main.py") "perf_all_in_one"

Write-Host "Checking dependencies..."
python -m pip install -q PyInstaller "flet-cli==0.85.3"

Write-Host ""
Write-Host "[1/4] Packing test_tool_flet.exe (flet pack)..."
flet pack main.py --onedir --name test_tool_flet -y `
    --add-data "assets;assets" `
    --add-data "scrcpy-win64-v2.7;scrcpy-win64-v2.7" `
    --hidden-import "core.adb" `
    --hidden-import "core.paths" `
    --hidden-import "core.config" `
    --hidden-import "core.user_prefs" `
    --hidden-import "core.logger" `
    --hidden-import "core.monkey_run" `
    --hidden-import "core.test_wallpaper" `
    --hidden-import "ui.styles" `
    --hidden-import "subtools.perfetto_view" `
    --hidden-import "subtools.monkey_view" `
    --hidden-import "subtools.log_check_view" `
    --hidden-import "subtools.language_view" `
    --hidden-import "subtools.settings_view" `
    --hidden-import "subtools.scrcpy_view" `
    --hidden-import "subtools.screenshots_view"
if ($LASTEXITCODE -ne 0) { throw "Pack main app failed." }

Write-Host ""
Write-Host "[2/4] Preparing slim perf_all_in_one (drop mtrace/simpleperf)..."
$Lite = Join-Path $Root "build\perf_all_in_one_lite"
if (Test-Path $Lite) { Remove-Item $Lite -Recurse -Force }
Copy-Item (Join-Path $Root "perf_all_in_one") $Lite -Recurse
$DropMtrace = Join-Path $Lite "lib\mtrace"
$DropSimple = Join-Path $Lite "lib\simpleperf"
if (Test-Path $DropMtrace) { Remove-Item $DropMtrace -Recurse -Force }
if (Test-Path $DropSimple) { Remove-Item $DropSimple -Recurse -Force }
Write-Host "Slim copy done."

Write-Host ""
Write-Host "[3/4] Building worker into build\ (not a separate dist product)..."
$PwDist = Join-Path $Root "build\pw_dist"
$PwWork = Join-Path $Root "build\pw_work"
if (Test-Path $PwDist) { Remove-Item $PwDist -Recurse -Force }
if (Test-Path $PwWork) { Remove-Item $PwWork -Recurse -Force }

python -m PyInstaller --noconfirm --clean --onedir --console `
    --name perfetto_worker `
    --distpath $PwDist `
    --workpath $PwWork `
    --specpath (Join-Path $Root "build") `
    --add-data "$Lite;perf_all_in_one" `
    --collect-data "perfetto" `
    --hidden-import "perfetto.trace_processor" `
    --hidden-import "openpyxl" `
    --hidden-import "sqlalchemy" `
    --exclude-module "flet" `
    --exclude-module "flet_core" `
    --exclude-module "flet_desktop" `
    --exclude-module "flet_cli" `
    (Join-Path $Root "perfetto_worker.py")
if ($LASTEXITCODE -ne 0) { throw "Pack worker failed." }

Write-Host ""
Write-Host "[4/4] Assemble single dist\test_tool_flet\ ..."
$MainExe = Join-Path $Root "dist\test_tool_flet\test_tool_flet.exe"
Require-Path $MainExe "main exe"

$WorkerDest = Join-Path $Root "dist\test_tool_flet\perfetto_worker"
if (Test-Path $WorkerDest) { Remove-Item $WorkerDest -Recurse -Force }
Copy-Item (Join-Path $PwDist "perfetto_worker") $WorkerDest -Recurse

$OrphanWorker = Join-Path $Root "dist\perfetto_worker"
if (Test-Path $OrphanWorker) { Remove-Item $OrphanWorker -Recurse -Force }

Write-Host ""
Write-Host "============================================"
Write-Host "Package done!"
Write-Host "Dist folder ONLY: dist\test_tool_flet\"
Write-Host "Run: dist\test_tool_flet\test_tool_flet.exe"
Write-Host "============================================"
