# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('assets', 'assets'), ('scrcpy-win64-v2.7', 'scrcpy-win64-v2.7')]
datas += collect_data_files('flet')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['flet', 'core.adb', 'core.paths', 'core.config', 'core.logger', 'core.monkey_run', 'core.test_wallpaper', 'ui.styles', 'subtools.perfetto_view', 'subtools.monkey_view', 'subtools.log_check_view', 'subtools.language_view', 'subtools.settings_view'],
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
    name='test_tool_flet_debug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='test_tool_flet_debug',
)
