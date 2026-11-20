"""Startar det byggda programmet och kontrollerar det utifran, utan att rora dess kod.

Kors med en vanlig Python som har requests (inte inuti programmet):

    python paketering/kontrollera.py --program SOKVAG --hem KATALOG [--port 8611]
           --vantad-motor whispercpp|faster --vantat-jobbfel TEXT [--riktig-rostmodell]

Varje steg skriver "OK: ..." eller "FEL: ...". Forsta FEL ger slutkod 1 (och de sista raderna av
programmets utskrift och logg). Sist "KONTROLL: OK".
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time

import requests

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROT, "app"))

MAC = sys.platform == "darwin"
HEADERS = {"X-Akasha-Meet": "1"}
TALARE_SAKNAS = "röstmodellen saknas. Hämta den på sidan."

proc = None
args = None
utskrift = None
logg = None


def ok(text):
    print(f"OK: {text}", flush=True)


def slut(text):
    """FEL: skriv felet, de sista raderna av programmets utskrift och logg, stoppa programmet."""
    print(f"FEL: {text}", flush=True)
    for namn, sokvag in (("programmets utskrift", utskrift), ("loggfilen", logg)):
        if sokvag and os.path.isfile(sokvag):
            with open(sokvag, encoding="utf-8", errors="replace") as f:
                rader = f.read().splitlines()[-40:]
            print(f"--- {namn} ({sokvag}), sista {len(rader)} raderna ---", flush=True)
            print("\n".join(rader), flush=True)
    if proc is not None and proc.poll() is None:
        proc.kill()
        proc.wait()
    sys.exit(1)


def kontrollera(villkor, text_ok, text_fel):
    if villkor:
        ok(text_ok)
    else:
        slut(text_fel)


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
    global proc, args, utskrift, logg
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", required=True)
    ap.add_argument("--hem", required=True)
    ap.add_argument("--port", type=int, default=8611)
    ap.add_argument("--vantad-motor", required=True, choices=["whispercpp", "faster"])
    ap.add_argument("--vantat-jobbfel", required=True)
    ap.add_argument("--riktig-rostmodell", action="store_true")
    args = ap.parse_args()
    hem = os.path.abspath(args.hem)
    program = os.path.abspath(args.program)

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

    # 2. Starta programmet med tom hemkatalog. Inga MODELLKATALOG eller DATAKATALOG: standardvardena provas.
    miljo = {"HOME": hem, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PORT": str(args.port),
             "LANG": "sv_SE.UTF-8"}
    for namn in ("TMPDIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE",
                 "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        for n in (namn, namn.lower()):
            if n in os.environ:
                miljo[n] = os.environ[n]
    utskrift = os.path.join(hem, "program-utskrift.log")
    logg = os.path.join(hem, "Library", "Logs", "Akasha Meet", "akasha-meet.log") if MAC else \
        os.path.join(hem, ".local", "share", "akasha-meet", "logg", "akasha-meet.log")
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
        if time.monotonic() - start > 60:
            slut("programmet svarade inte på /health inom 60 s")
        time.sleep(0.5)
    ok(f"/health svarar efter {time.monotonic() - start:.1f} s")

    # 4. Sidan och dess skript.
    r = hamta("/")
    kontrollera(r.status_code == 200 and "Akasha Meet" in r.text, "GET / ger 200 och innehåller Akasha Meet",
                f"GET / gav {r.status_code} utan texten Akasha Meet")
    r = hamta("/static/app.js")
    kontrollera(r.status_code == 200, f"GET /static/app.js ger 200 ({len(r.content)} byte)",
                f"GET /static/app.js gav {r.status_code}")

    # 5. /health.
    h = hamta("/health").json()
    forvantad = os.path.join(hem, "AkashaMeet")
    kontrollera(os.path.realpath(h.get("datakatalog", "")) == os.path.realpath(forvantad),
                f"datakatalog är {h.get('datakatalog')}", f"datakatalog är {h.get('datakatalog')}, väntade {forvantad}")
    kontrollera(h.get("talare") == TALARE_SAKNAS, "sherpa-onnx gick att importera (talare: röstmodellen saknas)",
                f"talare är {h.get('talare')!r}, väntade {TALARE_SAKNAS!r}")
    kontrollera(h.get("motor") == args.vantad_motor, f"motor är {h.get('motor')}",
                f"motor är {h.get('motor')!r}, väntade {args.vantad_motor!r}")

    # 6. /api/modeller: standardkatalog, bara talare saknas, gamla filer hardlankade.
    m = hamta("/api/modeller").json()
    kontrollera(m.get("hinder") is None, "hinder är null", f"hinder är {m.get('hinder')!r}")
    delar = ["Library", "Application Support", "Akasha Meet", "modeller"] if MAC else \
        [".local", "share", "akasha-meet", "modeller"]
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
    kontrollera(r.status_code == 201, "uppladdningen ger 201", f"uppladdningen gav {r.status_code}: {r.text}")
    id_ = r.json()["id"]
    t0 = time.monotonic()
    while True:
        i = hamta(f"/api/inspelningar/{id_}").json()
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

    # 9. Loggfilen.
    rad = f"Akasha Meet: http://127.0.0.1:{args.port}"
    text = open(logg, encoding="utf-8", errors="replace").read() if os.path.isfile(logg) else None
    kontrollera(text is not None and rad in text, f"loggfilen {logg} finns och innehåller '{rad}'",
                f"loggfilen {logg} saknas eller saknar raden '{rad}'")

    # 10. SIGTERM: processen ska avslutas och porten bli ledig.
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        slut("programmet avslutades inte inom 10 s efter SIGTERM")
    kontrollera(port_ledig(), f"programmet avslutades (kod {proc.returncode}) och porten är ledig",
                "porten är inte ledig efter SIGTERM")
    if MAC:
        kvar = subprocess.run(["pgrep", "-f", "whisper-cli"], capture_output=True)
        kontrollera(kvar.returncode != 0, "ingen whisper-cli kvar", "en whisper-cli är kvar efter SIGTERM")

    # 11. Storlek.
    rot, total = programstorlek(program)
    ok(f"programmets storlek: {total / 1e6:.1f} MB ({rot})")
    print("KONTROLL: OK")


if __name__ == "__main__":
    main()
