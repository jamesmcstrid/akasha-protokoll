"""Transkriberingen som Markdown eller ren text. Talarna far de namn som angetts i webbsidan."""
from datetime import datetime

VARNING_KONTROLL = "Transkriberat lokalt med KB-Whisper. Kontrollera mot ljudet innan texten används."


def tid(sekunder):
    s = int(round(sekunder or 0))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def talarnamn(meta, nr):
    namn = (meta.get("namn") or {}).get(str(nr), "").strip()
    return namn or f"Talare {nr}"


def rubrik(meta):
    if meta.get("titel"):
        return meta["titel"]
    try:
        return "Möte " + datetime.fromisoformat(meta["skapad"]).strftime("%Y-%m-%d %H:%M")
    except (KeyError, ValueError):
        return "Möte"


def info(meta):
    res = meta.get("resultat") or {}
    delar = []
    try:
        delar.append(datetime.fromisoformat(meta["skapad"]).strftime("%Y-%m-%d %H:%M"))
    except (KeyError, ValueError):
        pass
    if res.get("langd_s"):
        delar.append(tid(res["langd_s"]))
    if res.get("talare"):
        delar.append(f"{res['talare']} talare")
    return " · ".join(delar)


def _rader(meta):
    """-> [(tid_s, namn eller None, text)]"""
    res = meta.get("resultat") or {}
    ut = []
    for s in res.get("segment", []):
        namn = talarnamn(meta, s["speaker"]) if "speaker" in s else None
        ut.append((s["start"], namn, s["text"]))
    return ut


def som_markdown(meta):
    res = meta.get("resultat") or {}
    delar = [f"# {rubrik(meta)}", "", info(meta), "", f"_{VARNING_KONTROLL}_", ""]
    if res.get("varning"):
        delar += [f"**Obs:** {res['varning']}", ""]
    for start, namn, text in _rader(meta):
        if namn:
            delar += [f"**{namn}** ({tid(start)}): {text}", ""]
        else:
            delar += [f"({tid(start)}) {text}", ""]
    return "\n".join(delar).rstrip() + "\n"


def som_text(meta):
    res = meta.get("resultat") or {}
    delar = [rubrik(meta), info(meta), VARNING_KONTROLL, ""]
    if res.get("varning"):
        delar += [f"Obs: {res['varning']}", ""]
    for start, namn, text in _rader(meta):
        delar += [f"[{tid(start)}] {namn}: {text}" if namn else f"[{tid(start)}] {text}", ""]
    return "\n".join(delar).rstrip() + "\n"
