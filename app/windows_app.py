"""Akasha Protokoll som Windows-program: ikon vid klockan, meny och Avsluta. Tjansten, sidan och allt
annat ar desamma som annars (start.py). Har finns bara det som ar Windows.

Alla texter till anvandaren ligger i start.py. Pa modulnivan importeras bara ctypes, logging,
threading, time, plattform och start: ingen av dem laser installningar nar den importeras, sa att
loggningen (start.stall_in_loggning) hinner stallas in fore allt som gor det. pystray och Pillow
importeras i main(), och inget Windows-anrop gors fore det behovs (ctypes.WinDLL skapas i fraga()).

Allt som pystray anropar har hela sin kropp i try/except med en loggrad: ett undantag far aldrig
stoppa avslutet. Raderna "win: ..." visar i loggen hur langt skalet kom.
"""
import ctypes
import logging
import threading
import time

import plattform
import start

log = logging.getLogger("akasha-protokoll")

MUTEX = "Local\\AkashaProtokoll"  # per inloggad anvandare
VANTA_ANDRA_KOPIAN = 30  # sekunder

# Typer av ruta for fraga()
OK = "ok"
JA_NEJ = "janej"
AVSLUTA = "avsluta"  # Ja/Nej med Nej som forval och varningsikon

MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONWARNING = 0x30
MB_DEFBUTTON2 = 0x100
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000
IDYES = 6
_FLAGGOR = {
    OK: MB_OK,
    JA_NEJ: MB_YESNO,
    AVSLUTA: MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2,
}


def _user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.MessageBoxW.restype = ctypes.c_int
    u.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    return u


def fraga(rubrik, text, typ):
    """Modal ruta (MessageBoxW). -> sant om anvandaren valde Ja (eller OK for typ OK). Knapparnas
    text kommer fran Windows och foljer Windows sprak."""
    svar = _user32().MessageBoxW(None, text, rubrik, _FLAGGOR[typ] | MB_SETFOREGROUND | MB_TOPMOST)
    return svar == IDYES if typ != OK else True


class Skal:
    def __init__(self):
        self.tjanst = None
        self.redo = False
        self.ikon = None
        self.klart = threading.Event()  # sats nar programmet ska avslutas
        self._bakgrund = False
        self._avslutet = False  # sant sa snart avslutet har borjat: da gor startresultaten ingenting
        self._las = threading.Lock()
        self._avslutar = threading.Lock()

    # --- start ---------------------------------------------------------------------------------

    def borja(self):
        """Besluten fore ikonen. -> sant om programmet ska fortsatta (ikon och tjanst)."""
        if not plattform.en_kopia(MUTEX):
            log.info("win: kopia finns redan")
            self.andra_kopian()
            return False
        problem = start.installningsproblem()
        if problem and fraga(start.INSTALLNINGSFEL_RUBRIK,
                             start.installningsfel_text(problem) + "\n\n" + start.WIN_VISA_FILEN_FRAGA, JA_NEJ):
            plattform.visa_fil(plattform.installningsfil())  # rutan avslutar aldrig programmet
        beslut = start.forbered()
        log.info("win: beslut %s", beslut)
        if beslut == "redan_igang":
            plattform.oppna_webblasare(start.url())
            return False
        if beslut == "upptagen":
            fraga(start.UPPTAGEN_RUBRIK,
                  start.UPPTAGEN_TEXT.format(port=start.aktuell_port(), fil=plattform.installningsfil()), OK)
            return False
        return True  # "starta" ("ta_over" kan inte handa pa Windows)

    def andra_kopian(self):
        """En annan kopia har mutexen: vanta pa att den svarar och oppna sidan, annars en ruta."""
        slut = time.monotonic() + VANTA_ANDRA_KOPIAN
        while True:
            if start.lage() == "akasha":
                plattform.oppna_webblasare(start.url())
                return
            if time.monotonic() >= slut:
                break
            time.sleep(0.5)
        log.info("win: den andra kopian svarade inte inom %d s", VANTA_ANDRA_KOPIAN)
        fraga(start.STARTAR_REDAN_RUBRIK, start.STARTAR_REDAN_TEXT, OK)

    def starta_i_bakgrunden(self):
        """Egen trad: ikonen ska synas medan tjansten startar."""
        try:
            tjanst = start.Tjanst()
            self.tjanst = tjanst
            if self._avslutet:
                return
            tjanst.starta()
            if self._avslutet:  # avslutet borjade medan tjansten startade: stang den vi just startade
                tjanst.stang()
                return
            ok = tjanst.vanta(30)
        except start.StartFel as e:
            self.startfel(str(e))
            return
        except Exception:
            log.exception("tjansten startade inte")
            ok = False
        self.startad(ok)

    def _starta_bakgrund_en_gang(self):
        with self._las:
            if self._bakgrund:
                return
            self._bakgrund = True
        threading.Thread(target=self.starta_i_bakgrunden, name="start", daemon=True).start()

    def _efter_avslut(self, vad):
        if self._avslutet:
            log.info("win: %s ignoreras, avslutet har borjat", vad)
        return self._avslutet

    def startad(self, ok):
        try:
            if self._efter_avslut("startad"):
                return
            if not ok:
                log.info("win: tjansten svarade inte inom 30 s")
                self.startade_inte()
                return
            self.redo = True
            log.info("win: tjansten svarar, oppnar webblasaren")
            self.satt_tips(start.WIN_TIPS_IGANG)
            plattform.oppna_webblasare(start.url())  # forst nu, nar tjansten svarar
            if plattform.forsta_start_visad() and self.ikon is not None:
                self.ikon.notify(start.WIN_IGANG, plattform.NAMN)
        except Exception:
            log.exception("win: startad")

    def satt_tips(self, text):
        try:
            if self.ikon is not None:
                self.ikon.title = text
        except Exception:
            log.exception("win: satt_tips")

    def startfel(self, text):
        if self._efter_avslut("startfel"):
            return
        try:
            fraga(start.UPPTAGEN_RUBRIK, text, OK)
        except Exception:
            log.exception("win: startfel")
        self.avsluta(utan_fraga=True)

    def startade_inte(self):
        """Rutan "startade inte" far aldrig sjalv stoppa avslutet: gar den fel loggas det och programmet avslutas."""
        if self._efter_avslut("startade_inte"):
            return
        try:
            if fraga(start.STARTADE_INTE_RUBRIK,
                     start.STARTADE_INTE_TEXT.format(logg=start.loggfil()) + "\n\n" + start.WIN_VISA_LOGGEN_FRAGA,
                     JA_NEJ):
                plattform.visa_fil(start.loggfil())
        except Exception:
            log.exception("win: startade_inte")
        self.avsluta(utan_fraga=True)

    # --- det pystray anropar -----------------------------------------------------------------

    def oppna(self):
        try:
            if self.redo:
                plattform.oppna_webblasare(start.url())
        except Exception:
            log.exception("win: oppna")

    def _meny_oppna(self, _ikon=None, _rad=None):
        try:
            self.oppna()
        except Exception:
            log.exception("win: _meny_oppna")

    def _meny_avsluta(self, _ikon=None, _rad=None):
        """Egen trad: huvudtraden (ikonens meddelandeloop) ska inte blockeras av fragan och nedstangningen."""
        try:
            threading.Thread(target=self.avsluta, name="avsluta", daemon=True).start()
        except Exception:
            log.exception("win: _meny_avsluta")
            self.klart.set()

    def _setup(self, ikon):
        """pystray anropar den i en egen trad nar ikonen ar redo."""
        try:
            ikon.visible = True
            log.info("win: ikonen visas")
        except Exception as e:
            log.warning("win: ikonen kunde inte visas: %s", e)
        self._starta_bakgrund_en_gang()

    # --- avsluta ---------------------------------------------------------------------------------

    def avsluta(self, utan_fraga=False):
        """Fragar om nagot pagar (om inte utan_fraga), stanger tjansten och ikonen. Gar alltid att anropa:
        ett fel i fragan eller nedstangningen loggas och programmet avslutas anda."""
        if not self._avslutar.acquire(blocking=False):
            return  # en avslutsfraga visas redan
        try:
            if not utan_fraga and self.redo:
                try:
                    vad = start.pagar()
                    if vad and not fraga(start.AVSLUTA_RUBRIK,
                                         start.avsluta_text(vad) + "\n\n" + start.WIN_AVSLUTA_FRAGA, AVSLUTA):
                        return  # Nej: programmet fortsatter
                except Exception:
                    log.exception("win: avslutsfragan")
            self._avslutet = True
            log.info("win: avslutar")
            self.stang()
        finally:
            self._avslutar.release()

    def stang(self):
        """Tjansten och ikonen, en gang var (andra anropet gor inget). Kastar aldrig. Ordningen: tjansten,
        ikonen, och sist klart, sa att main() inte hinner avsluta processen under nedstangningen."""
        self._avslutet = True
        tjanst, self.tjanst = self.tjanst, None
        ikon, self.ikon = self.ikon, None
        try:
            if tjanst is not None:
                tjanst.stang()
        except Exception:
            log.exception("win: tjanst.stang")
        try:
            if ikon is not None:
                ikon.stop()
        except Exception:
            log.exception("win: ikon.stop")
        self.klart.set()

    # --- ikonen ----------------------------------------------------------------------------------

    def bygg_meny(self, pystray):
        """Menyn vid klockan: Oppna (forval) och Avsluta."""
        return pystray.Menu(
            pystray.MenuItem(start.WIN_MENY_OPPNA, self._meny_oppna, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(start.WIN_MENY_AVSLUTA, self._meny_avsluta),
        )

    def visa_ikon(self, pystray, Image):
        """Kor ikonens meddelandeloop tills avslutet (blockerar). Gar ikonen inte att skapa loggas det och
        programmet fortsatter utan ikon: tjansten startas anda, och avslut gar da via Aktivitetshanteraren."""
        try:
            meny = self.bygg_meny(pystray)
            bild = Image.open(plattform.ikonfil())
            self.ikon = pystray.Icon(plattform.NAMN, bild, start.WIN_TIPS_STARTAR, meny)
            self.ikon.run(self._setup)
            return
        except Exception as e:
            log.warning("win: ikonen kunde inte visas: %s", e)
            self.ikon = None
        self._starta_bakgrund_en_gang()
        self.klart.wait()


def main():
    start.stall_in_loggning()
    log.info("win: startar")
    skal = Skal()
    try:
        if not skal.borja():
            return 0
        try:
            import pystray
            from PIL import Image
        except Exception as e:
            log.warning("win: ikonen kunde inte visas: %s", e)
            skal._starta_bakgrund_en_gang()
            skal.klart.wait()
        else:
            skal.visa_ikon(pystray, Image)
    except Exception:
        log.exception("win: main")
        skal.startade_inte()  # rutan far aldrig sjalv stoppa avslutet (startade_inte avslutar alltid)
    finally:
        skal.stang()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
