"""Snabba kontroller av paketeringen: gar pa alla system och kraver varken PyInstaller eller PyObjC."""
import ast
import glob
import os
import re
import unittest

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
        for delar in (("app", "mac_app.py"), ("paketering", "akasha-protokoll.spec"), ("paketering", "kontrollera.py")):
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


if __name__ == "__main__":
    unittest.main()
