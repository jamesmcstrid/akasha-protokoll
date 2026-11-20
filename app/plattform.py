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

log = logging.getLogger("akasha-protokoll")

NAMN = "Akasha Protokoll"
GAMMAL_ETIKETT = "local.akasha-meet"  # launchd-tjansten fran mac/installera.sh
# Det gamla namnet (Akasha Meet) finns kvar bara har, for flytten till de nya mapparna.
GAMMALT_NAMN = "Akasha Meet"
GAMMAL_DATAKATALOG = "~/AkashaMeet"
NY_DATAKATALOG = "~/AkashaProtokoll"

FIL_GICK_INTE = "Filen gick inte att läsa ({orsak}). Inga inställningar ur den används."
FIL_KODNING = ("Filen är inte sparad som ren text i UTF-8. Inga inställningar ur den används. "
               "Spara den igen i TextEdit med Format → Gör till ren text, och välj Unicode (UTF-8).")
RAD_FEL = "Rad {nr} förstods inte och hoppades över. En rad ska se ut som NAMN=värde."

_NAMNMONSTER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def system():
    return platform.system()


def ar_paketerad():
    """Sant i programmet som PyInstaller har byggt (sys.frozen), falskt i en terminalinstallation."""
    return bool(getattr(sys, "frozen", False))


def _programkatalog(namn_mac, namn_linux):
    if system() == "Darwin":
        return os.path.expanduser("~/Library/Application Support/" + namn_mac)
    if system() == "Windows":
        bas = os.environ.get("LOCALAPPDATA") or os.path.expanduser(os.path.join("~", "AppData", "Local"))
        return os.path.join(bas, namn_mac)
    bas = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(os.path.join("~", ".local", "share"))
    return os.path.join(bas, namn_linux)


def ny_programkatalog():
    return _programkatalog("Akasha Protokoll", "akasha-protokoll")


def gammal_programkatalog():
    """Programkatalogen fran tiden da programmet hette Akasha Meet. Flyttas av flytta_till_nya_namn."""
    return _programkatalog(GAMMALT_NAMN, "akasha-meet")


def programkatalog():
    """Var programmet lagger sina egna filer (modeller, installningar). Skapar ingenting.
    Den nya katalogen om den finns eller om den gamla inte finns, annars den gamla: sa visas aldrig
    en tom lista eller en ny hamtning, ocksa nar flytten annu inte har gjorts."""
    ny = ny_programkatalog()
    if os.path.exists(ny):
        return ny
    gammal = gammal_programkatalog()
    return gammal if os.path.isdir(gammal) else ny


def standard_datakatalog():
    """Standardvardet for DATAKATALOG (med ~): samma upplosning som programkatalog()."""
    if os.path.exists(os.path.expanduser(NY_DATAKATALOG)):
        return NY_DATAKATALOG
    return GAMMAL_DATAKATALOG if os.path.isdir(os.path.expanduser(GAMMAL_DATAKATALOG)) else NY_DATAKATALOG


def flytta_till_nya_namn(datakatalog_satt=None):
    """Flyttar de gamla mapparna (Akasha Meet) till de nya namnen: programkatalogen och, om DATAKATALOG
    inte ar satt i miljon eller installningsfilen, inspelningsmappen. Gor bara os.rename, bara nar den
    gamla finns som katalog och den nya inte finns. Tar aldrig bort eller skriver over nagot. Ett fel loggas och
    lamnar den gamla pa plats (programkatalog() och standard_datakatalog() anvander den da).
    Returnerar en lista med (gammal, ny) for det som flyttades."""
    if datakatalog_satt is None:
        datakatalog_satt = bool(os.environ.get("DATAKATALOG", "").strip())
    par = [(gammal_programkatalog(), ny_programkatalog())]
    if not datakatalog_satt:
        par.append((os.path.expanduser(GAMMAL_DATAKATALOG), os.path.expanduser(NY_DATAKATALOG)))
    flyttat = []
    for gammal, ny in par:
        if not os.path.isdir(gammal):
            continue
        if os.path.lexists(ny):
            log.info("flytt: %s finns kvar och %s finns redan, ingen av dem rors", gammal, ny)
            continue
        try:
            os.rename(gammal, ny)
        except OSError as e:
            log.warning("flytt: kunde inte flytta %s till %s (%s), den gamla anvands tills vidare", gammal, ny, e)
            continue
        flyttat.append((gammal, ny))
    return flyttat


def loggkatalog():
    if system() == "Darwin":
        return os.path.expanduser("~/Library/Logs/Akasha Protokoll")
    return os.path.join(programkatalog(), "logg")


def installningsfil():
    return os.path.join(programkatalog(), "installningar.env")


def _avkoda(data):
    """UTF-16 med BOM (Anteckningar kan spara sa) eller UTF-8 med/utan BOM. Ingen gissning pa Latin-1."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def _varde(text):
    """Varde ur en rad: med citattecken (som bash, med kommentar efter) eller utan. None = raden forstods inte."""
    text = text.lstrip()
    if text[:1] in ("\"", "'"):
        slut = text.find(text[0], 1)
        if slut < 0:
            return None
        resten = text[slut + 1:].strip()
        if resten and not resten.startswith("#"):
            return None
        return text[1:slut]
    if text.startswith("#"):
        return ""
    return text.split(" #", 1)[0].rstrip()


def las_installningsfil(sokvag):
    """NAMN=varde-rader -> (dict, problem). Kastar aldrig pa grund av filen. Problemtexterna innehaller
    aldrig nagot ur filen (en rad kan ha en proxyadress med losenord), bara radnummer och orsak.
    Loggar inget: loggningen ar inte installd nar den har kors."""
    try:
        with open(sokvag, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError) as e:
        return {}, [FIL_GICK_INTE.format(orsak=getattr(e, "strerror", None) or type(e).__name__)]
    try:
        text = _avkoda(data)
    except UnicodeError:
        return {}, [FIL_KODNING]
    resultat = {}
    problem = []
    for nr, rad in enumerate(text.splitlines(), 1):
        rad = rad.strip()
        if not rad or rad.startswith("#"):
            continue
        if rad.startswith("export "):
            rad = rad[len("export "):].lstrip()
        namn, skiljetecken, varde = rad.partition("=")
        namn = namn.strip()
        if skiljetecken:
            varde = _varde(varde)
        if not skiljetecken or varde is None or not _NAMNMONSTER.match(namn):
            problem.append(RAD_FEL.format(nr=nr))
            continue
        resultat[namn] = varde
    return resultat, problem


def las_in_installningar():
    """Lagger installningar.env i miljon, men bara i programmet: terminalinstallationen har .env
    via mac/kor.sh. setdefault gor att en miljovariabel som redan finns vinner (som med .env).
    Returnerar problemlistan (tom utanfor programmet)."""
    if not ar_paketerad():
        return []
    installningar, problem = las_installningsfil(installningsfil())
    for namn, varde in installningar.items():
        os.environ.setdefault(namn, varde)
    return problem


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


# Mappar dar macOS inte later en bakgrundstjanst (launchd) lasa, och som ett program med fonster
# far en fraga om. Belagt hos Apple (Mac-anvandarhandboken, "Styra atkomsten till filer och mappar"):
# Skrivbord, Hamtade filer och Dokument. Antaget, inte last hos Apple: iCloud Drive, molnmappar
# via File Provider och natverks-/flyttbara volymer. De tas med eftersom en bakgrundstjanst
# inte heller ska kora fran en mapp som synkas eller kan kopplas bort.
SKYDDADE = (  # under hemkatalogen
    "Desktop", "Documents", "Downloads",
    os.path.join("Library", "Mobile Documents"),   # iCloud Drive (antaget)
    os.path.join("Library", "CloudStorage"),       # Dropbox, OneDrive, Google Drive m.fl. (antaget)
)
SKYDDADE_ABSOLUTA = ("/Volumes",)  # natverks- och flyttbara volymer (antaget)


def skyddad_plats(sokvag, hem=None):
    """Den skyddade rotmappen som sokvag ligger i eller ar, annars None.

    Bara stranglogik, ingen realpath och ingen stat: en stat i en skyddad mapp kan i sig fa
    macOS att fraga om lov. Jamforelsen ar per sokvagskomponent och skiftlagesokansligt
    (APFS ar det som standard)."""
    hem = hem or os.path.expanduser("~")
    kandidat = os.path.abspath(os.path.expanduser(sokvag)).casefold()
    roter = [os.path.join(hem, namn) for namn in SKYDDADE] + list(SKYDDADE_ABSOLUTA)
    for rot in roter:
        r = os.path.abspath(rot).casefold()
        if kandidat == r or kandidat.startswith(r + os.sep):
            return rot
    return None


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
    # Klonplatsen i README heter fortfarande akasha-meet; akasha-protokoll om repot en dag byter namn.
    kandidater.append(os.path.expanduser(os.path.join("~", "akasha-meet", "modeller")))
    kandidater.append(os.path.expanduser(os.path.join("~", "akasha-protokoll", "modeller")))
    hittade, sedda = [], set()
    for katalog in kandidater:
        rot = skyddad_plats(katalog)
        if rot:
            log.info("modeller: letar inte i %s (macOS skyddar %s)", katalog, rot)
            continue
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
