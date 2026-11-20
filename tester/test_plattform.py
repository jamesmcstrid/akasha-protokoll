"""Plattformen: kataloger, installningsfil, medfoljande whisper-cli och den gamla launchd-tjansten."""
import hjalp  # noqa: F401  (maste importeras forst)

import contextlib
import ctypes
import importlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

import installningar
import plattform


def system(namn):
    return mock.patch.object(plattform, "system", return_value=namn)


class Tillfallig(unittest.TestCase):
    def setUp(self):
        self.katalog = tempfile.mkdtemp(prefix="akasha-plattform-")
        self.addCleanup(shutil.rmtree, self.katalog, True)


class TillfalligtHem(Tillfallig):
    """En tillfallig hemkatalog: HOME pekar dit, och DATAKATALOG och XDG_DATA_HOME ar inte satta.
    Inget prov i den har filen ror de riktiga hemkatalogerna."""

    def setUp(self):
        super().setUp()
        self.hem = os.path.join(self.katalog, "hem")
        os.makedirs(self.hem)
        env = {k: v for k, v in os.environ.items() if k not in ("DATAKATALOG", "XDG_DATA_HOME", "LOCALAPPDATA")}
        env.update(HOME=self.hem, USERPROFILE=self.hem)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def mapp(self, *delar, fil="innehall.txt"):
        """Skapar en katalog under hemkatalogen med en fil i, och ger katalogens sokvag."""
        sokvag = os.path.join(self.hem, *delar)
        os.makedirs(sokvag)
        with open(os.path.join(sokvag, fil), "w", encoding="utf-8") as f:
            f.write("/".join(delar))
        return sokvag


class TestKataloger(TillfalligtHem):
    def test_programkatalog_mac(self):
        with system("Darwin"):
            self.assertEqual(plattform.programkatalog(),
                             os.path.join(self.hem, "Library", "Application Support", "Akasha Protokoll"))

    def test_programkatalog_windows(self):
        with system("Windows"), mock.patch.dict(os.environ, {"LOCALAPPDATA": "lokal"}):
            self.assertEqual(plattform.programkatalog(), os.path.join("lokal", "Akasha Protokoll"))

    def test_programkatalog_linux(self):
        with system("Linux"), mock.patch.dict(os.environ, {"XDG_DATA_HOME": "xdg"}):
            self.assertEqual(plattform.programkatalog(), os.path.join("xdg", "akasha-protokoll"))
        with system("Linux"):
            self.assertEqual(plattform.programkatalog(),
                             os.path.join(self.hem, ".local", "share", "akasha-protokoll"))

    def test_loggkatalog(self):
        with system("Darwin"):
            self.assertEqual(plattform.loggkatalog(), os.path.join(self.hem, "Library", "Logs", "Akasha Protokoll"))
        with system("Linux"), mock.patch.dict(os.environ, {"XDG_DATA_HOME": "xdg"}):
            self.assertEqual(plattform.loggkatalog(), os.path.join("xdg", "akasha-protokoll", "logg"))

    def test_installningsfil(self):
        with system("Linux"), mock.patch.dict(os.environ, {"XDG_DATA_HOME": "xdg"}):
            self.assertEqual(plattform.installningsfil(), os.path.join("xdg", "akasha-protokoll", "installningar.env"))

    def test_de_gamla_namnen(self):
        with system("Darwin"):
            self.assertEqual(plattform.gammal_programkatalog(),
                             os.path.join(self.hem, "Library", "Application Support", "Akasha Meet"))
        with system("Windows"), mock.patch.dict(os.environ, {"LOCALAPPDATA": "lokal"}):
            self.assertEqual(plattform.gammal_programkatalog(), os.path.join("lokal", "Akasha Meet"))
        with system("Linux"), mock.patch.dict(os.environ, {"XDG_DATA_HOME": "xdg"}):
            self.assertEqual(plattform.gammal_programkatalog(), os.path.join("xdg", "akasha-meet"))
        self.assertEqual((plattform.GAMMAL_DATAKATALOG, plattform.NY_DATAKATALOG), ("~/AkashaMeet", "~/AkashaProtokoll"))

    def test_ingen_av_dem_finns_ger_de_nya_namnen(self):
        with system("Darwin"):
            self.assertTrue(plattform.programkatalog().endswith("Akasha Protokoll"))
        self.assertEqual(plattform.standard_datakatalog(), "~/AkashaProtokoll")


class TestUpplosning(TillfalligtHem):
    """Den nya katalogen om den finns eller om den gamla inte finns, annars den gamla."""

    def test_bara_gammal_finns_ger_den_gamla(self):
        gammal = self.mapp("Library", "Application Support", "Akasha Meet")
        self.mapp("AkashaMeet")
        with system("Darwin"):
            self.assertEqual(plattform.programkatalog(), gammal)
            self.assertEqual(plattform.loggkatalog(), os.path.join(self.hem, "Library", "Logs", "Akasha Protokoll"))
        self.assertEqual(plattform.standard_datakatalog(), "~/AkashaMeet")

    def test_bara_ny_finns_ger_den_nya(self):
        ny = self.mapp("Library", "Application Support", "Akasha Protokoll")
        self.mapp("AkashaProtokoll")
        with system("Darwin"):
            self.assertEqual(plattform.programkatalog(), ny)
        self.assertEqual(plattform.standard_datakatalog(), "~/AkashaProtokoll")

    def test_bada_finns_ger_den_nya(self):
        self.mapp("Library", "Application Support", "Akasha Meet")
        ny = self.mapp("Library", "Application Support", "Akasha Protokoll")
        self.mapp("AkashaMeet")
        self.mapp("AkashaProtokoll")
        with system("Darwin"):
            self.assertEqual(plattform.programkatalog(), ny)
        self.assertEqual(plattform.standard_datakatalog(), "~/AkashaProtokoll")

    def test_en_fil_med_det_gamla_namnet_raknas_inte(self):
        with open(os.path.join(self.hem, "AkashaMeet"), "w", encoding="utf-8") as f:
            f.write("en fil")
        self.assertEqual(plattform.standard_datakatalog(), "~/AkashaProtokoll")

    def test_installningar_foljer_upplosningen_och_det_satta_vinner(self):
        self.addCleanup(setattr, installningar, "DATAKATALOG", installningar.DATAKATALOG)
        self.addCleanup(setattr, installningar, "MODELLKATALOG", installningar.MODELLKATALOG)
        self.mapp("AkashaMeet")
        installningar.uppdatera_platser()
        self.assertEqual(installningar.DATAKATALOG, os.path.join(self.hem, "AkashaMeet"))
        with mock.patch.dict(os.environ, {"DATAKATALOG": "~/Annat"}):
            installningar.uppdatera_platser()
            self.assertEqual(installningar.DATAKATALOG, os.path.join(self.hem, "Annat"))
        os.rename(os.path.join(self.hem, "AkashaMeet"), os.path.join(self.hem, "AkashaProtokoll"))
        installningar.uppdatera_platser()
        self.assertEqual(installningar.DATAKATALOG, os.path.join(self.hem, "AkashaProtokoll"))


class TestFlytt(TillfalligtHem):
    """flytta_till_nya_namn: bara os.rename, bara nar den gamla finns som katalog och den nya inte finns."""

    def trad(self):
        """Allt under hemkatalogen som (relativ sokvag, innehall eller None for en katalog)."""
        ut = {}
        for rot, kataloger, filer in os.walk(self.hem):
            for namn in kataloger:
                ut[os.path.relpath(os.path.join(rot, namn), self.hem).replace(os.sep, "/")] = None
            for namn in filer:
                sokvag = os.path.join(rot, namn)
                with open(sokvag, encoding="utf-8") as f:
                    ut[os.path.relpath(sokvag, self.hem).replace(os.sep, "/")] = f.read()
        return ut

    def test_bara_gammal_finns_flyttas_och_upplosningen_ger_den_nya(self):
        self.mapp("Library", "Application Support", "Akasha Meet", fil="installningar.env")
        os.makedirs(os.path.join(self.hem, "Library", "Application Support", "Akasha Meet", "modeller"))
        self.mapp("AkashaMeet", fil="20261119-140206.json")
        with system("Darwin"):
            self.assertTrue(plattform.programkatalog().endswith("Akasha Meet"))
            flyttat = plattform.flytta_till_nya_namn()
            self.assertEqual(flyttat, [
                (os.path.join(self.hem, "Library", "Application Support", "Akasha Meet"),
                 os.path.join(self.hem, "Library", "Application Support", "Akasha Protokoll")),
                (os.path.join(self.hem, "AkashaMeet"), os.path.join(self.hem, "AkashaProtokoll"))])
            self.assertTrue(plattform.programkatalog().endswith("Akasha Protokoll"))
        self.assertEqual(plattform.standard_datakatalog(), "~/AkashaProtokoll")
        self.assertEqual(self.trad(), {
            "Library": None, "Library/Application Support": None,
            "Library/Application Support/Akasha Protokoll": None,
            "Library/Application Support/Akasha Protokoll/installningar.env": "Library/Application Support/Akasha Meet",
            "Library/Application Support/Akasha Protokoll/modeller": None,
            "AkashaProtokoll": None, "AkashaProtokoll/20261119-140206.json": "AkashaMeet"})
        with system("Darwin"):
            self.assertEqual(plattform.flytta_till_nya_namn(), [])  # en andra gang gor ingenting

    def test_bada_finns_ror_ingenting_och_loggar(self):
        self.mapp("AkashaMeet", fil="gammal.json")
        self.mapp("AkashaProtokoll", fil="ny.json")
        self.mapp(".local", "share", "akasha-meet", fil="gammal.env")
        self.mapp(".local", "share", "akasha-protokoll", fil="ny.env")
        fore = self.trad()
        with system("Linux"), self.assertLogs("akasha-protokoll", "INFO") as lg:
            self.assertEqual(plattform.flytta_till_nya_namn(), [])
        self.assertEqual(self.trad(), fore)
        self.assertTrue(any("ingen av dem rors" in m for m in lg.output), lg.output)
        with system("Linux"):
            self.assertTrue(plattform.programkatalog().endswith("akasha-protokoll"))

    def test_en_tom_ny_katalog_skrivs_inte_over(self):
        self.mapp("AkashaMeet", fil="gammal.json")
        os.makedirs(os.path.join(self.hem, "AkashaProtokoll"))
        fore = self.trad()
        self.assertEqual(plattform.flytta_till_nya_namn(), [])
        self.assertEqual(self.trad(), fore)

    def test_satt_datakatalog_ger_ingen_flytt_av_inspelningarna(self):
        self.mapp("AkashaMeet", fil="gammal.json")
        self.mapp(".local", "share", "akasha-meet", fil="gammal.env")
        with system("Linux"), mock.patch.dict(os.environ, {"DATAKATALOG": "~/AkashaMeet"}):
            flyttat = plattform.flytta_till_nya_namn()  # ar DATAKATALOG satt avgors ur miljon
        self.assertEqual([ny for _, ny in flyttat], [os.path.join(self.hem, ".local", "share", "akasha-protokoll")])
        self.assertTrue(os.path.isfile(os.path.join(self.hem, "AkashaMeet", "gammal.json")))
        self.assertFalse(os.path.exists(os.path.join(self.hem, "AkashaProtokoll")))

    def test_tom_datakatalog_i_miljon_raknas_som_inte_satt(self):
        self.mapp("AkashaMeet", fil="gammal.json")
        with system("Linux"), mock.patch.dict(os.environ, {"DATAKATALOG": "  "}):
            plattform.flytta_till_nya_namn()
        self.assertTrue(os.path.isfile(os.path.join(self.hem, "AkashaProtokoll", "gammal.json")))

    def test_datakatalog_som_argument_gar_for_miljon(self):
        self.mapp("AkashaMeet", fil="gammal.json")
        with system("Linux"):
            self.assertEqual(plattform.flytta_till_nya_namn(datakatalog_satt=True), [])
        self.assertTrue(os.path.isfile(os.path.join(self.hem, "AkashaMeet", "gammal.json")))

    def test_rename_som_kastar_lamnar_den_gamla_som_anvands(self):
        self.mapp("Library", "Application Support", "Akasha Meet", fil="installningar.env")
        self.mapp("AkashaMeet", fil="gammal.json")
        fore = self.trad()
        with system("Darwin"), mock.patch("os.rename", side_effect=PermissionError(13, "nekad")), \
                self.assertLogs("akasha-protokoll", "WARNING") as lg:
            self.assertEqual(plattform.flytta_till_nya_namn(), [])
            self.assertTrue(plattform.programkatalog().endswith("Akasha Meet"))
        self.assertEqual(len(lg.output), 2)  # ett fel for varje mapp, och inget kastades
        self.assertEqual(plattform.standard_datakatalog(), "~/AkashaMeet")
        self.assertEqual(self.trad(), fore)

    def test_ett_fel_pa_forsta_mappen_hindrar_inte_den_andra(self):
        self.mapp("Library", "Application Support", "Akasha Meet", fil="installningar.env")
        self.mapp("AkashaMeet", fil="gammal.json")
        riktig = os.rename

        def rename(a, b):
            if a.endswith("Akasha Meet"):
                raise OSError(5, "fel")
            riktig(a, b)
        with system("Darwin"), mock.patch("os.rename", rename), self.assertLogs("akasha-protokoll", "WARNING"):
            flyttat = plattform.flytta_till_nya_namn()
        self.assertEqual(flyttat, [(os.path.join(self.hem, "AkashaMeet"), os.path.join(self.hem, "AkashaProtokoll"))])

    def test_en_fil_med_det_gamla_namnet_flyttas_inte(self):
        with open(os.path.join(self.hem, "AkashaMeet"), "w", encoding="utf-8") as f:
            f.write("en fil")
        self.assertEqual(plattform.flytta_till_nya_namn(), [])
        self.assertFalse(os.path.exists(os.path.join(self.hem, "AkashaProtokoll")))

    def test_flytten_tar_aldrig_bort_eller_skriver_over(self):
        """Koden anvander bara os.rename: inget annat som tar bort eller kopierar anropas."""
        self.mapp("AkashaMeet", fil="gammal.json")
        self.mapp("Library", "Application Support", "Akasha Meet")
        with system("Darwin"), mock.patch("shutil.rmtree") as rmtree, mock.patch("os.remove") as remove, \
                mock.patch("os.unlink") as unlink, mock.patch("shutil.move") as flytta, \
                mock.patch("shutil.copytree") as kopiera:
            plattform.flytta_till_nya_namn()
        for falsk in (rmtree, remove, unlink, flytta, kopiera):
            falsk.assert_not_called()


class TestInstallningsfil(Tillfallig):
    def skriv(self, data, namn="installningar.env"):
        fil = os.path.join(self.katalog, namn)
        with open(fil, "wb") as f:
            f.write(data)
        return fil

    def test_las_installningsfil(self):
        text = ("# kommentar\n\nexport A=1\nB = två ord \nC=\"med # inuti\"\nD='x'\n"
                "E=värde # kommentar\nF=a=b\n"
                "G=\"http://proxy.exempel:3128\" # företagets\nH='a b'   \n")
        fil = self.skriv(b"\xef\xbb\xbf" + text.encode("utf-8"))
        self.assertEqual(plattform.las_installningsfil(fil),
                         ({"A": "1", "B": "två ord", "C": "med # inuti", "D": "x", "E": "värde", "F": "a=b",
                           "G": "http://proxy.exempel:3128", "H": "a b"}, []))

    def test_oavslutat_citattecken_och_text_efter(self):
        fil = self.skriv('A=1\nI="ingen slut\nJ="x" y\nK=2\n'.encode("utf-8"))
        varden, problem = plattform.las_installningsfil(fil)
        self.assertEqual(varden, {"A": "1", "K": "2"})
        self.assertEqual(problem, [plattform.RAD_FEL.format(nr=2), plattform.RAD_FEL.format(nr=3)])
        self.assertFalse(any("ingen slut" in text for text in problem))

    def test_felaktiga_rader_namner_inget_ur_filen(self):
        fil = self.skriv("# rubrik\n\n1FEL=hemligt-lösen\nrad utan likhetstecken hemligt\nOK=1\n".encode("utf-8"))
        varden, problem = plattform.las_installningsfil(fil)
        self.assertEqual(varden, {"OK": "1"})
        self.assertEqual(problem, [plattform.RAD_FEL.format(nr=3), plattform.RAD_FEL.format(nr=4)])
        self.assertFalse(any("hemligt" in text for text in problem))

    def test_utf16_med_bom_och_crlf(self):
        fil = self.skriv("PORT=8700\n".encode("utf-16"))
        self.assertEqual(plattform.las_installningsfil(fil), ({"PORT": "8700"}, []))
        fil = self.skriv(b"A=1\r\nB=2\r\n", "crlf.env")
        self.assertEqual(plattform.las_installningsfil(fil), ({"A": "1", "B": "2"}, []))
        fil = self.skriv(b"A=1\rB=2\r", "cr.env")
        self.assertEqual(plattform.las_installningsfil(fil), ({"A": "1", "B": "2"}, []))

    def test_latin1_ger_kodningsproblem(self):
        fil = self.skriv("ORDLISTA=Västerås\n".encode("latin-1"))
        self.assertEqual(plattform.las_installningsfil(fil), ({}, [plattform.FIL_KODNING]))

    def test_katalog_med_filens_namn(self):
        fil = os.path.join(self.katalog, "installningar.env")
        os.mkdir(fil)
        varden, problem = plattform.las_installningsfil(fil)
        self.assertEqual(varden, {})
        self.assertEqual(len(problem), 1)
        self.assertTrue(problem[0].startswith("Filen gick inte att läsa ("))
        self.assertTrue(problem[0].endswith("). Inga inställningar ur den används."))

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "filbehorigheter gar inte att prova pa Windows eller som root")
    def test_fil_utan_behorighet(self):
        fil = self.skriv(b"A=1\n")
        os.chmod(fil, 0)
        self.addCleanup(os.chmod, fil, 0o600)
        varden, problem = plattform.las_installningsfil(fil)
        self.assertEqual(varden, {})
        self.assertEqual(len(problem), 1)

    def test_saknad_fil(self):
        self.assertEqual(plattform.las_installningsfil(os.path.join(self.katalog, "finns-inte.env")), ({}, []))

    def test_samma_namn_tva_ganger_sista_gar_fore(self):
        fil = self.skriv(b"A=1\nA=2\n")
        self.assertEqual(plattform.las_installningsfil(fil), ({"A": "2"}, []))

    def test_las_in_installningar_i_programmet(self):
        fil = self.skriv("AKASHA_PROV_NY=ny\nAKASHA_PROV_GAMMAL=fran-filen\nrad utan likhet\n".encode("utf-8"))
        with mock.patch.dict(os.environ, {"AKASHA_PROV_GAMMAL": "fran-miljon"}), \
             mock.patch.object(plattform, "ar_paketerad", return_value=True), \
             mock.patch.object(plattform, "installningsfil", return_value=fil):
            problem = plattform.las_in_installningar()
            self.assertEqual(os.environ["AKASHA_PROV_NY"], "ny")
            self.assertEqual(os.environ["AKASHA_PROV_GAMMAL"], "fran-miljon")
            os.environ.pop("AKASHA_PROV_NY")
        self.assertEqual(problem, [plattform.RAD_FEL.format(nr=3)])

    def test_las_in_installningar_utanfor_programmet(self):
        with mock.patch.object(plattform, "ar_paketerad", return_value=False), \
             mock.patch.object(plattform, "las_installningsfil") as las:
            self.assertEqual(plattform.las_in_installningar(), [])
        las.assert_not_called()


class TestVarden(unittest.TestCase):
    def tearDown(self):
        importlib.reload(installningar)

    def ladda(self, **miljo):
        with mock.patch.dict(os.environ, miljo):
            return importlib.reload(installningar)

    def test_port_som_inte_ar_ett_tal(self):
        i = self.ladda(PORT="abc")
        self.assertEqual(i.PORT, 8611)
        self.assertEqual(len(i.PROBLEM), 1)
        self.assertIn("PORT", i.PROBLEM[0])
        self.assertNotIn("abc", i.PROBLEM[0])

    def test_port_utanfor_intervallet(self):
        i = self.ladda(PORT="80")
        self.assertEqual(i.PORT, 8611)
        self.assertEqual(len(i.PROBLEM), 1)

    def test_giltig_port(self):
        i = self.ladda(PORT="8700")
        self.assertEqual(i.PORT, 8700)
        self.assertEqual(i.PROBLEM, [])

    def test_troskel_med_komma_och_utanfor(self):
        self.assertEqual(self.ladda(TALARE_TROSKEL="0,7").TALARE_TROSKEL, 0.7)
        i = self.ladda(TALARE_TROSKEL="2")
        self.assertEqual(i.TALARE_TROSKEL, 0.6)
        self.assertEqual(len(i.PROBLEM), 1)
        self.assertIn("Standardvärdet 0,6 används.", i.PROBLEM[0])

    def test_max_mb_och_cpu_tradar(self):
        i = self.ladda(MAX_MB="0", CPU_TRADAR="300")
        self.assertEqual((i.MAX_MB, i.CPU_TRADAR), (1024, 0))
        self.assertEqual(len(i.PROBLEM), 2)


class TestRenProcess(Tillfallig):
    """Som granskarens prov: import i en ren process dar sys.frozen sattes fore importen."""

    def kor(self, data):
        hem = os.path.join(self.katalog, "hem")
        mapp = os.path.join(hem, "xdg", "akasha-protokoll")
        os.makedirs(mapp)
        fil = os.path.join(mapp, "installningar.env")
        if data is None:
            os.mkdir(fil)
        else:
            with open(fil, "wb") as f:
                f.write(data)
        miljo = {k: v for k, v in os.environ.items() if k not in ("PORT", "XDG_DATA_HOME", "HOME", "LOCALAPPDATA")}
        miljo.update(HOME=hem, USERPROFILE=hem, XDG_DATA_HOME=os.path.join(hem, "xdg"),
                     LOCALAPPDATA=os.path.join(hem, "xdg"), PYTHONPATH=os.path.join(os.path.dirname(hjalp.__file__), "..", "app"))
        kod = ("import sys; sys.frozen = True\n"
               "import plattform\n"
               "plattform.system = lambda: 'Linux'\n"
               "import installningar\n"
               "print(installningar.PORT, len(installningar.PROBLEM))\n")
        svar = subprocess.run([sys.executable, "-c", kod], env=miljo, capture_output=True, text=True, timeout=60)
        self.assertEqual(svar.returncode, 0, svar.stderr)
        return svar.stdout.split()

    def test_utf16(self):
        self.assertEqual(self.kor("PORT=8700\n".encode("utf-16")), ["8700", "0"])

    def test_latin1(self):
        self.assertEqual(self.kor("ORDLISTA=Västerås\n".encode("latin-1")), ["8611", "1"])

    def test_katalog(self):
        self.assertEqual(self.kor(None), ["8611", "1"])


class TestWhisperCli(Tillfallig):
    def test_paketerad_med_fil(self):
        fil = os.path.join(self.katalog, "whisper-cli")
        with open(fil, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(fil, 0o755)
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "_MEIPASS", self.katalog, create=True), \
             mock.patch.object(installningar, "WHISPERCPP_BIN", "whisper-cli"), \
             mock.patch.object(shutil, "which", side_effect=AssertionError("which ska inte anropas")):
            if os.name == "nt":
                self.skipTest("Windows har ingen korbarhetsbit")
            self.assertEqual(plattform.whisper_cli(), fil)

    def test_paketerad_utan_fil(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "_MEIPASS", self.katalog, create=True), \
             mock.patch.object(installningar, "WHISPERCPP_BIN", "whisper-cli"), \
             mock.patch.object(shutil, "which", side_effect=AssertionError("which ska inte anropas")):
            self.assertIsNone(plattform.whisper_cli())

    def test_inte_paketerad(self):
        with mock.patch.object(plattform, "ar_paketerad", return_value=False), \
             mock.patch.object(shutil, "which", return_value="/valfri/whisper-cli") as which:
            self.assertEqual(plattform.whisper_cli(), "/valfri/whisper-cli")
        which.assert_called_once_with(installningar.WHISPERCPP_BIN)


class TestWhisperCliWindows(Tillfallig):
    def paketerad(self):
        return (mock.patch.object(sys, "frozen", True, create=True),
                mock.patch.object(sys, "_MEIPASS", self.katalog, create=True),
                mock.patch.object(installningar, "WHISPERCPP_BIN", "whisper-cli"),
                mock.patch.object(shutil, "which", side_effect=AssertionError("which ska inte anropas")))

    def test_exe_i_mappen_whisper(self):
        mapp = os.path.join(self.katalog, "whisper")
        os.mkdir(mapp)
        fil = os.path.join(mapp, "whisper-cli.exe")
        with open(fil, "wb") as f:
            f.write(b"MZ")
        # en fil utan .exe i roten ska inte hittas pa Windows
        with open(os.path.join(self.katalog, "whisper-cli"), "wb") as f:
            f.write(b"x")
        a, b, c, d = self.paketerad()
        with a, b, c, d, system("Windows"):
            self.assertEqual(plattform.whisper_cli(), fil)

    def test_utan_exe(self):
        a, b, c, d = self.paketerad()
        with a, b, c, d, system("Windows"):
            self.assertIsNone(plattform.whisper_cli())

    def test_vald_bin_i_installningarna_ar_ovrort(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(installningar, "WHISPERCPP_BIN", "C:\\egen\\whisper-cli.exe"), \
             mock.patch.object(shutil, "which", return_value=os.path.abspath("X")) as which, system("Windows"):
            self.assertEqual(plattform.whisper_cli(), os.path.abspath("X"))
        which.assert_called_once_with("C:\\egen\\whisper-cli.exe")


class FalskKernel32:
    """Ersatter kernel32 pa Linux. Skriver ner anropen och vad som skickades."""

    def __init__(self, jobb=1234, mutex=77, sista_fel=0, tilldela=1, sats=1, exekvering=0x80000000):
        self.anrop = []
        self.flaggor = None
        self.jobb, self.mutex, self.tilldela, self.sats, self.exekvering = jobb, mutex, tilldela, sats, exekvering

    def CreateJobObjectW(self, attr, namn):
        self.anrop.append(("CreateJobObjectW", attr, namn))
        return self.jobb

    def SetInformationJobObject(self, jobb, klass, info, storlek):
        self.anrop.append(("SetInformationJobObject", jobb, klass, storlek))
        self.flaggor = info._obj.BasicLimitInformation.LimitFlags
        return self.sats

    def AssignProcessToJobObject(self, jobb, process):
        self.anrop.append(("AssignProcessToJobObject", jobb, process))
        return self.tilldela

    def CloseHandle(self, h):
        self.anrop.append(("CloseHandle", h))
        return 1

    def CreateMutexW(self, attr, agare, namn):
        self.anrop.append(("CreateMutexW", attr, agare, namn))
        return self.mutex

    def SetThreadExecutionState(self, flaggor):
        self.anrop.append(("SetThreadExecutionState", flaggor))
        return self.exekvering


@contextlib.contextmanager
def falsk_win(k32):
    """Windows-grenen pa Linux: system() = Windows, falsk kernel32 och nollstallt tillstand i modulen."""
    with system("Windows"), mock.patch.object(plattform, "_kernel32", return_value=k32), \
         mock.patch.object(plattform, "_jobb", None), mock.patch.object(plattform, "_jobb_forsokt", False), \
         mock.patch.object(plattform, "_mutex", None), mock.patch.object(plattform, "_fel", lambda: 0), \
         mock.patch.object(plattform, "_nolla_fel"):
        yield


class FalskBarn:
    pid = 4242
    _handle = 999


class TestStartaBarn(unittest.TestCase):
    def test_mac_och_linux_ar_bara_popen(self):
        for namn in ("Darwin", "Linux"):
            with system(namn), mock.patch.object(subprocess, "Popen") as popen, \
                 mock.patch.object(plattform, "_kernel32", side_effect=AssertionError("ingen kernel32")):
                plattform.starta_barn(["x", "-a"], cwd="/mapp", stdout=subprocess.DEVNULL)
            popen.assert_called_once_with(["x", "-a"], cwd="/mapp", stdout=subprocess.DEVNULL)

    def test_windows_utan_fonster_och_i_jobbet(self):
        k = FalskKernel32()
        with falsk_win(k), mock.patch.object(subprocess, "Popen", return_value=FalskBarn()) as popen:
            p = plattform.starta_barn(["x.exe"], cwd="C:\\mapp", stderr=subprocess.PIPE)
        self.assertIsInstance(p, FalskBarn)
        popen.assert_called_once_with(["x.exe"], cwd="C:\\mapp", stderr=subprocess.PIPE,
                                      creationflags=0x08000000)
        self.assertEqual(k.flaggor, 0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self.assertEqual([x[0] for x in k.anrop],
                         ["CreateJobObjectW", "SetInformationJobObject", "AssignProcessToJobObject"])
        self.assertEqual(k.anrop[1][2:], (9, ctypes.sizeof(plattform._ExtendedLimit)))
        self.assertEqual(k.anrop[2][1:], (1234, 999))

    def test_egna_flaggor_behalls(self):
        with falsk_win(FalskKernel32()), mock.patch.object(subprocess, "Popen", return_value=FalskBarn()) as popen:
            plattform.starta_barn(["x"], creationflags=0x200)
        self.assertEqual(popen.call_args[1]["creationflags"], 0x200 | 0x08000000)

    def test_ett_jobb_per_process(self):
        k = FalskKernel32()
        with falsk_win(k), mock.patch.object(subprocess, "Popen", return_value=FalskBarn()):
            plattform.starta_barn(["x"])
            plattform.starta_barn(["y"])
        self.assertEqual([x[0] for x in k.anrop].count("CreateJobObjectW"), 1)
        self.assertEqual([x[0] for x in k.anrop].count("AssignProcessToJobObject"), 2)

    def test_misslyckad_tilldelning_loggas_och_processen_kors_anda(self):
        with falsk_win(FalskKernel32(tilldela=0)), mock.patch.object(subprocess, "Popen", return_value=FalskBarn()), \
             self.assertLogs("akasha-protokoll", "WARNING") as logg:
            p = plattform.starta_barn(["x"])
        self.assertIsInstance(p, FalskBarn)
        self.assertTrue(any("jobbobjekt" in r for r in logg.output), logg.output)

    def test_jobb_som_inte_gar_att_skapa(self):
        k = FalskKernel32(jobb=None)
        with falsk_win(k), mock.patch.object(subprocess, "Popen", return_value=FalskBarn()), \
             self.assertLogs("akasha-protokoll", "WARNING"):
            plattform.starta_barn(["x"])
            plattform.starta_barn(["y"])  # forsoker inte igen
        self.assertEqual([x[0] for x in k.anrop], ["CreateJobObjectW"])

    def test_jobb_vars_installning_misslyckas_stangs_och_ignoreras(self):
        k = FalskKernel32(sats=0)
        with falsk_win(k), mock.patch.object(subprocess, "Popen", return_value=FalskBarn()), \
             self.assertLogs("akasha-protokoll", "WARNING"):
            plattform.starta_barn(["x"])
        self.assertIn(("CloseHandle", 1234), k.anrop)
        self.assertNotIn("AssignProcessToJobObject", [x[0] for x in k.anrop])

    def test_strukturen_har_ratt_storlek_pa_64_bitar(self):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            self.skipTest("bara 64 bitar")
        self.assertEqual(ctypes.sizeof(plattform._BasicLimit), 64)
        self.assertEqual(ctypes.sizeof(plattform._ExtendedLimit), 144)


class TestEnKopia(unittest.TestCase):
    def test_utanfor_windows_alltid_sant(self):
        for namn in ("Darwin", "Linux"):
            with system(namn), mock.patch.object(plattform, "_kernel32", side_effect=AssertionError("ingen")):
                self.assertTrue(plattform.en_kopia("Local\\X"))
                self.assertTrue(plattform.en_kopia("Local\\X"))

    def test_forsta_och_andra(self):
        k = FalskKernel32()
        fel = iter([0, 183])
        with falsk_win(k), mock.patch.object(plattform, "_fel", lambda: next(fel)):
            self.assertTrue(plattform.en_kopia("Local\\AkashaProtokoll"))
            self.assertEqual(plattform._mutex, 77)
            self.assertFalse(plattform.en_kopia("Local\\AkashaProtokoll"))
        self.assertEqual(k.anrop[0], ("CreateMutexW", None, False, "Local\\AkashaProtokoll"))

    def test_mutexen_gick_inte_att_skapa_raknas_som_ensam(self):
        with falsk_win(FalskKernel32(mutex=None)), mock.patch.object(plattform, "_fel", lambda: 5), \
             self.assertLogs("akasha-protokoll", "WARNING"):
            self.assertTrue(plattform.en_kopia("Local\\X"))
            self.assertIsNone(plattform._mutex)


class TestHallVakenWindows(unittest.TestCase):
    def test_satter_och_slapper(self):
        k = FalskKernel32()
        with falsk_win(k):
            with plattform.hall_vaken():
                self.assertEqual(k.anrop, [("SetThreadExecutionState", 0x80000001)])
        self.assertEqual(k.anrop[1:], [("SetThreadExecutionState", 0x80000000)])

    def test_slapper_aven_vid_fel_i_jobbet(self):
        k = FalskKernel32()
        with falsk_win(k), self.assertRaises(ValueError):
            with plattform.hall_vaken():
                raise ValueError
        self.assertEqual(k.anrop[-1], ("SetThreadExecutionState", 0x80000000))

    def test_misslyckat_anrop_loggas_men_stoppar_inte_jobbet(self):
        k = FalskKernel32(exekvering=0)
        with falsk_win(k), self.assertLogs("akasha-protokoll", "WARNING"):
            with plattform.hall_vaken():
                pass

    def test_inget_pa_linux(self):
        with system("Linux"), mock.patch.object(plattform, "_kernel32", side_effect=AssertionError("ingen")), \
             mock.patch.object(subprocess, "Popen", side_effect=AssertionError("ingen")):
            with plattform.hall_vaken():
                pass


class TestWhisperCliRelativ(Tillfallig):
    def test_relativ_bin_ger_absolut_sokvag(self):
        mapp = os.path.join(self.katalog, "bin")
        os.mkdir(mapp)
        fil = os.path.join(mapp, "whisper-cli.exe" if os.name == "nt" else "whisper-cli")
        with open(fil, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(fil, 0o755)
        rel = os.path.join(".", "bin", os.path.basename(fil))
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.katalog)
        with mock.patch.object(plattform, "ar_paketerad", return_value=False), \
             mock.patch.object(installningar, "WHISPERCPP_BIN", rel):
            funnen = plattform.whisper_cli()
        self.assertTrue(os.path.isabs(funnen), funnen)
        self.assertEqual(os.path.realpath(funnen), os.path.realpath(fil))

    def test_saknad_ger_none(self):
        with mock.patch.object(plattform, "ar_paketerad", return_value=False), \
             mock.patch.object(shutil, "which", return_value=None):
            self.assertIsNone(plattform.whisper_cli())


class TestHallVaken(unittest.TestCase):
    def test_caffeinate_med_w(self):
        process = mock.Mock()
        with system("Darwin"), mock.patch.object(shutil, "which", return_value="/usr/bin/caffeinate"), \
             mock.patch.object(subprocess, "Popen", return_value=process) as popen:
            with plattform.hall_vaken():
                popen.assert_called_once_with(["caffeinate", "-i", "-w", str(os.getpid())])
                process.terminate.assert_not_called()
        process.terminate.assert_called_once()


class TestVisaFil(unittest.TestCase):
    def test_windows_citattecken_bara_runt_sokvagen(self):
        with system("Windows"), mock.patch.object(subprocess, "Popen") as popen:
            plattform.visa_fil("C:\\Users\\Åsa Öberg\\AkashaProtokoll\\en fil.txt")
        popen.assert_called_once_with('explorer /select,"C:\\Users\\Åsa Öberg\\AkashaProtokoll\\en fil.txt"')

    def test_windows_snedstreck_blir_omvanda(self):
        with system("Windows"), mock.patch.object(subprocess, "Popen") as popen:
            plattform.visa_fil("C:/Users/x/fil.txt")
        self.assertEqual(popen.call_args[0][0], 'explorer /select,"C:\\Users\\x\\fil.txt"')

    def test_windows_citattecken_i_sokvagen_loggas_och_ger_inget_anrop(self):
        with system("Windows"), mock.patch.object(subprocess, "Popen") as popen, \
             self.assertLogs("akasha-protokoll", "WARNING"):
            plattform.visa_fil('C:\\x"y\\fil.txt')
        popen.assert_not_called()

    def test_mac_ar_oforandrat(self):
        with system("Darwin"), mock.patch.object(subprocess, "Popen") as popen:
            plattform.visa_fil("/x/y.txt")
        popen.assert_called_once_with(["/usr/bin/open", "-R", "/x/y.txt"])


class TestFilKodning(Tillfallig):
    def test_olika_text_pa_mac_och_windows(self):
        fil = os.path.join(self.katalog, "i.env")
        with open(fil, "wb") as f:
            f.write("ORDLISTA=Västerås\n".encode("latin-1"))
        with system("Windows"):
            _, problem = plattform.las_installningsfil(fil)
        self.assertEqual(problem, [plattform.FIL_KODNING_WINDOWS])
        self.assertEqual(problem, ["Filen är inte sparad som ren text i UTF-8. Inga inställningar ur den används. "
                                   "Öppna den i Anteckningar, välj Arkiv → Spara som och välj kodningen UTF-8."])
        self.assertNotIn("TextEdit", problem[0])
        with system("Darwin"):
            _, problem = plattform.las_installningsfil(fil)
        self.assertEqual(problem, [plattform.FIL_KODNING])
        self.assertIn("TextEdit", problem[0])


@unittest.skipUnless(os.name == "nt", "bara pa Windows: riktiga anrop till kernel32")
class TestWindowsRiktigt(unittest.TestCase):
    """Kors bara pa Windows (windows-latest i tester.yml). Inga fonster; allt som vantar har en tidsgrans."""
    APP = os.path.join(os.path.dirname(os.path.abspath(hjalp.__file__)), "..", "app")

    def kor_skript(self, kod, *args, **kw):
        fil = os.path.join(tempfile.mkdtemp(prefix="akasha-win-"), "skript.py")
        self.addCleanup(shutil.rmtree, os.path.dirname(fil), True)
        with open(fil, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(kod))
        p = subprocess.Popen([sys.executable, fil, os.path.abspath(self.APP), *args],
                             stdout=subprocess.PIPE, stdin=subprocess.PIPE, text=True,
                             creationflags=0x08000000, **kw)
        # Tidsgrans: hanger skriptet dodas det efter en minut, sa att readline() inte vantar for evigt.
        vakt = threading.Timer(60, p.kill)
        vakt.daemon = True
        vakt.start()
        self.addCleanup(vakt.cancel)
        return p

    @staticmethod
    def _k32():
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k.WaitForSingleObject.restype = ctypes.c_uint32
        k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.TerminateProcess.restype = ctypes.c_int
        k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.CloseHandle.restype = ctypes.c_int
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        return k

    def vanta_pa_slut(self, pid, ms):
        """True om processen har avslutats inom ms millisekunder."""
        k = self._k32()
        h = k.OpenProcess(0x00100000 | 0x0001, 0, pid)  # SYNCHRONIZE | PROCESS_TERMINATE
        if not h:  # finns inte langre
            return True
        try:
            return k.WaitForSingleObject(h, ms) == 0
        finally:
            k.CloseHandle(h)

    def doda(self, pid):
        k = self._k32()
        h = k.OpenProcess(0x0001, 0, pid)
        if h:
            k.TerminateProcess(h, 1)
            k.CloseHandle(h)

    def test_barnet_dor_nar_foraldern_avslutas_med_terminateprocess(self):
        mellan = self.kor_skript("""
            import subprocess, sys, time
            sys.path.insert(0, sys.argv[1])
            import plattform
            barn = plattform.starta_barn([sys.executable, "-c", "import time; time.sleep(60)"])
            print(barn.pid, flush=True)
            time.sleep(60)
        """)
        barn_pid = None
        try:
            barn_pid = int(mellan.stdout.readline())  # slutar vanta nar mellanprocessen har dott
            self.assertFalse(self.vanta_pa_slut(barn_pid, 500), "barnet dog av sig sjalv")
            mellan.kill()  # TerminateProcess
            mellan.wait(timeout=20)
            self.assertTrue(self.vanta_pa_slut(barn_pid, 15000), "barnprocessen lever kvar")
        finally:
            if mellan.poll() is None:
                mellan.kill()
                mellan.wait(timeout=20)
            for ror in (mellan.stdout, mellan.stdin):
                ror.close()
            if barn_pid:
                self.doda(barn_pid)

    def test_exekveringsstatet_svarar_annat_an_noll(self):
        # Forsta anropet satter ES_CONTINUOUS | ES_SYSTEM_REQUIRED; det andra far det som tidigare
        # lage, alltsa inte 0.
        with plattform.hall_vaken():
            self.assertNotEqual(plattform._exekvering(plattform.ES_CONTINUOUS | plattform.ES_SYSTEM_REQUIRED), 0)
        self.assertNotEqual(plattform._exekvering(plattform.ES_CONTINUOUS), 0)

    def test_en_kopia_i_tva_processer_ger_sant_och_falskt(self):
        namn = "Local\\AkashaProtokollTest" + str(os.getpid()) + str(int(time.time()))
        kod = """
            import sys
            sys.path.insert(0, sys.argv[1])
            import plattform
            print(plattform.en_kopia(sys.argv[2]), flush=True)
            sys.stdin.readline()
        """
        a = self.kor_skript(kod, namn)
        b = None
        try:
            self.assertEqual(a.stdout.readline().strip(), "True")
            b = self.kor_skript(kod, namn)
            self.assertEqual(b.stdout.readline().strip(), "False")
        finally:
            for p in (a, b):
                if p is None:
                    continue
                try:
                    p.stdin.write("\n")
                    p.stdin.flush()
                except OSError:
                    pass
                try:
                    p.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=20)
                p.stdout.close()
                p.stdin.close()


class TestSkyddadPlats(unittest.TestCase):
    HEM = os.path.join(os.sep, "Users", "x")

    def _j(self, *delar):
        return os.path.join(self.HEM, *delar)

    def test_skyddade_rotter(self):
        j = self._j
        fall = [
            (j("Downloads", "Akasha-Meet-main"), j("Downloads")),
            (j("Documents"), j("Documents")),
            (j("Desktop", "x"), j("Desktop")),
            (j("Library", "Mobile Documents", "com~apple~CloudDocs", "a"), j("Library", "Mobile Documents")),
            (j("Library", "CloudStorage", "Dropbox", "a"), j("Library", "CloudStorage")),
            (j("downloads", "a"), j("Downloads")),
        ]
        for sokvag, rot in fall:
            with self.subTest(sokvag=sokvag):
                self.assertEqual(plattform.skyddad_plats(sokvag, self.HEM), rot)

    def test_oskyddade(self):
        for sokvag in (self._j("akasha-meet"), self._j("Downloadsx", "a"),
                       self._j("Library", "Logs"), self.HEM):
            with self.subTest(sokvag=sokvag):
                self.assertIsNone(plattform.skyddad_plats(sokvag, self.HEM))

    @unittest.skipIf(os.name == "nt", "/Volumes finns inte pa Windows")
    def test_volumes(self):
        self.assertEqual(plattform.skyddad_plats("/Volumes/USB/a", self.HEM), "/Volumes")

    def test_ror_inte_filsystemet(self):
        def forbjuden(*a, **k):
            raise AssertionError("filsystemet far inte nas")
        with mock.patch("os.stat", forbjuden), mock.patch("os.lstat", forbjuden), \
                mock.patch("os.path.realpath", forbjuden):
            self.assertEqual(plattform.skyddad_plats(self._j("Downloads", "a"), self.HEM), self._j("Downloads"))
            self.assertIsNone(plattform.skyddad_plats(self._j("akasha-meet"), self.HEM))


class TestGamlaModellkataloger(Tillfallig):
    def _hem(self):
        return mock.patch.dict(os.environ, {"HOME": self.katalog, "USERPROFILE": self.katalog})

    def test_fran_plist_och_standardplats(self):
        repo = os.path.join(self.katalog, "repo")
        os.makedirs(os.path.join(repo, "modeller"))
        standard = os.path.join(self.katalog, "akasha-meet", "modeller")
        os.makedirs(standard)
        agenter = os.path.join(self.katalog, "Library", "LaunchAgents")
        os.makedirs(agenter)
        with open(os.path.join(agenter, "local.akasha-meet.plist"), "wb") as f:
            plistlib.dump({"ProgramArguments": ["/bin/bash", os.path.join(repo, "mac", "kor.sh")]}, f)
        with self._hem():
            self.assertEqual(plattform.gamla_modellkataloger(), [os.path.join(repo, "modeller"), standard])

    def test_samma_katalog_tas_med_en_gang(self):
        repo = os.path.join(self.katalog, "akasha-meet")
        os.makedirs(os.path.join(repo, "modeller"))
        agenter = os.path.join(self.katalog, "Library", "LaunchAgents")
        os.makedirs(agenter)
        with open(os.path.join(agenter, "local.akasha-meet.plist"), "wb") as f:
            plistlib.dump({"ProgramArguments": ["/bin/bash", os.path.join(repo, "mac", "kor.sh")]}, f)
        with self._hem():
            self.assertEqual(plattform.gamla_modellkataloger(), [os.path.join(repo, "modeller")])

    def test_trasig_plist(self):
        agenter = os.path.join(self.katalog, "Library", "LaunchAgents")
        os.makedirs(agenter)
        with open(os.path.join(agenter, "local.akasha-meet.plist"), "wb") as f:
            f.write(b"inte en plist")
        with self._hem():
            self.assertEqual(plattform.gamla_modellkataloger(), [])

    def test_ingen_katalog(self):
        with self._hem():
            self.assertEqual(plattform.gamla_modellkataloger(), [])

    def _plist(self, repo):
        agenter = os.path.join(self.katalog, "Library", "LaunchAgents")
        os.makedirs(agenter)
        with open(os.path.join(agenter, "local.akasha-meet.plist"), "wb") as f:
            plistlib.dump({"ProgramArguments": ["/bin/bash", os.path.join(repo, "mac", "kor.sh")]}, f)

    def test_skyddad_mapp_hoppas_over_utan_att_undersokas(self):
        repo = os.path.join(self.katalog, "Downloads", "Akasha-Meet-main")
        os.makedirs(os.path.join(repo, "modeller"))
        self._plist(repo)
        skyddad = os.path.join(self.katalog, "Downloads")
        riktig = os.path.isdir
        anrop = []

        def spion(p):
            anrop.append(p)
            return riktig(p)
        with self._hem(), mock.patch("os.path.isdir", spion), \
                self.assertLogs("akasha-protokoll", level="INFO") as lg:
            resultat = plattform.gamla_modellkataloger()
        self.assertEqual(resultat, [])
        self.assertFalse([p for p in anrop if str(p).startswith(skyddad)], anrop)
        self.assertTrue(any("modeller: letar inte i" in m for m in lg.output))

    def test_klonplatsen_med_det_nya_namnet_tas_ocksa_med(self):
        repo = os.path.join(self.katalog, "akasha-protokoll")
        os.makedirs(os.path.join(repo, "modeller"))
        with self._hem():
            self.assertEqual(plattform.gamla_modellkataloger(), [os.path.join(repo, "modeller")])

    def test_repo_i_hemkatalogen_tas_med(self):
        repo = os.path.join(self.katalog, "akasha-meet")
        os.makedirs(os.path.join(repo, "modeller"))
        self._plist(repo)
        with self._hem():
            self.assertEqual(plattform.gamla_modellkataloger(), [os.path.join(repo, "modeller")])


class TestGammalTjanst(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(os, "getuid", return_value=501, create=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_linux_anropar_inget(self):
        with system("Linux"), mock.patch.object(subprocess, "run") as run:
            self.assertFalse(plattform.gammal_tjanst_finns())
        run.assert_not_called()

    def test_mac(self):
        for kod, vantat in ((0, True), (113, False)):
            with system("Darwin"), mock.patch.object(subprocess, "run", return_value=mock.Mock(returncode=kod)) as run:
                self.assertEqual(plattform.gammal_tjanst_finns(), vantat)
            run.assert_called_once_with(["launchctl", "print", "gui/501/local.akasha-meet"],
                                        capture_output=True, timeout=5)
        with system("Darwin"), mock.patch.object(subprocess, "run", side_effect=OSError):
            self.assertFalse(plattform.gammal_tjanst_finns())

    def test_stang_av(self):
        with system("Darwin"), mock.patch.object(subprocess, "run", return_value=mock.Mock(returncode=0)) as run, \
             mock.patch.object(plattform, "gammal_tjanst_finns", return_value=False):
            self.assertTrue(plattform.stang_av_gammal_tjanst())
        self.assertEqual([c.args[0] for c in run.call_args_list],
                         [["launchctl", "disable", "gui/501/local.akasha-meet"],
                          ["launchctl", "bootout", "gui/501/local.akasha-meet"]])

    def test_stang_av_pa_linux(self):
        with system("Linux"), mock.patch.object(subprocess, "run") as run:
            self.assertFalse(plattform.stang_av_gammal_tjanst())
        run.assert_not_called()


class TestModellkatalogIProgrammet(Tillfallig):
    def tearDown(self):
        importlib.reload(installningar)

    def test_programkatalog_i_programmet(self):
        env = {k: v for k, v in os.environ.items() if k != "MODELLKATALOG"}
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(plattform, "programkatalog", return_value=self.katalog), \
             mock.patch.object(plattform, "installningsfil", return_value=os.path.join(self.katalog, "ingen.env")):
            importlib.reload(installningar)
            self.assertEqual(installningar.MODELLKATALOG, os.path.join(self.katalog, "modeller"))


class TestOppnaWebblasare(unittest.TestCase):
    def test_mac(self):
        with system("Darwin"), mock.patch.object(subprocess, "Popen") as popen:
            self.assertTrue(plattform.oppna_webblasare("http://127.0.0.1:1"))
        popen.assert_called_once_with(["/usr/bin/open", "http://127.0.0.1:1"])

    def test_andra_system(self):
        with system("Linux"), mock.patch.object(plattform.webbrowser, "open") as oppna:
            self.assertTrue(plattform.oppna_webblasare("http://127.0.0.1:1"))
        oppna.assert_called_once_with("http://127.0.0.1:1")

    def test_fel(self):
        with system("Darwin"), mock.patch.object(subprocess, "Popen", side_effect=OSError):
            self.assertFalse(plattform.oppna_webblasare("http://127.0.0.1:1"))


if __name__ == "__main__":
    unittest.main()
