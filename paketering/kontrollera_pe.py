"""Kontrollerar att varje Windows-fil (.exe, .dll, .pyd) i en katalog hittar alla DLL-filer den importerar,
och att alla ar x64. Windows motsvarighet till otool -L-kontrollen pa Mac.

    python paketering/kontrollera_pe.py KATALOG [--sjalvstandig UNDERKATALOG ...] [--sok UNDERKATALOG ...]
           [--system-katalog KATALOG] [--ut FIL] [--arkitektur x64|x86|arm64] [--vc-saknas]

Importtabellen och de fordrojda importerna lases med pefile (pip install pefile). En import raknas som funnen om
DLL-filen ligger i ett av dessa ställen (efterliknar hur Windows letar efter en DLL):
  - samma katalog som filen som importerar den,
  - for filer i Python-delen: programmets rot och _internal (PyInstallers bootloader satter _internal som
    DLL-katalog), och kataloger som heter *.libs (numpy.libs, av.libs: biblioteken laddar dem sjalva),
  - en av kataloger angivna med --sok.
En katalog som anges med --sjalvstandig (till exempel _internal/whisper, dar whisper-cli.exe startas som egen
process) far bara hitta DLL-filer i sig sjalv och bland Windows egna: processen ar startad med
CreateProcess, som inte arver programmets DLL-kataloger.
Windows egna DLL-filer (kernel32, user32, api-ms-win-* osv.) behover inte finnas i katalogen. C-runtimen
(vcruntime140, msvcp140, vcomp140) och biblioteken vi levererar (onnxruntime, DirectML, libomp, libiomp, sherpa*, whisper*,
ggml*) raknas aldrig som Windows egna, inte heller om de finns i System32: hos anvandaren finns de inte sakert, eller
i en annan version.
Med --system-katalog (till exempel C:\\Windows\\System32) godtas dessutom varje annan DLL som finns dar, och den
listas som INFO sa att namnet kan laggas till i listan nedan.

Varje fel skrivs som FEL: med filens och DLL-filens namn. Slutkod 1 om nagot var FEL. Hela tabellen (varje fil
och dess importer) skrivs till --ut om den anges.
"""
import argparse
import collections
import os
import posixpath
import sys

import kontroll_hjalp

MASKINER = {"x64": 0x8664, "x86": 0x14C, "arm64": 0xAA64}
PE32_PLUS = 0x20B
ENDELSER = (".exe", ".dll", ".pyd")

# C-runtimen och Python: maste ligga i programmet (hos anvandaren finns inte alltid Visual C++ Redistributable).
EGNA_PREFIX = ("vcruntime", "msvcp", "vcomp", "concrt", "vccorlib", "python")
# Bibliotek som programmet levererar sjalv och som aldrig far godtas fran System32, ens med --system-katalog: Windows 10
# och 11 har egna (aldre) onnxruntime.dll och DirectML.dll, och en saknad fil i paketet skulle da ladda fel version hos
# anvandaren.
LEVERERAS_SJALV = EGNA_PREFIX + ("onnxruntime", "directml", "libomp", "libiomp", "sherpa", "whisper", "ggml")
SYSTEM_PREFIX = ("api-ms-win-", "ext-ms-win-")
# Namn utan .dll, gemener. Windows egna DLL-filer som ingar i Windows 10 och 11.
# vulkan-1 (Vulkan-laddaren) kommer med grafikdrivrutinen och levereras aldrig av oss: ggml-vulkan.dll importerar den,
# och saknas den hos anvandaren laddas inte ggml-vulkan.dll och whisper.cpp anvander processorn.
SYSTEM = frozenset("""
advapi32 authz avrt bcrypt bcryptprimitives cabinet cfgmgr32 combase comctl32 comdlg32 credui crypt32 cryptsp
d2d1 d3d9 d3d11 d3d12 dbgcore dbghelp dcomp dnsapi dwmapi dwrite dxcore dxgi gdi32 gdi32full glu32 imagehlp imm32
iphlpapi kernel32 kernelbase ksuser mf mfplat mfreadwrite mmdevapi mpr msctf msimg32 msvcrt mswsock ncrypt netapi32
normaliz ntdll ole32 oleacc oleaut32 opengl32 pdh powrprof profapi propsys psapi rpcrt4 rstrtmgr sechost secur32
setupapi shcore shell32 shlwapi sspicli ucrtbase uiautomationcore user32 userenv usp10 uxtheme version wevtapi avicap32 msacm32 msvfw32 vfw32
win32u vulkan-1 windowscodecs winhttp wininet winmm winspool wintrust wldap32 ws2_32 wsock32 wtsapi32 xinput1_4
""".split())


PEInfo = collections.namedtuple("PEInfo", "maskin magic importer fordrojda fel")


def stam(namn):
    """DLL-namn -> gemener utan .dll."""
    n = namn.lower()
    return n[:-4] if n.endswith(".dll") else n


def ar_egen(namn):
    return stam(namn).startswith(EGNA_PREFIX)


def ar_system(namn, system_stammar=None):
    """Sant for en DLL som Windows har (inte C-runtimen). system_stammar: namnen (stam) som finns i System32."""
    s = stam(namn)
    if s.startswith(LEVERERAS_SJALV):
        return False
    if s.startswith(SYSTEM_PREFIX) or s in SYSTEM:
        return True
    return bool(system_stammar) and s in system_stammar


def las_pe(sokvag):
    """-> PEInfo (med pefile). Ett fel ger PEInfo(None, None, [], [], text)."""
    import pefile

    try:
        pe = pefile.PE(sokvag, fast_load=True)
    except Exception as e:  # PEFormatError, OSError
        return PEInfo(None, None, [], [], f"inte en giltig PE-fil ({type(e).__name__}: {e})")
    try:
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        importer = [e.dll.decode("ascii", "replace") for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
        fordrojda = [e.dll.decode("ascii", "replace") for e in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])]
        return PEInfo(pe.FILE_HEADER.Machine, pe.OPTIONAL_HEADER.Magic, importer, fordrojda, None)
    except Exception as e:
        return PEInfo(None, None, [], [], f"importtabellen gick inte att lasa ({type(e).__name__}: {e})")
    finally:
        pe.close()


class Trad:
    """Filerna under en katalog: vilka som finns (per katalog, gemener) och PE-informationen for exe/dll/pyd."""

    def __init__(self, per_katalog, pe):
        self.per_katalog = per_katalog  # {"" eller "a/b": {gemena filnamn}}
        self.pe = pe                    # {"a/b/fil.dll": PEInfo}

    def finns(self, katalog, namn):
        return namn.lower() in self.per_katalog.get(katalog, ())

    def kataloger(self):
        return list(self.per_katalog)


def las_trad(rot, las=None):
    las = las or las_pe  # vid anropet, sa att testerna kan byta ut den
    per_katalog, pe = {}, {}
    for mapp, _under, filer in os.walk(rot):
        rel = os.path.relpath(mapp, rot).replace(os.sep, "/")
        rel = "" if rel == "." else rel
        per_katalog[rel] = {f.lower() for f in filer}
        for f in sorted(filer):
            if f.lower().endswith(ENDELSER):
                pe[posixpath.join(rel, f)] = las(os.path.join(mapp, f))
    return Trad(per_katalog, pe)


def _under(katalog, prefix):
    return katalog == prefix or katalog.startswith(prefix + "/")


def sokvagar(katalog, trad, sjalvstandiga, extra):
    """Kataloger (relativa, "" = roten) som en fil i `katalog` far hitta DLL-filer i, med en etikett var."""
    sok = [(katalog, "samma katalog")]
    if not any(_under(katalog, s) for s in sjalvstandiga):
        if any(_under(k, "_internal") for k in trad.kataloger()):
            sok.append(("_internal", "_internal"))
        sok.append(("", "programmets rot"))
        sok += [(k, f"{posixpath.basename(k)}") for k in sorted(trad.kataloger()) if k.endswith(".libs")]
        sok += [(e, f"--sok {e}") for e in extra]
    sedda, ut = set(), []
    for k, etikett in sok:
        if k not in sedda:
            sedda.add(k)
            ut.append((k, etikett))
    return ut


class Rapport:
    def __init__(self):
        self.fel = []                              # texter
        self.saknas = collections.defaultdict(list)  # {dll: [filer]}
        self.system = collections.defaultdict(set)   # {namn: {filer}} (godtagna som Windows egna)
        self.system_utanfor_listan = collections.defaultdict(set)  # funna bara via --system-katalog
        self.vagar = collections.Counter()
        self.rader = []                            # tabellen
        self.antal_filer = 0
        self.antal_importer = 0


def kontrollera(trad, sjalvstandiga=(), extra=(), maskin=MASKINER["x64"], system_stammar=None):
    """Hela kontrollen pa en inlast trad (ingen pefile behovs). -> Rapport."""
    r = Rapport()
    for fil, info in sorted(trad.pe.items()):
        r.antal_filer += 1
        katalog = posixpath.dirname(fil)
        if info.fel:
            r.fel.append(f"{fil}: {info.fel}")
            r.rader.append(f"{fil}  FEL: {info.fel}")
            continue
        arkitektur = {v: k for k, v in MASKINER.items()}.get(info.maskin, f"okand 0x{info.maskin:x}")
        if info.maskin != maskin:
            vantad = {v: k for k, v in MASKINER.items()}[maskin]
            r.fel.append(f"{fil}: fel arkitektur, {arkitektur} (Machine 0x{info.maskin:x}), vantade {vantad}")
        elif maskin in (MASKINER["x64"], MASKINER["arm64"]) and info.magic != PE32_PLUS:
            r.fel.append(f"{fil}: Machine ar x64 men filen ar inte PE32+ (Magic 0x{info.magic:x})")
        sok = sokvagar(katalog, trad, sjalvstandiga, extra)
        rad = [f"{fil}  {arkitektur}"]
        for dll in info.importer + info.fordrojda:
            r.antal_importer += 1
            fordrojd = dll in info.fordrojda and dll not in info.importer
            funnen = next(((k, e) for k, e in sok if trad.finns(k, dll)), None)
            if funnen:
                r.vagar[funnen[1]] += 1
                rad.append(f"  {dll}{' (fordrojd)' if fordrojd else ''} -> {posixpath.join(funnen[0], dll)}")
            elif ar_system(dll, system_stammar):
                r.system[stam(dll)].add(fil)
                if stam(dll) not in SYSTEM and not stam(dll).startswith(SYSTEM_PREFIX):
                    r.system_utanfor_listan[stam(dll)].add(fil)
                rad.append(f"  {dll}{' (fordrojd)' if fordrojd else ''} -> Windows")
            else:
                r.saknas[dll.lower()].append(fil)
                kat = ", ".join(k or "(roten)" for k, _ in sok)
                r.fel.append(f"{fil}: importerar {dll}{' (fordrojd)' if fordrojd else ''}, som inte finns i: {kat}")
                rad.append(f"  {dll}{' (fordrojd)' if fordrojd else ''} -> SAKNAS")
        r.rader.append("\n".join(rad))
    return r


def vc_saknas(trad, sjalvstandiga=()):
    """Namn (som de skrivs i importen) pa C-runtime-DLL:er som nagon fil importerar men som inte ligger
    bredvid den eller bland de andra platserna. Anvands for att veta vad som ska kopieras in."""
    saknas = {}
    for fil, info in sorted(trad.pe.items()):
        if info.fel:
            continue
        sok = sokvagar(posixpath.dirname(fil), trad, sjalvstandiga, ())
        for dll in info.importer + info.fordrojda:
            if ar_egen(dll) and not stam(dll).startswith("python") and not any(trad.finns(k, dll) for k, _ in sok):
                saknas.setdefault(dll.lower(), dll)
    return sorted(saknas.values())


def system_stammar_ur(katalog):
    try:
        return {stam(n) for n in os.listdir(katalog) if n.lower().endswith(".dll")}
    except OSError:
        return set()


def main(argv=None):
    kontroll_hjalp.utf8_utskrift()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("katalog")
    ap.add_argument("--sjalvstandig", action="append", default=[], metavar="UNDERKATALOG",
                    help="undre katalog (relativ) som bara far hitta DLL-filer i sig sjalv; kan upprepas. "
                         "Standard: _internal/whisper om den finns")
    ap.add_argument("--sok", action="append", default=[], metavar="UNDERKATALOG", help="extra sokkatalog (relativ)")
    ap.add_argument("--system-katalog", help="Windows System32: godta andra DLL-filer som finns dar")
    ap.add_argument("--ut", help="skriv hela tabellen till den har filen")
    ap.add_argument("--arkitektur", choices=sorted(MASKINER), default="x64")
    ap.add_argument("--vc-saknas", action="store_true",
                    help="skriv bara namnen pa C-runtime-DLL:er som importeras men saknas (en per rad)")
    args = ap.parse_args(argv)

    try:
        import pefile  # noqa: F401
    except ImportError:
        print("FEL: pefile saknas i den har Python (pip install -r paketering/krav-bygg.txt)", flush=True)
        return 2
    rot = os.path.abspath(args.katalog)
    if not os.path.isdir(rot):
        print(f"FEL: {args.katalog} finns inte eller ar inte en katalog", flush=True)
        return 1
    trad = las_trad(rot)
    sjalvstandiga = list(args.sjalvstandig)
    if not sjalvstandiga and "_internal/whisper" in trad.kataloger():
        sjalvstandiga = ["_internal/whisper"]

    if args.vc_saknas:
        for namn in vc_saknas(trad, sjalvstandiga):
            print(namn)
        return 0

    res = kontroll_hjalp.Resultat("KONTROLL AV DLL-BEROENDEN")
    system_stammar = system_stammar_ur(args.system_katalog) if args.system_katalog else None
    print(f"Kontrollerar {rot}")
    print(f"Sjalvstandiga kataloger: {', '.join(sjalvstandiga) or '(inga)'}")
    r = kontrollera(trad, sjalvstandiga, args.sok, MASKINER[args.arkitektur], system_stammar)
    if args.ut:
        with open(args.ut, "w", encoding="utf-8") as f:
            f.write("\n".join(r.rader) + "\n")
        print(f"Hela tabellen ({r.antal_filer} filer) skrevs till {args.ut}")
    print(f"{r.antal_filer} exe/dll/pyd-filer, {r.antal_importer} importer")
    print("Importer per hur de hittades: " + ", ".join(f"{k}: {v}" for k, v in sorted(r.vagar.items())))
    print(f"Windows egna DLL-filer som anvands ({len(r.system)}): {' '.join(sorted(r.system))}")
    if r.system_utanfor_listan:
        res.info("DLL-filer som inte ar i skriptets lista men finns i --system-katalog (laggs till i SYSTEM om de ar "
                 "Windows egna): " + " ".join(sorted(r.system_utanfor_listan)))
    for fel in r.fel:
        res.fel(fel)
    if r.saknas:
        print("Saknade DLL-filer och vilka filer som importerar dem:")
        for dll, filer in sorted(r.saknas.items()):
            print(f"  {dll}: {len(filer)} filer, till exempel {', '.join(filer[:4])}")
    if r.antal_filer == 0:
        res.fel(f"inga exe-, dll- eller pyd-filer hittades under {rot}")
    if not r.fel and r.antal_filer:
        res.ok(f"alla {r.antal_filer} filer ar {args.arkitektur} och hittar alla sina {r.antal_importer} importer")
    return res.sammanfatta()


if __name__ == "__main__":
    sys.exit(main())
