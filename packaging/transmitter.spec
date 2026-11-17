# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

block_cipher = None

sd_datas, sd_binaries, sd_hidden = collect_all("sounddevice")
sc_datas, sc_binaries, sc_hidden = collect_all("soundcard")
pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
shiboken_datas, shiboken_binaries, shiboken_hidden = collect_all("shiboken6")

a = Analysis(
    ["../run_transmitter.py"],
    pathex=[".."],
    binaries=sd_binaries + sc_binaries + pyside_binaries + shiboken_binaries,
    datas=sd_datas + sc_datas + pyside_datas + shiboken_datas,
    hiddenimports=sd_hidden
    + sc_hidden
    + pyside_hidden
    + shiboken_hidden
    + [
        "numpy",
        "sounddevice",
        "soundcard",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "shared",
        "shared.protocol",
        "shared.config",
        "shared.audio_devices",
        "transmitter",
        "transmitter.app",
        "transmitter.capture",
        "transmitter.sender",
        "transmitter.gui",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sound-transmitter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="sound-transmitter",
)
