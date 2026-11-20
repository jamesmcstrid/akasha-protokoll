"""Gemensamt for kontrollskripten i paketering/ som kors i Windows-flodet: utskrift och resultatrader.

Varje kontroll skriver "OK: ..." eller "FEL: ..." (och "INFO: ..." for det som bara visas). Skripten stannar
inte vid forsta felet utan samlar dem och skriver en sammanfattning sist, sa att en korning visar sa
mycket som mojligt. Slutkoden ar 1 om nagot var FEL.
"""
import sys


def utf8_utskrift():
    """Actions-maskinens konsol ar inte UTF-8, och en omdirigerad utskrift kraschar annars med
    UnicodeEncodeError pa tecken som a med ring, a med prickar, o med prickar och pilar. errors=replace: ett tecken som saknas far aldrig stoppa skriptet."""
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


class Resultat:
    def __init__(self, rubrik):
        self.rubrik = rubrik
        self.ok_rader = []
        self.fel_rader = []

    def steg(self, text):
        print(f"\n== {text}", flush=True)

    def info(self, text):
        print(f"INFO: {text}", flush=True)

    def ok(self, text):
        self.ok_rader.append(text)
        print(f"OK: {text}", flush=True)

    def fel(self, text):
        self.fel_rader.append(text)
        print(f"FEL: {text}", flush=True)

    def kontrollera(self, villkor, text_ok, text_fel):
        if villkor:
            self.ok(text_ok)
        else:
            self.fel(text_fel)
        return bool(villkor)

    def sammanfatta(self):
        """Skriver sammanfattningen och ger slutkoden (0 eller 1)."""
        print(f"\n== Sammanfattning: {self.rubrik}", flush=True)
        print(f"{len(self.ok_rader)} kontroller OK, {len(self.fel_rader)} FEL", flush=True)
        for rad in self.fel_rader:
            print(f"FEL: {rad}", flush=True)
        if self.fel_rader:
            print(f"{self.rubrik}: FEL", flush=True)
            return 1
        print(f"{self.rubrik}: OK", flush=True)
        return 0
