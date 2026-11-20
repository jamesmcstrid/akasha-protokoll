"""Kontrollerar att FFmpeg-biblioteken i ett PyAV-hjul eller ett byggt program bara har LGPL-delar. Det ska hindra att ett
GPL-bygge (som PyPI-hjulet, med x264 och x265 inlankade) nagonsin foljer med utan att nagon marker.

    python paketering/kontrollera_ffmpeg.py --hjul FIL.whl [--komponenter paketering/ffmpeg-komponenter.txt]
    python paketering/kontrollera_ffmpeg.py --katalog DIST_ELLER_APP [--komponenter ...]

Kontrollerna (varje skriver OK: eller FEL:, alla kors, sist en sammanfattning, slutkod 1 vid FEL):
 1. Exakt sju FFmpeg-bibliotek (avutil, avcodec, avformat, avfilter, avdevice, swresample, swscale), vart och ett en gang.
    Symboliska lankar rakas inte (PyInstaller lagger sadana pa toppnivan).
 2. Varje bibliotek har strangen "<namn> license: LGPL version 2.1 or later" och inte "license: GPL", "LGPL version 3"
    eller "nonfree".
 3. Configure-raden (strangen som borjar med --prefix=) har inte --enable-gpl, --enable-version3, --enable-nonfree eller
    --enable-lib, och har varje rad i ffmpeg-komponenter.txt.
 4. Inga forbjudna filnamn (libx264, libx265, postproc, ...) nagonstans, och i av.libs, av/.dylibs och av/__dot__dylibs
    far bara de sju finnas (fangar libwinpthread, libgcc_s, zlib1, liblzma m.fl.).
 5. Windows (om pefile finns): DLL-filernas importer bara bland Windows egna DLL-filer och varandra. Fel pa msvcrt.dll
    (fel MSYS2-miljo), libgcc_s*, libwinpthread* och libstdc++*.
"""
import argparse
import glob
import os
import re
import sys
import zipfile

import kontroll_hjalp

BIBLIOTEK = ("avutil", "avcodec", "avformat", "avfilter", "avdevice", "swresample", "swscale")
LIBNAMN = re.compile(r"^(?:lib)?(" + "|".join(BIBLIOTEK) + r")(?=[-._])")
FORBJUDNA_NAMN = (
    "libx264", "libx265", "postproc", "libmp3lame", "libtwolame", "libbluray", "libgmp", "libiconv", "libopencore", "libaom",
    "libdav1d", "libvpx", "libopus", "libogg", "libvorbis", "libspeex", "libwebp", "libsharpyuv", "libopenjp2", "libxml2",
    "libfreetype", "libfontconfig", "libpng16")
BARA_FFMPEG_I = ("av.libs/", "av/.dylibs/", "av/__dot__dylibs/")
FORBJUDET_I_LICENS = (b"license: GPL", b"LGPL version 3", b"nonfree")
FORBJUDET_I_CONFIGURE = ("--enable-gpl", "--enable-version3", "--enable-nonfree", "--enable-lib")
FORBJUDNA_IMPORTER = ("msvcrt", "libgcc_s", "libwinpthread", "libstdc++")


class Post:
    """En fil i hjulet eller katalogen: sokvag (med /) och en funktion som ger innehallet."""

    def __init__(self, sokvag, las):
        self.sokvag = sokvag
        self.las = las

    @property
    def namn(self):
        return self.sokvag.rsplit("/", 1)[-1]


def poster_ur_hjul(sokvag):
    z = zipfile.ZipFile(sokvag)
    return [Post(i.filename, (lambda n=i.filename: z.read(n))) for i in z.infolist() if not i.filename.endswith("/")]


def poster_ur_katalog(rot):
    ut = []
    for mapp, _k, filer in os.walk(rot):
        for f in sorted(filer):
            full = os.path.join(mapp, f)
            if os.path.islink(full):
                continue  # PyInstaller lagger lankar pa toppnivan till filerna i av.libs
            ut.append(Post(os.path.relpath(full, rot).replace(os.sep, "/"), (lambda p=full: open(p, "rb").read())))
    return ut


def las_komponenter(sokvag):
    with open(sokvag, encoding="utf-8") as f:
        return [r.strip() for r in f.read().splitlines() if r.strip() and not r.lstrip().startswith("#")]


def ar_bibliotek(post):
    """Biblioteksnamnet (avcodec ...) om filen ar ett FFmpeg-bibliotek, annars None."""
    n = post.namn.lower()
    m = LIBNAMN.match(n)
    if not m or not (n.endswith(".dll") or ".dylib" in n or ".so" in n):
        return None
    return m.group(1)


def configure_rad(data):
    """Configure-raden som star inbyggd i biblioteket (borjar med --prefix=), utan citattecken, eller None."""
    m = re.search(rb"--prefix=[\x20-\x7e]+", data)
    return m.group(0).decode("ascii").replace("'", "") if m else None


def bedom_importer(importer):
    """-> lista med skal till FEL for en DLLs importer (Windows). Tom lista = godkand."""
    fel = []
    for dll in importer:
        n = dll.lower()
        if n.startswith(FORBJUDNA_IMPORTER):
            fel.append(f"importerar {dll}")
            continue
        if re.match(r"^(?:lib)?(?:" + "|".join(BIBLIOTEK) + r")[-._]", n) or n.startswith("api-ms-win-"):
            continue
        if n.rsplit(".", 1)[0] in ("kernel32", "bcrypt", "advapi32", "user32", "ole32", "shell32", "ucrtbase", "kernelbase",
                                    "ntdll", "ws2_32", "oleaut32", "gdi32", "ext-ms-win-ntuser-window-l1-1-0"):
            continue
        fel.append(f"importerar {dll}, som inte ar en Windows-DLL eller ett FFmpeg-bibliotek")
    return fel


def importer_ur(data):
    """Importerna (importtabell och fordrojda) ur en PE-fil med pefile, eller None om pefile saknas."""
    try:
        import pefile
    except ImportError:
        return None
    pe = pefile.PE(data=data, fast_load=True)
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                               pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        return [e.dll.decode("ascii", "replace") for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
                + getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])]
    finally:
        pe.close()


def kontrollera(poster, komponenter, res):
    # 1. Exakt sju bibliotek, vart och ett en gang
    bibl = [(ar_bibliotek(p), p) for p in poster]
    bibl = [(n, p) for n, p in bibl if n]
    funna = {}
    for n, p in bibl:
        funna.setdefault(n, []).append(p.sokvag)
    print("FFmpeg-bibliotek: " + (", ".join(f"{n}={v}" for n, v in sorted(funna.items())) or "(inga)"))
    saknas = [n for n in BIBLIOTEK if n not in funna]
    dubbla = {n: v for n, v in funna.items() if len(v) > 1}
    if saknas:
        res.fel(f"saknade FFmpeg-bibliotek: {', '.join(saknas)} (väntade exakt sju)")
    if dubbla:
        res.fel("FFmpeg-bibliotek som finns mer än en gång: " + "; ".join(f"{n}: {v}" for n, v in dubbla.items()))
    if not saknas and not dubbla and len(bibl) == 7:
        res.ok("exakt sju FFmpeg-bibliotek, vart och ett en gång: " + ", ".join(sorted(funna)))

    # 2 och 3. Licensstrang och configure-rad i varje bibliotek
    for n, p in sorted(bibl, key=lambda x: x[0]):
        data = p.las()
        god = (b"lib" + n.encode() + b" license: LGPL version 2.1 or later") in data
        stracka = re.search(rb"lib" + n.encode() + rb" license: [\x20-\x7e]+", data)
        text = stracka.group(0).decode("ascii") if stracka else "(ingen licensträng)"
        if god:
            res.ok(f"{p.sokvag}: {text}")
        else:
            res.fel(f"{p.sokvag}: licensen är inte LGPL 2.1 eller senare ({text})")
        for fel_ord in FORBJUDET_I_LICENS:
            if fel_ord in data:
                res.fel(f"{p.sokvag}: innehåller '{fel_ord.decode()}'")
        rad = configure_rad(data)
        if rad is None:
            res.fel(f"{p.sokvag}: ingen configure-rad (--prefix=...) i biblioteket")
            continue
        forbjudet = [f for f in FORBJUDET_I_CONFIGURE if f in rad]
        if forbjudet:
            res.fel(f"{p.sokvag}: configure-raden har {' '.join(forbjudet)}")
        saknade = [k for k in komponenter if k not in rad]
        if saknade:
            res.fel(f"{p.sokvag}: configure-raden saknar {' '.join(saknade)} ur ffmpeg-komponenter.txt")
        if not forbjudet and not saknade:
            res.ok(f"{p.sokvag}: configure-raden har inga GPL- eller externa flaggor och alla {len(komponenter)} flaggor ur komponentfilen")
    if bibl:
        rader = {configure_rad(p.las()) for _n, p in bibl}
        print("configure-raden: " + (sorted(r for r in rader if r) or ["(ingen)"])[0])

    # 4. Forbjudna filnamn, och bara de sju i FFmpegs bibliotekskataloger
    forbjudna = [p.sokvag for p in poster if any(f in p.namn.lower() for f in FORBJUDNA_NAMN)]
    for s in forbjudna:
        res.fel(f"förbjuden fil (ett bibliotek som inte ska vara med): {s}")
    extra = [p.sokvag for p in poster if any(k in p.sokvag for k in BARA_FFMPEG_I) and not ar_bibliotek(p)]
    for s in extra:
        res.fel(f"en annan fil än de sju FFmpeg-biblioteken ligger bland dem: {s}")
    if not forbjudna and not extra:
        res.ok("inga förbjudna filnamn, och inget annat än de sju bland FFmpeg-biblioteken")

    # 5. Windows: importer
    dllar = [p for n, p in bibl if p.namn.lower().endswith(".dll")]
    if dllar:
        kollade = 0
        for p in dllar:
            importer = importer_ur(p.las())
            if importer is None:
                res.info("importkontrollen hoppades över: pefile saknas")
                break
            kollade += 1
            for skal in bedom_importer(importer):
                res.fel(f"{p.sokvag}: {skal}")
        else:
            res.kontrollera(not any(f.startswith(p.sokvag + ":") for f in res.fel_rader for p in dllar),
                            f"importerna i de {kollade} DLL-filerna är bara Windows egna DLL-filer och varandra",
                            "DLL-filernas importer stämmer inte (se raderna ovan)")


def main(argv=None):
    kontroll_hjalp.utf8_utskrift()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    grupp = ap.add_mutually_exclusive_group(required=True)
    grupp.add_argument("--hjul", help="PyAV-hjulet (.whl), jokertecken godtas")
    grupp.add_argument("--katalog", help="dist/ eller programkatalogen")
    ap.add_argument("--komponenter", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg-komponenter.txt"))
    args = ap.parse_args(argv)
    res = kontroll_hjalp.Resultat("KONTROLL AV FFMPEG")
    try:
        komponenter = las_komponenter(args.komponenter)
    except OSError as e:
        res.fel(f"kunde inte läsa {args.komponenter}: {e}")
        return res.sammanfatta()
    if args.hjul:
        traffar = sorted(glob.glob(args.hjul))
        if len(traffar) != 1:
            res.fel(f"--hjul {args.hjul} gav {len(traffar)} filer, väntade exakt en")
            return res.sammanfatta()
        print(f"Hjul: {traffar[0]}")
        poster = poster_ur_hjul(traffar[0])
    else:
        if not os.path.isdir(args.katalog):
            res.fel(f"{args.katalog} finns inte")
            return res.sammanfatta()
        print(f"Katalog: {args.katalog}")
        poster = poster_ur_katalog(args.katalog)
    print(f"{len(poster)} filer, {len(komponenter)} flaggor i komponentfilen")
    kontrollera(poster, komponenter, res)
    return res.sammanfatta()


if __name__ == "__main__":
    sys.exit(main())
