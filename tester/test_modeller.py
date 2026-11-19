import errno
import hashlib
import io
import os
import re
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import hjalp
import requests

import modeller
from falsk_hf import FalskHF, falska_paket, session_med

RIKTIGT = modeller.PAKET  # det riktiga manifestet, innan nagot patchas


class Bas(unittest.TestCase):
    def setUp(self):
        hjalp.tom_datakatalog()
        self.paket, self.innehall = falska_paket()
        for patch in (mock.patch.object(modeller, "PAUSER", (0, 0)),
                      mock.patch.object(modeller, "PAKET", self.paket)):
            patch.start()
            self.addCleanup(patch.stop)
        self.fil = self.paket["talare"][0]

    def adapter(self, **kw):
        self.a = FalskHF(self.innehall, **kw)
        return session_med(self.a)

    def delv(self, fil=None):
        return (fil or self.fil).sokvag() + ".delvis"

    def sha(self, fil=None):
        with open((fil or self.fil).sokvag(), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()


class TestHamtaFil(Bas):
    def test_lyckad_hamtning(self):
        self.assertEqual(modeller.hamta_fil(self.fil, self.adapter()), "hamtad")
        self.assertEqual(self.sha(), self.fil.sha256)
        self.assertFalse(os.path.exists(self.delv()))
        self.assertEqual([re.match(r"https://([^/]+)/", u).group(1) for u, _ in self.a.anrop],
                         ["huggingface.co", "cdn.test.hf.co"])

    def test_redan_hamtat(self):
        modeller.hamta_fil(self.fil, self.adapter())
        session = self.adapter()
        self.assertEqual(modeller.hamta_fil(self.fil, session), "finns")
        self.assertEqual(self.a.anrop, [])

    def test_avbrott_och_fortsattning(self):
        with self.assertRaises(modeller.HamtFel) as cm:
            modeller.hamta_fil(self.fil, self.adapter(bryt_efter=50_000))
        self.assertEqual(cm.exception.kod, "avbrott")
        self.assertEqual(os.path.getsize(self.delv()), 50_000)
        self.assertEqual(modeller.hamta_fil(self.fil, self.adapter()), "hamtad")
        self.assertIn("bytes=50000-", [r for _, r in self.a.anrop])
        self.assertEqual(self.sha(), self.fil.sha256)

    def test_servern_struntar_i_range(self):
        with self.assertRaises(modeller.HamtFel):
            modeller.hamta_fil(self.fil, self.adapter(bryt_efter=50_000))
        modeller.hamta_fil(self.fil, self.adapter(ignorera_range=True))
        self.assertEqual(self.sha(), self.fil.sha256)
        self.assertFalse(os.path.exists(self.delv()))

    def test_fel_kontrollsumma(self):
        sokvag = "/" + self.fil.repo + "/resolve/" + self.fil.revision + "/" + self.fil.namn
        with self.assertRaises(modeller.HamtFel) as cm:
            modeller.hamta_fil(self.fil, self.adapter(trasig_sokvag=sokvag, trasig_ganger=1))
        self.assertEqual(cm.exception.kod, "kontrollsumma")
        self.assertFalse(os.path.exists(self.delv()))
        self.assertFalse(os.path.exists(self.fil.sokvag()))

    def test_full_disk_under_skrivning(self):
        class Full(io.BytesIO):
            def write(self, data):
                raise OSError(errno.ENOSPC, "No space left on device")

        with mock.patch.object(modeller, "_oppna", lambda sokvag, lage: Full()):
            with self.assertRaises(modeller.HamtFel) as cm:
                modeller.hamta_fil(self.fil, self.adapter())
        self.assertEqual(cm.exception.kod, "disk_full")
        self.assertIn("under hämtningen", str(cm.exception))
        self.assertFalse(os.path.exists(self.fil.sokvag()))

    def test_annat_skrivfel(self):
        def neka(sokvag, lage):
            raise OSError(errno.EACCES, "Permission denied")

        with mock.patch.object(modeller, "_oppna", neka):
            with self.assertRaises(modeller.HamtFel) as cm:
                modeller.hamta_fil(self.fil, self.adapter())
        self.assertEqual(cm.exception.kod, "skrivfel")
        self.assertIn("Permission denied", str(cm.exception))

    def test_inget_nat_och_certifikat(self):
        with self.assertRaises(modeller.HamtFel) as cm:
            modeller.hamta_fil(self.fil, self.adapter(natfel_ganger=10))
        self.assertEqual(cm.exception.kod, "inget_nat")
        with self.assertRaises(modeller.HamtFel) as cm:
            modeller.hamta_fil(self.fil, self.adapter(natfel_ganger=10, natfel=requests.exceptions.SSLError))
        self.assertEqual(cm.exception.kod, "certifikat")

    def test_serverfel(self):
        with self.assertRaises(modeller.HamtFel) as cm:
            modeller.hamta_fil(self.fil, self.adapter(status=500))
        self.assertEqual(cm.exception.kod, "server")
        self.assertIn("500", str(cm.exception))

    def test_otillaten_omdirigering(self):
        for cdn in ("http://cdn.test.hf.co", "https://annan.example"):
            with self.subTest(cdn=cdn):
                session = self.adapter(cdn=cdn)
                with self.assertRaises(modeller.HamtFel) as cm:
                    modeller.hamta_fil(self.fil, session)
                self.assertEqual(cm.exception.kod, "adress")
                self.assertEqual([u.split("/")[2] for u, _ in self.a.anrop], ["huggingface.co"])

    def test_for_lang_delvis_tas_bort(self):
        os.makedirs(os.path.dirname(self.delv()))
        with open(self.delv(), "wb") as f:
            f.write(b"x" * (self.fil.storlek + 10))
        self.assertEqual(modeller.hamta_fil(self.fil, self.adapter()), "hamtad")
        self.assertEqual(self.sha(), self.fil.sha256)
        self.assertIsNone(self.a.anrop[0][1])  # inget Range: den gamla halvan kastades

    def test_komplett_delvis_doebs_om_utan_anrop(self):
        os.makedirs(os.path.dirname(self.delv()))
        data = self.innehall["/" + self.fil.repo + "/resolve/" + self.fil.revision + "/" + self.fil.namn]
        with open(self.delv(), "wb") as f:
            f.write(data)
        self.assertEqual(modeller.hamta_fil(self.fil, self.adapter()), "hamtad")
        self.assertEqual(self.a.anrop, [])
        self.assertFalse(os.path.exists(self.delv()))

    def test_avbryt_efter_forsta_biten(self):
        avbryt = threading.Event()
        avbryt.set()
        with self.assertRaises(modeller.HamtFel) as cm:
            modeller.hamta_fil(self.fil, self.adapter(), avbryt=avbryt)
        self.assertEqual(cm.exception.kod, "avbruten")
        self.assertTrue(os.path.exists(self.delv()))


class TestHamta(Bas):
    def test_full_disk_fore_start(self):
        with mock.patch.object(modeller, "ledigt", lambda katalog=None: 10):
            session = self.adapter()
            with self.assertRaises(modeller.HamtFel) as cm:
                modeller.hamta([("talare", self.fil)], session=session)
        self.assertEqual(cm.exception.kod, "disk_full")
        self.assertIn("Det får inte plats", str(cm.exception))
        self.assertEqual(self.a.anrop, [])

    def test_forsoker_sjalv_igen(self):
        modeller.hamta([("talare", self.fil)], session=self.adapter(bryt_efter=50_000, bryt_ganger=1))
        self.assertEqual(self.sha(), self.fil.sha256)
        steg = []
        with self.assertRaises(modeller.HamtFel) as cm:
            modeller.hamta([("talare", self.paket["faster", "medium"][1])],
                           framsteg=lambda *a: steg.append(a), session=self.adapter(bryt_efter=50_000, bryt_ganger=5))
        self.assertEqual(cm.exception.kod, "avbrott")
        self.assertEqual(len([u for u, _ in self.a.anrop if "cdn" in u]), modeller.FORSOK)

    def sokvag_till(self, fil):
        return "/" + fil.repo + "/resolve/" + fil.revision + "/" + fil.namn

    def test_kontrollsummefelet_visar_paketets_namn(self):
        with self.assertRaises(modeller.HamtFel) as cm:
            modeller.hamta([("KB-Whisper medium", self.fil)],
                           session=self.adapter(trasig_sokvag=self.sokvag_till(self.fil), trasig_ganger=1))
        self.assertEqual(cm.exception.kod, "kontrollsumma")
        self.assertTrue(str(cm.exception).startswith("KB-Whisper medium blev inte som den ska"))

    def test_forsok_med_framsteg_raknas_inte(self):
        fil = self.paket["faster", "medium"][1]
        with mock.patch.object(modeller, "FRAMSTEG_MIN", 10_000):
            modeller.hamta([("a", fil)], session=self.adapter(bryt_efter=30_000, bryt_ganger=5))
        self.assertEqual(self.sha(fil), fil.sha256)
        self.assertGreater(len([u for u, _ in self.a.anrop if "cdn" in u]), modeller.FORSOK)

    def test_max_forsok_ar_en_ovre_grans(self):
        fil = self.paket["faster", "medium"][1]
        with mock.patch.object(modeller, "FRAMSTEG_MIN", 10_000), mock.patch.object(modeller, "MAX_FORSOK", 4):
            with self.assertRaises(modeller.HamtFel) as cm:
                modeller.hamta([("a", fil)], session=self.adapter(bryt_efter=30_000, bryt_ganger=100))
        self.assertEqual(cm.exception.kod, "avbrott")
        self.assertEqual(len([u for u, _ in self.a.anrop if "cdn" in u]), 4)

    def test_framsteg_vaxer_och_slutar_pa_totalt(self):
        filer = [("a", self.paket["faster", "medium"][0]), ("b", self.fil)]
        steg = []
        modeller.hamta(filer, framsteg=lambda *a: steg.append(a),
                       session=self.adapter(bryt_efter=50_000, bryt_ganger=1, ignorera_range=True))
        hamtat = [h for _, _, h, _ in steg]
        self.assertEqual(hamtat, sorted(hamtat))
        self.assertEqual(steg[-1][2], steg[-1][3])
        self.assertEqual(steg[-1][3], sum(f.storlek for _, f in filer))


class TestManifest(unittest.TestCase):
    def test_manifestet(self):
        self.assertEqual(set(RIKTIGT), {("faster", "medium"), ("whispercpp", "medium"),
                                        ("faster", "large"), ("whispercpp", "large"), "talare"})
        for filer in RIKTIGT.values():
            for f in filer:
                self.assertTrue(f.url.startswith("https://huggingface.co/"))
                self.assertRegex(f.revision, r"^[0-9a-f]{40}$")
                self.assertRegex(f.sha256, r"^[0-9a-f]{64}$")
                self.assertGreater(f.storlek, 0)
        katalog_namn = {nyckel: ({f.katalog for f in filer}, [f.namn for f in filer])
                        for nyckel, filer in RIKTIGT.items()}
        filer_ct2 = ["model.bin", "config.json", "preprocessor_config.json", "tokenizer.json", "vocabulary.json"]
        self.assertEqual(katalog_namn[("faster", "medium")], ({"kb-whisper-medium"}, filer_ct2))
        self.assertEqual(katalog_namn[("faster", "large")], ({"kb-whisper-large"}, filer_ct2))
        self.assertEqual(katalog_namn[("whispercpp", "medium")], ({"kb-whisper-medium-ggml"}, ["ggml-model.bin"]))
        self.assertEqual(katalog_namn[("whispercpp", "large")], ({"kb-whisper-large-ggml"}, ["ggml-model-q5_0.bin"]))
        self.assertEqual(katalog_namn["talare"], ({"talare"}, ["nemo_en_titanet_small.onnx"]))

    def test_saknade(self):
        paket, innehall = falska_paket()
        with mock.patch.object(modeller, "PAKET", paket):
            hjalp.tom_datakatalog()
            filer = paket["talare"]
            self.assertEqual(modeller.saknade("talare"), list(filer))  # saknad fil
            sokvag = filer[0].sokvag()
            os.makedirs(os.path.dirname(sokvag))
            with open(sokvag, "wb") as f:
                f.write(b"fel storlek")
            self.assertEqual(modeller.saknade("talare"), list(filer))  # fel storlek
            with open(sokvag, "wb") as f:
                f.write(b"x" * filer[0].storlek)
            self.assertEqual(modeller.saknade("talare"), [])  # komplett


class TestSession(unittest.TestCase):
    def test_ssl_cert_file(self):
        fil = os.path.join(hjalp.DATA, "ca.pem")
        with open(fil, "w") as f:
            f.write("x")
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": fil}, clear=False):
            os.environ.pop("REQUESTS_CA_BUNDLE", None)
            os.environ.pop("CURL_CA_BUNDLE", None)
            self.assertEqual(modeller.ny_session().verify, fil)
            os.environ["REQUESTS_CA_BUNDLE"] = "/annan/fil.pem"
            self.assertIs(modeller.ny_session().verify, True)


class TestMain(Bas):
    def kor(self, argv):
        ut, fel = io.StringIO(), io.StringIO()
        with redirect_stdout(ut), redirect_stderr(fel):
            kod = modeller.main(argv)
        return kod, ut.getvalue(), fel.getvalue()

    def test_talare_hamtas_en_gang(self):
        with mock.patch.object(modeller, "ny_session", lambda: self.adapter()):
            kod, ut, _ = self.kor(["talare"])
            self.assertEqual(kod, 0)
            self.assertIn("OK: nemo_en_titanet_small.onnx", ut)
            kod, ut, _ = self.kor(["talare"])
        self.assertEqual(kod, 0)
        self.assertIn("finns: nemo_en_titanet_small.onnx", ut)
        self.assertNotIn("OK:", ut)

    def test_okant_lage_ger_2(self):
        kod, _, fel = self.kor(["okant"])
        self.assertEqual(kod, 2)
        self.assertIn("okänt läge: okant", fel)

    def test_ctrl_c_ger_130_utan_traceback(self):
        with mock.patch.object(modeller, "hamta", side_effect=KeyboardInterrupt):
            kod, _, fel = self.kor(["talare"])
        self.assertEqual(kod, 130)
        self.assertIn("ligger kvar", fel)
        self.assertNotIn("Traceback", fel)

    def test_hamtfel_ger_1(self):
        with mock.patch.object(modeller, "ny_session", lambda: self.adapter(status=500)):
            kod, _, fel = self.kor(["talare"])
        self.assertEqual(kod, 1)
        self.assertTrue(fel.startswith("FEL: Hugging Face svarade"))


class TestStorlekText(unittest.TestCase):
    def test_storlek_text(self):
        self.assertEqual(modeller.storlek_text(1532909758), "1,5 GB")
        self.assertEqual(modeller.storlek_text(40257283), "40 MB")
        self.assertEqual(modeller.storlek_text(1573167041), "1,6 GB")
        self.assertEqual(modeller.storlek_text(999_400_000), "999 MB")
        self.assertEqual(modeller.storlek_text(999_600_000), "1,0 GB")
        self.assertEqual(modeller.storlek_text(0), "0 MB")


if __name__ == "__main__":
    unittest.main()
