"""Windows-skalet (windows_app.py). Logiken provas pa alla system med en falsk pystray och en falsk fraga();
inget visar en riktig ruta, en riktig ikon eller oppnar en webblasare."""
import hjalp  # noqa: F401  (maste importeras forst)

import ast
import importlib
import os
import sys
import threading
import unittest
from unittest import mock

import plattform
import start
import windows_app
from windows_app import AVSLUTA, JA_NEJ, OK

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")


class FalskFraga:
    """Ersatter fraga(): skriver ner rutorna och svarar med det som ar givet (standard: Ja)."""

    def __init__(self, *svar):
        self.svar = list(svar)
        self.rutor = []

    def __call__(self, rubrik, text, typ):
        self.rutor.append((rubrik, text, typ))
        return self.svar.pop(0) if self.svar else True


class FalskKlocka:
    """Ersatter modulen time i windows_app: sleep() flyttar klockan, ingen riktig vantan."""

    def __init__(self):
        self.nu = 0.0

    def monotonic(self):
        return self.nu

    def sleep(self, s):
        self.nu += s


class FalskTimer:
    """Ersatter threading.Timer: gar aldrig ut av sig sjalv; provet anropar function()."""
    alla = []

    def __init__(self, intervall, function):
        self.intervall, self.function = intervall, function
        self.daemon = False
        self.startad = False
        self.avbruten = False
        FalskTimer.alla.append(self)

    def start(self):
        self.startad = True

    def cancel(self):
        self.avbruten = True


class FalskTjanst:
    def __init__(self, vanta=True, starta=None, stang=None):
        self.hande = []
        self._vanta, self._starta, self._stang = vanta, starta, stang

    def starta(self):
        self.hande.append("starta")
        if self._starta:
            raise self._starta

    def vanta(self, sekunder):
        self.hande.append(("vanta", sekunder))
        return self._vanta

    def stang(self):
        self.hande.append("stang")
        if self._stang:
            raise self._stang


class FalskIkon:
    def __init__(self, name, icon, title, menu):
        self.args = (name, icon, title, menu)
        self.title = title
        self.visible = False
        self.stoppad = 0
        self.notiser = []
        self.fel_vid_stop = None

    def run(self, setup=None):
        if setup:
            setup(self)

    def stop(self):
        self.stoppad += 1
        if self.fel_vid_stop:
            raise self.fel_vid_stop

    def notify(self, message, title=None):
        self.notiser.append((message, title))


class FalskMenuItem:
    def __init__(self, text, action, default=False):
        self.text, self.action, self.default = text, action, default


class FalskMeny:
    SEPARATOR = "---"

    def __init__(self, *rader):
        self.rader = rader


class FalskPystray:
    Icon = FalskIkon
    Menu = FalskMeny
    MenuItem = FalskMenuItem


class FalskBild:
    @staticmethod
    def open(sokvag):
        return ("bild", sokvag)


class Skalprov(unittest.TestCase):
    def setUp(self):
        self.fraga = FalskFraga()
        self.webb = mock.Mock(return_value=True)
        self.visa = mock.Mock()
        for pa in (mock.patch.object(windows_app, "fraga", self.fraga),
                   mock.patch.object(plattform, "oppna_webblasare", self.webb),
                   mock.patch.object(plattform, "visa_fil", self.visa),
                   mock.patch.object(plattform, "en_kopia", return_value=True),
                   mock.patch.object(start, "installningsproblem", return_value=[]),
                   mock.patch.object(start, "forbered", return_value="starta"),
                   mock.patch.object(start, "pagar", return_value=[]),
                   mock.patch.object(start, "aktuell_port", return_value=8611),
                   mock.patch.object(time_sleep(), "sleep")):
            pa.start()
            self.addCleanup(pa.stop)
        self.skal = windows_app.Skal()


def time_sleep():
    return windows_app.time


class TestBorja(Skalprov):
    def test_forsta_kopian_utan_hinder_startar(self):
        self.assertTrue(self.skal.borja())
        self.assertEqual(self.fraga.rutor, [])
        self.webb.assert_not_called()
        plattform.en_kopia.assert_called_once_with("Local\\AkashaProtokoll")

    def test_andra_kopian_oppnar_sidan_nar_den_svarar(self):
        plattform.en_kopia.return_value = False
        with mock.patch.object(start, "lage", side_effect=["ledig", "annat", "akasha"]), \
             mock.patch.object(start, "url", return_value="http://127.0.0.1:8611"):
            self.assertFalse(self.skal.borja())
        self.webb.assert_called_once_with("http://127.0.0.1:8611")
        self.assertEqual(self.fraga.rutor, [])
        start.forbered.assert_not_called()  # den andra kopian startar ingenting

    def test_andra_kopian_som_inte_svarar_ger_rutan_startar_redan(self):
        plattform.en_kopia.return_value = False
        with mock.patch.object(start, "lage", return_value="ledig"), \
             mock.patch.object(windows_app, "VANTA_ANDRA_KOPIAN", 0):
            self.assertFalse(self.skal.borja())
        self.webb.assert_not_called()
        self.assertEqual(self.fraga.rutor, [(start.STARTAR_REDAN_RUBRIK, start.STARTAR_REDAN_TEXT, OK)])

    def test_andra_kopian_vantar_hogst_10_sekunder(self):
        self.assertEqual(windows_app.VANTA_ANDRA_KOPIAN, 10)

    def fast_klocka(self):
        klocka = FalskKlocka()
        return klocka, mock.patch.object(windows_app, "time", klocka)

    def test_andra_kopian_oppnar_sidan_direkt_nar_den_forsta_redan_svarar(self):
        plattform.en_kopia.return_value = False
        klocka, pa = self.fast_klocka()
        with pa, mock.patch.object(start, "lage", return_value="akasha"), \
             mock.patch.object(start, "url", return_value="u"), \
             self.assertLogs("akasha-protokoll", "INFO") as logg:
            self.assertFalse(self.skal.borja())
        self.webb.assert_called_once_with("u")
        self.assertEqual(klocka.nu, 0)  # ingen vantan
        self.assertEqual(self.fraga.rutor, [])
        self.assertIn("INFO:akasha-protokoll:win: den forsta kopian svarade efter 0.0 s", logg.output)

    def test_andra_kopian_oppnar_sidan_nar_svaret_kommer_efter_8_s(self):
        plattform.en_kopia.return_value = False
        klocka, pa = self.fast_klocka()
        with pa, mock.patch.object(start, "lage", side_effect=lambda *a, **k: "akasha" if klocka.nu >= 8 else "ledig"), \
             mock.patch.object(start, "url", return_value="u"), \
             self.assertLogs("akasha-protokoll", "INFO") as logg:
            self.assertFalse(self.skal.borja())
        self.webb.assert_called_once_with("u")
        self.assertEqual(self.fraga.rutor, [])  # ingenting visas under vantan
        self.assertIn("INFO:akasha-protokoll:win: den forsta kopian svarade efter 8.0 s", logg.output)
        start.forbered.assert_not_called()  # den andra kopian startar ingenting

    def test_andra_kopian_som_ger_upp_visar_rutan_och_oppnar_ingen_webblasare(self):
        plattform.en_kopia.return_value = False
        klocka, pa = self.fast_klocka()
        with pa, mock.patch.object(start, "lage", return_value="ledig"), \
             self.assertLogs("akasha-protokoll", "INFO") as logg:
            self.assertFalse(self.skal.borja())
        self.assertGreaterEqual(klocka.nu, 10)
        self.assertLess(klocka.nu, 11)
        self.webb.assert_not_called()  # den forsta kopian oppnar sidan sjalv, annars blev det tva flikar
        self.assertEqual(self.fraga.rutor, [(start.STARTAR_REDAN_RUBRIK, start.STARTAR_REDAN_TEXT, OK)])
        self.assertIn("INFO:akasha-protokoll:win: den forsta kopian svarar inte an (10 s), visar rutan", logg.output)
        self.assertEqual(start.STARTAR_REDAN_RUBRIK, "Akasha Protokoll startar")

    def test_installningsproblem_ja_visar_filen(self):
        with mock.patch.object(start, "installningsproblem", return_value=["Rad 3 förstods inte."]):
            self.assertTrue(self.skal.borja())
        (rubrik, text, typ), = self.fraga.rutor
        self.assertEqual((rubrik, typ), (start.INSTALLNINGSFEL_RUBRIK, JA_NEJ))
        self.assertTrue(text.startswith(start.installningsfel_text(["Rad 3 förstods inte."])))
        self.assertTrue(text.endswith("\n\n" + start.WIN_VISA_FILEN_FRAGA))
        self.visa.assert_called_once_with(plattform.installningsfil())

    def test_installningsproblem_nej_visar_inte_filen_men_startar_anda(self):
        self.fraga.svar = [False]
        with mock.patch.object(start, "installningsproblem", return_value=["x"]):
            self.assertTrue(self.skal.borja())
        self.visa.assert_not_called()

    def test_redan_igang_oppnar_sidan_och_avslutar(self):
        with mock.patch.object(start, "forbered", return_value="redan_igang"), \
             mock.patch.object(start, "url", return_value="http://127.0.0.1:8611"):
            self.assertFalse(self.skal.borja())
        self.webb.assert_called_once_with("http://127.0.0.1:8611")
        self.assertEqual(self.fraga.rutor, [])

    def test_upptagen_ger_rutan_med_port_och_fil(self):
        with mock.patch.object(start, "forbered", return_value="upptagen"):
            self.assertFalse(self.skal.borja())
        self.assertEqual(self.fraga.rutor, [(
            start.UPPTAGEN_RUBRIK, start.UPPTAGEN_TEXT.format(port=8611, fil=plattform.installningsfil()), OK)])
        self.webb.assert_not_called()

    def test_loggar_beslutet(self):
        with self.assertLogs("akasha-protokoll", "INFO") as logg:
            self.skal.borja()
        self.assertIn("INFO:akasha-protokoll:win: beslut starta", logg.output)


class TestStart(Skalprov):
    def setUp(self):
        super().setUp()
        self.ikon = FalskIkon("n", "b", "t", None)
        self.skal.ikon = self.ikon
        self.forsta = mock.patch.object(plattform, "forsta_start_visad", return_value=True)
        self.forsta.start()
        self.addCleanup(self.forsta.stop)
        self.url = mock.patch.object(start, "url", return_value="http://127.0.0.1:8611")
        self.url.start()
        self.addCleanup(self.url.stop)

    def kor(self, tjanst):
        with mock.patch.object(start, "Tjanst", return_value=tjanst):
            self.skal.starta_i_bakgrunden()

    def test_tjansten_svarar(self):
        t = FalskTjanst()
        with self.assertLogs("akasha-protokoll", "INFO") as logg:
            self.kor(t)
        self.assertEqual(t.hande, ["starta", ("vanta", 60)])
        self.assertTrue(any(r.startswith("INFO:akasha-protokoll:win: tjansten startad efter ") for r in logg.output))
        self.assertTrue(self.skal.redo)
        self.webb.assert_called_once_with("http://127.0.0.1:8611")
        self.assertEqual(self.ikon.title, start.WIN_TIPS_IGANG)
        self.assertEqual(self.ikon.notiser, [(start.WIN_IGANG, "Akasha Protokoll")])  # forsta gangen
        self.assertIn("INFO:akasha-protokoll:win: tjansten svarar, oppnar webblasaren", logg.output)
        self.assertFalse(self.skal.klart.is_set())

    def test_ingen_notis_efter_forsta_gangen(self):
        self.forsta.stop()
        with mock.patch.object(plattform, "forsta_start_visad", return_value=False):
            self.kor(FalskTjanst())
        self.assertEqual(self.ikon.notiser, [])
        self.webb.assert_called_once()

    def test_utan_ikon_gar_det_ocksa(self):
        self.skal.ikon = None
        self.kor(FalskTjanst())
        self.assertTrue(self.skal.redo)
        self.webb.assert_called_once()

    def test_fel_i_notisen_stoppar_inte_programmet(self):
        self.ikon.notify = mock.Mock(side_effect=RuntimeError("ingen notis"))
        with self.assertLogs("akasha-protokoll", "ERROR"):
            self.kor(FalskTjanst())
        self.assertTrue(self.skal.redo)

    def test_tjansten_vantas_pa_i_60_s_fran_att_starta_har_returnerat(self):
        self.assertEqual(windows_app.VANTA_TJANSTEN, 60)

    def test_tjansten_svarar_inte_inom_60_s(self):
        self.fraga.svar = [False]
        t = FalskTjanst(vanta=False)
        self.kor(t)
        (rubrik, text, typ), = self.fraga.rutor
        self.assertEqual((rubrik, typ), (start.STARTADE_INTE_RUBRIK, JA_NEJ))
        self.assertEqual(text, start.STARTADE_INTE_TEXT.format(logg=start.loggfil()) + "\n\n"
                         + start.WIN_VISA_LOGGEN_FRAGA)
        self.visa.assert_not_called()
        self.webb.assert_not_called()
        self.assertFalse(self.skal.redo)
        self.assertTrue(self.skal.klart.is_set())  # programmet avslutas
        self.assertIn("stang", t.hande)
        self.assertEqual(self.ikon.stoppad, 1)

    def test_startade_inte_ja_visar_loggen(self):
        self.kor(FalskTjanst(vanta=False))
        self.visa.assert_called_once_with(start.loggfil())
        self.assertTrue(self.skal.klart.is_set())

    def test_undantag_vid_start_ar_startade_inte(self):
        with self.assertLogs("akasha-protokoll", "ERROR"):
            self.kor(FalskTjanst(starta=RuntimeError("fel")))
        self.assertEqual(self.fraga.rutor[0][0], start.STARTADE_INTE_RUBRIK)
        self.assertTrue(self.skal.klart.is_set())

    def test_startfel_visar_texten_och_avslutar(self):
        self.kor(FalskTjanst(starta=start.StartFel("Porten är upptagen")))
        self.assertEqual(self.fraga.rutor, [(start.UPPTAGEN_RUBRIK, "Porten är upptagen", OK)])
        self.assertTrue(self.skal.klart.is_set())
        self.webb.assert_not_called()

    def test_fel_i_rutan_hindrar_inte_avslutet(self):
        with mock.patch.object(windows_app, "fraga", side_effect=OSError("ingen ruta")), \
             self.assertLogs("akasha-protokoll", "ERROR"):
            self.kor(FalskTjanst(vanta=False))
        self.assertTrue(self.skal.klart.is_set())


class TestStartarNotis(Skalprov):
    """Notisen om att starten drojer: en timer som startas nar ikonen visas och avbryts nar startresultatet
    kommer eller avslutet borjar. Ingen riktig vantan: timern ar falsk."""

    def setUp(self):
        super().setUp()
        FalskTimer.alla = []
        pa = mock.patch.object(windows_app.threading, "Timer", FalskTimer)
        pa.start()
        self.addCleanup(pa.stop)
        bg = mock.patch.object(self.skal, "starta_i_bakgrunden")
        bg.start()
        self.addCleanup(bg.stop)
        self.ikon = FalskIkon("n", "b", "t", None)
        self.skal.ikon = self.ikon
        self.tjanst = FalskTjanst()
        self.skal.tjanst = self.tjanst

    def vantade(self):
        return [n for n in self.ikon.notiser if n[0] == start.WIN_STARTAR_NOTIS]

    def test_timern_startas_nar_ikonen_visas(self):
        self.skal._setup(self.ikon)
        (timer,) = FalskTimer.alla
        self.assertEqual(timer.intervall, 5)
        self.assertEqual(windows_app.NOTIS_EFTER, 5)
        self.assertTrue(timer.startad and timer.daemon and not timer.avbruten)
        self.assertEqual(timer.function, self.skal._starten_drojer)

    def test_notis_en_gang_nar_starten_drojer(self):
        self.skal._setup(self.ikon)
        timer = FalskTimer.alla[0]
        with self.assertLogs("akasha-protokoll", "INFO") as logg:
            timer.function()
        self.assertEqual(self.ikon.notiser, [(start.WIN_STARTAR_NOTIS, "Akasha Protokoll")])
        self.assertIn("INFO:akasha-protokoll:win: starten drojer, notis visad", logg.output)
        timer.function()  # aldrig tva ganger
        self.assertEqual(len(self.vantade()), 1)

    def test_ingen_notis_nar_starten_gick_fort(self):
        self.skal._setup(self.ikon)
        timer = FalskTimer.alla[0]
        with mock.patch.object(plattform, "forsta_start_visad", return_value=False), \
             mock.patch.object(start, "url", return_value="u"):
            self.skal.startad(True)
        self.assertTrue(timer.avbruten)
        timer.function()  # om den hann gå ut precis da: gor anda ingenting
        self.assertEqual(self.vantade(), [])

    def test_ingen_notis_om_startresultatet_kom_fore_timern(self):
        with mock.patch.object(plattform, "forsta_start_visad", return_value=False), \
             mock.patch.object(start, "url", return_value="u"):
            self.skal.startad(True)
        self.skal._setup(self.ikon)
        self.assertEqual(FalskTimer.alla, [])  # ingen timer alls

    def test_ingen_notis_efter_att_avslutet_har_borjat(self):
        self.skal._setup(self.ikon)
        timer = FalskTimer.alla[0]
        self.skal.avsluta()
        self.assertTrue(timer.avbruten)
        timer.function()
        self.assertEqual(self.ikon.notiser, [])

    def test_avslutet_utan_timer_stoppar_notisen_aven_om_timern_gick_ut(self):
        self.skal._setup(self.ikon)
        timer = FalskTimer.alla[0]
        self.skal._avslutet = True
        timer.function()
        self.assertEqual(self.ikon.notiser, [])

    def test_startade_inte_stoppar_notisen(self):
        self.skal._setup(self.ikon)
        timer = FalskTimer.alla[0]
        self.fraga.svar = [False]
        self.skal.startad(False)
        self.assertTrue(timer.avbruten)

    def test_fel_i_notisen_loggas_och_stor_inte_starten(self):
        self.ikon.notify = mock.Mock(side_effect=RuntimeError("ingen notis"))
        self.skal._setup(self.ikon)
        with self.assertLogs("akasha-protokoll", "ERROR"):
            FalskTimer.alla[0].function()  # kastar inte
        self.ikon.notify.assert_called_once()
        self.assertFalse(self.skal.klart.is_set())

    def test_ingen_notis_utan_ikon(self):
        self.skal._setup(self.ikon)
        self.skal.ikon = None
        FalskTimer.alla[0].function()
        self.assertEqual(self.ikon.notiser, [])

    def test_ikonen_blir_inte_synlig_ger_ingen_timer(self):
        class Osynlig(FalskIkon):
            @property
            def visible(self):
                return False

            @visible.setter
            def visible(self, v):
                if v:
                    raise OSError("ingen tray")

        with self.assertLogs("akasha-protokoll", "WARNING"):
            self.skal._setup(Osynlig("n", "b", "t", None))
        self.assertEqual(FalskTimer.alla, [])


class TestOppna(Skalprov):
    def test_oppnar_bara_nar_tjansten_ar_redo(self):
        self.skal.oppna()
        self.webb.assert_not_called()
        self.skal.redo = True
        self.skal.oppna()
        self.webb.assert_called_once()

    def test_fel_i_menyatgarden_loggas_och_kastas_inte(self):
        self.skal.redo = True
        self.webb.side_effect = OSError("ingen webblasare")
        with self.assertLogs("akasha-protokoll", "ERROR"):
            self.skal._meny_oppna(None, None)


class TestAvsluta(Skalprov):
    def setUp(self):
        super().setUp()
        self.ikon = FalskIkon("n", "b", "t", None)
        self.tjanst = FalskTjanst()
        self.skal.ikon, self.skal.tjanst, self.skal.redo = self.ikon, self.tjanst, True

    def stangt(self):
        return self.skal.klart.is_set()

    def test_inget_pagar_stanger_utan_fraga(self):
        with self.assertLogs("akasha-protokoll", "INFO") as logg:
            self.skal.avsluta()
        self.assertEqual(self.fraga.rutor, [])
        self.assertEqual(self.tjanst.hande, ["stang"])
        self.assertEqual(self.ikon.stoppad, 1)
        self.assertTrue(self.stangt())
        self.assertIn("INFO:akasha-protokoll:win: avslutar", logg.output)

    def test_nagot_pagar_ja_stanger(self):
        start.pagar.return_value = ["transkribering"]
        self.skal.avsluta()
        (rubrik, text, typ), = self.fraga.rutor
        self.assertEqual((rubrik, typ), (start.AVSLUTA_RUBRIK, AVSLUTA))
        self.assertEqual(text, start.avsluta_text(["transkribering"]) + "\n\n" + start.WIN_AVSLUTA_FRAGA)
        self.assertTrue(self.stangt())
        self.assertEqual(self.tjanst.hande, ["stang"])

    def test_nagot_pagar_nej_fortsatter(self):
        start.pagar.return_value = ["inspelning"]
        self.fraga.svar = [False]
        self.skal.avsluta()
        self.assertFalse(self.stangt())
        self.assertEqual(self.tjanst.hande, [])
        self.assertEqual(self.ikon.stoppad, 0)
        # och nasta forsok far fraga igen (las slapps)
        self.fraga.svar = [True]
        self.skal.avsluta()
        self.assertTrue(self.stangt())

    def test_fore_start_fragas_inget(self):
        self.skal.redo = False
        start.pagar.return_value = ["inspelning"]
        self.skal.avsluta()
        start.pagar.assert_not_called()
        self.assertTrue(self.stangt())

    def test_fel_i_fragan_stoppar_inte_avslutet(self):
        start.pagar.return_value = ["inspelning"]
        with mock.patch.object(windows_app, "fraga", side_effect=OSError("ingen ruta")), \
             self.assertLogs("akasha-protokoll", "ERROR"):
            self.skal.avsluta()
        self.assertTrue(self.stangt())
        self.assertEqual(self.tjanst.hande, ["stang"])

    def test_fel_i_tjansten_och_ikonen_stoppar_inte_avslutet(self):
        self.tjanst._stang = RuntimeError("tjansten")
        self.ikon.fel_vid_stop = RuntimeError("ikonen")
        with self.assertLogs("akasha-protokoll", "ERROR") as logg:
            self.skal.avsluta()
        self.assertTrue(self.stangt())
        self.assertEqual(len(logg.output), 2)

    def test_utan_fraga_aven_nar_nagot_pagar(self):
        start.pagar.return_value = ["transkribering"]
        self.skal.avsluta(utan_fraga=True)
        self.assertEqual(self.fraga.rutor, [])
        self.assertTrue(self.stangt())

    def test_en_fraga_at_gangen(self):
        self.skal._avslutar.acquire()
        self.skal.avsluta()
        self.assertFalse(self.stangt())

    def test_menyvalet_avsluta_kor_i_egen_trad(self):
        klart = threading.Event()
        trad = []

        def avsluta(*a, **k):
            trad.append(threading.current_thread())
            klart.set()

        with mock.patch.object(self.skal, "avsluta", avsluta):
            self.skal._meny_avsluta(None, None)
            self.assertTrue(klart.wait(10))
        self.assertIsNot(trad[0], threading.main_thread())

    def test_menyvalet_avsluta_gar_alltid(self):
        with mock.patch.object(windows_app.threading, "Thread", side_effect=RuntimeError("inga trador")), \
             self.assertLogs("akasha-protokoll", "ERROR"):
            self.skal._meny_avsluta(None, None)
        self.assertTrue(self.stangt())

    def test_stang_gor_varje_del_exakt_en_gang(self):
        self.skal.stang()
        self.skal.stang()
        self.assertEqual(self.tjanst.hande, ["stang"])
        self.assertEqual(self.ikon.stoppad, 1)
        self.assertTrue(self.stangt())

    def test_ett_vanligt_avslut_och_sedan_stang_fran_main_stanger_en_gang(self):
        self.skal.avsluta()
        self.skal.stang()  # som finally i main()
        self.assertEqual(self.tjanst.hande, ["stang"])
        self.assertEqual(self.ikon.stoppad, 1)

    def test_ordningen_tjansten_ikonen_sist_klart(self):
        hande = []
        self.tjanst.stang = lambda: hande.append(("tjanst", self.skal.klart.is_set()))
        self.ikon.stop = lambda: hande.append(("ikon", self.skal.klart.is_set()))
        self.skal.stang()
        self.assertEqual(hande, [("tjanst", False), ("ikon", False)])
        self.assertTrue(self.skal.klart.is_set())

    def test_inget_efter_att_avslutet_har_borjat(self):
        """Avsluta under start (redo ar falskt): sena resultat fran starttraden gor ingenting."""
        self.skal.redo = False
        self.ikon.notify = mock.Mock()
        with mock.patch.object(plattform, "forsta_start_visad", return_value=True), \
             mock.patch.object(start, "url", return_value="u"):
            self.skal.avsluta()
            tjanst = self.tjanst
            with self.assertLogs("akasha-protokoll", "INFO") as logg:
                self.skal.startad(False)
                self.skal.startad(True)
                self.skal.startfel("x")
                self.skal.startade_inte()
        self.assertEqual(self.fraga.rutor, [])
        self.webb.assert_not_called()
        self.visa.assert_not_called()
        self.ikon.notify.assert_not_called()
        self.assertFalse(self.skal.redo)
        self.assertEqual(tjanst.hande, ["stang"])
        self.assertEqual(len([r for r in logg.output if "ignoreras" in r]), 4)

    def test_tjansten_som_startar_nar_avslutet_borjar_stangs(self):
        skal = windows_app.Skal()
        t = FalskTjanst()
        orig = t.starta

        def starta():
            orig()
            skal.stang()  # avslutet borjar medan starta() pagar

        t.starta = starta
        with mock.patch.object(start, "Tjanst", return_value=t):
            skal.starta_i_bakgrunden()
        self.assertEqual(t.hande.count("stang"), 2)  # av skalet och av starttraden (Tjanst.stang tal flera)
        self.assertNotIn(("vanta", 60), t.hande)
        self.assertEqual(self.fraga.rutor, [])


class TestIkon(Skalprov):
    def setUp(self):
        super().setUp()
        self.bg = mock.patch.object(self.skal, "starta_i_bakgrunden")
        self.bg_mock = self.bg.start()
        self.addCleanup(self.bg.stop)
        self.bild = mock.patch.object(plattform, "ikonfil", return_value="/x/ikon.png")
        self.bild.start()
        self.addCleanup(self.bild.stop)

    def vanta_pa_bakgrund(self):
        for t in threading.enumerate():
            if t.name == "start":
                t.join(10)

    def test_ikonen_menyn_och_tjansten(self):
        with self.assertLogs("akasha-protokoll", "INFO") as logg:
            self.skal.visa_ikon(FalskPystray, FalskBild)
        self.vanta_pa_bakgrund()
        namn, bild, tips, meny = self.skal.ikon.args
        self.assertEqual((namn, bild, tips), ("Akasha Protokoll", ("bild", "/x/ikon.png"), start.WIN_TIPS_STARTAR))
        oppna, avdelare, avsluta = meny.rader
        self.assertEqual((oppna.text, oppna.default), (start.WIN_MENY_OPPNA, True))
        self.assertEqual(oppna.action, self.skal._meny_oppna)
        self.assertEqual(avdelare, FalskMeny.SEPARATOR)
        self.assertEqual((avsluta.text, avsluta.default), (start.WIN_MENY_AVSLUTA, False))
        self.assertEqual(avsluta.action, self.skal._meny_avsluta)
        self.assertTrue(self.skal.ikon.visible)
        self.bg_mock.assert_called_once_with()
        self.assertIn("INFO:akasha-protokoll:win: ikonen visas", logg.output)

    def test_ikonen_gar_inte_att_skapa_programmet_fortsatter_utan(self):
        class Trasig(FalskIkon):
            def run(self, setup=None):
                raise OSError("inget aktivitetsfalt")

        class P(FalskPystray):
            Icon = Trasig

        self.skal.klart.set()  # annars vantar visa_ikon pa avslutet
        with self.assertLogs("akasha-protokoll", "WARNING") as logg:
            self.skal.visa_ikon(P, FalskBild)
        self.vanta_pa_bakgrund()
        self.assertIn("WARNING:akasha-protokoll:win: ikonen kunde inte visas: inget aktivitetsfalt", logg.output)
        self.bg_mock.assert_called_once_with()  # tjansten startas anda, en gang
        self.assertIsNone(self.skal.ikon)

    def test_bilden_saknas(self):
        self.bild.stop()
        self.skal.klart.set()
        with mock.patch.object(plattform, "ikonfil", return_value=None), \
             mock.patch.object(FalskBild, "open", side_effect=TypeError("ingen sokvag")), \
             self.assertLogs("akasha-protokoll", "WARNING"):
            self.skal.visa_ikon(FalskPystray, FalskBild)
        self.vanta_pa_bakgrund()
        self.bg_mock.assert_called_once_with()
        self.bild.start()

    def test_ikonen_blir_inte_synlig_loggas_men_tjansten_startas(self):
        class Osynlig(FalskIkon):
            @property
            def visible(self):
                return False

            @visible.setter
            def visible(self, v):
                if v:
                    raise OSError("ingen tray")

        class P(FalskPystray):
            Icon = Osynlig

        with self.assertLogs("akasha-protokoll", "WARNING") as logg:
            self.skal.visa_ikon(P, FalskBild)
        self.vanta_pa_bakgrund()
        self.assertTrue(any("win: ikonen kunde inte visas: ingen tray" in r for r in logg.output))
        self.bg_mock.assert_called_once_with()

    def test_bakgrunden_startas_bara_en_gang(self):
        self.skal._starta_bakgrund_en_gang()
        self.skal._starta_bakgrund_en_gang()
        self.vanta_pa_bakgrund()
        self.bg_mock.assert_called_once_with()


class TestMain(Skalprov):
    def setUp(self):
        super().setUp()
        for pa in (mock.patch.object(start, "stall_in_loggning"),):
            pa.start()
            self.addCleanup(pa.stop)

    def med_falska_moduler(self):
        pil = mock.Mock(Image=FalskBild)
        return mock.patch.dict(sys.modules, {"pystray": FalskPystray, "PIL": pil, "PIL.Image": FalskBild})

    def test_andra_kopian_ger_kod_0_utan_ikon(self):
        plattform.en_kopia.return_value = False
        with mock.patch.object(start, "lage", return_value="akasha"), \
             mock.patch.object(start, "url", return_value="u"), \
             mock.patch.object(windows_app.Skal, "visa_ikon", side_effect=AssertionError("ingen ikon")), \
             self.assertLogs("akasha-protokoll", "INFO") as logg:
            self.assertEqual(windows_app.main(), 0)
        self.assertEqual(logg.output[0], "INFO:akasha-protokoll:win: startar")
        self.assertIn("INFO:akasha-protokoll:win: kopia finns redan", logg.output)

    def test_hela_vagen_med_falsk_pystray(self):
        tjanst = FalskTjanst()
        with self.med_falska_moduler(), \
             mock.patch.object(start, "Tjanst", return_value=tjanst), \
             mock.patch.object(start, "url", return_value="u"), \
             mock.patch.object(plattform, "forsta_start_visad", return_value=False), \
             mock.patch.object(plattform, "ikonfil", return_value="/x"):
            # run() hos den falska ikonen returnerar direkt, som nar ikonen har stoppats
            self.assertEqual(windows_app.main(), 0)
            for t in threading.enumerate():
                if t.name == "start":
                    t.join(10)
        self.assertIn("starta", tjanst.hande)
        self.assertIn("stang", tjanst.hande)  # main() stanger alltid tjansten pa vagen ut

    def test_utan_pystray_startas_tjansten_och_programmet_vantar_pa_avslutet(self):
        def bakgrund(skal):
            skal.klart.set()

        with mock.patch.dict(sys.modules, {"pystray": None}), \
             mock.patch.object(windows_app.Skal, "_starta_bakgrund_en_gang", bakgrund), \
             self.assertLogs("akasha-protokoll", "WARNING") as logg:
            self.assertEqual(windows_app.main(), 0)
        self.assertTrue(any("win: ikonen kunde inte visas" in r for r in logg.output))

    def test_oforutsett_fel_ger_rutan_startade_inte_och_kod_0(self):
        with mock.patch.object(start, "forbered", side_effect=RuntimeError("bom")), \
             self.assertLogs("akasha-protokoll", "ERROR"):
            self.assertEqual(windows_app.main(), 0)
        self.assertEqual(self.fraga.rutor[0][0], start.STARTADE_INTE_RUBRIK)


class TestFraga(unittest.TestCase):
    def kor(self, typ, svar):
        k = mock.Mock()
        k.MessageBoxW.return_value = svar
        with mock.patch.object(windows_app, "_user32", return_value=k):
            resultat = windows_app.fraga("Rubrik", "Text", typ)
        return resultat, k.MessageBoxW.call_args[0]

    def test_ok(self):
        resultat, args = self.kor(OK, 1)
        self.assertTrue(resultat)
        self.assertEqual(args, (None, "Text", "Rubrik", 0x0 | 0x10000 | 0x40000))

    def test_ja_nej(self):
        self.assertTrue(self.kor(JA_NEJ, 6)[0])
        resultat, args = self.kor(JA_NEJ, 7)
        self.assertFalse(resultat)
        self.assertEqual(args[3], 0x4 | 0x10000 | 0x40000)

    def test_avslutsfragan_har_nej_som_forval_och_varningsikon(self):
        resultat, args = self.kor(AVSLUTA, 7)
        self.assertFalse(resultat)
        self.assertEqual(args[3], 0x4 | 0x30 | 0x100 | 0x10000 | 0x40000)  # MB_YESNO|ICONWARNING|DEFBUTTON2|...
        self.assertTrue(self.kor(AVSLUTA, 6)[0])


class TestStatiskt(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(APP, "windows_app.py"), encoding="utf-8") as f:
            self.kalla = f.read()
        self.trad = ast.parse(self.kalla)

    def metoder(self):
        klass = next(n for n in self.trad.body if isinstance(n, ast.ClassDef) and n.name == "Skal")
        return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}

    def test_pa_modulnivan_bara_ctypes_logging_threading_time_plattform_start(self):
        importerade = set()
        for nod in self.trad.body:
            if isinstance(nod, ast.Import):
                importerade.update(a.name.split(".")[0] for a in nod.names)
            elif isinstance(nod, ast.ImportFrom):
                importerade.add((nod.module or "").split(".")[0])
        self.assertEqual(importerade, {"ctypes", "logging", "threading", "time", "plattform", "start"})

    def test_ingen_frozen_meipass_eller_windll_pa_modulnivan(self):
        for ord_ in ("sys.frozen", "_MEIPASS"):
            self.assertNotIn(ord_, self.kalla)
        for nod in self.trad.body:  # inget anrop pa modulnivan utom log = getLogger(...)
            if isinstance(nod, ast.Expr) and not isinstance(nod.value, ast.Constant):
                self.fail("anrop pa modulnivan")
            if isinstance(nod, ast.Assign):
                for under in ast.walk(nod.value):
                    if isinstance(under, ast.Attribute):
                        self.assertNotIn(under.attr, ("windll", "WinDLL"))

    def test_pystray_och_pillow_importeras_bara_i_main(self):
        for nod in ast.walk(self.trad):
            if isinstance(nod, (ast.Import, ast.ImportFrom)):
                namn = [a.name for a in nod.names] + [getattr(nod, "module", None) or ""]
                if any(n.split(".")[0] in ("pystray", "PIL") for n in namn):
                    funktion = next(f for f in self.trad.body if isinstance(f, ast.FunctionDef)
                                    and nod in ast.walk(f))
                    self.assertEqual(funktion.name, "main")

    def test_inga_svenska_texter_i_skalet(self):
        tillatna = {"Local\\AkashaProtokoll", "user32", OK, JA_NEJ, AVSLUTA, "\n\n", "start", "avsluta",
                    "tjansten startade inte", "__main__", "akasha-protokoll",
                    "redan_igang", "upptagen", "akasha", "startad", "startfel", "startade_inte"}  # besluten fran start.forbered()
        docstrings = set()
        for nod in ast.walk(self.trad):
            if isinstance(nod, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                d = ast.get_docstring(nod, clean=False)
                if d:
                    docstrings.add(d)
        for nod in ast.walk(self.trad):
            if isinstance(nod, ast.Constant) and isinstance(nod.value, str):
                v = nod.value
                if v in docstrings or v in tillatna or v.startswith("win: "):
                    continue
                self.fail(f"oväntad sträng i windows_app.py: {v!r}")
        for v in (n.value for n in ast.walk(self.trad) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                  and n.value not in docstrings):
            self.assertTrue(v.isascii(), v)

    def test_det_pystray_anropar_har_try_utanfor_allt(self):
        metoder = self.metoder()
        for namn in ("_meny_oppna", "_meny_avsluta", "_setup", "oppna", "startad", "satt_tips"):
            with self.subTest(namn):
                kropp = metoder[namn].body
                if isinstance(kropp[0], ast.Expr) and isinstance(getattr(kropp[0], "value", None), ast.Constant) \
                        and isinstance(kropp[0].value.value, str):
                    kropp = kropp[1:]
                self.assertIsInstance(kropp[0], ast.Try, f"{namn} ska ha try som forsta sats")
                self.assertTrue(any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
                                    for h in kropp[0].handlers), f"{namn} saknar except Exception")

    def test_loggraderna(self):
        for rad in ("win: startar", "win: kopia finns redan", "win: beslut %s",
                    "win: tjansten svarar, oppnar webblasaren", "win: ikonen visas",
                    "win: ikonen kunde inte visas: %s", "win: avslutar"):
            self.assertIn(f'"{rad}"', self.kalla)

    def test_importen_ror_inte_windll_pa_linux(self):
        importlib.reload(windows_app)  # ingen ctypes.windll pa Linux: importen far inte kasta


@unittest.skipUnless(os.name == "nt", "bara pa Windows: pystray och Pillow ar installerade bara dar")
class TestWindowsRiktigt(unittest.TestCase):
    """Inga rutor, ingen ikon och ingen webblasare: bara import och typer."""

    def test_windows_app_och_biblioteken_importeras(self):
        importlib.reload(windows_app)
        pystray = importlib.import_module("pystray")
        from PIL import Image
        self.assertTrue(hasattr(pystray, "Icon"))
        self.assertTrue(hasattr(Image, "open"))

    def test_ikonfilen_gar_att_oppna(self):
        from PIL import Image
        sokvag = plattform.ikonfil()
        self.assertIsNotNone(sokvag)
        with Image.open(sokvag) as bild:
            self.assertGreater(bild.size[0], 0)

    def test_messageboxw_har_ratt_typer(self):
        u = windows_app._user32()  # skapar bara kernel-objektet; ingen ruta visas
        self.assertEqual(u.MessageBoxW.restype, ctypes_c_int())
        self.assertEqual(len(u.MessageBoxW.argtypes), 4)

    def test_fraga_anropar_messageboxw_med_ratt_flaggor_utan_ruta(self):
        k = mock.Mock()
        k.MessageBoxW.return_value = 6
        with mock.patch.object(windows_app, "_user32", return_value=k):
            self.assertTrue(windows_app.fraga("R", "T", AVSLUTA))
        self.assertEqual(k.MessageBoxW.call_args[0][3], 0x4 | 0x30 | 0x100 | 0x10000 | 0x40000)

    def test_riktig_pystray_meny_anropar_skalets_metoder(self):
        """Den riktiga pystray.Menu/MenuItem (pystray raknar metodens parametrar). Ingen Icon, ingen
        ruta och ingen webblasare: oppna_webblasare ar utbytt och ingenting pagar."""
        import pystray
        skal = windows_app.Skal()
        skal.tjanst = FalskTjanst()
        meny = skal.bygg_meny(pystray)
        oppna, avdelare, avsluta = list(meny.items)
        self.assertEqual((oppna.text, oppna.default), (start.WIN_MENY_OPPNA, True))
        self.assertEqual(avdelare.text, pystray.Menu.SEPARATOR.text)
        self.assertEqual((avsluta.text, avsluta.default), (start.WIN_MENY_AVSLUTA, False))
        webb = mock.Mock(return_value=True)
        with mock.patch.object(plattform, "oppna_webblasare", webb), \
             mock.patch.object(start, "url", return_value="u"), \
             mock.patch.object(start, "pagar", return_value=[]), \
             mock.patch.object(windows_app, "fraga", side_effect=AssertionError("ingen ruta")):
            oppna(None)  # som pystray gor: MenuItem.__call__(icon)
            webb.assert_not_called()  # tjansten ar inte redo an
            skal.redo = True
            oppna(None)
            meny(None)  # forvalet, som ett vanstermusklick pa ikonen
            self.assertEqual(webb.call_count, 2)
            avsluta(None)
            self.assertTrue(skal.klart.wait(20), "Avsluta ledde inte till att klart sattes")
        self.assertEqual(skal.tjanst, None)

    def test_hela_skalet_med_falska_rutor_och_ikon_oppnar_ingen_webblasare(self):
        webb = mock.Mock(return_value=True)
        with mock.patch.object(windows_app, "fraga", FalskFraga()), \
             mock.patch.object(plattform, "oppna_webblasare", webb), \
             mock.patch.object(plattform, "en_kopia", return_value=True), \
             mock.patch.object(start, "forbered", return_value="redan_igang"), \
             mock.patch.object(start, "installningsproblem", return_value=[]), \
             mock.patch.object(start, "stall_in_loggning"):
            self.assertEqual(windows_app.main(), 0)
        webb.assert_called_once()


def ctypes_c_int():
    import ctypes
    return ctypes.c_int


if __name__ == "__main__":
    unittest.main()
