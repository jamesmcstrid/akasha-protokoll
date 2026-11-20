"""Alla installningar pa ett stalle. Allt har ett standardvarde; en installningsfil behovs bara for att andra.

Installningar kommer fran miljon: fran .env via mac/kor.sh (terminalinstallationen) eller fran
installningar.env i programkatalogen (programmet, se plattform.las_in_installningar).
"""
import os

import plattform

plattform.las_in_installningar()

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env(namn, standard):
    varde = os.environ.get(namn, "").strip()
    return varde or standard


def _sokvag(varde):
    return os.path.abspath(os.path.expanduser(varde))


# auto = whisper.cpp med Metal (GPU) pa Mac med Apple Silicon om whisper-cli och modellen finns,
#        annars faster-whisper pa CPU. Gar att tvinga med faster eller whispercpp.
MOTOR = _env("MOTOR", "auto").lower()
PORT = int(_env("PORT", "8611"))
SPRAK = _env("SPRAK", "sv")

# Inspelningar och transkriberingar. Medvetet INTE i Dokument eller Skrivbord: de synkas ofta
# till iCloud, och motesinspelningar ska stanna pa datorn.
DATAKATALOG = _sokvag(_env("DATAKATALOG", "~/AkashaMeet"))
# Programmet (PyInstaller) har modellerna i sin programkatalog, terminalinstallationen i repot.
_STANDARD_MODELLER = (
    os.path.join(plattform.programkatalog(), "modeller") if plattform.ar_paketerad() else os.path.join(REPO, "modeller")
)
MODELLKATALOG = _sokvag(_env("MODELLKATALOG", _STANDARD_MODELLER))

# KB-Whisper medium (standard) eller large. Large gor farre fel men tar langre tid.
MODELL = _env("MODELL", "medium").lower()

CPU_TRADAR = int(_env("CPU_TRADAR", "0"))  # 0 = motorn valjer
WHISPERCPP_BIN = _env("WHISPERCPP_BIN", "whisper-cli")
# Tva rostgrupper som liknar varandra mer an sa har raknas som samma person. Uppmatt med TitaNet:
# olika personer 0,09-0,56 (hogst i ett riktigt samtal med laptopmikrofon), samma person 0,80-0,90.
TALARE_TROSKEL = float(_env("TALARE_TROSKEL", "0.6"))
# Ord som alltid hjalper whisper att stava ratt (namn pa foretaget, facktermer).
ORDLISTA = _env("ORDLISTA", "")
MAX_MB = int(_env("MAX_MB", "1024"))
