"""Gemensamt for testerna: tillfallig datakatalog och app/ i sokvagen. Importeras forst."""
import os
import shutil
import sys
import tempfile

DATA = tempfile.mkdtemp(prefix="akasha-protokoll-test-")
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
