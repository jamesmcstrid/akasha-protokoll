"""halsokoll/jamfor_motorer.py: ordfelsmattet, facit och att --mote aldrig skriver ord ur motet.
Ingen modell och ingen hamtning. Pianissimo-motorn i sig testas i test_pianissimo.py."""
import contextlib
import io
import json
import os
import re
import sys
import unittest
from unittest import mock

import numpy as np

import hjalp  # noqa: F401  (maste importeras forst)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from halsokoll import jamfor_motorer as jm  # noqa: E402
from pianissimo import ord_fran_tokens  # noqa: E402

SR = jm.SR


class Ordfel(unittest.TestCase):
    def test_normalisering(self):
        self.assertEqual(jm.normalisera("Hej, VÄRLDEN!  t.ex. 1978; a_b"), ["hej", "världen", "t", "ex", "1978", "a", "b"])

    def test_lika_ger_noll(self):
        self.assertEqual(jm.wer("Det här är bra.", "det här är bra"), 0.0)

    def test_ersatt_saknat_och_extra_ord(self):
        self.assertEqual(jm.ordfel("a b c d", "a x c d"), (1, 4))
        self.assertEqual(jm.ordfel("a b c d", "a b d"), (1, 4))
        self.assertEqual(jm.ordfel("a b c d", "a b c d e f"), (2, 4))
        self.assertEqual(jm.wer("a b c d", "x y z"), 1.0)  # tre ersatta och ett saknat

    def test_tomt_facit(self):
        self.assertEqual(jm.ordfel("", "a b"), (2, 0))
        self.assertIsNone(jm.wer("", "a b"))
        self.assertIsNone(jm.wer("...", ""))

    def test_tom_hypotes(self):
        self.assertEqual(jm.wer("a b", ""), 1.0)


class Facit(unittest.TestCase):
    def setUp(self):
        with open(jm.FACIT, encoding="utf-8") as f:
            self.facit = json.load(f)

    def test_tacker_de_tre_testfilerna(self):
        self.assertEqual(sorted(self.facit), sorted(jm.PROVFILER))
        for namn, text in self.facit.items():
            self.assertTrue(os.path.isfile(os.path.join(jm.TESTLJUD, namn)), namn)
            self.assertTrue(jm.normalisera(text), namn)

    def test_nyckelorden_ur_kallor(self):
        t = {k: v.lower() for k, v in self.facit.items()}
        self.assertIn("dinosaurie", t["en-talare.m4a"])
        for ord_ in ("carter", "afghanistan", "struktur", "forskarna"):
            self.assertIn(ord_, t["tva-talare.m4a"])
            self.assertIn(ord_, t["digitalt-mote.webm"])
        for ord_ in ("boulevarderna", "turkiet"):
            self.assertIn(ord_, t["digitalt-mote.webm"])

    def test_antal_ord_stammer_med_klippen(self):
        """tva-talare = klipp 1604 + 1546 (42 + 36 ord), digitalt-mote lagger 1525 (36 ord) till."""
        n = {k: len(v.split()) for k, v in self.facit.items()}
        self.assertEqual(n["en-talare.m4a"], 36)
        self.assertEqual(n["tva-talare.m4a"], 42 + 36)
        self.assertEqual(n["digitalt-mote.webm"], 42 + 36 + 36)


class Mote(unittest.TestCase):
    ID = "20260101-120000"
    SPARAD = "Vi bestämde att budgeten godkänns fredag. Kvartalsrapporten skickas senare."
    PIANISSIMO = "Vi beslutade att budgeten godkänns fredag. Kvartalsrapporten skickas tidigare."

    def setUp(self):
        hjalp.tom_datakatalog()
        meta = {"id": self.ID, "andelse": ".m4a", "status": "klar", "resultat": {
            "motor": "KB-Whisper medium", "langd_s": 20, "talare": 1,
            "segment": [{"start": 0.0, "end": 10.0, "speaker": 1, "text": self.SPARAD}]}}
        with open(os.path.join(hjalp.DATA, self.ID + ".json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        with open(os.path.join(hjalp.DATA, self.ID + ".m4a"), "wb") as f:
            f.write(b"ljud")
        self.fore = sorted(os.listdir(hjalp.DATA))
        ord_lista = ord_fran_tokens(
            [" " + o for o in self.PIANISSIMO.split()], [i * 0.5 for i in range(len(self.PIANISSIMO.split()))], 10.0)
        self.patchar = [
            mock.patch.object(jm.motor, "avkoda", return_value=np.zeros(20 * SR, dtype=np.float32)),
            mock.patch.object(jm, "ladda_pianissimo", return_value=(object(), 0.1)),
            mock.patch.object(jm, "transkribera_pianissimo", return_value=(self.PIANISSIMO, ord_lista)),
        ]
        for p in self.patchar:
            p.start()
            self.addCleanup(p.stop)

    def kor(self, *args):
        ut = io.StringIO()
        with contextlib.redirect_stdout(ut):
            jm.main(["--mote", self.ID, *args])
        return ut.getvalue()

    def test_bara_siffror(self):
        text = self.kor()
        for ord_ in set(re.findall(r"\w{4,}", self.SPARAD + " " + self.PIANISSIMO)):
            self.assertNotIn(ord_.lower(), text.lower(), ord_)
        self.assertRegex(text, r"Ord som skiljer: \d+\.\d%")
        self.assertIn("realtid", text)

    def test_andel_som_skiljer(self):
        # 2 av 9 ord skiljer (beslutade, tidigare)
        self.assertIn("Ord som skiljer: 22.2%", self.kor())

    def test_inget_skrivs_i_datakatalogen(self):
        self.kor()
        self.assertEqual(sorted(os.listdir(hjalp.DATA)), self.fore)

    def test_ut_sparar_texten_utanfor_datakatalogen(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fil = os.path.join(tmp, "text.txt")
            text = self.kor("--ut", fil)
            with open(fil, encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), self.PIANISSIMO)
            self.assertNotIn("Kvartalsrapporten", text)
        self.assertEqual(sorted(os.listdir(hjalp.DATA)), self.fore)

    def test_ut_i_datakatalogen_nekas(self):
        with self.assertRaises(SystemExit):
            self.kor("--ut", os.path.join(hjalp.DATA, "text.txt"))
        self.assertEqual(sorted(os.listdir(hjalp.DATA)), self.fore)

    def test_okand_inspelning(self):
        with mock.patch.object(jm, "ladda_pianissimo", side_effect=AssertionError("ska inte laddas")):
            with self.assertRaises(SystemExit) as e:
                jm.main(["--mote", "20990101-000000"])
        self.assertIn("20990101-000000", str(e.exception))


if __name__ == "__main__":
    unittest.main()


class TestTraffar(unittest.TestCase):
    def test_hela_ord_och_skiftlage(self):
        self.assertEqual(jm.traffar("Carter och carter, men inte Carterson.", "Carter"), 2)
        self.assertEqual(jm.traffar("API endpoints och API", "API endpoints, Ahlsell"), 1)
        self.assertEqual(jm.traffar("text", ""), 0)
