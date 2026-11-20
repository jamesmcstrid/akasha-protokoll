"""Starten som ar gemensam for alla system: portkontroll, tjansten i en trad, loggfil, fragan fore
avslut och nedstangningen. Mac-skalet (mac_app.py) och `python app/start.py` anvander samma kod.

Pa modulnivan importeras bara standardbiblioteket och plattform (som inte laser nagra
installningar nar den importeras). installningar, app, lagring, modeller och motor importeras i
funktionerna, sa att `import start` aldrig kan misslyckas och loggningen alltid hinner stallas in
fore allt som laser installningar.
"""
import http.client
import json
import logging
import logging.handlers
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import plattform

log = logging.getLogger("akasha-protokoll")

# --- texter till anvandaren (B2 och B7 i planen) ---------------------------------------------

OK = "OK"
VISA_FILEN = "Visa filen"
VISA_LOGGEN = "Visa loggen"

INSTALLNINGSFEL_RUBRIK = "Inställningsfilen har fel"
INSTALLNINGSFEL_TEXT = "\n\n".join([
    "\n".join(["Akasha Protokoll startar ändå och använder standardvärdet för det som inte gick att läsa:",
               "{problem}"]),
    "\n".join(["Filen:", "{fil}"]),
])

TA_OVER_RUBRIK = "Akasha Protokoll är redan installerat från Terminal"
TA_OVER_TEXT = "\n\n".join([
    "Den gamla installationen är igång i bakgrunden och använder samma adress. Programmet kan ta över: "
    "den gamla stängs av och startar inte längre när du loggar in. Inspelningar och modeller ligger "
    "kvar och används av programmet.",
    "Vill du ha tillbaka den gamla senare kör du bash mac/installera.sh i Terminal igen.",
])
TA_OVER_JA = "Använd programmet"
TA_OVER_NEJ = "Avbryt"

TA_OVER_MISSLYCKADES_RUBRIK = "Den gamla installationen gick inte att stänga av"
TA_OVER_MISSLYCKADES_TEXT = "Kör bash mac/avinstallera.sh i Terminal och öppna sedan Akasha Protokoll igen."

UPPTAGEN_RUBRIK = "Akasha Protokoll kan inte starta"
UPPTAGEN_TEXT = "\n".join([
    "Ett annat program använder redan port {port}, som Akasha Protokoll behöver. Avsluta det programmet "
    "och öppna Akasha Protokoll igen. Du kan också välja en annan port med raden PORT= i inställningsfilen:",
    "{fil}",
])

STARTADE_INTE_RUBRIK = "Akasha Protokoll startade inte"
STARTADE_INTE_TEXT = "\n".join([
    "Något gick fel när Akasha Protokoll startade. Det som hände står i loggen:",
    "{logg}",
])

AVSLUTA_RUBRIK = "Vill du avsluta Akasha Protokoll?"
AVSLUTA_INLEDNING = {
    "inspelning": "en inspelning tas emot",
    "transkribering": "en transkribering pågår",
    "hamtning": "modellerna hämtas",
}
AVSLUTA_MENING = {
    "inspelning": "Inspelningen fortsätter i webbläsaren, och ljudet sparas i fliken tills du öppnar "
                  "Akasha Protokoll igen. Stäng inte fliken.",
    "transkribering": "Transkriberingen avbryts. Du kan göra om den med Försök igen när du har öppnat "
                      "Akasha Protokoll igen.",
    "hamtning": "Hämtningen av modellerna stoppas. Det som redan är hämtat ligger kvar, och nästa gång "
                "fortsätter den där den slutade.",
}
AVSLUTA_NEJ = "Avbryt"
AVSLUTA_JA = "Avsluta ändå"

_ORDNING = ("inspelning", "transkribering", "hamtning")
_problem_loggade = False


class StartFel(Exception):
    """Tjansten gick inte att starta. Texten ar redo att visas for anvandaren."""


# --- adress och installningar ------------------------------------------------------------------

def aktuell_port():
    import installningar

    return installningar.PORT


def url(port=None):
    return f"http://127.0.0.1:{port or aktuell_port()}"


def installningsproblem():
    """Problemen fran installningsfilen och miljon. Loggar dem forsta gangen."""
    global _problem_loggade
    try:
        import installningar

        problem = list(installningar.PROBLEM)
    except Exception:
        log.exception("kunde inte lasa installningarna")
        raise
    if not _problem_loggade:
        _problem_loggade = True
        for text in problem:
            log.warning("installningar: %s", text)
    return problem


def installningsfel_text(problem):
    return INSTALLNINGSFEL_TEXT.format(problem="\n".join("– " + p for p in problem),
                                       fil=plattform.installningsfil())


# --- fraga fore avslut -------------------------------------------------------------------------

def pagar(nu=None, tyst_sekunder=20):
    """Det som pagar och som gar forlorat om programmet avslutas: lista med id, tom om inget pagar.

    Kastar aldrig: gar nagot fel loggas det och svaret blir tomt, sa att programmet alltid gar
    att avsluta."""
    try:
        import lagring
        import modeller

        nu = time.time() if nu is None else nu
        lista = lagring.lista()
        vad = []
        for meta in lista:
            if meta.get("status") != "spelar_in":
                continue
            try:
                if nu - os.path.getmtime(lagring.ljudfil(meta)) <= tyst_sekunder:
                    vad.append("inspelning")
                    break
            except OSError:
                continue  # ingen ljudfil an: ingenting att forlora
        if any(meta.get("status") in lagring.PAGAENDE for meta in lista):
            vad.append("transkribering")
        if modeller.HAMTNING.status()["tillstand"] in ("hamtar", "kontrollerar"):
            vad.append("hamtning")
        return vad
    except Exception:
        log.exception("kunde inte avgora vad som pagar")
        return []


def avsluta_text(vad):
    inledning = [AVSLUTA_INLEDNING[v] for v in _ORDNING if v in vad]
    if len(inledning) <= 1:
        lista = "".join(inledning)
    else:
        lista = ", ".join(inledning[:-1]) + " och " + inledning[-1]
    meningar = " ".join(AVSLUTA_MENING[v] for v in _ORDNING if v in vad)
    return f"Akasha Protokoll arbetar fortfarande: {lista}.\n\n{meningar}"


# --- loggning ----------------------------------------------------------------------------------

def loggfil():
    return os.path.join(plattform.loggkatalog(), "akasha-protokoll.log")


def _logga_ohanterat(typ, varde, spar):
    if issubclass(typ, KeyboardInterrupt):
        sys.__excepthook__(typ, varde, spar)
        return
    log.critical("ohanterat fel", exc_info=(typ, varde, spar))


def _logga_ohanterat_trad(args):
    if args.exc_type is SystemExit:
        return
    log.critical("ohanterat fel i tradet %s", getattr(args.thread, "name", "?"),
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def stall_in_loggning():
    """Roterande loggfil pa rotloggern. Returnerar sokvagen. Andra anropet lagger ingen ny hanterare."""
    sokvag = loggfil()
    os.makedirs(os.path.dirname(sokvag), exist_ok=True)
    rot = logging.getLogger()
    for h in rot.handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == os.path.abspath(sokvag):
            return sokvag
    h = logging.handlers.RotatingFileHandler(sokvag, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    rot.addHandler(h)
    if rot.level == logging.NOTSET or rot.level > logging.INFO:
        rot.setLevel(logging.INFO)
    sys.excepthook = _logga_ohanterat
    threading.excepthook = _logga_ohanterat_trad
    return sokvag


def flytta_till_nya_namn():
    """Flyttar mapparna fran tiden som Akasha Meet till de nya namnen och raknar om standardplatserna.
    Kors bara nar beslutet ar att starta (Tjanst.starta), fore allt som anvander installningarna.
    Kastar aldrig: gar flytten fel anvands de gamla mapparna (se plattform.flytta_till_nya_namn)."""
    import installningar  # lagger installningar.env i miljon, sa att ett satt DATAKATALOG syns nedan

    try:
        flyttat = plattform.flytta_till_nya_namn()
    except Exception:
        log.exception("flytten till de nya namnen misslyckades")
        flyttat = []
    for gammal, ny in flyttat:
        log.info("flyttade %s till %s", gammal, ny)
    installningar.uppdatera_platser()
    # Ligger loggfilen i en katalog som flyttades (Linux, Windows) pekar loggern pa den gamla sokvagen.
    rot = logging.getLogger()
    for h in list(rot.handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler) and any(
                os.path.normcase(h.baseFilename).startswith(os.path.normcase(os.path.abspath(g)) + os.sep)
                for g, _ in flyttat):
            rot.removeHandler(h)
            h.close()
            stall_in_loggning()
    return flyttat


# --- port och tjanst ---------------------------------------------------------------------------

def lage(port=None, tidsgrans=1.0):
    """'akasha' (en Akasha Protokoll svarar), 'ledig' eller 'annat' (nagot annat anvander porten)."""
    port = port or aktuell_port()
    # Bind forst: lyckas det lyssnar ingen pa porten, och inget natanrop behovs. Windows vagrar
    # en anslutning till en stangd port forst efter cirka 2 s, sa att fraga forst gav "annat"
    # for en ledig port. Luckan mellan det har provet och skapa_server() hanteras redan av
    # Tjanst.starta(), som ger StartFel om porten tas under tiden.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # som waitress
        s.bind(("127.0.0.1", port))
        return "ledig"
    except OSError:
        pass  # nagot haller porten: fraga vem
    finally:
        s.close()
    # Nagot lyssnar (eller har bundit) porten, sa svaret kommer direkt, ocksa pa Windows.
    oppnare = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # aldrig proxy for 127.0.0.1
    try:
        try:
            with oppnare.open(f"http://127.0.0.1:{port}/health", timeout=tidsgrans) as svar:
                kropp = svar.read(100_000)
        except urllib.error.HTTPError as e:  # 503 ("inte redo") ar ocksa ett svar
            kropp = e.read(100_000)
        data = json.loads(kropp.decode("utf-8", "replace"))
        if isinstance(data, dict) and "motor" in data and "datakatalog" in data:
            return "akasha"
    except (OSError, ValueError, http.client.HTTPException):  # URLError ar en OSError
        pass
    return "annat"


def forbered():
    """Vad ska starten gora? 'ta_over', 'redan_igang', 'upptagen' eller 'starta'."""
    if plattform.gammal_tjanst_finns():
        return "ta_over"
    return {"akasha": "redan_igang", "annat": "upptagen", "ledig": "starta"}[lage(aktuell_port())]


class Tjanst:
    """Webbtjansten i en egen trad, med en stang() som stoppar den rent."""

    def __init__(self, port=None):
        self.port = port or aktuell_port()
        self.server = None
        self.trad = None

    def starta(self):
        flytta_till_nya_namn()
        import app
        import modeller
        import motor

        if plattform.ar_paketerad():
            modeller.ta_in_gamla(plattform.gamla_modellkataloger())
        app.forbered()
        try:
            self.server = app.skapa_server(self.port)
        except OSError as e:
            raise StartFel(UPPTAGEN_TEXT.format(port=self.port, fil=plattform.installningsfil())) from e
        self.trad = threading.Thread(target=self.server.run, name="waitress", daemon=True)
        self.trad.start()
        log.info("Akasha Protokoll: http://127.0.0.1:%s (motor %s, data i %s)", self.port, motor.AKTIV, app.DATAKATALOG)
        if motor.problem():
            log.warning("motorn ar inte redo: %s", motor.problem())

    def vanta(self, sekunder=30):
        """Sant nar tjansten svarar som en Akasha Protokoll."""
        slut = time.monotonic() + sekunder
        while True:
            if lage(self.port) == "akasha":
                return True
            if time.monotonic() >= slut or (self.trad is not None and not self.trad.is_alive()):
                return False
            time.sleep(0.25)

    def stang(self):
        """Stanger servern och stoppar whisper-cli. Far anropas flera ganger."""
        import motor
        from waitress import wasyncore

        server, self.server = self.server, None
        if server is not None:
            try:
                # 1. Hanterartradarna gor klart sina svar medan triggern annu ar oppen.
                server.task_dispatcher.shutdown(cancel_pending=True, timeout=5)
                # 2. Allt stangs inifran servertraden: dar valtar select() pa socketarna, och att
                #    stanga dem fran en annan trad gav "Bad file descriptor" pa macOS. Nar kartan
                #    ar tom tar loopen slut av sig sjalv. server._map ar waitress interna karta
                #    (versionen ar last till 3.0.0 i requirements.txt).
                server.trigger.pull_trigger(lambda: wasyncore.close_all(server._map))
            except Exception:
                log.exception("kunde inte stanga servern")
        motor.stoppa()
        if self.trad is not None:
            self.trad.join(5)
            if self.trad.is_alive():
                log.warning("servertraden stannade inte inom 5 s")
        log.info("Akasha Protokoll avslutas")


def _skriv(*delar):
    print("\n".join(delar), file=sys.stderr, flush=True)


def main():
    """Start utan fonster (Linux, utveckling). Returnerar slutkod."""
    stall_in_loggning()
    problem = installningsproblem()
    if problem:
        _skriv(installningsfel_text(problem))
    beslut = forbered()
    if beslut == "redan_igang":
        plattform.oppna_webblasare(url())
        return 0
    if beslut == "ta_over":
        _skriv(TA_OVER_RUBRIK, TA_OVER_TEXT)  # kan inte fraga utan fonster
        return 1
    if beslut == "upptagen":
        _skriv(UPPTAGEN_TEXT.format(port=aktuell_port(), fil=plattform.installningsfil()))
        return 1
    t = Tjanst()
    try:
        t.starta()
    except StartFel as e:
        _skriv(str(e))
        return 1
    except Exception:
        log.exception("tjansten startade inte")
        _skriv(STARTADE_INTE_TEXT.format(logg=loggfil()))
        return 1
    if not t.vanta():
        _skriv(STARTADE_INTE_TEXT.format(logg=loggfil()))
        t.stang()
        return 1
    plattform.oppna_webblasare(url())
    stopp = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopp.set())
    signal.signal(signal.SIGTERM, lambda *_: stopp.set())
    while not stopp.is_set():
        stopp.wait(1)
    t.stang()
    return 0


if __name__ == "__main__":
    sys.exit(main())
