"""Samlar licenstexterna for allt som foljer med programmet i en katalog licenser/: en fil per komponent (hela
licenstexten med upphovsrattsraderna) och forteckningen LICENSER.txt (en rad per komponent).

Kors av spec-filen (paketering/akasha-protokoll.spec) direkt efter PyInstallers analys. Python-paketen ar da de
distributioner som ager nagon av filerna som Analysis tog med (a.pure, a.scripts, a.binaries, a.datas, kallsokvagarna
jamforda med paketens RECORD), sa att det som excludes utesluter och det som aldrig importeras inte kommer med.
For ett prov utan PyInstaller (alla installerade paket utom byggverktygen och det som spec-filen utesluter):

    python paketering/samla_licenser.py --ut KATALOG --plattform windows|mac|linux --alla-installerade [--prov]
           [--version 0.2.0] [--whisper-licens KATALOG] [--ffmpeg-licenser KATALOG]

Komponenterna:
  - Akasha Protokoll (LICENSE och NOTICE) och typsnitten (OFL-texterna i app/static/typsnitt/),
  - varje Python-paket: licensfilerna ur paketet (LICENSE*, LICENCE*, COPYING*, NOTICE*, AUTHORS*), och licensen ur
    License-Expression, License eller klassificeringen. Ett paket utan licensfil ar FEL, utom de i SAMMA_PROJEKT, som
    far texten fran ett paket ur samma projekt med samma version,
  - biblioteken som ett paket bar med sig (av.libs, numpy.libs, sherpa_onnx/lib, .dylibs ...): vart och ett ska tackas
    av FFmpeg-komponenten (PyAV), Visual C++-runtimen, ett eget bibliotek i paketet, en text i paketering/licenstexter/
    (TILLAGG) eller paketets egen licenstext (som ska namna biblioteket). Annars FEL,
  - Python (PSF, LICENSE.txt ur den Python som bygger), whisper.cpp (Mac och Windows: KATALOG/LICENSE och KALLA.txt fran
    bygg-whisper-cli*.sh), FFmpeg (om PyAV foljer med: KATALOG/ut/ffmpeg fran bygg-ffmpeg.sh, och bara det egna
    LGPL-bygget godtas), GCC-runtimen (om bygg-ffmpeg.sh lade COPYING3 och COPYING.RUNTIME dar) och Visual C++-runtimen
    (Windows: DLL-filerna som finns i programmet, och var villkoren star).
Det som saknas ar FEL: kommandot ger slutkod 1. I bygget skriver spec-filen felen och bygger vidare, och LICENSER.txt
borjar da med OFULLSTANDIG, sa att kontrollen (kontrollera_licenser.py) stoppar bygget. --prov hoppar over whisper.cpp,
FFmpeg och GCC-runtimen och markerar forteckningen PROV (som kontrollen ocksa stoppar).
"""
import argparse
import importlib.metadata
import os
import platform
import re
import shutil
import sys
import sysconfig
import tempfile
from dataclasses import dataclass, field

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TILLAGGSKATALOG = os.path.join(ROT, "paketering", "licenstexter")
FORTECKNING = "LICENSER.txt"
SEP = " | "
STRECK = "---"
MARKERING_OFULLSTANDIG = "OFULLSTÄNDIG"
MARKERING_PROV = "PROV"
REPO = "https://github.com/jamesmcstrid/akasha-protokoll"
PLATTFORMSNAMN = {"mac": "Mac", "windows": "Windows", "linux": "Linux (provbygge)"}

LICENSFIL = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.I)
# Bara for --alla-installerade (provet): byggverktygen och det som spec-filen utesluter (excludes). I bygget avgor
# PyInstallers analys vad som foljer med.
BYGGVERKTYG = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "macholib", "pefile",
               "pywin32-ctypes", "packaging", "delvewheel", "delocate", "auditwheel", "patchelf", "cython"}
UTESLUTNA = {"faster-whisper", "ctranslate2", "tokenizers", "huggingface-hub", "hf-xet", "onnxruntime"}
# Hjul utan egen licensfil, med texten fran ett annat hjul ur samma projekt (samma version kravs).
SAMMA_PROJEKT = {
    "sherpa-onnx-core": ("sherpa-onnx", "Hjulet sherpa-onnx-core har ingen licensfil. Det hör till samma projekt "
                                        "(k2-fsa/sherpa-onnx) och samma version som sherpa-onnx, vars licens står nedan."),
    "pyobjc-core": ("pyobjc-framework-cocoa", "Hjulet pyobjc-core har ingen licensfil. Det hör till samma projekt "
                                              "(ronaldoussoren/pyobjc) och samma version som pyobjc-framework-Cocoa, vars "
                                              "licens står nedan."),
}
# Licenstexter for bibliotek som ett hjul bar med sig utan texten. Texterna ligger i paketering/licenstexter/<katalog>/
# (KALLA.txt sager varifran). Versionen ar paketets: en ny version maste kontrolleras (vilket bibliotek, vilken version).
TILLAGG = [
    {"paket": "sherpa-onnx-core", "version": "2.0.1", "bibliotek": re.compile(r"onnxruntime", re.I),
     "katalog": "onnxruntime-1.28.2", "namn": "ONNX Runtime 1.28.2 (MIT, Microsoft)"},
]
# Den korta licensen i forteckningen nar paketets metadata ar for lang eller oklar (hela texten star alltid i filen).
LICENS_KORT = {
    "sherpa-onnx": "Apache-2.0",
    "pyinstaller": "GPL-2.0-or-later med undantag för startprogrammet; körtidskrokarna Apache-2.0",
}
NOTER = {
    "pystray": "pystray är LGPL-3.0. Dess kod ligger som vanliga .py-filer i programmet (_internal\\pystray), inte "
               "inbakad i arkivet, så att du kan byta ut den mot en egen version. LGPL-3.0 är ett tillägg till GPL-3.0, "
               "och båda texterna står nedan.",
    "pyinstaller": "PyInstaller bygger programmet. Det som följer med är startprogrammet (bootloader) och körtidskrokarna; "
                   "undantagen i texten nedan gör att programmet inte behöver vara under GPL.",
}
MSVC = re.compile(r"^(msvcp|vcruntime|vcomp|concrt|vccorlib)140(_[a-z0-9_]+)?(-[0-9a-f]{8,})?\.dll$", re.I)
FFMPEG_BIBLIOTEK = ("avutil", "avcodec", "avformat", "avfilter", "avdevice", "swresample", "swscale")
FFMPEG_NAMN = re.compile(r"^(?:lib)?(" + "|".join(FFMPEG_BIBLIOTEK) + r")(?=[-._])", re.I)
WHISPER_NAMN = re.compile(r"^(whisper|ggml)", re.I)
MINGW_RUNTIME = "COPYING.MinGW-w64-runtime.txt"  # bygg-ffmpeg.sh kopierar den ur MSYS2 UCRT64
WINPTHREADS = "COPYING.winpthreads.txt"  # winpthreads, statiskt inlankad i FFmpeg-DLL:erna (-static)
MINGW_TEXTER = ("COPYING3", "COPYING.RUNTIME", MINGW_RUNTIME, WINPTHREADS)
TECKEN_I_NYCKEL = re.compile(r"[a-z]+")
STOPPORD = {"core", "base", "shared", "static", "cpython", "darwin", "linux", "win32", "amd64", "x86_64", "arm64", "dylib",
            "lib", "dll", "api"}


class LicensFel(Exception):
    """Katalogen gick inte att skriva som den ska (till exempel tva komponenter med samma filnamn)."""


@dataclass
class Komponent:
    namn: str
    version: str
    licens: str
    kalla: str
    fil: str
    text: str


@dataclass
class Resultat:
    komponenter: list = field(default_factory=list)
    fel: list = field(default_factory=list)
    varningar: list = field(default_factory=list)


# --- smahjalp ---------------------------------------------------------------------------------------------------

def normnamn(namn):
    """Paketnamnet som PEP 503 jamfor det: sma bokstaver, - i stallet for _ och ."""
    return re.sub(r"[-_.]+", "-", namn).lower()


def filnamn_for(namn):
    return re.sub(r"[^a-z0-9.+-]+", "-", namn.lower()).strip("-") + ".txt"


def las_text(sokvag):
    with open(sokvag, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def falt(text):
    """En kolumn i forteckningen: en rad, utan avgransaren."""
    return " ".join(str(text).split()).replace("|", "/") or "-"


def nyckel(sokvag):
    return os.path.normcase(os.path.abspath(sokvag))


def under(sokvag, katalog):
    """Ligger sokvag under katalog (realpath, sa att symboliska lankar till Python-installationen ocksa raknas)?"""
    try:
        s = os.path.normcase(os.path.realpath(sokvag))
        k = os.path.normcase(os.path.realpath(katalog))
        return os.path.commonpath([s, k]) == k
    except ValueError:  # olika enheter pa Windows
        return False


def ar_delat_bibliotek(namn):
    """Ett delat bibliotek (dll, dylib, so) som inte ar en Python-modul (.pyd, .cpython-*.so, .abi3.so)."""
    n = namn.lower()
    if n.endswith(".pyd") or re.search(r"\.(cpython-[^.]+|abi3)\.so$", n):
        return False
    return n.endswith((".dll", ".dylib")) or n.endswith(".so") or ".so." in n


def ar_binar(sokvag):
    """Ett program eller bibliotek (efter namnet, eller de forsta byten for en fil utan andelse: whisper-cli, Python)."""
    n = os.path.basename(sokvag).lower()
    if ar_delat_bibliotek(n) or n.endswith((".pyd", ".exe")) or re.search(r"\.(cpython-[^.]+|abi3)\.so$", n):
        return True
    if "." in n:
        return False
    try:
        with open(sokvag, "rb") as f:
            borjan = f.read(4)
    except OSError:
        return False
    return borjan[:2] == b"MZ" or borjan == b"\x7fELF" or borjan in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf")


def nycklar(biblioteksnamn):
    """Orden i ett biblioteksnamn som kan sta i en licenstext: libscipy_openblas64_-4e39...dll -> {scipy, openblas}."""
    n = os.path.basename(biblioteksnamn).lower()
    n = n[3:] if n.startswith("lib") else n
    n = n.split(".")[0]
    n = re.sub(r"-[0-9a-f]{8,}$", "", n)
    return {o for o in TECKEN_I_NYCKEL.findall(n) if len(o) >= 4 and o not in STOPPORD}


def kort_licens(dist):
    m = dist.metadata
    namn = normnamn(m["Name"])
    if namn in LICENS_KORT:
        return LICENS_KORT[namn]
    if m.get("License-Expression"):
        return m["License-Expression"]
    lic = (m.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) <= 80:
        return lic
    klasser = [k.split("::")[-1].strip() for k in (m.get_all("Classifier") or []) if k.startswith("License ::")]
    return ", ".join(klasser) or "se licenstexten"


def kalla_for(dist):
    m = dist.metadata
    urler = {}
    for rad in m.get_all("Project-URL") or []:
        etikett, _, url = rad.partition(",")
        urler[etikett.strip().lower()] = url.strip()
    for etikett in ("source", "source code", "repository", "code", "homepage", "home"):
        if urler.get(etikett):
            return urler[etikett]
    if m.get("Home-page"):
        return m["Home-page"]
    return f"https://pypi.org/project/{m['Name']}/{m['Version']}/"


def toppnamn(dist):
    """Paketets importnamn pa toppniva (top_level.txt, annars ur RECORD)."""
    text = dist.read_text("top_level.txt")
    if text:
        return {r.strip() for r in text.splitlines() if r.strip()}
    namn = set()
    for f in dist.files or []:
        delar = str(f).split("/")
        if delar[0].endswith((".dist-info", ".egg-info", ".data")) or delar[0] in ("..", "__pycache__"):
            continue
        namn.add(delar[0].rsplit(".", 1)[0] if len(delar) == 1 else delar[0])
    return namn


def egna_bibliotek(dist, biblioteksnamn):
    """Ett bibliotek som paketets eget projekt har byggt: namnet borjar med ett av paketets importnamn
    (sherpa-onnx-c-api.dll i sherpa_onnx/lib)."""
    n = re.sub(r"[^a-z0-9]", "", os.path.basename(biblioteksnamn).lower())
    n = n[3:] if n.startswith("lib") else n
    for t in toppnamn(dist) | {dist.metadata["Name"]}:
        t = re.sub(r"[^a-z0-9]", "", t.lower())
        if len(t) >= 4 and n.startswith(t):
            return True
    return False


# --- paketen ----------------------------------------------------------------------------------------------------

def distributioner(sokvagar=None):
    """{normnamn: Distribution}, den forsta for varje namn (som importlib gor)."""
    ut = {}
    for d in importlib.metadata.distributions(**({"path": sokvagar} if sokvagar is not None else {})):
        try:
            namn = normnamn(d.metadata["Name"])
        except (KeyError, TypeError):
            continue
        ut.setdefault(namn, d)
    return ut


def filkarta(dists):
    """{absolut sokvag: normnamn} for varje fil i paketens RECORD (utom ../, som hamnar utanfor site-packages)."""
    karta = {}
    for namn, d in dists.items():
        for f in d.files or []:
            if str(f).startswith(".."):
                continue
            karta.setdefault(nyckel(d.locate_file(f)), namn)
    return karta


def kallfiler_ur_toc(toc):
    """Kallsokvagarna i PyInstallers TOC-listor: (namn, kalla, typ) -> [(namn i programmet, kalla)]."""
    ut = []
    for post in toc:
        if len(post) >= 2 and isinstance(post[1], str) and post[1] and os.path.isfile(post[1]):
            ut.append((str(post[0]), post[1]))
    return ut


def fordela(filer, dists, karta=None):
    """[(namn i programmet, kalla)] -> ({normnamn: [(namn, kalla)]}, [(namn, kalla) som inget paket ager])."""
    if not filer:
        return {}, []
    karta = filkarta(dists) if karta is None else karta
    paket, ovriga = {}, []
    for mal, kalla in filer:
        namn = karta.get(nyckel(kalla)) or karta.get(nyckel(os.path.realpath(kalla)))
        if namn is None:
            ovriga.append((mal, kalla))
        else:
            paket.setdefault(namn, []).append((mal, kalla))
    return paket, ovriga


def alla_installerade(dists):
    """Provet: alla installerade paket utom byggverktygen och det som spec-filen utesluter, med alla sina filer."""
    paket = {}
    for namn, d in dists.items():
        if namn in BYGGVERKTYG or namn in UTESLUTNA:
            continue
        filer = [(str(f), str(d.locate_file(f))) for f in d.files or [] if not str(f).startswith("..")]
        paket[namn] = filer
    return paket


def licensfiler(dist):
    """Licensfilerna i paketet: [(relativ sokvag, absolut sokvag)], dist-info forst."""
    ut = []
    for f in dist.files or []:
        s = str(f)
        bas = s.rsplit("/", 1)[-1]
        if s.startswith("..") or not LICENSFIL.match(bas) or bas.lower().endswith((".py", ".pyc")):
            continue
        sokvag = str(dist.locate_file(f))
        if os.path.isfile(sokvag):
            ut.append((s, sokvag))
    return sorted(ut, key=lambda x: (".dist-info/" not in x[0], x[0]))


def text_ur_filer(filer):
    delar = []
    for rel, sokvag in filer:
        delar.append(f"===== {rel} =====\n{las_text(sokvag).rstrip()}\n")
    return "\n".join(delar)


def huvud(rader):
    return "\n".join(r for r in rader if r is not None) + "\n\n"


def paketkomponent(namn, dists, filer, res, ffmpeg_bibliotek, msvc_dllar, prov=False):
    """Komponenten for ett Python-paket. Lagger till FEL i res nar en text saknas."""
    d = dists[namn]
    m = d.metadata
    rubrik = f"{m['Name']} {m['Version']}"
    noter = []
    texter = licensfiler(d)
    if not texter and namn in SAMMA_PROJEKT:
        syskon, forklaring = SAMMA_PROJEKT[namn]
        s = dists.get(syskon)
        if s is None:
            res.fel.append(f"{rubrik}: saknar licensfil, och {syskon} (samma projekt) är inte installerat")
        elif s.metadata["Version"] != m["Version"]:
            res.fel.append(f"{rubrik}: saknar licensfil, och {syskon} har en annan version ({s.metadata['Version']})")
        else:
            texter = licensfiler(s)
            noter.append(forklaring)
    if not texter:
        if not any(rubrik in f for f in res.fel):
            res.fel.append(f"{rubrik}: paketet följer med programmet men har ingen licensfil (LICENSE, COPYING, NOTICE "
                           f"eller AUTHORS) i sin dist-info. Lägg till det i SAMMA_PROJEKT eller TILLAGG i samla_licenser.py "
                           f"med en kontrollerad text, eller ta bort paketet ur programmet.")
        return None
    licenstext = text_ur_filer(texter)
    if namn in NOTER:
        noter.append(NOTER[namn])

    # Bibliotek som paketet bar med sig
    bibliotek = sorted({(mal.replace(os.sep, "/"), kalla) for mal, kalla in filer
                        if ar_delat_bibliotek(os.path.basename(kalla))})
    tackta, tillagg, andra_av = [], [], []
    for mal, kalla in bibliotek:
        bas = os.path.basename(kalla)
        if MSVC.match(bas):
            msvc_dllar.append(mal)
            tackta.append(f"{mal} (Visual C++-runtimen, se microsoft-visual-c-runtime.txt)")
            continue
        if namn == "av" and FFMPEG_NAMN.match(bas):
            ffmpeg_bibliotek.append((mal, kalla))
            tackta.append(f"{mal} (FFmpeg, {'hoppades över i provet' if prov else 'se ffmpeg.txt'})")
            continue
        if namn == "av":
            andra_av.append(mal)
            if prov:
                tackta.append(f"{mal} (hoppades över i provet)")
            continue
        regel = next((t for t in TILLAGG if t["paket"] == namn and t["bibliotek"].search(bas)), None)
        if regel is not None:
            if regel["version"] != m["Version"]:
                res.fel.append(f"{rubrik}: texterna för {bas} i paketering/licenstexter/{regel['katalog']} gäller version "
                               f"{regel['version']}: kontrollera vilket bibliotek den nya versionen har och byt texterna")
                continue
            if regel not in tillagg:
                tillagg.append(regel)
            tackta.append(f"{mal} ({regel['namn']}, texten nedan)")
            continue
        if egna_bibliotek(d, bas):
            tackta.append(f"{mal} (paketets eget bibliotek)")
            continue
        traff = sorted(o for o in nycklar(bas) if o in licenstext.lower())
        if traff:
            tackta.append(f"{mal} (licenstexten nedan nämner {', '.join(traff)})")
            continue
        res.fel.append(f"{rubrik}: biblioteket {mal} följer med paketet men har ingen licenstext (paketets licensfiler "
                       f"nämner det inte, och det finns inget i paketering/licenstexter/)")
    if andra_av and not prov:
        korta = sorted({re.split(r"[-.]", os.path.basename(m))[0] for m in andra_av})
        res.fel.append(f"{rubrik}: PyAV har {len(andra_av)} bibliotek som inte är FFmpegs sju LGPL-bibliotek "
                       f"({', '.join(korta)}). Det är hjulet från PyPI, med FFmpeg byggt med GPL, och licenstexterna för "
                       f"de biblioteken följer inte med hjulet. Bygg programmet med det egna FFmpeg och PyAV "
                       f"(paketering/bygg-ffmpeg.sh och bygg-pyav.sh) och ange AKASHA_FFMPEG_LICENSER.")
    for regel in tillagg:
        katalog = os.path.join(TILLAGGSKATALOG, regel["katalog"])
        filer_t = sorted(os.path.join(katalog, f) for f in os.listdir(katalog)) if os.path.isdir(katalog) else []
        if not filer_t:
            res.fel.append(f"{rubrik}: paketering/licenstexter/{regel['katalog']} saknas eller är tom")
            continue
        licenstext += "\n" + text_ur_filer([(f"paketering/licenstexter/{regel['katalog']}/{os.path.basename(f)}", f)
                                            for f in filer_t])
    rader = [rubrik, f"Licens: {kort_licens(d)}", f"Källa: {kalla_for(d)}"]
    rader += [f"Anmärkning: {n}" for n in noter]
    if tackta:
        rader.append("Bibliotek som paketet har med sig:")
        rader += [f"  {t}" for t in tackta]
    return Komponent(m["Name"], m["Version"], kort_licens(d), kalla_for(d), filnamn_for(namn),
                     huvud(rader) + licenstext)


# --- de andra komponenterna -------------------------------------------------------------------------------------

def python_licensfil():
    """LICENSE.txt ur den Python som kor (bygger), eller None."""
    v = f"{sys.version_info.major}.{sys.version_info.minor}"
    kandidater = [
        os.path.join(sys.base_prefix, "LICENSE.txt"),  # Windows (python.org)
        os.path.join(sysconfig.get_paths(vars={"installed_base": sys.base_prefix})["stdlib"], "LICENSE.txt"),
        os.path.join(sys.base_prefix, "lib", f"python{v}", "LICENSE.txt"),  # Mac (Python.framework) och Linux
        os.path.join(sys.base_prefix, "Resources", "English.lproj", "License.rtf"),
        f"/usr/share/doc/python{v}/copyright",  # Debian och Ubuntu
        f"/usr/share/doc/libpython{v}-minimal/copyright",
    ]
    return next((k for k in kandidater if os.path.isfile(k)), None)


def python_komponent(res, python_binarer):
    v = platform.python_version()
    fil = python_licensfil()
    if fil is None:
        res.fel.append(f"Python {v}: hittade ingen LICENSE.txt i {sys.base_prefix}")
        return None
    rader = [f"Python {v}", "Licens: PSF-2.0 (och licenserna för det som ingår i Python, i texten nedan)",
             f"Källa: https://www.python.org/downloads/release/python-{v.replace('.', '')}/ (källkoden: "
             f"https://github.com/python/cpython/tree/v{v})", f"Byggd: {' '.join(sys.version.split())}"]
    if python_binarer:
        rader.append("Filer ur Python-installationen i programmet:")
        rader += [f"  {mal}" for mal in sorted(python_binarer)]
    texter = [(os.path.basename(fil), fil)]
    minor = f"cpython-{sys.version_info.major}.{sys.version_info.minor}"
    katalog = os.path.join(TILLAGGSKATALOG, minor)
    if os.path.isdir(katalog) and os.listdir(katalog):
        texter += [(f"paketering/licenstexter/{minor}/{f}", os.path.join(katalog, f)) for f in sorted(os.listdir(katalog))]
        rader.append("Licenserna för det som ingår i Python (expat i pyexpat, libmpdec i _decimal, libffi, zlib, HACL* i "
                     "_md5, _sha1, _sha2 och _sha3 m.fl.) står efter Pythons LICENSE.txt, ur CPythons Doc/license.rst. "
                     "OpenSSL och XZ Utils har egna filer.")
    else:
        res.fel.append(f"Python {v}: paketering/licenstexter/{minor} saknas (Doc/license.rst ur CPython, med licenserna för "
                       f"expat, libmpdec, libffi, zlib, HACL* m.fl., som ingår i Python)")
    return Komponent("Python", v, "PSF-2.0", f"https://www.python.org/ (källkoden: https://github.com/python/cpython/tree/v{v})",
                     "python.txt", huvud(rader) + text_ur_filer(texter))


# XZ Utils (liblzma) ar statiskt inlankad i _lzma i Python fran python.org, i den version som byggskripten anger (Mac:
# Mac/BuildScript/build-installer.py, Windows: PCbuild/get_externals.bat). Versionen gar inte att lasa ur _lzma.
XZ_I_PYTHON = {("mac", "3.12.10"): "5.2.3", ("windows", "3.12.10"): "5.2.5"}


def tillaggskomponent(namn, version, licens, kalla, fil, katalog, rader, res):
    sokvag = os.path.join(TILLAGGSKATALOG, katalog)
    if not os.path.isdir(sokvag) or not os.listdir(sokvag):
        res.fel.append(f"{namn} {version}: paketering/licenstexter/{katalog} saknas (licenstexten för den versionen)")
        return None
    texter = [(f"paketering/licenstexter/{katalog}/{f}", os.path.join(sokvag, f)) for f in sorted(os.listdir(sokvag))]
    rader = [f"{namn} {version}", f"Licens: {licens}", f"Källa: {kalla}"] + rader
    return Komponent(namn, version, licens, kalla, fil, huvud(rader) + text_ur_filer(texter))


def python_tredjepart(res, python_binarer, plattform):
    """OpenSSL (libssl, libcrypto, _ssl, _hashlib) och XZ Utils (_lzma) i Python-installationens filer i programmet."""
    ut = []
    namn = [os.path.basename(m).lower() for m in python_binarer]
    openssl = [m for m, n in zip(python_binarer, namn) if re.match(r"^(lib)?(ssl|crypto)[-.]|^_(ssl|hashlib)\.", n)]
    if openssl:
        try:
            import ssl
            # ur texten ("OpenSSL 3.0.16 11 Feb 2025"): OPENSSL_VERSION_INFO ar (3, 0, 0, 16, 0) for OpenSSL 3
            text = ssl.OPENSSL_VERSION
            m = re.match(r"OpenSSL (\d+\.\d+\.\d+)", text)
            version = m.group(1) if m else ""
        except ImportError:
            version, text = "", "(ssl gick inte att importera)"
        if not version:
            res.fel.append("OpenSSL följer med Python i programmet, men versionen gick inte att läsa (ssl.OPENSSL_VERSION)")
        else:
            k = tillaggskomponent("OpenSSL", version, "Apache-2.0", f"https://github.com/openssl/openssl (taggen openssl-{version})",
                                  "openssl.txt", f"openssl-{version}",
                                  [f"Python i programmet är byggt med {text}.", "Filer i programmet:"]
                                  + [f"  {m}" for m in sorted(openssl)], res)
            if k:
                ut.append(k)
    lzma = [m for m, n in zip(python_binarer, namn) if n.startswith("_lzma.")]
    if lzma:
        v = platform.python_version()
        version = XZ_I_PYTHON.get((plattform, v))
        if version is None:
            res.fel.append(f"XZ Utils (liblzma) är inlänkad i {lzma[0]}, men vilken version som Python {v} på {plattform} har "
                           f"är inte känd: kontrollera CPythons byggskript och lägg till den i XZ_I_PYTHON i samla_licenser.py")
        else:
            k = tillaggskomponent("XZ Utils (liblzma)", version, "public domain (liblzma)",
                                  f"https://github.com/tukaani-project/xz (taggen v{version})", "xz.txt", f"xz-{version}",
                                  [f"liblzma är statiskt inlänkad i {lzma[0]} (Python {v} från python.org).",
                                   "Den delen är public domain, enligt texten nedan."], res)
            if k:
                ut.append(k)
    return ut


def las_kalla(sokvag):
    """KALLA.txt fran bygg-ffmpeg.sh och bygg-whisper-cli*.sh: forsta raden ar namn och version, sedan nyckel: varde."""
    rader = las_text(sokvag).splitlines()
    info = {"rubrik": rader[0].strip() if rader else ""}
    for r in rader[1:]:
        k, _, v = r.partition(":")
        if v:
            info[k.strip().lower()] = v.strip()
    return info


def whisper_komponent(katalog, res, whisper_binarer):
    if not katalog or not os.path.isfile(os.path.join(katalog, "LICENSE")):
        res.fel.append(f"whisper.cpp: licensen saknas ({katalog or 'AKASHA_WHISPER_LICENS är inte satt'}). "
                       f"bygg-whisper-cli.sh och bygg-whisper-cli-windows.sh sparar den i UTKATALOG/licens")
        return None
    info = las_kalla(os.path.join(katalog, "KALLA.txt")) if os.path.isfile(os.path.join(katalog, "KALLA.txt")) else {}
    version = info.get("tagg") or (info.get("rubrik", "").split() + ["-"])[1]
    url = info.get("kalla", "https://github.com/ggml-org/whisper.cpp")
    kalla = f"{url}, tagg {version}, commit {info['commit']}" if info.get("commit") else url
    rader = [f"whisper.cpp {version}", "Licens: MIT", f"Källa: {kalla}",
             "whisper-cli är byggt från källkoden ovan (paketering/bygg-whisper-cli.sh, bygg-whisper-cli-windows.sh). "
             "ggml, som ingår, har samma licens."]
    if whisper_binarer:
        rader.append("Filer i programmet:")
        rader += [f"  {mal}" for mal in sorted(whisper_binarer)]
    return Komponent("whisper.cpp", version, "MIT", kalla, "whisper-cpp.txt",
                     huvud(rader) + text_ur_filer([("LICENSE", os.path.join(katalog, "LICENSE"))]))


def ffmpeg_licensstrang(kalla):
    """'LGPL version 2.1 or later' ur ett FFmpeg-bibliotek, eller None."""
    try:
        with open(kalla, "rb") as f:
            data = f.read()
    except OSError:
        return None
    m = re.search(rb"lib(?:avutil|avcodec|avformat|avfilter|avdevice|swresample|swscale) license: ([\x20-\x7e]+)", data)
    return m.group(1).decode("ascii") if m else None


def ffmpeg_komponenter(katalog, bibliotek, res):
    """FFmpeg (och GCC-runtimen om den finns i katalogen). bibliotek = [(namn i programmet, kalla)] ur PyAV."""
    if not katalog or not os.path.isfile(os.path.join(katalog, "COPYING.LGPLv2.1")):
        res.fel.append(f"FFmpeg: licenstexterna saknas ({katalog or 'AKASHA_FFMPEG_LICENSER är inte satt'}). PyAV följer med "
                       f"programmet, och FFmpeg ska vara det egna LGPL-bygget: KATALOG/ut/ffmpeg från paketering/bygg-ffmpeg.sh")
        return []
    for mal, kalla in bibliotek:
        lic = ffmpeg_licensstrang(kalla)
        if lic != "LGPL version 2.1 or later":
            res.fel.append(f"FFmpeg: {mal} har licensen {lic or '(ingen licenssträng)'}, väntade LGPL version 2.1 or later "
                           f"(det egna bygget)")
    info = las_kalla(os.path.join(katalog, "KALLA.txt")) if os.path.isfile(os.path.join(katalog, "KALLA.txt")) else {}
    version = (info.get("rubrik", "").split() + ["-", "-"])[1]
    url = info.get("kalla", "https://github.com/FFmpeg/FFmpeg").removesuffix(".git")
    arkiv = f"ffmpeg-{version}-kallkod.tar.xz"
    kalla = (f"{url}, tagg {info.get('tagg', '-')}, commit {info.get('commit', '-')}; källkoden: {arkiv} i samma "
             f"GitHub Release som programmet")
    configure = las_text(os.path.join(katalog, "configure.txt")).strip() if os.path.isfile(os.path.join(katalog, "configure.txt")) else "-"
    rader = [f"FFmpeg {version}", "Licens: LGPL-2.1-or-later (bara LGPL-delar, inga externa bibliotek)",
             f"Källa: {url}, tagg {info.get('tagg', '-')}, commit {info.get('commit', '-')}",
             f"Källkoden till exakt den här versionen: filen {arkiv} i samma GitHub Release som programmet "
             f"({REPO}/releases), och FFmpegs eget repo vid commiten ovan. Byggskriptet (paketering/bygg-ffmpeg.sh) och "
             f"flaggorna (paketering/ffmpeg-komponenter.txt) ligger bredvid källkoden i releasen och i {REPO}.",
             "FFmpeg är delade bibliotek bredvid PyAV i programmet och går att byta mot ett annat bygge av samma version.",
             f"Configure-raden: {configure}"]
    if info.get("kompilator"):
        rader.append(f"Kompilator: {info['kompilator']}")
    if bibliotek:
        rader.append("Biblioteken i programmet:")
        rader += [f"  {mal}" for mal, _ in sorted(bibliotek)]
    texter = [(n, os.path.join(katalog, n)) for n in ("COPYING.LGPLv2.1", "LICENSE.md", "CREDITS", "KALLA.txt")
              if os.path.isfile(os.path.join(katalog, n))]
    ut = [Komponent("FFmpeg", version, "LGPL-2.1-or-later", kalla, "ffmpeg.txt", huvud(rader) + text_ur_filer(texter))]
    # Windows (MinGW-w64 i MSYS2 UCRT64): libgcc och mingw-w64-runtimen ar statiskt inlankade i FFmpeg-DLL:erna
    gcc = [(n, os.path.join(katalog, n)) for n in MINGW_TEXTER
           if os.path.isfile(os.path.join(katalog, n))]
    mingw = info.get("system") == "windows" or bool(gcc)
    if mingw:
        saknas = [n for n in MINGW_TEXTER if not os.path.isfile(os.path.join(katalog, n))]
        if saknas:
            res.fel.append(f"FFmpeg (Windows): {', '.join(saknas)} saknas i {katalog}: libgcc, mingw-w64-runtimen och "
                           f"winpthreads är inlänkade i DLL-filerna (bygg-ffmpeg.sh kopierar texterna ur MSYS2 UCRT64)")
        rader = ["GCC- och mingw-w64-runtimen (i FFmpeg-biblioteken på Windows)",
                 "Licens: GPL-3.0-or-later WITH GCC-exception-3.1 (libgcc); mingw-w64-runtimen: ZPL-2.1, public domain "
                 "och andra fria licenser (se texten nedan)",
                 "Källa: https://gcc.gnu.org/ och https://www.mingw-w64.org/ (MSYS2 UCRT64, https://www.msys2.org/)",
                 "libgcc, mingw-w64-runtimens startkod och winpthreads (-static) är statiskt inlänkade i "
                 "FFmpeg-biblioteken på Windows. Undantaget i COPYING.RUNTIME gör att programmet inte behöver vara under GPL."]
        if info.get("kompilator"):
            rader.append(f"Kompilator: {info['kompilator']}")
        ut.append(Komponent("GCC- och mingw-w64-runtimen (i FFmpeg)", "-",
                            "GPL-3.0-or-later WITH GCC-exception-3.1; ZPL-2.1, MIT m.fl.",
                            "https://gcc.gnu.org/, https://www.mingw-w64.org/", "gcc-mingw-runtime.txt",
                            huvud(rader) + text_ur_filer(gcc)))
    return ut


def khronos_komponent(whisper_licens, whisper_binarer, res):
    """Vulkan-Headers och SPIRV-Headers (Khronos), som ggml-vulkan.dll bygger in. Versionerna star i whisper.cpp:s
    KALLA.txt (bygg-whisper-cli-windows.sh), texterna i paketering/licenstexter/."""
    if not any(os.path.basename(m).lower().startswith("ggml-vulkan") for m in whisper_binarer):
        return None
    kallfil = os.path.join(whisper_licens or "", "KALLA.txt")
    info = las_kalla(kallfil) if whisper_licens and os.path.isfile(kallfil) else {}
    sdk, spirv = info.get("vulkan-sdk", ""), info.get("spirv-headers", "")
    if not sdk or not spirv:
        res.fel.append(f"ggml-vulkan.dll följer med, men {kallfil} säger inte vilken Vulkan SDK och vilka SPIRV-Headers den "
                       f"byggdes med (vulkan-sdk: och spirv-headers:, från bygg-whisper-cli-windows.sh)")
        return None
    filer, saknas = [], False
    for k in (f"vulkan-headers-{sdk}", f"spirv-headers-{spirv[:12]}"):
        katalog = os.path.join(TILLAGGSKATALOG, k)
        if not os.path.isdir(katalog) or not os.listdir(katalog):
            res.fel.append(f"ggml-vulkan.dll: paketering/licenstexter/{k} saknas (licenstexterna för den versionen)")
            saknas = True
            continue
        filer += [(f"paketering/licenstexter/{k}/{f}", os.path.join(katalog, f)) for f in sorted(os.listdir(katalog))]
    if saknas:
        return None
    rader = [f"Vulkan-Headers (Vulkan SDK {sdk}) och SPIRV-Headers (commit {spirv})",
             "Licens: Apache-2.0 OR MIT (Vulkan-Headers); Khronos MIT-liknande licens (SPIRV-Headers)",
             "Källa: https://github.com/KhronosGroup/Vulkan-Headers och https://github.com/KhronosGroup/SPIRV-Headers",
             "ggml-vulkan.dll (whisper.cpp, grafikkretsen) bygger in vulkan.hpp och spirv.hpp från Khronos Group. "
             "Vulkan-Headers får användas under Apache-2.0 eller MIT; båda texterna står nedan."]
    return Komponent("Vulkan-Headers och SPIRV-Headers (Khronos, i ggml-vulkan.dll)", sdk,
                     "Apache-2.0 OR MIT; Khronos (MIT-liknande)",
                     "https://github.com/KhronosGroup/Vulkan-Headers, https://github.com/KhronosGroup/SPIRV-Headers",
                     "khronos-vulkan-spirv-headers.txt", huvud(rader) + text_ur_filer(filer))


def msvc_komponent(dllar):
    url = "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files"
    rader = ["Microsoft Visual C++-runtime",
             "Licens: Microsofts licensvillkor för Visual Studio (Microsoft Software License Terms), avsnittet om "
             "distribuerbar kod (Distributable Code)",
             f"Källa: {url}",
             "",
             "De här filerna i programmet är Microsofts Visual C++-runtime:"]
    rader += [f"  {d}" for d in sorted(set(dllar))]
    rader += ["",
              "Filerna bredvid whisper-cli.exe är tagna ur Visual Studios Redist-katalog. De andra följer med Python och "
              "Python-paketen. Alla är filer som Microsoft tillåter att andra program delar ut tillsammans med sig "
              "(distribuerbar kod), på de villkor som står i licensvillkoren för Visual Studio. Villkoren följer med "
              "Visual Studio och finns på https://visualstudio.microsoft.com/license-terms/. Ingen licenstext från "
              "Microsoft är kopierad hit."]
    return Komponent("Microsoft Visual C++-runtime", "-", "Microsofts licensvillkor för Visual Studio (distribuerbar kod)",
                     url, "microsoft-visual-c-runtime.txt", "\n".join(rader) + "\n")


def egna_komponenter(version, res):
    ut = []
    lic, notice = os.path.join(ROT, "LICENSE"), os.path.join(ROT, "NOTICE")
    if os.path.isfile(lic) and os.path.isfile(notice):
        rader = [f"Akasha Protokoll {version}", "Licens: Apache-2.0", f"Källa: {REPO}", "© 2026 Dennis Fredin"]
        ut.append(Komponent("Akasha Protokoll", version, "Apache-2.0", REPO, "akasha-protokoll.txt",
                            huvud(rader) + text_ur_filer([("NOTICE", notice), ("LICENSE", lic)])))
    else:
        res.fel.append("Akasha Protokoll: LICENSE eller NOTICE saknas i repots rot")
    typsnitt = os.path.join(ROT, "app", "static", "typsnitt")
    for namn, fil, url in (("Anton", "OFL-Anton.txt", "https://github.com/googlefonts/AntonFont"),
                           ("Instrument Sans", "OFL-Instrument-Sans.txt", "https://github.com/Instrument/instrument-sans")):
        sokvag = os.path.join(typsnitt, fil)
        if not os.path.isfile(sokvag):
            res.fel.append(f"typsnittet {namn}: {sokvag} saknas")
            continue
        rader = [f"Typsnittet {namn}", "Licens: OFL-1.1", f"Källa: {url}",
                 f"Typsnittet ligger i programmet som .woff2-filer i static/typsnitt/, med samma licenstext ({fil})."]
        ut.append(Komponent(f"Typsnittet {namn}", "-", "OFL-1.1", url, filnamn_for("typsnitt-" + namn),
                            huvud(rader) + text_ur_filer([(fil, sokvag)])))
    return ut


# --- forteckningen ----------------------------------------------------------------------------------------------

def inledning(plattform, version, res, prov, ffmpeg_arkiv="ffmpeg-...-kallkod.tar.xz"):
    rader = []
    if res.fel:
        rader += [f"{MARKERING_OFULLSTANDIG}: licenstexter saknas, och programmet får inte delas ut så här. Det som saknas:"]
        rader += [f"  - {f}" for f in res.fel]
        rader.append("")
    if prov:
        rader += [f"{MARKERING_PROV}: ett prov utan whisper.cpp, FFmpeg och GCC-runtimen. Inte för utdelning.", ""]
    rubrik = f"Licenser för Akasha Protokoll {version} ({PLATTFORMSNAMN.get(plattform, plattform)})"
    rader += [rubrik, "=" * len(rubrik), "",
              "Akasha Protokoll är fri programvara under Apache License 2.0 (se akasha-protokoll.txt). Programmet",
              "innehåller också program, bibliotek och typsnitt från andra, var och en under sin egen licens. Den här",
              "katalogen har den fullständiga licenstexten, med upphovsrättsraderna, för varje del som följer med",
              "programmet: en fil per del. Förteckningen nedan säger vilken fil som hör till vilken del.", ""]
    rader += ["FFmpeg är under LGPL-2.1-or-later och ligger som delade bibliotek i programmet. Du får byta ut dem mot",
              "ett eget bygge. Källkoden till exakt den version som följer med finns i samma GitHub Release som",
              f"programmet ({ffmpeg_arkiv}), se ffmpeg.txt."]
    if plattform == "windows":
        rader += ["pystray är under LGPL-3.0 och ligger som vanliga .py-filer i _internal\\pystray, så att den också",
                  "går att byta ut."]
    rader += ["",
              "Modellerna (KB-Whisper från KBLab, Kungliga biblioteket, och TitaNet från NVIDIA, via sherpa-onnx) följer",
              "inte med programmet. Du hämtar dem när du använder programmet första gången, och deras licenser står i",
              f"README, avsnittet Källor och licenser: {REPO}#källor-och-licenser", "",
              f"Källkoden till Akasha Protokoll: {REPO}", "",
              "Förteckning: namn | version | licens | källa | fil",
              STRECK]
    return rader


def forteckning(komponenter, plattform, version, res, prov):
    ffmpeg = next((k for k in komponenter if k.namn == "FFmpeg"), None)
    arkiv = f"ffmpeg-{ffmpeg.version}-kallkod.tar.xz" if ffmpeg else "ffmpeg-...-kallkod.tar.xz"
    rader = inledning(plattform, version, res, prov, arkiv)
    for k in komponenter:
        rader.append(SEP.join(falt(x) for x in (k.namn, k.version, k.licens, k.kalla, k.fil)))
    if res.varningar:
        rader += ["", "Att kontrollera (bara i provbygget på Linux):"] + [f"  - {v}" for v in res.varningar]
    return "\n".join(rader) + "\n"


def skriv(ut, komponenter, text):
    """Skriver katalogen i en tillfallig katalog bredvid och byter sedan ut den gamla (inget halvt resultat)."""
    ut = os.path.abspath(ut)
    os.makedirs(os.path.dirname(ut), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".licenser-", dir=os.path.dirname(ut))
    try:
        namn = set()
        for k in komponenter:
            if k.fil in namn or k.fil == FORTECKNING:
                raise LicensFel(f"två komponenter har filnamnet {k.fil}")
            namn.add(k.fil)
            with open(os.path.join(tmp, k.fil), "w", encoding="utf-8", newline="\n") as f:
                f.write(k.text)
        with open(os.path.join(tmp, FORTECKNING), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if os.path.exists(ut):
            shutil.rmtree(ut)
        os.replace(tmp, ut)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


# --- hela kedjan ------------------------------------------------------------------------------------------------

def samla(paket, ovriga, ut, plattform, version="0.2.0", whisper_licens=None, ffmpeg_licenser=None, prov=False,
          dists=None):
    """paket = {normnamn: [(namn i programmet, kalla)]}, ovriga = filer som inget paket ager.
    Skriver katalogen ut och ger ett Resultat (fel ar tom om allt finns)."""
    dists = distributioner() if dists is None else dists
    res = Resultat()
    ffmpeg_bibliotek, msvc_dllar = [], []
    python_binarer, whisper_binarer = [], []
    paketkomp = []
    for namn in sorted(paket, key=lambda n: n.lower()):
        k = paketkomponent(namn, dists, paket[namn], res, ffmpeg_bibliotek, msvc_dllar, prov=prov)
        if k is not None:
            paketkomp.append(k)
    for mal, kalla in ovriga:
        mal = mal.replace(os.sep, "/")
        bas = os.path.basename(kalla)
        if not ar_binar(kalla):
            continue  # data och Python-kod (appen, typsnitten, standardbiblioteket) har sina komponenter
        if MSVC.match(bas):
            msvc_dllar.append(mal)
        elif under(kalla, sys.base_prefix):
            python_binarer.append(mal)
        elif WHISPER_NAMN.match(bas):
            whisper_binarer.append(mal)
        elif plattform == "linux":
            res.varningar.append(f"{mal} ({kalla}) hör inte till något paket, Python eller whisper.cpp")
        else:
            res.fel.append(f"{mal} ({kalla}) följer med programmet men hör inte till något Python-paket, Python eller "
                           f"whisper.cpp: dess licens är okänd")

    komponenter = egna_komponenter(version, res)
    k = python_komponent(res, python_binarer)
    if k:
        komponenter.append(k)
    fore = len(res.fel)
    komponenter += python_tredjepart(res, python_binarer, plattform)
    if plattform == "linux":  # provbygget: systemets OpenSSL och liblzma, vars texter inte finns har
        res.varningar += res.fel[fore:]
        del res.fel[fore:]
    if plattform in ("mac", "windows") and not prov:
        k = whisper_komponent(whisper_licens, res, whisper_binarer)
        if k:
            komponenter.append(k)
        k = khronos_komponent(whisper_licens, whisper_binarer, res)
        if k:
            komponenter.append(k)
    if "av" in paket and not prov:
        komponenter += ffmpeg_komponenter(ffmpeg_licenser, ffmpeg_bibliotek, res)
    if msvc_dllar:
        komponenter.append(msvc_komponent(msvc_dllar))
    komponenter += paketkomp
    skriv(ut, komponenter, forteckning(komponenter, plattform, version, res, prov))
    res.komponenter = komponenter
    return res


def toc_for_katalog(katalog, prefix):
    """PyInstallers TOC (DATA) for alla filer i katalogen, under prefix i programmet."""
    ut = []
    for mapp, _k, filer in os.walk(katalog):
        for f in sorted(filer):
            full = os.path.join(mapp, f)
            ut.append((os.path.join(prefix, os.path.relpath(full, katalog)), full, "DATA"))
    return ut


def samla_for_bygget(toc, ut, plattform, version, whisper_licens=None, ffmpeg_licenser=None):
    """Spec-filens anrop: toc = a.pure + a.scripts + a.binaries + a.datas. Skriver ut resultatet och ger felen."""
    filer = kallfiler_ur_toc(toc)
    dists = distributioner()
    paket, ovriga = fordela(filer, dists)
    print(f"LICENSER: {len(filer)} filer i analysen, {len(paket)} Python-paket: {', '.join(sorted(paket))}", flush=True)
    try:
        res = samla(paket, ovriga, ut, plattform, version, whisper_licens, ffmpeg_licenser, dists=dists)
    except (OSError, LicensFel) as e:
        print(f"LICENSER: FEL: {e}", flush=True)
        return [str(e)]
    for v in res.varningar:
        print(f"LICENSER: VARNING: {v}", flush=True)
    for f in res.fel:
        print(f"LICENSER: FEL: {f}", flush=True)
    print(f"LICENSER: {len(res.komponenter)} komponenter i {ut}" + (f", {len(res.fel)} FEL (LICENSER.txt är markerad "
          f"{MARKERING_OFULLSTANDIG})" if res.fel else ""), flush=True)
    return res.fel


def main(argv=None):
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ut", required=True, help="katalogen som skrivs (licenser/)")
    ap.add_argument("--plattform", required=True, choices=["mac", "windows", "linux"])
    ap.add_argument("--alla-installerade", action="store_true", required=True,
                    help="alla installerade paket utom byggverktygen (bygget anvander PyInstallers analys via spec-filen)")
    ap.add_argument("--version", default=os.environ.get("AKASHA_VERSION", "0.2.0"))
    ap.add_argument("--whisper-licens", default=os.environ.get("AKASHA_WHISPER_LICENS") or None)
    ap.add_argument("--ffmpeg-licenser", default=os.environ.get("AKASHA_FFMPEG_LICENSER") or None)
    ap.add_argument("--prov", action="store_true", help="hoppa over whisper.cpp, FFmpeg och GCC-runtimen (markerat PROV)")
    args = ap.parse_args(argv)
    dists = distributioner()
    paket = alla_installerade(dists)
    res = samla(paket, [], args.ut, args.plattform, args.version, args.whisper_licens, args.ffmpeg_licenser,
                prov=args.prov, dists=dists)
    for k in res.komponenter:
        print(f"OK: {k.namn} {k.version} ({k.licens}) -> {k.fil}")
    for v in res.varningar:
        print(f"VARNING: {v}")
    for f in res.fel:
        print(f"FEL: {f}")
    print(f"{len(res.komponenter)} komponenter i {os.path.abspath(args.ut)}, {len(res.fel)} FEL")
    return 1 if res.fel else 0


if __name__ == "__main__":
    sys.exit(main())
