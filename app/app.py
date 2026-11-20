"""Akasha Protokoll: transkribera moten lokalt. Webbsida och API pa http://127.0.0.1:PORT.

Lyssnar ALLTID bara pa 127.0.0.1, sa ingen annan dator kommer at tjansten. Skydd mot att andra
webbsidor i samma webblasare anropar den:
  - Host maste vara localhost eller 127.0.0.1 (stoppar DNS-rebinding).
  - Allt som andrar nagot kraver headern X-Akasha-Protokoll: 1. En annan sajt kan bara skicka den
    efter en CORS-forfragan, och sadana godkanner tjansten aldrig.

Transkriberingar kors en i taget i en bakgrundstrad. Webbsidan fragar efter framsteg.
"""
import io
import logging
import os
import queue
import re
import tempfile
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

import numpy as np
from flask import Flask, jsonify, request, send_file

import export
import installningar
import lagring
import modeller
import motor
import plattform
import rattning
import talare
from installningar import DATAKATALOG, MAX_MB, MODELL, ORDLISTA, PORT

HEADER = "X-Akasha-Protokoll"
VARDAR = {"127.0.0.1", "localhost", "::1"}
SR = motor.SR

log = logging.getLogger("akasha-protokoll")
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

_ko = queue.Queue()
_framsteg = {}  # id -> {"fas": ..., "andel": 0..1, "start": monotonic}, bara i minnet
_arbetare_startad = threading.Event()


# --- skydd --------------------------------------------------------------------------------

def vardnamn(host):
    host = (host or "").strip()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


@app.before_request
def skydd():
    if vardnamn(request.host) not in VARDAR:
        return jsonify(error="Tjänsten svarar bara på localhost."), 403
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get(HEADER) != "1":
            return jsonify(error=f"Saknar headern {HEADER}."), 403
        origin = request.headers.get("Origin")
        if origin and vardnamn(urlparse(origin).netloc) not in VARDAR:
            return jsonify(error="Anrop från en annan webbplats."), 403
    return None


@app.after_request
def sakerhetsheaders(svar):
    svar.headers["Content-Security-Policy"] = (
        "default-src 'self'; media-src 'self' blob:; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    svar.headers["X-Content-Type-Options"] = "nosniff"
    svar.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/api/"):
        svar.headers["Cache-Control"] = "no-store"
    return svar


@app.errorhandler(lagring.Fel)
def lagringsfel(e):
    return jsonify(error=str(e)), e.kod


@app.errorhandler(413)
def for_stor(_e):
    return jsonify(error=f"Filen är för stor (max {MAX_MB} MB)."), 413


@app.errorhandler(Exception)
def ovantat_fel(e):
    from werkzeug.exceptions import HTTPException

    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    log.exception("ovantat fel i %s %s", request.method, request.path)
    return jsonify(error=f"Oväntat fel: {e}"), 500


# --- hjalpfunktioner -----------------------------------------------------------------------

def tolka_installningar(data):
    antal = str((data or {}).get("talare", "2")).strip().lower()
    try:
        talare.tolka_antal(antal)
    except ValueError:
        raise lagring.Fel("Antal talare måste vara 1–10 eller auto.")
    ord_ = str((data or {}).get("ord", "")).strip()[:500]
    # rum = en mikrofon i rummet. digitalt = mikrofonen i vanster kanal, motesfliken i hoger.
    kalla = "digitalt" if str((data or {}).get("kalla", "")).strip() == "digitalt" else "rum"
    return {"talare": antal, "ord": ord_, "kalla": kalla}


def med_framsteg(meta):
    meta = dict(meta)
    meta["rubrik"] = export.rubrik(meta)
    meta["info"] = export.info(meta)
    meta["info_delar"] = export.info_delar(meta)
    if meta["status"] in lagring.PAGAENDE and meta["id"] in _framsteg:
        framsteg = dict(_framsteg[meta["id"]])
        start = framsteg.pop("start", None)
        if start is not None:
            # Hur lange steget har hallit pa: sidan raknar ut ungefar hur lang tid som ar kvar.
            framsteg["sekunder"] = round(time.monotonic() - start, 1)
        meta["framsteg"] = framsteg
    return meta


def sammanfattning(meta):
    m = med_framsteg(meta)
    res = m.pop("resultat", None) or {}
    m["har_text"] = bool(res.get("segment"))
    m["langd_s"] = res.get("langd_s")
    m["rattad"] = "segment_original" in res  # talarna har rättats för hand
    return m


def skriv_text(meta):
    with open(lagring.textfil(meta["id"]), "w", encoding="utf-8") as f:
        f.write(export.som_markdown(meta))


# --- bakgrundsjobb -------------------------------------------------------------------------

def koa(id_, installningar=None):
    with lagring._las:
        meta = lagring.las(id_)
        if meta["status"] in lagring.PAGAENDE:
            raise lagring.Fel("Inspelningen transkriberas redan.", 409)
        if meta["status"] == "spelar_in":
            raise lagring.Fel("Inspelningen pågår fortfarande.", 409)
        if installningar:
            # Kallan (rum eller digitalt) hor till inspelningen: kanalerna i filen andras inte
            # av att man stoppar eller gor om med ett annat antal talare.
            installningar = {**installningar, "kalla": (meta.get("installningar") or {}).get("kalla", "rum")}
            meta["installningar"] = installningar
        meta["status"] = "koar"
        meta.pop("fel", None)
        lagring.spara(meta)
    _framsteg[id_] = {"fas": "koar", "andel": 0.0, "start": time.monotonic()}
    _ko.put(id_)
    return meta


def _satt(id_, fas, andel):
    # Starttiden nollstalls bara nar steget byts, inte vid varje ny andel.
    forra = _framsteg.get(id_) or {}
    start = forra.get("start") if forra.get("fas") == fas and "start" in forra else time.monotonic()
    _framsteg[id_] = {"fas": fas, "andel": round(max(0.0, min(1.0, andel)), 3), "start": start}


def kor(id_):
    meta = lagring.uppdatera(id_, status="transkriberar")
    inst = meta.get("installningar") or {}
    antal = talare.tolka_antal(inst.get("talare", "2"))
    dela = antal != 1
    varning = None
    if dela and talare.problem():
        varning = f"Texten är inte uppdelad per talare ({talare.problem()})."
        dela = False
    _satt(id_, "transkriberar", 0.0)

    t0 = time.monotonic()  # star still nar datorn sover: tiden blir arbetstid
    kanaler = None
    try:
        if inst.get("kalla") == "digitalt":
            vanster, hoger = motor.avkoda_kanaler(lagring.ljudfil(meta))
            if talare.har_tva_kanaler(vanster, hoger):
                kanaler = (vanster, hoger)
                # Whisper far bada kanalerna: din rost och motet.
                samples = np.clip(vanster + hoger, -1.0, 1.0)
            else:
                samples = (vanster + hoger) / 2
        else:
            samples = motor.avkoda(lagring.ljudfil(meta))
    except Exception as e:
        log.warning("kunde inte avkoda %s: %s", id_, e)
        raise lagring.Fel("Ljudet kunde inte läsas. Är inspelningen tom eller trasig?")
    if len(samples) < SR // 2:
        raise lagring.Fel("Inspelningen är kortare än en halv sekund.")

    prompt = ", ".join(x for x in (ORDLISTA, inst.get("ord", "")) if x.strip())
    text, segment, ord_lista = motor.transkribera(
        samples, per_ord=dela, prompt=prompt, framsteg=lambda a: _satt(id_, "transkriberar", a)
    )
    t1 = time.monotonic()
    antal_talare = None
    if dela and ord_lista:
        lagring.uppdatera(id_, status="talare")
        _satt(id_, "talare", 0.0)
        if kanaler:
            segment, antal_talare, talarvarning = talare.dela_upp_kanaler(
                *kanaler, ord_lista, antal, framsteg=lambda a: _satt(id_, "talare", a), ord_p=motor.ord_grans()
            )
        else:
            segment, antal_talare, talarvarning = talare.dela_upp(
                samples, ord_lista, antal, framsteg=lambda a: _satt(id_, "talare", a), ord_p=motor.ord_grans()
            )
        varning = varning or talarvarning
    t2 = time.monotonic()

    resultat = {
        "text": text,
        "segment": segment,
        "talare": antal_talare,
        "langd_s": round(len(samples) / SR, 1),
        "motor": motor.modellnamn(),
        "tid_s": {"transkribering": round(t1 - t0, 1), "talare": round(t2 - t1, 1)},
    }
    if varning:
        resultat["varning"] = varning
    if kanaler and any(s.get("speaker") == 1 for s in segment) and not (meta.get("namn") or {}).get("1"):
        # Talare 1 ar mikrofonen, alltsa den som spelade in.
        lagring.uppdatera(id_, namn={**(meta.get("namn") or {}), "1": "Du"})
    meta = lagring.uppdatera(
        id_, status="klar", resultat=resultat,
        klar=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    skriv_text(meta)


def _arbetare():
    while True:
        id_ = _ko.get()
        try:
            with plattform.hall_vaken():
                kor(id_)
        except lagring.Fel as e:
            lagring.uppdatera(id_, status="fel", fel=str(e))
        except motor.Avbruten:
            # Programmet avslutas: samma status och text som aterstall_avbrutna() ger vid nasta start.
            log.info("avbruten %s: programmet avslutas", id_)
            try:
                lagring.uppdatera(id_, status="avbruten", fel=lagring.AVBRUTEN)
            except lagring.Fel:
                pass  # inspelningen raderades under tiden
        except motor.MotorFel as e:
            log.error("motorfel %s: %s", id_, e)
            lagring.uppdatera(id_, status="fel", fel=f"Transkriberingen misslyckades: {e}")
        except Exception as e:  # noqa: BLE001 - jobbet far aldrig ta ner arbetstraden
            log.exception("ovantat fel i %s", id_)
            try:
                lagring.uppdatera(id_, status="fel", fel=f"Oväntat fel: {e}")
            except lagring.Fel:
                pass  # inspelningen raderades under tiden
        finally:
            _framsteg.pop(id_, None)
            _ko.task_done()


def starta_arbetare():
    if not _arbetare_startad.is_set():
        _arbetare_startad.set()
        threading.Thread(target=_arbetare, name="transkribering", daemon=True).start()


# --- webbsida och API ----------------------------------------------------------------------

@app.get("/")
def startsida():
    return send_file(os.path.join(app.static_folder, "index.html"))


@app.get("/health")
def health():
    motor.uppdatera()
    fel = motor.problem()
    return jsonify(
        status="ok" if fel is None else "error",
        motor=motor.AKTIV,
        modell=motor.modellnamn(),
        problem=fel,
        talare=talare.problem() or "ok",
        datakatalog=DATAKATALOG,
    ), (200 if fel is None else 503)


# --- modellhamtningen ----------------------------------------------------------------------

def att_hamta():
    """-> (paket, hinder). paket: [(id, [Fil])] i ordningen taligenkanning, talare, bara det som saknas."""
    hinder = motor.hinder()
    if hinder:
        return [], hinder
    paket = []
    if motor.problem() is not None:
        saknas = modeller.saknade(motor.mal_motor(), MODELL)
        if saknas:
            paket.append(("taligenkanning", saknas))
    saknas = modeller.saknade("talare")
    if saknas:
        paket.append(("talare", saknas))
    return paket, None


def paketnamn(id_):
    return modeller.INFO[id_][0].format(storlek=MODELL)


def modellstatus():
    paket, hinder = att_hamta()
    saknas = []
    for id_, filer in paket:
        _namn, beskrivning, licens = modeller.INFO[id_]
        saknas.append({"id": id_, "namn": paketnamn(id_), "beskrivning": beskrivning,
                       "storlek": sum(f.storlek for f in filer),
                       "kalla": f"huggingface.co/{filer[0].repo}", "licens": licens})
    return {
        "redo": motor.problem() is None,
        "hinder": hinder,
        "saknas": saknas,
        "totalt": sum(p["storlek"] for p in saknas),
        "redan_hamtat": sum(modeller.delvis(f) for _, filer in paket for f in filer),
        "ledigt": modeller.ledigt(),
        "katalog": modeller.MODELLKATALOG,
        "hamtning": modeller.HAMTNING.status(),  # slar upp vid anropet, sa att testerna kan byta ut den
    }


@app.get("/api/modeller")
def modeller_status():
    motor.uppdatera()
    return jsonify(modellstatus())


@app.post("/api/modeller/hamta")
def modeller_hamta():
    # Kroppen lases inte: vad som hamtas bestams bara av manifestet i modeller.py.
    motor.uppdatera()
    paket, hinder = att_hamta()
    if hinder:
        return jsonify(error=hinder), 409
    if not paket:
        return jsonify(modellstatus()), 200
    filer = [(paketnamn(id_), fil) for id_, fl in paket for fil in fl]
    startad = modeller.HAMTNING.starta(filer, efter=motor.uppdatera)
    return jsonify(modellstatus()), (202 if startad else 200)


@app.post("/api/modeller/avbryt")
def modeller_avbryt():
    pagick = modeller.HAMTNING.avbryt()
    return jsonify(modellstatus()), (202 if pagick else 200)


@app.get("/api/inspelningar")
def inspelningar():
    return jsonify(inspelningar=[sammanfattning(m) for m in lagring.lista()])


@app.post("/api/inspelningar")
def ny_inspelning():
    data = request.get_json(silent=True) or {}
    meta = lagring.ny_inspelning(data.get("andelse", ".webm"), data.get("titel", ""),
                                 tolka_installningar(data))
    return jsonify(id=meta["id"]), 201


@app.post("/api/inspelningar/fil")
def ladda_upp():
    fil = request.files.get("ljud")
    if fil is None or not fil.filename:
        raise lagring.Fel("Ingen fil valdes.")
    meta = lagring.fran_fil(fil, fil.filename, request.form.get("titel", ""),
                            tolka_installningar(request.form))
    koa(meta["id"])
    return jsonify(id=meta["id"]), 201


@app.post("/api/inspelningar/<id_>/del")
def del_av_inspelning(id_):
    try:
        nr = int(request.args.get("nr", ""))
    except ValueError:
        raise lagring.Fel("nr saknas")
    meta = lagring.lagg_till_del(id_, nr, request.get_data(cache=False))
    return jsonify(delar=meta["delar"])


@app.post("/api/inspelningar/<id_>/klar")
def inspelning_klar(id_):
    data = request.get_json(silent=True) or {}
    meta = lagring.avsluta_inspelning(id_)
    # Rubriken kan ha skrivits in under motet: den som star i faltet vid stopp galler.
    titel = str(data.get("titel") or "").strip()[:200]
    if titel:
        meta = lagring.uppdatera(id_, titel=titel)
    if data.get("starta", True):
        inst = tolka_installningar(data) if "talare" in data else None
        meta = koa(id_, inst)
    return jsonify(id=id_, status=meta["status"])


@app.post("/api/inspelningar/<id_>/transkribera")
def transkribera_igen(id_):
    meta = koa(id_, tolka_installningar(request.get_json(silent=True) or {}))
    return jsonify(id=id_, status=meta["status"])


@app.get("/api/inspelningar/<id_>")
def en_inspelning(id_):
    return jsonify(med_framsteg(lagring.las(id_)))


@app.post("/api/inspelningar/<id_>/titel")
def satt_titel(id_):
    data = request.get_json(silent=True) or {}
    meta = lagring.uppdatera(id_, titel=str(data.get("titel", "")).strip()[:200])
    if meta.get("resultat"):
        skriv_text(meta)
    return jsonify(titel=meta["titel"], rubrik=export.rubrik(meta))


@app.post("/api/inspelningar/<id_>/namn")
def satt_namn(id_):
    data = request.get_json(silent=True) or {}
    namn = {
        str(k): str(v).strip()[:60]
        for k, v in data.items()
        if re.fullmatch(r"\d{1,2}", str(k)) and str(v).strip()
    }
    meta = lagring.uppdatera(id_, namn=namn)
    if meta.get("resultat"):
        skriv_text(meta)
    return jsonify(namn=namn)


@app.post("/api/inspelningar/<id_>/talare")
def ratta_talare(id_):
    """Byt talare för en replik, en del av den (orden fran..till) eller alla repliker från en
    talare (alla). text måste vara repliken som webbsidan visade, annars har något ändrats."""
    data = request.get_json(silent=True) or {}
    with lagring._las:
        meta = lagring.las(id_)
        if meta["status"] in lagring.PAGAENDE:
            raise lagring.Fel("Inspelningen transkriberas just nu.", 409)
        res = meta.get("resultat") or {}
        segment = res.get("segment") or []
        i = data.get("replik")
        if not isinstance(i, int) or not 0 <= i < len(segment) or "speaker" not in segment[i]:
            raise lagring.Fel("Repliken finns inte.")
        if segment[i]["text"] != data.get("text"):
            raise lagring.Fel("Texten har ändrats sedan sidan visades. Ladda om sidan.", 409)
        talare_nr = data.get("talare")
        if talare_nr == "ny":
            talare_nr = rattning.nytt_nummer(segment, meta.get("namn"))
        if not isinstance(talare_nr, int) or isinstance(talare_nr, bool) or not 1 <= talare_nr <= 99:
            raise lagring.Fel("Ogiltig talare.")
        try:
            if data.get("alla"):
                nya = rattning.sla_ihop_talare(segment, segment[i]["speaker"], talare_nr)
            else:
                fran, till = data.get("fran"), data.get("till")
                if any(x is not None and (not isinstance(x, int) or isinstance(x, bool)) for x in (fran, till)):
                    raise ValueError("ogiltiga ord")
                nya = rattning.byt_talare(segment, i, talare_nr, fran, till)
        except ValueError as e:
            raise lagring.Fel(f"Kunde inte byta talare: {e}.")
        res.setdefault("segment_original", segment)  # maskinens version, för att kunna ångra
        res["segment"] = nya
        res["talare"] = len({s["speaker"] for s in nya if "speaker" in s})
        meta["resultat"] = res
        lagring.spara(meta)
    skriv_text(meta)
    return jsonify(talare=talare_nr)


@app.post("/api/inspelningar/<id_>/talare/angra")
def angra_talare(id_):
    """Tillbaka till maskinens version: alla rättningar av talare försvinner."""
    with lagring._las:
        meta = lagring.las(id_)
        res = meta.get("resultat") or {}
        if "segment_original" not in res:
            raise lagring.Fel("Det finns inga rättningar att ångra.", 409)
        res["segment"] = res.pop("segment_original")
        res["talare"] = len({s["speaker"] for s in res["segment"] if "speaker" in s})
        lagring.spara(meta)
    skriv_text(meta)
    return jsonify(ok=True)


def filnamn(meta):
    return re.sub(r'[\\/:*?"<>|]+', "-", export.rubrik(meta)).strip() or meta["id"]


@app.get("/api/inspelningar/<id_>/text.<fmt>")
def ladda_ner_text(id_, fmt):
    meta = lagring.las(id_)
    if not meta.get("resultat"):
        raise lagring.Fel("Inspelningen är inte transkriberad än.", 409)
    if fmt == "md":
        innehall, mime = export.som_markdown(meta), "text/markdown"
    elif fmt == "txt":
        innehall, mime = export.som_text(meta), "text/plain"
    else:
        raise lagring.Fel("Formatet finns inte.", 404)
    return send_file(io.BytesIO(innehall.encode("utf-8")), mimetype=f"{mime}; charset=utf-8",
                     as_attachment=True, download_name=f"{filnamn(meta)}.{fmt}")


@app.get("/api/inspelningar/<id_>/ljud")
def ljud(id_):
    meta = lagring.las(id_)
    if request.args.get("ladda_ner"):
        return send_file(lagring.ljudfil(meta), as_attachment=True,
                         download_name=f"{filnamn(meta)}{meta.get('andelse', '')}")
    return send_file(lagring.ljudfil(meta), conditional=True)


@app.post("/api/inspelningar/<id_>/radera")
def radera(id_):
    if lagring.las(id_)["status"] in lagring.PAGAENDE:
        raise lagring.Fel("Vänta tills transkriberingen är klar.", 409)
    lagring.radera(id_)
    return jsonify(raderad=id_)


@app.post("/transcribe")
def transkribera_direkt():
    """For skript och halsokollar: multipart 'audio', valfritt 'speakers'. Svarar direkt."""
    fil = request.files.get("audio")
    if fil is None:
        raise lagring.Fel("saknar faltet 'audio'")
    antal = 1
    if "speakers" in request.form:
        try:
            antal = talare.tolka_antal(request.form["speakers"])
        except ValueError:
            raise lagring.Fel("speakers maste vara 1-10 eller auto")
        if antal != 1 and talare.problem():
            return jsonify(error=talare.problem()), 503
    data = fil.read()
    # En egen katalog i stallet for NamedTemporaryFile: Windows later inte en oppen temporar fil
    # oppnas igen med namnet, och avkodaren oppnar den.
    with tempfile.TemporaryDirectory(prefix="akasha-protokoll-") as katalog:
        sokvag = os.path.join(katalog, "ljud" + (os.path.splitext(fil.filename or "")[1] or ".audio"))
        with open(sokvag, "wb") as f:
            f.write(data)
        t0 = time.time()
        try:
            samples = motor.avkoda(sokvag)
        except Exception as e:
            raise lagring.Fel(f"ljudet kunde inte lasas: {e}")
    try:
        text, segment, ord_lista = motor.transkribera(samples, per_ord=antal != 1, prompt=ORDLISTA)
    except motor.MotorFel as e:
        return jsonify(error=str(e)), 502
    svar = {"text": text, "duration_s": round(len(samples) / SR, 2), "model": motor.modellnamn()}
    if antal != 1:
        t1 = time.time()
        segment, svar["speakers"], talarvarning = talare.dela_upp(samples, ord_lista, antal)
        if talarvarning:
            svar["warning"] = talarvarning
        svar["speakers_elapsed_s"] = round(time.time() - t1, 3)
    svar["segments"] = segment
    svar["elapsed_s"] = round(time.time() - t0, 3)
    return jsonify(svar)


def forbered():
    """Det som maste goras en gang innan tjansten tar emot anrop."""
    os.makedirs(DATAKATALOG, mode=0o700, exist_ok=True)
    lagring.aterstall_avbrutna()
    starta_arbetare()


def skapa_server(port=PORT):
    """waitress-servern, bunden till 127.0.0.1. Kastar OSError om porten ar upptagen."""
    from waitress import create_server

    return create_server(app, host="127.0.0.1", port=port, threads=8,
                         max_request_body_size=MAX_MB * 1024 * 1024)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for text in installningar.PROBLEM:
        log.warning("installningar: %s", text)
    forbered()
    server = skapa_server()
    log.info("Akasha Protokoll: http://127.0.0.1:%s (motor %s, data i %s)", PORT, motor.AKTIV, DATAKATALOG)
    if motor.problem():
        log.warning("motorn ar inte redo: %s", motor.problem())
    server.run()


if __name__ == "__main__":
    main()
