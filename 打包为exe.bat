@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  Test Tool Flet - package script
echo  Output: dist\test_tool_flet\  (single folder)
echo ============================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\package.ps1"
exit /b %ERRORLEVEL%
