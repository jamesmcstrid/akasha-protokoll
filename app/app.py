"""Akasha Meet: transkribera moten lokalt. Webbsida och API pa http://127.0.0.1:PORT.

Lyssnar ALLTID bara pa 127.0.0.1, sa ingen annan dator kommer at tjansten. Skydd mot att andra
webbsidor i samma webblasare anropar den:
  - Host maste vara localhost eller 127.0.0.1 (stoppar DNS-rebinding).
  - Allt som andrar nagot kraver headern X-Akasha-Meet: 1. En annan sajt kan bara skicka den
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

from flask import Flask, jsonify, request, send_file

import export
import lagring
import motor
import talare
from installningar import DATAKATALOG, MAX_MB, ORDLISTA, PORT

HEADER = "X-Akasha-Meet"
VARDAR = {"127.0.0.1", "localhost", "::1"}
SR = motor.SR

log = logging.getLogger("akasha-meet")
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

_ko = queue.Queue()
_framsteg = {}  # id -> {"fas": ..., "andel": 0..1}, bara i minnet
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
    return {"talare": antal, "ord": ord_}


def med_framsteg(meta):
    meta = dict(meta)
    meta["rubrik"] = export.rubrik(meta)
    meta["info"] = export.info(meta)
    if meta["status"] in lagring.PAGAENDE and meta["id"] in _framsteg:
        meta["framsteg"] = _framsteg[meta["id"]]
    return meta


def sammanfattning(meta):
    m = med_framsteg(meta)
    res = m.pop("resultat", None) or {}
    m["har_text"] = bool(res.get("segment"))
    m["langd_s"] = res.get("langd_s")
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
            meta["installningar"] = installningar
        meta["status"] = "koar"
        meta.pop("fel", None)
        lagring.spara(meta)
    _framsteg[id_] = {"fas": "koar", "andel": 0.0}
    _ko.put(id_)
    return meta


def _satt(id_, fas, andel):
    _framsteg[id_] = {"fas": fas, "andel": round(max(0.0, min(1.0, andel)), 3)}


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

    t0 = time.time()
    try:
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
    t1 = time.time()
    antal_talare = None
    if dela and ord_lista:
        lagring.uppdatera(id_, status="talare")
        _satt(id_, "talare", 0.0)
        segment, antal_talare, talarvarning = talare.dela_upp(
            samples, ord_lista, antal, framsteg=lambda a: _satt(id_, "talare", a)
        )
        varning = varning or talarvarning
    t2 = time.time()

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
    meta = lagring.uppdatera(
        id_, status="klar", resultat=resultat,
        klar=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    skriv_text(meta)


def _arbetare():
    while True:
        id_ = _ko.get()
        try:
            kor(id_)
        except lagring.Fel as e:
            lagring.uppdatera(id_, status="fel", fel=str(e))
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
    fel = motor.problem()
    return jsonify(
        status="ok" if fel is None else "error",
        motor=motor.AKTIV,
        modell=motor.modellnamn(),
        problem=fel,
        talare=talare.problem() or "ok",
        datakatalog=DATAKATALOG,
    ), (200 if fel is None else 503)


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
    filnamn = re.sub(r'[\\/:*?"<>|]+', "-", export.rubrik(meta)).strip() or meta["id"]
    return send_file(io.BytesIO(innehall.encode("utf-8")), mimetype=f"{mime}; charset=utf-8",
                     as_attachment=True, download_name=f"{filnamn}.{fmt}")


@app.get("/api/inspelningar/<id_>/ljud")
def ljud(id_):
    return send_file(lagring.ljudfil(lagring.las(id_)), conditional=True)


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
    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(fil.filename or "")[1] or ".audio") as tmp:
        tmp.write(data)
        tmp.flush()
        t0 = time.time()
        try:
            samples = motor.avkoda(tmp.name)
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


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATAKATALOG, mode=0o700, exist_ok=True)
    lagring.aterstall_avbrutna()
    starta_arbetare()
    from waitress import serve

    log.info("Akasha Meet: http://127.0.0.1:%s (motor %s, data i %s)", PORT, motor.AKTIV, DATAKATALOG)
    if motor.problem():
        log.warning("motorn ar inte redo: %s", motor.problem())
    serve(app, host="127.0.0.1", port=PORT, threads=8,
          max_request_body_size=MAX_MB * 1024 * 1024)


if __name__ == "__main__":
    main()
