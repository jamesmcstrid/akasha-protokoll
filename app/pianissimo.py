"""Taligenkanning med Klang Pianissimo (KlangAI/pianissimo-sv-onnx, CC-BY-4.0), en svensk Parakeet-modell, via onnx-asr.

Valfri motor (MOTOR=pianissimo): onnx-asr ingar inte i appens krav utan i app/krav-pianissimo.txt. Modellen
hamtas av modeller.py som de andra. Pa processorn var den 6-8 ganger snabbare an KB-Whisper medium (Windows-
laptop) och ungefar 6 ganger snabbare an KB-Whisper med Metal (MacBook Air, 49 ganger realtid).

Ljudet delas vid tystaste stallet i bitar om hogst 30 s, sa att en timmes mote gar att kora utan att modellen
far hela ljudet pa en gang (och utan en andra modell for tal och tystnad). Ordtider kommer fran onnx-asr:s tid
per token (80 ms steg). Ingen prompt och ingen ordforstarkning: ORDLISTA och svarstavade ord ignoreras.
"""
import logging
import os
import threading
import time
from collections import namedtuple

import numpy as np

import modeller
import motor
from installningar import CPU_TRADAR

log = logging.getLogger("akasha-protokoll")
SR = 16000

BIT_S = 30  # langsta bit som modellen far
BIT_SOK_S = 10  # tystaste stallet soks i bitens sista sa manga sekunder
RAM_S = 0.05  # nivan mats i ramar om 50 ms
MIN_ORD_S = 0.1  # kortaste ordet i ordlistan
MAX_ORD_S = 1.0  # langsta ordet: en paus efter ordet raknas inte som tal i talaruppdelningen

_las = threading.Lock()  # modellen laddas en gang och anvands av en transkribering at gangen
_modell = None
_prompt_loggad = False

Bit = namedtuple("Bit", "fran till ord")  # fran och till i sampel; ord som motor.transkribera ger med per_ord


def ord_fran_tokens(tokens, tider, slut_s):
    """Pianissimos tokens (SentencePiece-bitar) och starttider -> [(start, slut, text)] som motor.transkribera.

    Ett ord borjar vid en bit som inleds med mellanslag eller ▁ (onnx-asr gor om ▁ till mellanslag) och
    far texten med inledande mellanslag, som whisper ger. Ordet slutar dar nasta borjar, men inte
    senare an MAX_ORD_S (annars raknas pauser som tal) och inte fore MIN_ORD_S. Sista ordet slutar
    vid slut_s, ljudets slut."""
    ord_ = []
    for bit, start in zip(tokens, tider):
        if not ord_ or bit[:1] in (" ", "▁"):
            ord_.append([start, " "])
        ord_[-1][1] += bit.lstrip(" ▁")
    ord_ = [(start, text) for start, text in ord_ if text.strip()]
    ut = []
    for i, (start, text) in enumerate(ord_):
        nasta = ord_[i + 1][0] if i + 1 < len(ord_) else slut_s
        ut.append((start, max(start + MIN_ORD_S, min(nasta, start + MAX_ORD_S)), text))
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
    kat = os.path.dirname(modeller.paket("pianissimo")[0].sokvag())
    modell = onnx_asr.load_model("nemo-conformer-tdt", kat, quantization="int8", sess_options=val,
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


def transkribera(samples, per_ord, prompt, framsteg):
    """-> (text, segment, ord), samma form som de andra motorerna ger i motor.transkribera.

    Med per_ord ger orden talaruppdelningen sina ordtider, som whisper.cpp:s DTW-ord, och segmenten delas
    efter meningsslut. Utan per_ord blir det ett segment per bit och ingen ordlista. Modellen laddas vid
    forsta anropet och ligger sedan kvar i minnet; laset gor att bara en tradd i taget anvander den."""
    global _modell, _prompt_loggad
    if prompt and not _prompt_loggad:
        _prompt_loggad = True
        log.info("Pianissimo anvander inte ORDLISTA eller svarstavade ord: prompten ignoreras")
    ord_lista, segs = [], []
    with _las:
        if _modell is None:
            _modell, sek = ladda()
            log.info("Pianissimo: modellen laddades pa %.1f s", sek)
        for bit in bitar_med_ord(_modell, samples):
            ord_lista += bit.ord
            if text := ord_till_text(bit.ord):
                segs.append({"start": round(bit.ord[0][0], 2), "end": round(bit.ord[-1][1], 2), "text": text})
            if framsteg:
                framsteg(bit.till / len(samples))
    if per_ord:
        return ord_till_text(ord_lista), motor._ord_till_segment(ord_lista), ord_lista
    return " ".join(s["text"] for s in segs), segs, []
