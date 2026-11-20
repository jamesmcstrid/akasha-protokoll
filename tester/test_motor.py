import json
import os
import shutil
import sys
import tempfile
import textwrap
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

    def test_auto_pa_windows_kraver_cli_och_modell(self):
        self.assertEqual(self.val(system="Windows"), "whispercpp")
        self.assertEqual(self.val(system="Windows", har_cli=False), "faster")  # t.ex. installation fran kallkod
        self.assertEqual(self.val(system="Windows", har_ggml=False), "faster")

    def test_tvingat_val_galler(self):
        self.assertEqual(self.val("faster"), "faster")
        self.assertEqual(self.val("whispercpp", system="Linux"), "whispercpp")


class TestMalMotor(unittest.TestCase):
    def test_mac_med_cli_ger_whispercpp_aven_utan_ggml(self):
        self.assertEqual(motor.mal_motor("auto", "Darwin", True), "whispercpp")

    def test_windows_med_cli_ger_whispercpp(self):
        self.assertEqual(motor.mal_motor("auto", "Windows", True), "whispercpp")

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
             mock.patch.object(plattform, "system", lambda: "Darwin"), \
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
        with mock.patch.object(plattform, "ar_paketerad", lambda: False), \
             mock.patch.object(plattform, "system", lambda: "Darwin"):
            self.assertEqual(motor._cli_saknas(), f"{installningar.WHISPERCPP_BIN} saknas. Kör: brew install whisper-cpp")
        with mock.patch.object(plattform, "ar_paketerad", lambda: False), \
             mock.patch.object(plattform, "system", lambda: "Windows"):
            text = motor._cli_saknas()
        self.assertNotIn("brew", text)
        self.assertIn("whisper-cli.exe", text)

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
            ut = os.path.join(kw["cwd"], cmd[cmd.index("-of") + 1])  # relativ till arbetskatalogen
            with open(ut + ".json", "w", encoding="utf-8") as f:
                f.write('{"transcription": []}')
            return MedFramsteg()

        framsteg = []
        with mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(plattform, "system", lambda: "Darwin"), \
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


def gammalt_kommando(cli, katalog, per_ord, prompt, tradar):
    """Kommandot som _whispercpp() byggde fore W2 (absoluta sokvagar), ordagrant."""
    ut = os.path.join(katalog, "ut")
    cmd = [
        cli,
        "-m", modeller.GGML_MODELL,
        "-f", os.path.join(katalog, "ljud.wav"),
        "-l", installningar.SPRAK,
        "-bs", str(motor.BEAM),
        "-np", "-pp",
        "-oj", "-of", ut,
    ]
    if prompt:
        cmd += ["--prompt", prompt]
    if tradar:
        cmd += ["-t", str(tradar)]
    if per_ord:
        cmd += ["-ml", "1", "-sow", "--dtw", modeller.DTW, "-nfa", "-ojf"]
    return cmd


class TestCliKommando(unittest.TestCase):
    REL = "tmp-akasha-protokoll-abc123"

    def abs_katalog(self):
        return os.path.join(modeller.MODELLKATALOG, self.REL)

    def test_mac_ar_som_forut_utom_sokvagarna(self):
        """Fore/efter: Darwin-kommandot skiljer sig bara i de tre sokvagarna (nu relativa), inget annat."""
        for per_ord in (False, True):
            for prompt in ("", "Åsa Öberg, Västerås"):
                for tradar in (0, 6):
                    fore = gammalt_kommando("/x/whisper-cli", self.abs_katalog(), per_ord, prompt, tradar)
                    efter, svarsfil = motor.cli_kommando("/x/whisper-cli", self.REL, per_ord, prompt, tradar, "Darwin")
                    self.assertIsNone(svarsfil)
                    self.assertEqual(len(efter), len(fore))
                    skillnader = [(a, b) for a, b in zip(fore, efter) if a != b]
                    self.assertEqual(skillnader, [
                        (modeller.GGML_MODELL, os.path.join("kb-whisper-medium-ggml", "ggml-model.bin")),
                        (os.path.join(self.abs_katalog(), "ljud.wav"), os.path.join(self.REL, "ljud.wav")),
                        (os.path.join(self.abs_katalog(), "ut"), os.path.join(self.REL, "ut")),
                    ])

    def test_mac_kommandot_ordagrant(self):
        cmd, _ = motor.cli_kommando("/x/whisper-cli", self.REL, True, "Åsa", 4, "Darwin")
        self.assertEqual(cmd, [
            "/x/whisper-cli", "-m", os.path.join("kb-whisper-medium-ggml", "ggml-model.bin"),
            "-f", os.path.join(self.REL, "ljud.wav"), "-l", "sv", "-bs", "5", "-np", "-pp",
            "-oj", "-of", os.path.join(self.REL, "ut"), "--prompt", "Åsa", "-t", "4",
            "-ml", "1", "-sow", "--dtw", "medium", "-nfa", "-ojf"])

    def test_linux_som_mac(self):
        self.assertEqual(motor.cli_kommando("/x/c", self.REL, False, "x", 0, "Linux"),
                         motor.cli_kommando("/x/c", self.REL, False, "x", 0, "Darwin"))

    def test_sokvagarna_ar_relativa_och_har_inte_modellkatalogen(self):
        for system in ("Darwin", "Windows"):
            cmd, svarsfil = motor.cli_kommando("/x/c", self.REL, True, "ord", 2, system)
            text = " ".join(cmd) + (svarsfil or "")
            self.assertNotIn(modeller.MODELLKATALOG, text)
            self.assertNotIn(tempfile.gettempdir(), text)
            for a in (cmd if svarsfil is None else svarsfil.splitlines()):
                if a.endswith((".bin", ".wav", "ut")) and not a.startswith(("-", "/")):
                    self.assertFalse(os.path.isabs(a), a)

    def test_windows_svarsfil(self):
        cmd, svarsfil = motor.cli_kommando("C:\\p\\whisper-cli.exe", self.REL, True, "Åsa Öberg", 4, "Windows")
        self.assertEqual(cmd, ["C:\\p\\whisper-cli.exe", "@" + os.path.join(self.REL, "args.txt")])
        mac, _ = motor.cli_kommando("C:\\p\\whisper-cli.exe", self.REL, True, "Åsa Öberg", 4, "Darwin")
        self.assertEqual(svarsfil.splitlines(), mac[1:])  # samma argument, en rad var, utan programnamnet
        self.assertTrue(svarsfil.endswith("\n"))
        self.assertNotIn("\r", svarsfil)
        self.assertIn("--prompt\nÅsa Öberg\n", svarsfil)
        data = svarsfil.encode("utf-8")
        self.assertIn(b"\xc3\x85sa \xc3\x96berg", data)  # UTF-8-byte for Asa Oberg (med prickarna)
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))  # ingen BOM

    def test_windows_radbrytning_i_ett_argument_blir_mellanslag(self):
        _, svarsfil = motor.cli_kommando("c", self.REL, False, "Åsa\nÖberg\r\nVäg", 0, "Windows")
        rader = svarsfil.splitlines()
        self.assertEqual(rader[rader.index("--prompt") + 1], "Åsa Öberg Väg")
        self.assertEqual(svarsfil.count("\n"), len(rader))

    def test_windows_utan_prompt_och_tradar(self):
        _, svarsfil = motor.cli_kommando("c", self.REL, False, "", 0, "Windows")
        self.assertNotIn("--prompt", svarsfil)
        self.assertNotIn("-t\n", svarsfil)


FALSK_CLI = textwrap.dedent("""
    import json, os, sys
    args = sys.argv[1:]
    if len(args) == 1 and args[0].startswith("@"):  # som whisper.cpp: en rad per argument, byte for byte
        with open(args[0][1:], "rb") as f:
            args = f.read().decode("utf-8").split("\\n")[:-1]
    d = dict(zip(args[::2], args[1::2]))  # alla flaggor har ett varde, utom de som ligger sist (-nfa osv.)
    prompt = args[args.index("--prompt") + 1] if "--prompt" in args else None
    modell = args[args.index("-m") + 1]
    with open(os.environ["FALSK_CLI_LOGG"], "w", encoding="utf-8") as f:
        json.dump({"cwd": os.getcwd(), "args": args, "prompt": prompt, "modell": modell,
                   "modell_finns": os.path.isfile(modell), "ljud_finns": os.path.isfile(args[args.index("-f") + 1]),
                   "katalog": os.path.dirname(args[args.index("-of") + 1])}, f)
    sys.stderr.write("whisper_print_progress_callback: progress =  50%\\n")
    with open(args[args.index("-of") + 1] + ".json", "w", encoding="utf-8") as f:
        f.write('{"transcription": [{"text": " Hej Åsa.", "offsets": {"from": 0, "to": 1500}, "tokens": []}]}')
""")


class FalskCliMiljo(unittest.TestCase):
    """En riktig process (ett Python-skript som liknar whisper-cli) startad via plattform.starta_barn."""

    def kor(self, mapp, system=None, prompt="Åsa Öberg"):
        bas = tempfile.mkdtemp(prefix="akasha-motor-")
        self.addCleanup(shutil.rmtree, bas, True)
        modellkatalog = os.path.join(bas, mapp)
        modell = os.path.join(modellkatalog, "kb-whisper-medium-ggml", "ggml-model.bin")
        os.makedirs(os.path.dirname(modell))
        with open(modell, "wb") as f:
            f.write(b"x")
        skript = os.path.join(bas, "falsk_cli.py")
        with open(skript, "w", encoding="utf-8") as f:
            f.write(FALSK_CLI)
        logg = os.path.join(bas, "logg.json")
        riktig = plattform.starta_barn

        def starta(cmd, cwd=None, **kw):
            cmd = [sys.executable, skript] + cmd[1:]
            if os.name != "nt":  # Windows-grenen med falskt system(): Popen utan Windows-flaggor
                return motor.subprocess.Popen(cmd, cwd=cwd, **kw)
            return riktig(cmd, cwd=cwd, **kw)  # pa Windows den riktiga: jobbobjekt och inget fonster

        patchar = [mock.patch.object(modeller, "MODELLKATALOG", modellkatalog),
                   mock.patch.object(motor, "GGML_MODELL", modell),
                   mock.patch.object(plattform, "whisper_cli", lambda: "falsk-cli"),
                   mock.patch.object(plattform, "starta_barn", starta),
                   mock.patch.dict(os.environ, {"FALSK_CLI_LOGG": logg})]
        if system:
            patchar.append(mock.patch.object(plattform, "system", lambda: system))
        for pa in patchar:
            pa.start()
            self.addCleanup(pa.stop)
        framsteg = []
        resultat = motor._whispercpp(np_tyst(), False, prompt, framsteg.append)
        with open(logg, encoding="utf-8") as f:
            return modellkatalog, json.load(f), resultat, framsteg


class TestWhispercppKor(FalskCliMiljo):
    def kontrollera(self, modellkatalog, logg, resultat, framsteg):
        self.assertEqual(os.path.realpath(logg["cwd"]), os.path.realpath(modellkatalog))
        self.assertTrue(logg["modell_finns"], "modellens relativa sokvag ska finnas fran arbetskatalogen")
        self.assertTrue(logg["ljud_finns"])
        self.assertFalse(os.path.isabs(logg["modell"]))
        self.assertTrue(logg["katalog"].startswith(motor.TMP_PREFIX), logg["katalog"])
        self.assertEqual(logg["prompt"], "Åsa Öberg")  # kom fram som UTF-8
        self.assertEqual(resultat[0], "Hej Åsa.")
        self.assertEqual(framsteg, [0.5])
        self.assertEqual([n for n in os.listdir(modellkatalog) if n.startswith(motor.TMP_PREFIX)], [],
                         "den tillfalliga katalogen ska tas bort")

    def test_mac_arbetskatalog_relativ_modell_och_stadning(self):
        mk, logg, res, fr = self.kor("modeller", system="Darwin")
        self.assertNotIn("@", "".join(logg["args"][:1]))
        self.kontrollera(mk, logg, res, fr)

    def test_windows_med_svarsfil(self):
        mk, logg, res, fr = self.kor("modeller", system="Windows")
        self.kontrollera(mk, logg, res, fr)

    def test_katalog_med_aao_i_namnet_via_svarsfil(self):
        mk, logg, res, fr = self.kor("Åsa Ölund", system="Windows")
        self.kontrollera(mk, logg, res, fr)

    def test_namnet_pa_den_tillfalliga_katalogen_ar_ascii(self):
        mk, logg, res, fr = self.kor("Åsa Ölund", system="Windows")
        logg["katalog"].encode("ascii")

    @unittest.skipUnless(os.name == "nt", "bara pa Windows: riktig svarsfil, riktig arbetskatalog med Åsa Ölund")
    def test_windows_riktigt_med_modellkatalog_som_heter_asa_olund(self):
        mk, logg, res, fr = self.kor("Åsa Ölund")  # plattform.system() ar riktigt "Windows"
        self.kontrollera(mk, logg, res, fr)


@unittest.skipIf(os.name == "nt", "ett skalskript som cli; sokvagstestet i test_plattform tacker Windows")
class TestRelativCli(unittest.TestCase):
    def test_relativ_whisper_cli_startas_trots_annan_arbetskatalog(self):
        """WHISPERCPP_BIN=./bin/whisper-cli: sokvagen gors absolut fore arbetskatalogen byts."""
        bas = tempfile.mkdtemp(prefix="akasha-motor-")
        self.addCleanup(shutil.rmtree, bas, True)
        bin_ = os.path.join(bas, "bin")
        modellkatalog = os.path.join(bas, "modeller")
        os.makedirs(bin_)
        os.makedirs(os.path.join(modellkatalog, "kb-whisper-medium-ggml"))
        modell = os.path.join(modellkatalog, "kb-whisper-medium-ggml", "ggml-model.bin")
        with open(modell, "wb") as f:
            f.write(b"x")
        logg = os.path.join(bas, "logg.json")
        cli = os.path.join(bin_, "whisper-cli")
        kod = f'#!/bin/sh\nexec "{sys.executable}" "{os.path.join(bas, "falsk_cli.py")}" "$@"\n'
        with open(cli, "w") as f:
            f.write(kod)
        os.chmod(cli, 0o755)
        with open(os.path.join(bas, "falsk_cli.py"), "w", encoding="utf-8") as f:
            f.write(FALSK_CLI)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(bas)  # annan an modellkatalogen: ./bin/whisper-cli finns bara har
        with mock.patch.object(modeller, "MODELLKATALOG", modellkatalog), \
             mock.patch.object(motor, "GGML_MODELL", modell), \
             mock.patch.object(plattform, "ar_paketerad", lambda: False), \
             mock.patch.object(plattform, "system", lambda: "Darwin"), \
             mock.patch.object(installningar, "WHISPERCPP_BIN", os.path.join(".", "bin", os.path.basename(cli))), \
             mock.patch.dict(os.environ, {"FALSK_CLI_LOGG": logg}):
            resultat = motor._whispercpp(np_tyst(), False, "", None)
        self.assertEqual(resultat[0], "Hej Åsa.")
        with open(logg, encoding="utf-8") as f:
            self.assertEqual(os.path.realpath(json.load(f)["cwd"]), os.path.realpath(modellkatalog))


class TestTillfalligKatalog(unittest.TestCase):
    def test_skapas_under_modellkatalogen_och_stadningen_ignorerar_fel(self):
        bas = tempfile.mkdtemp(prefix="akasha-motor-")
        self.addCleanup(shutil.rmtree, bas, True)
        anrop = []
        riktig = tempfile.TemporaryDirectory

        def tmp(*a, **kw):
            anrop.append(kw)
            return riktig(*a, **kw)

        with mock.patch.object(modeller, "MODELLKATALOG", bas), \
             mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(motor.tempfile, "TemporaryDirectory", tmp), \
             mock.patch.object(motor.subprocess, "Popen", return_value=FalskProcess()):
            with self.assertRaises(motor.MotorFel):
                motor._whispercpp(np_tyst(), False, "", None)
        self.assertEqual(anrop, [{"prefix": "tmp-akasha-protokoll-", "dir": bas, "ignore_cleanup_errors": True}])

    def test_startas_med_modellkatalogen_som_arbetskatalog(self):
        bas = tempfile.mkdtemp(prefix="akasha-motor-")
        self.addCleanup(shutil.rmtree, bas, True)
        with mock.patch.object(modeller, "MODELLKATALOG", bas), \
             mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli"), \
             mock.patch.object(plattform, "system", lambda: "Darwin"), \
             mock.patch.object(motor.subprocess, "Popen", return_value=FalskProcess()) as popen:
            with self.assertRaises(motor.MotorFel):
                motor._whispercpp(np_tyst(), False, "", None)
        self.assertEqual(popen.call_args[1]["cwd"], bas)

    def test_windows_startar_bara_med_svarsfilen(self):
        bas = tempfile.mkdtemp(prefix="akasha-motor-")
        self.addCleanup(shutil.rmtree, bas, True)
        sett = {}

        def popen(cmd, **kw):
            sett["cmd"] = cmd
            with open(os.path.join(kw["cwd"], cmd[1][1:]), "rb") as f:
                sett["fil"] = f.read()
            return FalskProcess()

        with mock.patch.object(modeller, "MODELLKATALOG", bas), \
             mock.patch.object(plattform, "whisper_cli", lambda: "/x/whisper-cli.exe"), \
             mock.patch.object(plattform, "system", lambda: "Windows"), \
             mock.patch.object(plattform, "starta_barn", popen):
            with self.assertRaises(motor.MotorFel):
                motor._whispercpp(np_tyst(), False, "Åsa Öberg", None)
        self.assertEqual(len(sett["cmd"]), 2)
        self.assertEqual(sett["cmd"][0], "/x/whisper-cli.exe")
        self.assertTrue(sett["cmd"][1].startswith("@tmp-akasha-protokoll-"))
        self.assertIn("Åsa Öberg\n".encode("utf-8"), sett["fil"])
        self.assertNotIn(b"\r", sett["fil"])


class TestStadaKvarglomda(unittest.TestCase):
    def setUp(self):
        self.bas = tempfile.mkdtemp(prefix="akasha-stada-")
        self.addCleanup(shutil.rmtree, self.bas, True)

    def mapp(self, namn, *fil):
        s = os.path.join(self.bas, namn)
        os.makedirs(s)
        for f in fil:
            with open(os.path.join(s, f), "w") as h:
                h.write("x")
        return s

    def test_tar_bara_kataloger_med_ratt_prefix(self):
        a = self.mapp("tmp-akasha-protokoll-aaaa", "ljud.wav", "args.txt")
        os.makedirs(os.path.join(a, "under"))
        b = self.mapp("tmp-akasha-protokoll-bbbb")
        kvar = [self.mapp("kb-whisper-medium-ggml", "ggml-model.bin"), self.mapp("akasha-protokoll-cccc", "x"),
                self.mapp("Tmp-akasha-protokoll-dddd", "x"), self.mapp("tmp-akasha-protokollx", "x"),
                self.mapp("annat", "x")]
        fil = os.path.join(self.bas, "tmp-akasha-protokoll-fil")  # en fil, ingen katalog
        with open(fil, "w") as h:
            h.write("x")
        inre = self.mapp("annat2")
        djupt = os.path.join(inre, "tmp-akasha-protokoll-djupt")  # bara en niva ner
        os.makedirs(djupt)
        with self.assertLogs("akasha-protokoll", "INFO"):
            self.assertEqual(motor.stada_kvarglomda(self.bas), 2)
        self.assertFalse(os.path.exists(a) or os.path.exists(b))
        for k in kvar + [fil, djupt]:
            self.assertTrue(os.path.exists(k), k)

    def test_foljer_inte_symbolisk_lank_ut_ur_katalogen(self):
        utanfor = tempfile.mkdtemp(prefix="akasha-utanfor-")
        self.addCleanup(shutil.rmtree, utanfor, True)
        with open(os.path.join(utanfor, "viktig.txt"), "w") as h:
            h.write("x")
        lank = os.path.join(self.bas, "tmp-akasha-protokoll-lank")
        try:
            os.symlink(utanfor, lank, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("kan inte skapa symboliska lankar har")
        # och en riktig tmp-katalog med en lank inuti som pekar ut
        riktig = self.mapp("tmp-akasha-protokoll-riktig")
        os.symlink(utanfor, os.path.join(riktig, "lank-inuti"), target_is_directory=True)
        self.assertEqual(motor.stada_kvarglomda(self.bas), 1)
        self.assertTrue(os.path.islink(lank))
        self.assertFalse(os.path.exists(riktig))
        self.assertTrue(os.path.exists(os.path.join(utanfor, "viktig.txt")))

    def test_saknad_katalog_och_fel_kastar_inte(self):
        self.assertEqual(motor.stada_kvarglomda(os.path.join(self.bas, "finns-inte")), 0)
        self.mapp("tmp-akasha-protokoll-x")
        with mock.patch.object(motor.shutil, "rmtree", side_effect=PermissionError("last")), \
             self.assertLogs("akasha-protokoll", "WARNING"):
            self.assertEqual(motor.stada_kvarglomda(self.bas), 0)

    def test_forbered_stadar_modellkatalogen(self):
        import app as akasha
        with mock.patch.object(motor, "stada_kvarglomda") as stada, \
             mock.patch.object(akasha, "starta_arbetare"), \
             mock.patch.object(akasha.lagring, "aterstall_avbrutna"):
            akasha.forbered()
        stada.assert_called_once_with()


class TestModellnamn(unittest.TestCase):
    def test_metal_bara_pa_mac(self):
        with mock.patch.object(motor, "AKTIV", "whispercpp"):
            for system, text in (("Darwin", "KB-Whisper medium (whisper.cpp, Metal)"),
                                 ("Windows", "KB-Whisper medium (whisper.cpp)"),
                                 ("Linux", "KB-Whisper medium (whisper.cpp)")):
                with mock.patch.object(plattform, "system", lambda: system):
                    self.assertEqual(motor.modellnamn(), text)
        with mock.patch.object(motor, "AKTIV", "faster"):
            self.assertEqual(motor.modellnamn(), "KB-Whisper medium")


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
