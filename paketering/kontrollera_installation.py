"""Provar installationsfilen pa riktigt (bara Windows): tyst installation till en katalog med a-ring, a-prickar och o-prickar
och mellanslag i namnet, genvag och avinstallationspost, om installationsfilen ser programmets mutex, kontrollera.py mot det
installerade programmet, tyst avinstallation, och att programmets filer ar borta medan en framand fil i katalogen och
anvandarens data ligger kvar. Kors bara i GitHub Actions (GITHUB_ACTIONS=true): skriptet installerar och avinstallerar for den
inloggade anvandaren med samma AppId som en riktig installation, och skriver i de riktiga mapparna AkashaProtokoll (i hemkatalogen)
och Akasha Protokoll under %LOCALAPPDATA%.

    python paketering/kontrollera_installation.py --installation dist/Akasha-Protokoll-installation.exe
           --katalog "RUNNER_TEMP/Installerat Åäö/Akasha Protokoll" --hem "RUNNER_TEMP/Hem för installationen Åäö"
           --version 0.2.0.1 [--port 8611] [--logg-katalog build/loggar]

Varje kontroll skriver OK: eller FEL: och skriptet fortsatter sa langt det gar. Sist en sammanfattning; slutkod 1 om nagot var
FEL. En Actions-maskin far genvagar och en avinstallationspost for runneradmin: det ar i sin ordning dar.
"""
import argparse
import os
import subprocess
import sys
import time

import kontroll_hjalp

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPID = "{9E5B73C9-B94B-4979-B5DF-00C834E09C1E}"
NAMN = "Akasha Protokoll"
EXE = "Akasha Protokoll.exe"
TYSTA = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]


def kommandorad(program, flaggor, **namngivna):
    """Kommandoraden som en sträng (Windows skickar den ordagrant): Inno Setup vill ha /DIR="sokvag med mellanslag"."""
    delar = [f'"{program}"'] + list(flaggor) + [f'/{k}="{v}"' for k, v in namngivna.items()]
    return " ".join(delar)


def ar_actions(miljo):
    return miljo.get("GITHUB_ACTIONS", "").lower() == "true"


def startmeny():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", NAMN + ".lnk")


def avinstallationspost():
    """-> {namn: varde} ur HKCU\\...\\Uninstall\\<AppId>_is1, eller None."""
    import winreg

    nyckel = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APPID}_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, nyckel) as k:
            ut = {}
            i = 0
            while True:
                try:
                    namn, varde, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                ut[namn] = varde
                i += 1
            return ut
    except OSError:
        return None


def visa_slut(sokvag, rader=60):
    if os.path.isfile(sokvag):
        with open(sokvag, encoding="utf-8", errors="replace") as f:
            text = f.read().splitlines()
        print(f"--- {sokvag}: sista {min(rader, len(text))} av {len(text)} raderna ---")
        print("\n".join(text[-rader:]))
    else:
        print(f"(ingen loggfil: {sokvag})")


def antal_filer(katalog):
    n = total = 0
    for mapp, _k, filer in os.walk(katalog):
        for f in filer:
            n += 1
            total += os.path.getsize(os.path.join(mapp, f))
    return n, total


def kor(kommando, tidsgrans):
    """-> (slutkod eller None vid tidsgrans)."""
    try:
        return subprocess.run(kommando, timeout=tidsgrans).returncode
    except subprocess.TimeoutExpired:
        return None


def vanta_tills_borta(sokvag, sekunder=90):
    slut = time.monotonic() + sekunder
    while os.path.exists(sokvag) and time.monotonic() < slut:
        time.sleep(1)
    return not os.path.exists(sokvag)


def mutexprov(res, args, installation, katalog):
    """Startar det installerade programmet och kor installationsfilen tyst igen: den ska se mutexen Local\\AkashaProtokoll."""
    import urllib.request

    hem = os.path.join(args.hem, "mutexprov")
    lokal = os.path.join(hem, "AppData", "Local")
    temp = os.path.join(lokal, "Temp")
    os.makedirs(temp, exist_ok=True)
    miljo = dict(os.environ, USERPROFILE=hem, LOCALAPPDATA=lokal, APPDATA=os.path.join(hem, "AppData", "Roaming"),
                 TEMP=temp, TMP=temp, PORT=str(args.port + 1))
    app = subprocess.Popen([os.path.join(katalog, EXE)], env=miljo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        slut = time.monotonic() + 90
        uppe = False
        while time.monotonic() < slut and app.poll() is None:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{args.port + 1}/health", timeout=3).read()
                uppe = True
                break
            except OSError:
                time.sleep(1)
        if not uppe:
            res.fel(f"det installerade programmet svarade inte (port {args.port + 1}), mutexprovet kunde inte goras")
            return
        res.ok("det installerade programmet kor (mutexen Local\\AkashaProtokoll ska finnas)")
        logg = os.path.join(args.logg_katalog, "installation-mutexprov.log")
        kod = kor(kommandorad(installation, TYSTA + ["/CURRENTUSER"], DIR=katalog, LOG=logg), 120)
        visa_slut(logg, 25)
        if kod is None:
            res.fel("installationsfilen hangde i 120 s med programmet igang (en ruta som vantar?): den ser antagligen mutexen men "
                    "svarar inte tyst")
        elif kod == 0:
            res.fel("installationsfilen gick igenom (kod 0) med programmet igang: AppMutex=Local\\AkashaProtokoll ser inte "
                    "programmets mutex")
        else:
            res.ok(f"installationsfilen avbrot (kod {kod}) nar programmet kor: den ser mutexen Local\\AkashaProtokoll")
        res.kontrollera(app.poll() is None, "programmet kor fortfarande efter installationsfilens forsok (den stangde det inte)",
                        f"programmet avslutades (kod {app.poll()}) under installationsfilens forsok")
    finally:
        if app.poll() is None:
            app.terminate()
            try:
                app.wait(10)
            except subprocess.TimeoutExpired:
                app.kill()


def main(argv=None):
    kontroll_hjalp.utf8_utskrift()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--installation", required=True)
    ap.add_argument("--katalog", required=True, help="dit den tysta installationen lagger programmet")
    ap.add_argument("--hem", required=True, help="hemkatalog for kontrollera.py (egen, inte zip-kontrollens)")
    ap.add_argument("--version", required=True)
    ap.add_argument("--port", type=int, default=8611)
    ap.add_argument("--logg-katalog", default="build/loggar")
    args = ap.parse_args(argv)
    res = kontroll_hjalp.Resultat("KONTROLL AV INSTALLATIONSFILEN")
    if not ar_actions(os.environ):
        res.fel("kontrollen kor bara i GitHub Actions (GITHUB_ACTIONS=true) och stannar har: den installerar och avinstallerar "
                "for den inloggade anvandaren, med samma AppId som en riktig installation (en riktig installation skulle "
                "avinstalleras), och skriver i de riktiga mapparna AkashaProtokoll och %LOCALAPPDATA%\\Akasha Protokoll. "
                "Det finns ingen flagga for att tvinga den.")
        return res.sammanfatta()
    if os.name != "nt":
        res.fel("kontrollen kan bara goras pa Windows")
        return res.sammanfatta()
    installation = os.path.abspath(args.installation)
    katalog = os.path.abspath(args.katalog)
    args.hem = os.path.abspath(args.hem)
    args.logg_katalog = os.path.abspath(args.logg_katalog)
    os.makedirs(args.logg_katalog, exist_ok=True)
    os.makedirs(args.hem, exist_ok=True)
    if not os.path.isfile(installation):
        res.fel(f"{installation} finns inte (se bygget av installationsfilen)")
        return res.sammanfatta()
    print(f"Installationsfil: {installation} ({os.path.getsize(installation)} byte)\nInstallationskatalog: {katalog}\nHem: {args.hem}")

    # Anvandarens data i den riktiga profilen: avinstallationen far aldrig rora den. Markorer laggs dar fore och kontrolleras efter.
    data = os.path.join(os.path.expanduser("~"), "AkashaProtokoll")
    modeller = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Akasha Protokoll", "modeller")
    fanns_fore = {d: os.path.isdir(d) for d in (data, modeller)}
    markorer = {d: os.path.join(d, "installationsprov.txt") for d in (data, modeller)}

    res.steg("1. tyst installation")
    ilogg = os.path.join(args.logg_katalog, "installation.log")
    kod = kor(kommandorad(installation, TYSTA + ["/CURRENTUSER"], DIR=katalog, LOG=ilogg), 600)
    visa_slut(ilogg, 40)
    res.kontrollera(kod == 0, "den tysta installationen avslutades med kod 0", f"den tysta installationen gav {kod!r}")
    exe = os.path.join(katalog, EXE)
    for rel in (EXE, os.path.join("_internal", "whisper", "whisper-cli.exe"), os.path.join("_internal", "static", "app.js"),
                "unins000.exe"):
        res.kontrollera(os.path.isfile(os.path.join(katalog, rel)), f"{rel} finns i installationskatalogen",
                        f"{rel} saknas i {katalog}")
    n, total = antal_filer(katalog)
    print(f"INFO: {n} filer, {total / 1e6:.1f} MB i installationskatalogen (zip-filen har 288 filer; hit kommer unins000.exe och .dat)")
    res.kontrollera(os.path.isfile(startmeny()), f"genvagen i Start-menyn finns: {startmeny()}", f"genvagen saknas: {startmeny()}")
    post = avinstallationspost()
    if post is None:
        res.fel(f"avinstallationsposten HKCU\\...\\Uninstall\\{APPID}_is1 saknas")
    else:
        print("INFO: avinstallationsposten: " + "; ".join(f"{k}={post.get(k)}" for k in
              ("DisplayName", "DisplayVersion", "Publisher", "InstallLocation", "UninstallString"))
              + " (Publisher kan vara tom: ingen utgivare ar satt)")
        res.kontrollera(post.get("DisplayVersion") == args.version and post.get("DisplayName") == NAMN,
                        f"avinstallationsposten har namnet {NAMN} och versionen {args.version}",
                        f"avinstallationsposten har namn {post.get('DisplayName')!r} och version {post.get('DisplayVersion')!r}")
    skrivbord = os.path.join(os.path.expanduser("~"), "Desktop", NAMN + ".lnk")
    print(f"INFO: skrivbordsgenvag {'finns' if os.path.exists(skrivbord) else 'finns inte'} (ska inte finnas: valet ar av som standard)")

    res.steg("2. ser installationsfilen programmets mutex (Local\\AkashaProtokoll)?")
    if os.path.isfile(exe):
        try:
            mutexprov(res, args, installation, katalog)
        except Exception as e:
            res.fel(f"mutexprovet kastade {type(e).__name__}: {e}")

    res.steg("3. kontrollera.py mot det installerade programmet (egen hemkatalog)")
    if os.path.isfile(exe):
        kommando = [sys.executable, os.path.join(ROT, "paketering", "kontrollera.py"), "--program", exe,
                    "--hem", os.path.join(args.hem, "kontrollera"), "--port", str(args.port), "--vantad-motor", "whispercpp",
                    "--vantat-jobbfel", "whisper-cli", "--riktig-rostmodell", "--fortsatt-efter-fel"]
        kod = kor(kommando, 900)
        res.kontrollera(kod == 0, "kontrollera.py godtar det installerade programmet",
                        f"kontrollera.py gav {kod!r} for det installerade programmet (se utskriften ovan)")
    else:
        res.fel("det installerade programmet saknas: kontrollera.py kordes inte")

    res.steg("4. tyst avinstallation: bara programmets filer och genvagarna, aldrig andras filer eller anvandarens data")
    framand = os.path.join(katalog, "inte-var-fil.txt")  # en fil som inte ar var egen: den ska klara avinstallationen
    if os.path.isdir(katalog):
        with open(framand, "w", encoding="utf-8") as f:
            f.write("en annan fil i installationskatalogen\n")
    for d, m in markorer.items():
        os.makedirs(d, exist_ok=True)
        with open(m, "w", encoding="utf-8") as f:
            f.write("ska finnas kvar efter avinstallationen\n")
    ulogg = os.path.join(args.logg_katalog, "avinstallation.log")
    avinstallerare = os.path.join(katalog, "unins000.exe")
    if os.path.isfile(avinstallerare):
        kod = kor(kommandorad(avinstallerare, TYSTA, LOG=ulogg), 300)
        print(f"INFO: avinstallationen gav kod {kod!r}")
        borta = vanta_tills_borta(exe) and vanta_tills_borta(os.path.join(katalog, "_internal"))
        visa_slut(ulogg, 40)
        res.kontrollera(borta, f"{EXE} och _internal ar borta efter avinstallationen",
                        f"{EXE} eller _internal finns kvar i {katalog}")
        print("Kvar i katalogen:", sorted(os.listdir(katalog)) if os.path.isdir(katalog) else "(katalogen ar borta)")
    else:
        res.fel(f"{avinstallerare} saknas: avinstallationen kordes inte")
    res.kontrollera(not os.path.exists(startmeny()), "genvagen i Start-menyn ar borta", f"genvagen finns kvar: {startmeny()}")
    res.kontrollera(avinstallationspost() is None, "avinstallationsposten ar borta", "avinstallationsposten finns kvar")
    res.kontrollera(os.path.isfile(framand), "den framande filen inte-var-fil.txt ligger kvar (avinstallationen tog inte bort andras filer)",
                    f"avinstallationen tog bort {framand}, en fil som inte ar vår")
    for d, m in markorer.items():
        res.kontrollera(os.path.isfile(m), f"{d} ligger kvar (markoren finns)", f"avinstallationen tog bort {m}")
    # Stada: den framande filen och installationskatalogen (om den ar tom), markorerna, och katalogerna om det var vi som skapade dem
    try:
        os.remove(framand)
        os.rmdir(katalog)
    except OSError:
        pass
    for d, m in markorer.items():
        try:
            os.remove(m)
            if not fanns_fore[d] and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass
    return res.sammanfatta()


if __name__ == "__main__":
    sys.exit(main())
