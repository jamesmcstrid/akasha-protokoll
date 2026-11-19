"""Rättningar av talare för hand."""
import unittest

import hjalp  # noqa: F401
import rattning

SEG = [
    {"start": 0.0, "end": 10.0, "speaker": 2, "text": "Det fanns inte så mycket att välja på Nej, precis."},
    {"start": 10.0, "end": 12.0, "speaker": 1, "text": "Ja, men det är bra."},
    {"start": 12.0, "end": 20.0, "speaker": 2, "text": "Nu har ju Rebilt börjat i Jönköping."},
]


class TestBytTalare(unittest.TestCase):
    def test_hel_replik_och_grannar_slas_ihop(self):
        nya = rattning.byt_talare(SEG, 1, 2)
        self.assertEqual(len(nya), 1)
        self.assertEqual(nya[0]["speaker"], 2)
        self.assertEqual((nya[0]["start"], nya[0]["end"]), (0.0, 20.0))
        self.assertIn("välja på Nej, precis. Ja, men det är bra. Nu har ju", nya[0]["text"])

    def test_slutet_av_en_replik_far_nasta_talare(self):
        # "Nej, precis." (ord 8-9) sa talare 1: delas av och slås ihop med nästa replik.
        nya = rattning.byt_talare(SEG, 0, 1, 8)
        self.assertEqual([(s["speaker"], s["text"]) for s in nya], [
            (2, "Det fanns inte så mycket att välja på"),
            (1, "Nej, precis. Ja, men det är bra."),
            (2, "Nu har ju Rebilt börjat i Jönköping."),
        ])
        self.assertLess(nya[0]["end"], 10.0)
        self.assertEqual(nya[0]["end"], nya[1]["start"])  # delningen får en uppskattad tid

    def test_mitten_av_en_replik_blir_tre_delar(self):
        nya = rattning.byt_talare(SEG, 2, 3, 2, 4)
        self.assertEqual([(s["speaker"], s["text"]) for s in nya[2:]], [
            (2, "Nu har"), (3, "ju Rebilt"), (2, "börjat i Jönköping.")])
        self.assertTrue(12.0 < nya[3]["start"] < nya[3]["end"] < 20.0)

    def test_ogiltiga_ord_och_repliker(self):
        for fel in ((5, 1, None, None), (0, 1, 3, 3), (0, 1, -1, 2), (0, 1, 0, 99)):
            with self.assertRaises(ValueError):
                rattning.byt_talare(SEG, *fel)
        self.assertEqual(SEG[0]["speaker"], 2)  # originalet ändras inte


class TestOsakert(unittest.TestCase):
    MARKERAD = [
        {"start": 0.0, "end": 4.0, "speaker": 1, "text": "Det är svårt att matcha det.", "osakra_ord": [4]},
        {"start": 4.0, "end": 6.0, "speaker": 2, "text": "Isar vad bra", "osaker_talare": True, "osakra_ord": [0]},
        {"start": 6.0, "end": 9.0, "speaker": 1, "text": "Så tänker jag.", "osaker_talare": True},
    ]

    def test_talaren_stammer_tar_bort_markeringen(self):
        nya = rattning.byt_talare(self.MARKERAD, 1, 2)
        self.assertNotIn("osaker_talare", nya[1])
        self.assertEqual(nya[1]["osakra_ord"], [0])  # osäkra ord ligger kvar

    def test_osakra_ord_foljer_med_vid_delning_och_ihopslagning(self):
        nya = rattning.byt_talare(self.MARKERAD, 1, 1)  # "Isar vad bra" var talare 1: allt slås ihop
        self.assertEqual(len(nya), 1)
        orden = nya[0]["text"].split()
        self.assertEqual([orden[i] for i in nya[0]["osakra_ord"]], ["matcha", "Isar"])
        self.assertNotIn("osaker_talare", nya[0])
        delad = rattning.byt_talare(self.MARKERAD, 0, 3, 3, 5)  # "att matcha" sa talare 3
        self.assertEqual(delad[1]["text"], "att matcha")
        self.assertEqual(delad[1]["osakra_ord"], [1])
        self.assertNotIn("osakra_ord", delad[0])


class TestSlaIhop(unittest.TestCase):
    def test_alla_repliker_fran_en_talare(self):
        nya = rattning.sla_ihop_talare(SEG, 1, 2)
        self.assertEqual(len(nya), 1)
        self.assertEqual(nya[0]["speaker"], 2)

    def test_nytt_nummer_krockar_inte_med_namn(self):
        self.assertEqual(rattning.nytt_nummer(SEG, {}), 3)
        self.assertEqual(rattning.nytt_nummer(SEG, {"4": "Eva"}), 5)


if __name__ == "__main__":
    unittest.main()
