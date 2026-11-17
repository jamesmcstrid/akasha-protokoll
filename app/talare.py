"""Talaridentifiering: vem pratar nar. Kors lokalt.

Metod (fonster och klustring):
  1. Talet delas i glidande fonster om 1,5 s (steg 0,5 s). Var det finns tal vet vi fran
     whispers ordtider.
  2. En rostmodell (3D-Speaker ERes2Net, VoxCeleb, via sherpa-onnx) gor ett rostavtryck per fonster.
  3. Avtrycken delas upp i sa manga grupper som antalet talare (k-means med cosinusavstand).
     Grupper som ar nastan lika slas ihop: da ar det samma person. "Vet inte": provar 2, 3, ...
     grupper och stannar innan tva grupper blir for lika.
  4. Varje ord far den grupp som fonstren runt ordet liknar mest.

Varfor inte pyannote: i ett riktigt samtal inspelat med en laptopmikrofon hittade pyannotes
segmentering inga talarbyten alls, medan fonstermetoden hittade dem (se README).
Ingen modell ror texten: whisper transkriberar, och har far varje ord en talare.
"""
import os
import threading

import numpy as np

from installningar import ROSTMODELL, TALARE_TROSKEL

SR = 16000
FONSTER_S = 1.5
STEG_S = 0.5
MAX_TALARE = 10
AUTO_MAX = 6  # "vet inte": som mest sa manga talare
MIN_TAL_I_FONSTER = 0.3  # andel av fonstret som maste vara tal
MIN_NIVA = 0.2  # fonster tystare an sa har (andel av mediannivan) hoppas over: brus, inte rost
VIKT_SIGMA_S = 0.35  # fonster nara ordets mitt vager tyngst (gaussisk vikt), 0 = lika vikt
MIN_GRUPP = 3  # "vet inte": en talare maste ha minst sa manga fonster (1,5 s eget tal)

_las = threading.Lock()
_extraktor = None


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
    if not os.path.isfile(ROSTMODELL):
        return "röstmodellen saknas. Kor: bash mac/hamta-modeller.sh talare"
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return "sherpa-onnx saknas. Kor: bash mac/installera.sh"
    return None


def _hamta_extraktor():
    global _extraktor
    if _extraktor is None:
        import sherpa_onnx

        _extraktor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=ROSTMODELL, num_threads=min(4, os.cpu_count() or 2)
            )
        )
    return _extraktor


def _avtryck(extraktor, x):
    s = extraktor.create_stream()
    s.accept_waveform(SR, x)
    s.input_finished()
    v = np.asarray(extraktor.compute(s), dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


# --- ren matematik (testas utan modell) ----------------------------------------------------

def fonster_med_tal(ord_lista, langd_s):
    """Starttider for fonster dar minst MIN_TAL_I_FONSTER av tiden ar tal enligt ordtiderna."""
    if langd_s <= FONSTER_S:
        return [0.0] if ord_lista else []
    tal = sorted((max(0.0, a - 0.1), min(langd_s, b + 0.1)) for a, b, _ in ord_lista)
    starter = []
    for start in np.arange(0.0, langd_s - FONSTER_S + 1e-9, STEG_S):
        slut = start + FONSTER_S
        overlapp = sum(max(0.0, min(slut, b) - max(start, a)) for a, b in tal if b > start and a < slut)
        if overlapp >= MIN_TAL_I_FONSTER * FONSTER_S:
            starter.append(float(start))
    return starter


def kmeans(X, k, forsok=10, seed=0):
    """k-means for normerade vektorer (cosinus). -> (etiketter, centroider)."""
    k = max(1, min(k, len(X)))
    rng = np.random.default_rng(seed)
    basta = None
    for _ in range(forsok):
        # k-means++: borja med punkter som ligger langt fran varandra
        c = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            avstand = 1.0 - np.max(X @ np.array(c).T, axis=1)
            p = np.clip(avstand, 0, None) ** 2
            c.append(X[rng.choice(len(X), p=p / p.sum())] if p.sum() > 0 else X[rng.integers(len(X))])
        c = np.array(c)
        for _ in range(100):
            etiketter = np.argmax(X @ c.T, axis=1)
            ny = np.array([X[etiketter == j].mean(0) if np.any(etiketter == j) else c[j] for j in range(k)])
            ny /= np.linalg.norm(ny, axis=1, keepdims=True) + 1e-9
            if np.allclose(ny, c, atol=1e-6):
                break
            c = ny
        poang = float(np.sum(np.max(X @ c.T, axis=1)))
        if basta is None or poang > basta[0]:
            basta = (poang, np.argmax(X @ c.T, axis=1), c)
    return basta[1], basta[2]


def sla_ihop_lika(X, etiketter, troskel):
    """Sla ihop grupper vars medelavtryck liknar varandra mer an troskel (samma person)."""
    etiketter = etiketter.copy()
    while True:
        grupper = sorted(set(etiketter.tolist()))
        if len(grupper) < 2:
            break
        c = np.array([X[etiketter == g].mean(0) for g in grupper])
        c /= np.linalg.norm(c, axis=1, keepdims=True) + 1e-9
        likhet = c @ c.T
        np.fill_diagonal(likhet, -1.0)
        i, j = np.unravel_index(np.argmax(likhet), likhet.shape)
        if likhet[i, j] <= troskel:
            break
        etiketter[etiketter == grupper[j]] = grupper[i]
    grupper = sorted(set(etiketter.tolist()))
    c = np.array([X[etiketter == g].mean(0) for g in grupper])
    c /= np.linalg.norm(c, axis=1, keepdims=True) + 1e-9
    return np.array([grupper.index(e) for e in etiketter]), c


def gissa_antal(X, troskel, max_antal=None):
    """Prova 2, 3, ... grupper och stanna innan tva grupper blir mer lika an troskel, eller
    innan nagon grupp blir for liten for att vara en egen person.

    -> (etiketter, centroider). En grupp om redan tva ar for lika (en person).
    """
    max_antal = max_antal or AUTO_MAX
    basta = (np.zeros(len(X), dtype=int), _centroider(X, np.zeros(len(X), dtype=int)))
    for k in range(2, min(max_antal, len(X)) + 1):
        etiketter, c = kmeans(X, k)
        if len(set(etiketter.tolist())) < k or np.bincount(etiketter, minlength=k).min() < MIN_GRUPP:
            break
        likhet = c @ c.T
        np.fill_diagonal(likhet, -1.0)
        if likhet.max() > troskel:
            break
        basta = (etiketter, c)
    return basta


def _centroider(X, etiketter):
    c = np.array([X[etiketter == g].mean(0) for g in sorted(set(etiketter.tolist()))])
    return c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-9)


def etikett_per_ord(ord_lista, starter, X, centroider):
    """Varje ord far den grupp som fonstren runt ordets mitt liknar mest. Fonster vars mitt ligger
    nara ordet vager tyngst, sa att ett talarbyte hamnar mellan ratt ord."""
    starter = np.asarray(starter)
    mitter = starter + FONSTER_S / 2
    ut = []
    for a, b, _ in ord_lista:
        m = (a + b) / 2
        runt = np.where((starter <= m) & (m <= starter + FONSTER_S))[0]
        if len(runt) == 0:
            runt = np.array([int(np.argmin(np.abs(mitter - m)))])
        if VIKT_SIGMA_S > 0:
            vikt = np.exp(-0.5 * ((mitter[runt] - m) / VIKT_SIGMA_S) ** 2) + 1e-6
        else:
            vikt = np.ones(len(runt))
        poang = (vikt[:, None] * (X[runt] @ centroider.T)).sum(0) / vikt.sum()
        ut.append(int(np.argmax(poang)))
    return ut


def utan_tysta(samples, starter):
    """Ta bort fonster som ar mycket tystare an de andra (brus eller andning, inte rost)."""
    if not starter or MIN_NIVA <= 0:
        return starter
    niva = np.array([np.sqrt(np.mean(samples[int(s * SR): int((s + FONSTER_S) * SR)] ** 2) + 1e-12)
                     for s in starter])
    grans = MIN_NIVA * np.median(niva)
    kvar = [s for s, n in zip(starter, niva) if n >= grans]
    return kvar if len(kvar) >= 2 else starter


def repliker(ord_lista, etiketter):
    """Sla ihop ord i foljd med samma talare till repliker. Talarna numreras fran 1 i den
    ordning de forst sager nagot. -> [{"start", "end", "speaker", "text"}]"""
    nummer, ut = {}, []
    for (start, slut, text), e in zip(ord_lista, etiketter):
        if not text.strip():
            continue
        nr = nummer.setdefault(e, len(nummer) + 1)
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


# --- hela kedjan ---------------------------------------------------------------------------

def dela_upp(samples, ord_lista, antal, framsteg=None):
    """-> (repliker, antal_hittade, varning eller None).

    samples: float32, 16 kHz mono. ord_lista: [(start, slut, text)] fran whisper.
    antal: int (kant antal) eller None (gissa, som mest AUTO_MAX).
    """
    ord_lista = [o for o in ord_lista if o[2].strip()]
    langd = len(samples) / SR
    starter = utan_tysta(samples, fonster_med_tal(ord_lista, langd))
    if antal == 1 or len(starter) < 2:
        return repliker(ord_lista, [0] * len(ord_lista)), 1, None

    with _las:
        extraktor = _hamta_extraktor()
        X = []
        for i, start in enumerate(starter):
            bit = samples[int(start * SR): int((start + FONSTER_S) * SR)]
            X.append(_avtryck(extraktor, bit))
            if framsteg and i % 10 == 0:
                framsteg(i / len(starter))
    X = np.array(X)

    if antal:
        etiketter, _ = kmeans(X, antal)
        # Skyddsracke: grupper som ar nastan lika ar samma person. Hellre farre talare an pahittade.
        etiketter, centroider = sla_ihop_lika(X, etiketter, TALARE_TROSKEL)
    else:
        etiketter, centroider = gissa_antal(X, TALARE_TROSKEL)
    hittade = len(centroider)
    varning = None
    if antal and hittade < antal:
        varning = (f"Du angav {antal} talare, men bara {hittade} "
                   f"{'röst' if hittade == 1 else 'röster'} gick att skilja åt.")
    if framsteg:
        framsteg(1.0)
    per_ord = etikett_per_ord(ord_lista, starter, X, centroider)
    rep = repliker(ord_lista, per_ord)
    return rep, len({r["speaker"] for r in rep}), varning
