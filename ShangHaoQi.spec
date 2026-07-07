# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('automation_settings.json', '.'), ('debug_ocr\\template_passport_btn.png', 'debug_ocr')],
    hiddenimports=['PIL', 'pytesseract', 'cv2', 'win32com', 'win32gui', 'win32con', 'playwright.sync_api', 'douluo_launcher', 'douluo_launcher.config', 'douluo_launcher.automation', 'douluo_launcher.dm_client', 'douluo_launcher.gui'],
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
    name='ShangHaoQi',
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
    name='ShangHaoQi',
)
