"""Alla installningar pa ett stalle. Allt har ett standardvarde; en installningsfil behovs bara for att andra.

Installningar kommer fran miljon: fran .env via mac/kor.sh (terminalinstallationen) eller fran
installningar.env i programkatalogen (programmet, se plattform.las_in_installningar).
"""
import os

import plattform

# Problem med installningarna (text utan innehall ur filen). Startar visar dem nar loggningen ar installd.
PROBLEM = list(plattform.las_in_installningar())
VARDE_FEL = "{namn} har ett ogiltigt värde (ska vara {regel}). Standardvärdet {standard} används."

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env(namn, standard):
    varde = os.environ.get(namn, "").strip()
    return varde or standard


def _tal(namn, standard, typ, minst, hogst, regel):
    """Talvarde som aldrig kastar: tomt, ogiltigt eller utanfor intervallet ger standardvardet och ett problem."""
    varde = _env(namn, "")
    if not varde:
        return standard
    try:
        tal = typ(varde.replace(",", ".") if typ is float else varde)
        if minst <= tal <= hogst:
            return tal
    except ValueError:
        pass
    PROBLEM.append(VARDE_FEL.format(namn=namn, regel=regel, standard=str(standard).replace(".", ",")))
    return standard


def _sokvag(varde):
    return os.path.abspath(os.path.expanduser(varde))


# auto = whisper.cpp med Metal (GPU) pa Mac med Apple Silicon om whisper-cli och modellen finns,
#        annars faster-whisper pa CPU. Gar att tvinga med faster eller whispercpp.
MOTOR = _env("MOTOR", "auto").lower()
PORT = _tal("PORT", 8611, int, 1024, 65535, "ett heltal 1024–65535")
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

CPU_TRADAR = _tal("CPU_TRADAR", 0, int, 0, 256, "ett heltal 0–256")  # 0 = motorn valjer
WHISPERCPP_BIN = _env("WHISPERCPP_BIN", "whisper-cli")
# Tva rostgrupper som liknar varandra mer an sa har raknas som samma person. Uppmatt med TitaNet:
# olika personer 0,09-0,56 (hogst i ett riktigt samtal med laptopmikrofon), samma person 0,80-0,90.
TALARE_TROSKEL = _tal("TALARE_TROSKEL", 0.6, float, 0.0, 1.0, "ett tal mellan 0 och 1")
# Ord som alltid hjalper whisper att stava ratt (namn pa foretaget, facktermer).
ORDLISTA = _env("ORDLISTA", "")
MAX_MB = _tal("MAX_MB", 1024, int, 1, 100000, "ett heltal 1–100000")
