"""Starten: portkontroll, tjansten i en trad, loggfil, fragan fore avslut. Riktiga socketar pa 127.0.0.1."""
import gc
import http.server
import io
import json
import logging
import os
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import warnings
from unittest import mock

import hjalp
import app as akasha
import installningar
import lagring
import modeller
import motor
import plattform
import start

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
INST = {"talare": "2", "ord": ""}


def ledig_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Stadning(unittest.TestCase):
    """Sparar och aterstaller det som loggningen ror vid, sa att inget laser kvar mellan testerna."""

    def setUp(self):
        rot = logging.getLogger()
        self.hanterare = list(rot.handlers)
        self.niva = rot.level
        self.excepthook = sys.excepthook
        self.trad_excepthook = threading.excepthook
        self.problem_loggade = start._problem_loggade
        self.katalog = tempfile.mkdtemp(prefix="akasha-meet-start-")
        p = mock.patch.object(plattform, "loggkatalog", lambda: os.path.join(self.katalog, "logg"))
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        rot = logging.getLogger()
        for h in list(rot.handlers):
            if h not in self.hanterare:
                rot.removeHandler(h)
                h.close()  # annars hålls loggfilen öppen, vilket stoppar borttagningen på Windows
        rot.setLevel(self.niva)
        sys.excepthook = self.excepthook
        threading.excepthook = self.trad_excepthook
        start._problem_loggade = self.problem_loggade
        shutil.rmtree(self.katalog, ignore_errors=True)


class FalskHalsa(http.server.BaseHTTPRequestHandler):
    kod = 200
    kropp = b"{}"
    typ = "application/json"

    def do_GET(self):
        self.send_response(self.kod)
        self.send_header("Content-Type", self.typ)
        self.send_header("Content-Length", str(len(self.kropp)))
        self.end_headers()
        self.wfile.write(self.kropp)

    def log_message(self, *a):
        pass


class Testserver(http.server.HTTPServer):
    """HTTPServer utan namnuppslag: server_bind() anropar annars socket.getfqdn(), som tog
    cirka 35 s forsta gangen pa GitHubs Mac-maskin. Namnet anvands inte av testerna."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


class TestLage(unittest.TestCase):
    def server(self, kod, kropp, typ="application/json"):
        klass = type("H", (FalskHalsa,), {"kod": kod, "kropp": kropp, "typ": typ})
        srv = Testserver(("127.0.0.1", 0), klass)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(t.join, 5)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def test_ledig(self):
        port = ledig_port()
        with mock.patch.object(urllib.request, "build_opener") as opener:
            t0 = time.monotonic()
            lage = start.lage(port)
            tid = time.monotonic() - t0
        self.assertEqual(lage, "ledig")
        self.assertLess(tid, 0.5)
        opener.assert_not_called()  # inget natanrop for en ledig port

    def test_bunden_men_inte_lyssnande_ar_annat(self):
        s = socket.socket()
        self.addCleanup(s.close)
        s.bind(("127.0.0.1", 0))  # utan SO_REUSEADDR och utan listen()
        t0 = time.monotonic()
        self.assertEqual(start.lage(s.getsockname()[1]), "annat")
        self.assertLess(time.monotonic() - t0, 2)

    def test_testservern_slar_inte_upp_namn(self):
        with mock.patch.object(socket, "getfqdn", side_effect=AssertionError("getfqdn anropades")):
            port = self.server(200, json.dumps({"motor": "faster", "datakatalog": "/x"}).encode())
            self.assertEqual(start.lage(port), "akasha")

    def test_akasha_med_200(self):
        svar = json.dumps({"motor": "faster", "datakatalog": "/x"}).encode()
        self.assertEqual(start.lage(self.server(200, svar)), "akasha")

    def test_akasha_med_503(self):
        svar = json.dumps({"motor": "faster", "datakatalog": "/x"}).encode()
        self.assertEqual(start.lage(self.server(503, svar)), "akasha")

    def test_annat_svar_ar_annat(self):
        self.assertEqual(start.lage(self.server(200, b"hej", "text/plain")), "annat")
        self.assertEqual(start.lage(self.server(200, b'{"status": "ok"}')), "annat")

    def test_lyssnar_men_svarar_aldrig(self):
        s = socket.socket()
        self.addCleanup(s.close)
        s.bind(("127.0.0.1", 0))
        s.listen(5)
        self.assertEqual(start.lage(s.getsockname()[1], tidsgrans=0.3), "annat")

    def test_proxy_i_miljon_anvands_inte(self):
        port = ledig_port()
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9"}):
            self.assertEqual(start.lage(port), "ledig")


class TestForbered(unittest.TestCase):
    def test_ta_over_fragar_inte_porten(self):
        with mock.patch.object(plattform, "gammal_tjanst_finns", lambda: True), \
             mock.patch.object(start, "lage") as lage:
            self.assertEqual(start.forbered(), "ta_over")
        lage.assert_not_called()

    def test_oversattning_av_lagena(self):
        with mock.patch.object(plattform, "gammal_tjanst_finns", lambda: False):
            for lage, beslut in (("akasha", "redan_igang"), ("annat", "upptagen"), ("ledig", "starta")):
                with mock.patch.object(start, "lage", return_value=lage):
                    self.assertEqual(start.forbered(), beslut)


class FalskServer:
    """Det Tjanst.stang() ror vid pa en waitress-server: task_dispatcher, trigger och _map."""

    def __init__(self):
        self.stangd = False
        self.anrop = []
        self._map = {}
        self.task_dispatcher = mock.Mock()
        self.trigger = mock.Mock()
        self.trigger.pull_trigger.side_effect = self._dra

    def _dra(self, funktion):
        self.anrop.append("pull_trigger")
        funktion()  # i waitress kor servertraden den; har finns ingen
        self.stangd = True

    def run(self):
        pass


class TestTjanst(Stadning):
    def setUp(self):
        super().setUp()
        hjalp.tom_datakatalog()
        p = mock.patch.object(motor, "stoppa")
        self.stoppa = p.start()
        self.addCleanup(p.stop)

    def test_starta_vanta_och_stang(self):
        port = ledig_port()
        t = start.Tjanst(port=port)
        t.starta()
        try:
            self.assertTrue(t.vanta(10))
            self.assertEqual(start.lage(port), "akasha")
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    f"http://127.0.0.1:{port}/", timeout=5) as r:
                self.assertEqual(r.status, 200)
        finally:
            t.stang()
        self.stoppa.assert_called_once()
        self.assertEqual(start.lage(port), "ledig")
        t.stang()  # far anropas igen

    def test_stang_utan_undantag_i_tradar(self):
        """Felet pa macOS (Bad file descriptor i waitress-traden och i en hanterartrad) var en
        kapplopning mellan stang() och en forfragan pa vag. Pa Linux gar testet igenom aven med
        den gamla koden (close() fran en annan trad); det ar enhetstesterna pa macOS som faller den."""
        for varv in range(10):
            with self.subTest(varv=varv):
                self._stang_med_forfragningar_pa_vag()

    def _stang_med_forfragningar_pa_vag(self):
        insamlade = []
        gammal = threading.excepthook
        threading.excepthook = lambda args: insamlade.append(
            f"{args.thread.name if args.thread else '?'}: {args.exc_type.__name__}: {args.exc_value}")
        try:
            port = ledig_port()
            t = start.Tjanst(port=port)
            t.starta()
            try:
                self.assertTrue(t.vanta(10))
                oppnare = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                def hamta(sokvag):
                    try:
                        with oppnare.open(f"http://127.0.0.1:{port}{sokvag}", timeout=10) as r:
                            r.read()
                    except OSError:
                        pass  # ett avbrutet svar vid stangningen ar tillatet; undantag i traden ar det inte

                klienter = [threading.Thread(target=hamta, args=(sokvag,), name="klient" + sokvag)
                            for sokvag in ("/health", "/api/modeller")]
                for k in klienter:
                    k.start()
                time.sleep(0.05)
            finally:
                t.stang()
            for k in klienter:
                k.join(15)
            self.assertFalse(any(k.is_alive() for k in klienter))
            self.assertFalse(t.trad.is_alive())
            self.assertEqual(start.lage(port), "ledig")
            self.assertEqual(insamlade, [])
        finally:
            threading.excepthook = gammal

    def test_stang_anropar_dispatcher_fore_trigger_och_stanger_kartan_inifran(self):
        falsk = FalskServer()
        falsk.task_dispatcher.shutdown.side_effect = lambda **kw: falsk.anrop.append("shutdown")
        t = start.Tjanst(port=1234)
        t.server = falsk
        with mock.patch("waitress.wasyncore.close_all") as close_all:
            t.stang()
            falsk.task_dispatcher.shutdown.assert_called_once_with(cancel_pending=True, timeout=5)
            self.assertEqual(falsk.anrop, ["shutdown", "pull_trigger"])
            close_all.assert_called_once_with(falsk._map)
        self.assertIsNone(t.server)
        self.stoppa.assert_called_once()

    def test_upptagen_port_ger_startfel_med_portnumret(self):
        s = socket.socket()
        self.addCleanup(s.close)
        s.bind(("127.0.0.1", 0))
        s.listen(5)
        port = s.getsockname()[1]
        with mock.patch.object(akasha, "forbered"):
            # Kand lacka i waitress 3.0.0: create_server() stadar inte pipe och socket nar bind
            # misslyckas, sa objektet nar aldrig var kod. Varningen doljs bara har, runt starta().
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                with self.assertRaises(start.StartFel) as e:
                    start.Tjanst(port=port).starta()
                meddelande = str(e.exception)
                del e  # undantaget haller traceback och ramar, och med dem det halvskapade servern
                gc.collect()
        self.assertIn(str(port), meddelande)

    def test_gamla_modeller_tas_bara_in_nar_programmet_ar_paketerat(self):
        for paketerad in (False, True):
            falsk = FalskServer()
            with mock.patch.object(modeller, "ta_in_gamla") as ta_in, \
                 mock.patch.object(plattform, "gamla_modellkataloger", lambda: ["/gammal"]), \
                 mock.patch.object(plattform, "ar_paketerad", lambda p=paketerad: p), \
                 mock.patch.object(akasha, "forbered"), \
                 mock.patch.object(akasha, "skapa_server", lambda port: falsk):
                t = start.Tjanst(port=1234)
                t.starta()
                t.stang()
            if paketerad:
                ta_in.assert_called_once_with(["/gammal"])
            else:
                ta_in.assert_not_called()
            self.assertTrue(falsk.stangd)


class TestLoggning(Stadning):
    def test_loggfilen_far_raderna_och_hanteraren_laggs_bara_till_en_gang(self):
        antal = len(logging.getLogger().handlers)
        sokvag = start.stall_in_loggning()
        self.assertEqual(sokvag, start.loggfil())
        self.assertEqual(start.stall_in_loggning(), sokvag)
        self.assertEqual(len(logging.getLogger().handlers), antal + 1)
        logging.getLogger("akasha-meet").info("hej fran provet")
        with open(sokvag, encoding="utf-8") as f:
            self.assertIn("INFO hej fran provet", f.read())
        self.assertIsNot(sys.excepthook, self.excepthook)  # ohanterade fel hamnar i loggen

    def test_ohanterat_fel_i_trad_hamnar_i_loggen(self):
        sokvag = start.stall_in_loggning()

        def kasta():
            raise RuntimeError("kraschprov")

        t = threading.Thread(target=kasta, name="prov")
        t.start()
        t.join()
        with open(sokvag, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("CRITICAL", text)
        self.assertIn("kraschprov", text)


class TestMain(Stadning):
    def test_redan_igang(self):
        with mock.patch.object(start, "forbered", return_value="redan_igang"), \
             mock.patch.object(plattform, "oppna_webblasare") as oppna:
            self.assertEqual(start.main(), 0)
        oppna.assert_called_once_with(start.url())

    def test_upptagen_skriver_portnumret_pa_stderr(self):
        err = io.StringIO()
        with mock.patch.object(start, "forbered", return_value="upptagen"), \
             mock.patch.object(sys, "stderr", err):
            self.assertEqual(start.main(), 1)
        self.assertIn(str(installningar.PORT), err.getvalue())

    def test_ta_over_kan_inte_fragas_utan_fonster(self):
        err = io.StringIO()
        with mock.patch.object(start, "forbered", return_value="ta_over"), \
             mock.patch.object(sys, "stderr", err):
            self.assertEqual(start.main(), 1)
        self.assertIn(start.TA_OVER_RUBRIK, err.getvalue())

    def test_installningsproblem_skrivs_pa_stderr_och_starten_fortsatter(self):
        err = io.StringIO()
        with mock.patch.object(installningar, "PROBLEM", ["Rad 3 förstods inte och hoppades över."]), \
             mock.patch.object(start, "forbered", return_value="redan_igang"), \
             mock.patch.object(plattform, "oppna_webblasare"), \
             mock.patch.object(sys, "stderr", err):
            self.assertEqual(start.main(), 0)
        self.assertIn("– Rad 3 förstods inte och hoppades över.", err.getvalue())
        with open(start.loggfil(), encoding="utf-8") as f:
            self.assertIn("WARNING installningar: Rad 3 förstods inte", f.read())


class TestImport(unittest.TestCase):
    def test_import_laddar_inga_installningar(self):
        kod = ("import sys; sys.path.insert(0, %r); import start; "
               "print([n for n in ('installningar', 'app', 'modeller', 'motor', 'lagring') if n in sys.modules])"
               % APP)
        ut = subprocess.run([sys.executable, "-I", "-c", kod], capture_output=True, text=True, timeout=60)
        self.assertEqual(ut.returncode, 0, ut.stderr)
        self.assertEqual(ut.stdout.strip(), "[]")


class TestPagar(unittest.TestCase):
    def setUp(self):
        hjalp.tom_datakatalog()
        self.addCleanup(hjalp.tom_datakatalog)

    def inspelning(self, status):
        m = lagring.ny_inspelning(".webm", "", INST)
        lagring.lagg_till_del(m["id"], 0, b"ljud")
        if status != "spelar_in":
            lagring.uppdatera(m["id"], status=status)
        return m

    def test_inget_pagar(self):
        self.assertEqual(start.pagar(), [])
        self.inspelning("klar")
        self.assertEqual(start.pagar(), [])

    def test_inspelning_som_nyss_fick_ljud(self):
        m = self.inspelning("spelar_in")
        self.assertEqual(start.pagar(), ["inspelning"])
        mtime = os.path.getmtime(lagring.ljudfil(m))
        self.assertEqual(start.pagar(nu=mtime + 30), [])  # tyst for lange: fliken ar troligen stangd
        self.assertEqual(start.pagar(nu=mtime + 30, tyst_sekunder=60), ["inspelning"])

    def test_transkribering(self):
        self.inspelning("transkriberar")
        self.assertEqual(start.pagar(), ["transkribering"])

    def test_hamtning(self):
        for tillstand, vad in (("hamtar", ["hamtning"]), ("kontrollerar", ["hamtning"]), ("vilar", [])):
            with mock.patch.object(modeller.HAMTNING, "status", return_value={"tillstand": tillstand}):
                self.assertEqual(start.pagar(), vad)

    def test_alla_tre_i_ordning(self):
        self.inspelning("spelar_in")
        self.inspelning("koar")
        with mock.patch.object(modeller.HAMTNING, "status", return_value={"tillstand": "hamtar"}):
            self.assertEqual(start.pagar(), ["inspelning", "transkribering", "hamtning"])

    def test_fel_ger_tom_lista(self):
        with mock.patch.object(lagring, "lista", side_effect=RuntimeError("trasigt")), \
             self.assertLogs("akasha-meet", "ERROR"):
            self.assertEqual(start.pagar(), [])


class TestTexter(Stadning):
    def test_avsluta_text(self):
        self.assertEqual(
            start.avsluta_text(["transkribering"]),
            "Akasha Meet arbetar fortfarande: en transkribering pågår.\n\n"
            "Transkriberingen avbryts. Du kan göra om den med Försök igen när du har öppnat Akasha Meet igen.")
        self.assertEqual(
            start.avsluta_text(["inspelning", "transkribering"]),
            "Akasha Meet arbetar fortfarande: en inspelning tas emot och en transkribering pågår.\n\n"
            "Inspelningen fortsätter i webbläsaren, och ljudet sparas i fliken tills du öppnar Akasha Meet igen. "
            "Stäng inte fliken. "
            "Transkriberingen avbryts. Du kan göra om den med Försök igen när du har öppnat Akasha Meet igen.")
        self.assertEqual(
            start.avsluta_text(["inspelning", "transkribering", "hamtning"]),
            "Akasha Meet arbetar fortfarande: en inspelning tas emot, en transkribering pågår och "
            "modellerna hämtas.\n\n"
            "Inspelningen fortsätter i webbläsaren, och ljudet sparas i fliken tills du öppnar Akasha Meet igen. "
            "Stäng inte fliken. "
            "Transkriberingen avbryts. Du kan göra om den med Försök igen när du har öppnat Akasha Meet igen. "
            "Hämtningen av modellerna stoppas. Det som redan är hämtat ligger kvar, och nästa gång fortsätter "
            "den där den slutade.")

    def test_installningsfel_text(self):
        with mock.patch.object(plattform, "installningsfil", lambda: "/x/installningar.env"):
            self.assertEqual(
                start.installningsfel_text(["A", "B"]),
                "Akasha Meet startar ändå och använder standardvärdet för det som inte gick att läsa:\n"
                "– A\n– B\n\nFilen:\n/x/installningar.env")

    def test_dialogtexterna_ordagrant(self):
        self.assertEqual(start.TA_OVER_RUBRIK, "Akasha Meet är redan installerat från Terminal")
        self.assertEqual(
            start.TA_OVER_TEXT,
            "Den gamla installationen är igång i bakgrunden och använder samma adress. Programmet kan ta över: "
            "den gamla stängs av och startar inte längre när du loggar in. Inspelningar och modeller ligger kvar "
            "och används av programmet.\n\n"
            "Vill du ha tillbaka den gamla senare kör du bash mac/installera.sh i Terminal igen.")
        self.assertEqual((start.TA_OVER_JA, start.TA_OVER_NEJ), ("Använd programmet", "Avbryt"))
        self.assertEqual(start.TA_OVER_MISSLYCKADES_RUBRIK, "Den gamla installationen gick inte att stänga av")
        self.assertEqual(start.TA_OVER_MISSLYCKADES_TEXT,
                         "Kör bash mac/avinstallera.sh i Terminal och öppna sedan Akasha Meet igen.")
        self.assertEqual(start.UPPTAGEN_RUBRIK, "Akasha Meet kan inte starta")
        self.assertEqual(
            start.UPPTAGEN_TEXT.format(port=8611, fil="/f"),
            "Ett annat program använder redan port 8611, som Akasha Meet behöver. Avsluta det programmet och "
            "öppna Akasha Meet igen. Du kan också välja en annan port med raden PORT= i inställningsfilen:\n/f")
        self.assertEqual(start.STARTADE_INTE_RUBRIK, "Akasha Meet startade inte")
        self.assertEqual(start.STARTADE_INTE_TEXT.format(logg="/l"),
                         "Något gick fel när Akasha Meet startade. Det som hände står i loggen:\n/l")
        self.assertEqual((start.VISA_LOGGEN, start.VISA_FILEN, start.OK), ("Visa loggen", "Visa filen", "OK"))
        self.assertEqual(start.INSTALLNINGSFEL_RUBRIK, "Inställningsfilen har fel")
        self.assertEqual((start.AVSLUTA_RUBRIK, start.AVSLUTA_NEJ, start.AVSLUTA_JA),
                         ("Vill du avsluta Akasha Meet?", "Avbryt", "Avsluta ändå"))


class TestHelaStarten(unittest.TestCase):
    def forbered(self):
        katalog = tempfile.mkdtemp(prefix="akasha-meet-hel-")
        self.addCleanup(shutil.rmtree, katalog, ignore_errors=True)
        self.katalog = katalog
        self.port = ledig_port()
        env = dict(os.environ, PORT=str(self.port), MOTOR="faster", BROWSER="true",
                   DATAKATALOG=os.path.join(katalog, "data"), MODELLKATALOG=os.path.join(katalog, "m"),
                   XDG_DATA_HOME=os.path.join(katalog, "xdg"), HOME=katalog)
        for namn in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
            env.pop(namn, None)
        self.env = env
        self.kor = [sys.executable, os.path.join(APP, "start.py")]
        forsta = subprocess.Popen(self.kor, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(forsta.kill)
        self.addCleanup(forsta.wait)
        for _ in range(200):
            if start.lage(self.port) == "akasha" or forsta.poll() is not None:
                break
            time.sleep(0.1)
        self.assertEqual(start.lage(self.port), "akasha")
        return forsta

    # Pa Mac oppnar oppna_webblasare den riktiga webblasaren med /usr/bin/open (BROWSER hjalper inte).
    @unittest.skipIf(sys.platform == "darwin", "oppnar den riktiga webblasaren pa Mac")
    def test_start_och_andra_start(self):
        forsta = self.forbered()
        andra = subprocess.run(self.kor, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5)
        self.assertEqual(andra.returncode, 0)
        self.assertIsNone(forsta.poll())  # den forsta gar fortfarande
        forsta.terminate()  # SIGTERM pa Unix, TerminateProcess pa Windows
        forsta.wait(20)
        self.assertIsNotNone(forsta.poll())

    @unittest.skipIf(os.name == "nt", "SIGTERM och ett rent avslut finns inte pa Windows")
    @unittest.skipIf(sys.platform == "darwin", "oppnar den riktiga webblasaren pa Mac")
    def test_sigterm_ger_rent_avslut(self):
        forsta = self.forbered()
        forsta.send_signal(signal.SIGTERM)
        self.assertEqual(forsta.wait(20), 0)
        self.assertEqual(start.lage(self.port), "ledig")
        with open(os.path.join(self.katalog, "xdg", "akasha-meet", "logg", "akasha-meet.log"),
                  encoding="utf-8") as f:
            self.assertIn("Akasha Meet avslutas", f.read())


if __name__ == "__main__":
    unittest.main()
