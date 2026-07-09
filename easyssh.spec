# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
project_dir = Path(SPECPATH)
icon_path = project_dir / "img" / "logo.png"
icns_path = project_dir / "img" / "logo.icns"

hiddenimports = collect_submodules("sshuttle") + [
    "pexpect",
    "ptyprocess",
    "tkinter",
    "tkinter.ttk",
]

a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[(str(project_dir / "img" / "logo.png"), "img")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EasySSH",
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
    icon=str(icon_path) if icon_path.exists() and sys.platform != "darwin" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EasySSH",
)

if sys.platform == "darwin":
    app_icon = icns_path if icns_path.exists() else icon_path
    app = BUNDLE(
        coll,
        name="EasySSH.app",
        icon=str(app_icon),
        bundle_identifier="com.easyssh.app",
    )
