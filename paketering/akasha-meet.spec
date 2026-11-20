# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-spec for Akasha Meet. Samma fil bygger Mac-programmet (Akasha Meet.app) och
# provbygget pa Linux (en vanlig katalog med start.py som startfil).
#   pyinstaller --noconfirm --clean --distpath UT/dist --workpath UT/pyi paketering/akasha-meet.spec
# Miljovariablerna nedan satts bara av byggskripten; de ror inte app/.
import os
import sys

ROT = os.path.dirname(SPECPATH)  # SPECPATH ar paketering/
MAC = sys.platform == "darwin"

WHISPER_CLI = os.environ.get("AKASHA_WHISPER_CLI")
IKON = os.environ.get("AKASHA_IKON") or None
VERSION = os.environ.get("AKASHA_VERSION", "0.2.0")
BYGGNUMMER = os.environ.get("AKASHA_BYGGNUMMER", "1")

if MAC and not WHISPER_CLI:
    raise SystemExit("AKASHA_WHISPER_CLI saknas: kor paketering/bygg-whisper-cli.sh forst")

a = Analysis(
    [os.path.join(ROT, "app", "mac_app.py" if MAC else "start.py")],
    pathex=[os.path.join(ROT, "app")],
    # whisper-cli hamnar i Contents/Frameworks (= sys._MEIPASS), dar PyInstaller signerar den.
    binaries=[(WHISPER_CLI, ".")] if MAC else [],
    # Flask hittar static/ via modulen app, som i det frysta programmet ligger i sys._MEIPASS.
    datas=[(os.path.join(ROT, "app", "static"), "static")],
    hiddenimports=["app", "start", "ljud", "av", "sherpa_onnx", "truststore", "waitress"]
    + (["AppKit", "Foundation", "objc", "PyObjCTools.AppHelper"] if MAC else []),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # faster-whisper-stacken foljer inte med (A6): motorn ar whisper.cpp och ljud.py avkodar med PyAV.
    excludes=["faster_whisper", "ctranslate2", "tokenizers", "huggingface_hub", "hf_xet", "onnxruntime", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

NAMN = "Akasha Meet" if MAC else "akasha-meet"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAMN,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=not MAC,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64" if MAC else None,
    codesign_identity=None,  # ingen identitet: PyInstaller signerar ad hoc
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=NAMN,
)

if MAC:
    app = BUNDLE(
        coll,
        name="Akasha Meet.app",
        icon=IKON,
        bundle_identifier="io.github.jamesmcstrid.akashameet",
        version=VERSION,
        info_plist={
            "CFBundleName": "Akasha Meet",
            "CFBundleDisplayName": "Akasha Meet",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": BYGGNUMMER,
            "LSMinimumSystemVersion": "14.0",
            "LSArchitecturePriority": ["arm64"],
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHumanReadableCopyright": "© 2026 Dennis Fredin. Apache-2.0.",
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",  # behovs for retina-upplosning (PyInstallers dokumentation)
        },
    )
