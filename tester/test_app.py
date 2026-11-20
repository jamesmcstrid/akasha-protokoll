"""Webbtjansten med en lataskmotor: inga modeller behovs."""
import io
import json
import os
import threading
import unittest
from unittest import mock

import numpy as np

import hjalp
import app as akasha
import lagring
import modeller
import motor
import plattform
import talare
from falsk_hf import FalskHF, falska_paket, session_med

H = {"X-Akasha-Meet": "1"}
ORD = [(0.0, 0.5, " Hej"), (0.5, 1.0, " Bo."), (1.5, 2.0, " Hej"), (2.0, 2.5, " Anna.")]


def falsk_dela_upp(samples, ord_lista, antal, framsteg=None, ord_p=None):
    if framsteg:
        framsteg(1.0)
    return talare.repliker(ord_lista, [0, 0, 1, 1]), 2, None


def falsk_avkoda(sokvag):
    with open(sokvag, "rb") as f:
        if f.read().startswith(b"trasig"):
            raise ValueError("Invalid data found when processing input")
    return np.zeros(motor.SR * 3, dtype=np.float32)


def falsk_transkribera(samples, per_ord=False, prompt="", framsteg=None):
    if framsteg:
        framsteg(1.0)
    segs = [{"start": 0.0, "end": 2.5, "text": "Hej Bo. Hej Anna."}]
    return "Hej Bo. Hej Anna.", segs, (ORD if per_ord else [])


class TestApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        akasha.starta_arbetare()

    def setUp(self):
        hjalp.tom_datakatalog()
        self.klient = akasha.app.test_client()
        self.patchar = [
            mock.patch.object(motor, "avkoda", falsk_avkoda),
            mock.patch.object(motor, "transkribera", falsk_transkribera),
            mock.patch.object(motor, "problem", lambda: None),
            mock.patch.object(talare, "problem", lambda: None),
            mock.patch.object(talare, "dela_upp", falsk_dela_upp),
        ]
        for p in self.patchar:
            p.start()

    def tearDown(self):
        for p in self.patchar:
            p.stop()

    def ladda_upp(self, innehall=b"ljud", talare_="2", titel="Avstämning"):
        r = self.klient.post("/api/inspelningar/fil", headers=H, content_type="multipart/form-data",
                             data={"ljud": (io.BytesIO(innehall), "mote.m4a"), "talare": talare_, "titel": titel})
        self.assertEqual(r.status_code, 201, r.get_json())
        akasha._ko.join()  # vanta tills bakgrundsjobbet ar klart
        return r.get_json()["id"]

    # --- skydd ---------------------------------------------------------------------------

    def test_avbruten_nar_programmet_avslutas(self):
        def avbryt(*a, **k):
            raise motor.Avbruten("stoppad")

        with mock.patch.object(motor, "transkribera", avbryt):
            id_ = self.ladda_upp()
        m = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertEqual((m["status"], m["fel"]), ("avbruten", lagring.AVBRUTEN))
        # Forsok igen: jobbet kor vidare med den vanliga (falska) motorn.
        r = self.klient.post(f"/api/inspelningar/{id_}/transkribera", headers=H)
        self.assertEqual(r.status_code, 200, r.get_json())
        akasha._ko.join()
        self.assertEqual(self.klient.get(f"/api/inspelningar/{id_}").get_json()["status"], "klar")

    def test_annat_vardnamn_avvisas(self):
        self.assertEqual(self.klient.get("/", base_url="http://angripare.example").status_code, 403)
        self.assertEqual(self.klient.get("/health", base_url="http://127.0.0.1:8611").status_code, 200)

    def test_andring_utan_header_eller_fran_annan_sajt_avvisas(self):
        self.assertEqual(self.klient.post("/api/inspelningar", json={}).status_code, 403)
        r = self.klient.post("/api/inspelningar", json={}, headers={**H, "Origin": "https://angripare.example"})
        self.assertEqual(r.status_code, 403)
        r = self.klient.post("/api/inspelningar", json={}, headers={**H, "Origin": "http://localhost:8611"})
        self.assertEqual(r.status_code, 201)

    def test_sakerhetsheaders(self):
        with self.klient.get("/") as r:
            self.assertEqual(r.status_code, 200)
            self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")

    # --- floden --------------------------------------------------------------------------

    def test_uppladdning_ger_repliker_text_och_namn(self):
        id_ = self.ladda_upp()
        m = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertEqual(m["status"], "klar", m)
        self.assertEqual(m["resultat"]["talare"], 2)
        self.assertEqual([(s["speaker"], s["text"]) for s in m["resultat"]["segment"]],
                         [(1, "Hej Bo."), (2, "Hej Anna.")])
        with open(lagring.textfil(id_), encoding="utf-8") as f:
            self.assertIn("**Talare 1** (00:00): Hej Bo.", f.read())

        r = self.klient.post(f"/api/inspelningar/{id_}/namn", headers=H, json={"1": " Anna ", "x": "bort"})
        self.assertEqual(r.get_json()["namn"], {"1": "Anna"})
        with open(lagring.textfil(id_), encoding="utf-8") as f:
            self.assertIn("**Anna** (00:00): Hej Bo.", f.read())

        r = self.klient.get(f"/api/inspelningar/{id_}/text.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Avst%C3%A4mning.txt", r.headers["Content-Disposition"])  # RFC 5987
        self.assertIn("[00:00] Anna: Hej Bo.", r.get_data(as_text=True))

    def test_uppladdning_utan_rubrik_och_byte_av_rubrik(self):
        r = self.klient.post("/api/inspelningar/fil", headers=H, content_type="multipart/form-data",
                             data={"ljud": (io.BytesIO(b"ljud"), "Storgatan 1 5.m4a"), "talare": "2"})
        id_ = r.get_json()["id"]
        akasha._ko.join()
        m = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertTrue(m["rubrik"].startswith("Möte "), m["rubrik"])
        self.assertNotIn("Storgatan", json.dumps(m, ensure_ascii=False))

        r = self.klient.post(f"/api/inspelningar/{id_}/titel", headers=H, json={"titel": "  Planering  "})
        self.assertEqual(r.get_json(), {"titel": "Planering", "rubrik": "Planering"})
        with open(lagring.textfil(id_), encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("# Planering\n"))
        self.assertIn("Planering.md", self.klient.get(f"/api/inspelningar/{id_}/text.md").headers["Content-Disposition"])
        r = self.klient.post(f"/api/inspelningar/{id_}/titel", headers=H, json={"titel": ""})
        self.assertTrue(r.get_json()["rubrik"].startswith("Möte "))
        self.assertEqual(self.klient.post(f"/api/inspelningar/{id_}/titel", json={"titel": "x"}).status_code, 403)

    def test_en_talare_delar_inte_upp(self):
        id_ = self.ladda_upp(talare_="1")
        res = self.klient.get(f"/api/inspelningar/{id_}").get_json()["resultat"]
        self.assertIsNone(res["talare"])
        self.assertNotIn("speaker", res["segment"][0])

    def test_inspelning_i_delar(self):
        r = self.klient.post("/api/inspelningar", headers=H, json={"andelse": ".webm", "talare": "2"})
        id_ = r.get_json()["id"]
        for nr, data in enumerate([b"del0", b"del1", b"del2"]):
            r = self.klient.post(f"/api/inspelningar/{id_}/del?nr={nr}", headers=H, data=data,
                                 content_type="application/octet-stream")
            self.assertEqual(r.get_json()["delar"], nr + 1)
        r = self.klient.post(f"/api/inspelningar/{id_}/del?nr=1", headers=H, data=b"del1")
        self.assertEqual(r.get_json()["delar"], 3)  # omsandning godtas
        self.assertEqual(self.klient.post(f"/api/inspelningar/{id_}/del?nr=5", headers=H, data=b"x").status_code, 409)
        self.klient.post(f"/api/inspelningar/{id_}/klar", headers=H, json={"starta": True, "talare": "2"})
        akasha._ko.join()
        m = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertEqual(m["status"], "klar")
        with open(lagring.ljudfil(m), "rb") as f:
            self.assertEqual(f.read(), b"del0del1del2")

    def test_rubrik_vid_stopp_ersatter_rubriken_fran_start(self):
        r = self.klient.post("/api/inspelningar", headers=H, json={"andelse": ".webm", "titel": "Från start"})
        id_ = r.get_json()["id"]
        self.klient.post(f"/api/inspelningar/{id_}/del?nr=0", headers=H, data=b"ljud")
        self.klient.post(f"/api/inspelningar/{id_}/klar", headers=H,
                         json={"starta": True, "talare": "2", "titel": "  " + "x" * 250})
        akasha._ko.join()
        m = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertEqual((m["status"], m["titel"]), ("klar", "x" * 200))
        with open(lagring.textfil(id_), encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("# " + "x" * 200 + "\n"))

    def test_tom_rubrik_vid_stopp_behaller_rubriken_fran_start(self):
        for titel in ({"titel": "   "}, {"titel": None}, {}):
            r = self.klient.post("/api/inspelningar", headers=H, json={"andelse": ".webm", "titel": "Från start"})
            id_ = r.get_json()["id"]
            self.klient.post(f"/api/inspelningar/{id_}/del?nr=0", headers=H, data=b"ljud")
            self.klient.post(f"/api/inspelningar/{id_}/klar", headers=H, json={"starta": True, **titel})
            akasha._ko.join()
            self.assertEqual(lagring.las(id_)["titel"], "Från start", titel)

    def test_utan_talarmodeller_blir_det_en_varning(self):
        with mock.patch.object(talare, "problem", lambda: "talarmodellerna saknas"):
            id_ = self.ladda_upp()
        res = self.klient.get(f"/api/inspelningar/{id_}").get_json()["resultat"]
        self.assertIn("inte uppdelad per talare", res["varning"])
        self.assertIsNone(res["talare"])

    def inspelning_i_delar(self, installningar):
        r = self.klient.post("/api/inspelningar", headers=H, json={"andelse": ".webm", **installningar})
        id_ = r.get_json()["id"]
        self.klient.post(f"/api/inspelningar/{id_}/del?nr=0", headers=H, data=b"ljud")
        self.klient.post(f"/api/inspelningar/{id_}/klar", headers=H, json={"starta": True})
        akasha._ko.join()
        return id_

    def test_digitalt_mote_ger_du_som_talare_1(self):
        vanster = np.zeros(motor.SR * 3, dtype=np.float32)
        hoger = np.ones(motor.SR * 3, dtype=np.float32) * 0.1
        anrop = []

        def falsk_kanaler(v, h, ord_lista, antal, framsteg=None, ord_p=None):
            anrop.append(antal)
            return talare.repliker(ord_lista, [1, 1, 2, 2], fasta_nummer=True), 2, None
        with mock.patch.object(motor, "avkoda_kanaler", lambda p: (vanster, hoger)), \
             mock.patch.object(talare, "dela_upp_kanaler", falsk_kanaler):
            id_ = self.inspelning_i_delar({"talare": "2", "kalla": "digitalt"})
        m = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertEqual((m["status"], m["installningar"]["kalla"], anrop), ("klar", "digitalt", [2]))
        self.assertEqual(m["namn"], {"1": "Du"})
        with open(lagring.textfil(id_), encoding="utf-8") as f:
            self.assertIn("**Du** (00:00): Hej Bo.", f.read())

    def test_digitalt_men_mono_fil_delas_som_vanligt(self):
        x = np.ones(motor.SR * 3, dtype=np.float32) * 0.1
        with mock.patch.object(motor, "avkoda_kanaler", lambda p: (x, x.copy())):
            id_ = self.inspelning_i_delar({"talare": "2", "kalla": "digitalt"})
        m = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertEqual(m["status"], "klar")
        self.assertEqual(m["namn"], {})  # ingen mikrofonkanal, alltsa inget "Du"

    def test_kallan_behalls_nar_man_stoppar_eller_gor_om(self):
        r = self.klient.post("/api/inspelningar", headers=H, json={"andelse": ".webm", "talare": "3", "kalla": "digitalt"})
        id_ = r.get_json()["id"]
        self.klient.post(f"/api/inspelningar/{id_}/del?nr=0", headers=H, data=b"ljud")
        # Sidan skickar antal talare igen nar man stoppar, utan kalla.
        self.klient.post(f"/api/inspelningar/{id_}/klar", headers=H, json={"starta": True, "talare": "2", "ord": ""})
        akasha._ko.join()
        self.assertEqual(lagring.las(id_)["installningar"], {"talare": "2", "ord": "", "kalla": "digitalt"})
        self.klient.post(f"/api/inspelningar/{id_}/transkribera", headers=H, json={"talare": "4", "kalla": "rum"})
        akasha._ko.join()
        self.assertEqual(lagring.las(id_)["installningar"]["kalla"], "digitalt")

    def test_okand_kalla_blir_rum(self):
        r = self.klient.post("/api/inspelningar", headers=H, json={"kalla": "något annat"})
        self.assertEqual(lagring.las(r.get_json()["id"])["installningar"]["kalla"], "rum")

    def test_varning_nar_farre_roster_an_angivet(self):
        def en_rost(samples, ord_lista, antal, framsteg=None, ord_p=None):
            return talare.repliker(ord_lista, [0] * len(ord_lista)), 1, "Du angav 2 talare, men bara 1 röst gick att skilja åt."
        with mock.patch.object(talare, "dela_upp", en_rost):
            id_ = self.ladda_upp()
        res = self.klient.get(f"/api/inspelningar/{id_}").get_json()["resultat"]
        self.assertEqual(res["talare"], 1)
        self.assertIn("bara 1 röst", res["varning"])

    def test_trasigt_ljud_ger_begripligt_fel(self):
        id_ = self.ladda_upp(innehall=b"trasig fil")
        m = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertEqual(m["status"], "fel")
        self.assertIn("kunde inte läsas", m["fel"])
        # och den gar att gora om nar ljudet ar ratt
        with open(lagring.ljudfil(m), "wb") as f:
            f.write(b"ljud")
        self.klient.post(f"/api/inspelningar/{id_}/transkribera", headers=H, json={"talare": "2"})
        akasha._ko.join()
        self.assertEqual(self.klient.get(f"/api/inspelningar/{id_}").get_json()["status"], "klar")

    def test_motorfel_ger_fel_status(self):
        def kraschar(*a, **k):
            raise motor.MotorFel("whisper-cli avslutades med kod 1")
        with mock.patch.object(motor, "transkribera", kraschar):
            id_ = self.ladda_upp()
        m = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertEqual(m["status"], "fel")
        self.assertIn("whisper-cli", m["fel"])

    def test_ogiltiga_varden(self):
        r = self.klient.post("/api/inspelningar", headers=H, json={"talare": "elva"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.klient.get("/api/inspelningar/..%2F..%2Fetc").status_code, 404)
        self.assertEqual(self.klient.post("/api/inspelningar/fil", headers=H).status_code, 400)

    def test_radera_och_inte_under_transkribering(self):
        id_ = self.ladda_upp()
        lagring.uppdatera(id_, status="transkriberar")
        self.assertEqual(self.klient.post(f"/api/inspelningar/{id_}/radera", headers=H).status_code, 409)
        lagring.uppdatera(id_, status="klar")
        self.assertEqual(self.klient.post(f"/api/inspelningar/{id_}/radera", headers=H).status_code, 200)
        self.assertEqual(self.klient.get("/api/inspelningar").get_json()["inspelningar"], [])

    def test_ratta_talare_dela_sla_ihop_och_angra(self):
        id_ = self.ladda_upp()
        url = f"/api/inspelningar/{id_}"
        seg = self.klient.get(url).get_json()["resultat"]["segment"]
        self.assertEqual([(s["speaker"], s["text"]) for s in seg], [(1, "Hej Bo."), (2, "Hej Anna.")])
        # "Bo." sa talare 2: delas av och slås ihop med nästa replik
        r = self.klient.post(f"{url}/talare", json={"replik": 0, "text": "Hej Bo.", "talare": 2, "fran": 1}, headers=H)
        self.assertEqual(r.status_code, 200, r.get_json())
        m = self.klient.get(url).get_json()
        self.assertEqual([(s["speaker"], s["text"]) for s in m["resultat"]["segment"]],
                         [(1, "Hej"), (2, "Bo. Hej Anna.")])
        self.assertIn("**Talare 2** (00:00): Bo. Hej Anna.", self.klient.get(f"{url}/text.md").get_data(as_text=True))
        lista = self.klient.get("/api/inspelningar").get_json()["inspelningar"]
        self.assertTrue(lista[0]["rattad"])
        # ny talare för hela första repliken
        r = self.klient.post(f"{url}/talare", json={"replik": 0, "text": "Hej", "talare": "ny"}, headers=H)
        self.assertEqual(r.get_json()["talare"], 3)
        # alla repliker från talare 3 är talare 2: allt blir en replik, en talare
        r = self.klient.post(f"{url}/talare", json={"replik": 0, "text": "Hej", "talare": 2, "alla": True}, headers=H)
        res = self.klient.get(url).get_json()["resultat"]
        self.assertEqual([(s["speaker"], s["text"]) for s in res["segment"]], [(2, "Hej Bo. Hej Anna.")])
        self.assertEqual(res["talare"], 1)
        # ångra: tillbaka till maskinens version
        self.assertEqual(self.klient.post(f"{url}/talare/angra", headers=H).status_code, 200)
        res = self.klient.get(url).get_json()["resultat"]
        self.assertEqual([(s["speaker"], s["text"]) for s in res["segment"]], [(1, "Hej Bo."), (2, "Hej Anna.")])
        self.assertNotIn("segment_original", res)
        self.assertEqual(self.klient.post(f"{url}/talare/angra", headers=H).status_code, 409)

    def test_ratta_talare_avvisar_fel(self):
        id_ = self.ladda_upp()
        url = f"/api/inspelningar/{id_}/talare"
        fall = [
            ({"replik": 0, "text": "Något annat", "talare": 2}, 409),  # texten har ändrats
            ({"replik": 9, "text": "Hej Bo.", "talare": 2}, 400),
            ({"replik": 0, "text": "Hej Bo.", "talare": 0}, 400),
            ({"replik": 0, "text": "Hej Bo.", "talare": True}, 400),
            ({"replik": 0, "text": "Hej Bo.", "talare": 2, "fran": 5}, 400),
            ({"replik": 0, "text": "Hej Bo.", "talare": 2, "fran": "1"}, 400),
        ]
        for data, kod in fall:
            self.assertEqual(self.klient.post(url, json=data, headers=H).status_code, kod, data)
        self.assertEqual(self.klient.post(url, json={"replik": 0, "text": "Hej Bo.", "talare": 2}).status_code, 403)

    def test_gor_om_tar_bort_rattningarna(self):
        id_ = self.ladda_upp()
        self.klient.post(f"/api/inspelningar/{id_}/talare", json={"replik": 0, "text": "Hej Bo.", "talare": 2}, headers=H)
        self.klient.post(f"/api/inspelningar/{id_}/transkribera", json={"talare": "2"}, headers=H)
        akasha._ko.join()
        res = self.klient.get(f"/api/inspelningar/{id_}").get_json()["resultat"]
        self.assertNotIn("segment_original", res)
        self.assertEqual(len(res["segment"]), 2)

    def test_ljud_kan_laddas_ner(self):
        id_ = self.ladda_upp(titel="Möte med A/B")
        # with: send_file haller filen oppen tills svaret stangs, och Windows tar inte bort en oppen fil.
        with self.klient.get(f"/api/inspelningar/{id_}/ljud?ladda_ner=1") as r:
            self.assertEqual(r.status_code, 200)
            self.assertIn("attachment", r.headers["Content-Disposition"])
            self.assertIn("M%C3%B6te%20med%20A-B.m4a", r.headers["Content-Disposition"])

    def test_ljud_kan_spolas(self):
        id_ = self.ladda_upp(innehall=b"0123456789")
        with self.klient.get(f"/api/inspelningar/{id_}/ljud", headers={"Range": "bytes=2-4"}) as r:
            self.assertEqual(r.status_code, 206)
            self.assertEqual(r.get_data(), b"234")

    def test_framsteg_visar_hur_lange_steget_har_hallit_pa(self):
        id_ = self.klient.post("/api/inspelningar", headers=H, json={"andelse": ".webm"}).get_json()["id"]
        lagring.uppdatera(id_, status="transkriberar")
        klocka = [1000.0]
        try:
            with mock.patch.object(akasha.time, "monotonic", lambda: klocka[0]):
                akasha._satt(id_, "transkriberar", 0.0)
                klocka[0] = 1030.0
                akasha._satt(id_, "transkriberar", 0.25)  # samma steg: starttiden ligger kvar
                klocka[0] = 1040.0
                f = self.klient.get(f"/api/inspelningar/{id_}").get_json()["framsteg"]
                self.assertEqual(f, {"fas": "transkriberar", "andel": 0.25, "sekunder": 40.0})
                lista = self.klient.get("/api/inspelningar").get_json()["inspelningar"]
                self.assertEqual(lista[0]["framsteg"]["sekunder"], 40.0)

                lagring.uppdatera(id_, status="talare")
                akasha._satt(id_, "talare", 0.1)  # nytt steg: tiden borjar om
                klocka[0] = 1045.0
                f = self.klient.get(f"/api/inspelningar/{id_}").get_json()["framsteg"]
                self.assertEqual(f, {"fas": "talare", "andel": 0.1, "sekunder": 5.0})

            # Utan starttid (som i aldre kod) skickas inget tidsfalt.
            akasha._framsteg[id_] = {"fas": "transkriberar", "andel": 0.5}
            f = self.klient.get(f"/api/inspelningar/{id_}").get_json()["framsteg"]
            self.assertEqual(f, {"fas": "transkriberar", "andel": 0.5})
        finally:
            akasha._framsteg.pop(id_, None)

    def test_ovantat_fel_ger_json(self):
        with mock.patch.object(lagring, "lista", side_effect=RuntimeError("disken borta")):
            r = self.klient.get("/api/inspelningar")
        self.assertEqual(r.status_code, 500)
        self.assertIn("disken borta", r.get_json()["error"])
        self.assertEqual(self.klient.get("/finns-inte").get_json()["error"].split()[0], "The")

    def test_transcribe_direkt(self):
        r = self.klient.post("/transcribe", headers=H, content_type="multipart/form-data",
                             data={"audio": (io.BytesIO(b"ljud"), "a.m4a"), "speakers": "2"})
        svar = r.get_json()
        self.assertEqual(r.status_code, 200, svar)
        self.assertEqual(svar["speakers"], 2)
        self.assertEqual(svar["segments"][1]["text"], "Hej Anna.")



class TestModellerApi(unittest.TestCase):
    """API:t for hamtningen mot den falska Hugging Face. motor.problem och talare.problem patchas inte."""

    def setUp(self):
        hjalp.tom_datakatalog()
        self.klient = akasha.app.test_client()
        self.paket, self.innehall = falska_paket(storlek_per_fil=20_000, storlek_for={"model.bin": 200_000})
        self.adapter = FalskHF(self.innehall)
        self.hamtningar = 0
        riktig = modeller.hamta

        def rakna(*a, **kw):
            self.hamtningar += 1
            return riktig(*a, **kw)

        gammal = modeller.HAMTNING
        modeller.HAMTNING = modeller.Hamtning()
        self.addCleanup(setattr, modeller, "HAMTNING", gammal)
        for patch in (mock.patch.object(modeller, "PAKET", self.paket),
                      mock.patch.object(modeller, "PAUSER", (0, 0)),
                      mock.patch.object(modeller, "hamta", rakna),
                      mock.patch.object(modeller, "ny_session", lambda: session_med(self.adapter))):
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        modeller.HAMTNING.vanta(5)
        motor.AKTIV = "faster"

    def get(self):
        svar = self.klient.get("/api/modeller")
        self.assertEqual(svar.status_code, 200)
        return svar.get_json()

    def post(self, vag="hamta", headers=H, **kw):
        return self.klient.post("/api/modeller/" + vag, headers=headers, **kw)

    def sokvag(self, fil):
        return "/" + fil.repo + "/resolve/" + fil.revision + "/" + fil.namn

    def modell_bin(self):
        return self.paket["faster", "medium"][0]

    def skriv(self, filer):
        for fil in filer:
            os.makedirs(os.path.dirname(fil.sokvag()), exist_ok=True)
            with open(fil.sokvag(), "wb") as f:
                f.write(self.innehall[self.sokvag(fil)])

    def vanta_pa(self, villkor):
        for _ in range(500):
            svar = self.get()
            if villkor(svar):
                return svar
            threading.Event().wait(0.01)
        self.fail("villkoret uppfylldes aldrig")

    def anrop_till(self, fil):
        return [rang for url, rang in self.adapter.anrop if url.endswith("/" + fil.namn) and "cdn" in url]

    def test_1_tom_modellkatalog(self):
        svar = self.get()
        self.assertFalse(svar["redo"])
        self.assertIsNone(svar["hinder"])
        self.assertEqual([p["id"] for p in svar["saknas"]], ["taligenkanning", "talare"])
        self.assertEqual(svar["totalt"], sum(p["storlek"] for p in svar["saknas"]))
        self.assertEqual(svar["saknas"][0]["namn"], "KB-Whisper medium")
        self.assertEqual(svar["saknas"][0]["kalla"], "huggingface.co/KBLab/kb-whisper-medium")
        self.assertEqual(svar["saknas"][1]["licens"], "CC-BY-4.0")
        self.assertEqual(svar["hamtning"]["tillstand"], "vilar")
        self.assertEqual(self.klient.get("/health").status_code, 503)

    def test_2_post_kraver_rubrik_och_ratt_origin(self):
        self.assertEqual(self.klient.post("/api/modeller/hamta").status_code, 403)
        self.assertEqual(self.post(headers={**H, "Origin": "https://annan.example"}).status_code, 403)
        self.assertEqual(self.adapter.anrop, [])

    def test_3_hamtning_ger_redo_utan_omstart(self):
        svar = self.post()
        self.assertEqual(svar.status_code, 202)
        self.assertEqual(svar.get_json()["hamtning"]["tillstand"], "hamtar")
        modeller.HAMTNING.vanta(5)
        svar = self.get()
        self.assertEqual(svar["saknas"], [])
        self.assertTrue(svar["redo"])
        self.assertEqual(svar["hamtning"]["tillstand"], "klar")
        halsa = self.klient.get("/health")
        self.assertEqual(halsa.status_code, 200)
        self.assertEqual(halsa.get_json()["status"], "ok")

    def test_4_fel_kontrollsumma_och_nytt_forsok(self):
        self.adapter.trasig_sokvag = self.sokvag(self.modell_bin())
        self.adapter.trasig_ganger = 1
        self.assertEqual(self.post().status_code, 202)
        modeller.HAMTNING.vanta(5)
        h = self.get()["hamtning"]
        self.assertEqual((h["tillstand"], h["felkod"]), ("fel", "kontrollsumma"))
        self.assertIn("KB-Whisper medium", h["fel"])
        self.assertNotIn("model.bin", h["fel"])
        self.assertEqual(self.post().status_code, 202)
        modeller.HAMTNING.vanta(5)
        self.assertEqual(self.get()["hamtning"]["tillstand"], "klar")

    def test_5_avbrott_efter_egna_omforsok_och_fortsattning(self):
        self.adapter.bryt_efter = 50_000
        self.adapter.bryt_ganger = 10
        self.post()
        modeller.HAMTNING.vanta(5)
        h = self.get()["hamtning"]
        self.assertEqual((h["tillstand"], h["felkod"]), ("fel", "avbrott"))
        self.assertTrue(os.path.exists(self.modell_bin().sokvag() + ".delvis"))
        self.adapter.bryt_efter = None
        self.post()
        modeller.HAMTNING.vanta(5)
        self.assertIsNotNone(self.anrop_till(self.modell_bin())[-1])  # Range-rubriken
        self.assertEqual(self.get()["hamtning"]["tillstand"], "klar")

    def test_6_post_under_pagaende_hamtning_startar_ingen_ny(self):
        self.adapter.fordrojning = 0.2
        self.assertEqual(self.post().status_code, 202)
        svar = self.post()
        self.assertEqual(svar.status_code, 200)
        self.assertEqual(svar.get_json()["hamtning"]["tillstand"], "hamtar")
        modeller.HAMTNING.vanta(10)
        self.assertEqual(self.hamtningar, 1)
        self.assertEqual(self.get()["hamtning"]["tillstand"], "klar")

    def test_7_bara_rostmodellen_saknas(self):
        self.skriv(self.paket["faster", "medium"])
        svar = self.get()
        self.assertEqual([p["id"] for p in svar["saknas"]], ["talare"])
        self.assertTrue(svar["redo"])
        self.assertEqual(self.post().status_code, 202)
        modeller.HAMTNING.vanta(5)
        self.assertEqual(self.get()["saknas"], [])
        self.assertEqual({u.split("/")[-1] for u, _ in self.adapter.anrop}, {"nemo_en_titanet_small.onnx"})

    def test_8_hinder(self):
        with mock.patch.object(motor, "MOTOR", "whispercpp"), mock.patch.object(plattform, "whisper_cli", lambda: None):
            svar = self.get()
            self.assertEqual(svar["hinder"], "whisper-cli saknas. Kör: brew install whisper-cpp")
            self.assertEqual(svar["saknas"], [])
            self.assertFalse(svar["redo"])
            post = self.post()
            self.assertEqual(post.status_code, 409)
            self.assertEqual(post.get_json()["error"], svar["hinder"])
        self.assertEqual(self.adapter.anrop, [])

    def test_9_kroppen_ignoreras(self):
        svar = self.post(json={"url": "https://annan.example/x", "sokvag": "/etc"})
        self.assertEqual(svar.status_code, 202)
        modeller.HAMTNING.vanta(5)
        self.assertEqual({u.split("/")[2] for u, _ in self.adapter.anrop}, {"huggingface.co", "cdn.test.hf.co"})
        skrivna = [os.path.join(rot, namn) for rot, _, namn_ in os.walk(hjalp.DATA) for namn in namn_]
        self.assertTrue(skrivna)
        for sokvag in skrivna:
            self.assertTrue(sokvag.startswith(modeller.MODELLKATALOG + os.sep), sokvag)

    def test_10_avbryt_skyddas(self):
        self.assertEqual(self.klient.post("/api/modeller/avbryt").status_code, 403)
        svar = self.post("avbryt", headers={**H, "Origin": "https://annan.example"})
        self.assertEqual(svar.status_code, 403)

    def test_11_avbryt_nar_inget_pagar(self):
        svar = self.post("avbryt")
        self.assertEqual(svar.status_code, 200)
        self.assertEqual(svar.get_json()["hamtning"]["tillstand"], "vilar")
        self.assertFalse(svar.get_json()["hamtning"]["stoppas"])

    def avbryt_under_hamtning(self):
        """Startar med model.bin som enda saknade fil i taligenkanningen och stoppar den mitt i."""
        kvar = self.paket["faster", "medium"][0]
        self.skriv(self.paket["faster", "medium"][1:])
        self.adapter.fordrojning = 0.3
        self.assertEqual(self.post().status_code, 202)
        self.vanta_pa(lambda s: s["hamtning"]["hamtat"] > 0)
        svar = self.post("avbryt")
        self.assertEqual(svar.status_code, 202)
        self.assertTrue(svar.get_json()["hamtning"]["stoppas"])
        modeller.HAMTNING.vanta(5)
        return kvar

    def test_12_avbryt_under_hamtning_och_fortsatt(self):
        kvar = self.avbryt_under_hamtning()
        svar = self.get()
        h = svar["hamtning"]
        self.assertEqual((h["tillstand"], h["stoppas"], h["fel"], h["felkod"]), ("avbruten", False, None, None))
        self.assertTrue(os.path.exists(kvar.sokvag() + ".delvis"))
        self.assertFalse(os.path.exists(kvar.sokvag()))
        for fil in self.paket["faster", "medium"][1:]:
            self.assertTrue(modeller.komplett(fil))  # kompletta filer ligger kvar
        self.assertGreater(svar["redan_hamtat"], 0)
        self.adapter.fordrojning = 0
        self.assertEqual(self.post().status_code, 202)
        modeller.HAMTNING.vanta(5)
        self.assertIsNotNone(self.anrop_till(kvar)[-1])  # Range: fortsatte dar den slutade
        self.assertEqual(self.get()["hamtning"]["tillstand"], "klar")

    def test_13_nytt_avbrott_stoppar_inte_nasta_hamtning(self):
        self.avbryt_under_hamtning()
        self.adapter.fordrojning = 0
        self.post()
        modeller.HAMTNING.vanta(5)
        svar = self.get()
        self.assertEqual((svar["hamtning"]["tillstand"], svar["saknas"]), ("klar", []))


class TestHallVaken(unittest.TestCase):
    def test_caffeinate_startas_och_stoppas_pa_mac(self):
        process = mock.Mock()
        with mock.patch.object(plattform.platform, "system", return_value="Darwin"), \
             mock.patch.object(plattform.shutil, "which", return_value="/usr/bin/caffeinate"), \
             mock.patch.object(plattform.subprocess, "Popen", return_value=process) as popen:
            with plattform.hall_vaken():
                popen.assert_called_once_with(["caffeinate", "-i", "-w", str(os.getpid())])
                process.terminate.assert_not_called()
        process.terminate.assert_called_once()

    def test_inget_pa_andra_system(self):
        with mock.patch.object(plattform.platform, "system", return_value="Linux"), \
             mock.patch.object(plattform.subprocess, "Popen") as popen:
            with plattform.hall_vaken():
                pass
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
