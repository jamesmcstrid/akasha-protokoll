import io
import json
import os
import threading
import unittest
from unittest import mock

import hjalp
import lagring
from werkzeug.datastructures import FileStorage

INST = {"talare": "2", "ord": ""}


class Uppladdning:
    """Som werkzeug FileStorage: save(dst) skriver innehallet, anropar under(dst) och kastar fel."""

    def __init__(self, innehall=b"ljud", under=None, fel=None):
        self.innehall, self.under, self.fel = innehall, under, fel

    def save(self, dst):
        with open(dst, "wb") as f:
            f.write(self.innehall)
        if self.under:
            self.under(dst)
        if self.fel:
            raise self.fel


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
        self.assertEqual(lagring.las(b["id"])["fel"], lagring.AVBRUTEN)
        self.assertEqual(lagring.AVBRUTEN, "Transkriberingen avbröts eftersom Akasha Protokoll avslutades. "
                                           "Tryck Försök igen för att göra om den.")
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
        self.assertEqual(ers.call_count, lagring.OMFORSOK)

    def test_las_forsoker_igen_vid_permissionerror(self):
        m = lagring.ny_inspelning(".webm", "Titel", INST)
        riktig = open
        anrop = []

        def last_tva_ganger(*a, **k):
            anrop.append(a)
            if len(anrop) <= 2:
                raise PermissionError("last")
            return riktig(*a, **k)

        with mock.patch("lagring.time.sleep"), mock.patch("builtins.open", last_tva_ganger):
            meta = lagring.las(m["id"])
        self.assertEqual(meta["titel"], "Titel")
        self.assertEqual(len(anrop), 3)

    def test_las_ger_upp_efter_alla_forsok(self):
        m = lagring.ny_inspelning(".webm", "", INST)
        with mock.patch("lagring.time.sleep") as sov, \
                mock.patch("builtins.open", side_effect=PermissionError("last")) as oppna:
            with self.assertRaises(PermissionError):
                lagring.las(m["id"])
        self.assertEqual(oppna.call_count, lagring.OMFORSOK)
        self.assertEqual(sov.call_count, lagring.OMFORSOK - 1)

    def test_lista_hoppar_over_last_fil(self):
        a = lagring.ny_inspelning(".webm", "A", INST)
        b = lagring.ny_inspelning(".webm", "B", INST)
        riktig = lagring.las

        def las_med_last_fil(id_):
            if id_ == a["id"]:
                raise PermissionError("last")
            return riktig(id_)

        with mock.patch("lagring.las", las_med_last_fil), self.assertLogs("lagring", "WARNING") as logg:
            ut = lagring.lista()
        self.assertEqual([m["id"] for m in ut], [b["id"]])
        self.assertIn(a["id"], logg.output[0])

    def test_las_vantar_pa_laset(self):
        m = lagring.ny_inspelning(".webm", "", INST)
        har_laset = threading.Event()
        slapp = threading.Event()
        klar = threading.Event()

        def hall_laset():
            with lagring._las:
                har_laset.set()
                slapp.wait(5)

        def lasare():
            lagring.las(m["id"])
            klar.set()

        h = threading.Thread(target=hall_laset)
        h.start()
        self.assertTrue(har_laset.wait(5))
        t = threading.Thread(target=lasare)
        t.start()
        self.assertFalse(klar.wait(0.2))  # las() ska stanna kvar tills laset slapps
        slapp.set()
        self.assertTrue(klar.wait(5))
        h.join(5)
        t.join(5)

    # --- delar som skrivs en gang --------------------------------------------------------

    def innehall(self, m):
        with open(lagring.ljudfil(m), "rb") as f:
            return f.read()

    def test_del_skrivs_inte_tva_ganger_nar_uppgifterna_inte_gick_att_spara(self):
        m = lagring.ny_inspelning(".webm", "", INST)
        lagring.lagg_till_del(m["id"], 0, b"aaa")
        with mock.patch.object(lagring, "spara", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                lagring.lagg_till_del(m["id"], 1, b"bbb")
        self.assertEqual(self.innehall(m), b"aaa")
        lagring.lagg_till_del(m["id"], 1, b"bbb")  # webblasaren skickar samma del igen
        self.assertEqual(self.innehall(m), b"aaabbb")
        meta = lagring.las(m["id"])
        self.assertEqual((meta["delar"], meta["byte"]), (2, 6))

    def test_del_efter_krasch_mellan_ljud_och_uppgifter_skrivs_om(self):
        m = lagring.ny_inspelning(".webm", "", INST)
        lagring.lagg_till_del(m["id"], 0, b"aaa")
        with open(lagring.ljudfil(m), "ab") as f:
            f.write(b"bb")  # del 1 skrevs (till halften), sedan stannade programmet
        with self.assertLogs("lagring", "WARNING"):
            lagring.lagg_till_del(m["id"], 1, b"bbb")
            self.assertEqual(self.innehall(m), b"aaabbb")
        lagring.lagg_till_del(m["id"], 2, b"ccc")
        self.assertEqual(self.innehall(m), b"aaabbbccc")
        self.assertEqual(lagring.las(m["id"])["byte"], 9)

    def test_aldre_inspelning_utan_byte_kortas_inte(self):
        m = lagring.ny_inspelning(".webm", "", INST)
        lagring.lagg_till_del(m["id"], 0, b"aaa")
        meta = lagring.las(m["id"])
        del meta["byte"]
        lagring.spara(meta)
        with open(lagring.ljudfil(m), "ab") as f:
            f.write(b"xx")
        lagring.lagg_till_del(m["id"], 1, b"bbb")
        self.assertEqual(self.innehall(m), b"aaaxxbbb")  # som forut
        self.assertEqual(lagring.las(m["id"])["byte"], 8)

    # --- uppladdning som syns forst nar den ar skriven -----------------------------------

    def test_uppladdning_syns_forst_nar_filen_ar_skriven(self):
        sett = []
        m = lagring.fran_fil(Uppladdning(b"ljud", under=lambda dst: sett.append(lagring.lista())),
                             "mote.m4a", "", INST)
        self.assertEqual(sett, [[]])
        self.assertEqual([x["id"] for x in lagring.lista()], [m["id"]])
        self.assertEqual(self.innehall(m), b"ljud")
        self.assertEqual(sorted(os.listdir(hjalp.DATA)), [m["id"] + ".json", m["id"] + ".m4a"])

    def test_uppladdning_som_inte_gar_att_skriva_lamnar_inget_kvar(self):
        with self.assertRaises(OSError):
            lagring.fran_fil(Uppladdning(b"halv", fel=OSError(28, "No space left on device")), "mote.m4a", "", INST)
        self.assertEqual(lagring.lista(), [])
        self.assertEqual(os.listdir(hjalp.DATA), [])

    def test_tom_uppladdning_lamnar_inget_kvar(self):
        with self.assertRaises(lagring.Fel) as e:
            lagring.fran_fil(Uppladdning(b""), "tom.m4a", "", INST)
        self.assertEqual(str(e.exception), "filen ar tom")
        self.assertEqual(os.listdir(hjalp.DATA), [])

    def test_uppladdning_dar_uppgifterna_inte_gar_att_spara_lamnar_inget_kvar(self):
        with mock.patch.object(lagring, "spara", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                lagring.fran_fil(Uppladdning(b"ljud"), "mote.m4a", "", INST)
        self.assertEqual(os.listdir(hjalp.DATA), [])

    # --- listan med cache ----------------------------------------------------------------

    def test_sammanfattningar_har_inte_texten_men_de_tre_falten(self):
        m = lagring.ny_inspelning(".webm", "Möte", INST)
        segment = [{"start": 0.0, "end": 1.0, "text": "Hej", "speaker": 1}]
        lagring.uppdatera(m["id"], status="klar", resultat={
            "text": "Hej", "segment": segment, "segment_original": segment, "talare": 1, "langd_s": 3.0})
        k, = lagring.sammanfattningar()
        self.assertEqual((k["har_text"], k["langd_s"], k["rattad"]), (True, 3.0, True))
        self.assertEqual(k["resultat"], {"langd_s": 3.0, "talare": 1})  # det export.info visar
        self.assertEqual((k["titel"], k["status"]), ("Möte", "klar"))
        ny = lagring.ny_inspelning(".webm", "", INST)
        tom, = [x for x in lagring.sammanfattningar() if x["id"] == ny["id"]]
        self.assertEqual((tom["har_text"], tom["langd_s"], tom["rattad"]), (False, None, False))
        self.assertNotIn("resultat", tom)
        # lista() ger fortfarande hela uppgifterna.
        hel, = [x for x in lagring.lista() if x["id"] == m["id"]]
        self.assertEqual(hel["resultat"]["segment"], segment)

    def test_sammanfattningar_laser_inte_om_oforandrade_filer(self):
        a = lagring.ny_inspelning(".webm", "A", INST)
        lagring.ny_inspelning(".webm", "B", INST)
        lagring.sammanfattningar()
        with mock.patch.object(lagring, "las", wraps=lagring.las) as las:
            self.assertEqual(len(lagring.sammanfattningar()), 2)
            self.assertEqual(las.call_count, 0)
            lagring.uppdatera(a["id"], titel="Ny")
            las.reset_mock()
            ut = lagring.sammanfattningar()
            las.assert_called_once_with(a["id"])
        self.assertEqual(next(x["titel"] for x in ut if x["id"] == a["id"]), "Ny")
        ut[0]["titel"] = "andrad av den som fick listan"
        self.assertNotIn("andrad av den som fick listan", [x["titel"] for x in lagring.sammanfattningar()])

    def test_sammanfattningar_ser_andringar_och_raderingar_utanfor_programmet(self):
        a = lagring.ny_inspelning(".webm", "A", INST)
        b = lagring.ny_inspelning(".webm", "B", INST)
        lagring.sammanfattningar()
        sokvag = os.path.join(hjalp.DATA, a["id"] + ".json")

        def skriv(titel, mtime_ns):
            # Som ett annat program: utan spara(), och med en vald andringstid.
            meta = lagring.las(a["id"])
            meta["titel"] = titel
            with open(sokvag, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=1)
            os.utime(sokvag, ns=(mtime_ns, mtime_ns))

        def titel():
            return next(x["titel"] for x in lagring.sammanfattningar() if x["id"] == a["id"])

        forut = os.stat(sokvag).st_mtime_ns
        skriv("C", forut + 2_000_000_000)  # samma storlek, ny tid
        self.assertEqual(titel(), "C")
        skriv("En längre titel", forut + 2_000_000_000)  # samma tid, ny storlek
        self.assertEqual(titel(), "En längre titel")
        lagring.radera(a["id"])
        self.assertEqual([x["id"] for x in lagring.sammanfattningar()], [b["id"]])
        os.remove(os.path.join(hjalp.DATA, b["id"] + ".json"))
        self.assertEqual(lagring.sammanfattningar(), [])

    def test_sammanfattningar_hoppar_over_last_och_tom_fil(self):
        a = lagring.ny_inspelning(".webm", "A", INST)
        b = lagring.ny_inspelning(".webm", "B", INST)
        with open(os.path.join(hjalp.DATA, "20261117-140312.json"), "w"):
            pass  # en reservation av ett id (tom .json-fil) syns inte
        riktig = lagring.las

        def las_med_last_fil(id_):
            if id_ == a["id"]:
                raise PermissionError("last")
            return riktig(id_)

        with mock.patch("lagring.las", las_med_last_fil), self.assertLogs("lagring", "WARNING") as logg:
            ut = lagring.sammanfattningar()
        self.assertEqual([m["id"] for m in ut], [b["id"]])
        self.assertIn(a["id"], logg.output[0])
        self.assertEqual([m["id"] for m in lagring.sammanfattningar()], [b["id"], a["id"]])  # last fil cachas inte

    def test_stada_halvfardiga_tar_bara_bort_rester_av_uppladdningar(self):
        def skriv(namn, innehall=b""):
            with open(os.path.join(hjalp.DATA, namn), "wb") as f:
                f.write(innehall)

        hel = lagring.ny_inspelning(".webm", "Hel", INST)
        lagring.lagg_till_del(hel["id"], 0, b"ljud")
        skriv("20261117-140312.json")           # tom reservation...
        skriv("20261117-140312.m4a")            # ...med tom ljudfil: tas bort
        skriv("20261117-140312.m4a.delvis", b"halv")  # avbruten kopia: tas bort
        skriv("20261117-150000.json")           # tom .json men ljud finns: lamnas
        skriv("20261117-150000.webm", b"ljud")
        skriv("annat.delvis", b"x")             # inte programmets: lamnas
        lagring.stada_halvfardiga()
        kvar = sorted(os.listdir(hjalp.DATA))
        self.assertNotIn("20261117-140312.json", kvar)
        self.assertNotIn("20261117-140312.m4a", kvar)
        self.assertNotIn("20261117-140312.m4a.delvis", kvar)
        for namn in ("20261117-150000.json", "20261117-150000.webm", "annat.delvis",
                     hel["id"] + ".json", hel["id"] + ".webm"):
            self.assertIn(namn, kvar)
        self.assertEqual(lagring.las(hel["id"])["delar"], 1)


if __name__ == "__main__":
    unittest.main()
