import os
import unittest
from unittest import mock

import hjalp  # noqa: F401
import installningar
import modeller
import motor


class TestValjMotor(unittest.TestCase):
    def val(self, onskad="auto", system="Darwin", har_cli=True, har_ggml=True):
        return motor.valj_motor(onskad, system, har_cli, har_ggml)

    def test_auto_blir_whispercpp_nar_det_ar_installerat_pa_mac(self):
        self.assertEqual(self.val(), "whispercpp")

    def test_auto_faller_tillbaka_pa_cpu(self):
        self.assertEqual(self.val(system="Linux"), "faster")
        self.assertEqual(self.val(har_cli=False), "faster")  # whisper-cpp inte installerat
        self.assertEqual(self.val(har_ggml=False), "faster")  # modellen saknas

    def test_tvingat_val_galler(self):
        self.assertEqual(self.val("faster"), "faster")
        self.assertEqual(self.val("whispercpp", system="Linux"), "whispercpp")


class TestModell(unittest.TestCase):
    def test_large_far_egen_fil_och_dtw(self):
        self.assertEqual(modeller.paket("faster", "large")[0].katalog, "kb-whisper-large")
        self.assertEqual(modeller.paket("whispercpp", "large")[0].namn, "ggml-model-q5_0.bin")
        self.assertEqual(modeller.DTW_PER_STORLEK["large"], "large.v3")  # KB-Whisper large bygger pa whisper-large-v3

    def test_medium_ar_standard(self):
        self.assertEqual(installningar.MODELL, "medium")
        self.assertEqual(modeller.DTW, "medium")
        self.assertTrue(modeller.GGML_MODELL.endswith(os.path.join("kb-whisper-medium-ggml", "ggml-model.bin")))

    def test_namn_och_okand_storlek(self):
        with mock.patch.object(motor, "MODELL", "large"):
            self.assertTrue(motor.modellnamn().startswith("KB-Whisper large"))
        with mock.patch.object(motor, "MODELL", "jatte"):
            self.assertIn("MODELL", motor.problem())


class TestRensa(unittest.TestCase):
    def test_interna_markeringar_forsvinner(self):
        raw = [
            {"text": " Hej", "tokens": [{"text": " Hej", "t_dtw": 100}]},
            {"text": " då! <|nospeech|>", "tokens": [{"text": " då", "t_dtw": 130}, {"text": "!", "t_dtw": 140},
                                                       {"text": "<|nospeech|>", "t_dtw": 900}]},
            {"text": "<|nospeech|>", "tokens": [{"text": "<|nospeech|>", "t_dtw": 1100}]},
            {"text": " [BLANK_AUDIO]", "tokens": [{"text": " [BLANK_AUDIO]", "t_dtw": 1200}]},
        ]
        ord_ = motor.dtw_ordtider(motor.rensa(raw))
        self.assertEqual([o[2].strip() for o in ord_], ["Hej", "då!"])
        self.assertEqual(ord_[1][1], 1.3)  # slutar vid "då", inte vid markeringen


class TestDtwOrdtider(unittest.TestCase):
    def seg(self, text, *tokens):
        return {"text": text, "tokens": [{"text": t, "t_dtw": d} for t, d in tokens]}

    def test_tider_fran_dtw_utan_skiljetecken(self):
        raw = [
            self.seg(" kylan?", ("[_BEG_]", 0), (" k", 2226), ("ylan", 2250), ("?", 2364)),
            self.seg(" nej", (" ne", 2370), ("j", 2382)),
            self.seg(" inte", (" inte", 2462)),
        ]
        self.assertEqual([o[:3] for o in motor.dtw_ordtider(raw)], [
            (22.06, 22.5, " kylan?"),  # "?" pa 23,64 raknas inte
            (23.5, 23.82, " nej"),
            (24.42, 24.62, " inte"),  # borjar 0,2 s fore, men inte fore nej:s slut
        ])

    def test_sannolikhet_ar_lagsta_bokstavstoken(self):
        raw = [{"text": " Isar,", "tokens": [{"text": " Is", "t_dtw": 100, "p": 0.31}, {"text": "ar", "t_dtw": 120, "p": 0.82},
                                              {"text": ",", "t_dtw": 125, "p": 0.05}]}]
        self.assertEqual(motor.dtw_ordtider(raw)[0][3], 0.31)  # kommatecknet raknas inte

    def test_utan_dtw_blir_det_none(self):
        self.assertIsNone(motor.dtw_ordtider([self.seg(" du", (" du", -1))]))


class TestOrdTillSegment(unittest.TestCase):
    def test_delar_efter_meningsslut(self):
        ord_lista = [(0.0, 0.4, " Hej"), (0.4, 0.8, " Bo."), (1.0, 1.5, " Ska"), (1.5, 2.0, " vi?")]
        self.assertEqual(motor._ord_till_segment(ord_lista), [
            {"start": 0.0, "end": 0.8, "text": "Hej Bo."},
            {"start": 1.0, "end": 2.0, "text": "Ska vi?"},
        ])


if __name__ == "__main__":
    unittest.main()
