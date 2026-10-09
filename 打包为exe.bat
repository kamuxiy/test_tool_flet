@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  Test Tool Flet - package script
echo  Output: dist\test_tool_flet\  (single folder)
echo ============================================

if not exist "%~dp0assets\languages.py" (
    echo [ERROR] missing "%~dp0assets\languages.py"
    exit /b 1
)
if not exist "%~dp0scrcpy-win64-v2.7\scrcpy.exe" (
    echo [ERROR] missing "%~dp0scrcpy-win64-v2.7\scrcpy.exe"
    exit /b 1
)
if not exist "%~dp0perf_all_in_one\main.py" (
    echo [ERROR] missing "%~dp0perf_all_in_one\main.py"
    exit /b 1
)

echo Checking dependencies...
py -m pip install -q PyInstaller flet-cli

echo.
echo [1/4] Packing test_tool_flet.exe (flet pack)...
flet pack main.py --onedir --name test_tool_flet -y ^
    --add-data "assets;assets" ^
    --add-data "scrcpy-win64-v2.7;scrcpy-win64-v2.7" ^
    --hidden-import "core.adb" ^
    --hidden-import "core.paths" ^
    --hidden-import "core.config" ^
    --hidden-import "core.user_prefs" ^
    --hidden-import "core.logger" ^
    --hidden-import "core.monkey_run" ^
    --hidden-import "core.test_wallpaper" ^
    --hidden-import "ui.styles" ^
    --hidden-import "subtools.perfetto_view" ^
    --hidden-import "subtools.monkey_view" ^
    --hidden-import "subtools.log_check_view" ^
    --hidden-import "subtools.language_view" ^
    --hidden-import "subtools.settings_view" ^
    --hidden-import "subtools.scrcpy_view" ^
    --hidden-import "subtools.screenshots_view"
if errorlevel 1 (
    echo Pack main app failed.
    exit /b 1
)

echo.
echo [2/4] Preparing slim perf_all_in_one (drop mtrace/simpleperf)...
if exist "%~dp0build\perf_all_in_one_lite" rmdir /s /q "%~dp0build\perf_all_in_one_lite"
xcopy /e /i /q "%~dp0perf_all_in_one" "%~dp0build\perf_all_in_one_lite" >nul
if exist "%~dp0build\perf_all_in_one_lite\lib\mtrace" rmdir /s /q "%~dp0build\perf_all_in_one_lite\lib\mtrace"
if exist "%~dp0build\perf_all_in_one_lite\lib\simpleperf" rmdir /s /q "%~dp0build\perf_all_in_one_lite\lib\simpleperf"
echo Slim copy done.

echo.
echo [3/4] Building worker into build\ (not a separate dist product)...
if exist "%~dp0build\pw_dist" rmdir /s /q "%~dp0build\pw_dist"
if exist "%~dp0build\pw_work" rmdir /s /q "%~dp0build\pw_work"
py -m PyInstaller --noconfirm --clean --onedir --console ^
    --name perfetto_worker ^
    --distpath "build\pw_dist" ^
    --workpath "build\pw_work" ^
    --specpath "build" ^
    --add-data "%~dp0build\perf_all_in_one_lite;perf_all_in_one" ^
    --collect-data "perfetto" ^
    --hidden-import "perfetto.trace_processor" ^
    --hidden-import "openpyxl" ^
    --hidden-import "sqlalchemy" ^
    --exclude-module "flet" ^
    --exclude-module "flet_core" ^
    --exclude-module "flet_desktop" ^
    --exclude-module "flet_cli" ^
    perfetto_worker.py
if errorlevel 1 (
    echo Pack worker failed.
    exit /b 1
)

echo.
echo [4/4] Assemble single dist\test_tool_flet\ ...
if not exist "dist\test_tool_flet\test_tool_flet.exe" (
    echo [ERROR] main exe missing under dist\test_tool_flet\
    exit /b 1
)
if exist "dist\test_tool_flet\perfetto_worker" (
    rmdir /s /q "dist\test_tool_flet\perfetto_worker"
)
xcopy /e /i /q "build\pw_dist\perfetto_worker" "dist\test_tool_flet\perfetto_worker" >nul
if errorlevel 1 (
    echo Copy worker into test_tool_flet failed.
    exit /b 1
)

REM Remove leftover standalone worker under dist\ (if any from old builds)
if exist "dist\perfetto_worker" (
    rmdir /s /q "dist\perfetto_worker"
)

echo.
echo ============================================
echo Package done!
echo Dist folder ONLY: dist\test_tool_flet\
echo Run: dist\test_tool_flet\test_tool_flet.exe
echo ============================================
exit /b 0
