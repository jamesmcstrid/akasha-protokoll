"""Kontrollerar licenserna i ett byggt program (katalogen licenser/ som samla_licenser.py skriver).

    python paketering/kontrollera_licenser.py --program SOKVAG

SOKVAG ar programfilen: .../Akasha Protokoll.app/Contents/MacOS/Akasha Protokoll (Mac; licenserna i
Contents/Resources/licenser), .../Akasha Protokoll.exe (Windows; licenser\\ bredvid exe-filen) eller
.../akasha-protokoll (Linux-provet; _internal/licenser).

Kontrollerna (varje skriver OK: eller FEL:, alla kors, sist en sammanfattning, slutkod 1 vid FEL):
 1. licenser/LICENSER.txt finns och har en forteckning, och den ar inte markerad OFULLSTANDIG eller PROV.
 2. Varje komponent i forteckningen har sin fil i licenser/, och filen ar inte tom.
 3. Varje Python-paket som finns i programmet star i forteckningen. Paketen hittas med paketen i den Python som kor
    kontrollen (byggets venv) som facit: filerna i programmets kataloger jamfors med paketens RECORD, och modulerna i
    programmets PYZ-arkiv (PyInstallers arkivlasare) med paketens moduler. En modul som inte hor till nagot paket,
    till Python eller till appen ar ocksa FEL. Finns inte PyInstaller kontrolleras bara filerna (en INFO-rad).
Kors av bygg-mac.sh, bygg-windows.sh och kontrollera.py (programmet ur zip-filen och det installerade programmet).
"""
import argparse
import importlib.metadata
import os
import re
import sys

import kontroll_hjalp

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORTECKNING = "LICENSER.txt"
SEP = " | "
STRECK = "---"
MARKERINGAR = ("OFULLSTÄNDIG", "PROV")
PYINSTALLERS_EGNA = ("pyimod", "pyi_", "_pyi_")


def normnamn(namn):
    return re.sub(r"[-_.]+", "-", namn).lower()


def platser(program):
    """-> (licenskatalogen, [kataloger med programmets filer]) for programfilen."""
    p = os.path.abspath(program)
    delar = p.replace("\\", "/").split("/Contents/MacOS/")
    if len(delar) == 2:
        app = delar[0]
        return (os.path.join(app, "Contents", "Resources", "licenser"),
                [os.path.join(app, "Contents", "Frameworks"), os.path.join(app, "Contents", "Resources")])
    katalog = os.path.dirname(p)
    if p.lower().endswith(".exe"):
        return os.path.join(katalog, "licenser"), [os.path.join(katalog, "_internal")]
    return os.path.join(katalog, "_internal", "licenser"), [os.path.join(katalog, "_internal")]


def las_forteckning(sokvag):
    """-> (rader [{namn, version, licens, kalla, fil}], markeringar som forsta raderna har)."""
    with open(sokvag, encoding="utf-8") as f:
        text = f.read()
    rader = text.splitlines()
    markeringar = [m for m in MARKERINGAR if any(r.startswith(m + ":") for r in rader[:3])]
    if STRECK not in rader:
        return [], markeringar
    ut = []
    for r in rader[rader.index(STRECK) + 1:]:
        if not r.strip():
            break
        falt = r.split(SEP)
        if len(falt) != 5:
            ut.append({"fel": r})
            continue
        ut.append(dict(zip(("namn", "version", "licens", "kalla", "fil"), (x.strip() for x in falt))))
    return ut, markeringar


def recordkartor(dists):
    """-> ({relativ sokvag i site-packages: normnamn}, {modulnamn: {normnamn}}) ur paketens RECORD."""
    filer, moduler = {}, {}
    for d in dists:
        try:
            namn = normnamn(d.metadata["Name"])
        except (KeyError, TypeError):
            continue
        for f in d.files or []:
            s = str(f).replace("\\", "/")
            if s.startswith("..") or "/__pycache__/" in f"/{s}":
                continue
            filer.setdefault(os.path.normcase(s), namn)
            for andelse in (".py", ".pyc"):
                if s.endswith(andelse):
                    mod = s[: -len(andelse)].replace("/", ".")
                    mod = mod[: -len(".__init__")] if mod.endswith(".__init__") else mod
                    moduler.setdefault(mod, set()).add(namn)
    return filer, moduler


def paket_i_filer(rotter, filkarta, licenskatalog):
    """{normnamn: en fil i programmet} for filerna i programmets kataloger som star i ett pakets RECORD."""
    hittat = {}
    for rot in rotter:
        if not os.path.isdir(rot):
            continue
        for mapp, kataloger, filer in os.walk(rot):
            if os.path.abspath(mapp) == os.path.abspath(licenskatalog):
                kataloger[:] = []
                continue
            for f in filer:
                full = os.path.join(mapp, f)
                if os.path.islink(full):
                    continue  # Mac: lankarna mellan Frameworks och Resources
                rel = os.path.relpath(full, rot).replace("\\", "/")
                namn = filkarta.get(os.path.normcase(rel))
                if namn:
                    hittat.setdefault(namn, rel)
    return hittat


def pyz_moduler(program):
    """Modulnamnen i programmets PYZ-arkiv, eller None om PyInstaller saknas. Ett lasfel ar ett undantag."""
    try:
        from PyInstaller.archive import readers
    except ImportError:
        return None
    pkg = readers.CArchiveReader(program)
    moduler = []
    for namn, post in pkg.toc.items():
        if post[-1] == readers.PKG_ITEM_PYZ:
            moduler += list(pkg.open_embedded_archive(namn).toc.keys())
    return moduler


def appens_moduler():
    app = os.path.join(ROT, "app")
    return {f[:-3] for f in os.listdir(app) if f.endswith(".py")} | {"app"} if os.path.isdir(app) else {"app"}


def paket_i_moduler(moduler, modulkarta, toppkarta):
    """-> ({normnamn: modul}, [moduler som inte hor till nagot paket, Python eller appen])."""
    hittat, okanda = {}, []
    stdlib = set(sys.stdlib_module_names)
    egna = appens_moduler()
    for mod in moduler:
        topp = mod.split(".")[0]
        if topp in stdlib or topp in egna or topp.startswith(PYINSTALLERS_EGNA):
            continue
        namn = modulkarta.get(mod) or {normnamn(n) for n in toppkarta.get(topp, [])}
        if not namn:
            okanda.append(mod)
            continue
        for n in sorted(namn):
            hittat.setdefault(n, mod)
    return hittat, okanda


def kontrollera(program, res, dists=None, las_pyz=None, toppkarta=None):
    licenser, rotter = platser(program)
    fil = os.path.join(licenser, FORTECKNING)
    if not os.path.isfile(fil):
        res.fel(f"{fil} saknas (licenserna följer inte med programmet: se LICENSER-raderna i PyInstallers utskrift)")
        return
    rader, markeringar = las_forteckning(fil)
    for m in markeringar:
        res.fel(f"{FORTECKNING} är markerad {m}: {'licenstexter saknas (se början av filen)' if m != 'PROV' else 'ett prov, inte för utdelning'}")
    trasiga = [r["fel"] for r in rader if "fel" in r]
    rader = [r for r in rader if "fel" not in r]
    for r in trasiga:
        res.fel(f"{FORTECKNING}: raden har inte fem fält (namn | version | licens | källa | fil): {r}")
    if not rader:
        res.fel(f"{FORTECKNING} har ingen förteckning (raderna efter {STRECK})")
        return
    saknade = []
    for r in rader:
        namn = r["fil"]
        sokvag = os.path.join(licenser, namn)
        if os.path.basename(namn) != namn or namn in ("", ".", ".."):
            saknade.append(f"{r['namn']}: filnamnet {namn!r} är inte en fil i licenser/")
        elif not os.path.isfile(sokvag) or os.path.getsize(sokvag) == 0:
            saknade.append(f"{r['namn']}: {namn} saknas eller är tom")
    for s in saknade:
        res.fel(f"komponenten {s}")
    if not saknade:
        res.ok(f"{len(rader)} komponenter i {FORTECKNING}, och var och en har sin fil i {licenser}")

    # 3. Paketen i programmet
    dists = list(importlib.metadata.distributions()) if dists is None else list(dists)
    filkarta, modulkarta = recordkartor(dists)
    i_forteckningen = {normnamn(r["namn"]) for r in rader}
    hittat = paket_i_filer(rotter, filkarta, licenser)
    kalla = {n: f"filen {f}" for n, f in hittat.items()}
    try:
        moduler = (las_pyz or pyz_moduler)(program)
    except Exception as e:  # noqa: BLE001  (PyInstallers lasare: vilket fel som helst ar ett FEL har)
        res.fel(f"modulerna i programmets PYZ-arkiv gick inte att läsa ({type(e).__name__}: {e})")
        moduler = []
    if moduler is None:
        res.info("PyInstaller finns inte i den här Python: modulerna i PYZ-arkivet kontrolleras inte, bara filerna")
    elif moduler:
        toppkarta = importlib.metadata.packages_distributions() if toppkarta is None else toppkarta
        ur_pyz, okanda = paket_i_moduler(moduler, modulkarta, toppkarta)
        for n, mod in ur_pyz.items():
            kalla.setdefault(n, f"modulen {mod}")
        for mod in sorted(okanda):
            res.fel(f"modulen {mod} i programmet hör inte till något paket i den här Python-miljön, till Python eller till appen")
        print(f"{len(moduler)} moduler i PYZ-arkivet, {len(ur_pyz)} paket bland dem", flush=True)
    utan = sorted(n for n in kalla if n not in i_forteckningen)
    for n in utan:
        res.fel(f"paketet {n} finns i programmet ({kalla[n]}) men inte i {FORTECKNING}")
    if kalla and not utan:
        res.ok(f"alla {len(kalla)} Python-paket i programmet står i {FORTECKNING}: {', '.join(sorted(kalla))}")
    elif not kalla:
        res.fel("hittade inga Python-paket i programmet (fel katalog, eller en annan Python-miljö än byggets?)")
    installerade = {normnamn(d.metadata["Name"]) for d in dists if d.metadata["Name"]}
    ej_i_programmet = sorted(n for n in i_forteckningen & installerade if n not in kalla)
    if ej_i_programmet:
        res.info(f"i förteckningen men inte hittade i programmet: {', '.join(ej_i_programmet)}")


def main(argv=None):
    kontroll_hjalp.utf8_utskrift()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--program", required=True)
    args = ap.parse_args(argv)
    res = kontroll_hjalp.Resultat("KONTROLL AV LICENSERNA")
    res.steg(f"licenserna i {args.program}")
    kontrollera(args.program, res)
    return res.sammanfatta()


if __name__ == "__main__":
    sys.exit(main())
