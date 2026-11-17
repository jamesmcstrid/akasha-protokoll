"""Talaruppdelningen (fonster + klustring). Rostmodellen ersatts av konstgjorda avtryck."""
import unittest
from unittest import mock

import numpy as np

import hjalp  # noqa: F401  (maste importeras forst)
import talare

SR = talare.SR


def ord_fran(repliker):
    """[(talare, start, slut, 'ord ord')] -> ordlista med ett ord per halvsekund."""
    ut = []
    for _, start, slut, text in repliker:
        orden = text.split()
        steg = (slut - start) / len(orden)
        ut += [(start + i * steg, start + (i + 1) * steg, " " + o) for i, o in enumerate(orden)]
    return ut


def falska_avtryck(repliker, dim=16, brus=0.05, seed=1):
    """Ett avtryck per talare plus brus. Fonstret far rosten hos den som pratar mest i det."""
    rng = np.random.default_rng(seed)
    roster = {}

    def avtryck(_extraktor, bit, _start=[0]):
        raise AssertionError("ersatts nedan")

    def for_fonster(start):
        slut = start + talare.FONSTER_S
        tid = {}
        for vem, a, b, _ in repliker:
            tid[vem] = tid.get(vem, 0) + max(0.0, min(slut, b) - max(start, a))
        vem = max(tid, key=tid.get)
        if vem not in roster:
            roster[vem] = rng.normal(size=dim)
        v = roster[vem] + rng.normal(scale=brus * np.linalg.norm(roster[vem]), size=dim)
        return v / np.linalg.norm(v)

    return for_fonster


class TestDelaUpp(unittest.TestCase):
    def kor(self, repliker, antal):
        ord_lista = ord_fran(repliker)
        langd = max(b for _, _, b, _ in repliker) + 0.5
        samples = np.zeros(int(langd * SR), dtype=np.float32)
        for_fonster = falska_avtryck(repliker)
        starter_kvar = iter(talare.fonster_med_tal(ord_lista, langd))
        with mock.patch.object(talare, "_hamta_extraktor", lambda: None), \
             mock.patch.object(talare, "_avtryck", lambda e, bit: for_fonster(next(starter_kvar))):
            return talare.dela_upp(samples, ord_lista, antal)

    DIALOG = [
        ("A", 0.0, 6.0, "då testar vi min nya app lyssnar du"),
        ("B", 6.5, 9.0, "vad sa du"),
        ("A", 9.5, 16.0, "vi ska se om den hör allt vi säger"),
        ("B", 16.5, 22.0, "nej det visste jag inte alls"),
    ]

    def test_tva_talare_far_ratt_repliker(self):
        rep, hittade, varning = self.kor(self.DIALOG, 2)
        self.assertEqual(hittade, 2)
        self.assertIsNone(varning)
        self.assertEqual([r["speaker"] for r in rep], [1, 2, 1, 2])
        self.assertEqual(rep[1]["text"], "vad sa du")

    def test_gissat_antal_hittar_tva(self):
        rep, hittade, _ = self.kor(self.DIALOG, None)
        self.assertEqual(hittade, 2)
        self.assertEqual([r["speaker"] for r in rep], [1, 2, 1, 2])

    def test_en_rost_delas_inte_pa_tva(self):
        ensam = [("A", 0.0, 6.0, "en två tre fyra fem"), ("A", 6.5, 14.0, "sex sju åtta nio tio elva")]
        rep, hittade, varning = self.kor(ensam, 2)
        self.assertEqual(hittade, 1)
        self.assertIn("bara 1 röst", varning)
        self.assertEqual({r["speaker"] for r in rep}, {1})

    def test_en_talare_eller_for_kort_ljud(self):
        rep, hittade, _ = self.kor(self.DIALOG, 1)
        self.assertEqual((hittade, len(rep)), (1, 1))
        rep, hittade, _ = self.kor([("A", 0.0, 1.0, "hej")], 2)
        self.assertEqual((hittade, rep[0]["text"]), (1, "hej"))


class TestDelar(unittest.TestCase):
    def test_fonster_bara_dar_det_pratas(self):
        ord_lista = [(0.0, 2.0, " a"), (10.0, 12.0, " b")]
        starter = talare.fonster_med_tal(ord_lista, 14.0)
        self.assertTrue(all(s <= 2.1 or s >= 9.0 for s in starter), starter)
        self.assertIn(0.0, starter)
        self.assertIn(10.5, starter)

    def test_sla_ihop_lika_grupper(self):
        a, b = np.eye(2)
        X = np.array([a, a, a * 0.99 + b * 0.01, b, b])
        X /= np.linalg.norm(X, axis=1, keepdims=True)
        etiketter, c = talare.sla_ihop_lika(X, np.array([0, 0, 1, 2, 2]), 0.6)
        self.assertEqual(etiketter.tolist(), [0, 0, 0, 1, 1])
        self.assertEqual(len(c), 2)

    def test_repliker_och_numrering(self):
        ord_lista = [(0, 1, " Hej"), (1, 2, " Bo."), (2, 3, " Hej"), (3, 4, "san."), (4, 5, " Ja.")]
        rep = talare.repliker(ord_lista, [7, 7, 3, 3, 7])
        self.assertEqual([(r["speaker"], r["text"]) for r in rep], [(1, "Hej Bo."), (2, "Hejsan."), (1, "Ja.")])
        self.assertEqual(talare.repliker([(0, 1, "  ")], [0]), [])


class TestTolkaAntal(unittest.TestCase):
    def test_giltiga(self):
        self.assertEqual(talare.tolka_antal("2"), 2)
        self.assertEqual(talare.tolka_antal(" 10 "), 10)
        self.assertIsNone(talare.tolka_antal(" AUTO "))

    def test_ogiltiga(self):
        for v in ("0", "11", "två", "", "-1"):
            with self.assertRaises(ValueError, msg=v):
                talare.tolka_antal(v)


if __name__ == "__main__":
    unittest.main()
