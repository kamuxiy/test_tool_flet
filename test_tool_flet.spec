# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('scrcpy-win64-v2.7', 'scrcpy-win64-v2.7')],
    hiddenimports=['core.adb', 'core.paths', 'core.config', 'core.user_prefs', 'core.logger', 'core.monkey_run', 'core.test_wallpaper', 'ui.styles', 'subtools.perfetto_view', 'subtools.monkey_view', 'subtools.log_check_view', 'subtools.language_view', 'subtools.settings_view', 'subtools.scrcpy_view', 'subtools.screenshots_view'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='test_tool_flet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='D:\\Users\\W8076967\\AppData\\Local\\Temp\\95b6359b-b950-49f4-9186-6734d9143bfc',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='test_tool_flet',
)
