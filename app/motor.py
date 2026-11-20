"""Taligenkanning med KB-Whisper (KBLab, Kungliga biblioteket), medium eller large (MODELL).
Tva motorer, valj med MOTOR (standard auto: whisper.cpp pa Mac med Apple Silicon och pa Windows
om whisper-cli och modellen finns, annars faster-whisper):

  faster      faster-whisper (CTranslate2) i den har processen, pa CPU. Fungerar overallt.
              Modellen laddas vid forsta transkriberingen och ligger sedan kvar i minnet.
  whispercpp  whisper.cpp:s whisper-cli (brew install whisper-cpp pa Mac), som anvander Metal (GPU) pa
              Apple Silicon. Startas en gang per transkribering och laddar modellen varje gang.

Ingen sprakmodell rattar eller sammanfattar texten. Det som whisper hor ar det som skrivs.
"""
import collections
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np

import ljud
import modeller
import plattform
from installningar import CPU_TRADAR, MODELL, MOTOR, SPRAK, WHISPERCPP_BIN
from modeller import CT2_MODELL, DTW, GGML_MODELL, STORLEKAR

# faster-whisper ska aldrig hamta nagot sjalv: modellerna hamtas bara av modeller.py
os.environ.setdefault("HF_HUB_OFFLINE", "1")

log = logging.getLogger("akasha-protokoll")
SR = 16000
BEAM = 5
PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")
# Raderna ur whisper-clis stderr som loggas (INFO, prefixet "whisper-cli: "), hogst MAX_LOGGRADER per korning:
# vilken processorvariant ggml laddade, systeminformationen (AVX, AVX2 ...), GPU, modelltyp och tiderna
# i slutet. Inget annat ur stderr loggas.
LOGGA_RADER = re.compile(
    r"(?:load_backend:|system_info:|whisper_backend_init_gpu:|whisper_model_load:\s+(?:type|ftype)\b"
    r"|whisper_print_timings:)")
MAX_LOGGRADER = 30
# Raderna som far ligga i "sista" (de 15 sista raderna, som hamnar i felmeddelandet och darmed i loggen):
# bara whisper.cpps och ggml:s egna diagnosrader (funktionsnamn med understrykning, main:, error: ...).
# Texten skrivs pa stdout (aldrig last), men en rad som ser ut som text eller som innehaller prompten
# (de svarstavade orden) tas aldrig med.
SAKER_RAD = re.compile(
    r"(?:[a-z][a-z0-9]*_[a-z0-9_]*|main|error|warning|usage|WARNING|ERROR):|\s*$")
# Interna markeringar som whisper.cpp ibland skriver i texten, t.ex. <|nospeech|> och [BLANK_AUDIO].
INTERNA_RE = re.compile(r"<\|[^|>]*\|>|\[[A-Z_]+\]")

_las = threading.Lock()  # en transkribering at gangen: modellen tar 1-2 GB minne
_faster_modell = None


def valj_motor(onskad=MOTOR, system=None, har_cli=None, har_ggml=None):
    """auto -> whispercpp pa Mac och Windows om whisper-cli och GGML-modellen finns, annars faster.

    mac/installera.sh installerar whisper-cpp och GGML-modellen bara pa Apple Silicon, dar Metal
    gjorde transkriberingen ungefar tre ganger snabbare an CPU (MacBook Air). Valet gors pa vad som
    ar installerat och inte pa processortyp: en Python som kor via Rosetta ser x86_64 fast datorn
    har Apple Silicon. faster och whispercpp valjs som de ar.
    """
    if onskad != "auto":
        return onskad
    system = system or plattform.system()
    har_cli = plattform.whisper_cli() is not None if har_cli is None else har_cli
    if har_ggml is None:
        try:
            har_ggml = not modeller.saknade("whispercpp", MODELL)
        except KeyError:  # okand MODELL: hinder() sager ifran
            har_ggml = False
    if system in ("Darwin", "Windows") and har_cli and har_ggml:
        return "whispercpp"
    return "faster"


def mal_motor(onskad=MOTOR, system=None, har_cli=None):
    """Vilken motor modellerna ska hamtas for. Pa en Mac eller Windows med whisper-cli blir det
    whisper.cpp aven nar GGML-filen saknas (valj_motor() ger da faster tills den har hamtats)."""
    if onskad != "auto":
        return onskad
    system = system or plattform.system()
    har_cli = plattform.whisper_cli() is not None if har_cli is None else har_cli
    return "whispercpp" if system in ("Darwin", "Windows") and har_cli else "faster"


def motor_text():
    """Motorn som den ska stå i startraden i loggen. Saknas modellen for malmotorn star det: valj_motor()
    ger da faster tills modellen har hamtats, fast malet (och det som hamtas) ar en annan motor."""
    mal = mal_motor()
    try:
        saknas = bool(modeller.saknade(mal, MODELL))
    except KeyError:  # okand MODELL: hinder() sager ifran
        saknas = False
    return f"motor {mal}, modellen saknas" if saknas else f"motor {AKTIV}"


AKTIV = valj_motor()  # bestams nar tjansten startar, och raknas om av uppdatera()


class MotorFel(Exception):
    """Motorn saknas, kraschar eller svarar fel."""


class Avbruten(MotorFel):
    """Transkriberingen stoppades for att programmet avslutas."""


def _cli_saknas():
    if plattform.ar_paketerad():
        return "whisper-cli saknas i programmet. Ladda ned Akasha Protokoll på nytt."
    if plattform.system() == "Windows":
        return (f"{WHISPERCPP_BIN} saknas. Lägg whisper-cli.exe i en mapp som finns i PATH, "
                "eller ange MOTOR=faster i installningar.env.")
    return f"{WHISPERCPP_BIN} saknas. Kör: brew install whisper-cpp"


def hinder():
    """Det en hamtning inte kan ratta: None, eller vad som ar fel med installningarna."""
    if MODELL not in STORLEKAR:
        return f"okand MODELL={MODELL!r}, anvand medium eller large"
    if MOTOR not in ("auto", "faster", "whispercpp"):
        return f"okand MOTOR={MOTOR!r}, anvand auto, faster eller whispercpp"
    if (plattform.ar_paketerad() and MOTOR == "faster"
            and importlib.util.find_spec("faster_whisper") is None):
        return ("MOTOR=faster går inte i programmet, eftersom faster-whisper inte följer med. "
                "Ta bort raden MOTOR i installningar.env.")
    if mal_motor(MOTOR) == "whispercpp" and plattform.whisper_cli() is None:  # MOTOR lases nu, inte vid def
        return _cli_saknas()
    return None


def problem():
    """None om motorn ar redo, annars vad som saknas."""
    fel = hinder()
    if fel:
        return fel
    if AKTIV == "whispercpp" and plattform.whisper_cli() is None:
        return _cli_saknas()
    if modeller.saknade(AKTIV, MODELL):
        return "KB-Whisper (GGML) saknas. Hämta den på sidan." if AKTIV == "whispercpp" \
            else "KB-Whisper saknas. Hämta den på sidan."
    return None


def uppdatera():
    """Raknar om AKTIV, sa att tjansten blir redo utan omstart nar modellerna har hamtats (aven med
    skriptet i en terminal). Tar transkriberingslaset utan att vanta: ar det upptaget, med en
    transkribering som anvander motorn, gors ingenting och nasta anrop forsoker igen."""
    global AKTIV, _faster_modell
    ny = valj_motor()
    if ny != AKTIV and _las.acquire(blocking=False):
        try:
            AKTIV = ny
            _faster_modell = None
            log.info("motor: %s", ny)
        finally:
            _las.release()
    return AKTIV


def ord_grans():
    """Under den har sannolikheten markeras ett ord som osakert. Kalibrerat pa 40 meningar ur
    FLEURS med facit: whisper.cpp:s ord under 0,5 var fel fyra ganger sa ofta som andra (20 % mot
    4-5 %). faster-whispers sannolikheter skiljer samre; under 0,4 var en tredjedel fel."""
    return 0.5 if AKTIV == "whispercpp" else 0.4


def modellnamn():
    if AKTIV != "whispercpp":
        return f"KB-Whisper {MODELL}"
    return f"KB-Whisper {MODELL} (whisper.cpp, Metal)" if plattform.system() == "Darwin" \
        else f"KB-Whisper {MODELL} (whisper.cpp)"


def avkoda(sokvag):
    """Valfritt ljudformat -> float32, 16 kHz mono. PyAV, via ljud.py."""
    return ljud.avkoda(sokvag, SR)


def avkoda_kanaler(sokvag):
    """-> (vanster, hoger), float32, 16 kHz. En monofil ger tva lika kanaler."""
    return ljud.avkoda(sokvag, SR, stereo=True)


def transkribera(samples, per_ord=False, prompt="", framsteg=None):
    """-> (text, segment, ord). Kastar Avbruten om programmet har borjat avslutas.

    segment: [{"start", "end", "text"}] i sekunder.
    ord: [(start, slut, text)] om per_ord (behovs for talaridentifiering), annars [].
    framsteg: anropas med en andel 0..1 medan arbetet pagar.
    """
    if _avslutas:
        raise Avbruten("stoppad")
    fel = problem()
    if fel:
        raise MotorFel(fel)
    with _las:
        if _avslutas:  # kan ha satts medan jobbet vantade pa laset
            raise Avbruten("stoppad")
        if AKTIV == "faster":
            return _faster(samples, per_ord, prompt, framsteg)
        return _whispercpp(samples, per_ord, prompt, framsteg)


def _faster(samples, per_ord, prompt, framsteg):
    global _faster_modell
    if _faster_modell is None:
        from faster_whisper import WhisperModel

        # Mac: CPU och int8 (faster-whisper har ingen Metal-backend).
        _faster_modell = WhisperModel(
            CT2_MODELL, device="cpu", compute_type="int8", cpu_threads=CPU_TRADAR
        )
    langd = len(samples) / SR
    segments, _info = _faster_modell.transcribe(
        samples,
        language=SPRAK,
        beam_size=BEAM,
        initial_prompt=prompt or None,
        word_timestamps=per_ord,
        # Hoppar over tystnad. Minskar risken att whisper hittar pa text i langa pauser.
        vad_filter=True,
    )
    segs, ord_lista = [], []
    for s in segments:  # generator: arbetet sker medan vi itererar
        if s.text.strip():
            segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        ord_lista.extend((w.start, w.end, w.word, w.probability) for w in (s.words or []))
        if framsteg and langd:
            framsteg(min(1.0, s.end / langd))
    text = " ".join(s["text"] for s in segs)
    return text, segs, ord_lista


def wav_16k_mono(samples):
    """float32 [-1, 1] -> WAV med 16 bit PCM, som whisper-cli laser utan ffmpeg."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


# Pagaende whisper-cli. start.Tjanst.stang() anropar stoppa() nar programmet avslutas, annars
# fortsatter whisper-cli efter att programmet har stangts.
_process = None
# Sant sa snart programmet avslutas. Lamnas satt: inga nya whisper-cli ska startas efter det.
_avslutas = False


def stoppa():
    global _avslutas
    _avslutas = True  # fore terminate(), sa att _whispercpp() ser att det ar ett avslut
    p = _process
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


# Katalogerna som whisper-cli arbetar i heter sa har och ligger direkt under MODELLKATALOG, inte i
# systemets temp-mapp: sokvagen dit har anvandarnamnet i sig, och whisper-cli pa Windows tolkar
# argumenten i systemets teckentabell medan modellen laddas som UTF-8. Darfor kors whisper-cli
# med MODELLKATALOG som arbetskatalog och med sokvagar som bara har ASCII och ar relativa.
TMP_PREFIX = "tmp-akasha-protokoll-"


def cli_kommando(cli, katalog_rel, per_ord, prompt, tradar, system):
    """Kommandot for whisper-cli -> (argv, svarsfil_text eller None).

    katalog_rel: den tillfalliga katalogen (namnet under MODELLKATALOG). Alla sokvagar i argumenten
    ar relativa till MODELLKATALOG, dar whisper-cli kors. Pa Windows skrivs argumenten i en svarsfil
    (@args.txt i den tillfalliga katalogen, en rad per argument, UTF-8) som whisper-cli laser byte
    for byte, sa att prompten kommer fram som UTF-8; argv ar da bara [cli, "@..."] och svarsfil_text
    ar filens innehall. Pa Mac och Linux skickas argumenten som vanligt och svarsfil_text ar None."""
    modell = os.path.relpath(GGML_MODELL, modeller.MODELLKATALOG)
    cmd = [
        cli,
        "-m", modell,
        "-f", os.path.join(katalog_rel, "ljud.wav"),
        "-l", SPRAK,
        "-bs", str(BEAM),
        # Utan -np skriver whisper-cli sina diagnosrader (backend, system_info, tider) pa stderr; de
        # utvalda loggas av _whispercpp (LOGGA_RADER). Texten skrivs pa stdout, som aldrig lases.
        "-pp",
        "-oj", "-of", os.path.join(katalog_rel, "ut"),  # whisper-cli lagger till .json
    ]
    if prompt:
        cmd += ["--prompt", prompt]
    if tradar:
        cmd += ["-t", str(tradar)]
    if per_ord:
        # Ett segment per ord. whisper.cpp:s vanliga ordtider ar ungefarliga (ett ord kunde
        # hamna 0,6 s fel, sa att det fick fel talare). DTW ger tider som stammer med
        # faster-whisper, men fungerar bara utan flash attention. Darfor bara har.
        cmd += ["-ml", "1", "-sow", "--dtw", DTW, "-nfa", "-ojf"]
    if system != "Windows":
        return cmd, None
    # En rad per argument: en radbrytning i ett argument (ord i installningarna kan ha det)
    # blir ett mellanslag.
    rader = [" ".join(a.splitlines()) if ("\n" in a or "\r" in a) else a for a in cmd[1:]]
    return [cli, "@" + os.path.join(katalog_rel, "args.txt")], "".join(r + "\n" for r in rader)


def stada_kvarglomda(katalog=None):
    """Tar bort kvarglomda tmp-akasha-protokoll-* direkt under MODELLKATALOG (efter en krasch eller
    ett avbrott mitt i en transkribering). Ror inget annat: bara kataloger med exakt det prefixet,
    en niva ner, och aldrig en symbolisk lank eller junction (den foljs inte ut ur katalogen).
    Kastar aldrig. Returnerar antalet borttagna."""
    katalog = katalog or modeller.MODELLKATALOG
    try:
        namn = os.listdir(katalog)
    except OSError:
        return 0
    ar_junction = getattr(os.path, "isjunction", lambda s: False)
    antal = 0
    for n in namn:
        sokvag = os.path.join(katalog, n)
        if not n.startswith(TMP_PREFIX) or os.path.islink(sokvag) or ar_junction(sokvag) \
                or not os.path.isdir(sokvag):
            continue
        try:
            shutil.rmtree(sokvag)
            antal += 1
        except OSError as e:
            log.warning("kunde inte ta bort kvarglomd katalog %s: %s", n, e)
    if antal:
        log.info("tog bort %d kvarglomda tillfalliga kataloger i %s", antal, katalog)
    return antal


def _kansliga_ord(prompt):
    """Prompten och dess ord (minst 4 tecken, gemener): rader som innehaller nagot av dem loggas aldrig."""
    ord_ = {w.lower() for w in re.split(r"[\s,;.:]+", prompt or "") if len(w) >= 4}
    if prompt and prompt.strip():
        ord_.add(prompt.strip().lower())
    return ord_


def _far_sparas(rad, kansliga):
    """Sant om raden far loggas och ga in i felmeddelandet: en diagnosrad utan prompten eller dess ord."""
    if not SAKER_RAD.match(rad):
        return False
    liten = rad.lower()
    return not any(w in liten for w in kansliga)


def _whispercpp(samples, per_ord, prompt, framsteg):
    global _process
    cli = plattform.whisper_cli()
    if cli is None:
        raise MotorFel(_cli_saknas())
    bas = modeller.MODELLKATALOG
    os.makedirs(bas, exist_ok=True)
    # ignore_cleanup_errors: pa Windows kan whisper-cli annu halla en fil oppen efter terminate(), och
    # PermissionError i stadningen far inte doldja Avbruten. Resten tas bort vid nasta start.
    with tempfile.TemporaryDirectory(prefix=TMP_PREFIX, dir=bas, ignore_cleanup_errors=True) as katalog:
        wav = os.path.join(katalog, "ljud.wav")
        with open(wav, "wb") as f:
            f.write(wav_16k_mono(samples))
        ut = os.path.join(katalog, "ut")  # whisper-cli lagger till .json
        cmd, svarsfil = cli_kommando(cli, os.path.basename(katalog), per_ord, prompt, CPU_TRADAR,
                                     plattform.system())
        if svarsfil is not None:
            with open(os.path.join(katalog, "args.txt"), "w", encoding="utf-8", newline="\n") as f:
                f.write(svarsfil)

        t0 = time.monotonic()
        p = plattform.starta_barn(
            cmd, cwd=bas, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace"
        )
        _process = p
        try:
            if _avslutas:  # stoppa() hann inte se processen
                p.terminate()
            sista = collections.deque(maxlen=15)
            forsta = None  # tiden till forsta framsteg (pa Mac kompileras Metal-biblioteken forst)
            loggade = 0
            kansliga = _kansliga_ord(prompt)
            for rad in p.stderr:  # en rad i taget: inget buffras obegransat
                if _far_sparas(rad, kansliga):
                    sista.append(rad.rstrip())
                    if loggade < MAX_LOGGRADER and LOGGA_RADER.match(rad):
                        loggade += 1
                        log.info("whisper-cli: %s", rad.strip())
                m = PROGRESS_RE.search(rad)
                if m and forsta is None:
                    forsta = time.monotonic() - t0
                if m and framsteg:
                    framsteg(int(m.group(1)) / 100)
            kod = p.wait()
            log.info("whisper-cli: forsta framsteg efter %s s, klar efter %.1f s (kod %d, %.0f s ljud)",
                     "%.1f" % forsta if forsta is not None else "-", time.monotonic() - t0, kod,
                     len(samples) / SR)
        finally:
            _process = None
        if kod != 0 and _avslutas:
            raise Avbruten("stoppad")
        if kod != 0:
            raise MotorFel(f"whisper-cli avslutades med kod {p.returncode}: " + " | ".join(sista))
        try:
            with open(ut + ".json", "rb") as f:
                # strict=False: whisper-cli escapar bara " och \ i texten, inte radbrytningar.
                svar = json.loads(f.read().decode("utf-8", "replace"), strict=False)
        except (OSError, ValueError) as e:
            raise MotorFel(f"kunde inte lasa whisper-cli:s JSON: {e}")

    raw = rensa(svar.get("transcription", []))
    # Segmenttexterna har egna inledande mellanslag: satt ihop dem som de ar.
    text = " ".join("".join(s.get("text", "") for s in raw).split())
    tider = [(s["offsets"]["from"] / 1000, s["offsets"]["to"] / 1000, s.get("text", "")) for s in raw]
    if per_ord:
        tider = dtw_ordtider(raw) or tider
        return text, _ord_till_segment(tider), tider
    segs = [
        {"start": round(a, 2), "end": round(b, 2), "text": t.strip()} for a, b, t in tider if t.strip()
    ]
    return text, segs, []


SKILJETECKEN = set(".,!?;:…\"'()-–")


def rensa(raw):
    """Tar bort whisper.cpp:s interna markeringar (<|nospeech|>, [BLANK_AUDIO]) ur text och tokens.
    Annars hamnade t.ex. <|nospeech|> sist i texten, som en egen replik."""
    for seg in raw:
        seg["text"] = INTERNA_RE.sub("", seg.get("text", ""))
        seg["tokens"] = [t for t in seg.get("tokens", []) if not INTERNA_RE.fullmatch(t.get("text", "").strip())]
    return raw


def dtw_ordtider(raw):
    """Ordtider fran DTW (t_dtw per token, hundradels sekunder). None om DTW saknas.
    -> [(start, slut, text, sannolikhet)]

    t_dtw markerar ungefar var token slutar. Ordet slutar dar dess sista bokstavstoken slutar
    (skiljetecken far ibland en sen tid och raknas inte), och borjar 0,2 s fore sin forsta token,
    men aldrig fore foregaende ords slut. Sannolikheten ar den lagsta bland ordets bokstavstokens:
    hur saker whisper var pa ordet.
    """
    ut, forra_slut = [], 0.0
    for seg in raw:
        tokens = [t for t in seg.get("tokens", [])
                  if not t.get("text", "").startswith("[") and t.get("text", "").strip(" ").strip("".join(SKILJETECKEN))]
        tid = [t.get("t_dtw", -1) / 100 for t in tokens]
        if not seg.get("text", "").strip():
            continue
        if not tid or min(tid) < 0:
            return None  # DTW kordes inte (t.ex. aldre whisper.cpp)
        slut = max(tid)
        start = max(forra_slut, min(tid) - 0.2)
        p = min((t["p"] for t in tokens if "p" in t), default=None)
        ut.append((round(start, 2), round(max(slut, start + 0.05), 2), seg["text"], p))
        forra_slut = slut
    return ut


def _ord_till_segment(ord_lista, max_tecken=200):
    """Ord (fran -ml 1) -> segment av lagom langd, delade efter meningsslut."""
    segs, aktuell = [], None
    for a, b, t, *_ in ord_lista:
        if aktuell is None:
            aktuell = {"start": a, "end": b, "text": ""}
        aktuell["end"] = b
        aktuell["text"] += t
        if t.rstrip().endswith((".", "?", "!")) or len(aktuell["text"]) > max_tecken:
            segs.append(aktuell)
            aktuell = None
    if aktuell:
        segs.append(aktuell)
    return [
        {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": " ".join(s["text"].split())}
        for s in segs
        if s["text"].strip()
    ]
