import unittest

import hjalp  # noqa: F401  (maste importeras forst)
import talare

TURER = [(0.0, 2.0, 7), (2.5, 4.0, 3), (4.2, 6.0, 7)]


class TestRepliker(unittest.TestCase):
    def test_ord_far_talare_och_numreras_fran_1(self):
        ord_lista = [
            (0.1, 0.5, " Hej"), (0.6, 1.9, " där."),
            (2.25, 2.45, " Hallå"),  # i pausen, narmast nasta tur
            (2.6, 3.0, " ISO-"), (3.0, 3.5, "revision"),  # ett ord i tva delar
            (4.5, 5.0, " Tack."),
        ]
        r = talare.repliker(ord_lista, TURER)
        self.assertEqual([x["speaker"] for x in r], [1, 2, 1])
        self.assertEqual(r[0]["text"], "Hej där.")
        self.assertEqual(r[1]["text"], "Hallå ISO-revision")
        self.assertEqual(r[2]["text"], "Tack.")
        self.assertEqual((r[1]["start"], r[1]["end"]), (2.25, 3.5))

    def test_oavgjort_i_paus_gar_till_tidigare_tur(self):
        self.assertEqual(talare.repliker([(2.1, 2.4, " x")], TURER)[0]["speaker"], 1)

    def test_utan_turer_blir_allt_en_talare(self):
        r = talare.repliker([(0, 1, " a"), (1, 2, " b")], [])
        self.assertEqual(r, [{"start": 0, "end": 2, "speaker": 1, "text": "a b"}])

    def test_tomma_ord_hoppas_over(self):
        self.assertEqual(talare.repliker([(0, 1, "  "), (1, 2, "")], TURER), [])
        self.assertEqual(talare.repliker([], TURER), [])


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
