"""Jämför två transkriberingar av samma möte: samma ljud med olika modeller, eller samma möte
inspelat med två olika enheter (till exempel datorn och en telefon).

    bash halsokoll/jamfor.sh <id A> <id B>

Utskriften innehåller inga ord ur mötet och går att visa för någon annan: hur stor andel av orden
som skiljer, var i mötet, om talarna stämmer överens och hur mycket inspelningarna är förskjutna.
Skillnaderna med text sparas i en fil i jamforelser/ i inspelningsmappen, för att läsas på datorn.

Att två transkriberingar stämmer överens betyder inte att de är rätt (samma modell gör samma
fel på namn och facktermer), men där de skiljer sig har minst en av dem hört fel.
"""
import difflib
import itertools
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
from installningar import DATAKATALOG  # noqa: E402

BLOCK_S = 600
SAMMANHANG = 5  # ord före och efter en skillnad i filen


def tid(s):
    s = int(round(max(0, s or 0)))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def las(id_):
    try:
        with open(os.path.join(DATAKATALOG, id_ + ".json"), encoding="utf-8") as f:
            meta = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Hittade ingen inspelning {id_} i {DATAKATALOG}.")
    if not (meta.get("resultat") or {}).get("segment"):
        sys.exit(f"{id_} har ingen text än (status {meta.get('status')}).")
    return meta


def ord_med_tider(meta):
    """[(normerat ord, ord som det står, tid, talare)]. Tiden fördelas jämnt över repliken."""
    ut = []
    for s in meta["resultat"]["segment"]:
        orden = s["text"].split()
        steg = (s["end"] - s["start"]) / max(1, len(orden))
        for i, o in enumerate(orden):
            normerat = re.sub(r"[^\w]", "", o.lower())
            if normerat:
                ut.append((normerat, o, s["start"] + (i + 0.5) * steg, s["speaker"]))
    return ut


def basta_parning(par):
    """Talare i A -> talare i B som ger flest ord med samma talare. -> (karta, antal)."""
    a_talare = sorted({a for a, _ in par})
    b_talare = sorted({b for _, b in par})
    raknare = {}
    for p in par:
        raknare[p] = raknare.get(p, 0) + 1
    basta = ({}, 0)
    if len(a_talare) <= len(b_talare):
        for perm in itertools.permutations(b_talare, len(a_talare)):
            karta = dict(zip(a_talare, perm))
            n = sum(raknare.get((a, b), 0) for a, b in karta.items())
            if n > basta[1]:
                basta = (karta, n)
    else:
        for perm in itertools.permutations(a_talare, len(b_talare)):
            karta = dict(zip(perm, b_talare))
            n = sum(raknare.get((a, b), 0) for a, b in karta.items())
            if n > basta[1]:
                basta = (karta, n)
    return basta


def main():
    if len(sys.argv) != 3:
        sys.exit("Ange två inspelningar: bash halsokoll/jamfor.sh <id A> <id B>")
    a_meta, b_meta = las(sys.argv[1]), las(sys.argv[2])
    a, b = ord_med_tider(a_meta), ord_med_tider(b_meta)
    for namn, m, o in (("A", a_meta, a), ("B", b_meta, b)):
        r = m["resultat"]
        print(f"{namn}: {m['id']}  {tid(r.get('langd_s'))}  {r.get('motor')}  "
              f"{len(o)} ord, {r.get('talare')} talare")

    matcher = difflib.SequenceMatcher(None, [w[0] for w in a], [w[0] for w in b], autojunk=False)
    opkoder = matcher.get_opcodes()
    lika = [(i, j) for tag, i1, i2, j1, j2 in opkoder if tag == "equal"
            for i, j in zip(range(i1, i2), range(j1, j2))]
    if len(lika) < 20:
        sys.exit("\nTexterna liknar inte varandra. Är det verkligen samma möte?")

    # Förskjutning: B:s tid som funktion av A:s (rak linje, så att klockor som går olika syns).
    ta = [a[i][2] for i, _ in lika]
    tb = [b[j][2] for _, j in lika]
    n = len(ta)
    ma, mb = sum(ta) / n, sum(tb) / n
    varians = sum((x - ma) ** 2 for x in ta)
    lutning = sum((x - ma) * (y - mb) for x, y in zip(ta, tb)) / varians if varians else 1.0
    forskjutning = mb - lutning * ma
    slut = a_meta["resultat"].get("langd_s") or ta[-1]
    print(f"\nFörskjutning: B ligger {forskjutning:+.1f} s från A i början och "
          f"{forskjutning + (lutning - 1) * slut:+.1f} s i slutet (ungefärligt, utifrån orden)")

    # Andel ord som skiljer, räknat som ordfel med A som facit.
    def skillnad(op):
        return sum((i2 - i1) if tag in ("replace", "delete") else (j2 - j1) if tag == "insert" else 0
                   for tag, i1, i2, j1, j2 in op)
    print(f"\nOrd som skiljer: {skillnad(opkoder) / len(a):.1%} (räknat som ordfel med A som facit)")
    print(f"  bara i A: {sum(i2 - i1 for t, i1, i2, _, _ in opkoder if t in ('delete', 'replace'))} ord, "
          f"bara i B: {sum(j2 - j1 for t, _, _, j1, j2 in opkoder if t in ('insert', 'replace'))} ord")

    karta, samma = basta_parning([(a[i][3], b[j][3]) for i, j in lika])
    print(f"\nTalare: {samma / len(lika):.1%} av de gemensamma orden har samma talare i båda")
    for ta_ in sorted({a[i][3] for i, _ in lika}):
        egna = [b[j][3] for i, j in lika if a[i][3] == ta_]
        fordelning = "  ".join(f"B:T{tb_} {egna.count(tb_) / len(egna) * 100:3.0f}%"
                               for tb_ in sorted(set(egna)) if egna.count(tb_) / len(egna) >= 0.02)
        print(f"  A:T{ta_} ({len(egna):5} ord) -> {fordelning}"
              + (f"   (motsvarar B:T{karta[ta_]})" if ta_ in karta else ""))

    print(f"\nPer {BLOCK_S // 60} minuter (tid i A):")
    print("  block            ord   skiljer  samma talare   B-A (s)")
    for b0 in range(0, int(slut) + 1, BLOCK_S):
        inom = [op for op in opkoder if op[1] < len(a) and b0 <= a[min(op[1], len(a) - 1)][2] < b0 + BLOCK_S]
        antal = sum(1 for w in a if b0 <= w[2] < b0 + BLOCK_S)
        par = [(i, j) for i, j in lika if b0 <= a[i][2] < b0 + BLOCK_S]
        talare_lika = sum(1 for i, j in par if karta.get(a[i][3]) == b[j][3])
        # Tidsskillnad for samma ord (median). Ska vara ungefar lika i alla block; ett hopp betyder
        # att den ena transkriberingens tider har hamnat fel i det blocket.
        diff = sorted(b[j][2] - a[i][2] for i, j in par)
        median = f"{diff[len(diff) // 2]:+9.1f}" if diff else "        -"
        if antal:
            print(f"  {tid(b0):>7}–{tid(min(b0 + BLOCK_S, slut)):<7} {antal:6} {skillnad(inom) / antal:8.1%}"
                  f"  {talare_lika / max(1, len(par)):11.1%} {median}")

    katalog = os.path.join(DATAKATALOG, "jamforelser")
    os.makedirs(katalog, mode=0o700, exist_ok=True)
    fil = os.path.join(katalog, f"{a_meta['id']}--{b_meta['id']}.md")
    with open(fil, "w", encoding="utf-8") as f:
        f.write(f"# Skillnader mellan {a_meta['id']} (A) och {b_meta['id']} (B)\n\n"
                f"A: {a_meta['resultat'].get('motor')}  \nB: {b_meta['resultat'].get('motor')}\n\n"
                "Tiden är A:s. Fetstil är det som skiljer. Lyssna på stället för att avgöra vem som har rätt.\n\n")
        for tag, i1, i2, j1, j2 in opkoder:
            if tag == "equal":
                continue
            fore = " ".join(w[1] for w in a[max(0, i1 - SAMMANHANG):i1])
            efter = " ".join(w[1] for w in a[i2:i2 + SAMMANHANG])
            a_text = " ".join(w[1] for w in a[i1:i2]) or "–"
            b_text = " ".join(w[1] for w in b[j1:j2]) or "–"
            f.write(f"- **{tid(a[min(i1, len(a) - 1)][2])}** …{fore} **A: {a_text}** / **B: {b_text}** {efter}…\n")
    print(f"\nSkillnaderna med text: {fil}")
    print("(Filen innehåller mötets text. Läs den på datorn.)")


if __name__ == "__main__":
    main()
