"""Taligenkanning med Klang Pianissimo (KlangAI/pianissimo-sv-onnx, CC-BY-4.0), en svensk Parakeet-modell, via onnx-asr.

Valfri motor (MOTOR=pianissimo): onnx-asr ingar inte i appens krav utan i app/krav-pianissimo.txt. Modellen
hamtas av modeller.py som de andra. Pa processorn var den 6-8 ganger snabbare an KB-Whisper medium (Windows-
laptop) och ungefar 6 ganger snabbare an KB-Whisper med Metal (MacBook Air, 49 ganger realtid).

Ljudet delas vid tystaste stallet i bitar om hogst 30 s, sa att en timmes mote gar att kora utan att modellen
far hela ljudet pa en gang (och utan en andra modell for tal och tystnad). Ordtider kommer fran onnx-asr:s tid
per token (80 ms steg). Prompten (ORDLISTA och svarstavade ord, kommaseparerade) forstarker orden under en
transkribering, se pianissimo_boost.py.
"""
import contextlib
import logging
import os
import re
import threading
import time
from collections import namedtuple

import numpy as np

import modeller
import motor
import pianissimo_boost
from installningar import CPU_TRADAR

log = logging.getLogger("akasha-protokoll")
SR = 16000
TOKENISERARE = "tokenizer.model"  # SentencePiece-modellen, for ordforstarkningen

BIT_S = 30  # langsta bit som modellen far
BIT_SOK_S = 10  # tystaste stallet soks i bitens sista sa manga sekunder
RAM_S = 0.05  # nivan mats i ramar om 50 ms
MIN_ORD_S = 0.1  # kortaste ordet i ordlistan
MAX_ORD_S = 1.0  # ett ord raknas som tal hogst sa lange efter sin start: en paus efter det raknas inte som tal
SLUT_BIT_S = 0.3  # men ett langre ord slutar tidigast sa har lange efter sin sista bit

_las = threading.Lock()  # modellen laddas en gang och anvands av en transkribering at gangen
_modell = None

Bit = namedtuple("Bit", "fran till ord")  # fran och till i sampel; ord som motor.transkribera ger med per_ord


def ord_fran_tokens(tokens, tider, slut_s):
    """Pianissimos tokens (SentencePiece-bitar) och starttider -> [(start, slut, text)] som motor.transkribera.

    Ett ord borjar vid en bit som inleds med mellanslag eller ▁ (onnx-asr gor om ▁ till mellanslag) och
    far texten med inledande mellanslag, som whisper ger. Ordet slutar dar nasta borjar, men inte
    senare an MAX_ORD_S efter starten (annars raknas pauser som tal), utom for ett langt ord: det
    slutar tidigast SLUT_BIT_S efter sin sista bit. Annars klipptes ett ord pa 1,5 s vid 1 s, och luckan efter
    det raknades som en paus som delade meningen i talaruppdelningen. Ordet slutar inte fore MIN_ORD_S.
    Sista ordet slutar vid slut_s, ljudets slut."""
    ord_ = []
    for bit, start in zip(tokens, tider):
        if not ord_ or bit[:1] in (" ", "▁"):
            ord_.append([start, " ", start])
        ord_[-1][1] += bit.lstrip(" ▁")
        ord_[-1][2] = start
    ord_ = [(start, text, sista) for start, text, sista in ord_ if text.strip()]
    ut = []
    for i, (start, text, sista) in enumerate(ord_):
        nasta = ord_[i + 1][0] if i + 1 < len(ord_) else slut_s
        langst = max(start + MAX_ORD_S, sista + SLUT_BIT_S)
        ut.append((start, max(start + MIN_ORD_S, min(nasta, langst)), text))
    return ut


def dela_i_bitar(samples, bit_s=BIT_S, sok_s=BIT_SOK_S):
    """-> [(fran, till)] i sampel: bitar om hogst bit_s, klippta dar ljudet ar tystast under bitens
    sista sok_s sekunder, sa att ett ord sallan klipps itu."""
    ram = int(RAM_S * SR)
    bitar, a = [], 0
    while len(samples) - a > bit_s * SR:
        fran = a + int((bit_s - sok_s) * SR)
        antal = int(sok_s * SR) // ram
        niva = (samples[fran:fran + antal * ram].reshape(antal, ram) ** 2).mean(axis=1)
        klipp = fran + int(np.argmin(niva)) * ram + ram // 2
        bitar.append((a, klipp))
        a = klipp
    bitar.append((a, len(samples)))
    return bitar


def _modellkatalog():
    return os.path.dirname(modeller.paket("pianissimo")[0].sokvag())


def ladda(bara_cpu=True):
    """Laddar modellen (filerna ska redan vara hamtade). -> (modell, laddningstid i s).

    bara_cpu: alltid sant i appen. Pa Mac valjer onnxruntime annars CoreML, som bara klarar en del av grafen
    (uppmatt: 348 bitar och 1648 av 4635 noder): bitarna skickas fram och tillbaka och det blir ungefar 6 ganger
    langsammare an bara processorn. Falskt finns bara sa att halsokoll/jamfor_motorer.py kan mata det."""
    import onnx_asr
    import onnxruntime

    t0 = time.perf_counter()
    val = onnxruntime.SessionOptions()
    val.intra_op_num_threads = CPU_TRADAR  # 0 = onnxruntime valjer, som i appen
    modell = onnx_asr.load_model("nemo-conformer-tdt", _modellkatalog(), quantization="int8", sess_options=val,
                                 providers=["CPUExecutionProvider"] if bara_cpu else None)
    return modell.with_timestamps(), time.perf_counter() - t0


def bitar_med_ord(modell, samples):
    """Kor modellen bit for bit och ger en Bit per bit. Kastar motor.Avbruten fore en bit om programmet
    avslutas, sa att ett langt mote stannar inom en bit (hogst 30 s ljud) i stallet for att tas till slut."""
    for fran, till in dela_i_bitar(samples):
        if motor._avslutas:
            raise motor.Avbruten("stoppad")
        res = modell.recognize(samples[fran:till])
        tider = [fran / SR + t for t in res.timestamps or []]
        yield Bit(fran, till, ord_fran_tokens(res.tokens or [], tider, till / SR))


def ord_till_text(ord_):
    return " ".join("".join(o[2] for o in ord_).split())


def ordlista_ur_prompt(prompt):
    """Prompten ("Carter, Fredskvist") -> ["Carter", "Fredskvist"]. Ord med mellanslag ar en fras."""
    return [o.strip() for o in re.split(r"[,;\n]", prompt or "") if o.strip()]


@contextlib.contextmanager
def med_ordlista(modell, prompt):
    """Forstarker orden i prompten under en transkribering och tar bort forstarkningen efter, ocksa vid fel,
    sa att en inspelnings ord aldrig foljer med till nasta (modellen ligger kvar i minnet). Gar forstarkningen
    inte att satta in fortsatter transkriberingen utan den. Orden loggas aldrig, se motor._kansliga_ord."""
    ord_ = ordlista_ur_prompt(prompt)
    if not ord_:
        yield
        return
    try:
        pianissimo_boost.forstark(modell, ord_, os.path.join(_modellkatalog(), TOKENISERARE))
    except Exception as e:  # ett saknat paket eller en ny onnx-asr far aldrig stoppa transkriberingen
        log.warning("Pianissimo: ordlistan gick inte att anvanda, transkriberar utan den (%s)", type(e).__name__)
    try:
        yield
    finally:
        pianissimo_boost.stang_av(modell)


def transkribera(samples, per_ord, prompt, framsteg):
    """-> (text, segment, ord), samma form som de andra motorerna ger i motor.transkribera.

    Med per_ord ger orden talaruppdelningen sina ordtider, som whisper.cpp:s DTW-ord, och segmenten delas
    efter meningsslut. Utan per_ord blir det ett segment per bit. Modellen laddas vid forsta anropet och
    ligger sedan kvar i minnet; laset gor att bara en tradd i taget anvander den (och dess ordlista)."""
    global _modell
    ord_lista, segs = [], []
    with _las:
        if _modell is None:
            _modell, sek = ladda()
            log.info("Pianissimo: modellen laddades pa %.1f s", sek)
        with med_ordlista(_modell, prompt):
            for bit in bitar_med_ord(_modell, samples):
                ord_lista += bit.ord
                if text := ord_till_text(bit.ord):
                    segs.append({"start": round(bit.ord[0][0], 2), "end": round(bit.ord[-1][1], 2), "text": text})
                if framsteg:
                    framsteg(bit.till / len(samples))
    if per_ord:
        return ord_till_text(ord_lista), motor._ord_till_segment(ord_lista), ord_lista
    return " ".join(s["text"] for s in segs), segs, []
