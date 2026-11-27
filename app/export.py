"""Transkriberingen som Markdown eller ren text. Talarna far de namn som angetts i webbsidan."""
from datetime import datetime

import installningar

LANK_REPO = "https://github.com/jamesmcstrid/akasha-protokoll"
LANK_HAMTA = LANK_REPO + "/releases/latest"

VARNING_KONTROLL = "Transkriberat lokalt med KB-Whisper. Kontrollera mot ljudet innan texten används."


def varning_kontroll(meta):
    """Raden overst i texten, med den motor som faktiskt anvandes (resultat.motor). Aldre inspelningar
    saknar den uppgiften: da galler KB-Whisper, som var den enda motorn."""
    motor = ((meta.get("resultat") or {}).get("motor") or "").split(" (")[0].strip()
    if not motor or motor.startswith("KB-Whisper"):
        return VARNING_KONTROLL
    return f"Transkriberat lokalt med {motor}. Kontrollera mot ljudet innan texten används."


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


def info_delar(meta):
    """Datum, langd och antal talare som en lista (sidan satter egna mellanrum)."""
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
    return delar


def info(meta):
    return " · ".join(info_delar(meta))


def _rader(meta):
    """-> [(tid_s, namn eller None, text)]"""
    res = meta.get("resultat") or {}
    ut = []
    for s in res.get("segment", []):
        namn = talarnamn(meta, s["speaker"]) if "speaker" in s else None
        ut.append((s["start"], namn, s["text"]))
    return ut


def _med_signatur(signatur):
    """None: installningen SIGNATUR avgor. Sant/falskt: tvingar fram eller tar bort signaturen."""
    return installningar.SIGNATUR == "pa" if signatur is None else bool(signatur)


def som_markdown(meta, signatur=None):
    res = meta.get("resultat") or {}
    delar = [f"# {rubrik(meta)}", "", info(meta), "", f"_{varning_kontroll(meta)}_", ""]
    if res.get("varning"):
        delar += [f"**Obs:** {res['varning']}", ""]
    for start, namn, text in _rader(meta):
        if namn:
            delar += [f"**{namn}** ({tid(start)}): {text}", ""]
        else:
            delar += [f"({tid(start)}) {text}", ""]
    if _med_signatur(signatur):
        delar += ["---", "",
                  f"_Transkriberat med [Akasha Protokoll]({LANK_REPO}), lokalt på den egna datorn. "
                  f"Vill du testa själv? [Ladda ner här]({LANK_HAMTA})._"]
    return "\n".join(delar).rstrip() + "\n"


def som_text(meta, signatur=None):
    res = meta.get("resultat") or {}
    delar = [rubrik(meta), info(meta), varning_kontroll(meta), ""]
    if res.get("varning"):
        delar += [f"Obs: {res['varning']}", ""]
    for start, namn, text in _rader(meta):
        delar += [f"[{tid(start)}] {namn}: {text}" if namn else f"[{tid(start)}] {text}", ""]
    if _med_signatur(signatur):
        delar += ["Transkriberat med Akasha Protokoll, lokalt på den egna datorn.",
                  f"Vill du testa själv? {LANK_HAMTA}"]
    return "\n".join(delar).rstrip() + "\n"
