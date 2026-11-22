"""Smaverktyg for Windows-bygget, i Python sa att sokvagar med a, a och o och mellanslag inte passerar bash:
    python paketering/bygg_windows_verktyg.py lista KATALOG
    python paketering/bygg_windows_verktyg.py runtime KATALOG       kopierar in C-runtime-DLL:erna som filerna importerar
    python paketering/bygg_windows_verktyg.py ikon PNG ICO
    python paketering/bygg_windows_verktyg.py versionsfil UTFIL VERSION BYGGNUMMER
    python paketering/bygg_windows_verktyg.py exeinfo EXE            versionsresurs, ikon och fonsterprogram (pefile)
    python paketering/bygg_windows_verktyg.py forbjudet KATALOG
    python paketering/bygg_windows_verktyg.py pianissimo KATALOG    onnx-asr, onnxruntime och sentencepiece ska vara med
    python paketering/bygg_windows_verktyg.py storlekar KATALOG
    python paketering/bygg_windows_verktyg.py zip KATALOG ZIPFIL
    python paketering/bygg_windows_verktyg.py uppacka ZIPFIL MAPP
Varje kommando skriver OK:, FEL: eller INFO: och ger slutkod 1 vid FEL.
"""
import fnmatch
import glob
import os
import shutil
import subprocess
import sys
import zipfile

import kontroll_hjalp
import kontrollera_pe

VERSIONSTEXT = """# UTF-8
# Skrivs av paketering/bygg_windows_verktyg.py och lases av PyInstaller (EXE(version=...)).
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={filevers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('041D04B0', [
        StringStruct('FileDescription', {namn}),
        StringStruct('FileVersion', {versionstext}),
        StringStruct('InternalName', {namn}),
        StringStruct('LegalCopyright', {upphovsratt}),
        StringStruct('OriginalFilename', {filnamn}),
        StringStruct('ProductName', {namn}),
        StringStruct('ProductVersion', {versionstext})])
    ]),
    VarFileInfo([VarStruct('Translation', [1053, 1200])])
  ]
)
"""
NAMN = "Akasha Protokoll"
UTGIVARE = "Dennis Fredin"  # i upphovsratten, och som utgivare i installationsfilen (AppPublisher i .iss)
UPPHOVSRATT = f"\u00a9 2026 {UTGIVARE}. Apache-2.0."


def versionstext(version, byggnummer):
    """Texten i versionsfilen (PyInstallers VSVersionInfo). Ren ASCII: tecken som copyright-tecknet skrivs som
    \\xa9 i stringvardena, sa att filen lases lika oavsett kodning."""
    delar = [int(d) for d in str(version).split(".")][:3]
    delar += [0] * (3 - len(delar))
    delar.append(int(byggnummer))
    return VERSIONSTEXT.format(
        filevers=tuple(delar), namn=ascii(NAMN), versionstext=ascii(".".join(str(d) for d in delar)),
        upphovsratt=ascii(UPPHOVSRATT), filnamn=ascii(NAMN + ".exe"))


def ar_forbjudet(namn, ar_katalog):
    """Namnet pa en fil eller katalog som inte ska finnas i programmet: faster-whisper-stacken och tkinter.
    onnxruntime ska vara med (Pianissimo, och sherpa-onnx har en egen onnxruntime.dll), och matchas darfor inte."""
    n = namn.lower()
    return n.startswith(("faster_whisper", "ctranslate2", "tokenizers", "huggingface_hub", "hf_xet",
                         "tkinter", "_tkinter", "tcl86", "tk86"))


def hitta_forbjudna(rot):
    funna = []
    for mapp, kataloger, filer in os.walk(rot):
        for namn in kataloger:
            if ar_forbjudet(namn, True):
                funna.append(os.path.join(mapp, namn))
        for namn in filer:
            if ar_forbjudet(namn, False):
                funna.append(os.path.join(mapp, namn))
    return sorted(funna)


# Pianissimo (MOTOR=pianissimo) i programmet: filer (med * som joker) som onnx-asr, onnxruntime och sentencepiece behover.
PIANISSIMO_FILER = ("onnx_asr/preprocessors/data/fbanks.npz", "onnx_asr-*.dist-info/METADATA",
                    "onnxruntime/capi/onnxruntime.dll", "onnxruntime/capi/onnxruntime_pybind11_state*.pyd",
                    "sentencepiece/_sentencepiece*.pyd")


def saknad_pianissimo(rot):
    """De mönster i PIANISSIMO_FILER som ingen fil i trädet under rot motsvarar."""
    alla = [os.path.relpath(os.path.join(mapp, f), rot).replace(os.sep, "/").lower()
            for mapp, _k, filer in os.walk(rot) for f in filer]
    return [m for m in PIANISSIMO_FILER
            if not any(fnmatch.fnmatchcase(a, "*/" + m.lower()) or fnmatch.fnmatchcase(a, m.lower()) for a in alla)]


def katalogstorlek(rot):
    total = 0
    for mapp, _k, filer in os.walk(rot):
        for f in filer:
            try:
                total += os.lstat(os.path.join(mapp, f)).st_size
            except OSError:
                pass
    return total


def storlekar_i(rot):
    """[(bytes, namn)] for varje post direkt i rot, storst forst."""
    ut = []
    for namn in os.listdir(rot):
        sokvag = os.path.join(rot, namn)
        ut.append((katalogstorlek(sokvag) if os.path.isdir(sokvag) else os.lstat(sokvag).st_size, namn))
    return sorted(ut, reverse=True)


def vs_kataloger():
    """Visual Studios installationskataloger: vswhere om den finns, annars de vanliga platserna."""
    kataloger = []
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = os.path.join(pf86, "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if os.path.isfile(vswhere):
        try:
            ut = subprocess.run([vswhere, "-all", "-products", "*", "-property", "installationPath"],
                                capture_output=True, text=True, timeout=60, errors="replace").stdout
            kataloger += [r.strip() for r in ut.splitlines() if r.strip()]
        except (OSError, subprocess.SubprocessError):
            pass
    for pf in {os.environ.get("ProgramFiles", r"C:\Program Files"), pf86}:
        kataloger += glob.glob(os.path.join(pf, "Microsoft Visual Studio", "*", "*"))
    sedda, ut = set(), []
    for k in kataloger:
        if k.lower() not in sedda and os.path.isdir(k):
            sedda.add(k.lower())
            ut.append(k)
    return ut


def _versionsnyckel(sokvag):
    """Sorteringsnyckel for ...\\MSVC\\14.44.35207\\x64\\...: versionen som tal (14.9 < 14.44)."""
    delar = sokvag.replace("\\", "/").split("/")
    for i, d in enumerate(delar[:-1]):
        if d.upper() == "MSVC":
            return tuple(int(x) if x.isdigit() else 0 for x in delar[i + 1].split("."))
    return ()


def filversion(sokvag):
    """Filversionen ur versionsresursen (pefile), eller None."""
    try:
        import pefile

        pe = pefile.PE(sokvag, fast_load=True)
        try:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
            f = pe.VS_FIXEDFILEINFO[0]
            return f"{f.FileVersionMS >> 16}.{f.FileVersionMS & 0xFFFF}.{f.FileVersionLS >> 16}.{f.FileVersionLS & 0xFFFF}"
        finally:
            pe.close()
    except Exception:
        return None


def system32():
    return os.path.join(os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or r"C:\Windows", "System32")


def redist_kandidater(namn):
    """Filer med det namnet i Visual Studios VC\\Redist\\MSVC\\<version>\\x64\\Microsoft.VC*.CRT och .OpenMP, hogsta versionen forst."""
    traffar = []
    for vs in vs_kataloger():
        traffar += glob.glob(os.path.join(vs, "VC", "Redist", "MSVC", "*", "x64", "Microsoft.VC*.*", namn))
    traffar = [t for t in traffar if "debug_nonredist" not in t.lower() and os.path.isfile(t)]
    return sorted(set(traffar), key=lambda t: (_versionsnyckel(t), t), reverse=True)


def hitta_runtime(namn):
    """-> (sokvag, var) for en C-runtime-DLL. Forst Visual Studios Redist-katalog (hogsta versionen): filen ska vara
    minst lika ny som kompilatorn som byggde, och Redist-katalogen hor till den. Sedan System32, som kan ha en aldre.
    (None, text) om den inte finns."""
    sok = redist_kandidater(namn)
    sys32 = os.path.join(system32(), namn)
    for s in sok + [sys32]:
        if os.path.isfile(s):
            return s, None
    return None, "sokte: " + "; ".join((sok or ["(ingen Redist-katalog)"])[:4] + [sys32])


def kopiera_runtime(katalog, res):
    """Kopierar in de C-runtime-DLL:er (vcruntime140, msvcp140, vcomp140 ...) som filerna i katalogen importerar,
    tills inga saknas. En whisper-cli startad i sin egen katalog letar bara dar och i Windows egna kataloger."""
    kopierade = []
    for _varv in range(6):
        trad = kontrollera_pe.las_trad(katalog)
        saknas = [n for n in kontrollera_pe.vc_saknas(trad) if n.lower() not in {k.lower() for k in kopierade}]
        if not saknas:
            break
        for namn in saknas:
            kalla, text = hitta_runtime(namn)
            if kalla is None:
                res.fel(f"{namn} importeras men hittades inte ({text})")
                kopierade.append(namn)
                continue
            shutil.copy2(kalla, os.path.join(katalog, namn))
            kopierade.append(namn)
            jamfor = os.path.join(system32(), namn)
            res.ok(f"{namn} kopierad fran {kalla} (version {filversion(kalla) or 'okand'}, {os.path.getsize(kalla)} byte); "
                   f"samma fil i System32: "
                   + (f"version {filversion(jamfor) or 'okand'}" if os.path.isfile(jamfor) else "finns inte"))
    if not kopierade:
        res.ok("inga C-runtime-DLL:er saknas (filerna importerar inga, eller de ligger redan bredvid)")
    return kopierade


def exe_info(sokvag, res):
    """Versionsresursen, ikonen och undersystemet i en exe-fil: syns under Egenskaper och avgor om en konsol oppnas."""
    import pefile

    pe = pefile.PE(sokvag)
    try:
        strangar = {}
        for fi in getattr(pe, "FileInfo", None) or []:
            for post in fi:
                if getattr(post, "Key", b"") == b"StringFileInfo":
                    for tabell in post.StringTable:
                        for k, v in tabell.entries.items():
                            strangar[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
        for k in sorted(strangar):
            print(f"  {k}: {strangar[k]}")
        res.kontrollera(strangar.get("LegalCopyright") == UPPHOVSRATT and strangar.get("ProductName") == NAMN,
                        f"versionsresursen har ProductName {NAMN} och upphovsratten {UPPHOVSRATT}",
                        f"versionsresursen saknas eller har fel text (LegalCopyright {strangar.get('LegalCopyright')!r}, "
                        f"ProductName {strangar.get('ProductName')!r})")
        ikongrupper = 0
        for e in getattr(getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None), "entries", []) or []:
            if e.id == pefile.RESOURCE_TYPE["RT_GROUP_ICON"]:
                ikongrupper = len(e.directory.entries)
        res.kontrollera(ikongrupper > 0, f"exe-filen har en ikon ({ikongrupper} ikongrupp)", "exe-filen har ingen ikon")
        undersystem = pe.OPTIONAL_HEADER.Subsystem
        res.kontrollera(undersystem == pefile.SUBSYSTEM_TYPE["IMAGE_SUBSYSTEM_WINDOWS_GUI"],
                        "undersystemet ar Windows GUI (ingen konsol oppnas)",
                        f"undersystemet ar {undersystem}, vantade 2 (GUI): console=False galler inte")
    finally:
        pe.close()


def lista(katalog):
    print(f"Filer i {katalog}:")
    total = 0
    for mapp, _k, filer in sorted(os.walk(katalog)):
        for f in sorted(filer):
            p = os.path.join(mapp, f)
            storlek = os.path.getsize(p)
            total += storlek
            print(f"  {storlek:>10}  {os.path.relpath(p, katalog)}")
    print(f"Summa: {total} byte ({total / 1e6:.1f} MB)")


def skapa_ikon(png, ico, res):
    from PIL import Image

    storlekar = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    with Image.open(png) as bild:
        bild.convert("RGBA").save(ico, format="ICO", sizes=storlekar)
    with Image.open(ico) as ut:
        funna = sorted(ut.info.get("sizes", []))
    res.kontrollera(os.path.getsize(ico) > 0 and len(funna) == len(storlekar),
                    f"{ico} skapad ({os.path.getsize(ico)} byte, storlekar {[s[0] for s in funna]})",
                    f"{ico} har storlekarna {funna}, vantade {storlekar}")


def packa_zip(katalog, zipfil):
    """Mappen (till exempel dist/Akasha Protokoll) hamnar overst i zip-filen med sitt eget namn."""
    katalog = os.path.abspath(katalog)
    namn = os.path.basename(katalog)
    if os.path.exists(zipfil):
        os.remove(zipfil)
    antal = 0
    with zipfile.ZipFile(zipfil, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for mapp, kataloger, filer in os.walk(katalog):
            kataloger.sort()
            for f in sorted(filer):
                p = os.path.join(mapp, f)
                z.write(p, os.path.join(namn, os.path.relpath(p, katalog)))
                antal += 1
    return antal


def main(argv=None):
    kontroll_hjalp.utf8_utskrift()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    kmd, rest = argv[0], argv[1:]
    res = kontroll_hjalp.Resultat(f"bygg_windows_verktyg {kmd}")
    try:
        if kmd == "lista" and len(rest) == 1:
            lista(rest[0])
            return 0
        if kmd == "runtime" and len(rest) == 1:
            kopiera_runtime(rest[0], res)
        elif kmd == "ikon" and len(rest) == 2:
            skapa_ikon(rest[0], rest[1], res)
        elif kmd == "versionsfil" and len(rest) == 3:
            text = versionstext(rest[1], rest[2])
            with open(rest[0], "w", encoding="ascii", newline="\n") as f:
                f.write(text)
            res.ok(f"versionsfilen {rest[0]} skriven (version {rest[1]}.{rest[2]})")
        elif kmd == "exeinfo" and len(rest) == 1:
            exe_info(rest[0], res)
        elif kmd == "forbjudet" and len(rest) == 1:
            funna = hitta_forbjudna(rest[0])
            for f in funna:
                res.fel(f"finns i programmet men ska inte: {f}")
            if not funna:
                res.ok("ingen faster-whisper-stack (faster_whisper, ctranslate2, tokenizers, huggingface_hub, hf_xet) "
                       "och inget tkinter finns i programmet")
            for mapp, _k, filer in os.walk(rest[0]):
                for f in filer:
                    if f.lower() == "onnxruntime.dll":
                        res.info(f"{os.path.relpath(os.path.join(mapp, f), rest[0])} (onnxruntime.dll: ska vara med, "
                                 "i sherpa_onnx/lib och i onnxruntime/capi)")
        elif kmd == "pianissimo" and len(rest) == 1:
            saknas = saknad_pianissimo(rest[0])
            for m in saknas:
                res.fel(f"programmet har ingen fil som motsvarar {m} (Pianissimo)")
            if not saknas:
                res.ok("onnx-asr (data och dist-info), onnxruntime och sentencepiece finns i programmet")
        elif kmd == "storlekar" and len(rest) == 1:
            total = katalogstorlek(rest[0])
            print(f"Hela {rest[0]}: {total / 1e6:.1f} MB")
            intern = os.path.join(rest[0], "_internal")
            for rot in (rest[0], intern):
                if os.path.isdir(rot):
                    print(f"De 15 storsta posterna i {os.path.relpath(rot, rest[0])}:")
                    for storlek, namn in storlekar_i(rot)[:15]:
                        print(f"  {storlek / 1e6:>8.1f} MB  {namn}")
            return 0
        elif kmd == "zip" and len(rest) == 2:
            antal = packa_zip(rest[0], rest[1])
            res.ok(f"{rest[1]} skapad: {antal} filer, {os.path.getsize(rest[1])} byte")
        elif kmd == "uppacka" and len(rest) == 2:
            if os.path.isdir(rest[1]):
                shutil.rmtree(rest[1])
            os.makedirs(rest[1])
            with zipfile.ZipFile(rest[0]) as z:
                z.extractall(rest[1])
                antal = len(z.namelist())
            res.ok(f"{rest[0]} uppackad till {rest[1]} ({antal} poster)")
        else:
            print(__doc__)
            return 2
    except Exception as e:  # ett ovantat fel ska synas som FEL med typ, inte som en traceback ensam
        import traceback

        traceback.print_exc()
        res.fel(f"{kmd}: {type(e).__name__}: {e}")
    return res.sammanfatta()


if __name__ == "__main__":
    sys.exit(main())
