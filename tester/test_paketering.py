"""Snabba kontroller av paketeringen: gar pa alla system och kraver varken PyInstaller eller PyObjC."""
import ast
import glob
import os
import importlib.util
import io
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import unittest
from unittest import mock

import hjalp
import start

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROT, "app")
PAKETERING = os.path.join(ROT, "paketering")


def las(*delar):
    with open(os.path.join(ROT, *delar), encoding="utf-8") as f:
        return f.read()


class Paketering(unittest.TestCase):
    def test_filerna_gar_att_kompilera(self):
        for delar in (("app", "mac_app.py"), ("app", "windows_app.py"), ("paketering", "akasha-protokoll.spec"), ("paketering", "kontrollera.py")):
            compile(las(*delar), "/".join(delar), "exec")  # inte importerad: PyObjC finns bara pa Mac

    def test_typsnitten_stilmallen_pekar_pa_finns_med_sina_licenser(self):
        stil = las("app", "static", "stil.css")
        filer = re.findall(r'url\("(typsnitt/[^"]+)"\)', stil)
        self.assertEqual(len(filer), 3)
        for fil in filer:
            self.assertTrue(os.path.isfile(os.path.join(APP, "static", fil)), fil)
        for licens in ("OFL-Anton.txt", "OFL-Instrument-Sans.txt"):
            text = las("app", "static", "typsnitt", licens)
            self.assertIn("SIL OPEN FONT LICENSE Version 1.1", text)
        self.assertIn("*.woff2 binary", las(".gitattributes"))

    def test_byggkraven_ar_last_till_exakta_versioner(self):
        rader = [r.strip() for r in las("paketering", "krav-bygg.txt").splitlines()]
        rader = [r for r in rader if r and not r.startswith("#")]
        self.assertTrue(rader)
        for r in rader:
            self.assertIn("==", r)

    def test_appens_krav_har_av_och_truststore(self):
        krav = las("app", "requirements.txt")
        self.assertRegex(krav, r"(?m)^av==")
        self.assertRegex(krav, r"(?m)^truststore==")

    def test_frozen_och_meipass_finns_bara_i_plattform(self):
        for sokvag in glob.glob(os.path.join(APP, "*.py")):
            if os.path.basename(sokvag) == "plattform.py":
                continue
            text = las("app", os.path.basename(sokvag))
            for ord_ in ("sys.frozen", "_MEIPASS", '"frozen"'):
                self.assertNotIn(ord_, text, f"{ord_} i {os.path.basename(sokvag)}")

    def test_faster_whisper_importeras_bara_i_motor_och_dar_bara_i_faster(self):
        monster = re.compile(r"^(\s*)(import faster_whisper|from faster_whisper)", re.M)
        for sokvag in glob.glob(os.path.join(APP, "*.py")):
            namn = os.path.basename(sokvag)
            traffar = list(monster.finditer(las("app", namn)))
            if namn != "motor.py":
                self.assertEqual(traffar, [], f"faster_whisper importeras i {namn}")
                continue
            self.assertTrue(traffar)
            for t in traffar:
                self.assertTrue(t.group(1), "faster_whisper importeras pa modulnivan i motor.py")
            # och inne i _faster(): ingen annan funktion far importera den
            tradet = ast.parse(las("app", namn))
            for nod in ast.walk(tradet):
                if isinstance(nod, (ast.FunctionDef, ast.AsyncFunctionDef)) and nod.name != "_faster":
                    for under in ast.walk(nod):
                        if isinstance(under, ast.Import):
                            self.assertFalse(any(a.name.startswith("faster_whisper") for a in under.names), nod.name)
                        if isinstance(under, ast.ImportFrom):
                            self.assertFalse((under.module or "").startswith("faster_whisper"), nod.name)

    def test_start_har_texterna_i_b2_och_b7_ordagrant(self):
        self.assertEqual(start.TA_OVER_RUBRIK, "Akasha Protokoll är redan installerat från Terminal")
        self.assertEqual(
            start.TA_OVER_TEXT,
            "Den gamla installationen är igång i bakgrunden och använder samma adress. Programmet kan ta över: "
            "den gamla stängs av och startar inte längre när du loggar in. Inspelningar och modeller ligger "
            "kvar och används av programmet.\n\n"
            "Vill du ha tillbaka den gamla senare kör du bash mac/installera.sh i Terminal igen.")
        self.assertEqual((start.TA_OVER_JA, start.TA_OVER_NEJ), ("Använd programmet", "Avbryt"))
        self.assertEqual(start.TA_OVER_MISSLYCKADES_RUBRIK, "Den gamla installationen gick inte att stänga av")
        self.assertEqual(start.TA_OVER_MISSLYCKADES_TEXT,
                         "Kör bash mac/avinstallera.sh i Terminal och öppna sedan Akasha Protokoll igen.")
        self.assertEqual(start.UPPTAGEN_RUBRIK, "Akasha Protokoll kan inte starta")
        self.assertEqual(
            start.UPPTAGEN_TEXT,
            "Ett annat program använder redan port {port}, som Akasha Protokoll behöver. Avsluta det programmet "
            "och öppna Akasha Protokoll igen. Du kan också välja en annan port med raden PORT= i inställningsfilen:\n{fil}")
        self.assertEqual(start.STARTADE_INTE_RUBRIK, "Akasha Protokoll startade inte")
        self.assertEqual(start.STARTADE_INTE_TEXT,
                         "Något gick fel när Akasha Protokoll startade. Det som hände står i loggen:\n{logg}")
        self.assertEqual(start.VISA_LOGGEN, "Visa loggen")
        self.assertEqual(start.OK, "OK")
        self.assertEqual(start.INSTALLNINGSFEL_RUBRIK, "Inställningsfilen har fel")
        self.assertEqual(
            start.INSTALLNINGSFEL_TEXT,
            "Akasha Protokoll startar ändå och använder standardvärdet för det som inte gick att läsa:\n{problem}"
            "\n\nFilen:\n{fil}")
        self.assertEqual(start.VISA_FILEN, "Visa filen")
        self.assertEqual(start.AVSLUTA_RUBRIK, "Vill du avsluta Akasha Protokoll?")
        self.assertEqual(start.AVSLUTA_INLEDNING, {"inspelning": "en inspelning tas emot",
                                                   "transkribering": "en transkribering pågår",
                                                   "hamtning": "modellerna hämtas"})
        self.assertEqual(start.AVSLUTA_MENING, {
            "inspelning": "Inspelningen fortsätter i webbläsaren, och ljudet sparas i fliken tills du öppnar "
                          "Akasha Protokoll igen. Stäng inte fliken.",
            "transkribering": "Transkriberingen avbryts. Du kan göra om den med Försök igen när du har öppnat "
                              "Akasha Protokoll igen.",
            "hamtning": "Hämtningen av modellerna stoppas. Det som redan är hämtat ligger kvar, och nästa gång "
                        "fortsätter den där den slutade."})
        self.assertEqual((start.AVSLUTA_NEJ, start.AVSLUTA_JA), ("Avbryt", "Avsluta ändå"))

    def test_start_har_texterna_for_windows_skalet_ordagrant(self):
        self.assertEqual(start.WIN_AVSLUTA_FRAGA, "Vill du avsluta ändå?")
        self.assertEqual(start.WIN_VISA_LOGGEN_FRAGA, "Vill du öppna mappen med loggen?")
        self.assertEqual(start.WIN_VISA_FILEN_FRAGA, "Vill du öppna mappen med inställningsfilen?")
        self.assertEqual(start.STARTAR_REDAN_RUBRIK, "Akasha Protokoll startar redan")
        self.assertEqual(
            start.STARTAR_REDAN_TEXT,
            "Akasha Protokoll håller redan på att starta men svarar inte. Vänta en stund och försök igen. "
            "Hjälper det inte, starta om datorn.")
        self.assertEqual(start.WIN_IGANG, "Akasha Protokoll är igång. Du hittar det bland ikonerna vid klockan.")
        self.assertEqual(start.WIN_TIPS_STARTAR, "Akasha Protokoll startar\u2026")
        self.assertEqual(start.WIN_TIPS_IGANG, "Akasha Protokoll är igång")
        self.assertEqual(start.WIN_MENY_OPPNA, "Öppna Akasha Protokoll i webbläsaren")
        self.assertEqual(start.WIN_MENY_AVSLUTA, "Avsluta Akasha Protokoll")

    def test_mac_app_importerar_inget_som_laser_installningar_pa_modulnivan(self):
        trad = ast.parse(las("app", "mac_app.py"))
        importerade = set()
        for nod in trad.body:  # bara toppnivan: importer inne i funktioner ar tillatna
            if isinstance(nod, ast.Import):
                importerade.update(a.name.split(".")[0] for a in nod.names)
            elif isinstance(nod, ast.ImportFrom):
                importerade.add((nod.module or "").split(".")[0])
        self.assertTrue({"AppKit", "plattform", "start"} <= importerade)
        for namn in ("installningar", "app", "lagring", "modeller", "motor", "talare"):
            self.assertNotIn(namn, importerade)

    def test_mac_app_har_inga_dialogtexter(self):
        # Dialogtexterna ligger i start.py. Menyrubrikerna (B3) ar de enda svenska texterna har.
        text = las("app", "mac_app.py")
        for konstant in ("Vill du avsluta", "Inställningsfilen har fel", "Använd programmet", "Akasha Protokoll startade inte"):
            self.assertNotIn(konstant, text)

    def test_specen_har_info_plist_med_principalklass_och_ad_hoc(self):
        spec = las("paketering", "akasha-protokoll.spec")
        self.assertIn("NSPrincipalClass", spec)
        self.assertIn('"LSMinimumSystemVersion": "14.0"', spec)
        self.assertIn("codesign_identity=None", spec)
        self.assertIn("faster_whisper", spec)  # i excludes

    def delegatens_metoder(self):
        trad = ast.parse(las("app", "mac_app.py"))
        klass = next(n for n in trad.body if isinstance(n, ast.ClassDef) and n.name == "Delegat")
        return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}

    def test_delegat_init_anvander_objc_super(self):
        init = self.delegatens_metoder()["init"]
        anrop = [n for n in ast.walk(init) if isinstance(n, ast.Call)]
        # objc.super(Delegat, self)
        objc_super = [n for n in anrop if isinstance(n.func, ast.Attribute) and n.func.attr == "super"
                      and isinstance(n.func.value, ast.Name) and n.func.value.id == "objc"]
        self.assertEqual(len(objc_super), 1)
        self.assertEqual([getattr(a, "id", None) for a in objc_super[0].args], ["Delegat", "self"])
        # inget super() utan argument
        self.assertEqual([n for n in anrop if isinstance(n.func, ast.Name) and n.func.id == "super"], [])

    def test_metoder_som_cocoa_anropar_har_try_utanfor_allt(self):
        metoder = self.delegatens_metoder()
        for namn in ("applicationDidFinishLaunching_", "applicationShouldHandleReopen_hasVisibleWindows_",
                     "applicationDockMenu_", "applicationShouldTerminate_", "applicationWillTerminate_",
                     "oppna_", "startad", "startfel"):
            with self.subTest(namn):
                kropp = metoder[namn].body
                if isinstance(kropp[0], ast.Expr) and isinstance(getattr(kropp[0], "value", None), ast.Constant) \
                        and isinstance(kropp[0].value.value, str):
                    kropp = kropp[1:]  # docstring
                self.assertEqual(len(kropp), 1, f"{namn} ska bara ha ett try som yttersta sats")
                self.assertIsInstance(kropp[0], ast.Try)
                self.assertTrue(any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
                                    for h in kropp[0].handlers), f"{namn} saknar except Exception")

    def test_mac_app_har_loggraderna_for_mac_korningen(self):
        text = las("app", "mac_app.py")
        for rad in ("mac: startar", "mac: beslut %s", "mac: tjansten svarar, oppnar webblasaren",
                    "mac: tjansten svarade inte inom 30 s", "mac: avslutar", "mac: applicationWillTerminate"):
            self.assertIn(f'"{rad}"', text)


WINDOWS_PY = ("kontroll_hjalp.py", "kontrollera_pe.py", "kontrollera_whisper_cli_windows.py", "kontrollera_windows.py",
              "bygg_windows_verktyg.py", "bygg_installation.py", "kontrollera_installation.py", "kontrollsummor.py")
WINDOWS_SH = ("bygg-whisper-cli-windows.sh", "samla-whisper-cli-windows.sh", "bygg-windows.sh")


def kommentarer(delar):
    """Kommentartexterna i en fil: tokenize for .py, annars allt efter ett # som borjar ett ord (sh, yml, spec)."""
    text = las(*delar)
    if delar[-1].endswith(".py") or delar[-1].endswith(".spec"):
        return [t.string for t in tokenize.generate_tokens(io.StringIO(text).readline) if t.type == tokenize.COMMENT]
    return re.findall(r"(?:^|\s)#(?!\{|!).*", text, re.M)


class WindowsBygget(unittest.TestCase):
    def test_skripten_gar_att_tolka(self):
        for namn in WINDOWS_PY:
            compile(las("paketering", namn), namn, "exec")
        # Inte pa Windows: subprocess hittar dar C:\\Windows\\System32\\bash.exe (WSL-startaren) fore Git Bash. Linux-jobbet tacker det.
        if os.name != "nt" and shutil.which("bash"):
            for namn in WINDOWS_SH:
                p = subprocess.run(["bash", "-n", os.path.join(PAKETERING, namn)], capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, f"{namn}: {p.stderr}")

    def test_inga_msys_sokvagar_till_windows_program_i_skripten(self):
        # Med MSYS_NO_PATHCONV=1 gar $ROT, $(pwd) och $PWD (som ger /d/a/...) oforandrade till python.exe, cmake och git,
        # som inte forstar dem. Skripten gar till repots rot med cd och anvander relativa sokvagar (eller pwd -W).
        for namn in WINDOWS_SH:
            for rad in las("paketering", namn).splitlines():
                kod = rad.split(" #")[0] if not rad.lstrip().startswith("#") else ""
                if "$ROT" in kod or "${ROT}" in kod:
                    self.assertTrue(kod.startswith("ROT=") or kod.strip() == 'cd "$ROT"', f"{namn}: {rad}")
                self.assertNotIn("$PWD", kod, f"{namn}: {rad}")
                if "$(pwd" in kod or "`pwd" in kod:
                    self.assertTrue(kod.startswith("ROT=") or kod.startswith("winsokvag()"), f"{namn}: {rad}")
        for namn in ("bygg-whisper-cli-windows.sh", "samla-whisper-cli-windows.sh"):
            text = las("paketering", namn)
            self.assertIn('cd "$(dirname "$0")/.."', text)
            self.assertIn('"$PYTHON" "paketering/', text)
        flode = las(".github", "workflows", "windows-app.yml")
        self.assertNotIn("$(pwd)", flode)
        self.assertNotIn("$PWD", flode)

    def test_bygget_av_whisper_cli_tar_inte_med_parakeet(self):
        text = las("paketering", "bygg-whisper-cli-windows.sh")
        self.assertIn('cp "$BIN_KAT"/whisper.dll "$BIN_KAT"/ggml*.dll', text)
        self.assertNotIn('"$BIN_KAT"/*.dll', text)

    def test_kommentarerna_i_windows_filerna_har_inga_aao(self):
        filer = [("paketering", n) for n in WINDOWS_PY + WINDOWS_SH] + [("paketering", "akasha-protokoll.spec")]
        for delar in filer + [("tester", "falsk_whisper_cli.py"), ("tester", "test_windows_bygg.py"),
                               ("tester", "falsk_sherpa", "sherpa_onnx", "__init__.py")]:
            for kommentar in kommentarer(delar):
                self.assertIsNone(re.search("[åäöÅÄÖ]", kommentar), f"{'/'.join(delar)}: {kommentar}")

    def test_commiten_for_whisper_cpp_ar_densamma_for_mac_och_windows(self):
        mac = re.search(r"v1\.9\.5\) VANTAD=([0-9a-f]{40})", las("paketering", "bygg-whisper-cli.sh"))
        win = re.search(r"v1\.9\.5\) VANTAD=([0-9a-f]{40})", las("paketering", "bygg-whisper-cli-windows.sh"))
        self.assertTrue(mac and win)
        self.assertEqual(mac.group(1), win.group(1))
        self.assertEqual(win.group(1), "d1be6fde11ac6e0407606b4e42fe72d34add8037")

    def test_bygget_av_whisper_cli_anvander_whisper_cpps_egna_windowsflaggor(self):
        text = las("paketering", "bygg-whisper-cli-windows.sh")
        for flagga in ("-A x64", "-DBUILD_SHARED_LIBS=ON", "-DGGML_NATIVE=OFF", "-DGGML_BACKEND_DL=ON",
                       "-DGGML_CPU_ALL_VARIANTS=ON", "-DWHISPER_SDL2=OFF", "-DWHISPER_BUILD_TESTS=OFF",
                       "-DWHISPER_BUILD_SERVER=OFF", "-DWHISPER_CURL=OFF"):
            self.assertIn(flagga, text)
        bygg = [r for r in text.splitlines() if r.startswith("cmake --build")]
        self.assertEqual(len(bygg), 1)
        self.assertNotIn("--target", bygg[0])  # alla standardmal, inga gissade malnamn

    def test_kontrollen_av_whisper_cli_har_samma_testmodell_som_mac(self):
        mac = las("paketering", "kontrollera-whisper-cli.sh")
        win = las("paketering", "kontrollera_whisper_cli_windows.py")
        for rad in ("5359861c739e955e79d9a303bcbc70fb988958b1", "818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7"):
            self.assertIn(rad, mac)
            self.assertIn(rad, win)

    def test_kontrollen_hamtar_aldrig_kb_whisper(self):
        for namn in WINDOWS_PY:
            text = las("paketering", namn)
            self.assertNotIn("KBLab", text)
            self.assertNotIn("kb-whisper-medium/resolve", text)

    def kor_spec(self, plattform, miljo):
        """Kor spec-filen med falska PyInstaller-klasser och en annan sys.platform -> {klassnamn: (args, kwargs)}."""
        anrop = {}

        def falsk(namn):
            def f(*a, **kw):
                anrop[namn] = (a, kw)
                return mock.MagicMock(pure=[], scripts=[], binaries=[], datas=[])
            return f

        mapp = tempfile.mkdtemp(prefix="akasha-spec-")
        self.addCleanup(shutil.rmtree, mapp, True)
        ns = {n: falsk(n) for n in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE")}
        ns.update(SPECPATH=PAKETERING, workpath=os.path.join(mapp, "pyi"), DISTPATH=mapp)
        miljo = {"AKASHA_WHISPER_CLI": "", "AKASHA_WHISPER_KATALOG": "", "AKASHA_IKON": "", "AKASHA_VERSIONSFIL": "", **miljo}
        with mock.patch.object(sys, "platform", plattform), mock.patch.dict(os.environ, miljo):
            exec(compile(las("paketering", "akasha-protokoll.spec"), "spec", "exec"), ns)
        return anrop

    def whisper_katalog(self):
        mapp = tempfile.mkdtemp(prefix="akasha-whisper-")
        self.addCleanup(shutil.rmtree, mapp, True)
        for namn in ("whisper-cli.exe", "whisper.dll", "ggml-cpu-haswell.dll"):
            with open(os.path.join(mapp, namn), "wb") as f:
                f.write(b"x")
        return mapp

    def test_spec_linux_ar_som_forut(self):
        a, e, c = (self.kor_spec("linux", {})[k] for k in ("Analysis", "EXE", "COLLECT"))
        self.assertEqual(os.path.basename(a[0][0][0]), "start.py")
        self.assertEqual(a[1]["binaries"], [])
        self.assertEqual(a[1]["datas"], [(os.path.join(APP, "static"), "static")])
        self.assertNotIn("module_collection_mode", a[1])
        self.assertTrue(e[1]["console"])
        self.assertNotIn("icon", e[1])
        self.assertEqual((e[1]["name"], c[1]["name"]), ("akasha-protokoll", "akasha-protokoll"))

    def test_spec_mac_ar_som_forut(self):
        k = self.kor_spec("darwin", {"AKASHA_WHISPER_CLI": "/x/whisper-cli", "AKASHA_IKON": "/x/ikon.icns"})
        a, e = k["Analysis"], k["EXE"]
        self.assertEqual(os.path.basename(a[0][0][0]), "mac_app.py")
        self.assertEqual(a[1]["binaries"], [("/x/whisper-cli", ".")])
        self.assertFalse(e[1]["console"])
        self.assertEqual(e[1]["target_arch"], "arm64")
        self.assertEqual(k["BUNDLE"][1]["name"], "Akasha Protokoll.app")
        self.assertNotIn("icon", e[1])
        with self.assertRaises(SystemExit):
            self.kor_spec("darwin", {})

    def test_spec_windows(self):
        kat = self.whisper_katalog()
        k = self.kor_spec("win32", {"AKASHA_WHISPER_KATALOG": kat, "AKASHA_IKON": "C:/b/ikon.ico",
                                    "AKASHA_VERSIONSFIL": "C:/b/versionsfil.txt"})
        a, e, c = k["Analysis"], k["EXE"], k["COLLECT"]
        self.assertEqual(os.path.basename(a[0][0][0]), "windows_app.py")
        self.assertEqual(sorted((os.path.basename(f), d) for f, d in a[1]["binaries"]),
                         [("ggml-cpu-haswell.dll", "whisper"), ("whisper-cli.exe", "whisper"), ("whisper.dll", "whisper")])
        self.assertEqual([d for _, d in a[1]["datas"]], ["static", "."])
        self.assertEqual(os.path.basename(a[1]["datas"][1][0]), "ikon.png")
        self.assertTrue(os.path.isfile(a[1]["datas"][1][0]))
        for modul in ("pystray", "pystray._win32", "PIL.Image"):
            self.assertIn(modul, a[1]["hiddenimports"])
        self.assertEqual(a[1]["module_collection_mode"], {"pystray": "py"})  # LGPL: kallkoden ska ga att byta ut
        for modul in ("faster_whisper", "ctranslate2", "onnxruntime", "tkinter"):
            self.assertIn(modul, a[1]["excludes"])
        self.assertFalse(e[1]["console"])
        self.assertEqual((e[1]["icon"], e[1]["version"]), ("C:/b/ikon.ico", "C:/b/versionsfil.txt"))
        self.assertEqual((e[1]["name"], c[1]["name"]), ("Akasha Protokoll", "Akasha Protokoll"))
        self.assertNotIn("BUNDLE", k)

    def test_spec_windows_stoppar_utan_whisper_katalog_men_inte_utan_whisper_cli(self):
        with self.assertRaises(SystemExit) as fel:
            self.kor_spec("win32", {})
        self.assertIn("AKASHA_WHISPER_KATALOG", str(fel.exception))
        tom = tempfile.mkdtemp(prefix="akasha-whisper-")
        self.addCleanup(shutil.rmtree, tom, True)
        with mock.patch("builtins.print"):
            k = self.kor_spec("win32", {"AKASHA_WHISPER_KATALOG": tom})
        self.assertEqual(k["Analysis"][1]["binaries"], [])  # bygger anda: bygg-windows.sh stoppar med FEL sedan

    def test_windows_byggkraven_finns_med_win32_markor(self):
        krav = las("paketering", "krav-bygg.txt")
        for rad in ("pystray==0.19.5", "pillow==13.0.0", "six==1.17.0", "pefile==2024.8.26", "pywin32-ctypes==0.2.3"):
            self.assertIn(rad + '; sys_platform == "win32"', krav)

    def test_bygg_windows_sh_gor_det_planen_sager(self):
        text = las("paketering", "bygg-windows.sh")
        for stycke in ("bygg_windows_verktyg.py", "ikon-1024.png", "-m PyInstaller", "akasha-protokoll.spec", "kontrollera_pe.py",
                       "forbjudet", "exeinfo", "storlekar", "Akasha-Protokoll-windows-x64.zip", "pyinstaller.log",
                       "build/uppackad/Åsa Ölund", "_internal/whisper/whisper-cli.exe", "ggml-cpu-*.dll"):
            self.assertIn(stycke, text)
        self.assertNotIn("sys.frozen", text)
        # kontrollerna stoppar inte vid forsta felet: de gar genom fel(), och skriptet slutar med slutkod 1
        self.assertGreaterEqual(text.count("|| fel "), 4)
        self.assertIn('exit 1\nfi\necho "OK: bygget klart', text)


class Installationsfilen(unittest.TestCase):
    """Statiska kontroller av paketering/akasha-protokoll.iss (Inno Setup finns bara pa Windows-maskinen i Actions)."""

    def iss(self):
        with open(os.path.join(PAKETERING, "akasha-protokoll.iss"), "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"), "UTF-8 med BOM, annars laser Inno Setup a, a, o fel")
        return data.decode("utf-8-sig")

    def sektion(self, namn):
        text = self.iss()
        delar = re.split(r"(?m)^\[(\w+)\]\s*$", text)
        return dict(zip(delar[1::2], delar[2::2]))[namn]

    def test_texterna_ordagrant(self):
        text = self.iss()
        self.assertIn('Description: "Skapa en genväg på skrivbordet"; Flags: unchecked', text)  # av som standard
        self.assertIn('Description: "Starta Akasha Protokoll"; Flags: nowait postinstall skipifsilent', text)
        self.assertIn("SuppressibleMsgBox('Dina inspelningar ligger kvar i mappen AkashaProtokoll i din hemkatalog, och "
                      "modellerna i %LOCALAPPDATA%\\Akasha Protokoll. Ta bort dem själv om du inte vill ha dem.', mbInformation, "
                      "MB_OK, IDOK)", text)
        self.assertIn("CurUninstallStep = usPostUninstall", text)
        self.assertIn("LicenseLabel=Läs licensen nedan innan du fortsätter. Andra delar av programmet har egna licenser.", text)
        self.assertIn('Name: "sv"', text)
        self.assertIn("Name: \"{autoprograms}\\{#Namn}\"", text)  # genvagen i Start-menyn heter Akasha Protokoll
        self.assertIn('#define Namn "Akasha Protokoll"', text)

    def test_per_anvandare_utan_administratorsratt(self):
        text = self.iss()
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertNotIn("PrivilegesRequired=admin", text)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\{#Namn}", text)
        self.assertNotIn("{pf", text)
        self.assertNotIn("{commonappdata}", text)
        self.assertNotIn("HKLM", text)

    def test_mutexen_ar_samma_som_programmets_och_programmet_stangs_inte(self):
        text = self.iss()
        mutex = re.search(r'MUTEX = "(.+?)"', las("app", "windows_app.py")).group(1).replace("\\\\", "\\")
        self.assertEqual(mutex, "Local\\AkashaProtokoll")
        self.assertIn(f"AppMutex={mutex}", text)
        self.assertIn("CloseApplications=no", text)

    def test_licensen_finns_och_licenser_txt_namns_inte(self):
        text = self.iss()
        self.assertIn("LicenseFile=..\\LICENSE", text)
        self.assertTrue(os.path.isfile(os.path.join(ROT, "LICENSE")))
        self.assertNotIn("LICENSER", text)  # filen finns inte an

    def test_inga_sokvagar_fran_byggmaskinen(self):
        text = self.iss()
        self.assertIsNone(re.search(r"(?i)\b[a-z]:\\", text), "en enhetsbokstav i skriptet")
        self.assertNotIn("runner", text.lower())
        self.assertNotIn("/home/", text)

    def test_avinstallationen_ror_inte_anvandarens_data(self):
        borta = self.sektion("UninstallDelete").strip().splitlines()
        poster = [r for r in borta if r.strip() and not r.startswith(";")]
        # bara PyInstallers eget (_internal): {app} ensam far aldrig tas bort med allt innehall (en katalog med andras filer)
        self.assertEqual(poster, ['Type: filesandordirs; Name: "{app}\\_internal"'])
        self.assertIsNone(re.search(r"\{app\}(?!\\_internal)", "\n".join(poster)))  # aldrig {app} ensam
        self.assertIn("DisableDirPage=yes", self.iss())  # ingen katalogsida: alltid Programs\\Akasha Protokoll
        text = self.iss()
        self.assertNotIn("{userdocs}", text)
        self.assertNotIn("{%USERPROFILE}", text)
        for ord_ in ("AkashaProtokoll\\", "{localappdata}\\Akasha Protokoll"):
            for sektion in ("Files", "Icons", "Run", "UninstallDelete", "Setup"):
                self.assertNotIn(ord_, self.sektion(sektion))
        # {app} (Programs\\Akasha Protokoll) ar inte %LOCALAPPDATA%\\Akasha Protokoll (log, modeller, installningar)
        self.assertIn("{localappdata}\\Programs\\{#Namn}", text)

    def test_versionen_och_upphovsratten_som_i_versionsresursen(self):
        import bygg_windows_verktyg as v
        text = self.iss()
        self.assertIn(f"AppCopyright={v.UPPHOVSRATT}", text)
        self.assertIn(f"VersionInfoCopyright={v.UPPHOVSRATT}", text)
        self.assertNotIn("AppPublisher", text)  # utgivare i applistan ar inte godkand av agaren
        self.assertIn("OutputBaseFilename=Akasha-Protokoll-installation", text)
        self.assertIn("{#Namn}", text)
        self.assertEqual(v.NAMN, "Akasha Protokoll")
        import kontrollera_installation as k
        self.assertIn("AppId={" + k.APPID, text)  # AppId={{GUID} i Inno Setup: dubbla { ar ett enda {

    def test_kommentarerna_i_iss_har_inga_aao(self):
        for rad in self.iss().splitlines():
            if rad.startswith(";"):
                self.assertIsNone(re.search("[åäöÅÄÖ]", rad), rad)

    def test_kontrollen_av_installationen_kor_bara_i_actions_och_provar_framand_fil(self):
        import kontrollera_installation as k
        self.assertTrue(k.ar_actions({"GITHUB_ACTIONS": "true"}))
        for miljo in ({}, {"GITHUB_ACTIONS": "false"}, {"GITHUB_ACTIONS": ""}):
            self.assertFalse(k.ar_actions(miljo))
        miljo = {n: v for n, v in os.environ.items() if n != "GITHUB_ACTIONS"}
        with mock.patch.dict(os.environ, miljo, clear=True), mock.patch("builtins.print") as skriv:
            self.assertEqual(k.main(["--installation", "x.exe", "--katalog", "k", "--hem", "h", "--version", "0.2.0.1"]), 1)
        text = " ".join(str(a[0][0]) for a in skriv.call_args_list)
        self.assertIn("bara i GitHub Actions", text)
        self.assertIn("ingen flagga", text)
        kallkod = las("paketering", "kontrollera_installation.py")
        self.assertNotIn("--tvinga", kallkod)
        for stycke in ("inte-var-fil.txt", "den framande filen", "_internal ar borta"):
            self.assertIn(stycke, kallkod)

    def test_mutexprovet_raknar_varje_http_svar_som_att_programmet_kor(self):
        import urllib.error
        import kontrollera_installation as k

        class Levande:
            def poll(self):
                return None

        class Dod:
            def poll(self):
                return 1

        def fel(kod):
            return urllib.error.HTTPError("http://x/health", kod, "x", {}, None)

        def oppna_med(handelser):
            kvar = list(handelser)

            def oppna(url):
                h = kvar.pop(0)
                if isinstance(h, BaseException):
                    raise h
                return h
            return oppna

        class Svar:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        vila = lambda s: None  # noqa: E731
        # 503 (modellerna saknas) raknas som igang, utan att vanta
        self.assertEqual(k.vanta_pa_svar("u", Levande(), 5, oppna_med([fel(503)]), vila), 503)
        self.assertEqual(k.vanta_pa_svar("u", Levande(), 5, oppna_med([Svar()]), vila), 200)
        # anslutningsfel (porten inte oppen an) vantas ut, sedan ett svar
        self.assertEqual(k.vanta_pa_svar("u", Levande(), 5, oppna_med([ConnectionRefusedError(), OSError(), fel(404)]), vila), 404)
        # programmet har avslutats: inget svar, ingen vantan
        self.assertIsNone(k.vanta_pa_svar("u", Dod(), 5, oppna_med([]), vila))
        # tiden gar ut
        self.assertIsNone(k.vanta_pa_svar("u", Levande(), 0, oppna_med([]), vila))
        self.assertIn("sista raderna ur loggen", las("paketering", "kontrollera_installation.py"))

    def test_bygget_hittar_iscc_och_skriver_versionen(self):
        import bygg_installation as b
        funna, sokt = b.hitta_iscc({"ProgramFiles(x86)": "P86", "ProgramFiles": "P"}, finns=lambda s: s == os.path.join("P", "Inno Setup 6", "ISCC.exe"),
                                   which=lambda n: None)
        self.assertEqual(funna, os.path.join("P", "Inno Setup 6", "ISCC.exe"))
        self.assertEqual(sokt[0], os.path.join("P86", "Inno Setup 6", "ISCC.exe"))  # Program Files (x86) forst
        saknas, sokt = b.hitta_iscc({}, finns=lambda s: False, which=lambda n: None)
        self.assertIsNone(saknas)
        self.assertTrue(sokt)
        pa_path, _ = b.hitta_iscc({}, finns=lambda s: s == "/x/ISCC", which=lambda n: "/x/ISCC")
        self.assertEqual(pa_path, "/x/ISCC")
        self.assertEqual(b.versionsrad("Inno Setup 6 Command-Line Compiler\nCopyright (C) ...\n"), "Inno Setup 6 Command-Line Compiler")

    def test_inno_setup_kommandoraden_har_citattecken_runt_sokvagar_med_mellanslag(self):
        import kontrollera_installation as k
        rad = k.kommandorad("C:\\x y\\Setup.exe", k.TYSTA + ["/CURRENTUSER"], DIR="C:\\Åsa Ölund\\Akasha Protokoll", LOG="C:\\l.log")
        self.assertEqual(rad, '"C:\\x y\\Setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER '
                              '/DIR="C:\\Åsa Ölund\\Akasha Protokoll" /LOG="C:\\l.log"')

    def test_kontrollsummorna_har_sha256sum_format(self):
        import hashlib
        import kontrollsummor as ks
        mapp = tempfile.mkdtemp(prefix="akasha-summor-")
        self.addCleanup(shutil.rmtree, mapp, True)
        a, b = os.path.join(mapp, "Åsa zip.zip"), os.path.join(mapp, "inst.exe")
        for f, data in ((a, b"abc"), (b, b"")):
            with open(f, "wb") as h:
                h.write(data)
        rader, saknas = ks.rader([a, b, os.path.join(mapp, "finns-inte")])
        self.assertEqual(rader, [hashlib.sha256(b"abc").hexdigest() + "  Åsa zip.zip", hashlib.sha256(b"").hexdigest() + "  inst.exe"])
        self.assertEqual(len(saknas), 1)
        ut = os.path.join(mapp, "SHA256SUMS.txt")
        with mock.patch("builtins.print"):
            self.assertEqual(ks.main([ut, a, b]), 0)
            self.assertEqual(ks.main([ut, a, os.path.join(mapp, "saknas")]), 1)  # saknad fil ger FEL men a far sin summa
        with open(ut, encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), hashlib.sha256(b"abc").hexdigest() + "  Åsa zip.zip\n")
        if shutil.which("sha256sum") and os.name != "nt":
            p = subprocess.run(["sha256sum", "-c", ut], cwd=mapp, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class WindowsFlodet(unittest.TestCase):
    """Statiska kontroller av .github/workflows/windows-app.yml (flodet kors bara i Actions)."""
    FLODE = (".github", "workflows", "windows-app.yml")

    def text(self):
        return las(*self.FLODE)

    def yaml(self):
        if importlib.util.find_spec("yaml") is None:
            self.skipTest("PyYAML saknas")
        import yaml
        return yaml.safe_load(self.text())

    def test_yaml_gar_att_lasa(self):
        d = self.yaml()
        self.assertEqual(set(d["jobs"]), {"bygg", "signera"})

    def test_bara_workflow_dispatch(self):
        text = self.text()
        self.assertRegex(text, r"(?m)^on:\n  workflow_dispatch:\n    inputs:\n      whisper_version:")
        for utlosare in ("push:", "pull_request", "schedule:", "workflow_run", "release:", "workflow_call"):
            self.assertNotIn(utlosare, text)
        self.assertIn('default: "v1.9.5"', text)
        if importlib.util.find_spec("yaml"):
            self.assertEqual(list(self.yaml()[True]), ["workflow_dispatch"])  # "on" tolkas som True av YAML 1.1

    def test_inga_hemligheter(self):
        text = self.text()
        self.assertNotIn("secrets", text.lower())
        self.assertNotIn("GITHUB_TOKEN", text)
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read$")

    def test_fast_etikett_tidsgrans_och_skal(self):
        text = self.text()
        self.assertEqual(re.findall(r"runs-on: (\S+)", text), ["windows-2025", "windows-2025"])
        self.assertNotRegex(text, r"runs-on: windows-latest")
        self.assertIn("timeout-minutes: 45", text)
        self.assertRegex(text, r"defaults:\n      run:\n        shell: bash")
        self.assertRegex(text, r"concurrency:\n  group: windows-app")

    def test_teckenkodning_och_git_bash(self):
        text = self.text()
        self.assertIn('PYTHONUTF8: "1"', text)
        self.assertIn("PYTHONIOENCODING: utf-8", text)
        self.assertIn("LANG: C.UTF-8", text)  # Git Bash for over argument med a-ring m.m. som UTF-8
        self.assertIn("LC_ALL: C.UTF-8", text)
        self.assertIn('MSYS_NO_PATHCONV: "1"', text)  # /v till reg och /FI till tasklist skrivs annars om

    def test_samma_versioner_av_atgarderna_som_mac_flodet(self):
        mac = dict(re.findall(r"uses: (\S+)@(\S+)", las(".github", "workflows", "mac-app.yml")))
        win = re.findall(r"uses: (\S+)@(\S+)", self.text())
        self.assertTrue(win)
        for namn, version in win:
            kalla = "actions/cache" if namn.startswith("actions/cache/") else namn
            self.assertIn(kalla, mac, f"{namn} ar en atgard som Mac-flodet inte anvander")
            self.assertEqual(version, mac[kalla], namn)
        self.assertEqual({n for n, _ in win}, {"actions/checkout", "actions/setup-python", "actions/cache/restore",
                                               "actions/cache/save", "actions/upload-artifact"})

    def test_stegen_i_ordning_med_ratt_kommandon(self):
        text = self.text()
        ordning = ["bygg-whisper-cli-windows.sh", "samla-whisper-cli-windows.sh", "kontrollera_whisper_cli_windows.py", "bygg-windows.sh",
                   "paketering/kontrollera.py", "kontrollera_windows.py", "name: Sammanfattning", "name: Samla loggar"]
        lage = [text.index(o) for o in ordning]
        self.assertEqual(lage, sorted(lage))
        for stycke in ('"$WHISPER_VERSION" build/whisper', "build/whisper/ut", "--port 8611", "--vantad-motor whispercpp",
                       "--vantat-jobbfel whisper-cli", "--riktig-rostmodell", "--ordtider-ut", "--ordtider",
                       'build/uppackad/Åsa Ölund/Akasha Protokoll/Akasha Protokoll.exe', '--hem "$RUNNER_TEMP/Åsa Ölund"',
                       "build/venv/Scripts/python", "dist/Akasha-Protokoll-windows-x64.zip", "archive: false",
                       "retention-days: 7", "name: loggar", "--durations 15"):
            self.assertIn(stycke, text)
        self.assertNotIn("faster-whisper\n", text.replace("'^faster-whisper'", ""))  # stacken installeras inte
        self.assertIn("grep -v '^faster-whisper' app/requirements.txt", text)

    def test_kontrollstegen_stoppar_inte_jobbet_och_allt_syns_i_sammanfattningen(self):
        d = self.yaml()
        steg = {s["id"]: s for s in d["jobs"]["bygg"]["steps"] if "id" in s}
        kontroller = ("tester", "bygg_cli", "samla_cli", "kontroll_cli", "bygg", "kontroll_program", "kontroll_windows")
        for id_ in kontroller:
            self.assertTrue(steg[id_].get("continue-on-error"), id_)
        for id_ in ("samla_cli", "kontroll_cli", "bygg", "kontroll_program", "kontroll_windows"):
            self.assertEqual(steg[id_]["if"], "${{ !cancelled() }}", id_)  # kors aven om ett tidigare steg fell
        sammanfattning = next(s for s in d["jobs"]["bygg"]["steps"] if s.get("name") == "Sammanfattning")
        self.assertEqual(sammanfattning["if"], "${{ always() }}")
        for id_ in kontroller:
            self.assertIn(f"steps.{id_}.outcome", str(sammanfattning["env"]), id_)
        self.assertIn("exit 1", sammanfattning["run"])
        for s in d["jobs"]["bygg"]["steps"]:
            if s.get("uses", "").startswith("actions/upload-artifact") and s.get("with", {}).get("name") == "loggar":
                self.assertEqual(s["if"], "${{ always() }}")
                break
        else:
            self.fail("ingen uppladdning av artefakten loggar")
        samla = next(s for s in d["jobs"]["bygg"]["steps"] if s.get("name") == "Samla loggar")
        self.assertEqual(samla["if"], "${{ always() }}")
        self.assertIn("find \"$HEM\" -name 'akasha-protokoll.log'", samla["run"])  # loggen letas upp, antas inte ligga pa en plats
        for fil in ("pyinstaller.log", "warn-*.txt", "program-utskrift.log", "program-utskrift-andra.log", "programlogg"):
            self.assertIn(fil, samla["run"])

    def test_installationen_och_kontrollsummorna_i_flodet(self):
        d = self.yaml()
        steg = d["jobs"]["bygg"]["steps"]
        id_ = [s_.get("id") for s_ in steg]
        for i in ("installation", "kontroll_installation", "summor"):
            s_ = steg[id_.index(i)]
            self.assertTrue(s_["continue-on-error"], i)  # ett fel hos Inno Setup hindrar aldrig zip-filen
            self.assertEqual(s_["if"], "${{ !cancelled() }}", i)
        # efter zip-kontrollen, fore sammanfattningen
        self.assertLess(id_.index("kontroll_windows"), id_.index("installation"))
        self.assertLess(id_.index("installation"), id_.index("kontroll_installation"))
        self.assertLess(id_.index("kontroll_installation"), id_.index("summor"))
        text = self.text()
        for stycke in ("bygg_installation.py", "kontrollera_installation.py", "kontrollsummor.py",
                       '--version "$AKASHA_VERSION.$AKASHA_BYGGNUMMER"', "$RUNNER_TEMP/Installerat Åäö/Akasha Protokoll",
                       "$RUNNER_TEMP/Hem för installationen Åäö", "dist/Akasha-Protokoll-installation.exe", "dist/SHA256SUMS.txt"):
            self.assertIn(stycke, text)
        uppladdat = [s_["with"]["path"] for s_ in steg if s_.get("uses", "").startswith("actions/upload-artifact") and "path" in s_.get("with", {})
                     and not s_["with"].get("name")]
        self.assertEqual(uppladdat, ["dist/Akasha-Protokoll-windows-x64.zip", "dist/Akasha-Protokoll-installation.exe", "dist/SHA256SUMS.txt"])
        sammanfattning = next(s_ for s_ in steg if s_.get("name") == "Sammanfattning")
        for i in ("installation", "kontroll_installation", "summor"):
            self.assertIn(f"steps.{i}.outcome", str(sammanfattning["env"]))
        self.assertNotIn("secrets", text.lower())

    def test_cachen_sparas_bara_nar_bygget_lyckades(self):
        d = self.yaml()
        spara = next(s for s in d["jobs"]["bygg"]["steps"] if s.get("uses", "").startswith("actions/cache/save"))
        self.assertIn("steps.bygg_cli.outcome == 'success'", spara["if"])
        nyckel = next(s for s in d["jobs"]["bygg"]["steps"] if s.get("id") == "cli")["with"]["key"]
        # bara skriptet som kompilerar ingar i nyckeln: en rattning i verktygen far inte ge ett nytt bygge
        self.assertIn("hashFiles('paketering/bygg-whisper-cli-windows.sh')", nyckel)
        self.assertNotIn("verktyg", nyckel)
        self.assertNotIn("kontrollera_pe", nyckel)
        self.assertTrue(nyckel.endswith("-windows2025"))
        for s_ in d["jobs"]["bygg"]["steps"]:
            if s_.get("uses", "").startswith("actions/cache/"):
                self.assertEqual(s_["with"]["path"], "build/whisper/kompilerat")
        samla = next(s_ for s_ in d["jobs"]["bygg"]["steps"] if s_.get("id") == "samla_cli")
        self.assertNotIn("cache-hit", str(samla.get("if")))  # kors efter bygge och cachetraff
        self.assertIn("samla-whisper-cli-windows.sh build/whisper/kompilerat build/whisper/ut", samla["run"])

    def test_cachelagret_har_inte_runtime_eller_verktyg(self):
        bygg = las("paketering", "bygg-whisper-cli-windows.sh")
        self.assertNotIn('bygg_windows_verktyg.py" runtime', bygg)  # kopieringen ligger i samla
        self.assertNotIn('kontrollera_pe.py"', bygg)
        samla = las("paketering", "samla-whisper-cli-windows.sh")
        for stycke in ("runtime", "kontrollera_pe.py", "lista", "ggml-cpu-*.dll"):
            self.assertIn(stycke, samla)

    def test_signera_finns_men_kors_aldrig(self):
        text = self.text()
        d = self.yaml()
        signera = d["jobs"]["signera"]
        self.assertIs(signera["if"], False)
        self.assertEqual(signera["needs"], "bygg")
        for steg in signera["steps"]:
            self.assertNotIn("uses", steg)  # inga atgarder fran tredje part
            self.assertNotIn("env", steg)
        delar = text.split("\n  signera:\n")[1]
        self.assertIn("SignPath", delar)
        self.assertNotIn("uses:", delar)
        self.assertIn("if: false", delar)
        self.assertNotIn("secrets", delar.lower())

    def test_kommentarerna_har_inga_aao(self):
        for kommentar in kommentarer(self.FLODE):
            self.assertIsNone(re.search("[åäöÅÄÖ]", kommentar), kommentar)


if __name__ == "__main__":
    unittest.main()
