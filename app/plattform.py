"""Det som skiljer mellan operativsystemen, samlat pa ett stalle.

Far bara importera standardbiblioteket: installningar.py importerar den.
"""
import contextlib
import logging
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
import webbrowser

log = logging.getLogger("akasha-meet")

NAMN = "Akasha Meet"
GAMMAL_ETIKETT = "local.akasha-meet"  # launchd-tjansten fran mac/installera.sh

_NAMNMONSTER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def system():
    return platform.system()


def ar_paketerad():
    """Sant i programmet som PyInstaller har byggt (sys.frozen), falskt i en terminalinstallation."""
    return bool(getattr(sys, "frozen", False))


def programkatalog():
    """Var programmet lagger sina egna filer (modeller, installningar). Skapar ingenting."""
    if system() == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Akasha Meet")
    if system() == "Windows":
        bas = os.environ.get("LOCALAPPDATA") or os.path.expanduser(os.path.join("~", "AppData", "Local"))
        return os.path.join(bas, "Akasha Meet")
    bas = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(os.path.join("~", ".local", "share"))
    return os.path.join(bas, "akasha-meet")


def loggkatalog():
    if system() == "Darwin":
        return os.path.expanduser("~/Library/Logs/Akasha Meet")
    return os.path.join(programkatalog(), "logg")


def installningsfil():
    return os.path.join(programkatalog(), "installningar.env")


def las_installningsfil(sokvag):
    """NAMN=varde-rader -> dict. Saknad fil ger {}."""
    try:
        with open(sokvag, encoding="utf-8-sig") as f:
            rader = f.read().splitlines()
    except FileNotFoundError:
        return {}
    resultat = {}
    for rad in rader:
        rad = rad.strip()
        if not rad or rad.startswith("#"):
            continue
        if rad.startswith("export "):
            rad = rad[len("export "):].lstrip()
        namn, skiljetecken, varde = rad.partition("=")
        namn = namn.strip()
        if not skiljetecken or not _NAMNMONSTER.match(namn):
            log.warning("hoppar over raden %r i %s", rad, sokvag)
            continue
        varde = varde.strip()
        if len(varde) >= 2 and varde[0] == varde[-1] and varde[0] in "\"'":
            varde = varde[1:-1]
        else:
            if varde.startswith("#"):
                varde = ""
            else:
                varde = varde.split(" #", 1)[0].rstrip()
        resultat[namn] = varde
    return resultat


def las_in_installningar():
    """Lagger installningar.env i miljon, men bara i programmet: terminalinstallationen har .env
    via mac/kor.sh. setdefault gor att en miljovariabel som redan finns vinner (som med .env)."""
    if not ar_paketerad():
        return {}
    installningar = las_installningsfil(installningsfil())
    for namn, varde in installningar.items():
        os.environ.setdefault(namn, varde)
    return installningar


def whisper_cli():
    from installningar import WHISPERCPP_BIN

    if ar_paketerad() and WHISPERCPP_BIN == "whisper-cli":
        # Bara den medfoljande, provade versionen: ingen gissning pa vad som ligger i PATH.
        kandidat = os.path.join(sys._MEIPASS, "whisper-cli")
        if os.path.isfile(kandidat) and os.access(kandidat, os.X_OK):
            return kandidat
        return None
    return shutil.which(WHISPERCPP_BIN)


def oppna_webblasare(url):
    try:
        if system() == "Darwin":
            subprocess.Popen(["/usr/bin/open", url])
        else:
            webbrowser.open(url)
    except OSError as e:
        log.warning("kunde inte oppna webblasaren: %s", e)
        return False
    return True


def visa_fil(sokvag):
    try:
        if system() == "Darwin":
            subprocess.Popen(["/usr/bin/open", "-R", sokvag])
        elif system() == "Windows":
            subprocess.Popen(["explorer", "/select,", sokvag])
        else:
            webbrowser.open("file://" + os.path.dirname(sokvag))
    except OSError as e:
        log.warning("kunde inte visa %s: %s", sokvag, e)


@contextlib.contextmanager
def hall_vaken():
    """Pa Mac: lat inte datorn somna av sig sjalv medan ett jobb pagar (caffeinate -i).
    Ett stangt lock sover anda, och da pausas jobbet tills locket oppnas.
    -w gor att caffeinate slutar nar var process gor det, ocksa om programmet avslutas mitt i ett jobb."""
    process = None
    if system() == "Darwin" and shutil.which("caffeinate"):
        try:
            process = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        except OSError as e:
            log.warning("kunde inte starta caffeinate: %s", e)
    try:
        yield
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def gamla_modellkataloger():
    """Modellkataloger fran terminalinstallationen som finns kvar, utan dubbletter."""
    kandidater = []
    plist = os.path.expanduser("~/Library/LaunchAgents/local.akasha-meet.plist")
    if os.path.isfile(plist):
        try:
            with open(plist, "rb") as f:
                kor = plistlib.load(f)["ProgramArguments"][-1]
            if kor.endswith(os.path.join("mac", "kor.sh")):
                repo = os.path.dirname(os.path.dirname(kor))
                kandidater.append(os.path.join(repo, "modeller"))
        except (OSError, plistlib.InvalidFileException, KeyError, IndexError, TypeError):
            pass
    kandidater.append(os.path.expanduser(os.path.join("~", "akasha-meet", "modeller")))
    hittade, sedda = [], set()
    for katalog in kandidater:
        if not os.path.isdir(katalog):
            continue
        verklig = os.path.realpath(katalog)
        if verklig in sedda:
            continue
        sedda.add(verklig)
        hittade.append(katalog)
    return hittade


def _gui_tjanst():
    return f"gui/{os.getuid()}/{GAMMAL_ETIKETT}"


def gammal_tjanst_finns():
    if system() != "Darwin":
        return False
    try:
        return subprocess.run(["launchctl", "print", _gui_tjanst()], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def stang_av_gammal_tjanst():
    """disable gor att den gamla inte startar vid nasta inloggning (installera.sh kor launchctl
    enable och tar tillbaka den); bootout stoppar den nu."""
    if system() != "Darwin":
        return False
    for kommando in ("disable", "bootout"):
        try:
            svar = subprocess.run(["launchctl", kommando, _gui_tjanst()], capture_output=True, timeout=15)
            if svar.returncode != 0:
                log.warning("launchctl %s gav %s: %s", kommando, svar.returncode, svar.stderr)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("launchctl %s misslyckades: %s", kommando, e)
    slut = time.monotonic() + 15
    while gammal_tjanst_finns() and time.monotonic() < slut:
        time.sleep(0.5)
    return not gammal_tjanst_finns()
