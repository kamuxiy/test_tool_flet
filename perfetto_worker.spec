# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('build\\perf_all_in_one_lite', 'perf_all_in_one')]
datas += collect_data_files('perfetto')


a = Analysis(
    ['perfetto_worker.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['perfetto.trace_processor', 'openpyxl', 'sqlalchemy'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['flet', 'flet_core', 'flet_desktop', 'flet_cli'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='perfetto_worker',
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
    name='perfetto_worker',
)
