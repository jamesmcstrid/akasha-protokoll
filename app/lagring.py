"""Inspelningar och resultat pa disk, i DATAKATALOG. Allt stannar pa den har datorn.

  <id>.<andelse>  ljudet (inspelat i webblasaren eller uppladdat)
  <id>.json       uppgifter, status och resultat
  <id>.md         transkriberingen som text (skrivs om nar talarna far namn)

id ar tidpunkten, t.ex. 20261117-140312 (med -2, -3 ... om tva startar samma sekund).
Status: spelar_in, sparad, koar, transkriberar, talare, klar, fel, avbruten.
"""
import json
import os
import re
import threading
import time
from datetime import datetime

from installningar import DATAKATALOG

ID_RE = re.compile(r"^\d{8}-\d{6}(-\d{1,3})?$")
ANDELSER = {".webm", ".m4a", ".mp4", ".mp3", ".wav", ".ogg", ".oga", ".opus", ".aac", ".flac", ".mov"}
PAGAENDE = {"koar", "transkriberar", "talare"}
AVBRUTEN = "Transkriberingen avbröts eftersom Akasha Meet avslutades. Tryck Försök igen för att göra om den."

_las = threading.RLock()


class Fel(Exception):
    """Felaktig begaran. kod ar HTTP-statusen."""

    def __init__(self, meddelande, kod=400):
        super().__init__(meddelande)
        self.kod = kod


def _sokvag(id_, andelse):
    if not ID_RE.fullmatch(id_ or ""):
        raise Fel("ogiltigt id", 404)
    return os.path.join(DATAKATALOG, id_ + andelse)


def ljudfil(meta):
    return _sokvag(meta["id"], meta["andelse"])


def textfil(id_):
    return _sokvag(id_, ".md")


def las(id_):
    try:
        with open(_sokvag(id_, ".json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise Fel("inspelningen finns inte", 404)


def spara(meta):
    """Skriv atomiskt: en halvskriven fil ska aldrig kunna ersatta en hel."""
    sokvag = _sokvag(meta["id"], ".json")
    tmp = sokvag + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    # Pa Windows ger os.replace PermissionError om en annan trad just laser .json-filen (listan
    # lases varannan sekund medan ett jobb skriver). Det gar over efter nagra millisekunder.
    for forsok in range(5):
        try:
            os.replace(tmp, sokvag)
            return
        except PermissionError:
            if forsok == 4:
                raise
            time.sleep(0.05)


def uppdatera(id_, **falt):
    with _las:
        meta = las(id_)
        meta.update(falt)
        spara(meta)
        return meta


def _ny(andelse, titel, installningar, status):
    andelse = (andelse or "").lower()
    if not andelse.startswith("."):
        andelse = "." + andelse
    if andelse not in ANDELSER:
        raise Fel(f"filtypen {andelse} stods inte")
    os.makedirs(DATAKATALOG, exist_ok=True)
    nu = datetime.now().astimezone()
    bas = nu.strftime("%Y%m%d-%H%M%S")
    with _las:
        for n in range(1, 1000):
            id_ = bas if n == 1 else f"{bas}-{n}"
            # "x": skapas exklusivt, en befintlig inspelning skrivs aldrig over. Id:t reserveras
            # med .json-filen, som heter likadant oavsett ljudformat.
            try:
                with open(_sokvag(id_, ".json"), "x"):
                    pass
            except FileExistsError:
                continue
            try:
                with open(_sokvag(id_, andelse), "xb"):
                    pass
                break
            except FileExistsError:  # kvarglomd ljudfil utan uppgifter: lat den vara
                os.remove(_sokvag(id_, ".json"))
                continue
        else:
            raise Fel("kunde inte skapa en ny inspelning", 500)
        meta = {
            "id": id_,
            "skapad": nu.isoformat(timespec="seconds"),
            "titel": (titel or "").strip()[:200],
            "andelse": andelse,
            "status": status,
            "delar": 0,
            "installningar": installningar,
            "namn": {},
        }
        spara(meta)
    return meta


def ny_inspelning(andelse, titel, installningar):
    """Inspelning i webblasaren. Ljudet kommer i delar via lagg_till_del."""
    return _ny(andelse, titel, installningar, "spelar_in")


def fran_fil(filobjekt, filnamn, titel, installningar):
    """Uppladdad fil (werkzeug FileStorage).

    Filnamnet anvands bara for att se filtypen, aldrig som rubrik och sparas inte: Rostmemon pa
    iPhone dopar inspelningar efter platsen, sa filnamnet ar ofta en gatuadress.
    """
    meta = _ny(os.path.splitext(filnamn or "")[1], titel, installningar, "sparad")
    filobjekt.save(ljudfil(meta))
    if os.path.getsize(ljudfil(meta)) == 0:
        radera(meta["id"])
        raise Fel("filen ar tom")
    return meta


def lagg_till_del(id_, nr, data):
    """Lagg till del nr (0, 1, 2 ...) av en pagaende inspelning.

    Ett omsandt del-nummer (nr < antal mottagna) godtas utan att skrivas igen, sa att
    webblasaren kan forsoka igen efter ett natverksfel. En lucka (nr > antal) avvisas.
    """
    with _las:
        meta = las(id_)
        if meta["status"] != "spelar_in":
            raise Fel("inspelningen ar redan avslutad", 409)
        if nr < meta["delar"]:
            return meta
        if nr > meta["delar"]:
            raise Fel(f"del {nr} kom fore del {meta['delar']}", 409)
        with open(ljudfil(meta), "ab") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        meta["delar"] += 1
        spara(meta)
        return meta


def avsluta_inspelning(id_):
    with _las:
        meta = las(id_)
        if meta["status"] == "spelar_in":
            meta["status"] = "sparad"
            spara(meta)
        return meta


def lista():
    if not os.path.isdir(DATAKATALOG):
        return []
    ut = []
    for namn in os.listdir(DATAKATALOG):
        id_, andelse = os.path.splitext(namn)
        if andelse == ".json" and ID_RE.fullmatch(id_):
            try:
                ut.append(las(id_))
            except (Fel, ValueError):
                continue
    return sorted(ut, key=lambda m: m["id"], reverse=True)


def radera(id_):
    with _las:
        meta = las(id_)
        for sokvag in (ljudfil(meta), textfil(id_), _sokvag(id_, ".json")):
            try:
                os.remove(sokvag)
            except FileNotFoundError:
                pass


def aterstall_avbrutna():
    """Vid start: transkriberingar som pagick nar tjansten stannade markeras som avbrutna.

    Inspelningar med status spelar_in lamnas orda: webblasaren kan fortfarande skicka delar,
    och annars gar de att avsluta fran listan.
    """
    for meta in lista():
        if meta["status"] in PAGAENDE:
            uppdatera(meta["id"], status="avbruten", fel=AVBRUTEN)
