"""Taligenkanning med KB-Whisper medium (KBLab, Kungliga biblioteket). Tva motorer, valj med MOTOR:

  faster      faster-whisper (CTranslate2) i den har processen, pa CPU. Fungerar overallt.
              Modellen laddas vid forsta transkriberingen och ligger sedan kvar i minnet.
  whispercpp  whisper.cpp:s whisper-cli (brew install whisper-cpp), som anvander Metal (GPU) pa
              Apple Silicon. Startas en gang per transkribering och laddar modellen varje gang.

Ingen sprakmodell rattar eller sammanfattar texten. Det som whisper hor ar det som skrivs.
"""
import collections
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave

import numpy as np

from installningar import CPU_TRADAR, CT2_MODELL, GGML_MODELL, MOTOR, SPRAK, WHISPERCPP_BIN

SR = 16000
BEAM = 5
PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")

_las = threading.Lock()  # en transkribering at gangen: modellen tar 1-2 GB minne
_faster_modell = None


class MotorFel(Exception):
    """Motorn saknas, kraschar eller svarar fel."""


def problem():
    """None om motorn ar redo, annars vad som saknas."""
    if MOTOR == "faster":
        if not os.path.isfile(os.path.join(CT2_MODELL, "model.bin")):
            return "KB-Whisper saknas. Kor: bash mac/hamta-modeller.sh"
        return None
    if MOTOR == "whispercpp":
        if not shutil.which(WHISPERCPP_BIN):
            return f"{WHISPERCPP_BIN} saknas. Kor: brew install whisper-cpp"
        if not os.path.isfile(GGML_MODELL):
            return "KB-Whisper (GGML) saknas. Kor: bash mac/hamta-modeller.sh ggml"
        return None
    return f"okand MOTOR={MOTOR!r}, anvand faster eller whispercpp"


def modellnamn():
    return "KB-Whisper medium" + (" (whisper.cpp)" if MOTOR == "whispercpp" else "")


def avkoda(sokvag):
    """Valfritt ljudformat -> float32, 16 kHz mono. PyAV (samma som faster-whisper anvander)."""
    from faster_whisper.audio import decode_audio

    return decode_audio(sokvag, sampling_rate=SR)


def transkribera(samples, per_ord=False, prompt="", framsteg=None):
    """-> (text, segment, ord).

    segment: [{"start", "end", "text"}] i sekunder.
    ord: [(start, slut, text)] om per_ord (behovs for talaridentifiering), annars [].
    framsteg: anropas med en andel 0..1 medan arbetet pagar.
    """
    fel = problem()
    if fel:
        raise MotorFel(fel)
    with _las:
        if MOTOR == "faster":
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
        ord_lista.extend((w.start, w.end, w.word) for w in (s.words or []))
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


def _whispercpp(samples, per_ord, prompt, framsteg):
    with tempfile.TemporaryDirectory(prefix="akasha-meet-") as katalog:
        wav = os.path.join(katalog, "ljud.wav")
        with open(wav, "wb") as f:
            f.write(wav_16k_mono(samples))
        ut = os.path.join(katalog, "ut")  # whisper-cli lagger till .json
        cmd = [
            shutil.which(WHISPERCPP_BIN),
            "-m", GGML_MODELL,
            "-f", wav,
            "-l", SPRAK,
            "-bs", str(BEAM),
            "-np", "-pp",  # inga utskrifter utom framsteg
            "-oj", "-of", ut,
        ]
        if prompt:
            cmd += ["--prompt", prompt]
        if CPU_TRADAR:
            cmd += ["-t", str(CPU_TRADAR)]
        if per_ord:
            cmd += ["-ml", "1", "-sow"]  # ett segment per ord, med tidsstamplar

        p = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace"
        )
        sista = collections.deque(maxlen=15)
        for rad in p.stderr:
            sista.append(rad.rstrip())
            m = PROGRESS_RE.search(rad)
            if m and framsteg:
                framsteg(int(m.group(1)) / 100)
        if p.wait() != 0:
            raise MotorFel(f"whisper-cli avslutades med kod {p.returncode}: " + " | ".join(sista))
        try:
            with open(ut + ".json", "rb") as f:
                # strict=False: whisper-cli escapar bara " och \ i texten, inte radbrytningar.
                svar = json.loads(f.read().decode("utf-8", "replace"), strict=False)
        except (OSError, ValueError) as e:
            raise MotorFel(f"kunde inte lasa whisper-cli:s JSON: {e}")

    raw = svar.get("transcription", [])
    # Segmenttexterna har egna inledande mellanslag: satt ihop dem som de ar.
    text = " ".join("".join(s.get("text", "") for s in raw).split())
    tider = [(s["offsets"]["from"] / 1000, s["offsets"]["to"] / 1000, s.get("text", "")) for s in raw]
    if per_ord:
        return text, _ord_till_segment(tider), tider
    segs = [
        {"start": round(a, 2), "end": round(b, 2), "text": t.strip()} for a, b, t in tider if t.strip()
    ]
    return text, segs, []


def _ord_till_segment(ord_lista, max_tecken=200):
    """Ord (fran -ml 1) -> segment av lagom langd, delade efter meningsslut."""
    segs, aktuell = [], None
    for a, b, t in ord_lista:
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
