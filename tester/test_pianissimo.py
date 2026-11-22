"""app/pianissimo.py: ordlistan fran Pianissimos tokens, delningen i bitar, manifestet och motorn
(MOTOR=pianissimo) genom motor.transkribera med en falsk onnx_asr (tester/falsk_onnx_asr.py). Ingen modell
och ingen hamtning. Inget kraver att onnx-asr ar installerat utom RiktigaPaketet, som annars hoppas over."""
import importlib.util
import inspect
import os
import sys
import threading
import unittest
from unittest import mock

import numpy as np

import hjalp  # noqa: F401  (maste importeras forst)
import falsk_onnx_asr
import installningar
import modeller
import motor
import pianissimo
import plattform

HAR_ONNX_ASR = importlib.util.find_spec("onnx_asr") is not None  # fore sys.modules-byten
SR = pianissimo.SR


class OrdFranTokens(unittest.TestCase):
    def test_bitar_slas_ihop_till_ord(self):
        ut = pianissimo.ord_fran_tokens([" Hej", " s", "an", " och", " ▁hopp"], [0.0, 0.4, 0.56, 0.8, 1.2], 2.0)
        self.assertEqual([o[2] for o in ut], [" Hej", " san", " och", " hopp"])
        self.assertEqual([o[0] for o in ut], [0.0, 0.4, 0.8, 1.2])

    def test_stremarkeringen_ar_samma_sak_som_mellanslag(self):
        ut = pianissimo.ord_fran_tokens(["▁a", "b", "▁c"], [0.0, 0.1, 0.5], 1.0)
        self.assertEqual([o[2] for o in ut], [" ab", " c"])

    def test_ord_slutar_dar_nasta_borjar(self):
        ut = pianissimo.ord_fran_tokens([" a", " b"], [0.0, 0.5], 3.0)
        self.assertEqual(ut[0][:2], (0.0, 0.5))

    def test_paus_efter_ordet_raknas_inte_som_tal(self):
        ut = pianissimo.ord_fran_tokens([" a", " b"], [0.0, 8.0], 20.0)
        self.assertEqual(ut[0][1], pianissimo.MAX_ORD_S)
        self.assertEqual(ut[1][1], 8.0 + pianissimo.MAX_ORD_S)

    def test_kort_ord_far_minsta_langd(self):
        ut = pianissimo.ord_fran_tokens([" a", " b"], [0.0, 0.02], 0.03)
        self.assertEqual(ut[0][1], pianissimo.MIN_ORD_S)
        self.assertEqual(ut[1][1], 0.02 + pianissimo.MIN_ORD_S)

    def test_sista_ordet_slutar_vid_ljudets_slut(self):
        ut = pianissimo.ord_fran_tokens([" a", " b"], [0.0, 1.0], 1.4)
        self.assertEqual(ut[1][:2], (1.0, 1.4))

    def test_tomma_bitar_ger_inga_ord(self):
        self.assertEqual(pianissimo.ord_fran_tokens([], [], 1.0), [])
        self.assertEqual(pianissimo.ord_fran_tokens([" ", "▁"], [0.0, 0.1], 1.0), [])

    def test_passar_talaruppdelningens_format(self):
        """Samma form som motor.transkribera: (start, slut, text) med inledande mellanslag."""
        import talare
        ord_lista = pianissimo.ord_fran_tokens([" Hej", " du", ".", " Ja"], [0.0, 0.5, 0.9, 1.5], 2.0)
        rep = talare.repliker(ord_lista, [0, 0, 1])
        self.assertEqual([r["text"] for r in rep], ["Hej du.", "Ja"])


class Bitar(unittest.TestCase):
    def ljud(self, sekunder, tysta=()):
        x = np.random.default_rng(0).normal(0, 0.1, int(sekunder * SR)).astype(np.float32)
        for a, b in tysta:
            x[int(a * SR):int(b * SR)] *= 0.01
        return x

    def test_kort_ljud_ar_en_bit(self):
        x = self.ljud(25)
        self.assertEqual(pianissimo.dela_i_bitar(x), [(0, len(x))])

    def test_klipper_i_tystnaden(self):
        x = self.ljud(50, tysta=[(26.0, 26.3)])
        bitar = pianissimo.dela_i_bitar(x)
        self.assertEqual(len(bitar), 2)
        self.assertTrue(26.0 * SR <= bitar[0][1] <= 26.3 * SR)

    def test_bitarna_ar_sammanhangande_och_hogst_30_s(self):
        x = self.ljud(200)
        bitar = pianissimo.dela_i_bitar(x)
        self.assertEqual(bitar[0][0], 0)
        self.assertEqual(bitar[-1][1], len(x))
        for (_, slut), (start, _) in zip(bitar, bitar[1:]):
            self.assertEqual(slut, start)
        self.assertTrue(all(b - a <= pianissimo.BIT_S * SR for a, b in bitar))
        self.assertTrue(all(b - a >= (pianissimo.BIT_S - pianissimo.BIT_SOK_S) * SR for a, b in bitar[:-1]))




class Manifest(unittest.TestCase):
    def test_pinnad_revision_och_kontrollsummor(self):
        filer = modeller.paket("pianissimo")
        self.assertEqual(len(filer), 4)
        for f in filer:
            self.assertEqual(f.repo, "KlangAI/pianissimo-sv-onnx")
            self.assertRegex(f.revision, r"^[0-9a-f]{40}$")
            self.assertRegex(f.sha256, r"^[0-9a-f]{64}$")
            self.assertGreater(f.storlek, 0)
            self.assertTrue(f.url.startswith("https://huggingface.co/"), f.url)
            self.assertIn(f.revision, f.url)
            self.assertTrue(modeller.tillaten(f.url), f.url)
            self.assertTrue(f.sokvag().endswith(os.path.join("pianissimo-sv-onnx", f.namn)))

    def test_filerna_onnx_asr_letar_efter(self):
        namn = {f.namn for f in modeller.paket("pianissimo")}
        self.assertEqual(namn, {"encoder-model.int8.onnx", "decoder_joint-model.int8.onnx", "vocab.txt", "config.json"})

    def test_inte_knutet_till_modellstorleken(self):
        self.assertIs(modeller.paket("pianissimo", "large"), modeller.paket("pianissimo", "medium"))

    def test_texten_pa_sidan(self):
        namn, beskrivning, licens = modeller.INFO["pianissimo"]
        self.assertEqual(namn, "Pianissimo")
        self.assertEqual(beskrivning, "svensk taligenkänning från Klang, byggd på NVIDIA Parakeet")
        self.assertEqual(licens, "CC-BY-4.0")


class FalskMiljo(unittest.TestCase):
    """MOTOR=pianissimo med en falsk onnx_asr och modellfilerna pa plats. Tillstandet aterstalls efter varje test."""

    def setUp(self):
        moduler, self.modell, self.anrop = falsk_onnx_asr.moduler()
        for p in (mock.patch.dict(sys.modules, moduler),
                  mock.patch.object(motor, "MOTOR", "pianissimo"),
                  mock.patch.object(motor, "AKTIV", "pianissimo"),
                  mock.patch.object(modeller, "saknade", lambda *a, **k: [])):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(setattr, motor, "_avslutas", False)  # stoppa() lamnar flaggan satt
        self.addCleanup(setattr, motor, "_process", None)
        for namn, varde in (("_modell", None), ("_prompt_loggad", False)):
            self.addCleanup(setattr, pianissimo, namn, varde)
            setattr(pianissimo, namn, varde)

    def ljud(self, sekunder, tysta=()):
        x = np.random.default_rng(0).normal(0, 0.1, int(sekunder * SR)).astype(np.float32)
        for a, b in tysta:
            x[int(a * SR):int(b * SR)] *= 0.01
        return x


class Motorn(FalskMiljo):
    def test_per_ord_ger_ordtider_och_segment_delade_efter_meningsslut(self):
        text, segs, ord_lista = motor.transkribera(self.ljud(2), per_ord=True)
        self.assertEqual(text, "Hej du. Ja")
        self.assertEqual([o[2] for o in ord_lista], [" Hej", " du.", " Ja"])
        self.assertEqual([o[0] for o in ord_lista], [0.0, 0.5, 1.5])
        self.assertEqual([s["text"] for s in segs], ["Hej du.", "Ja"])
        self.assertEqual(segs, motor._ord_till_segment(ord_lista))

    def test_orden_passar_talaruppdelningen(self):
        import talare
        _, _, ord_lista = motor.transkribera(self.ljud(2), per_ord=True)
        rep = talare.repliker(ord_lista, [0, 0, 1])
        self.assertEqual([r["text"] for r in rep], ["Hej du.", "Ja"])

    def test_utan_per_ord_ett_segment_per_bit(self):
        text, segs, ord_lista = motor.transkribera(self.ljud(40, tysta=[(26.0, 26.3)]))
        self.assertEqual(ord_lista, [])
        self.assertEqual(len(self.modell.langder), 2)
        self.assertEqual([s["text"] for s in segs], ["Hej du. Ja"] * 2)
        self.assertEqual(text, "Hej du. Ja Hej du. Ja")
        self.assertEqual(segs[0]["start"], 0.0)
        self.assertAlmostEqual(segs[1]["start"], 26.15, delta=0.2)  # tiderna galler hela ljudet

    def test_ordtiderna_galler_hela_ljudet_med_flera_bitar(self):
        _, _, ord_lista = motor.transkribera(self.ljud(40, tysta=[(26.0, 26.3)]), per_ord=True)
        self.assertEqual(len(ord_lista), 6)
        self.assertGreater(ord_lista[3][0], 26.0)

    def test_framsteg_efter_varje_bit(self):
        andelar = []
        motor.transkribera(self.ljud(40, tysta=[(26.0, 26.3)]), framsteg=andelar.append)
        self.assertEqual(len(andelar), 2)
        self.assertLess(andelar[0], andelar[1])
        self.assertEqual(andelar[1], 1.0)

    def test_avbruten_mellan_bitarna(self):
        def stoppa(andel):
            motor._avslutas = True  # som motor.stoppa()

        with self.assertRaises(motor.Avbruten):
            motor.transkribera(self.ljud(80), framsteg=stoppa)
        self.assertEqual(len(self.modell.langder), 1)  # ingen andra bit
        self.assertFalse(motor._las.locked())
        self.assertFalse(pianissimo._las.locked())

    def test_avbruten_fore_forsta_biten(self):
        motor.stoppa()
        with self.assertRaises(motor.Avbruten):
            motor.transkribera(self.ljud(2))
        self.assertEqual(self.modell.langder, [])
        self.assertEqual(self.anrop, [])  # modellen laddades inte heller

    def test_bara_processorn_och_int8(self):
        motor.transkribera(self.ljud(2))
        (args, kw), = self.anrop
        self.assertEqual(args[0], "nemo-conformer-tdt")
        self.assertEqual(os.path.basename(args[1]), "pianissimo-sv-onnx")
        self.assertEqual(kw["providers"], ["CPUExecutionProvider"])
        self.assertEqual(kw["quantization"], "int8")
        self.assertEqual(kw["sess_options"].intra_op_num_threads, installningar.CPU_TRADAR)

    def test_ladda_utan_bara_cpu_later_onnxruntime_valja(self):
        pianissimo.ladda(bara_cpu=False)  # bara for halsokoll/jamfor_motorer.py
        self.assertIsNone(self.anrop[0][1]["providers"])

    def test_modellen_laddas_en_gang(self):
        motor.transkribera(self.ljud(2))
        motor.transkribera(self.ljud(2))
        self.assertEqual(len(self.anrop), 1)
        self.assertEqual(len(self.modell.langder), 2)

    def test_prompten_ignoreras_och_loggas_en_gang(self):
        with self.assertLogs("akasha-protokoll", "INFO") as logg:
            motor.transkribera(self.ljud(2), prompt="Fredskvist")
        self.assertEqual(sum("ignoreras" in r for r in logg.output), 1)
        self.assertNotIn("Fredskvist", "".join(logg.output))
        with self.assertNoLogs("akasha-protokoll", "INFO"):
            motor.transkribera(self.ljud(2), prompt="Fredskvist")

    def test_bara_en_tradd_i_taget_i_modellen(self):
        nu = mest = 0
        recognize = self.modell.recognize

        def langsam(samples):
            nonlocal nu, mest
            nu += 1
            mest = max(mest, nu)
            threading.Event().wait(0.02)
            try:
                return recognize(samples)
            finally:
                nu -= 1

        self.modell.recognize = langsam
        x = self.ljud(2)
        trad = [threading.Thread(target=pianissimo.transkribera, args=(x, False, "", None)) for _ in range(4)]
        for t in trad:
            t.start()
        for t in trad:
            t.join()
        self.assertEqual(len(self.modell.langder), 4)
        self.assertEqual(mest, 1)
        self.assertEqual(len(self.anrop), 1)  # och modellen laddades bara en gang


class Val(FalskMiljo):
    def test_valj_och_mal_motor(self):
        self.assertEqual(motor.valj_motor("pianissimo", "Linux", False, False), "pianissimo")
        self.assertEqual(motor.mal_motor("pianissimo", "Darwin", True), "pianissimo")

    def test_auto_ar_oforandrat(self):
        for system, cli, ggml, forvantat in (("Darwin", True, True, "whispercpp"), ("Windows", True, True, "whispercpp"),
                                             ("Linux", True, True, "faster"), ("Darwin", False, False, "faster")):
            self.assertEqual(motor.valj_motor("auto", system, cli, ggml), forvantat)
        self.assertEqual(motor.mal_motor("auto", "Windows", True), "whispercpp")
        self.assertEqual(motor.mal_motor("auto", "Linux", False), "faster")

    def test_auto_bryr_sig_inte_om_onnx_asr(self):
        with mock.patch.object(motor, "MOTOR", "auto"), \
             mock.patch.object(motor.importlib.util, "find_spec", lambda namn: None):
            self.assertIsNone(motor.hinder())

    def test_modellnamn(self):
        self.assertEqual(motor.modellnamn(), "Pianissimo (Klang)")

    def test_redo_nar_allt_finns(self):
        self.assertIsNone(motor.hinder())
        self.assertIsNone(motor.problem())

    def test_onnx_asr_saknas(self):
        with mock.patch.object(motor.importlib.util, "find_spec", lambda namn: None), \
             mock.patch.object(plattform, "ar_paketerad", lambda: False):
            self.assertIn("pip install -r app/krav-pianissimo.txt", motor.hinder())
            self.assertEqual(motor.problem(), motor.hinder())

    def test_onnx_asr_saknas_i_programmet(self):
        with mock.patch.object(motor.importlib.util, "find_spec", lambda namn: None), \
             mock.patch.object(plattform, "ar_paketerad", lambda: True):
            text = motor.hinder()
        self.assertIn("går inte i programmet", text)
        self.assertIn("MOTOR", text)
        self.assertNotIn("pip", text)

    def test_modellen_saknas(self):
        with mock.patch.object(modeller, "saknade", lambda *a, **k: ["x"]):
            self.assertEqual(motor.problem(), "Pianissimo saknas. Hämta den på sidan.")

    def test_okand_motor_namner_pianissimo(self):
        with mock.patch.object(motor, "MOTOR", "raket"):
            self.assertIn("pianissimo", motor.hinder())


class Sidan(FalskMiljo):
    """Modellhamtningen: sidan erbjuder Pianissimo nar den ar malmotorn och saknas."""

    def test_erbjuder_pianissimo_med_namn_beskrivning_kalla_och_licens(self):
        import app as webb
        saknade = lambda nyckel, storlek=None: [] if nyckel == "talare" else list(modeller.PAKET[nyckel])  # noqa: E731
        with mock.patch.object(modeller, "saknade", saknade), \
             mock.patch.object(motor, "mal_motor", lambda *a: "pianissimo"):
            paket, hinder = webb.att_hamta()
            status = webb.modellstatus()
        self.assertIsNone(hinder)
        self.assertEqual([id_ for id_, _ in paket], ["taligenkanning"])
        self.assertEqual(paket[0][1], list(modeller.PAKET["pianissimo"]))
        (p,) = status["saknas"]
        self.assertEqual((p["id"], p["namn"], p["licens"], p["kalla"]),
                         ("taligenkanning", "Pianissimo", "CC-BY-4.0", "huggingface.co/KlangAI/pianissimo-sv-onnx"))
        self.assertEqual(p["beskrivning"], "svensk taligenkänning från Klang, byggd på NVIDIA Parakeet")

    def test_kb_whisper_som_forut(self):
        import app as webb
        with mock.patch.object(motor, "mal_motor", lambda *a: "faster"):
            self.assertEqual(webb.paketnamn("taligenkanning"), "KB-Whisper medium")


@unittest.skipUnless(HAR_ONNX_ASR, "onnx-asr är inte installerat (app/krav-pianissimo.txt)")
class RiktigaPaketet(unittest.TestCase):
    def test_load_model_tar_argumenten_vi_skickar(self):
        import onnx_asr
        import onnxruntime
        param = inspect.signature(onnx_asr.load_model).parameters
        for namn in ("quantization", "sess_options", "providers"):
            self.assertIn(namn, param)
        self.assertTrue(hasattr(onnxruntime.SessionOptions(), "intra_op_num_threads"))


if __name__ == "__main__":
    unittest.main()
