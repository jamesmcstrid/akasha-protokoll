"""Tillaggen: laddning, api-objektet och krokarna i programmet. Ett tillagg skrivs som en riktig fil i en temporar katalog."""
import itertools
import os
import shutil
import tempfile
import textwrap
import threading
import unittest
from unittest import mock

import hjalp
import app as akasha
import installningar
import lagring
import motor
import plattform
import start
import tillagg

H = {"X-Akasha-Protokoll": "1"}
NYTT_ID = itertools.count(1)

# Ett tillagg med en GET- och en POST-vag och en statisk katalog.
TILLAGG_OK = '''
import os
NAMN = "Prov"
VERSION = "0.1"
KRAVER_API = 1

def registrera(api):
    @api.route("/hej")
    def hej():
        return {"hej": "varlden"}

    @api.route("/skicka", methods=["POST"])
    def skicka():
        return {"ok": True}

    api.statisk(os.path.join(os.path.dirname(__file__), "static"))
'''


class Bas(unittest.TestCase):
    """Flask tar inte emot nya vagar efter den forsta begaran (setupmethod kontrollerar app._got_first_request).
    Resten av testsviten har redan gjort anrop mot samma app, sa ladda() kors har med flaggan tillfalligt
    avstangd: det motsvarar det som forbered() gor i det riktiga programmet, dar laddningen sker fore servern.
    Vagar gar inte att ta bort igen, sa varje test som lagger vagar far ett eget id (ny_katalog) och ett
    tillagg som inte blev aktivt svarar 404 (api._skydda)."""

    @classmethod
    def setUpClass(cls):
        akasha.starta_arbetare()

    def setUp(self):
        hjalp.tom_datakatalog()
        tillagg._nollstall()
        self.bas = tempfile.mkdtemp(prefix="akasha-tillagg-test-")
        self.klient = akasha.app.test_client()

    def tearDown(self):
        tillagg._nollstall()
        shutil.rmtree(self.bas, ignore_errors=True)

    def ny_katalog(self, kod=TILLAGG_OK, namn=None, statisk=None):
        """Skriver ett tillagg i self.bas. -> id."""
        id_ = namn or f"prov{next(NYTT_ID)}"
        katalog = os.path.join(self.bas, id_)
        os.makedirs(katalog)
        with open(os.path.join(katalog, "tillagg.py"), "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(kod))
        for filnamn, innehall in (statisk or {}).items():
            os.makedirs(os.path.join(katalog, "static"), exist_ok=True)
            with open(os.path.join(katalog, "static", filnamn), "w", encoding="utf-8") as f:
                f.write(innehall)
        return id_

    def ladda(self):
        with mock.patch.object(installningar, "TILLAGG", self.bas), \
             mock.patch.object(akasha.app, "_got_first_request", False):
            return tillagg.ladda(akasha)

    def ny_inspelning(self, status="spelar_in"):
        meta = lagring.ny_inspelning(".webm", "Prov", {"talare": "2", "ord": "", "kalla": "rum"})
        if status != "spelar_in":
            meta = lagring.uppdatera(meta["id"], status=status)
        return meta["id"]


class TestLaddning(Bas):
    def test_utan_tillagg_ar_allt_som_forut(self):
        self.assertEqual(self.ladda(), [])
        self.assertEqual(self.klient.get("/api/tillagg").get_json(), {"api": 1, "aktiva": [], "problem": []})
        with mock.patch.object(motor, "uppdatera"), mock.patch.object(motor, "problem", return_value=None):
            h = self.klient.get("/health").get_json()
        self.assertEqual(h["tillagg"], [])
        self.assertEqual(h["status"], "ok")
        self.assertEqual(self.klient.get("/api/inspelningar").get_json(), {"inspelningar": []})

    def test_status_har_inga_sokvagar(self):
        id_ = self.ny_katalog()
        self.ladda()
        status = self.klient.get("/api/tillagg").get_json()
        self.assertEqual(status["aktiva"], [{"id": id_, "namn": "Prov", "version": "0.1"}])
        self.assertNotIn(self.bas, str(status))
        with mock.patch.object(motor, "uppdatera"), mock.patch.object(motor, "problem", return_value=None):
            self.assertEqual(self.klient.get("/health").get_json()["tillagg"], [id_])

    def test_ladda_ar_idempotent(self):
        self.ny_katalog()
        forsta = self.ladda()
        self.assertEqual(len(forsta), 1)
        self.ny_katalog()  # kommer efter laddningen
        self.assertEqual(self.ladda(), forsta)

    def test_version_ar_valfri(self):
        self.ny_katalog('NAMN = "Utan"\nKRAVER_API = 1\ndef registrera(api):\n    pass\n')
        self.assertIsNone(self.ladda()[0]["version"])

    def test_programkatalogen_soks_efter_TILLAGG_och_forsta_traffen_vinner(self):
        program = os.path.join(self.bas, "program", "tillagg")
        egen = os.path.join(self.bas, "egen")
        os.makedirs(program)
        os.makedirs(egen)
        for bas, namn in ((egen, "Fran TILLAGG"), (program, "Fran programkatalogen")):
            os.makedirs(os.path.join(bas, "dubbel"))
            with open(os.path.join(bas, "dubbel", "tillagg.py"), "w") as f:
                f.write(f'NAMN = "{namn}"\nKRAVER_API = 1\ndef registrera(api):\n    pass\n')
        os.makedirs(os.path.join(program, "bara_program"))
        with open(os.path.join(program, "bara_program", "tillagg.py"), "w") as f:
            f.write('NAMN = "Bara programmet"\nKRAVER_API = 1\ndef registrera(api):\n    pass\n')
        os.makedirs(os.path.join(program, "inget_tillagg"))  # ingen tillagg.py: ignoreras utan problem
        with mock.patch.object(installningar, "TILLAGG", egen), \
             mock.patch.object(plattform, "programkatalog", return_value=os.path.dirname(program)):
            aktiva = tillagg.ladda(akasha)
        self.assertEqual({a["id"]: a["namn"] for a in aktiva},
                         {"dubbel": "Fran TILLAGG", "bara_program": "Bara programmet"})
        self.assertEqual(tillagg.status()["problem"], [])

    def test_fel_kraver_api_ger_inget_aktivt_tillagg(self):
        id_ = self.ny_katalog('NAMN = "Nytt"\nKRAVER_API = 2\ndef registrera(api):\n    raise AssertionError("ska inte anropas")\n')
        self.assertEqual(self.ladda(), [])
        status = self.klient.get("/api/tillagg").get_json()
        self.assertEqual(status["aktiva"], [])
        self.assertEqual(len(status["problem"]), 1)
        self.assertIn(id_, status["problem"][0])
        self.assertEqual(self.klient.get("/api/inspelningar").status_code, 200)

    def test_import_som_kastar_ger_problem_och_loggas(self):
        self.ny_katalog('raise RuntimeError("trasig")\n')
        with self.assertLogs("akasha-protokoll.tillagg", "WARNING"):
            self.assertEqual(self.ladda(), [])
        self.assertEqual(len(tillagg.status()["problem"]), 1)
        self.assertNotIn("trasig", tillagg.status()["problem"][0])
        self.assertEqual(self.klient.get("/api/inspelningar").status_code, 200)

    def test_registrera_som_kastar_lamnar_varken_vagar_eller_krokar_kvar(self):
        id_ = self.ny_katalog('''
            NAMN = "Halv"
            KRAVER_API = 1
            def registrera(api):
                api.vid_start(lambda: None)
                @api.route("/halv")
                def halv():
                    return {}
                raise RuntimeError("fel i registrera")
        ''')
        with self.assertLogs("akasha-protokoll.tillagg", "WARNING"):
            self.assertEqual(self.ladda(), [])
        self.assertEqual(tillagg._krokar["start"], [])
        self.assertEqual(self.klient.get(f"/api/tillagg/{id_}/halv").status_code, 404)

    def test_ogiltigt_namn_och_saknade_delar_ger_problem(self):
        self.ny_katalog(TILLAGG_OK, namn="Fel-Namn")
        self.ny_katalog('KRAVER_API = 1\ndef registrera(api):\n    pass\n')  # saknar NAMN
        self.ny_katalog('NAMN = "x"\ndef registrera(api):\n    pass\n')  # saknar KRAVER_API
        self.assertEqual(self.ladda(), [])
        self.assertEqual(len(tillagg.status()["problem"]), 3)

    def test_tilleggets_egna_moduler_gar_att_importera(self):
        id_ = self.ny_katalog('import syster\nNAMN = syster.NAMN\nKRAVER_API = 1\ndef registrera(api):\n    pass\n')
        with open(os.path.join(self.bas, id_, "syster.py"), "w") as f:
            f.write('NAMN = "Med syster"\n')
        try:
            self.assertEqual(self.ladda()[0]["namn"], "Med syster")
        finally:
            import sys
            sys.modules.pop("syster", None)


class TestVagar(Bas):
    def setUp(self):
        super().setUp()
        self.id = self.ny_katalog(statisk={"tillagg.js": "console.log(1);", "hemlig.txt": "x"})
        with open(os.path.join(self.bas, "hemlig-utanfor.txt"), "w") as f:
            f.write("utanfor tilleggets static-katalog")
        self.ladda()

    def test_get_och_post_under_api_tillagg_id(self):
        self.assertEqual(self.klient.get(f"/api/tillagg/{self.id}/hej").get_json(), {"hej": "varlden"})
        r = self.klient.post(f"/api/tillagg/{self.id}/skicka", headers=H)
        self.assertEqual((r.status_code, r.get_json()), (200, {"ok": True}))

    def test_post_utan_headern_ger_403(self):
        r = self.klient.post(f"/api/tillagg/{self.id}/skicka")
        self.assertEqual(r.status_code, 403)

    def test_fel_host_ger_403(self):
        r = self.klient.get(f"/api/tillagg/{self.id}/hej", headers={"Host": "exempel.se"})
        self.assertEqual(r.status_code, 403)

    def test_get_pa_en_postvag_ar_405(self):
        self.assertEqual(self.klient.get(f"/api/tillagg/{self.id}/skicka").status_code, 405)

    def test_statisk_fil_med_filtyp_och_nosniff(self):
        r = self.klient.get(f"/tillagg/{self.id}/tillagg.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "text/javascript")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.data, b"console.log(1);")
        r.close()

    def test_okand_filtyp_blir_octet_stream(self):
        with open(os.path.join(self.bas, self.id, "static", "data.xyz"), "w") as f:
            f.write("x")
        r = self.klient.get(f"/tillagg/{self.id}/data.xyz")
        self.assertEqual(r.mimetype, "application/octet-stream")
        r.close()

    def test_statisk_nekar_att_lamna_katalogen_och_saknade_filer(self):
        for sokvag in ("../hemlig-utanfor.txt", "..%2Fhemlig-utanfor.txt", "../tillagg.py", "saknas.js"):
            r = self.klient.get(f"/tillagg/{self.id}/{sokvag}")
            self.assertEqual(r.status_code, 404, sokvag)
            self.assertNotIn(b"utanfor tilleggets", r.data)

    def test_statisk_tar_bara_get(self):
        r = self.klient.post(f"/tillagg/{self.id}/tillagg.js", headers=H)
        self.assertEqual(r.status_code, 405)


class TestKo(Bas):
    def test_koa_kor_funktionen_i_arbetstraden_och_haller_datorn_vaken(self):
        api = tillagg.Api(akasha, "prov")
        trad = []
        with mock.patch.object(plattform, "hall_vaken") as vaken:
            api.koa(lambda: trad.append(threading.current_thread().name))
            akasha._ko.join()
        self.assertEqual(trad, ["transkribering"])
        vaken.return_value.__enter__.assert_called_once_with()

    def test_ett_jobb_som_kastar_stoppar_inte_de_nasta(self):
        api = tillagg.Api(akasha, "prov")
        kord = []

        def kastar():
            raise RuntimeError("fel i jobbet")

        with self.assertLogs("akasha-protokoll", "ERROR"):
            api.koa(kastar)
            api.koa(lambda: kord.append("efter"))
            akasha._ko.join()
        self.assertEqual(kord, ["efter"])
        self.assertEqual(akasha._ko.unfinished_tasks, 0)

    def test_koa_nekar_det_som_inte_ar_en_funktion(self):
        with self.assertRaises(TypeError):
            tillagg.Api(akasha, "prov").koa("20261117-140312")


class TestKrokar(Bas):
    def setUp(self):
        super().setUp()
        self.api = tillagg.Api(akasha, "prov")

    def test_vid_inspelning_laggs_till_under_tillagg(self):
        id_ = self.ny_inspelning()
        self.api.vid_inspelning(lambda meta: {"id": meta["id"], "antal": 3})
        andra = tillagg.Api(akasha, "annat")
        andra.vid_inspelning(lambda meta: None)  # None: ingen post
        svar = self.klient.get(f"/api/inspelningar/{id_}").get_json()
        self.assertEqual(svar["tillagg"], {"prov": {"id": id_, "antal": 3}})

    def test_ingen_tillagg_post_utan_svar_och_ett_undantag_hoppas_over(self):
        id_ = self.ny_inspelning()
        self.assertNotIn("tillagg", self.klient.get(f"/api/inspelningar/{id_}").get_json())

        def kastar(meta):
            raise RuntimeError("fel")

        self.api.vid_inspelning(kastar)
        with self.assertLogs("akasha-protokoll.tillagg", "ERROR"):
            svar = self.klient.get(f"/api/inspelningar/{id_}")
        self.assertEqual(svar.status_code, 200)
        self.assertNotIn("tillagg", svar.get_json())

    def test_vid_radera_far_ta_bort_sina_egna_filer(self):
        id_ = self.ny_inspelning()
        egen = os.path.join(hjalp.DATA, f"{id_}.x")
        with open(egen, "w") as f:
            f.write("tilleggets fil")
        anrop = []

        def radera(i):
            anrop.append(i)
            os.remove(egen)

        self.api.vid_radera(radera)
        r = self.klient.post(f"/api/inspelningar/{id_}/radera", headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(anrop, [id_])
        self.assertFalse(os.path.exists(egen))
        self.assertFalse(os.path.exists(os.path.join(hjalp.DATA, f"{id_}.json")))

    def test_vid_radera_som_kastar_stoppar_inte_raderingen(self):
        id_ = self.ny_inspelning()

        def kastar(i):
            raise RuntimeError("fel")

        self.api.vid_radera(kastar)
        with self.assertLogs("akasha-protokoll.tillagg", "ERROR"):
            r = self.klient.post(f"/api/inspelningar/{id_}/radera", headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(os.path.exists(os.path.join(hjalp.DATA, f"{id_}.json")))

    def test_hindrar_ger_409_med_texten_for_radera_och_transkribera_igen(self):
        id_ = self.ny_inspelning("sparad")
        self.api.hindrar(lambda meta: f"Används av ett tillägg ({meta['id']}).")
        for url in (f"/api/inspelningar/{id_}/radera", f"/api/inspelningar/{id_}/transkribera"):
            r = self.klient.post(url, headers=H)
            self.assertEqual(r.status_code, 409, url)
            self.assertEqual(r.get_json()["error"], f"Används av ett tillägg ({id_}).")
        self.assertEqual(lagring.las(id_)["status"], "sparad")  # ingenting hann andras
        self.assertTrue(os.path.exists(os.path.join(hjalp.DATA, f"{id_}.json")))

    def test_hindrar_som_ger_none_eller_kastar_hindrar_inte(self):
        id_ = self.ny_inspelning()
        self.api.hindrar(lambda meta: None)

        def kastar(meta):
            raise RuntimeError("fel")

        self.api.hindrar(kastar)
        with self.assertLogs("akasha-protokoll.tillagg", "ERROR"):
            r = self.klient.post(f"/api/inspelningar/{id_}/radera", headers=H)
        self.assertEqual(r.status_code, 200)

    def test_vid_start_anropas_av_forbered_och_vid_stopp_av_stang(self):
        start_anrop, stopp_anrop = [], []
        self.api.vid_start(lambda: start_anrop.append(1))
        self.api.vid_stopp(lambda: stopp_anrop.append(1))
        with mock.patch.object(motor, "stada_kvarglomda"), \
             mock.patch.object(akasha, "starta_arbetare"), \
             mock.patch.object(lagring, "stada_halvfardiga"), \
             mock.patch.object(lagring, "aterstall_avbrutna"):
            akasha.forbered()
        self.assertEqual((start_anrop, stopp_anrop), ([1], []))
        with mock.patch.object(motor, "stoppa") as stoppa:
            start.Tjanst(port=1).stang()
        stoppa.assert_called_once_with()
        self.assertEqual(stopp_anrop, [1])

    def test_vid_start_och_vid_stopp_som_kastar_loggas(self):
        def kastar():
            raise RuntimeError("fel")

        self.api.vid_start(kastar)
        self.api.vid_stopp(kastar)
        with self.assertLogs("akasha-protokoll.tillagg", "ERROR") as logg:
            tillagg.kor_vid_start()
            tillagg.kor_vid_stopp()
        self.assertEqual(len(logg.records), 2)


if __name__ == "__main__":
    unittest.main()
