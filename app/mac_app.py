"""Akasha Protokoll som Mac-program: ikon i Dock, meny och Avsluta. Tjansten, sidan och allt annat
ar desamma som annars (start.py). Har finns bara det som ar Mac.

Ett Python-undantag som lamnar en metod som Cocoa anropar blir ett Objective-C-undantag och kan
avsluta programmet utan rad i loggen. Darfor har varje sadan metod hela sin kropp i try/except
med en loggrad och ett sakert svar. Raderna "mac: ..." visar i loggen hur langt skalet kom.

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

log = logging.getLogger("akasha-protokoll")

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
        self = objc.super(Delegat, self).init()
        if self is None:
            return None
        self.tjanst = None
        self.redo = False
        return self

    def applicationDidFinishLaunching_(self, _notis):
        try:
            self.borja()
        except Exception:
            log.exception("mac: applicationDidFinishLaunching_")
            self.startade_inte_sakert()

    @objc.python_method
    def borja(self):
        problem = start.installningsproblem()
        if problem and fraga(start.INSTALLNINGSFEL_RUBRIK, start.installningsfel_text(problem),
                             [start.OK, start.VISA_FILEN]) == 1:
            plattform.visa_fil(plattform.installningsfil())  # rutan avslutar aldrig programmet
        beslut = start.forbered()
        log.info("mac: beslut %s", beslut)
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
        try:
            if ok:
                self.redo = True
                log.info("mac: tjansten svarar, oppnar webblasaren")
                plattform.oppna_webblasare(start.url())  # forst nu, nar tjansten svarar
            else:
                log.info("mac: tjansten svarade inte inom 30 s")
                self.startade_inte()
        except Exception:
            log.exception("mac: startad")
            self.startade_inte_sakert()

    @objc.python_method
    def startfel(self, text):
        try:
            fraga(start.UPPTAGEN_RUBRIK, text, [start.OK])
            self.avsluta()
        except Exception:
            log.exception("mac: startfel")
            self.avsluta()

    @objc.python_method
    def startade_inte(self):
        if fraga(start.STARTADE_INTE_RUBRIK, start.STARTADE_INTE_TEXT.format(logg=start.loggfil()),
                 [start.VISA_LOGGEN, start.OK]) == 0:
            plattform.visa_fil(start.loggfil())
        self.avsluta()

    @objc.python_method
    def startade_inte_sakert(self):
        """Rutan "startade inte" far aldrig sjalv stoppa avslutet: gar den fel loggas det och programmet avslutas."""
        try:
            self.startade_inte()
        except Exception:
            log.exception("mac: startade_inte")
            self.avsluta()

    def oppna_(self, _avsandare):
        try:
            if self.redo:
                plattform.oppna_webblasare(start.url())
        except Exception:
            log.exception("mac: oppna_")

    def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _synliga):
        try:
            self.oppna_(None)
            return False
        except Exception:
            log.exception("mac: applicationShouldHandleReopen_hasVisibleWindows_")
            return False

    def applicationDockMenu_(self, _app):
        try:
            meny = NSMenu.alloc().init()
            rad = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Öppna i webbläsaren", "oppna:", "")
            rad.setTarget_(self)
            meny.addItem_(rad)
            return meny
        except Exception:
            log.exception("mac: applicationDockMenu_")
            return None  # Dock visar da bara sina egna rader

    def applicationShouldTerminate_(self, _app):
        try:
            if not self.redo:
                return NSTerminateNow
            vad = start.pagar()
            if not vad:
                return NSTerminateNow
            svar = fraga(start.AVSLUTA_RUBRIK, start.avsluta_text(vad), [start.AVSLUTA_NEJ, start.AVSLUTA_JA])
            return NSTerminateNow if svar == 1 else NSTerminateCancel
        except Exception:
            log.exception("mac: applicationShouldTerminate_")
            return NSTerminateNow  # programmet ska alltid ga att avsluta

    def applicationWillTerminate_(self, _notis):
        try:
            log.info("mac: applicationWillTerminate")
            if self.tjanst is not None:
                self.tjanst.stang()
        except Exception:
            log.exception("mac: applicationWillTerminate_")

    @objc.python_method
    def avsluta(self):
        log.info("mac: avslutar")
        try:
            NSApp.terminate_(None)
        except Exception:
            log.exception("mac: avsluta")


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

    rad("Om Akasha Protokoll", "orderFrontStandardAboutPanel:", "")
    meny.addItem_(NSMenuItem.separatorItem())
    rad("Öppna Akasha Protokoll i webbläsaren", "oppna:", "o", delegat)
    meny.addItem_(NSMenuItem.separatorItem())
    rad("Göm Akasha Protokoll", "hide:", "h")
    meny.addItem_(NSMenuItem.separatorItem())
    rad("Avsluta Akasha Protokoll", "terminate:", "q")
    holder.setSubmenu_(meny)
    NSApp.setMainMenu_(huvud)


def main():
    global _delegat
    start.stall_in_loggning()
    log.info("mac: startar")
    app = NSApplication.sharedApplication()
    _delegat = Delegat.alloc().init()
    app.setDelegate_(_delegat)
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    bygg_meny(_delegat)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
