"""Laser JSON fran whisper-cli (-oj -ojf, med -ml 1 -sow --dtw) som app/motor.py gor, och kontrollerar den.

    python paketering/las_whisper_json.py ut.json [--minst 5] [--langd 27]

Kors av kontrollera-whisper-cli.sh med byggets venv (motor.py behover numpy och PyAV). Varje kontroll
skriver "OK: ..." eller "FEL: ..." och ett FEL ger slutkod 1. Ingenting i app/ andras, och
installningarna pekas om till en tillfallig katalog sa att inget i anvandarens kataloger beror pa det.
"""
import argparse
import json
import os
import sys
import tempfile

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TMP = tempfile.mkdtemp(prefix="akasha-protokoll-las-json-")
os.environ["DATAKATALOG"] = TMP
os.environ["MODELLKATALOG"] = os.path.join(TMP, "inga-modeller")
os.environ["MOTOR"] = "faster"  # motor.py laser installningarna vid import; motorn kors inte har
os.environ["MODELL"] = "medium"
sys.path.insert(0, os.path.join(ROT, "app"))


def fel(text):
    print(f"FEL: {text}", flush=True)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_fil")
    ap.add_argument("--minst", type=int, default=5, help="minsta antal ord (standard 5)")
    ap.add_argument("--langd", type=float, default=27.0, help="storsta tillatna tid i sekunder (standard 27)")
    args = ap.parse_args()

    try:
        import motor
    except Exception as e:  # saknas numpy eller PyAV i den Python som kor skriptet syns det har
        fel(f"kunde inte importera app/motor.py med {sys.executable}: {type(e).__name__}: {e}")

    try:
        with open(args.json_fil, "rb") as f:
            # Som motor._whispercpp: whisper-cli escapar bara " och \ i texten, inte radbrytningar.
            svar = json.loads(f.read().decode("utf-8", "replace"), strict=False)
    except (OSError, ValueError) as e:
        fel(f"kunde inte lasa {args.json_fil}: {e}")
    print(f"OK: {args.json_fil} gar att lasa som JSON (nycklar: {', '.join(sorted(svar)) if isinstance(svar, dict) else type(svar).__name__})")

    raw = motor.rensa(svar.get("transcription", []) if isinstance(svar, dict) else [])
    text = " ".join("".join(s.get("text", "") for s in raw).split())
    if not raw:
        fel("JSON-filen har inga segment under 'transcription'")
    if not text:
        fel("texten ar tom efter motor.rensa()")
    print(f"OK: motor.rensa() gav {len(raw)} segment och texten har {len(text)} tecken")

    ord_ = motor.dtw_ordtider(raw)
    if ord_ is None:
        fel("motor.dtw_ordtider() gav None: JSON-filen saknar t_dtw per token (--dtw och -ojf fungerade inte)")
    if len(ord_) < args.minst:
        fel(f"motor.dtw_ordtider() gav {len(ord_)} ord, vantade minst {args.minst}")
    utanfor = [o for o in ord_ if not (0 <= o[0] <= o[1] <= args.langd)]
    if utanfor:
        fel(f"{len(utanfor)} av {len(ord_)} ord har tider utanfor 0-{args.langd:g} s (start <= slut krävs), "
            f"till exempel {utanfor[0][:3]}")
    print(f"OK: motor.dtw_ordtider() gav {len(ord_)} ord, alla med tider mellan 0 och {args.langd:g} s "
          f"(sista ordet slutar vid {ord_[-1][1]:.2f} s)")
    print("De första tio orden: " + " | ".join(f"{o[2].strip()} {o[0]:.2f}-{o[1]:.2f}" for o in ord_[:10]))
    print(f"Texten börjar: {text[:120]}")
    print("KONTROLL AV JSON: OK")


if __name__ == "__main__":
    main()
