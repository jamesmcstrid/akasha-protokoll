"""Modellerna: vilka filer som behovs, och hamtningen fran Hugging Face.

Alla uppgifter om modellerna (repo, revision, filnamn, katalog, storlek, sha256) finns bara har.
Hamtningen gors med requests: den kan fortsatta en avbruten fil (Range), foljer omdirigeringar
for hand (bara till Hugging Face) och kontrollerar sha256 innan filen far sitt riktiga namn.

Skriptlaget (python app/modeller.py [faster] [ggml] [talare]) anvands av mac/hamta-modeller.sh och
mac/installera.sh. Modulen importerar bara standardbiblioteket, requests och installningar (och truststore om det
finns), sa att den gar att kora i en venv med enbart requests.
"""
import errno
import hashlib
import logging
import os
import shutil
import ssl
import sys
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests

from installningar import MODELL, MODELLKATALOG

log = logging.getLogger("akasha-protokoll")


@dataclass(frozen=True)
class Fil:
    repo: str
    revision: str
    namn: str      # filnamnet i repot och pa disken
    katalog: str   # mapp under MODELLKATALOG
    storlek: int
    sha256: str

    @property
    def url(self):
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.namn}"

    def sokvag(self):
        return os.path.join(MODELLKATALOG, self.katalog, self.namn)  # MODELLKATALOG lases vid anropet


_MEDIUM = ("KBLab/kb-whisper-medium", "0abe10b9d7f75d0902656e5c06c5c4d549604dc5")
_LARGE = ("KBLab/kb-whisper-large", "d5d5984b4d8f7c4847a8ea203f1976285fb28300")
_TALARE = ("csukuangfj/speaker-embedding-models", "0743f301363dec56491a490f6d6cbc9d67f9a3bf")

PAKET = {
    ("faster", "medium"): (
        Fil(*_MEDIUM, "model.bin", "kb-whisper-medium", 1527906492,
            "4a4a32952026bcfa0bcfaa76b0b006f232ffba6a8f5bccbcb12e4a1153a40494"),
        Fil(*_MEDIUM, "config.json", "kb-whisper-medium", 3592,
            "11dcf5ae76605d0870db8e1cbb5edcb2d150d61adec08160800bdd17240572c4"),
        Fil(*_MEDIUM, "preprocessor_config.json", "kb-whisper-medium", 339,
            "a6a76d28c93edb273669eb9e0b0636a2bddbb1272c3261e47b7ca6dfdbac1b8d"),
        Fil(*_MEDIUM, "tokenizer.json", "kb-whisper-medium", 3931232,
            "b2eda7f36f7ca45f3be94a568f1623453b4246083013dfe5db3fe43b9b35dd1b"),
        Fil(*_MEDIUM, "vocabulary.json", "kb-whisper-medium", 1068103,
            "5ad28279db5e546349708b9a74736e2c018737ac5a600f1048f1f26c99b85b47"),
    ),
    ("whispercpp", "medium"): (
        Fil(*_MEDIUM, "ggml-model.bin", "kb-whisper-medium-ggml", 1533763076,
            "1b7842bc1c3f79fb3bf043a0a3590961d625a49ef3ccbdceb00e738c5dd8b015"),
    ),
    ("faster", "large"): (
        Fil(*_LARGE, "model.bin", "kb-whisper-large", 3087284276,
            "69ed56887f68417f651d50fd5f225c60dfc0f9515bef85bb0f1404825c6f01de"),
        Fil(*_LARGE, "config.json", "kb-whisper-large", 3717,
            "48be972f94e790720e32b8711ad54860b1d06d5434079d3fcdfdfe1254d29c69"),
        Fil(*_LARGE, "preprocessor_config.json", "kb-whisper-large", 340,
            "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711"),
        Fil(*_LARGE, "tokenizer.json", "kb-whisper-large", 3931383,
            "d06d0c877b5143ccdcb761407d5650b18a6afc33f9261fcb7e0dd44acbc1c262"),
        Fil(*_LARGE, "vocabulary.json", "kb-whisper-large", 1068114,
            "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1"),
    ),
    # kvantiserad (q5_0), som KBLab rekommenderar for whisper.cpp
    ("whispercpp", "large"): (
        Fil(*_LARGE, "ggml-model-q5_0.bin", "kb-whisper-large-ggml", 1081140203,
            "6d2863812d7410322bb7d8647a5c7260761300fa946714c9ed66d22bb30bcb19"),
    ),
    "talare": (
        Fil(*_TALARE, "nemo_en_titanet_small.onnx", "talare", 40257283,
            "ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e"),
    ),
}

STORLEKAR = ("medium", "large")
# KB-Whisper large bygger pa whisper-large-v3, darav DTW-forinstallningen i whisper.cpp.
DTW_PER_STORLEK = {"medium": "medium", "large": "large.v3"}
INFO = {"taligenkanning": ("KB-Whisper {storlek}", "taligenkänning på svenska från Kungliga biblioteket (KBLab)", "Apache-2.0"),
        "talare": ("TitaNet small", "röstmodell som delar upp texten per talare (NVIDIA)", "CC-BY-4.0")}
TILLATNA_VARDAR = ("huggingface.co",)   # plus allt som slutar pa ".huggingface.co" eller ".hf.co"
FORSOK = 3            # forsok utan framsteg per fil vid avbrott, tidsgrans och natfel
FRAMSTEG_MIN = 1 << 20  # byte som ett forsok maste ha lagt till i .delvis for att inte raknas
MAX_FORSOK = 20       # ovre grans per fil, sa att det aldrig snurrar for evigt
PAUSER = (2, 5)       # sekunder mellan forsoken; testerna satter (0, 0)
MARGINAL = 100_000_000  # byte som ska finnas kvar pa disken efter hamtningen

# Sokvagarna som motor och talare anvander. Okand MODELL faller tillbaka pa medium (motor.problem()
# sager ifran).
_storlek = MODELL if MODELL in STORLEKAR else "medium"
CT2_MODELL = os.path.join(MODELLKATALOG, PAKET[("faster", _storlek)][0].katalog)
GGML_MODELL = PAKET[("whispercpp", _storlek)][0].sokvag()
DTW = DTW_PER_STORLEK[_storlek]
ROSTMODELL = PAKET["talare"][0].sokvag()

_FEL = {
    "inget_nat": "Kunde inte nå Hugging Face. Kontrollera att datorn är ansluten till internet och tryck Försök igen.",
    "certifikat": "Anslutningen till Hugging Face gick inte att kontrollera (certifikatfel). På ett företagsnät kan det "
                  "behövas en inställning för proxy eller certifikat. Se Felsökning i README.",
    "avbrott": "Hämtningen avbröts. Det som redan hämtats ligger kvar, så Försök igen fortsätter där det slutade.",
    "server": "Hugging Face svarade med ett fel (kod {status}). Försök igen om en stund.",
    "adress": "Hugging Face skickade vidare till en adress som inte är tillåten ({varde}). Inget sparades. "
              "Försök igen om en stund.",
    "kontrollsumma": "{fil} blev inte som den ska (kontrollsumman stämmer inte) och har tagits bort. Tryck Försök igen. "
                     "Händer det igen kan filen ha ändrats hos Hugging Face.",
    "disk_full_fore": "Det får inte plats på disken. Hämtningen behöver {behov} ledigt, men det finns {ledigt}. "
                      "Frigör utrymme och tryck Försök igen.",
    "disk_full": "Disken blev full under hämtningen. Det som redan hämtats ligger kvar. "
                 "Frigör utrymme och tryck Försök igen.",
    "skrivfel": "Kunde inte spara i {katalog}: {strerror}.",
    "avbruten": "Hämtningen stoppades.",
    "ovantat": "Oväntat fel vid hämtningen: {e}",
}


class HamtFel(Exception):
    """Ett fel som kan visas for anvandaren. kod namnar vad som hant; texten kommer fran _FEL."""

    def __init__(self, kod, **uppgifter):
        self.kod = kod
        self.uppgifter = uppgifter
        mall = _FEL["disk_full_fore"] if kod == "disk_full" and "behov" in uppgifter else _FEL[kod]
        super().__init__(mall.format(**uppgifter))


def paket(nyckel, storlek=None):
    if nyckel == "talare":
        return PAKET["talare"]
    return PAKET[(nyckel, storlek or MODELL)]


def komplett(fil):
    sokvag = fil.sokvag()
    return os.path.isfile(sokvag) and os.path.getsize(sokvag) == fil.storlek


def saknade(nyckel, storlek=None):
    return [f for f in paket(nyckel, storlek) if not komplett(f)]


def delvis(fil):
    try:
        return os.path.getsize(fil.sokvag() + ".delvis")
    except OSError:
        return 0


def ledigt(katalog=None):
    """Lediga byte pa disken, raknat pa narmaste katalog uppat som finns."""
    mapp = os.path.abspath(katalog or MODELLKATALOG)
    while not os.path.isdir(mapp):
        over = os.path.dirname(mapp)
        if over == mapp:
            break
        mapp = over
    return shutil.disk_usage(mapp).free


def storlek_text(byte):
    mb = round(byte / 1e6)  # avrunda forst, sa att 999,6 MB blir "1,0 GB" och aldrig "1000 MB"
    if mb < 1000:
        return f"{mb} MB"
    return f"{byte / 1e9:.1f}".replace(".", ",") + " GB"


def _truststore_kontext():
    import truststore

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class _Systemcertifikat(requests.adapters.HTTPAdapter):
    """Litar pa operativsystemets certifikat (nyckelringen pa Mac), via truststore. Da fungerar
    ett foretagsnat med egen rot-CA utan installningar."""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = _truststore_kontext()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **kwargs):
        kwargs["ssl_context"] = _truststore_kontext()
        return super().proxy_manager_for(proxy, **kwargs)


def ny_session():
    session = requests.Session()
    # requests laser REQUESTS_CA_BUNDLE och CURL_CA_BUNDLE men inte SSL_CERT_FILE.
    cert = os.environ.get("SSL_CERT_FILE")
    if (cert and os.path.exists(cert) and not os.environ.get("REQUESTS_CA_BUNDLE")
            and not os.environ.get("CURL_CA_BUNDLE")):
        session.verify = cert
    if not (os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE")
            or os.environ.get("SSL_CERT_FILE")):
        try:
            import truststore  # noqa: F401
        except ImportError:
            return session  # som tidigare: certifikaten som requests har med sig
        session.mount("https://", _Systemcertifikat())
    return session


def ta_in_gamla(kataloger):
    """Lankar in modeller som redan finns i gamla modellkataloger (terminalinstallationens
    modeller/) i den nuvarande. Hard lank: inget extra utrymme, och terminalinstallationen fungerar
    som forut. Ingen kopiering och ingen sha256: filerna kontrollerades nar de hamtades med samma
    manifest, och "finns" betyder rimlig storlek (se komplett). -> lista med sokvagar som lankades."""
    lankade, sedda = [], set()
    for filer in PAKET.values():
        for fil in filer:
            mal = fil.sokvag()
            if mal in sedda:
                continue
            sedda.add(mal)
            if komplett(fil):
                continue
            for katalog in kataloger:
                kandidat = os.path.join(katalog, fil.katalog, fil.namn)
                if not (os.path.isfile(kandidat) and os.path.getsize(kandidat) == fil.storlek):
                    continue
                if os.path.exists(mal) and os.path.samefile(kandidat, mal):
                    continue
                try:
                    os.makedirs(os.path.dirname(mal), exist_ok=True)
                    if os.path.lexists(mal):
                        os.remove(mal)  # en ofullstandig fil med fel storlek ligger i vagen
                    os.link(kandidat, mal)
                except OSError as e:
                    log.info("modeller: tog inte in %s fran %s, hard lank gick inte: %s", fil.namn, katalog, e)
                    continue
                lankade.append(mal)
                log.info("modeller: tog in %s fran %s (hard lank)", fil.namn, katalog)
                break
    return lankade


def tillaten(url):
    delar = urlparse(url)
    vard = (delar.hostname or "").lower()
    return delar.scheme == "https" and (
        vard in TILLATNA_VARDAR or vard.endswith(".huggingface.co") or vard.endswith(".hf.co"))


def _oppna(sokvag, lage):
    return open(sokvag, lage)  # egen funktion bara sa att testerna kan ersatta den


def _begar(fil, session, start):
    """Begar filen och foljer omdirigeringar for hand, sa att ingen okand adress nagonsin kontaktas."""
    rubriker = {"Accept-Encoding": "identity"}
    if start > 0:
        rubriker["Range"] = f"bytes={start}-"
    url = fil.url
    svar = None
    for _ in range(6):  # startadressen och hogst 5 omdirigeringar
        svar = session.get(url, stream=True, timeout=(15, 60), allow_redirects=False, headers=rubriker)
        if svar.status_code not in (301, 302, 303, 307, 308):
            return svar
        plats = svar.headers.get("Location")
        status = svar.status_code
        svar.close()
        if not plats:
            raise HamtFel("server", status=status)
        url = urljoin(url, plats)
        if not tillaten(url):
            raise HamtFel("adress", varde=urlparse(url).hostname or url)
    raise HamtFel("server", status=svar.status_code)


def _ta_bort(sokvag):
    try:
        os.remove(sokvag)
    except OSError:
        pass


def _hamta(fil, session, framsteg, avbryt, lasta):
    """Sjalva hamtningen av en fil. lasta[0] raknar byte som last i det har forsoket."""
    sok = fil.sokvag()
    delv = sok + ".delvis"
    os.makedirs(os.path.dirname(sok), exist_ok=True)
    start = delvis(fil)
    if start > fil.storlek:
        os.remove(delv)
        start = 0
    if start < fil.storlek:
        svar = _begar(fil, session, start)
        try:
            kod = svar.status_code
            if kod == 206 and svar.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
                lage = "ab"
            elif kod == 200:
                lage, start = "wb", 0
            elif kod == 416:
                _ta_bort(delv)
                raise HamtFel("avbrott")
            else:
                raise HamtFel("server", status=kod)
            i_filen = start
            with _oppna(delv, lage) as f:
                for bit in svar.iter_content(1 << 20):
                    if not bit:
                        continue
                    lasta[0] += len(bit)
                    i_filen += len(bit)
                    if i_filen > fil.storlek:
                        f.close()
                        _ta_bort(delv)
                        raise HamtFel("server", status=kod)
                    f.write(bit)
                    if framsteg:
                        framsteg("hamtar", i_filen)
                    if avbryt is not None and avbryt.is_set():
                        raise HamtFel("avbruten")
                f.flush()
                os.fsync(f.fileno())
        finally:
            svar.close()
        if delvis(fil) < fil.storlek:
            raise HamtFel("avbrott")  # filen ligger kvar, nasta forsok fortsatter
    if framsteg:
        framsteg("kontrollerar", fil.storlek)
    summa = hashlib.sha256()
    with open(delv, "rb") as f:
        while True:
            bit = f.read(1 << 20)
            if not bit:
                break
            summa.update(bit)
    if summa.hexdigest() != fil.sha256:
        _ta_bort(delv)
        raise HamtFel("kontrollsumma", fil=fil.namn)
    os.replace(delv, sok)  # atomiskt: en halv fil far aldrig malets namn


def hamta_fil(fil, session, framsteg=None, avbryt=None):
    """Hamtar en fil. Ger "finns" eller "hamtad". framsteg(fas, byte_i_filen)."""
    if komplett(fil):
        return "finns"
    lasta = [0]
    try:
        _hamta(fil, session, framsteg, avbryt, lasta)
    except HamtFel:
        raise
    except requests.exceptions.SSLError:
        raise HamtFel("certifikat")
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout,
            requests.exceptions.ChunkedEncodingError):
        raise HamtFel("avbrott")
    except requests.exceptions.ConnectionError:
        raise HamtFel("inget_nat" if lasta[0] == 0 else "avbrott")
    except requests.exceptions.RequestException as e:
        raise HamtFel("ovantat", e=e)
    except OSError as e:
        if e.errno == errno.ENOSPC:
            raise HamtFel("disk_full")
        raise HamtFel("skrivfel", katalog=os.path.dirname(fil.sokvag()), strerror=e.strerror or str(e))
    return "hamtad"


def hamta(filer, framsteg=None, avbryt=None, session=None):
    """Hamtar (namn, Fil)-par. framsteg(namn, fas, hamtat, totalt) galler hela jobbet."""
    kvar = [(namn, fil) for namn, fil in filer if not komplett(fil)]
    behov = sum(max(0, fil.storlek - delvis(fil)) for _, fil in kvar)
    if kvar:
        fritt = ledigt()
        if fritt < behov + MARGINAL:
            raise HamtFel("disk_full", behov=storlek_text(behov + MARGINAL), ledigt=storlek_text(fritt))
    session = session or ny_session()
    totalt = sum(fil.storlek for _, fil in kvar)
    klart = 0     # byte i filer som redan ar klara
    hogsta = [0]  # framsteget far aldrig ga bakat (t.ex. nar en server skriver om filen fran borjan)
    for namn, fil in kvar:
        def rapportera(fas, i_filen, namn=namn, klart=klart):
            if framsteg:
                hogsta[0] = max(hogsta[0], klart + i_filen)
                framsteg(namn, fas, hogsta[0], totalt)
        # Ett forsok som har hamtat minst FRAMSTEG_MIN raknas inte mot FORSOK: ett skakigt nat ska inte
        # ge "Forsok igen" nar hamtningen anda gar framat. MAX_FORSOK ar den ovre gransen.
        utan_framsteg = forsok = 0
        while True:
            fore = delvis(fil)
            try:
                hamta_fil(fil, session, rapportera, avbryt)
                break
            except HamtFel as e:
                if e.kod == "kontrollsumma":
                    raise HamtFel("kontrollsumma", fil=namn) from e  # paketets namn, inte filnamnet
                if e.kod not in ("avbrott", "inget_nat"):
                    raise
                forsok += 1
                if delvis(fil) - fore >= FRAMSTEG_MIN:
                    utan_framsteg = 0
                    paus = PAUSER[0]
                else:
                    utan_framsteg += 1
                    paus = PAUSER[min(utan_framsteg - 1, len(PAUSER) - 1)]
                if utan_framsteg == FORSOK or forsok == MAX_FORSOK:
                    raise
                if avbryt is not None:
                    if avbryt.wait(paus):
                        raise HamtFel("avbruten")
                else:
                    time.sleep(paus)
        klart += fil.storlek
    return None


class Hamtning:
    """Hamtningen i en bakgrundstrad, en at gangen, for webbtjansten. Sidan fragar efter status().

    Tillstand: vilar, hamtar, kontrollerar, klar, fel, avbruten. avbryt() sater en handelse som
    hamta_fil ser efter nasta bit. Under kontrollen (sha256) ser hamta_fil inte handelsen, sa kontrollen
    blir klar och en godkand fil far sitt riktiga namn. Var det den sista filen lyckas hamtningen, och
    tillstandet blir klar och inte avbruten. Annars stannar den vid forsta biten av nasta fil.
    All andring av tillstandet sker under _lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._trad = None
        self._avbryt = threading.Event()
        self._nollstall()

    def _nollstall(self):
        self._tillstand = "vilar"
        self._fil = None
        self._hamtat = 0
        self._totalt = 0
        self._hamtat0 = 0      # byte som redan lag kvar nar jobbet startade
        self._start = None
        self._slut = None
        self._fel = None
        self._felkod = None
        self._stoppas = False
        self._pagar = False

    def starta(self, filer, efter=None):
        """filer: (namn, Fil)-par. True om en ny trad startades, False om en redan pagar."""
        with self._lock:
            if self._pagar:
                return False
            kvar = [fil for _, fil in filer if not komplett(fil)]
            self._nollstall()
            self._pagar = True
            self._tillstand = "hamtar"
            self._totalt = sum(fil.storlek for fil in kvar)
            self._hamtat = self._hamtat0 = sum(delvis(fil) for fil in kvar)
            self._start = time.monotonic()
            # En ny handelse varje gang, sa att ett gammalt avbrott inte stoppar nasta hamtning.
            self._avbryt = avbryt = threading.Event()
            self._trad = threading.Thread(target=self._kor, args=(filer, efter, avbryt),
                                          name="modellhamtning", daemon=True)
            self._trad.start()
            return True

    def avbryt(self):
        """True om en hamtning pagick och har fatt beskedet att stanna. Vantar inte."""
        with self._lock:
            if not self._pagar:
                return False
            self._avbryt.set()
            self._stoppas = True
            return True

    def _framsteg(self, namn, fas, hamtat, totalt):
        with self._lock:
            self._tillstand = "hamtar" if fas == "hamtar" else "kontrollerar"
            self._fil = namn
            self._hamtat = hamtat
            self._totalt = totalt

    def _kor(self, filer, efter, avbryt):
        tillstand, fel, felkod = "klar", None, None
        try:
            hamta(filer, framsteg=self._framsteg, avbryt=avbryt)
            if efter:
                efter()
        except HamtFel as e:
            if e.kod == "avbruten":
                tillstand = "avbruten"
                log.info("modellhamtningen stoppades")
            else:
                tillstand, fel, felkod = "fel", str(e), e.kod
                log.warning("modellhamtningen misslyckades: %s", e)
        except Exception as e:  # noqa: BLE001 - traden far aldrig do tyst
            tillstand, fel, felkod = "fel", _FEL["ovantat"].format(e=e), "ovantat"
            log.exception("ovantat fel vid modellhamtningen")
        finally:
            with self._lock:
                self._tillstand, self._fel, self._felkod = tillstand, fel, felkod
                self._fil = None
                self._slut = time.monotonic()
                self._stoppas = False
                self._pagar = False

    def status(self):
        """Kopia av tillstandet (allt under ett las, sa att faltens ar konsekventa)."""
        with self._lock:
            sekunder = kvar_s = None
            if self._start is not None:
                sekunder = int((self._slut or time.monotonic()) - self._start)
                lagt = self._hamtat - self._hamtat0  # byte hamtade i det har forsoket
                if self._pagar and sekunder >= 10 and lagt > 0:
                    kvar_s = max(0, int((self._totalt - self._hamtat) / (lagt / sekunder)))
            return {"tillstand": self._tillstand, "fil": self._fil, "hamtat": self._hamtat,
                    "totalt": self._totalt, "sekunder": sekunder, "kvar_s": kvar_s,
                    "fel": self._fel, "felkod": self._felkod, "stoppas": self._stoppas}

    def vanta(self, timeout=None):
        """Vantar pa traden (for testerna)."""
        trad = self._trad
        if trad is not None:
            trad.join(timeout)


HAMTNING = Hamtning()


_LAGEN = {"faster": "faster", "ggml": "whispercpp", "talare": "talare"}


def main(argv):
    lagen = list(argv) or ["faster", "talare"]
    for lage in lagen:
        if lage not in _LAGEN:
            print(f"okänt läge: {lage} (faster, ggml eller talare)", file=sys.stderr)
            return 2
    if MODELL not in STORLEKAR:
        print(f"FEL: MODELL={MODELL}, ska vara medium eller large", file=sys.stderr)
        return 2
    print(f"Modellkatalog: {MODELLKATALOG}", flush=True)
    rubriker = {
        "faster": f"== KB-Whisper {MODELL} för faster-whisper (KBLab, Apache-2.0)",
        "ggml": f"== KB-Whisper {MODELL} för whisper.cpp (KBLab, Apache-2.0)",
        "talare": "== Talaruppdelning: röstmodellen NeMo TitaNet small (NVIDIA, CC-BY-4.0, 40 MB)",
    }
    try:
        for lage in lagen:
            print(rubriker[lage], flush=True)
            for fil in paket(_LAGEN[lage]):
                if komplett(fil):
                    print(f"finns: {fil.namn}", flush=True)
                    continue
                print(f"hämtar {fil.namn} ({storlek_text(fil.storlek)})", flush=True)
                senast = [0]

                def skriv(namn, fas, hamtat, totalt, fil=fil, senast=senast):
                    if fil.storlek <= 10_000_000 or fas != "hamtar" or not totalt:
                        return
                    tiondel = hamtat * 10 // totalt
                    while senast[0] < tiondel:
                        senast[0] += 1
                        print(f"  {senast[0] * 10} %", flush=True)

                hamta([(fil.namn, fil)], framsteg=skriv)
                print(f"OK: {fil.namn}", flush=True)
    except KeyboardInterrupt:
        print(f"\nAvbrutet. Det som redan hämtats ligger kvar i {MODELLKATALOG}, och nästa körning "
              "fortsätter där det slutade.", file=sys.stderr)
        return 130  # konventionen for Ctrl-C, sa att set -e i installera.sh stannar
    except HamtFel as e:
        print(f"FEL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
