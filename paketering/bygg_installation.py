"""Bygger installationsfilen (dist/Akasha-Protokoll-installation.exe) med Inno Setups ISCC.exe ur dist/Akasha Protokoll/.

    python paketering/bygg_installation.py --version 0.2.0.1 --kalla "dist/Akasha Protokoll" --ikon build/app/ikon.ico --ut dist

Letar upp ISCC.exe (Inno Setup 6 under Program Files, annars PATH), skriver ut versionen och vilka sprakfiler som
finns, kor kompilatorn och kontrollerar att filen blev till. Saknas ISCC.exe blir det ett tydligt FEL och inget annat
hindras. Varje kontroll skriver OK: eller FEL:; slutkod 1 om nagot var FEL.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

import kontroll_hjalp

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKRIPT = os.path.join(ROT, "paketering", "akasha-protokoll.iss")
UTFIL = "Akasha-Protokoll-installation.exe"


def kandidater(miljo, which=shutil.which):
    """Platser att leta pa, i ordning: vanliga installationskataloger, sedan PATH."""
    ut = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        bas = miljo.get(var)
        if bas:
            delar = ("Programs", "Inno Setup 6") if var == "LOCALAPPDATA" else ("Inno Setup 6",)
            ut.append(os.path.join(bas, *delar, "ISCC.exe"))
    ut.append(os.path.join(r"C:\Program Files (x86)", "Inno Setup 6", "ISCC.exe"))
    pa_path = which("ISCC") or which("ISCC.exe")
    if pa_path:
        ut.append(pa_path)
    return ut


def hitta_iscc(miljo=None, finns=os.path.isfile, which=shutil.which):
    """-> (sokvag eller None, lista over var som sokts)."""
    sokt = kandidater(os.environ if miljo is None else miljo, which)
    for s in sokt:
        if finns(s):
            return s, sokt
    return None, sokt


def versionsrad(text):
    """Raden med Inno Setups version ur ISCC:s hjalptext, eller None."""
    for rad in text.splitlines():
        if re.search(r"Inno Setup \d", rad):
            return rad.strip()
    return None


def main(argv=None):
    kontroll_hjalp.utf8_utskrift()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--version", required=True, help="till exempel 0.2.0.1 (samma som i versionsresursen)")
    ap.add_argument("--kalla", required=True, help="katalogen som installeras, dist/Akasha Protokoll")
    ap.add_argument("--ikon", required=True)
    ap.add_argument("--ut", required=True, help="katalogen installationsfilen skrivs i")
    args = ap.parse_args(argv)
    res = kontroll_hjalp.Resultat("BYGGE AV INSTALLATIONSFILEN")

    iscc, sokt = hitta_iscc()
    if iscc is None:
        res.fel("ISCC.exe (Inno Setup) hittades inte. Sokte: " + "; ".join(sokt))
        return res.sammanfatta()
    res.ok(f"ISCC.exe: {iscc}")
    hjalp = subprocess.run([iscc, "/?"], capture_output=True, timeout=60)
    text = (hjalp.stdout + hjalp.stderr).decode("utf-8", "replace")
    print("Version: " + (versionsrad(text) or "(okand, se hjalptexten nedan)"))
    if not versionsrad(text):
        print(text[:800])
    sprak = os.path.join(os.path.dirname(iscc), "Languages")
    filer = sorted(os.listdir(sprak)) if os.path.isdir(sprak) else []
    print(f"Sprakfiler i {sprak}: {len(filer)} st; Swedish.isl finns: {'ja' if 'Swedish.isl' in filer else 'NEJ'}")
    if "Swedish.isl" not in filer:
        print("INFO: guiden blir pa engelska utom de egna texterna (Swedish.isl foljer inte med den har Inno Setup)")

    for namn, sokvag in (("--kalla", args.kalla), ("--ikon", args.ikon)):
        if not os.path.exists(sokvag):
            res.fel(f"{namn} {sokvag} finns inte")
    if res.fel_rader:
        return res.sammanfatta()
    os.makedirs(args.ut, exist_ok=True)
    utfil = os.path.join(args.ut, UTFIL)
    if os.path.exists(utfil):
        os.remove(utfil)
    kommando = [iscc, f"/DVersion={args.version}", f"/DKalla={os.path.abspath(args.kalla)}",
                f"/DIkon={os.path.abspath(args.ikon)}", f"/DUt={os.path.abspath(args.ut)}", SKRIPT]
    print("Kommando:", kommando, flush=True)
    p = subprocess.run(kommando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
    print(p.stdout.decode("utf-8", "replace"), flush=True)
    res.kontrollera(p.returncode == 0, "ISCC.exe avslutades med kod 0", f"ISCC.exe avslutades med kod {p.returncode} (se utskriften ovan)")
    if os.path.isfile(utfil):
        res.ok(f"{utfil} skapad ({os.path.getsize(utfil)} byte)")
    else:
        res.fel(f"{utfil} blev inte till")
    return res.sammanfatta()


if __name__ == "__main__":
    sys.exit(main())
