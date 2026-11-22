"""Inspelningar och resultat pa disk, i DATAKATALOG. Allt stannar pa den har datorn.

  <id>.<andelse>  ljudet (inspelat i webblasaren eller uppladdat)
  <id>.json       uppgifter, status och resultat
  <id>.md         transkriberingen som text (skrivs om nar talarna far namn)

id ar tidpunkten, t.ex. 20261117-140312 (med -2, -3 ... om tva startar samma sekund).
Status: spelar_in, sparad, koar, transkriberar, talare, klar, fel, avbruten.
"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime

from installningar import DATAKATALOG

ID_RE = re.compile(r"^\d{8}-\d{6}(-\d{1,3})?$")
ANDELSER = {".webm", ".m4a", ".mp4", ".mp3", ".wav", ".ogg", ".oga", ".opus", ".aac", ".flac", ".mov"}
PAGAENDE = {"koar", "transkriberar", "talare"}
AVBRUTEN = "Transkriberingen avbröts eftersom Akasha Protokoll avslutades. Tryck Försök igen för att göra om den."

_las = threading.RLock()
log = logging.getLogger(__name__)
# sammanfattningar(): id -> ((st_mtime_ns, st_size) for .json-filen, _kort()). Andras bara med _las.
_kortcache = {}

# Windows: den som oppnar .json-filen precis nar den byts ut (eller nar utomstaende program som
# Defender eller sokindexering haller den) far PermissionError nagra millisekunder.
OMFORSOK = 10
OMFORSOK_PAUS = 0.05


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
    sokvag = _sokvag(id_, ".json")
    # Laset gor att ingen lasning i programmet kan krocka med ett utbyte i spara(). Det halls ocksa
    # under de korta omforsoken nedan (hogst OMFORSOK * OMFORSOK_PAUS = 0,5 s): ett utomstaende
    # program haller filen bara en kort stund, och annars kunde en skrivare hinna byta ut filen
    # mitt i omforsoken.
    with _las:
        for forsok in range(OMFORSOK):
            try:
                with open(sokvag, encoding="utf-8") as f:
                    return json.load(f)
            except FileNotFoundError:
                raise Fel("inspelningen finns inte", 404)
            except PermissionError:
                if forsok == OMFORSOK - 1:
                    raise
                time.sleep(OMFORSOK_PAUS)


def spara(meta):
    """Skriv atomiskt: en halvskriven fil ska aldrig kunna ersatta en hel."""
    sokvag = _sokvag(meta["id"], ".json")
    tmp = sokvag + ".tmp"
    with _las:  # se las(): lasare och skrivare i programmet tar turas
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        # Pa Windows ger os.replace PermissionError om nagon just har .json-filen oppen (listan
        # lases varannan sekund medan ett jobb skriver, eller ett utomstaende program). Det gar
        # over efter nagra millisekunder.
        for forsok in range(OMFORSOK):
            try:
                os.replace(tmp, sokvag)
                _kortcache.pop(meta["id"], None)
                return
            except PermissionError:
                if forsok == OMFORSOK - 1:
                    raise
                time.sleep(OMFORSOK_PAUS)


def uppdatera(id_, **falt):
    with _las:
        meta = las(id_)
        meta.update(falt)
        spara(meta)
        return meta


def _ny(andelse, titel, installningar, status):
    """Reserverar ett nytt id -> uppgifterna, som inte ar sparade an.

    Id:t reserveras med en tom .json-fil och en tom ljudfil, bada skapade exklusivt. Den tomma
    .json-filen gar inte att tolka, sa lista() hoppar over den tills spara() har skrivit den.
    """
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
    return {
        "id": id_,
        "skapad": nu.isoformat(timespec="seconds"),
        "titel": (titel or "").strip()[:200],
        "andelse": andelse,
        "status": status,
        "delar": 0,
        "installningar": installningar,
        "namn": {},
    }


def ny_inspelning(andelse, titel, installningar):
    """Inspelning i webblasaren. Ljudet kommer i delar via lagg_till_del."""
    with _las:
        meta = _ny(andelse, titel, installningar, "spelar_in")
        meta["byte"] = 0  # ljudet i de mottagna delarna, se lagg_till_del
        spara(meta)
    return meta


def _ta_bort(*sokvagar):
    """Stadar efter ett fel: kastar aldrig, sa att det forsta felet ar det som syns."""
    for sokvag in sokvagar:
        try:
            os.remove(sokvag)
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("kunde inte ta bort %s: %s", os.path.basename(sokvag), e)


def fran_fil(filobjekt, filnamn, titel, installningar):
    """Uppladdad fil (werkzeug FileStorage).

    Filnamnet anvands bara for att se filtypen, aldrig som rubrik och sparas inte: Rostmemon pa
    iPhone dopar inspelningar efter platsen, sa filnamnet ar ofta en gatuadress.

    Ljudet skrivs forst till <id><andelse>.delvis, som lista() inte ser. Forst nar hela filen ar
    skriven, och inte ar tom, far den ljudfilens namn och uppgifterna sparas: inspelningen syns
    aldrig halvfardig. Vid ett fel tas allt bort, sist reservationen av id:t.
    """
    meta = _ny(os.path.splitext(filnamn or "")[1], titel, installningar, "sparad")
    ljud = ljudfil(meta)
    delvis = ljud + ".delvis"
    uppgifter = _sokvag(meta["id"], ".json")
    try:
        filobjekt.save(delvis)
        if os.path.getsize(delvis) == 0:
            raise Fel("filen ar tom")
        with _las:
            os.replace(delvis, ljud)  # ljudfilen ar var egen: tom och skapad exklusivt av _ny
            spara(meta)
    except BaseException:
        _ta_bort(delvis, ljud, uppgifter + ".tmp", uppgifter)
        raise
    return meta


def lagg_till_del(id_, nr, data):
    """Lagg till del nr (0, 1, 2 ...) av en pagaende inspelning.

    Ett omsandt del-nummer (nr < antal mottagna) godtas utan att skrivas igen, sa att
    webblasaren kan forsoka igen efter ett natverksfel. En lucka (nr > antal) avvisas.

    meta["byte"] ar langden pa ljudet i de mottagna delarna. En del som skrevs men vars uppgifter
    aldrig sparades (fel i spara() eller en krasch emellan) kommer igen fran webblasaren, och far
    inte hamna tva ganger i ljudet: filen kortas tillbaka. Aldre inspelningar utan byte kortas
    inte fore skrivningen.
    """
    with _las:
        meta = las(id_)
        if meta["status"] != "spelar_in":
            raise Fel("inspelningen ar redan avslutad", 409)
        if nr < meta["delar"]:
            return meta
        if nr > meta["delar"]:
            raise Fel(f"del {nr} kom fore del {meta['delar']}", 409)
        sokvag = ljudfil(meta)
        try:
            fore = os.path.getsize(sokvag)
        except FileNotFoundError:
            fore = 0  # som forut: "ab" skapar filen
        if meta.get("byte") is not None and fore > meta["byte"]:
            log.warning("%s: %d byte utan sparade uppgifter fore del %d tas bort", id_, fore - meta["byte"], nr)
            os.truncate(sokvag, meta["byte"])
            fore = meta["byte"]
        try:
            with open(sokvag, "ab") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
                meta["byte"] = os.fstat(f.fileno()).st_size
            meta["delar"] += 1
            spara(meta)
        except BaseException:
            # Uppgifterna pa disken sager att delen saknas: da ska ljudet inte heller ha den.
            try:
                os.truncate(sokvag, fore)
            except OSError as e:
                log.warning("%s: kunde inte korta ljudet efter ett fel: %s", id_, e)
            raise
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
            except PermissionError:
                log.warning("hoppar over %s i listan: filen gar inte att lasa", id_)
                continue
    return sorted(ut, key=lambda m: m["id"], reverse=True)


def _kort(meta):
    """Det listan behover ur en inspelning: allt utom texten, som kan vara flera MB. resultat har
    bara langd_s och talare kvar (export.info visar dem), och har_text, langd_s och rattad raknas
    ut har."""
    kort = {k: v for k, v in meta.items() if k != "resultat"}
    res = meta.get("resultat") or {}
    if res:
        kort["resultat"] = {k: res[k] for k in ("langd_s", "talare") if k in res}
    kort["har_text"] = bool(res.get("segment"))
    kort["langd_s"] = res.get("langd_s")
    kort["rattad"] = "segment_original" in res  # talarna har rattats for hand
    return kort


def sammanfattningar():
    """_kort() for varje inspelning, nyast forst: listan som webbsidan fragar efter varannan sekund.

    En .json-fil lases bara om nar (st_mtime_ns, st_size) har andrats sedan forra gangen, och
    spara() och radera() tar bort sin post direkt. Den som behover hela uppgifterna anvander lista().
    Det som returneras ar kopior, men de inre ordlistorna (installningar, namn) far inte andras.
    """
    if not os.path.isdir(DATAKATALOG):
        return []
    ut, sedda = [], set()
    for namn in os.listdir(DATAKATALOG):
        id_, andelse = os.path.splitext(namn)
        if andelse != ".json" or not ID_RE.fullmatch(id_):
            continue
        sedda.add(id_)
        try:
            with _las:  # ingen spara() mellan stat, lasningen och cachen
                st = os.stat(_sokvag(id_, ".json"))
                nyckel = (st.st_mtime_ns, st.st_size)
                post = _kortcache.get(id_)
                if post is None or post[0] != nyckel:
                    post = (nyckel, _kort(las(id_)))
                    _kortcache[id_] = post
        except (Fel, ValueError, FileNotFoundError):
            continue
        except PermissionError:
            log.warning("hoppar over %s i listan: filen gar inte att lasa", id_)
            continue
        ut.append(dict(post[1]))
    with _las:
        for id_ in set(_kortcache) - sedda:  # borttagna utanfor programmet
            del _kortcache[id_]
    return sorted(ut, key=lambda m: m["id"], reverse=True)


def radera(id_):
    with _las:
        meta = las(id_)
        for sokvag in (ljudfil(meta), textfil(id_), _sokvag(id_, ".json")):
            try:
                os.remove(sokvag)
            except FileNotFoundError:
                pass
        _kortcache.pop(id_, None)


def stada_halvfardiga():
    """Vid start: det som en uppladdning lamnade efter sig om programmet stannade mitt i den.

    Tar bara bort <id><andelse>.delvis (en ofullstandig kopia av en fil som anvandaren fortfarande
    har) och reservationer dar bade .json-filen och ljudfilen ar tomma. En reservation med ljud
    i lamnas orord. Far bara koras innan tjansten tar emot anrop: da pagar ingen uppladdning.
    """
    if not os.path.isdir(DATAKATALOG):
        return
    with _las:
        for namn in os.listdir(DATAKATALOG):
            sokvag = os.path.join(DATAKATALOG, namn)
            if namn.endswith(".delvis"):
                id_, andelse = os.path.splitext(namn[: -len(".delvis")])
                if ID_RE.fullmatch(id_) and andelse in ANDELSER:
                    log.info("tar bort en avbruten uppladdning: %s", namn)
                    _ta_bort(sokvag)
                continue
            id_, andelse = os.path.splitext(namn)
            if andelse != ".json" or not ID_RE.fullmatch(id_):
                continue
            try:
                if os.path.getsize(sokvag) != 0:
                    continue
                ljud = [_sokvag(id_, a) for a in ANDELSER if os.path.exists(_sokvag(id_, a))]
                if any(os.path.getsize(s) != 0 for s in ljud):
                    continue
            except OSError:
                continue
            log.info("tar bort en tom reservation: %s", id_)
            _ta_bort(*ljud, sokvag)


def aterstall_avbrutna():
    """Vid start: transkriberingar som pagick nar tjansten stannade markeras som avbrutna.

    Inspelningar med status spelar_in lamnas orda: webblasaren kan fortfarande skicka delar,
    och annars gar de att avsluta fran listan.
    """
    for meta in lista():
        if meta["status"] in PAGAENDE:
            uppdatera(meta["id"], status="avbruten", fel=AVBRUTEN)
