"""Rättningar av talare som görs för hand på webbsidan.

En replik är {"start", "end", "speaker", "text"}. Orden räknas som text.split(), samma som på
webbsidan. Ordtiderna sparas inte, så när en replik delas uppskattas tiden för delningen utifrån
hur stor del av texten (antal tecken) som kommer före.
"""


def _tid_vid(replik, orden, k):
    tecken = [len(o) + 1 for o in orden]
    andel = sum(tecken[:k]) / max(1, sum(tecken))
    return round(replik["start"] + (replik["end"] - replik["start"]) * andel, 2)


def sla_ihop_grannar(segment):
    """Repliker i följd med samma talare blir en."""
    ut = []
    for s in segment:
        if ut and "speaker" in s and ut[-1].get("speaker") == s["speaker"]:
            ut[-1] = {**ut[-1], "end": s["end"], "text": f"{ut[-1]['text']} {s['text']}"}
        else:
            ut.append(dict(s))
    return ut


def byt_talare(segment, index, talare, fran=None, till=None):
    """Orden fran..till (till räknas inte med) i replik index får talare. Utan fran och till:
    hela repliken. Repliken delas vid behov, och grannar med samma talare slås ihop."""
    if not 0 <= index < len(segment) or "speaker" not in segment[index]:
        raise ValueError("repliken finns inte")
    replik = segment[index]
    orden = replik["text"].split()
    fran = 0 if fran is None else fran
    till = len(orden) if till is None else till
    if not 0 <= fran < till <= len(orden):
        raise ValueError("orden finns inte i repliken")
    a, b = _tid_vid(replik, orden, fran), _tid_vid(replik, orden, till)
    delar = []
    if fran > 0:
        delar.append({**replik, "end": a, "text": " ".join(orden[:fran])})
    delar.append({**replik, "start": a, "end": b, "speaker": talare, "text": " ".join(orden[fran:till])})
    if till < len(orden):
        delar.append({**replik, "start": b, "text": " ".join(orden[till:])})
    return sla_ihop_grannar(segment[:index] + delar + segment[index + 1:])


def sla_ihop_talare(segment, fran, till):
    """Alla repliker från talare fran får talare till."""
    return sla_ihop_grannar([{**s, "speaker": till} if s.get("speaker") == fran else dict(s) for s in segment])


def nytt_nummer(segment, namn):
    """Ett talarnummer som inte används, varken i texten eller bland namnen."""
    anvanda = {s["speaker"] for s in segment if "speaker" in s} | {int(k) for k in (namn or {}) if k.isdigit()}
    return max(anvanda, default=0) + 1
