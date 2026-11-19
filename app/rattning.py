"""Rättningar av talare som görs för hand på webbsidan.

En replik är {"start", "end", "speaker", "text"}, och ibland "osaker_talare" (True) och
"osakra_ord" (index i text.split()). Orden räknas som text.split(), samma som på webbsidan.
Ordtiderna sparas inte, så när en replik delas uppskattas tiden för delningen utifrån hur stor
del av texten (antal tecken) som kommer före.

Den del som får en talare för hand är inte längre osäker. Osäkra ord följer med orden.
"""


def _tid_vid(replik, orden, k):
    tecken = [len(o) + 1 for o in orden]
    andel = sum(tecken[:k]) / max(1, sum(tecken))
    return round(replik["start"] + (replik["end"] - replik["start"]) * andel, 2)


def _del(replik, a, b, **andrat):
    """Orden a..b (b räknas inte med) av en replik, med osäkra ord flyttade till sina nya index."""
    ny = {**replik, **andrat}
    ny.pop("osakra_ord", None)
    osakra = [i - a for i in replik.get("osakra_ord", []) if a <= i < b]
    if osakra:
        ny["osakra_ord"] = osakra
    return ny


def sla_ihop_grannar(segment):
    """Repliker i följd med samma talare blir en. Den blir osäker bara om båda var det."""
    ut = []
    for s in segment:
        if ut and "speaker" in s and ut[-1].get("speaker") == s["speaker"]:
            forra = ut[-1]
            forskjutning = len(forra["text"].split())
            ny = {**forra, "end": s["end"], "text": f"{forra['text']} {s['text']}"}
            osakra = forra.get("osakra_ord", []) + [i + forskjutning for i in s.get("osakra_ord", [])]
            ny.pop("osakra_ord", None)
            if osakra:
                ny["osakra_ord"] = osakra
            if not (forra.get("osaker_talare") and s.get("osaker_talare")):
                ny.pop("osaker_talare", None)
            ut[-1] = ny
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
        delar.append(_del(replik, 0, fran, end=a, text=" ".join(orden[:fran])))
    vald = _del(replik, fran, till, start=a, end=b, speaker=talare, text=" ".join(orden[fran:till]))
    vald.pop("osaker_talare", None)  # bestämd för hand
    delar.append(vald)
    if till < len(orden):
        delar.append(_del(replik, till, len(orden), start=b, text=" ".join(orden[till:])))
    return sla_ihop_grannar(segment[:index] + delar + segment[index + 1:])


def sla_ihop_talare(segment, fran, till):
    """Alla repliker från talare fran får talare till."""
    return sla_ihop_grannar([{**s, "speaker": till} if s.get("speaker") == fran else dict(s) for s in segment])


def nytt_nummer(segment, namn):
    """Ett talarnummer som inte används, varken i texten eller bland namnen."""
    anvanda = {s["speaker"] for s in segment if "speaker" in s} | {int(k) for k in (namn or {}) if k.isdigit()}
    return max(anvanda, default=0) + 1
