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


# faster = faster-whisper pa CPU (fungerar overallt). whispercpp = whisper.cpp med Metal (GPU).
MOTOR = _env("MOTOR", "faster").lower()
PORT = int(_env("PORT", "8611"))
SPRAK = _env("SPRAK", "sv")

# Inspelningar och transkriberingar. Medvetet INTE i Dokument eller Skrivbord: de synkas ofta
# till iCloud, och motesinspelningar ska stanna pa datorn.
DATAKATALOG = _sokvag(_env("DATAKATALOG", "~/AkashaMeet"))
MODELLKATALOG = _sokvag(_env("MODELLKATALOG", os.path.join(REPO, "modeller")))

CT2_MODELL = os.path.join(MODELLKATALOG, "kb-whisper-medium")
GGML_MODELL = os.path.join(MODELLKATALOG, "kb-whisper-medium-ggml", "ggml-model.bin")
SEGMENTERINGSMODELL = os.path.join(MODELLKATALOG, "talare", "segmentation-3-0.onnx")
ROSTMODELL = os.path.join(MODELLKATALOG, "talare", "nemo_en_titanet_small.onnx")

CPU_TRADAR = int(_env("CPU_TRADAR", "0"))  # 0 = motorn valjer
WHISPERCPP_BIN = _env("WHISPERCPP_BIN", "whisper-cli")
# Bara for "vet inte" (auto). Hogre = farre talare. 0,7-0,9 gav ratt antal i proven.
TALARE_TROSKEL = float(_env("TALARE_TROSKEL", "0.8"))
# Ord som alltid hjalper whisper att stava ratt (namn pa foretaget, facktermer).
ORDLISTA = _env("ORDLISTA", "")
MAX_MB = int(_env("MAX_MB", "1024"))
