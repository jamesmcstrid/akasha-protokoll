"""Sammanfattning av en transkribering utan själva texten: tider, talare och tecken på fel.

Utskriften innehåller inga ord ur mötet och inga namn, så den går att visa för någon annan.

    bash halsokoll/sammanfatta.sh            # senaste färdiga inspelningen
    bash halsokoll/sammanfatta.sh <id>       # en viss inspelning (id står i listan överst)
"""
import collections
import math
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
from installningar import DATAKATALOG  # noqa: E402


def tid(s):
    s = int(round(s or 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def fastnat(ord_):
    """Samma ord eller fras många gånger i rad, som när whisper fastnar i en slinga."""
    for n in range(1, 9):
        for i in range(len(ord_) - n):
            k = 1
            while ord_[i + k * n:i + (k + 1) * n] == ord_[i:i + n]:
                k += 1
            if k >= (5 if n <= 2 else 4):
                return True
    return False


def main():
    alla = []
    for f in sorted(glob.glob(os.path.join(DATAKATALOG, "*.json"))):
        try:
            with open(f, encoding="utf-8") as fil:
                alla.append(json.load(fil))
        except (OSError, ValueError):
            pass
    print("Senaste inspelningar:")
    for m in alla[-5:]:
        langd = (m.get("resultat") or {}).get("langd_s")
        print(f"  {m['id']}  {m.get('status', ''):12} {tid(langd):>8}  {m.get('andelse', '')}")
    if len(sys.argv) > 1:
        val = [m for m in alla if m["id"] == sys.argv[1]]
    else:
        val = [m for m in alla if m.get("status") in ("klar", "fel")]
    if not val:
        sys.exit("Hittade ingen färdig inspelning.")
    pagar = [m["id"] for m in alla if m.get("status") not in ("klar", "fel")]
    if pagar:
        print(f"\nOBS: {', '.join(pagar)} är inte klar än. Kör igen när den står som klar i listan.")

    m = val[-1]
    r = m.get("resultat") or {}
    seg = r.get("segment") or []
    langd = r.get("langd_s") or 0
    t = r.get("tid_s") or {}
    inst = m.get("installningar") or {}
    print(f"\nInspelning {m['id']} ({m.get('andelse', '')}), status {m.get('status')}")
    if m.get("fel"):
        print("  Fel:", m["fel"])
    print(f"  Längd {tid(langd)}, motor: {r.get('motor')}")
    print(f"  Inställningar: talare={inst.get('talare')}, källa={inst.get('kalla')}, "
          f"ordlista={'ja' if inst.get('ord') else 'nej'}, namn ifyllda={len(m.get('namn') or {})}")
    if langd and t:
        totalt = sum(t.values())
        print(f"  Tid: transkribering {tid(t.get('transkribering'))}, talare {tid(t.get('talare'))}, "
              f"totalt {tid(totalt)} = {totalt / langd * 60:.1f} min per timme möte")
    print(f"  Talare hittade: {r.get('talare')}" + (f"   VARNING: {r['varning']}" if r.get("varning") else ""))
    if not seg:
        return

    per = collections.defaultdict(lambda: [0, 0, 0.0])  # repliker, ord, sekunder
    for s in seg:
        p = per[s["speaker"]]
        p[0] += 1
        p[1] += len(s["text"].split())
        p[2] += s["end"] - s["start"]
    taltid = sum(p[2] for p in per.values()) or 1
    print(f"\n  {len(seg)} repliker, {sum(p[1] for p in per.values())} ord, "
          f"{len(seg) / (langd / 60 or 1):.1f} talarbyten per minut")
    for nr in sorted(per):
        p = per[nr]
        print(f"    Talare {nr}: {p[0]:4} repliker {p[1]:6} ord  {p[2] / taltid * 100:4.0f} % av taltiden")
    korta = sum(1 for s in seg if s["end"] - s["start"] < 1.0)
    print(f"  Korta repliker (<1 s): {korta}   längsta replik: {tid(max(s['end'] - s['start'] for s in seg))}")
    luckor = sorted(((b["start"] - a["end"], a["end"]) for a, b in zip(seg, seg[1:])
                     if b["start"] - a["end"] >= 10), reverse=True)[:5]
    print("  Tystnader utan text över 10 s: " + (", ".join(f"{g:.0f} s vid {tid(v)}" for g, v in luckor) or "inga"))
    upprepade = [s for s in seg if fastnat(s["text"].lower().split())]
    dubbletter = [k for k, n in collections.Counter(
        " ".join(s["text"].lower().split()) for s in seg if len(s["text"].split()) >= 3).items() if n >= 3]
    print(f"  Ser ut som att whisper har fastnat: {len(upprepade)} repliker med samma ord om och om igen"
          + (" (vid " + ", ".join(tid(s["start"]) for s in upprepade[:8]) + ")" if upprepade else "")
          + f", {len(dubbletter)} likadana repliker (3+ ord) som förekommer 3+ gånger")

    blk = 300 if langd <= 3600 else 600
    print(f"\n  Per {blk // 60} minuter (ord, och andel per talare):")
    for b0 in range(0, max(1, math.ceil(langd)), blk):
        ord_per_talare = collections.Counter()
        for s in seg:
            # Orden fordelas jamnt over repliken, sa att en lang replik raknas i alla block den
            # gar over och inte bara i det dar den borjar.
            orden = len(s["text"].split())
            steg = (s["end"] - s["start"]) / max(1, orden)
            for i in range(orden):
                if b0 <= s["start"] + (i + 0.5) * steg < b0 + blk:
                    ord_per_talare[s["speaker"]] += 1
        n = sum(ord_per_talare.values())
        andelar = "  ".join(f"T{k} {v / n * 100:.0f}%" for k, v in sorted(ord_per_talare.items())) if n else ""
        print(f"    {tid(b0):>7}–{tid(min(b0 + blk, langd)):<7} {n:5} ord  {andelar}")


if __name__ == "__main__":
    main()
