"""Akasha Meet som Mac-program: ikon i Dock, meny och Avsluta. Tjansten, sidan och allt annat
ar desamma som annars (start.py). Har finns bara det som ar Mac.

Alla texter till anvandaren ligger i start.py. Pa modulnivan importeras bara AppKit/Foundation/
PyObjCTools, plattform och start: ingen av dem laser installningar nar den importeras, sa att
loggningen (start.stall_in_loggning) hinner stallas in fore allt som gor det.
"""
import logging
import threading
import time

import objc
from AppKit import (NSAlert, NSAlertFirstButtonReturn, NSApp, NSApplication,
                    NSApplicationActivationPolicyRegular, NSMenu, NSMenuItem,
                    NSTerminateCancel, NSTerminateNow)
from Foundation import NSObject
from PyObjCTools import AppHelper

import plattform
import start

log = logging.getLogger("akasha-meet")

_delegat = None  # en referens, annars kan delegaten stadas bort


def fraga(rubrik, text, knappar):
    """Modal ruta. -> index for knappen som trycktes (0 = forsta, den som ar forval)."""
    ruta = NSAlert.alloc().init()
    ruta.setMessageText_(rubrik)
    ruta.setInformativeText_(text)
    for k in knappar:
        ruta.addButtonWithTitle_(k)
    NSApp.activateIgnoringOtherApps_(True)
    return ruta.runModal() - NSAlertFirstButtonReturn


class Delegat(NSObject):
    def init(self):
        self = super().init()
        if self is None:
            return None
        self.tjanst = None
        self.redo = False
        return self

    def applicationDidFinishLaunching_(self, _notis):
        try:
            self.borja()
        except Exception:
            log.exception("starten misslyckades")
            self.startade_inte()

    @objc.python_method
    def borja(self):
        problem = start.installningsproblem()
        if problem and fraga(start.INSTALLNINGSFEL_RUBRIK, start.installningsfel_text(problem),
                             [start.OK, start.VISA_FILEN]) == 1:
            plattform.visa_fil(plattform.installningsfil())  # rutan avslutar aldrig programmet
        beslut = start.forbered()
        if beslut == "ta_over":
            if fraga(start.TA_OVER_RUBRIK, start.TA_OVER_TEXT, [start.TA_OVER_JA, start.TA_OVER_NEJ]) != 0:
                return self.avsluta()
            if not plattform.stang_av_gammal_tjanst() or not self.vanta_pa_ledig_port():
                fraga(start.TA_OVER_MISSLYCKADES_RUBRIK, start.TA_OVER_MISSLYCKADES_TEXT, [start.OK])
                return self.avsluta()
            beslut = "starta"
        if beslut == "redan_igang":
            plattform.oppna_webblasare(start.url())
            return self.avsluta()
        if beslut == "upptagen":
            fraga(start.UPPTAGEN_RUBRIK,
                  start.UPPTAGEN_TEXT.format(port=start.aktuell_port(), fil=plattform.installningsfil()),
                  [start.OK])
            return self.avsluta()
        threading.Thread(target=self.starta_i_bakgrunden, name="start", daemon=True).start()

    @objc.python_method
    def vanta_pa_ledig_port(self, sekunder=15):
        slut = time.monotonic() + sekunder
        while True:
            if start.lage() == "ledig":
                return True
            if time.monotonic() >= slut:
                return False
            time.sleep(0.25)

    @objc.python_method
    def starta_i_bakgrunden(self):
        """Egen trad: huvudtraden ska hinna rita Dock-ikonen. Resultatet lamnas till huvudtraden."""
        try:
            self.tjanst = start.Tjanst()
            self.tjanst.starta()
            ok = self.tjanst.vanta(30)
        except start.StartFel as e:
            AppHelper.callAfter(self.startfel, str(e))
            return
        except Exception:
            log.exception("tjansten startade inte")
            ok = False
        AppHelper.callAfter(self.startad, ok)

    @objc.python_method
    def startad(self, ok):
        if ok:
            self.redo = True
            plattform.oppna_webblasare(start.url())  # forst nu, nar tjansten svarar
        else:
            self.startade_inte()

    @objc.python_method
    def startfel(self, text):
        fraga(start.UPPTAGEN_RUBRIK, text, [start.OK])
        self.avsluta()

    @objc.python_method
    def startade_inte(self):
        if fraga(start.STARTADE_INTE_RUBRIK, start.STARTADE_INTE_TEXT.format(logg=start.loggfil()),
                 [start.VISA_LOGGEN, start.OK]) == 0:
            plattform.visa_fil(start.loggfil())
        self.avsluta()

    def oppna_(self, _avsandare):
        if self.redo:
            plattform.oppna_webblasare(start.url())

    def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _synliga):
        self.oppna_(None)
        return False

    def applicationDockMenu_(self, _app):
        meny = NSMenu.alloc().init()
        rad = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Öppna i webbläsaren", "oppna:", "")
        rad.setTarget_(self)
        meny.addItem_(rad)
        return meny

    def applicationShouldTerminate_(self, _app):
        if not self.redo:
            return NSTerminateNow
        vad = start.pagar()
        if not vad:
            return NSTerminateNow
        svar = fraga(start.AVSLUTA_RUBRIK, start.avsluta_text(vad), [start.AVSLUTA_NEJ, start.AVSLUTA_JA])
        return NSTerminateNow if svar == 1 else NSTerminateCancel

    def applicationWillTerminate_(self, _notis):
        if self.tjanst is not None:
            self.tjanst.stang()

    @objc.python_method
    def avsluta(self):
        NSApp.terminate_(None)


def bygg_meny(delegat):
    """Programmenyn i B3. macOS visar programmets namn som rubrik."""
    huvud = NSMenu.alloc().init()
    holder = NSMenuItem.alloc().init()
    huvud.addItem_(holder)
    meny = NSMenu.alloc().init()

    def rad(titel, atgard, tangent, mal=None):
        r = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(titel, atgard, tangent)
        if mal is not None:
            r.setTarget_(mal)
        meny.addItem_(r)

    rad("Om Akasha Meet", "orderFrontStandardAboutPanel:", "")
    meny.addItem_(NSMenuItem.separatorItem())
    rad("Öppna Akasha Meet i webbläsaren", "oppna:", "o", delegat)
    meny.addItem_(NSMenuItem.separatorItem())
    rad("Göm Akasha Meet", "hide:", "h")
    meny.addItem_(NSMenuItem.separatorItem())
    rad("Avsluta Akasha Meet", "terminate:", "q")
    holder.setSubmenu_(meny)
    NSApp.setMainMenu_(huvud)


def main():
    global _delegat
    start.stall_in_loggning()
    app = NSApplication.sharedApplication()
    _delegat = Delegat.alloc().init()
    app.setDelegate_(_delegat)
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    bygg_meny(_delegat)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
