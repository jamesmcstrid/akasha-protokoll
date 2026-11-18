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


class TestDigitaltMote(unittest.TestCase):
    """Mikrofonen i vanster kanal, motesfliken i hoger."""

    def kor(self, mik, motet, antal):
        alla = sorted(mik + motet, key=lambda r: r[1])
        ord_lista = ord_fran(alla)
        langd = max(b for _, _, b, _ in alla) + 0.5
        vanster = np.zeros(int(langd * SR), dtype=np.float32)
        hoger = np.zeros(int(langd * SR), dtype=np.float32)
        rng = np.random.default_rng(0)
        for kanal, repliker_ in ((vanster, mik), (hoger, motet)):
            for _, a, b, _ in repliker_:
                kanal[int(a * SR):int(b * SR)] = rng.normal(scale=0.2, size=int(b * SR) - int(a * SR))
        for_fonster = falska_avtryck(motet)
        andras = [o for o, du in zip(ord_lista, talare.kanal_per_ord(vanster, hoger, ord_lista)) if not du]
        starter = iter(talare.fonster_med_tal(andras, langd))
        with mock.patch.object(talare, "_hamta_extraktor", lambda: None), \
             mock.patch.object(talare, "_avtryck", lambda e, bit: for_fonster(next(starter))):
            return talare.dela_upp_kanaler(vanster, hoger, ord_lista, antal)

    MIK = [("du", 0.0, 4.0, "hej allihop nu kör vi"), ("du", 14.5, 18.0, "bra då säger vi så")]
    MOTET = [("A", 4.5, 9.0, "hej hej hör ni mig"), ("B", 9.5, 14.0, "ja vi hör dig bra")]

    def test_du_ar_alltid_talare_1_och_de_andra_delas_upp(self):
        rep, hittade, varning = self.kor(self.MIK, self.MOTET, 3)
        self.assertEqual([r["speaker"] for r in rep], [1, 2, 3, 1])
        self.assertEqual(rep[0]["text"], "hej allihop nu kör vi")
        self.assertEqual((hittade, varning), (3, None))

    def test_tva_talare_betyder_du_och_en_till(self):
        rep, hittade, _ = self.kor(self.MIK, self.MOTET, 2)
        self.assertEqual([r["speaker"] for r in rep], [1, 2, 1])
        self.assertEqual(hittade, 2)

    def test_du_ar_talare_1_aven_om_nagon_annan_borjar(self):
        motet = [("A", 0.0, 4.0, "välkomna till mötet idag")]
        mik = [("du", 4.5, 8.0, "tack så mycket")]
        rep, _, _ = self.kor(mik, motet, 2)
        self.assertEqual([(r["speaker"], r["text"]) for r in rep], [(2, "välkomna till mötet idag"), (1, "tack så mycket")])

    def test_osakert_ord_far_narmaste_sakra_ords_talare(self):
        v = np.zeros(SR * 6, dtype=np.float32)
        h = np.zeros(SR * 6, dtype=np.float32)
        v[0:SR * 2] = 0.3          # du pratar 0-2 s
        h[SR * 2:SR * 6] = 0.3     # motet pratar 2-6 s ...
        h[int(SR * 3.9):int(SR * 4.3)] = 0.003  # ... utom ett svagt ord vid 4 s
        v[int(SR * 3.9):int(SR * 4.3)] = 0.004  # dar mikrofonen bara har brus
        h[int(SR * 0.9):int(SR * 1.3)] = 0.5    # och ett tydligt "ja" fran motet mitt i din replik
        v[int(SR * 0.9):int(SR * 1.3)] = 0.01
        ord_lista = [(0.2, 0.8, " hej"), (0.95, 1.25, " ja"), (1.4, 1.9, " du"),
                     (2.5, 3.5, " vi"), (3.95, 4.25, " att"), (4.5, 5.5, " ses")]
        self.assertEqual(talare.kanal_per_ord(v, h, ord_lista), [True, False, True, False, False, False])

    def test_monofil_raknas_inte_som_tva_kanaler(self):
        x = np.random.default_rng(1).normal(size=16000).astype(np.float32)
        self.assertFalse(talare.har_tva_kanaler(x, x.copy()))
        self.assertTrue(talare.har_tva_kanaler(x, np.zeros_like(x)))


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

    @staticmethod
    def grupper_med_likhet(likhet, fonster):
        """Fonster for grupper vars medelavtryck har exakt de angivna likheterna."""
        roster = np.linalg.cholesky(np.array(likhet))  # rad i = grupp i, roster @ roster.T = likhet
        return np.repeat(roster, fonster, axis=0), np.repeat(np.arange(len(likhet)), fonster)

    def test_sammanslagen_grupp_drar_inte_med_sig_en_tredje(self):
        # Som i ett riktigt mote: A och D ar samma person, C en annan som liknar bada lite
        # mindre an troskeln. A+D:s medelavtryck liknar C mer (0,604) an A och D gor var for sig.
        # Alla tre har mycket tal (minuter i motet, har 100 s).
        X, etiketter = self.grupper_med_likhet([[1.0, 0.91, 0.595],
                                                [0.91, 1.0, 0.585],
                                                [0.595, 0.585, 1.0]], [200, 200, 200])
        nya, c = talare.sla_ihop_lika(X, etiketter, 0.6)
        self.assertEqual(len(c), 2)
        self.assertEqual(nya[0], nya[200])
        self.assertNotEqual(nya[0], nya[400])

    def test_kort_avvikelse_hos_samma_person_slas_ihop(self):
        # Som i inspelningen med en person: tva stora grupper (0,78) och en grupp om 3 s som
        # liknar dem lite mindre an troskeln var for sig, men den samlade rosten mer (0,625).
        X, etiketter = self.grupper_med_likhet([[1.0, 0.78, 0.62],
                                                [0.78, 1.0, 0.56],
                                                [0.62, 0.56, 1.0]], [100, 100, 6])
        nya, c = talare.sla_ihop_lika(X, etiketter, 0.6)
        self.assertEqual(len(c), 1)

    def test_en_person_i_tre_delar_slas_ihop(self):
        # Som i testljudet: en person som k-means delat i tre grupper (0,91, 0,63 och 0,61).
        X, etiketter = self.grupper_med_likhet([[1.0, 0.91, 0.63],
                                                [0.91, 1.0, 0.61],
                                                [0.63, 0.61, 1.0]], [200, 200, 200])
        nya, c = talare.sla_ihop_lika(X, etiketter, 0.6)
        self.assertEqual(len(c), 1)
        self.assertEqual(set(nya.tolist()), {0})

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
