"""Kontrollerar sokvagar med a-ring, a-prickar och o-prickar och talaruppdelningen pa Windows: sherpa-onnx ska kunna
ladda rostmodellen fran en sokvag som har anvandarnamnet i sig, och talare.dela_upp() ska fungera pa ett testljud.

    python paketering/kontrollera_windows.py --hem HEM [--ordtider FIL] [--ljud-katalog KAT]

Kors efter paketering/kontrollera.py, med byggets venv (sherpa_onnx, numpy och PyAV finns dar) och samma --hem som den:
rostmodellen (40 MB) har da hamtats av programmet till <HEM>\\AppData\\Local\\Akasha Protokoll\\modeller\\talare\\.
Skriptet startar inget program och hamtar inget. --ordtider = JSON-filen som kontrollera_whisper_cli_windows.py skrev
(--ordtider-ut): riktiga ordtider fran den lilla modellen, som talare.dela_upp() ocksa provas med.

sherpa-onnx avslutar processen (exit) i stallet for att kasta ett undantag nar modellen inte gar att ladda. Darfor
kor varje prov i en egen underprocess, och ett krasch ger FEL med sokvagen som provades och, som diagnos, om modellen
gar att ladda fran en relativ sokvag (arbetskatalogen satt), fran 8.3-namnet eller fran en kopia i en ASCII-katalog:
det avgor vilken rattning som behovs (D28 i planen). Varje kontroll skriver OK: eller FEL:; slutkod 1 om nagot var FEL.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

import kontroll_hjalp

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAMNAMN = "Akasha Protokoll"
LJUDKATALOG = "Ljudprov Åäö"
RESULTAT = "RESULTAT "  # underprocessens sista rad: json


def modellkatalog(hem):
    return os.path.join(hem, "AppData", "Local", PROGRAMNAMN, "modeller")


def miljo_for(hem):
    """Miljon underprocesserna far: modellkatalogen under hem (och dess sokvag har a, a och o i sig)."""
    miljo = dict(os.environ)
    miljo.update(MODELLKATALOG=modellkatalog(hem), DATAKATALOG=os.path.join(hem, "AkashaProtokoll"), MOTOR="whispercpp",
                 MODELL="medium", PYTHONIOENCODING="utf-8")
    return miljo


# --- underprocesserna: ett prov var ---------------------------------------------------------------------------

def under_extraktor(modell, ljudfil):
    """sherpa_onnx.SpeakerEmbeddingExtractor med `modell` (som den ar skriven) och ett rostavtryck pa ljudfilen."""
    sys.path.insert(0, os.path.join(ROT, "app"))
    import numpy as np
    import sherpa_onnx

    import ljud

    print(f"sherpa_onnx {sherpa_onnx.__version__} fran {os.path.dirname(sherpa_onnx.__file__)}", flush=True)
    print(f"modell: {modell!r} (cwd {os.getcwd()!r})", flush=True)
    extraktor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=modell, num_threads=2))
    samples = ljud.avkoda(ljudfil)[: 10 * ljud.SR]
    s = extraktor.create_stream()
    s.accept_waveform(ljud.SR, samples)
    s.input_finished()
    v = np.asarray(extraktor.compute(s), dtype=np.float32)
    print(RESULTAT + json.dumps({"dim": int(extraktor.dim), "langd": int(v.size), "norm": float(np.linalg.norm(v)),
                                 "andlig": bool(np.isfinite(v).all()), "sekunder": len(samples) / ljud.SR}), flush=True)


def under_dela_upp(ljudfil, ordtider_fil):
    """talare.dela_upp() med rostmodellen pa standardplatsen (MODELLKATALOG) och antal = 2."""
    sys.path.insert(0, os.path.join(ROT, "app"))
    import ljud
    import talare

    print(f"talare.ROSTMODELL: {talare.ROSTMODELL!r}", flush=True)
    samples = ljud.avkoda(ljudfil)[: 60 * ljud.SR]
    langd = len(samples) / ljud.SR
    if ordtider_fil:
        with open(ordtider_fil, encoding="utf-8") as f:
            ord_lista = [(a, b, t, 0.9) for a, b, t in json.load(f)]
        kalla = f"{len(ord_lista)} riktiga ordtider ur {os.path.basename(ordtider_fil)}"
    else:
        ord_lista = [(i * 0.5, i * 0.5 + 0.4, f" ord{i}", 0.9) for i in range(int(langd / 0.5) - 1)]
        kalla = f"{len(ord_lista)} pahittade ordtider (ett ord var 0,5 s)"
    print(f"ljud: {langd:.1f} s, {kalla}", flush=True)
    repliker, antal, varning = talare.dela_upp(samples, ord_lista, 2)
    print(RESULTAT + json.dumps({"repliker": len(repliker), "antal": antal, "varning": varning,
                                 "talare": sorted({r["speaker"] for r in repliker})}), flush=True)


# --- foraldern -------------------------------------------------------------------------------------------------

def kor_under(res, hem, namn, args, cwd=None, tidsgrans=300):
    """Startar `python kontrollera_windows.py --under NAMN ARGS...` -> (slutkod, utskrift, resultat eller None)."""
    kommando = [sys.executable, os.path.abspath(__file__), "--under", namn, *args]
    try:
        p = subprocess.run(kommando, cwd=cwd, env=miljo_for(hem), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=tidsgrans)
        kod, ut = p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        kod, ut = None, (e.stdout or b"").decode("utf-8", "replace") + f"\n[tidsgrans {tidsgrans} s]"
    resultat = None
    for rad in ut.splitlines():
        if rad.startswith(RESULTAT):
            try:
                resultat = json.loads(rad[len(RESULTAT):])
            except ValueError:
                pass
    return kod, ut, resultat


def kort_sokvag(sokvag):
    """8.3-namnet (GetShortPathNameW) eller None."""
    if os.name != "nt":
        return None
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(sokvag, buf, 1024)
    return buf.value if 0 < n < 1024 else None


def diagnos(res, hem, modell, ljudfil):
    """Efter ett misslyckat prov: gar modellen att ladda pa annat satt? Bara INFO (det avgor vilken rattning som behovs)."""
    res.info("diagnos: laddar sherpa-onnx modellen pa nagot annat satt?")
    katalog, namn = os.path.split(modell)
    forsok = [("relativ sokvag med arbetskatalogen satt till modellkatalogen", namn, katalog)]
    kort = kort_sokvag(modell)
    forsok.append((f"8.3-namnet {kort!r}" if kort else "8.3-namnet (finns inte)", kort, None))
    # En ASCII-katalog: pa Windows direkt under systemenheten (anvandarens temp-katalog har ju anvandarnamnet i sig).
    bas = os.environ.get("SystemDrive", "C:") + os.sep if os.name == "nt" else None
    try:
        ascii_kat = tempfile.mkdtemp(prefix="akasha-ascii-", dir=bas)
    except OSError:
        ascii_kat = tempfile.mkdtemp(prefix="akasha-ascii-")
    try:
        kopia = os.path.join(ascii_kat, namn)
        shutil.copyfile(modell, kopia)
        forsok.append((f"en kopia i en ASCII-katalog ({ascii_kat})", kopia, None))
        for text, sokvag, cwd in forsok:
            if sokvag is None:
                res.info(f"diagnos: {text}: inte prov")
                continue
            kod, ut, r = kor_under(res, hem, "extraktor", [sokvag, ljudfil], cwd=cwd, tidsgrans=120)
            res.info(f"diagnos: {text}: {'FUNGERADE' if r else f'fungerade inte (kod {kod})'}")
    finally:
        shutil.rmtree(ascii_kat, True)


def main(argv=None):
    kontroll_hjalp.utf8_utskrift()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hem")
    ap.add_argument("--ordtider", help="JSON med ordtider fran kontrollen av whisper-cli")
    ap.add_argument("--ljud-katalog", help="var testljuden kopieras (standard: <hem>/" + LJUDKATALOG + ")")
    ap.add_argument("--under", help=argparse.SUPPRESS)
    ap.add_argument("rest", nargs="*", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.under == "extraktor":
        under_extraktor(*args.rest)
        return 0
    if args.under == "dela_upp":
        under_dela_upp(args.rest[0], args.rest[1] if len(args.rest) > 1 and args.rest[1] else None)
        return 0
    if not args.hem:
        ap.error("--hem krävs")

    hem = os.path.abspath(args.hem)
    res = kontroll_hjalp.Resultat("KONTROLL AV SÖKVÄGAR OCH TALARE")
    print(f"Hemkatalog: {hem}")
    os.environ.update(miljo_for(hem))
    sys.path.insert(0, os.path.join(ROT, "app"))

    # 1. Rostmodellen som programmet hamtade: rimlig plats, ratt storlek och ratt sha256.
    res.steg("1. rostmodellen under en sokvag med å, ä och ö")
    import modeller

    fil = modeller.PAKET["talare"][0]
    modell = fil.sokvag()
    print(f"Sökvägen som provas: {modell}")
    res.kontrollera(any(ord(c) > 127 for c in modell), "sökvägen har tecken utanför ASCII (som ett användarnamn med å, ä eller ö)",
                    "sökvägen har bara ASCII: ge --hem en katalog med å, ä eller ö i namnet, annars provas ingenting")
    if not os.path.isfile(modell):
        res.fel(f"röstmodellen finns inte: {modell} (kör paketering/kontrollera.py med --riktig-rostmodell först)")
        return res.sammanfatta()
    h = hashlib.sha256()
    with open(modell, "rb") as f:
        for bit in iter(lambda: f.read(1 << 20), b""):
            h.update(bit)
    res.kontrollera(os.path.getsize(modell) == fil.storlek and h.hexdigest() == fil.sha256,
                    f"röstmodellen har rätt storlek ({fil.storlek} byte) och sha256",
                    f"röstmodellen har storlek {os.path.getsize(modell)} och sha256 {h.hexdigest()}, väntade {fil.storlek} och {fil.sha256}")

    # 2. Testljuden under en katalog med a, a och o: PyAV (FFmpeg) ska kunna oppna dem.
    res.steg("2. avkodning av en ljudfil under en katalog med å, ä och ö")
    import ljud

    ljudkat = os.path.abspath(args.ljud_katalog) if args.ljud_katalog else os.path.join(hem, LJUDKATALOG)
    os.makedirs(ljudkat, exist_ok=True)
    kopior = {}
    for namn in ("en-talare.m4a", "tva-talare.m4a"):
        kopior[namn] = os.path.join(ljudkat, namn)
        shutil.copyfile(os.path.join(ROT, "testljud", namn), kopior[namn])
    for namn, sokvag in kopior.items():
        try:
            langd = len(ljud.avkoda(sokvag)) / ljud.SR
            res.kontrollera(langd > 5, f"{sokvag} avkodad med PyAV: {langd:.1f} s", f"{sokvag} gav bara {langd:.1f} s")
        except Exception as e:
            res.fel(f"{sokvag} gick inte att avkoda: {type(e).__name__}: {e}")

    # 3. sherpa-onnx: ladda modellen fran sokvagen och rakna ett rostavtryck.
    res.steg("3. sherpa-onnx SpeakerEmbeddingExtractor (egen process)")
    kod, ut, r = kor_under(res, hem, "extraktor", [modell, kopior["en-talare.m4a"]])
    print(ut)
    if r is None:
        res.fel(f"sherpa-onnx klarade inte röstmodellen på sökvägen {modell!r} (slutkod {kod}, se utskriften ovan)")
        diagnos(res, hem, modell, kopior["en-talare.m4a"])
    else:
        res.kontrollera(r["dim"] > 0 and r["langd"] == r["dim"] and r["andlig"] and r["norm"] > 0,
                        f"röstavtrycket har längd {r['langd']} (= extraktorns dim {r['dim']}), är ändligt och inte noll "
                        f"(norm {r['norm']:.2f}, {r['sekunder']:.0f} s ljud)",
                        f"röstavtrycket är fel: {r}")

    # 4. talare.dela_upp() pa tva talare, med pahittade ordtider och (om de finns) riktiga fran den lilla modellen.
    res.steg("4. talare.dela_upp() (egen process)")
    ordtider = os.path.abspath(args.ordtider) if args.ordtider and os.path.isfile(args.ordtider) else None
    if args.ordtider and not ordtider:
        res.fel(f"--ordtider {args.ordtider} finns inte (kontrollen av whisper-cli skriver den)")
    prov = [("två talare, påhittade ordtider", kopior["tva-talare.m4a"], "")]
    if ordtider:
        prov.append(("en talare, riktiga ordtider från den lilla modellen (antal 2 tvingar fram klustringen)",
                     kopior["en-talare.m4a"], ordtider))
    for text, ljudfil, tider in prov:
        kod, ut, r = kor_under(res, hem, "dela_upp", [ljudfil, tider])
        print(ut)
        if r is None:
            res.fel(f"talare.dela_upp() ({text}) kastade eller kraschade (slutkod {kod}, se utskriften ovan)")
        else:
            res.kontrollera(r["repliker"] > 0 and r["antal"] >= 1,
                            f"talare.dela_upp() ({text}): {r['repliker']} repliker, {r['antal']} talare {r['talare']}"
                            + (f", varning: {r['varning']}" if r["varning"] else ""),
                            f"talare.dela_upp() ({text}) gav inga repliker: {r}")
    return res.sammanfatta()


if __name__ == "__main__":
    sys.exit(main())
