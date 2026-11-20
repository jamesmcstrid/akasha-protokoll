# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-spec for Akasha Protokoll. Samma fil bygger Mac-programmet (Akasha Protokoll.app), Windows-programmet
# (en katalog med Akasha Protokoll.exe och _internal, med windows_app.py som startfil) och provbygget pa Linux
# (en vanlig katalog med start.py som startfil).
#   pyinstaller --noconfirm --clean --distpath UT/dist --workpath UT/pyi paketering/akasha-protokoll.spec
# Miljovariablerna nedan satts bara av byggskripten; de ror inte app/.
import glob
import os
import shutil
import sys

ROT = os.path.dirname(SPECPATH)  # SPECPATH ar paketering/
MAC = sys.platform == "darwin"
WIN = sys.platform == "win32"

WHISPER_CLI = os.environ.get("AKASHA_WHISPER_CLI")
IKON = os.environ.get("AKASHA_IKON") or None
WHISPER_KATALOG = os.environ.get("AKASHA_WHISPER_KATALOG")  # Windows: katalogen med whisper-cli.exe och DLL-filerna
VERSIONSFIL = os.environ.get("AKASHA_VERSIONSFIL") or None  # Windows: skrivs av bygg_windows_verktyg.py
VERSION = os.environ.get("AKASHA_VERSION", "0.2.0")
BYGGNUMMER = os.environ.get("AKASHA_BYGGNUMMER", "1")

if MAC and not WHISPER_CLI:
    raise SystemExit("AKASHA_WHISPER_CLI saknas: kor paketering/bygg-whisper-cli.sh forst")
if WIN and not (WHISPER_KATALOG and os.path.isdir(WHISPER_KATALOG)):
    raise SystemExit("AKASHA_WHISPER_KATALOG saknas eller ar ingen katalog: kor paketering/bygg-whisper-cli-windows.sh forst")

# Windows: whisper-cli.exe och alla DLL-filer bredvid den hamnar i _internal/whisper/ (plattform.whisper_cli() letar dar).
# Utan whisper-cli.exe i katalogen bygger PyInstaller anda (sa att en korning visar vad mer som felar);
# bygg_windows.sh stoppar sedan med FEL.
WHISPER_FILER = sorted(f for f in glob.glob(os.path.join(WHISPER_KATALOG, "*")) if os.path.isfile(f)) if WIN else []
if WIN and not any(os.path.basename(f).lower() == "whisper-cli.exe" for f in WHISPER_FILER):
    print("VARNING: whisper-cli.exe saknas i " + WHISPER_KATALOG)

# Windows: bilden till ikonen vid klockan heter ikon.png i programmet (plattform.ikonfil()).
IKON_PNG = None
if WIN:
    IKON_PNG = os.path.join(workpath, "ikon.png")
    os.makedirs(workpath, exist_ok=True)
    shutil.copyfile(os.path.join(ROT, "paketering", "ikon-1024.png"), IKON_PNG)

a = Analysis(
    [os.path.join(ROT, "app", "mac_app.py" if MAC else "windows_app.py" if WIN else "start.py")],
    pathex=[os.path.join(ROT, "app")],
    # whisper-cli hamnar i Contents/Frameworks (= sys._MEIPASS), dar PyInstaller signerar den.
    binaries=[(WHISPER_CLI, ".")] if MAC else [(f, "whisper") for f in WHISPER_FILER],
    # Flask hittar static/ via modulen app, som i det frysta programmet ligger i sys._MEIPASS.
    datas=[(os.path.join(ROT, "app", "static"), "static")] + ([(IKON_PNG, ".")] if WIN else []),
    hiddenimports=["app", "start", "ljud", "av", "sherpa_onnx", "truststore", "waitress"]
    + (["AppKit", "Foundation", "objc", "PyObjCTools.AppHelper"] if MAC else [])
    + (["pystray", "pystray._win32", "PIL.Image"] if WIN else []),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # faster-whisper-stacken foljer inte med (A6): motorn ar whisper.cpp och ljud.py avkodar med PyAV.
    excludes=["faster_whisper", "ctranslate2", "tokenizers", "huggingface_hub", "hf_xet", "onnxruntime", "tkinter"],
    noarchive=False,
    optimize=0,
    # pystray ar LGPLv3: dess kod ligger som vanliga .py-filer i programmet, inte inbakad i arkivet, sa att den gar att byta ut.
    **({"module_collection_mode": {"pystray": "py"}} if WIN else {}),
)
pyz = PYZ(a.pure)

NAMN = "Akasha Protokoll" if (MAC or WIN) else "akasha-protokoll"

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
    console=not (MAC or WIN),  # Windows: fonsterprogram (runw.exe), ingen konsol
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64" if MAC else None,
    codesign_identity=None,  # ingen identitet: PyInstaller signerar ad hoc
    entitlements_file=None,
    **({"icon": IKON, "version": VERSIONSFIL} if WIN else {}),
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
        name="Akasha Protokoll.app",
        icon=IKON,
        bundle_identifier="io.github.jamesmcstrid.akashaprotokoll",
        version=VERSION,
        info_plist={
            "CFBundleName": "Akasha Protokoll",
            "CFBundleDisplayName": "Akasha Protokoll",
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
