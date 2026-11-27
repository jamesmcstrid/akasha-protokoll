import unittest
from unittest import mock

import hjalp  # noqa: F401
import export

META = {
    "id": "20261117-140312",
    "skapad": "2026-11-17T14:03:12+01:00",
    "titel": "",
    "namn": {"1": "Anna"},
    "resultat": {
        "langd_s": 3725,
        "talare": 2,
        "segment": [
            {"start": 0.4, "end": 3.0, "speaker": 1, "text": "Hej Bo."},
            {"start": 3725 - 10, "end": 3725, "speaker": 2, "text": "Hej Anna."},
        ],
    },
}


class TestExport(unittest.TestCase):
    def test_tid(self):
        self.assertEqual(export.tid(0), "00:00")
        self.assertEqual(export.tid(65.4), "01:05")
        self.assertEqual(export.tid(3725), "1:02:05")

    def test_info_delar_och_info(self):
        self.assertEqual(export.info_delar(META), ["2026-11-17 14:03", "1:02:05", "2 talare"])
        utan = dict(META, resultat={"langd_s": 5, "segment": []})
        self.assertEqual(export.info_delar(utan), ["2026-11-17 14:03", "00:05"])
        for m in (META, utan):
            self.assertEqual(export.info(m), " · ".join(export.info_delar(m)))
        self.assertEqual(export.info(META), "2026-11-17 14:03 · 1:02:05 · 2 talare")

    def test_markdown_med_namn(self):
        md = export.som_markdown(META)
        self.assertTrue(md.startswith("# Möte 2026-11-17 14:03\n"))
        self.assertIn("1:02:05 · 2 talare", md)
        self.assertIn("**Anna** (00:00): Hej Bo.", md)
        self.assertIn("**Talare 2** (1:01:55): Hej Anna.", md)
        self.assertIn(export.VARNING_KONTROLL, md)

    def test_text_och_en_talare(self):
        meta = dict(META, titel="Avstämning", resultat={
            "langd_s": 5, "segment": [{"start": 1.0, "end": 2.0, "text": "Bara jag."}],
            "varning": "Texten är inte uppdelad per talare."})
        txt = export.som_text(meta)
        self.assertTrue(txt.startswith("Avstämning\n"))
        self.assertIn("[00:01] Bara jag.", txt)
        self.assertIn("Obs: Texten är inte uppdelad per talare.", txt)


class TestSignatur(unittest.TestCase):
    def test_standard_sist_i_markdown_och_text(self):
        md = export.som_markdown(META)
        self.assertTrue(md.endswith(
            "Hej Anna.\n\n---\n\n_Transkriberat med [Akasha Protokoll](" + export.LANK_REPO + "), "
            "lokalt på den egna datorn. Vill du testa själv? [Ladda ner här](" + export.LANK_HAMTA + ")._\n"), md)
        txt = export.som_text(META)
        self.assertTrue(txt.endswith(
            "Hej Anna.\n\nTranskriberat med Akasha Protokoll, lokalt på den egna datorn.\n"
            "Vill du testa själv? " + export.LANK_HAMTA + "\n"), txt)
        self.assertEqual(export.LANK_HAMTA, "https://github.com/jamesmcstrid/akasha-protokoll/releases/latest")

    def test_signatur_false_tar_bort_den(self):
        for text in (export.som_markdown(META, signatur=False), export.som_text(META, signatur=False)):
            self.assertNotIn("Akasha Protokoll", text)
            self.assertNotIn(export.LANK_REPO, text)
            self.assertTrue(text.endswith("Hej Anna.\n"), text)

    def test_installningen_av(self):
        with mock.patch.object(export.installningar, "SIGNATUR", "av"):
            self.assertNotIn("Akasha Protokoll", export.som_markdown(META))
            self.assertNotIn("Akasha Protokoll", export.som_text(META))
            self.assertIn("Akasha Protokoll", export.som_text(META, signatur=True))

    def test_en_enda_radbrytning_sist(self):
        for text in (export.som_markdown(META), export.som_text(META),
                     export.som_markdown({}), export.som_text({})):
            self.assertTrue(text.endswith("\n"))
            self.assertFalse(text.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()


class TestVarningMedMotor(unittest.TestCase):
    def test_motorn_som_anvandes(self):
        self.assertEqual(export.varning_kontroll({}), export.VARNING_KONTROLL)
        self.assertEqual(export.varning_kontroll({"resultat": {"motor": "KB-Whisper medium (whisper.cpp, Metal)"}}),
                         export.VARNING_KONTROLL)
        text = export.varning_kontroll({"resultat": {"motor": "Pianissimo (Klang)"}})
        self.assertTrue(text.startswith("Transkriberat lokalt med Pianissimo."), text)
        self.assertNotIn("KB-Whisper", export.som_text({"resultat": {"motor": "Pianissimo (Klang)", "segment": []}}))
