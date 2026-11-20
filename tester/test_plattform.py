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
        mapp = os.path.join(hem, "xdg", "akasha-meet")
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


class TestHallVaken(unittest.TestCase):
    def test_caffeinate_med_w(self):
        process = mock.Mock()
        with system("Darwin"), mock.patch.object(shutil, "which", return_value="/usr/bin/caffeinate"), \
             mock.patch.object(subprocess, "Popen", return_value=process) as popen:
            with plattform.hall_vaken():
                popen.assert_called_once_with(["caffeinate", "-i", "-w", str(os.getpid())])
                process.terminate.assert_not_called()
        process.terminate.assert_called_once()


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
