import io
import os
import unittest
from unittest import mock

import hjalp
import lagring
from werkzeug.datastructures import FileStorage

INST = {"talare": "2", "ord": ""}


class TestLagring(unittest.TestCase):
    def setUp(self):
        hjalp.tom_datakatalog()

    def test_delar_laggs_till_i_ordning(self):
        m = lagring.ny_inspelning(".webm", "Möte", INST)
        self.assertEqual(m["status"], "spelar_in")
        lagring.lagg_till_del(m["id"], 0, b"aaa")
        lagring.lagg_till_del(m["id"], 1, b"bbb")
        with open(lagring.ljudfil(m), "rb") as f:
            self.assertEqual(f.read(), b"aaabbb")

    def test_omsand_del_skrivs_inte_tva_ganger(self):
        m = lagring.ny_inspelning(".webm", "", INST)
        lagring.lagg_till_del(m["id"], 0, b"aaa")
        lagring.lagg_till_del(m["id"], 0, b"aaa")  # webblasaren forsokte igen
        self.assertEqual(lagring.las(m["id"])["delar"], 1)
        with open(lagring.ljudfil(m), "rb") as f:
            self.assertEqual(f.read(), b"aaa")

    def test_lucka_avvisas(self):
        m = lagring.ny_inspelning(".webm", "", INST)
        with self.assertRaises(lagring.Fel) as e:
            lagring.lagg_till_del(m["id"], 1, b"x")
        self.assertEqual(e.exception.kod, 409)

    def test_avslutad_inspelning_tar_inte_emot_fler_delar(self):
        m = lagring.ny_inspelning(".webm", "", INST)
        lagring.avsluta_inspelning(m["id"])
        self.assertEqual(lagring.las(m["id"])["status"], "sparad")
        with self.assertRaises(lagring.Fel):
            lagring.lagg_till_del(m["id"], 0, b"x")

    def test_unika_id_samma_sekund(self):
        a = lagring.ny_inspelning(".webm", "", INST)
        b = lagring.ny_inspelning(".webm", "", INST)
        self.assertNotEqual(a["id"], b["id"])
        self.assertTrue(lagring.ID_RE.fullmatch(b["id"]))

    def test_ogiltigt_id_och_filtyp(self):
        for id_ in ("../etc/passwd", "20261117-140312/../x", "", "abc"):
            with self.assertRaises(lagring.Fel, msg=id_):
                lagring.las(id_)
        with self.assertRaises(lagring.Fel):
            lagring.ny_inspelning(".exe", "", INST)

    def test_fran_fil_och_tom_fil(self):
        m = lagring.fran_fil(FileStorage(io.BytesIO(b"ljud"), "Storgatan 1 5.m4a"), "Storgatan 1 5.m4a", "", INST)
        # Filnamnet (ofta en adress fran Rostmemon) blir aldrig rubrik och sparas inte.
        self.assertEqual((m["status"], m["andelse"], m["titel"]), ("sparad", ".m4a", ""))
        with open(os.path.join(hjalp.DATA, m["id"] + ".json"), encoding="utf-8") as f:
            self.assertNotIn("Storgatan", f.read())
        with self.assertRaises(lagring.Fel):
            lagring.fran_fil(FileStorage(io.BytesIO(b""), "tom.m4a"), "tom.m4a", "", INST)
        self.assertEqual(len(lagring.lista()), 1)  # den tomma ar bortstadad

    def test_lista_radera_och_aterstall(self):
        a = lagring.ny_inspelning(".webm", "", INST)
        b = lagring.ny_inspelning(".m4a", "", INST)
        lagring.uppdatera(b["id"], status="transkriberar")
        self.assertEqual([m["id"] for m in lagring.lista()], [b["id"], a["id"]])
        lagring.aterstall_avbrutna()
        self.assertEqual(lagring.las(b["id"])["status"], "avbruten")
        self.assertEqual(lagring.las(a["id"])["status"], "spelar_in")  # orord
        lagring.radera(a["id"])
        self.assertFalse(os.path.exists(lagring.ljudfil(a)))
        self.assertEqual(len(lagring.lista()), 1)

    def test_spara_forsoker_igen_om_filen_ar_last(self):
        # Windows: os.replace ger PermissionError om en annan trad just laser .json-filen.
        m = lagring.ny_inspelning(".webm", "Före", INST)
        riktig = os.replace
        anrop = []

        def last_en_gang(a, b):
            anrop.append(a)
            if len(anrop) == 1:
                raise PermissionError("last")
            return riktig(a, b)

        with mock.patch("lagring.time.sleep"), mock.patch("lagring.os.replace", last_en_gang):
            lagring.uppdatera(m["id"], titel="Efter")
        self.assertEqual(len(anrop), 2)
        self.assertEqual(lagring.las(m["id"])["titel"], "Efter")

    def test_spara_ger_upp_efter_fem_forsok(self):
        m = lagring.ny_inspelning(".webm", "", INST)
        with mock.patch("lagring.time.sleep"), \
                mock.patch("lagring.os.replace", side_effect=PermissionError("last")) as ers:
            with self.assertRaises(PermissionError):
                lagring.uppdatera(m["id"], titel="X")
        self.assertEqual(ers.call_count, 5)


if __name__ == "__main__":
    unittest.main()
