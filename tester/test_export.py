import unittest

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
