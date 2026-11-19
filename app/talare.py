"""Talaridentifiering: vem pratar nar. Kors lokalt.

Metod (fonster och klustring):
  1. Talet delas i glidande fonster om 1,5 s (steg 0,5 s). Var det finns tal vet vi fran
     whispers ordtider.
  2. En rostmodell (NeMo TitaNet small, via sherpa-onnx) gor ett rostavtryck per fonster.
  3. Avtrycken delas upp i sa manga grupper som antalet talare (k-means med cosinusavstand).
     Grupper som ar nastan lika slas ihop (snittet av likheterna mellan de ursprungliga
     grupperna, se sla_ihop_lika): da ar det samma person. "Vet inte": provar 2, 3, ...
     grupper och stannar innan tva grupper blir for lika.
  4. Varje ord far den grupp som fonstren runt ordet liknar mest.

Varfor inte pyannote: i ett riktigt samtal inspelat med en laptopmikrofon hittade pyannotes
segmentering inga talarbyten alls, medan fonstermetoden hittade dem (se docs/TEKNIK.md).
Ingen modell ror texten: whisper transkriberar, och har far varje ord en talare.
"""
import os
import re
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
MENING_PAUS_S = 0.4  # meningsregeln: en sa har lang paus avslutar ocksa en mening
KORT_SJOK = 4  # meningsregeln: hogst sa manga ord i rad kan fa meningens talare
MARGINAL = 0.03  # osaker talare: rosten liknar tva grupper nastan lika mycket (kalibrerad pa AMI)
OSAKER_ANDEL = 0.5  # en replik ar osaker om sa stor andel av orden ar osakra
ORD_P = 0.5  # osakert ord: whisper var mindre saker an sa (standard; motorn anger sin egen, se motor.ord_grans)
STOR_GRUPP_S = 30.0  # sammanslagning: grupper med minst sa mycket tal jamfors grupp for grupp
SAKER_KVOT = 4.0  # digitalt mote: ena kanalen maste vara sa har mycket starkare for ett sakert beslut

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
    tal = sorted((max(0.0, o[0] - 0.1), min(langd_s, o[1] + 0.1)) for o in ord_lista)
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
    """Sla ihop grupper som liknar varandra mer an troskel (samma person).

    Likheten mellan tva grupper, som kan vara sammanslagna redan, mats pa tva satt:
    - Bada har minst STOR_GRUPP_S tal: snittet av likheterna mellan de ursprungliga grupperna,
      viktat med antal fonster. Den sammanslagna gruppens medelavtryck hamnar mellan delarna och
      blir mer likt en tredje grupp an nagon av delarna ar. I ett riktigt mote med fem personer
      forsvann darfor en talare med 17 minuters tal, trots att den liknade bada delarna mindre
      an troskeln.
    - Annars: likheten mellan medelavtrycken. En kort grupps medelavtryck ar osakert och jamfors
      hellre med den storre gruppens samlade rost. Sa slas korta avvikelser hos en och samma
      person ihop (i en inspelning med en person: en grupp om 3 s som annars blev en egen talare).
    """
    grupper = sorted(set(etiketter.tolist()))
    c = _centroider(X, etiketter)
    likhet = c @ c.T
    n = np.array([np.sum(etiketter == g) for g in grupper], dtype=float)
    stor = STOR_GRUPP_S / STEG_S  # fonster
    kluster = [[i] for i in range(len(grupper))]
    while len(kluster) > 1:
        medel = [_medelavtryck(X[np.isin(etiketter, [grupper[i] for i in k])]) for k in kluster]
        basta, par = -2.0, None
        for p in range(len(kluster)):
            for q in range(p + 1, len(kluster)):
                if min(n[kluster[p]].sum(), n[kluster[q]].sum()) >= stor:
                    vikt = np.outer(n[kluster[p]], n[kluster[q]])
                    lik = float(np.sum(vikt * likhet[np.ix_(kluster[p], kluster[q])]) / vikt.sum())
                else:
                    lik = float(medel[p] @ medel[q])
                if lik > basta:
                    basta, par = lik, (p, q)
        if basta <= troskel:
            break
        p, q = par
        kluster[p] += kluster.pop(q)
    karta = {grupper[i]: k for k, medlemmar in enumerate(kluster) for i in medlemmar}
    nya = np.array([karta[e] for e in etiketter.tolist()])
    return nya, _centroider(X, nya)


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


def _medelavtryck(X):
    v = X.mean(0)
    return v / (np.linalg.norm(v) + 1e-9)


def _centroider(X, etiketter):
    c = np.array([X[etiketter == g].mean(0) for g in sorted(set(etiketter.tolist()))])
    return c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-9)


def etikett_per_ord(ord_lista, starter, X, centroider, marginal=None):
    """Varje ord far den grupp som fonstren runt ordets mitt liknar mest. Fonster vars mitt ligger
    nara ordet vager tyngst, sa att ett talarbyte hamnar mellan ratt ord. marginal (en lista)
    fylls med skillnaden mot nast basta grupp: litet = osakert."""
    starter = np.asarray(starter)
    mitter = starter + FONSTER_S / 2
    ut = []
    for o in ord_lista:
        m = (o[0] + o[1]) / 2
        runt = np.where((starter <= m) & (m <= starter + FONSTER_S))[0]
        if len(runt) == 0:
            runt = np.array([int(np.argmin(np.abs(mitter - m)))])
        if VIKT_SIGMA_S > 0:
            vikt = np.exp(-0.5 * ((mitter[runt] - m) / VIKT_SIGMA_S) ** 2) + 1e-6
        else:
            vikt = np.ones(len(runt))
        poang = (vikt[:, None] * (X[runt] @ centroider.T)).sum(0) / vikt.sum()
        ut.append(int(np.argmax(poang)))
        if marginal is not None:
            topp = np.sort(poang)
            marginal.append(float(topp[-1] - topp[-2]) if len(topp) > 1 else float("inf"))
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


_MENINGSSLUT = re.compile(r"[.?!…][\"'”»)]*$")


def meningar(ord_lista):
    """[(a, b)]: ordindex for meningar. En mening slutar vid . ? ! eller en paus (MENING_PAUS_S)."""
    ut, a = [], 0
    for k in range(1, len(ord_lista) + 1):
        if (k == len(ord_lista) or _MENINGSSLUT.search(ord_lista[k - 1][2].strip())
                or ord_lista[k][0] - ord_lista[k - 1][1] >= MENING_PAUS_S):
            ut.append((a, k))
            a = k
    return ut


def jamna_ut(ord_lista, etiketter):
    """Talaren byter sallan mitt i en mening. Inom en mening far korta avvikande sjok (hogst
    KORT_SJOK ord i rad) samma talare som meningen i ovrigt, om en talare har mer an halften av
    meningens ord. Egna meningar ("Ja, ja.") och langre avvikelser rors inte.

    Varfor: ordtiderna ar ungefarliga (whisper.cpp:s kan hamna en sekund fel), och ett skratt eller
    "mm" fran nagon annan kan ta over ett ord. Da hamnade enstaka ord mitt i en mening hos fel
    person, och en tredjedel av replikerna i ett riktigt mote blev 1-3 ord. Svagheten: saknar
    whisper skiljetecken vid ett talarbyte kan ett kort svar ("Nej, precis.") hamna hos den andra.
    """
    et = list(etiketter)
    for a, b in meningar(ord_lista):
        if b - a < 2:
            continue
        antal = {}
        for e in et[a:b]:
            antal[e] = antal.get(e, 0) + 1
        storst = max(antal, key=antal.get)
        if antal[storst] * 2 <= b - a:
            continue  # ingen talare har mer an halften: rors inte
        k = a
        while k < b:
            j = k
            while j < b and et[j] == et[k]:
                j += 1
            if et[k] != storst and j - k <= KORT_SJOK:
                et[k:j] = [storst] * (j - k)
            k = j
    return et


def repliker(ord_lista, etiketter, fasta_nummer=False, osakra=None, ord_p=ORD_P):
    """Sla ihop ord i foljd med samma talare till repliker. Talarna numreras fran 1 i den
    ordning de forst sager nagot, eller far etiketten som nummer (fasta_nummer).
    -> [{"start", "end", "speaker", "text"}], och vid behov:
       "osaker_talare": True om minst OSAKER_ANDEL av orden har osaker talare (osakra: bool per ord)
       "osakra_ord": index (i text.split()) for ord som whisper var osaker pa (sannolikhet < ord_p)
    """
    nummer, ut, stat = {}, [], []
    for k, (o, e) in enumerate(zip(ord_lista, etiketter)):
        text = o[2]
        delar = text.split()
        if not delar:
            continue
        nr = int(e) if fasta_nummer else nummer.setdefault(e, len(nummer) + 1)
        if ut and ut[-1]["speaker"] == nr:
            r, s = ut[-1], stat[-1]
            # ett ord utan inledande mellanslag fortsatter foregaende ord ("Hej" + "san.")
            fortsatter = not text[0].isspace() and not r["text"][-1].isspace()
            r["end"] = o[1]
            r["text"] += text
        else:
            r = {"start": o[0], "end": o[1], "speaker": nr, "text": text}
            s = {"ord": 0, "osakra": 0, "osakra_ord": set(), "antal": 0}
            ut.append(r)
            stat.append(s)
            fortsatter = False
        forsta = s["antal"] - 1 if fortsatter else s["antal"]
        s["antal"] += len(delar) - (1 if fortsatter else 0)
        s["ord"] += 1
        if osakra is not None and osakra[k]:
            s["osakra"] += 1
        if len(o) > 3 and o[3] is not None and o[3] < ord_p:
            s["osakra_ord"].update(range(forsta, s["antal"]))
    for r, s in zip(ut, stat):
        r["text"] = " ".join(r["text"].split())
        r["start"] = round(r["start"], 2)
        r["end"] = round(r["end"], 2)
        if osakra is not None and s["osakra"] >= OSAKER_ANDEL * s["ord"]:
            r["osaker_talare"] = True
        if s["osakra_ord"]:
            r["osakra_ord"] = sorted(s["osakra_ord"])
    return ut


# --- hela kedjan ---------------------------------------------------------------------------

def _klustra(samples, ord_lista, antal, framsteg=None, marginal=None):
    """Fonster, avtryck och grupper. -> (etikett per ord 0..k-1, antal_hittade, varning).
    marginal (en lista) fylls med hur saker varje ords grupp ar, se etikett_per_ord."""
    langd = len(samples) / SR
    starter = utan_tysta(samples, fonster_med_tal(ord_lista, langd))
    if antal == 1 or len(starter) < 2:
        if marginal is not None:
            marginal.extend([float("inf")] * len(ord_lista))
        return [0] * len(ord_lista), 1, None

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
    return etikett_per_ord(ord_lista, starter, X, centroider, marginal), hittade, varning


def dela_upp(samples, ord_lista, antal, framsteg=None, ord_p=ORD_P):
    """-> (repliker, antal_hittade, varning eller None).

    samples: float32, 16 kHz mono. ord_lista: [(start, slut, text)] fran whisper.
    antal: int (kant antal) eller None (gissa, som mest AUTO_MAX).
    """
    ord_lista = [o for o in ord_lista if o[2].strip()]
    marginal = []
    etiketter, _, varning = _klustra(samples, ord_lista, antal, framsteg, marginal)
    jamnade = jamna_ut(ord_lista, etiketter)
    # Osaker talare: rosten liknar tva grupper nastan lika, eller meningsregeln flyttade ordet.
    osakra = [m < MARGINAL or j != e for m, e, j in zip(marginal, etiketter, jamnade)]
    rep = repliker(ord_lista, jamnade, osakra=osakra, ord_p=ord_p)
    return rep, len({r["speaker"] for r in rep}), varning


# --- digitala moten: mikrofonen i vanster kanal, motesfliken i hoger -----------------------

def har_tva_kanaler(vanster, hoger):
    """Falskt om filen egentligen ar mono (bada kanalerna lika)."""
    if len(vanster) == 0 or len(vanster) != len(hoger):
        return False
    skillnad = np.sqrt(np.mean((vanster - hoger) ** 2))
    niva = np.sqrt(np.mean(vanster ** 2) + np.mean(hoger ** 2)) + 1e-9
    return skillnad / niva > 0.05


def kanal_per_ord(vanster, hoger, ord_lista, saker_ut=None):
    """True for ord som sags i mikrofonen (du), False for ord fran motet.

    Ett ord avgors av kanalen bara om den ena ar minst fyra ganger sa stark (SAKER_KVOT). Annars
    far ordet samma som narmaste sakra ord. Osakra ar t.ex. svaga ord nar bada kanalerna ar
    nastan tysta, och ord dar nagon i motet later samtidigt som du pratar (ett skratt eller ett
    "mm"). Med kravet dubbelt sa stark blev en tredjedel av replikerna i ett riktigt mote bara
    1-3 ord, nar enstaka ord mitt i en mening hamnade hos fel person. Ett tydligt kort "ja" fran
    motet ar fortfarande sakert och raknas som de andras.
    """
    beslut, saker = [], []
    for a, b, *_ in ord_lista:
        i, j = max(0, int((a - 0.05) * SR)), int((b + 0.05) * SR)
        v = float(np.sqrt(np.mean(vanster[i:j] ** 2))) if j > i else 0.0
        h = float(np.sqrt(np.mean(hoger[i:j] ** 2))) if j > i else 0.0
        beslut.append(v >= h)
        saker.append(max(v, h) >= SAKER_KVOT * (min(v, h) + 1e-6))
    if saker_ut is not None:
        saker_ut.extend(saker)
    sakra = [k for k, ok in enumerate(saker) if ok]
    if not sakra:
        return beslut
    mitter = [(o[0] + o[1]) / 2 for o in ord_lista]
    ut = []
    for k in range(len(ord_lista)):
        if saker[k]:
            ut.append(beslut[k])
        else:
            narmast = min(sakra, key=lambda n: abs(mitter[n] - mitter[k]))
            ut.append(beslut[narmast])
    return ut


def dela_upp_kanaler(vanster, hoger, ord_lista, antal, framsteg=None, ord_p=ORD_P):
    """Digitalt mote. -> (repliker, antal_hittade, varning).

    Talare 1 ar alltid du (mikrofonen). De andra (motesfliken) delas upp som vanligt, men bara
    i hoger kanal. antal raknar med dig: 3 = du och tva till. None = gissa hur manga de andra ar.
    """
    ord_lista = [o for o in ord_lista if o[2].strip()]
    saker = []
    min_rost = kanal_per_ord(vanster, hoger, ord_lista, saker)
    andras_ord = [o for o, du in zip(ord_lista, min_rost) if not du]
    andra = None if antal is None else max(1, antal - 1)
    marginal_andra = []
    etiketter_andra, _, varning = _klustra(hoger, andras_ord, andra, framsteg, marginal_andra)
    if varning and antal:
        hittade = len(set(etiketter_andra))
        varning = (f"Du angav {antal} talare (du och {antal - 1} till), men bland de andra gick bara "
                   f"{hittade} {'röst' if hittade == 1 else 'röster'} att skilja åt.")
    # Numrera de andra fran 2 i den ordning de forst sager nagot.
    nummer, kvar, kvar_marginal = {}, iter(etiketter_andra), iter(marginal_andra)
    etiketter, marginal = [], []
    for du in min_rost:
        if du:
            etiketter.append(1)
            marginal.append(float("inf"))
        else:
            e = next(kvar)
            etiketter.append(nummer.setdefault(e, len(nummer) + 2))
            marginal.append(next(kvar_marginal))
    jamnade = jamna_ut(ord_lista, etiketter)
    # Osaker talare: kanalen avgjorde inte, rosten bland de andra var oklar, eller
    # meningsregeln flyttade ordet.
    osakra = [not s or m < MARGINAL or j != e for s, m, e, j in zip(saker, marginal, etiketter, jamnade)]
    rep = repliker(ord_lista, jamnade, fasta_nummer=True, osakra=osakra, ord_p=ord_p)
    return rep, len({r["speaker"] for r in rep}), varning
