import unittest

import hjalp  # noqa: F401
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


class TestDtwOrdtider(unittest.TestCase):
    def seg(self, text, *tokens):
        return {"text": text, "tokens": [{"text": t, "t_dtw": d} for t, d in tokens]}

    def test_tider_fran_dtw_utan_skiljetecken(self):
        raw = [
            self.seg(" kylan?", ("[_BEG_]", 0), (" k", 2226), ("ylan", 2250), ("?", 2364)),
            self.seg(" nej", (" ne", 2370), ("j", 2382)),
            self.seg(" inte", (" inte", 2462)),
        ]
        self.assertEqual(motor.dtw_ordtider(raw), [
            (22.06, 22.5, " kylan?"),  # "?" pa 23,64 raknas inte
            (23.5, 23.82, " nej"),
            (24.42, 24.62, " inte"),  # borjar 0,2 s fore, men inte fore nej:s slut
        ])

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
