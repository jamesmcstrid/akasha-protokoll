import io
import os
import unittest

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
        m = lagring.fran_fil(FileStorage(io.BytesIO(b"ljud"), "möte.m4a"), "möte.m4a", "", INST)
        self.assertEqual((m["status"], m["andelse"], m["titel"]), ("sparad", ".m4a", "möte"))
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


if __name__ == "__main__":
    unittest.main()
