"""Alla installningar pa ett stalle. Allt har ett standardvarde; .env behovs bara for att andra.

mac/kor.sh laser .env (om den finns) innan tjansten startar.
"""
import os

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
MODELLKATALOG = _sokvag(_env("MODELLKATALOG", os.path.join(REPO, "modeller")))

# KB-Whisper medium (standard) eller large. Large gor farre fel men tar langre tid.
MODELL = _env("MODELL", "medium").lower()
# storlek: (katalog for faster-whisper, fil for whisper.cpp, DTW-forinstallning i whisper.cpp)
STORLEKAR = {
    "medium": ("kb-whisper-medium", os.path.join("kb-whisper-medium-ggml", "ggml-model.bin"), "medium"),
    # large: KBLab:s kvantiserade GGML (q5_0, 1,1 GB) i stallet for 3,1 GB. KB-Whisper large
    # bygger pa whisper-large-v3, darav DTW-forinstallningen.
    "large": ("kb-whisper-large", os.path.join("kb-whisper-large-ggml", "ggml-model-q5_0.bin"), "large.v3"),
}
_storlek = STORLEKAR.get(MODELL, STORLEKAR["medium"])
CT2_MODELL = os.path.join(MODELLKATALOG, _storlek[0])
GGML_MODELL = os.path.join(MODELLKATALOG, _storlek[1])
DTW = _storlek[2]
ROSTMODELL = os.path.join(MODELLKATALOG, "talare", "nemo_en_titanet_small.onnx")

CPU_TRADAR = int(_env("CPU_TRADAR", "0"))  # 0 = motorn valjer
WHISPERCPP_BIN = _env("WHISPERCPP_BIN", "whisper-cli")
# Tva rostgrupper som liknar varandra mer an sa har raknas som samma person. Uppmatt med TitaNet:
# olika personer 0,09-0,56 (hogst i ett riktigt samtal med laptopmikrofon), samma person 0,80-0,90.
TALARE_TROSKEL = float(_env("TALARE_TROSKEL", "0.6"))
# Ord som alltid hjalper whisper att stava ratt (namn pa foretaget, facktermer).
ORDLISTA = _env("ORDLISTA", "")
MAX_MB = int(_env("MAX_MB", "1024"))
