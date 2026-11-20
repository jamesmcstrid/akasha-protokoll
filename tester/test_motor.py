import os
import sys
import unittest
from unittest import mock

import hjalp  # noqa: F401
import installningar
import modeller
import motor
import plattform
import talare


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


class TestMalMotor(unittest.TestCase):
    def test_mac_med_cli_ger_whispercpp_aven_utan_ggml(self):
        self.assertEqual(motor.mal_motor("auto", "Darwin", True), "whispercpp")

    def test_mac_utan_cli_och_andra_system_ger_faster(self):
        self.assertEqual(motor.mal_motor("auto", "Darwin", False), "faster")
        self.assertEqual(motor.mal_motor("auto", "Linux", True), "faster")
        self.assertEqual(motor.mal_motor("auto", "Windows", False), "faster")

    def test_tvingat_val_galler(self):
        self.assertEqual(motor.mal_motor("faster", "Darwin", True), "faster")
        self.assertEqual(motor.mal_motor("whispercpp", "Linux", False), "whispercpp")


class TestHinder(unittest.TestCase):
    def test_inget_hinder_som_standard(self):
        self.assertIsNone(motor.hinder())

    def test_okand_modell(self):
        with mock.patch.object(motor, "MODELL", "jatte"):
            self.assertIn("MODELL", motor.hinder())

    def test_okand_motor(self):
        with mock.patch.object(motor, "MOTOR", "raket"):
            self.assertIn("MOTOR", motor.hinder())

    def test_whispercpp_utan_cli(self):
        with mock.patch.object(motor, "MOTOR", "whispercpp"), \
             mock.patch.object(plattform, "whisper_cli", lambda: None):
            self.assertEqual(motor.hinder(), "whisper-cli saknas. Kör: brew install whisper-cpp")
            self.assertEqual(motor.problem(), motor.hinder())
        with mock.patch.object(motor, "MOTOR", "whispercpp"), \
             mock.patch.object(plattform, "whisper_cli", lambda: "/usr/bin/whisper-cli"):
            self.assertIsNone(motor.hinder())


class TestPaketerad(unittest.TestCase):
    """Texterna i programmet (paketerat) och i terminalinstallationen."""

    def test_cli_saknas_i_programmet(self):
        with mock.patch.object(plattform, "ar_paketerad", lambda: True), \
             mock.patch.object(motor, "MOTOR", "whispercpp"), \
             mock.patch.object(plattform, "whisper_cli", lambda: None):
            text = "whisper-cli saknas i programmet. Ladda ned Akasha Protokoll på nytt."
            self.assertEqual(motor.hinder(), text)
            with mock.patch.object(motor, "AKTIV", "whispercpp"):
                self.assertEqual(motor.problem(), text)

    def test_cli_saknas_i_terminalinstallationen(self):
        with mock.patch.object(plattform, "ar_paketerad", lambda: False):
            self.assertEqual(motor._cli_saknas(), f"{installningar.WHISPERCPP_BIN} saknas. Kör: brew install whisper-cpp")

    def test_motor_faster_utan_faster_whisper_i_programmet(self):
        text = ("MOTOR=faster går inte i programmet, eftersom faster-whisper inte följer med. "
                "Ta bort raden MOTOR i installningar.env.")
        with mock.patch.object(motor, "MOTOR", "faster"), \
             mock.patch.object(motor.importlib.util, "find_spec", lambda namn: None):
            with mock.patch.object(plattform, "ar_paketerad", lambda: True):
                self.assertEqual(motor.hinder(), text)
            with mock.patch.object(plattform, "ar_paketerad", lambda: False):
                self.assertIsNone(motor.hinder())

    def test_auto_i_programmet_ger_inte_faster_texten(self):
        with mock.patch.object(motor, "MOTOR", "auto"), \
             mock.patch.object(plattform, "ar_paketerad", lambda: True), \
             mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(motor.importlib.util, "find_spec", lambda namn: None):
            self.assertIsNone(motor.hinder())

    def test_sherpa_saknas(self):
        with mock.patch.dict(sys.modules, {"sherpa_onnx": None}), \
             mock.patch.object(modeller, "saknade", lambda *a, **k: []):
            with mock.patch.object(plattform, "ar_paketerad", lambda: True):
                self.assertEqual(talare.problem(), "sherpa-onnx saknas i programmet. Ladda ned Akasha Protokoll på nytt.")
            with mock.patch.object(plattform, "ar_paketerad", lambda: False):
                self.assertEqual(talare.problem(), "sherpa-onnx saknas. Kör: bash mac/installera.sh")


class FalskProcess:
    stderr = []
    returncode = 1

    def __init__(self):
        self.stoppad = False

    def wait(self, timeout=None):
        return 1

    def poll(self):
        return 1


class TestWhispercpp(unittest.TestCase):
    def test_anvander_plattformens_cli(self):
        with mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(motor.subprocess, "Popen", return_value=FalskProcess()) as popen:
            with self.assertRaises(motor.MotorFel) as e:
                motor._whispercpp(np_tyst(), False, "", None)
        self.assertEqual(popen.call_args[0][0][0], "/x/whisper-cli")
        self.assertIn("kod 1", str(e.exception))
        self.assertIsNone(motor._process)

    def test_startar_via_plattformens_starta_barn(self):
        with mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(plattform, "starta_barn", return_value=FalskProcess()) as starta:
            with self.assertRaises(motor.MotorFel):
                motor._whispercpp(np_tyst(), False, "", None)
        self.assertEqual(starta.call_args[0][0][0], "/x/whisper-cli")

    def test_loggar_tiden_till_forsta_framsteg_och_total_tid(self):
        class MedFramsteg(FalskProcess):
            stderr = ["whisper_print_progress_callback: progress =  10%\n",
                      "whisper_print_progress_callback: progress = 100%\n"]
            returncode = 0

            def wait(self, timeout=None):
                return 0

        def popen(cmd, **kw):
            ut = cmd[cmd.index("-of") + 1]
            with open(ut + ".json", "w", encoding="utf-8") as f:
                f.write('{"transcription": []}')
            return MedFramsteg()

        framsteg = []
        with mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(motor.subprocess, "Popen", popen), \
             self.assertLogs("akasha-protokoll", "INFO") as loggat:
            motor._whispercpp(np_tyst(), False, "", framsteg.append)
        self.assertEqual(framsteg, [0.1, 1.0])
        rader = [r for r in loggat.output if "whisper-cli: forsta framsteg efter" in r]
        self.assertEqual(len(rader), 1, loggat.output)
        self.assertRegex(rader[0], r"forsta framsteg efter \d+\.\d s, klar efter \d+\.\d s \(kod 0, ")

    def test_loggraden_visar_streck_om_inget_framsteg_kom(self):
        with mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(motor.subprocess, "Popen", return_value=FalskProcess()), \
             self.assertLogs("akasha-protokoll", "INFO") as loggat:
            with self.assertRaises(motor.MotorFel):
                motor._whispercpp(np_tyst(), False, "", None)
        self.assertTrue(any("forsta framsteg efter - s," in r and "kod 1" in r for r in loggat.output),
                        loggat.output)

    def test_saknad_cli_ger_motorfel(self):
        with mock.patch.object(plattform, "whisper_cli", lambda: None), \
             mock.patch.object(plattform, "ar_paketerad", lambda: True):
            with self.assertRaises(motor.MotorFel) as e:
                motor._whispercpp(np_tyst(), False, "", None)
        self.assertEqual(str(e.exception), "whisper-cli saknas i programmet. Ladda ned Akasha Protokoll på nytt.")


class TestStoppa(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, motor, "_process", None)
        self.addCleanup(setattr, motor, "_avslutas", False)  # stoppa() lamnar flaggan satt

    def test_stoppar_pagaende_process(self):
        p = mock.Mock()
        p.poll.return_value = None
        motor._process = p
        motor.stoppa()
        p.terminate.assert_called_once()
        p.kill.assert_not_called()

    def test_dodar_om_den_inte_stannar(self):
        p = mock.Mock()
        p.poll.return_value = None
        p.wait.side_effect = motor.subprocess.TimeoutExpired("x", 5)
        motor._process = p
        motor.stoppa()
        p.kill.assert_called_once()

    def test_inget_att_stoppa(self):
        motor._process = None
        motor.stoppa()  # ingen process: inget undantag
        p = mock.Mock()
        p.poll.return_value = 0  # redan klar
        motor._process = p
        motor.stoppa()
        p.terminate.assert_not_called()


class DodadProcess(FalskProcess):
    """En whisper-cli som har fatt SIGTERM: wait() ger -15."""
    returncode = -15

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return -15


class TestAvbruten(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, motor, "_process", None)
        self.addCleanup(setattr, motor, "_avslutas", False)

    def test_stoppa_sater_flaggan_och_gor_avbruten_av_dodad_process(self):
        self.assertFalse(motor._avslutas)
        motor.stoppa()
        self.assertTrue(motor._avslutas)
        with mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(motor.subprocess, "Popen", return_value=DodadProcess()):
            with self.assertRaises(motor.Avbruten) as e:
                motor._whispercpp(np_tyst(), False, "", None)
        self.assertIsInstance(e.exception, motor.MotorFel)

    def test_utan_stoppa_ar_det_vanligt_motorfel(self):
        with mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(motor.subprocess, "Popen", return_value=DodadProcess()):
            with self.assertRaises(motor.MotorFel) as e:
                motor._whispercpp(np_tyst(), False, "", None)
        self.assertNotIsInstance(e.exception, motor.Avbruten)
        self.assertIn("kod -15", str(e.exception))

    def test_efter_stoppa_startas_ingen_ny_whisper_cli(self):
        motor.stoppa()
        with mock.patch.object(motor.subprocess, "Popen") as popen, \
             mock.patch.object(motor, "problem", lambda: None):
            with self.assertRaises(motor.Avbruten):
                motor.transkribera(np_tyst())
        popen.assert_not_called()


def np_tyst():
    import numpy as np
    return np.zeros(1600, dtype=np.float32)


class TestProblem(unittest.TestCase):
    def setUp(self):
        hjalp.tom_datakatalog()  # tidigare tester kan ha lagt filer i modellkatalogen

    def test_saknade_modeller_pekar_pa_sidan(self):
        self.assertEqual(motor.problem(), "KB-Whisper saknas. Hämta den på sidan.")
        with mock.patch.object(motor, "AKTIV", "whispercpp"), \
             mock.patch.object(plattform, "whisper_cli", lambda: "/usr/bin/whisper-cli"):
            self.assertEqual(motor.problem(), "KB-Whisper (GGML) saknas. Hämta den på sidan.")

    def test_rostmodell_med_fel_storlek_ger_texten_om_rostmodellen(self):
        sokvag = modeller.ROSTMODELL
        os.makedirs(os.path.dirname(sokvag), exist_ok=True)
        with open(sokvag, "wb") as f:
            f.write(b"fel storlek")
        self.addCleanup(os.remove, sokvag)
        self.assertEqual(talare.problem(), "röstmodellen saknas. Hämta den på sidan.")


class TestUppdatera(unittest.TestCase):
    def setUp(self):
        self.gammal = motor.AKTIV
        self.addCleanup(setattr, motor, "AKTIV", self.gammal)
        self.addCleanup(setattr, motor, "_faster_modell", None)

    def test_byter_motor_och_glommer_den_laddade_modellen(self):
        motor._faster_modell = object()
        with mock.patch.object(motor, "valj_motor", lambda: "whispercpp"):
            self.assertEqual(motor.uppdatera(), "whispercpp")
        self.assertEqual(motor.AKTIV, "whispercpp")
        self.assertIsNone(motor._faster_modell)
        self.assertFalse(motor._las.locked())  # laset ar slappt igen

    def test_upptaget_las_andrar_ingenting(self):
        motor.AKTIV = "faster"
        with mock.patch.object(motor, "valj_motor", lambda: "whispercpp"):
            with motor._las:
                self.assertEqual(motor.uppdatera(), "faster")
                self.assertEqual(motor.AKTIV, "faster")
            self.assertEqual(motor.uppdatera(), "whispercpp")  # nasta anrop forsoker igen


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
