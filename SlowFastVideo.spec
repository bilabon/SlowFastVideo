# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None

project_dir = os.path.abspath(".")
app_name = "SlowFastVideo"
icon_path = os.path.join(project_dir, "SlowFastVideo.icns")  # если иконки нет — поставь None

a = Analysis(
    ['SlowFastVideo.py'],
    pathex=[project_dir],
    binaries=[
        ('ffmpeg', '.'),   # вложим ffmpeg рядом с исполняемым файлом внутри бандла
        ('ffprobe', '.'),
    ],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,   # оставляем стандарт
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,   # важный момент: передаём бинарники прямо в EXE -> onefile
    a.datas,
    [],
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # на macOS лучше без UPX
    upx_exclude=[],
    runtime_tmpdir=None,       # распаковка во временную папку (_MEIPASS)
    console=False,             # GUI
    disable_windowed_traceback=False,
    argv_emulation=False,      # не нужно
    # На Apple Silicon можно не указывать — соберётся arm64.
    # Если хочешь зафиксировать:
    target_arch="arm64",
    codesign_identity=None,    # подпишешь позже при необходимости
    entitlements_file=None,
)

app = BUNDLE(
    exe,
    name=f'{app_name}.app',
    icon=icon_path,
    bundle_identifier='com.example.slowfastvideo',  # замени на свой
    # При необходимости можно добавить Info.plist поля:
    # info_plist={
    #     "NSHighResolutionCapable": True,
    #     "LSMinimumSystemVersion": "15.0",
    # },
)
