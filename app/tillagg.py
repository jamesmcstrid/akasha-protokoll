"""Tillagg: valfria, separat installerade paket som bygger ut programmet.

Utan tillagg gor den har modulen ingenting, och programmet beter sig som forut. Ett tillagg ar en
katalog med en fil tillagg.py. Den hittas i (forsta traffen per namn vinner):
  1. varje katalog i installningen TILLAGG (skilda med os.pathsep)
  2. <programkatalogen>/tillagg

Mappnamnet blir tilleggets id. tillagg.py maste ha NAMN (text), KRAVER_API (heltal, se API_VERSION)
och registrera(api); VERSION (text) ar valfri. Ett tillagg som inte gar att ladda (fel API-version, ett
undantag vid import eller registrera) blir inte aktivt och programmet startar anda: orsaken loggas och
visas i status(). Tillaggen laddas en gang, i app.forbered(), innan tjansten tar emot anrop: Flask tar
inte emot nya vagar efter den forsta begaran.
"""
import functools
import importlib.util
import logging
import os
import re
import sys

from flask import abort, send_from_directory

import installningar
import plattform

API_VERSION = 1
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

log = logging.getLogger("akasha-protokoll.tillagg")

_aktiva = []  # [{"id", "namn", "version", "katalog"}]
_problem = []  # korta texter for anvandaren
_laddat = False
# namn -> [(id, funktion)]. Se Api.vid_* och kor_*.
_krokar = {"inspelning": [], "radera": [], "hindrar": [], "start": [], "stopp": []}
_tillagda_sokvagar = []  # det ladda() lagt i sys.path, sa att _nollstall() kan ta bort det


class _Avvisat(Exception):
    """Tillagget kan inte laddas. Texten visas for anvandaren."""


class Api:
    """Det enda ett tillagg far lita pa: registrera(api) far en instans per tillagg.

    Tillagg lagger bara till vagar under /api/tillagg/<id>/ (api.route) och sidor under
    /tillagg/<id>/ (api.statisk). Det som andrar nagot (POST, PUT, DELETE) skyddas av samma
    kontroll som programmets egna anrop: Host och headern X-Akasha-Protokoll.

    Attribut, bara att lasa:
      app        Flask-appen. Anvand api.route, inte app.route, sa att vagarna hamnar under /api/tillagg/<id>/.
      id         tilleggets id (mappnamnet)
      lagring, export, modeller, plattform   programmets moduler med samma namn
      log        en logger for tillagget
    """

    def __init__(self, app_modul, id_):
        self._modul = app_modul
        self._aktiv = False  # satts av ladda() nar registrera() gatt bra
        self.id = id_
        self.app = app_modul.app
        self.lagring = app_modul.lagring
        self.export = app_modul.export
        self.modeller = app_modul.modeller
        self.plattform = app_modul.plattform
        self.log = logging.getLogger(f"akasha-protokoll.tillagg.{id_}")

    def _skydda(self, vy):
        """En vag som registrerats av ett tillagg som sedan inte blev aktivt svarar 404:
        Flask gar inte att be ta bort en vag."""
        @functools.wraps(vy)
        def skyddad(*a, **k):
            if not self._aktiv:
                abort(404)
            return vy(*a, **k)
        return skyddad

    def route(self, regel, **val):
        """Som app.route, men regeln hamnar under /api/tillagg/<id>/. Svarar med JSON; GET som standard."""
        def dekor(vy):
            val["endpoint"] = f"tillagg_{self.id}_{val.get('endpoint') or vy.__name__}"
            self.app.route(f"/api/tillagg/{self.id}/{regel.lstrip('/')}", **val)(self._skydda(vy))
            return vy
        return dekor

    def statisk(self, katalog):
        """Servera filerna i katalog pa /tillagg/<id>/<fil> (bara GET). Sidan laddar tillagg.js och
        tillagg.css darifran. Filtyperna ar programmets egen tabell; allt utanfor katalog ger 404."""
        katalog = os.path.abspath(katalog)

        def servera(fil):
            return send_from_directory(katalog, fil, mimetype=self._modul.filtyp(fil) or "application/octet-stream")

        self.app.add_url_rule(f"/tillagg/{self.id}/<path:fil>", endpoint=f"tillagg_{self.id}_statisk",
                              view_func=self._skydda(servera), methods=["GET"])

    def koa(self, funktion):
        """Kor funktion() i bakgrundstraden som transkriberar, sa att bara ett tungt jobb pagar at gangen.
        Ett undantag loggas och stoppar varken traden eller jobben efter."""
        if not callable(funktion):
            raise TypeError("koa tar en funktion")
        self._modul._ko.put(funktion)

    def vid_inspelning(self, fn):
        """fn(meta) -> dict | None. Ett dict laggs till i GET /api/inspelningar/<id> under tillagg[<id>].
        meta ar inspelningens uppgifter: andra dem inte."""
        self._ny("inspelning", fn)

    def vid_radera(self, fn):
        """fn(id_) anropas precis innan en inspelnings filer tas bort, under lagring._las, sa att tillagget
        kan ta bort sina egna filer (<id>.*). Ett undantag loggas och raderingen fortsatter."""
        self._ny("radera", fn)

    def hindrar(self, fn):
        """fn(meta) -> text | None. Ger den text svarar radera och transkribera igen 409 med texten."""
        self._ny("hindrar", fn)

    def vid_start(self, fn):
        """fn() anropas en gang vid start, efter programmets egen stadning."""
        self._ny("start", fn)

    def vid_stopp(self, fn):
        """fn() anropas nar programmet stangs, tillsammans med att motorn stoppas (for barnprocesser)."""
        self._ny("stopp", fn)

    def _ny(self, namn, fn):
        if not callable(fn):
            raise TypeError("en funktion behovs")
        _krokar[namn].append((self.id, fn))


# --- laddning -----------------------------------------------------------------------------

def _sokkataloger():
    kataloger = [os.path.abspath(os.path.expanduser(k)) for k in installningar.TILLAGG.split(os.pathsep) if k.strip()]
    kataloger.append(os.path.join(plattform.programkatalog(), "tillagg"))
    return kataloger


def _hitta():
    """-> [(id, katalog)] i sokordningen; det forsta tillagget med ett namn vinner."""
    sedda, ut = set(), []
    for bas in _sokkataloger():
        try:
            namn = sorted(os.listdir(bas))
        except OSError:
            continue
        for n in namn:
            katalog = os.path.join(bas, n)
            if n not in sedda and os.path.isfile(os.path.join(katalog, "tillagg.py")):
                sedda.add(n)
                ut.append((n, katalog))
    return ut


def _importera(id_, katalog):
    """Laddar tillagg.py under ett eget modulnamn. Katalogen laggs sist i sys.path sa att tillagget kan
    importera sina egna moduler; programmets moduler gar alltid fore."""
    if katalog not in sys.path:
        sys.path.append(katalog)
        _tillagda_sokvagar.append(katalog)
    spec = importlib.util.spec_from_file_location(f"akasha_tillagg_{id_}", os.path.join(katalog, "tillagg.py"))
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


def _kontrollera(modul):
    if not isinstance(getattr(modul, "NAMN", None), str) or not callable(getattr(modul, "registrera", None)):
        raise _Avvisat("saknar NAMN eller registrera().")
    kraver = getattr(modul, "KRAVER_API", None)
    if isinstance(kraver, bool) or not isinstance(kraver, int):
        raise _Avvisat("saknar KRAVER_API.")
    if kraver != API_VERSION:
        raise _Avvisat(f"är gjort för tilläggsgränssnitt {kraver}, men den här versionen av Akasha Protokoll "
                       f"har {API_VERSION}.")


def _ladda_ett(app_modul, id_, katalog):
    api = Api(app_modul, id_)
    try:
        if not ID_RE.fullmatch(id_):
            raise _Avvisat("mappnamnet får bara ha gemener a-z, siffror och _, och börja med en bokstav.")
        modul = _importera(id_, katalog)
        _kontrollera(modul)
        modul.registrera(api)
    except _Avvisat as e:
        orsak = str(e)
    except Exception:  # noqa: BLE001 - ett trasigt tillagg far aldrig ta ner programmet
        log.exception("tillagget %s (%s) kunde inte laddas", id_, katalog)
        orsak = "kunde inte startas. Se loggen."
    else:
        api._aktiv = True
        version = getattr(modul, "VERSION", None)
        _aktiva.append({"id": id_, "namn": modul.NAMN, "version": None if version is None else str(version),
                        "katalog": katalog})
        log.info("tillagg %s (%s) laddat fran %s", id_, modul.NAMN, katalog)
        return
    log.warning("tillagget %s ar inte aktivt: %s", id_, orsak)
    _problem.append(f"Tillägget {id_} är inte aktivt: {orsak}")
    for lista in _krokar.values():
        lista[:] = [(i, fn) for i, fn in lista if i != id_]
    sys.modules.pop(f"akasha_tillagg_{id_}", None)


def ladda(app_modul):
    """Laddar alla tillagg en gang (anropas igen gor ingenting) och ger de aktiva. app_modul ar app.py."""
    global _laddat
    if not _laddat:
        _laddat = True
        for id_, katalog in _hitta():
            _ladda_ett(app_modul, id_, katalog)
    return list(_aktiva)


def status():
    """Det webbsidan far se. Inga sokvagar."""
    return {
        "api": API_VERSION,
        "aktiva": [{k: a[k] for k in ("id", "namn", "version")} for a in _aktiva],
        "problem": list(_problem),
    }


def _nollstall():
    """Bara for testerna: tillbaka till att inget ar laddat."""
    global _laddat
    _laddat = False
    _aktiva.clear()
    _problem.clear()
    for lista in _krokar.values():
        lista.clear()
    for katalog in _tillagda_sokvagar:
        if katalog in sys.path:
            sys.path.remove(katalog)
    _tillagda_sokvagar.clear()
    for namn in [n for n in sys.modules if n.startswith("akasha_tillagg_")]:
        del sys.modules[namn]


# --- krokarna, anropade av programmet ------------------------------------------------------

def _kor(namn, *argument):
    """Anropar tilleggens funktioner for namn och ger deras svar. Ett undantag loggas och hoppas over."""
    for id_, fn in list(_krokar[namn]):
        try:
            yield id_, fn(*argument)
        except Exception:  # noqa: BLE001
            log.exception("tillagget %s: %s misslyckades", id_, namn)


def kor_vid_inspelning(meta):
    """-> {id: svar} for de tillagg som gav ett svar."""
    return {id_: svar for id_, svar in _kor("inspelning", meta) if svar is not None}


def kor_vid_radera(id_):
    for _ in _kor("radera", id_):
        pass


def kor_hindrar(meta):
    """-> texten fran det forsta tillagg som hindrar atgarden, annars None."""
    for _id, text in _kor("hindrar", meta):
        if text:
            return str(text)
    return None


def kor_vid_start():
    for _ in _kor("start"):
        pass


def kor_vid_stopp():
    for _ in _kor("stopp"):
        pass
