"""Startar det byggda programmet och kontrollerar det utifran, utan att rora dess kod.

Kors med en vanlig Python som har requests (inte inuti programmet):

    python paketering/kontrollera.py --program SOKVAG --hem KATALOG [--port 8611]
           --vantad-motor whispercpp|faster --vantat-jobbfel TEXT [--riktig-rostmodell]

Varje steg skriver "OK: ..." eller "FEL: ...". Forsta FEL ger slutkod 1 (och de sista raderna av
programmets utskrift och logg). Sist "KONTROLL: OK". Forst, innan programmet startas, kontrolleras licenserna i
programmet (kontrollera_licenser.py: forteckningen, filerna och att varje Python-paket i programmet star i den).

Pa Windows (sys.platform == "win32") ar miljon USERPROFILE, LOCALAPPDATA och TEMP under --hem (ge en katalog med
a-ring och o-prickar och mellanslag i namnet), programmet avslutas med TerminateProcess, ett steg provar den andra
kopian (mutexen) och whisper-cli-processer letas med tasklist.
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time

import requests

import kontroll_hjalp
import kontrollera_licenser

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROT, "app"))

MAC = sys.platform == "darwin"
WIN = sys.platform == "win32"
HEADERS = {"X-Akasha-Protokoll": "1"}
TALARE_SAKNAS = "röstmodellen saknas. Hämta den på sidan."
FLYTTPROV = "flyttprov"
# Programkatalogen under hemkatalogen, med det gamla namnet (Akasha Meet) och det nya.
GAMMAL_PROGRAMKATALOG = ("Library", "Application Support", "Akasha Meet") if MAC else \
    ("AppData", "Local", "Akasha Meet") if WIN else (".local", "share", "akasha-meet")
NY_PROGRAMKATALOG = ("Library", "Application Support", "Akasha Protokoll") if MAC else \
    ("AppData", "Local", "Akasha Protokoll") if WIN else (".local", "share", "akasha-protokoll")
START_TIDSGRANS = 120 if WIN else 60  # Windows: Defender granskar en nyuppackad exe och dess DLL-filer forsta gangen
ANDRA_KOPIAN_TIDSGRANS = 40
# Windows: variabler som programmet behover ur den egna miljon (utan SYSTEMROOT fungerar inte Pythons nat och slumptal).
WINDOWS_MILJO = ("SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "PATHEXT", "PROCESSOR_ARCHITECTURE",
                 "PROCESSOR_ARCHITEW6432", "NUMBER_OF_PROCESSORS", "OS", "PROGRAMDATA", "PROGRAMFILES", "ALLUSERSPROFILE",
                 "USERNAME", "COMPUTERNAME")

FORTSATT = False  # --fortsatt-efter-fel: ett misslyckat villkor skrivs som FEL och kontrollen fortsatter
fel_lista = []
proc = None
andra_proc = None
args = None
utskrift = None
logg = None


def ok(text):
    print(f"OK: {text}", flush=True)


def sammanfatta_fel():
    """Med --fortsatt-efter-fel: listan over alla FEL som hittats (tom annars)."""
    if fel_lista:
        print(f"--- {len(fel_lista)} FEL i kontrollen ---", flush=True)
        for rad in fel_lista:
            print(f"FEL: {rad}", flush=True)


def slut(text):
    """FEL: skriv felet, de sista raderna av programmets utskrift och logg, stoppa programmet."""
    print(f"FEL: {text}", flush=True)
    if FORTSATT:
        fel_lista.append(text)
    for namn, sokvag in (("programmets utskrift", utskrift), ("loggfilen", logg)):
        if sokvag and os.path.isfile(sokvag):
            with open(sokvag, encoding="utf-8", errors="replace") as f:
                rader = f.read().splitlines()[-40:]
            print(f"--- {namn} ({sokvag}), sista {len(rader)} raderna ---", flush=True)
            print("\n".join(rader), flush=True)
    if WIN and logg and os.path.isfile(logg):
        with open(logg, encoding="utf-8", errors="replace") as f:
            win = [r for r in f.read().splitlines() if "win:" in r]
        print(f"--- alla loggrader fran Windows-skalet (win: ...), {len(win)} st ---", flush=True)
        print("\n".join(win), flush=True)
    sammanfatta_fel()
    for p in (andra_proc, proc):
        if p is not None and p.poll() is None:
            p.kill()
            p.wait()
    sys.exit(1)


def kontrollera(villkor, text_ok, text_fel):
    """OK, eller FEL: utan --fortsatt-efter-fel stoppar kontrollen (slut), med den skrivs felet och kontrollen fortsatter."""
    if villkor:
        ok(text_ok)
    elif FORTSATT:
        print(f"FEL: {text_fel}", flush=True)
        fel_lista.append(text_fel)
    else:
        slut(text_fel)
    return bool(villkor)


def hamta(sokvag, **kw):
    return requests.get(f"http://127.0.0.1:{args.port}{sokvag}", timeout=10, **kw)


def port_ledig():
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", args.port))
    except (ConnectionRefusedError, OSError):
        return True
    finally:
        s.close()
    return False


def programmiljo(hem):
    """Miljon programmet startas med: tom hemkatalog, och bara det som behovs ur den egna miljon."""
    if WIN:
        sysrot = os.environ.get("SYSTEMROOT") or r"C:\Windows"
        lokal = os.path.join(hem, "AppData", "Local")
        temp = os.path.join(lokal, "Temp")
        os.makedirs(temp, exist_ok=True)
        miljo = {"USERPROFILE": hem, "APPDATA": os.path.join(hem, "AppData", "Roaming"), "LOCALAPPDATA": lokal,
                 "TEMP": temp, "TMP": temp, "SYSTEMROOT": sysrot, "WINDIR": os.environ.get("WINDIR") or sysrot,
                 "COMSPEC": os.environ.get("COMSPEC") or os.path.join(sysrot, "System32", "cmd.exe"),
                 "PATH": os.path.join(sysrot, "System32") + os.pathsep + sysrot, "PORT": str(args.port)}
        for namn in WINDOWS_MILJO:
            if namn in os.environ:
                miljo.setdefault(namn, os.environ[namn])
    else:
        miljo = {"HOME": hem, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PORT": str(args.port),
                 "LANG": "sv_SE.UTF-8"}
    for namn in ("TMPDIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE",
                 "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        for n in (namn, namn.lower()):
            if n in os.environ:
                miljo[n] = os.environ[n]
    return miljo


def prova_format(katalog):
    """Skickar varje fil i katalogen (testljud/format/) till POST /transcribe i det korande programmet.
    -> [(filnamn, statuskod, text)]. Motorn saknas eller har inga riktiga modeller i provet, sa 502 (eller 500) ar vantat: det
    betyder att avkodningen lyckades. Det som inte far handa ar 400 med "ljudet kunde inte lasas"."""
    ut = []
    for namn in sorted(os.listdir(katalog)):
        with open(os.path.join(katalog, namn), "rb") as f:
            r = requests.post(f"http://127.0.0.1:{args.port}/transcribe", timeout=120,
                              headers={**HEADERS, "Origin": f"http://127.0.0.1:{args.port}"},
                              files={"audio": (namn, f, "application/octet-stream")})
        ut.append((namn, r.status_code, r.text))
    return ut


def kontrollera_format(katalog):
    """Avkodningen av varje format i det paketerade programmet (sa att ett bibliotek som saknar en avkodare syns har)."""
    svar = prova_format(katalog)
    kontrollera(len(svar) > 0, f"{len(svar)} ljudformat i {katalog} skickades till /transcribe",
                f"inga filer i {katalog}")
    for namn, status, text in svar:
        kontrollera(not (status == 400 and "ljudet kunde inte l" in text.lower()),
                    f"{namn}: avkodningen lyckades (svar {status})",
                    f"{namn}: ljudet kunde inte läsas av det paketerade programmet (svar {status}: {text.strip()[:200]})")


def tasklist(avbildning):
    """Namn pa processer med den avbildningen (tasklist; MSYS omskriver inte argument som startas fran Python)."""
    ut = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {avbildning}", "/NH", "/FO", "CSV"], capture_output=True,
                        timeout=60).stdout.decode("utf-8", "replace")
    return [r for r in ut.splitlines() if avbildning.lower() in r.lower()]


def programstorlek(program):
    """Summa av filstorlekar: .app pa Mac, annars katalogen programmet ligger i."""
    rot = os.path.dirname(os.path.abspath(program))
    if MAC:
        while rot != os.path.dirname(rot) and not rot.endswith(".app"):
            rot = os.path.dirname(rot)
    total = 0
    for mapp, _kataloger, filer in os.walk(rot):
        for namn in filer:
            try:
                total += os.lstat(os.path.join(mapp, namn)).st_size
            except OSError:
                pass
    return rot, total


def main():
    global proc, andra_proc, args, utskrift, logg, FORTSATT
    if WIN:  # Actions-maskinens konsol ar inte UTF-8: en omdirigerad utskrift med a-ring far inte krascha skriptet
        for strom in (sys.stdout, sys.stderr):
            strom.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", required=True)
    ap.add_argument("--hem", required=True)
    ap.add_argument("--port", type=int, default=8611)
    ap.add_argument("--vantad-motor", required=True, choices=["whispercpp", "faster"])
    ap.add_argument("--vantat-jobbfel", required=True)
    ap.add_argument("--riktig-rostmodell", action="store_true")
    ap.add_argument("--fortsatt-efter-fel", action="store_true",
                    help="skriv varje misslyckat villkor som FEL och fortsatt; stoppa bara nar det inte gar att fortsatta "
                         "(programmet startar eller svarar inte). Sist en lista over alla FEL och slutkod 1")
    args = ap.parse_args()
    FORTSATT = args.fortsatt_efter_fel
    hem = os.path.abspath(args.hem)
    program = os.path.abspath(args.program)
    if WIN and not os.path.isfile(program):  # ett tydligt FEL i stallet for en traceback om bygget inte gav nagon exe
        print(f"FEL: programmet {program} finns inte (se bygget)", flush=True)
        sys.exit(1)

    # 0. Licenserna i programmet (filerna, inget startas): forteckningen, en fil per komponent, och varje Python-paket i
    # programmet star i forteckningen.
    lic = kontroll_hjalp.Resultat("LICENSER")
    kontrollera_licenser.kontrollera(program, lic)
    kontrollera(not lic.fel_rader, f"licenserna i programmet: {len(lic.ok_rader)} kontroller OK",
                f"licenserna i programmet stämmer inte ({len(lic.fel_rader)} FEL: {'; '.join(lic.fel_rader)[:600]})")

    # 1. Gamla modeller pa den gamla platsen. Tjansten kontrollerar bara storleken pa en befintlig
    # fil (steg 1, A3), sa en gles fil med ratt storlek racker: ingen hamtning av 1,5 GB (A8).
    import modeller
    os.makedirs(hem, exist_ok=True)
    gamla = []
    for fil in modeller.PAKET[(args.vantad_motor, "medium")]:
        sokvag = os.path.join(hem, "akasha-meet", "modeller", fil.katalog, fil.namn)
        os.makedirs(os.path.dirname(sokvag), exist_ok=True)
        with open(sokvag, "wb") as f:
            f.truncate(fil.storlek)
        gamla.append(sokvag)
    ok(f"{len(gamla)} gamla modellfiler lagda (glesa, rätt storlek) i {hem}/akasha-meet/modeller")

    # 1b. De gamla mapparna fran tiden som Akasha Meet: inspelningsmappen med en fil, och programkatalogen
    # med en tom installningsfil. Programmet ska flytta dem till de nya namnen vid start (plattform.py).
    gammal_data = os.path.join(hem, "AkashaMeet")
    gammal_program = os.path.join(hem, *GAMMAL_PROGRAMKATALOG)
    # Windows: bara inspelningsmappen. Loggfilen ligger i programkatalogen dar, och stall_in_loggning() oppnar den fore
    # flytten, och en katalog med en oppen fil kan inte byta namn pa Windows. Ingen Windows-installation har heller haft
    # det gamla namnet, sa den flytten behovs inte dar.
    flyttpar = [(gammal_data, "flyttprov.txt", FLYTTPROV)]
    if not WIN:
        flyttpar.append((gammal_program, "installningar.env", ""))
    for mapp, fil, innehall in flyttpar:
        os.makedirs(mapp, exist_ok=True)
        with open(os.path.join(mapp, fil), "w", encoding="utf-8") as f:
            f.write(innehall)
    if WIN:
        ok(f"gammal mapp lagd: {gammal_data} (flyttprov.txt)")
        print(f"INFO: den gamla programkatalogen ({gammal_program}) laggs inte och flytten av den provas inte pa Windows: "
              "loggfilen ligger i programkatalogen, sa en katalog med det gamla namnet kan inte byta namn medan "
              "programmet kor, och ingen Windows-installation har haft det gamla namnet", flush=True)
    else:
        ok(f"gamla mappar lagda: {gammal_data} (flyttprov.txt) och {gammal_program} (installningar.env)")

    # 2. Starta programmet med tom hemkatalog. Inga MODELLKATALOG eller DATAKATALOG: standardvardena provas.
    miljo = programmiljo(hem)
    utskrift = os.path.join(hem, "program-utskrift.log")
    logg = os.path.join(hem, "Library", "Logs", "Akasha Protokoll", "akasha-protokoll.log") if MAC else \
        os.path.join(hem, *NY_PROGRAMKATALOG, "logg", "akasha-protokoll.log")
    with open(utskrift, "wb") as ut:
        proc = subprocess.Popen([program], env=miljo, stdout=ut, stderr=subprocess.STDOUT)
    ok(f"programmet startat (pid {proc.pid}, port {args.port})")

    # 3. Vanta pa /health.
    start = time.monotonic()
    while True:
        if proc.poll() is not None:
            slut(f"programmet avslutades med kod {proc.returncode} innan det svarade")
        try:
            hamta("/health")
            break
        except requests.RequestException:
            pass
        if time.monotonic() - start > START_TIDSGRANS:
            slut(f"programmet svarade inte på /health inom {START_TIDSGRANS} s")
        time.sleep(0.5)
    ok(f"/health svarar efter {time.monotonic() - start:.1f} s")

    # 4. Sidan och dess skript.
    r = hamta("/")
    kontrollera(r.status_code == 200 and "Akasha Protokoll" in r.text, "GET / ger 200 och innehåller Akasha Protokoll",
                f"GET / gav {r.status_code} utan texten Akasha Protokoll")
    r = hamta("/static/app.js")
    kontrollera(r.status_code == 200, f"GET /static/app.js ger 200 ({len(r.content)} byte)",
                f"GET /static/app.js gav {r.status_code}")
    r = hamta("/static/typsnitt/instrument-sans-latin-wght-normal.woff2")
    kontrollera(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("font/woff2"),
                f"GET /static/typsnitt/instrument-sans-latin-wght-normal.woff2 ger 200 font/woff2 ({len(r.content)} byte)",
                f"typsnittet gav {r.status_code} med Content-Type {r.headers.get('Content-Type')!r}")

    # 5. /health.
    h = hamta("/health").json()
    forvantad = os.path.join(hem, "AkashaProtokoll")
    kontrollera(os.path.realpath(h.get("datakatalog", "")) == os.path.realpath(forvantad),
                f"datakatalog är {h.get('datakatalog')}", f"datakatalog är {h.get('datakatalog')}, väntade {forvantad}")
    # Flytten: det som lades under de gamla namnen ska nu ligga under de nya, och de gamla ska vara borta.
    ny_program = os.path.join(hem, *NY_PROGRAMKATALOG)
    kontrolleras = [(gammal_data, forvantad, "flyttprov.txt", FLYTTPROV)]
    if not WIN:
        kontrolleras.append((gammal_program, ny_program, "installningar.env", ""))
    for gammal, ny, fil, innehall in kontrolleras:
        sokvag = os.path.join(ny, fil)
        text = open(sokvag, encoding="utf-8").read() if os.path.isfile(sokvag) else None
        kontrollera(text == innehall and not os.path.exists(gammal),
                    f"{gammal} flyttades till {ny} (innehållet orört, den gamla borta)",
                    f"flytten av {gammal} till {ny} misslyckades (filen {sokvag}: {text!r}, den gamla finns: "
                    f"{os.path.exists(gammal)})")
    kontrollera(h.get("talare") == TALARE_SAKNAS, "sherpa-onnx gick att importera (talare: röstmodellen saknas)",
                f"talare är {h.get('talare')!r}, väntade {TALARE_SAKNAS!r}")
    kontrollera(h.get("motor") == args.vantad_motor, f"motor är {h.get('motor')}",
                f"motor är {h.get('motor')!r}, väntade {args.vantad_motor!r}")

    # 6. /api/modeller: standardkatalog, bara talare saknas, gamla filer hardlankade.
    m = hamta("/api/modeller").json()
    kontrollera(m.get("hinder") is None, "hinder är null", f"hinder är {m.get('hinder')!r}")
    delar = [*NY_PROGRAMKATALOG, "modeller"]
    kontrollera(os.path.realpath(m.get("katalog", "")) == os.path.realpath(os.path.join(hem, *delar)),
                f"modellkatalogen är {m.get('katalog')}",
                f"modellkatalogen är {m.get('katalog')!r}, väntade {os.path.join(hem, *delar)}")
    ids = [s["id"] for s in m.get("saknas", [])]
    kontrollera(ids == ["talare"], "bara talare saknas (de gamla modellerna togs in)", f"saknas är {ids}")
    for gammal, fil in zip(gamla, modeller.PAKET[(args.vantad_motor, "medium")]):
        ny = os.path.join(m["katalog"], fil.katalog, fil.namn)
        kontrollera(os.path.exists(ny) and os.path.samefile(gammal, ny),
                    f"{fil.namn} är hårdlänkad från den gamla platsen",
                    f"{ny} är inte samma fil som {gammal}")

    # 7. Riktig hamtning av rostmodellen genom programmets API.
    if args.riktig_rostmodell:
        t0 = time.monotonic()
        r = requests.post(f"http://127.0.0.1:{args.port}/api/modeller/hamta", timeout=10,
                          headers={**HEADERS, "Origin": f"http://127.0.0.1:{args.port}"})
        kontrollera(r.status_code == 202, "POST /api/modeller/hamta ger 202", f"hamta gav {r.status_code}: {r.text}")
        while True:
            m = hamta("/api/modeller").json()
            if m["hamtning"]["tillstand"] in ("klar", "fel"):
                break
            if time.monotonic() - t0 > 180:
                slut(f"hämtningen blev inte klar inom 180 s: {m['hamtning']}")
            time.sleep(1)
        kontrollera(m["hamtning"]["tillstand"] == "klar", "hämtningen blev klar", f"hämtningen gav {m['hamtning']}")
        kontrollera(m["saknas"] == [], "inget saknas efter hämtningen", f"saknas är {m['saknas']}")
        h = hamta("/health").json()
        kontrollera(h.get("talare") == "ok", f"röstmodellen hämtad och verifierad på {time.monotonic() - t0:.1f} s (talare: ok)",
                    f"talare är {h.get('talare')!r} efter hämtningen")

    # 8. Ladda upp ett testljud: avkodningen ska lyckas och jobbet misslyckas med vantat fel.
    ljud = os.path.join(ROT, "testljud", "en-talare.m4a")
    with open(ljud, "rb") as f:
        r = requests.post(f"http://127.0.0.1:{args.port}/api/inspelningar/fil", timeout=60,
                          headers={**HEADERS, "Origin": f"http://127.0.0.1:{args.port}"},
                          files={"ljud": ("en-talare.m4a", f, "audio/mp4")}, data={"talare": "1"})
    uppladdat = kontrollera(r.status_code == 201, "uppladdningen ger 201", f"uppladdningen gav {r.status_code}: {r.text}")
    if uppladdat:
        id_ = r.json()["id"]
        t0 = time.monotonic()
        while True:
            svar = hamta(f"/api/inspelningar/{id_}")
            try:
                i = svar.json() if svar.status_code == 200 else None
            except ValueError:
                i = None
            if not isinstance(i, dict) or "status" not in i:
                slut(f"inspelningen {id_} kunde inte läsas under väntan på jobbet: "
                     f"statuskod {svar.status_code}, svar {svar.text[:300]!r}")
            if i["status"] in ("klar", "fel"):
                break
            if time.monotonic() - t0 > 120:
                slut(f"jobbet blev inte klart inom 120 s (status {i['status']})")
            time.sleep(1)
        jobbfel = i.get("fel") or ""
        kontrollera(i["status"] == "fel" and args.vantat_jobbfel in jobbfel,
                    f"jobbet misslyckades som väntat efter {time.monotonic() - t0:.1f} s: {jobbfel}",
                    f"jobbet gav status {i['status']} och fel {jobbfel!r}, väntade felet {args.vantat_jobbfel!r}")
        kontrollera("Ljudet kunde inte läsas" not in jobbfel, "avkodningen av ljudet lyckades",
                    f"avkodningen misslyckades: {jobbfel}")

    # 8b. Varje ljudformat genom det paketerade programmet: avkodningen ska lyckas (motorn far gerna fela efterat).
    kontrollera_format(os.path.join(ROT, "testljud", "format"))

    # 9. Loggfilen.
    rad = f"Akasha Protokoll: http://127.0.0.1:{args.port}"
    text = open(logg, encoding="utf-8", errors="replace").read() if os.path.isfile(logg) else None
    kontrollera(text is not None and rad in text, f"loggfilen {logg} finns och innehåller '{rad}'",
                f"loggfilen {logg} saknas eller saknar raden '{rad}'")
    text = text or ""  # med --fortsatt-efter-fel kan loggen saknas: raderna nedan jamfor da mot en tom text
    if WIN:
        # Raderna "win: ..." visar hur langt skalet kom (ikonen vid klockan, beslutet, webblasaren).
        print("--- loggrader fran Windows-skalet (win: ...) ---", flush=True)
        print("\n".join(r for r in text.splitlines() if "win:" in r), flush=True)
        for rad_win in ("win: startar", "win: beslut starta", "win: tjansten svarar, oppnar webblasaren"):
            kontrollera(rad_win in text, f"loggen har raden '{rad_win}'", f"loggen saknar raden '{rad_win}'")
        if "win: ikonen visas" in text:
            ok("ikonen vid klockan visades (win: ikonen visas)")
        else:
            print("INFO: loggen saknar 'win: ikonen visas' (en Actions-maskin kan sakna skrivbord; tjansten gick anda)",
                  flush=True)

    # 9b. Windows: starta programmet en gang till. Den andra kopian ska se mutexen, oppna sidan och avsluta sig
    # sjalv med kod 0, och den forsta ska fortfarande svara.
    if WIN:
        with open(os.path.join(hem, "program-utskrift-andra.log"), "wb") as ut2:
            andra_proc = subprocess.Popen([program], env=miljo, stdout=ut2, stderr=subprocess.STDOUT)
        try:
            kod = andra_proc.wait(ANDRA_KOPIAN_TIDSGRANS)
        except subprocess.TimeoutExpired:
            slut(f"den andra kopian avslutades inte inom {ANDRA_KOPIAN_TIDSGRANS} s (mutexen eller redan_igang fungerar inte)")
        kontrollera(kod == 0, "den andra kopian avslutade sig själv med kod 0",
                    f"den andra kopian avslutades med kod {kod}, väntade 0")
        r = hamta("/health")
        kontrollera(r.status_code == 200, "den första kopian svarar fortfarande på /health efter den andra starten",
                    f"/health gav {r.status_code} efter den andra starten")
        text = open(logg, encoding="utf-8", errors="replace").read() if os.path.isfile(logg) else ""
        kontrollera("win: kopia finns redan" in text, "loggen har raden 'win: kopia finns redan'",
                    "loggen saknar raden 'win: kopia finns redan' (den andra kopian kom inte till mutexen)")

    # 10. SIGTERM (Windows: TerminateProcess, som Aktivitetshanteraren): processen ska avslutas och porten bli ledig.
    if WIN:
        proc.terminate()
    else:
        proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        slut(f"programmet avslutades inte inom 10 s efter {'TerminateProcess' if WIN else 'SIGTERM'}")
    kontrollera(port_ledig(), f"programmet avslutades (kod {proc.returncode}) och porten är ledig",
                f"porten är inte ledig efter {'TerminateProcess' if WIN else 'SIGTERM'}")
    if WIN:
        kvar = tasklist("whisper-cli.exe")
        kontrollera(not kvar, "ingen whisper-cli.exe kvar", f"whisper-cli.exe är kvar efter att programmet avslutats: {kvar}")
        print(f"INFO: processer som heter Akasha Protokoll.exe: {len(tasklist('Akasha Protokoll.exe'))}", flush=True)
    if MAC:
        kvar = subprocess.run(["pgrep", "-f", "whisper-cli"], capture_output=True)
        kontrollera(kvar.returncode != 0, "ingen whisper-cli kvar", "en whisper-cli är kvar efter SIGTERM")

    # 11. Storlek.
    rot, total = programstorlek(program)
    ok(f"programmets storlek: {total / 1e6:.1f} MB ({rot})")
    sammanfatta_fel()
    if fel_lista:
        print("KONTROLL: FEL")
        sys.exit(1)
    print("KONTROLL: OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Bara med --fortsatt-efter-fel: ett ovantat undantag (till exempel ett svar som saknar ett falt efter ett misslyckat
        # villkor) ska inte dolja de FEL som redan hittats.
        if not FORTSATT:
            raise
        import traceback

        traceback.print_exc()
        fel_lista.append("kontrollen avbrots av ett ovantat undantag (se traceback ovan)")
        slut("kontrollen kunde inte fortsatta")
