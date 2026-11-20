"""Plattformen: kataloger, installningsfil, medfoljande whisper-cli och den gamla launchd-tjansten."""
import hjalp  # noqa: F401  (maste importeras forst)

import importlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
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


class TestKataloger(unittest.TestCase):
    def test_programkatalog_mac(self):
        with system("Darwin"):
            self.assertEqual(plattform.programkatalog(),
                             os.path.expanduser("~/Library/Application Support/Akasha Meet"))

    def test_programkatalog_windows(self):
        with system("Windows"), mock.patch.dict(os.environ, {"LOCALAPPDATA": "lokal"}):
            self.assertEqual(plattform.programkatalog(), os.path.join("lokal", "Akasha Meet"))

    def test_programkatalog_linux(self):
        with system("Linux"), mock.patch.dict(os.environ, {"XDG_DATA_HOME": "xdg"}):
            self.assertEqual(plattform.programkatalog(), os.path.join("xdg", "akasha-meet"))
        env = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
        with system("Linux"), mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(plattform.programkatalog(),
                             os.path.join(os.path.expanduser(os.path.join("~", ".local", "share")), "akasha-meet"))

    def test_loggkatalog(self):
        with system("Darwin"):
            self.assertEqual(plattform.loggkatalog(), os.path.expanduser("~/Library/Logs/Akasha Meet"))
        with system("Linux"), mock.patch.dict(os.environ, {"XDG_DATA_HOME": "xdg"}):
            self.assertEqual(plattform.loggkatalog(), os.path.join("xdg", "akasha-meet", "logg"))

    def test_installningsfil(self):
        with system("Linux"), mock.patch.dict(os.environ, {"XDG_DATA_HOME": "xdg"}):
            self.assertEqual(plattform.installningsfil(), os.path.join("xdg", "akasha-meet", "installningar.env"))


class TestInstallningsfil(Tillfallig):
    def test_las_installningsfil(self):
        fil = os.path.join(self.katalog, "installningar.env")
        text = ("# kommentar\n\nexport A=1\nB = två ord \nC=\"med # inuti\"\nD='x'\n"
                "E=värde # kommentar\n1FEL=x\nrad utan likhetstecken\nF=a=b\n")
        with open(fil, "wb") as f:
            f.write(b"\xef\xbb\xbf" + text.encode("utf-8"))
        self.assertEqual(plattform.las_installningsfil(fil),
                         {"A": "1", "B": "två ord", "C": "med # inuti", "D": "x", "E": "värde", "F": "a=b"})

    def test_saknad_fil(self):
        self.assertEqual(plattform.las_installningsfil(os.path.join(self.katalog, "finns-inte.env")), {})

    def test_las_in_installningar_i_programmet(self):
        fil = os.path.join(self.katalog, "installningar.env")
        with open(fil, "w", encoding="utf-8") as f:
            f.write("AKASHA_PROV_NY=ny\nAKASHA_PROV_GAMMAL=fran-filen\n")
        with mock.patch.dict(os.environ, {"AKASHA_PROV_GAMMAL": "fran-miljon"}), \
             mock.patch.object(plattform, "ar_paketerad", return_value=True), \
             mock.patch.object(plattform, "installningsfil", return_value=fil):
            lastes = plattform.las_in_installningar()
            self.assertEqual(os.environ["AKASHA_PROV_NY"], "ny")
            self.assertEqual(os.environ["AKASHA_PROV_GAMMAL"], "fran-miljon")
            os.environ.pop("AKASHA_PROV_NY")
        self.assertEqual(lastes, {"AKASHA_PROV_NY": "ny", "AKASHA_PROV_GAMMAL": "fran-filen"})

    def test_las_in_installningar_utanfor_programmet(self):
        with mock.patch.object(plattform, "ar_paketerad", return_value=False), \
             mock.patch.object(plattform, "las_installningsfil") as las:
            self.assertEqual(plattform.las_in_installningar(), {})
        las.assert_not_called()


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


class TestHallVaken(unittest.TestCase):
    def test_caffeinate_med_w(self):
        process = mock.Mock()
        with system("Darwin"), mock.patch.object(shutil, "which", return_value="/usr/bin/caffeinate"), \
             mock.patch.object(subprocess, "Popen", return_value=process) as popen:
            with plattform.hall_vaken():
                popen.assert_called_once_with(["caffeinate", "-i", "-w", str(os.getpid())])
                process.terminate.assert_not_called()
        process.terminate.assert_called_once()


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
