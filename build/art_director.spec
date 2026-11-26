# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform PyInstaller spec for Art Director standalone executable."""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ASSETS_DIR = PROJECT_ROOT / "art_director" / "assets"

datas = [
    (str(ASSETS_DIR / "art_director.ico"), "assets"),
    (str(ASSETS_DIR / "art_director.png"), "assets"),
]
binaries = []
hiddenimports = [
    "mido.backends.rtmidi",
    "pythonosc",
    "pythonosc.udp_client",
    "websocket",
    "psutil",
    "PySide6.QtNetwork",
]

for pkg in ("vosk", "sounddevice", "onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

try:
    d, b, h = collect_all("_sounddevice_data")
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass

datas += collect_data_files("faster_whisper")
datas += collect_data_files("certifi")
binaries += collect_dynamic_libs("ctranslate2")
hiddenimports += collect_submodules("pynput")
hiddenimports += collect_submodules("rtmidi")
hiddenimports += collect_submodules("faster_whisper")
hiddenimports += collect_submodules("ctranslate2")
hiddenimports += collect_submodules("huggingface_hub")
hiddenimports += collect_submodules("httpx2")
hiddenimports += collect_submodules("hf_xet")
hiddenimports += collect_submodules("tokenizers")

excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtSvgWidgets",
    "tkinter",
    "matplotlib",
    "scipy",
    "pandas",
]

a = Analysis(
    [str(PROJECT_ROOT / "run_art_director.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="ArtDirector",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=str(ASSETS_DIR / "art_director.png"),
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="ArtDirector",
    )
    app = BUNDLE(
        coll,
        name="ArtDirector.app",
        icon=str(ASSETS_DIR / "art_director.png"),
        bundle_identifier="com.artdirector.stagevoice",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="ArtDirector",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        icon=str(ASSETS_DIR / ("art_director.ico" if sys.platform == "win32" else "art_director.png")),
    )
