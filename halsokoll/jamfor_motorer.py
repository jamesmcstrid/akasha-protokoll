"""Jämför KB-Whisper (appens motor) med Klang Pianissimo, en svensk Parakeet-modell: hastighet,
ordfel mot facit och om ordtiderna räcker för talaruppdelningen.

    bash halsokoll/jamfor_motorer.sh                          # båda motorerna, de tre testljuden
    bash halsokoll/jamfor_motorer.sh --motor pianissimo --fil en-talare.m4a tva-talare.m4a
    bash halsokoll/jamfor_motorer.sh --mote <id> [--ut text.txt]

Pianissimo (KlangAI/pianissimo-sv-onnx, CC-BY-4.0) hämtas första gången till MODELLKATALOG, med samma
hämtning som appens modeller (modeller.hamta: fortsätter en avbruten fil, bara Hugging Face, sha256).
Modellen körs med onnx-asr (krav i app/krav-pianissimo.txt, inte i appens krav) av app/pianissimo.py, som
också är motorn MOTOR=pianissimo i appen: manifestet, delningen i bitar och ordtiderna finns bara där.
--ord "a, b" ger båda motorerna en ordlista, som ORDLISTA och svårstavade ord i appen. Klangs egen kod i
modellrepot körs inte: ordförstärkningen är app/pianissimo_boost.py, en granskad kopia.

--mote skriver bara siffror: tid, hastighet och andel ord som skiljer från den sparade texten.
Inget skrivs i datakatalogen. Texten från Pianissimo sparas bara om du anger --ut.
"""
import argparse
import difflib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import numpy as np  # noqa: E402

import lagring  # noqa: E402
import modeller  # noqa: E402
import motor  # noqa: E402
import pianissimo  # noqa: E402
import talare  # noqa: E402
from halsokoll import jamfor, prov  # noqa: E402
from installningar import DATAKATALOG  # noqa: E402

SR = pianissimo.SR
TESTLJUD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testljud")
FACIT = os.path.join(TESTLJUD, "facit.json")
PROVFILER = ("en-talare.m4a", "tva-talare.m4a", "digitalt-mote.webm")
MOTORER = ("kbwhisper", "pianissimo")


# --- ren logik (testas utan modell) --------------------------------------------------------

def normalisera(text):
    """Ord för ordfelsmåttet: gemener, skiljetecken som mellanslag (som Klangs modellkort)."""
    return re.sub(r"[\W_]+", " ", text.lower()).split()


def ordfel(facit, hypotes):
    """-> (antal fel, antal ord i facit). Levenshtein på ord: ersatta, saknade och extra ord."""
    f, h = normalisera(facit), normalisera(hypotes)
    rad = list(range(len(h) + 1))
    for i, fo in enumerate(f, 1):
        ny = [i]
        for j, ho in enumerate(h, 1):
            ny.append(min(rad[j] + 1, ny[j - 1] + 1, rad[j - 1] + (fo != ho)))
        rad = ny
    return rad[-1], len(f)


def wer(facit, hypotes):
    """Ordfelsandel, eller None om facit saknar ord (då går det inte att dela)."""
    fel, n = ordfel(facit, hypotes)
    return fel / n if n else None


# --- Pianissimo ----------------------------------------------------------------------------

def _framsteg():
    senast = [-1]

    def skriv(namn, fas, hamtat, totalt):
        if fas == "hamtar" and totalt and hamtat * 10 // totalt > senast[0]:
            senast[0] = hamtat * 10 // totalt
            print(f"  hämtar Pianissimo {senast[0] * 10} %", flush=True)
    return skriv


def ladda_pianissimo(bara_cpu=False):
    """Hämtar filerna vid behov och laddar modellen. -> (modell, laddningstid i s).

    bara_cpu: se pianissimo.ladda. Här är standarden onnxruntimes eget val, så att --cpu kan jämföras med det."""
    modeller.hamta([(f.namn, f) for f in modeller.paket("pianissimo")], framsteg=_framsteg())
    return pianissimo.ladda(bara_cpu)


def transkribera_pianissimo(modell, samples, prompt=""):
    """-> (text, ordlista). Ordlistan har samma form som motor.transkribera ger med per_ord."""
    with pianissimo.med_ordlista(modell, prompt):
        ord_lista = [o for bit in pianissimo.bitar_med_ord(modell, samples) for o in bit.ord]
    return pianissimo.ord_till_text(ord_lista), ord_lista


BARA_CPU = False  # --cpu


def laddad_pianissimo():
    print("Laddar Pianissimo (int8%s) ..." % (", bara processorn" if BARA_CPU else ""), flush=True)
    modell, sek = ladda_pianissimo(BARA_CPU)
    print(f"Pianissimo: modellen laddades på {sek:.1f} s")
    return modell


# --- mätningarna ---------------------------------------------------------------------------

def tid_och_ord(motornamn, modell, samples, prompt=""):
    """Kör en motor. -> (text, ordlista, sekunder)."""
    t0 = time.perf_counter()
    if motornamn == "pianissimo":
        text, ord_lista = transkribera_pianissimo(modell, samples, prompt)
    else:
        text, _, ord_lista = motor.transkribera(samples, per_ord=True, prompt=prompt)
    return text, ord_lista, time.perf_counter() - t0


def mata_filer(motorer, modeller_, filer, facit, prompt=""):
    """Skriver en rad per motor och fil. -> {(motor, fil): ordlista}, för talarkontrollen."""
    print(f"\n{'Motor':<22}{'Fil':<20}{'Ljud':>7}{'Tid':>8}{'x realtid':>11}{'Ord':>6}{'Ordfel':>9}")
    ordlistor = {}
    for namn in motorer:
        for fil in filer:
            samples = motor.avkoda(os.path.join(TESTLJUD, fil))
            text, ord_lista, sek = tid_och_ord(namn, modeller_.get(namn), samples, prompt)
            ordlistor[(namn, fil)] = ord_lista
            langd = len(samples) / SR
            fel = wer(facit[fil], text)
            print(f"{namn:<22}{fil:<20}{langd:6.1f}s{sek:7.1f}s{langd / sek:11.1f}{len(text.split()):6}"
                  f"{'-' if fel is None else f'{fel:.1%}':>9}", flush=True)
    return ordlistor


def kolla_talare(motorer, ordlistor):
    """Talaruppdelning av tva-talare.m4a med varje motors ordtider, samma facit som halsokoll/prov.py."""
    print("\nTalaruppdelning, tva-talare.m4a (facit: 2 talare, mannen och kvinnan skilda):")
    fel = talare.problem()
    if fel:
        print(f"  hoppas över: {fel}")
        return
    samples = motor.avkoda(os.path.join(TESTLJUD, "tva-talare.m4a"))
    for namn in motorer:
        rep, antal, _ = talare.dela_upp(samples, ordlistor[(namn, "tva-talare.m4a")], 2, ord_p=motor.ord_grans())
        ok, man, kvinna = prov.tva_stammer(rep, antal)
        print(f"  {namn}: {'OK' if ok else 'FEL'}, {antal} talare, mannen={sorted(man)}, kvinnan={sorted(kvinna)}")
        for r in rep:
            print(f"    [{r['start']:5.1f}] talare {r['speaker']}: {r['text'][:60]}")


def mata_mote(id_, ut):
    """Pianissimo mot den sparade texten. Skriver bara siffror, aldrig ord ur mötet."""
    meta = jamfor.las(id_)
    sokvag = lagring.ljudfil(meta)
    if not os.path.isfile(sokvag):
        sys.exit(f"Ljudfilen för {id_} finns inte kvar.")
    data = os.path.abspath(DATAKATALOG)
    if ut and os.path.commonpath([os.path.abspath(ut), data]) == data:
        sys.exit("--ut får inte peka i datakatalogen.")
    modell = laddad_pianissimo()
    samples = motor.avkoda(sokvag)
    text, ord_lista, sek = tid_och_ord("pianissimo", modell, samples)
    langd = len(samples) / SR
    ny = {"resultat": {"segment": [{**s, "speaker": 1} for s in motor._ord_till_segment(ord_lista)]}}
    a, b = jamfor.ord_med_tider(meta), jamfor.ord_med_tider(ny)
    opkoder = difflib.SequenceMatcher(None, [w[0] for w in a], [w[0] for w in b], autojunk=False).get_opcodes()
    print(f"\nMöte {id_}: {langd:.0f} s ljud")
    print(f"  Pianissimo: {sek:.0f} s, {langd / sek:.1f} x realtid, {len(b)} ord")
    print(f"  Sparad text ({meta['resultat'].get('motor')}): {len(a)} ord")
    print(f"  Ord som skiljer: {jamfor.skillnad(opkoder) / max(1, len(a)):.1%} (den sparade texten som facit)")
    if ut:
        with open(ut, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"  Pianissimos text sparad i {ut} (den innehåller mötets ord)")


def main(argv=None):
    p = argparse.ArgumentParser(description="Jämför KB-Whisper och Klang Pianissimo.")
    p.add_argument("--motor", nargs="+", choices=MOTORER, default=list(MOTORER))
    p.add_argument("--fil", nargs="+", choices=PROVFILER, default=list(PROVFILER), help="testljud att köra")
    p.add_argument("--mote", metavar="ID", help="en inspelning i datakatalogen: bara Pianissimo, bara siffror")
    p.add_argument("--ut", metavar="FIL", help="med --mote: spara Pianissimos text här")
    p.add_argument("--ord", metavar="ORD", default="", help='ordlista, kommaseparerad: "Carter, Afghanistan"')
    p.add_argument("--cpu", action="store_true", help="Pianissimo bara på processorn (på Mac: utan CoreML)")
    args = p.parse_args(argv)
    if args.ord and args.mote:
        p.error("--ord hör inte ihop med --mote")
    if args.ut and not args.mote:
        p.error("--ut hör ihop med --mote")

    global BARA_CPU
    BARA_CPU = args.cpu
    if args.mote:
        mata_mote(args.mote, args.ut)
        return 0
    modeller_ = {"pianissimo": laddad_pianissimo()} if "pianissimo" in args.motor else {}

    motorer = list(args.motor)
    if "kbwhisper" in motorer:
        fel = motor.problem()
        if fel:
            print(f"KB-Whisper hoppas över: {fel}")
            motorer.remove("kbwhisper")
        else:
            # faster-whisper laddar modellen vid första anropet: det ska inte räknas i första filens tid
            t0 = time.perf_counter()
            motor.transkribera(np.zeros(SR, dtype=np.float32), per_ord=True)
            print(f"KB-Whisper: {motor.modellnamn()}, första anropet (laddar modellen) tog {time.perf_counter() - t0:.1f} s")
    with open(FACIT, encoding="utf-8") as f:
        facit = json.load(f)
    ordlistor = mata_filer(motorer, modeller_, args.fil, facit, args.ord)
    if "tva-talare.m4a" in args.fil:
        kolla_talare(motorer, ordlistor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
