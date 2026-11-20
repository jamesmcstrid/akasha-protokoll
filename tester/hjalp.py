"""Gemensamt for testerna: tillfallig datakatalog och app/ i sokvagen. Importeras forst."""
import atexit
import os
import shutil
import sys
import tempfile

DATA = tempfile.mkdtemp(prefix="akasha-protokoll-test-")
# Ingen test far rora den riktiga hemkatalogen (flytten av mapparna i start.py och plattform.py
# gor os.rename under HOME): hela provkorningen far en tillfallig hemkatalog.
HEM = tempfile.mkdtemp(prefix="akasha-protokoll-test-hem-")
atexit.register(shutil.rmtree, HEM, True)
os.environ["HOME"] = HEM
os.environ["USERPROFILE"] = HEM
os.environ.pop("XDG_DATA_HOME", None)
os.environ["LOCALAPPDATA"] = os.path.join(HEM, "AppData", "Local")  # programkatalogen pa Windows
os.environ["DATAKATALOG"] = DATA
os.environ["MODELLKATALOG"] = os.path.join(DATA, "inga-modeller")
os.environ["MOTOR"] = "faster"
os.environ["MODELL"] = "medium"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))


def tom_datakatalog():
    for namn in os.listdir(DATA):
        sokvag = os.path.join(DATA, namn)
        if os.path.isdir(sokvag):
            shutil.rmtree(sokvag)
        else:
            os.remove(sokvag)
