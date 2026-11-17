"""Talaridentifiering: vem pratar nar. Kors lokalt med sherpa-onnx.

1. pyannote segmentation-3.0 hittar var nagon pratar och var talaren byts.
2. En rostmodell (NeMo TitaNet small) gor ett rostavtryck for varje taldel.
3. Klustring delar upp avtrycken pa N talare (kant antal) eller sa manga som behovs (auto).

Ingen modell ror texten: whisper transkriberar, och har paras varje ord ihop med den talare
som pratade nar ordet sades.
"""
import os
import threading

from installningar import ROSTMODELL, SEGMENTERINGSMODELL, TALARE_TROSKEL

MAX_TALARE = 10
_las = threading.Lock()
_motor = None


def tolka_antal(varde):
    """'1'..'10' -> int, 'auto' -> None. Annat -> ValueError."""
    v = str(varde).strip().lower()
    if v == "auto":
        return None
    n = int(v)
    if not 1 <= n <= MAX_TALARE:
        raise ValueError(f"antal talare maste vara 1-{MAX_TALARE} eller auto")
    return n


def problem():
    """None om allt finns, annars vad som saknas."""
    for fil in (SEGMENTERINGSMODELL, ROSTMODELL):
        if not os.path.isfile(fil):
            return "talarmodellerna saknas. Kor: bash mac/hamta-modeller.sh talare"
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return "sherpa-onnx saknas. Kor: bash mac/installera.sh"
    return None


def _config(antal):
    import sherpa_onnx

    tradar = min(4, os.cpu_count() or 2)
    return sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=SEGMENTERINGSMODELL
            ),
            num_threads=tradar,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=ROSTMODELL, num_threads=tradar),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=antal if antal else -1, threshold=TALARE_TROSKEL
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )


def vem_pratar_nar(samples, antal, framsteg=None):
    """samples: float32, 16 kHz mono. antal: int eller None (auto).

    Returnerar [(start_s, slut_s, talare)] sorterat pa tid (sherpa:s etiketter 0, 1, ...).
    """
    global _motor
    import sherpa_onnx

    def aterrop(klara, totalt):
        if framsteg and totalt:
            framsteg(klara / totalt)
        return 0  # 0 = fortsatt

    with _las:  # modellerna laddas en gang; antalet talare satts per korning
        cfg = _config(antal)
        if _motor is None:
            _motor = sherpa_onnx.OfflineSpeakerDiarization(cfg)
        else:
            _motor.set_config(cfg)
        res = _motor.process(samples, callback=aterrop).sort_by_start_time()
    return [(r.start, r.end, r.speaker) for r in res]


def _talare_for(start, slut, turer):
    """Talaren som overlappar ordet mest. Inget overlapp (ord i en paus): narmaste tur."""
    basta, basta_overlapp = None, 0.0
    for a, b, s in turer:
        overlapp = min(slut, b) - max(start, a)
        if overlapp > basta_overlapp:
            basta, basta_overlapp = s, overlapp
    if basta is not None:
        return basta
    mitt = (start + slut) / 2
    return min(
        turer,
        key=lambda t: 0.0 if t[0] <= mitt <= t[1] else min(abs(mitt - t[0]), abs(mitt - t[1])),
    )[2]


def repliker(ord_lista, turer):
    """Para ihop ord med talare och sla ihop ord i foljd fran samma talare till repliker.

    ord_lista: [(start_s, slut_s, text)] dar texten har sitt eget inledande mellanslag
    (som fran whisper). turer: fran vem_pratar_nar. Talarna numreras om fran 1 i den ordning
    de forst sager nagot. Returnerar [{"start", "end", "speaker", "text"}].
    """
    if not turer:
        turer = [(0.0, float("inf"), 0)]
    nummer = {}
    ut = []
    for start, slut, text in ord_lista:
        if not text.strip():
            continue
        s = _talare_for(start, slut, turer)
        nr = nummer.setdefault(s, len(nummer) + 1)
        if ut and ut[-1]["speaker"] == nr:
            ut[-1]["end"] = slut
            ut[-1]["text"] += text
        else:
            ut.append({"start": start, "end": slut, "speaker": nr, "text": text})
    for r in ut:
        r["text"] = " ".join(r["text"].split())
        r["start"] = round(r["start"], 2)
        r["end"] = round(r["end"], 2)
    return ut
