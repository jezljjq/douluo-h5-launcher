# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('automation_settings.template.json', '.'), ('debug_ocr\\template_passport_btn.png', 'debug_ocr')]
binaries = []
hiddenimports = ['PIL', 'pytesseract', 'cv2', 'tkinterdnd2', 'win32com', 'win32gui', 'win32con', 'playwright.sync_api', 'douluo_launcher', 'douluo_launcher.config', 'douluo_launcher.automation', 'douluo_launcher.dm_client', 'douluo_launcher.gui']
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='Launcher',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='斗罗大陆H5上号器-v1.3.0',
)
