# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

import sshuttle

block_cipher = None
project_dir = Path(SPECPATH)
icon_path = project_dir / "img" / "logo.png"
icns_path = project_dir / "img" / "logo.icns"
ico_path = project_dir / "img" / "logo.ico"
sshuttle_dir = Path(next(iter(sshuttle.__path__)))

hiddenimports = collect_submodules("sshuttle") + [
    "pexpect",
    "pexpect.popen_spawn",
    "ptyprocess",
    "tkinter",
    "tkinter.ttk",
]

if sys.platform == "win32" and ico_path.exists():
    exe_icon = str(ico_path)
elif sys.platform == "darwin":
    exe_icon = None
elif icon_path.exists():
    exe_icon = str(icon_path)
else:
    exe_icon = None

a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[
        (str(project_dir / "img" / "logo.png"), "img"),
        (str(sshuttle_dir), "sshuttle"),
    ],
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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=exe_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
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
