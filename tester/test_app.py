"""Webbtjansten med en lataskmotor: inga modeller behovs."""
import io
import json
import os
import unittest
from unittest import mock

import numpy as np

import hjalp
import app as akasha
import lagring
import motor
import talare

H = {"X-Akasha-Meet": "1"}
ORD = [(0.0, 0.5, " Hej"), (0.5, 1.0, " Bo."), (1.5, 2.0, " Hej"), (2.0, 2.5, " Anna.")]


def falsk_dela_upp(samples, ord_lista, antal, framsteg=None):
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
        r = self.klient.get("/")
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

    def test_utan_talarmodeller_blir_det_en_varning(self):
        with mock.patch.object(talare, "problem", lambda: "talarmodellerna saknas"):
            id_ = self.ladda_upp()
        res = self.klient.get(f"/api/inspelningar/{id_}").get_json()["resultat"]
        self.assertIn("inte uppdelad per talare", res["varning"])
        self.assertIsNone(res["talare"])

    def test_varning_nar_farre_roster_an_angivet(self):
        def en_rost(samples, ord_lista, antal, framsteg=None):
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

    def test_ljud_kan_spolas(self):
        id_ = self.ladda_upp(innehall=b"0123456789")
        r = self.klient.get(f"/api/inspelningar/{id_}/ljud", headers={"Range": "bytes=2-4"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.get_data(), b"234")

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


if __name__ == "__main__":
    unittest.main()
