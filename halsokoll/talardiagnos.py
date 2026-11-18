"""Varför blev det så många talare? Räknar om röstavtrycken för en inspelning och visar hur
lika grupperna är, innan något slås ihop. Ändrar ingenting och skriver inte ut någon text.

    bash halsokoll/talardiagnos.sh                 # senaste färdiga inspelningen
    bash halsokoll/talardiagnos.sh <id> [grupper]  # en viss inspelning, och antal grupper

Antal grupper är som standard det antal talare som angavs (5 om "Vet inte" valdes).
Tar runt en minut för ett möte på en timme.
"""
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import numpy as np  # noqa: E402

import motor  # noqa: E402
import talare  # noqa: E402
from installningar import DATAKATALOG, TALARE_TROSKEL  # noqa: E402
from talare import FONSTER_S, SR, STEG_S  # noqa: E402

TROSKLAR = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8)


def hamta(id_):
    filer = [os.path.join(DATAKATALOG, id_ + ".json")] if id_ else sorted(glob.glob(os.path.join(DATAKATALOG, "*.json")))
    for f in reversed(filer):
        with open(f, encoding="utf-8") as fil:
            meta = json.load(fil)
        if (meta.get("resultat") or {}).get("segment"):
            return meta
    sys.exit("Hittade ingen färdig inspelning med text.")


def main():
    meta = hamta(sys.argv[1] if len(sys.argv) > 1 else None)
    angivet = str((meta.get("installningar") or {}).get("talare", ""))
    k = int(sys.argv[2]) if len(sys.argv) > 2 else (int(angivet) if angivet.isdigit() and int(angivet) > 1 else 5)
    seg = meta["resultat"]["segment"]
    print(f"Inspelning {meta['id']}, {k} grupper")

    t0 = time.time()
    samples = motor.avkoda(os.path.join(DATAKATALOG, meta["id"] + meta["andelse"]))
    # Replikerna anger var det pratas (ordtiderna sparas inte).
    starter = talare.utan_tysta(samples, talare.fonster_med_tal(
        [(s["start"], s["end"], "x") for s in seg], len(samples) / SR))
    print(f"{len(starter)} fönster med tal, räknar röstavtryck …", flush=True)
    extraktor = talare._hamta_extraktor()
    X = np.array([talare._avtryck(extraktor, samples[int(a * SR):int((a + FONSTER_S) * SR)]) for a in starter])
    etiketter, c = talare.kmeans(X, k)
    namn = "ABCDEFGHIJ"[:k]
    print(f"klart på {time.time() - t0:.0f} s\n")

    def talare_i_texten(start):
        mitt = start + FONSTER_S / 2
        return next((s["speaker"] for s in seg if s["start"] <= mitt <= s["end"]), 0)

    i_texten = np.array([talare_i_texten(a) for a in starter])
    talarna = sorted(set(i_texten.tolist()) - {0})
    print(f"Uppdelat i {k} grupper (före sammanslagning). Tid per grupp, och var gruppens fönster hamnade i texten:")
    for g in range(k):
        v = etiketter == g
        fordelning = "  ".join(f"T{t} {np.mean(i_texten[v] == t) * 100:3.0f}%" for t in talarna)
        print(f"  {namn[g]}: {v.sum() * STEG_S / 60:5.1f} min   {fordelning}")

    likhet = c @ c.T
    print(f"\nLikhet mellan grupperna (1 = samma röst). Gränsen för samma person är {TALARE_TROSKEL}:")
    print("      " + "".join(f"{g:>6}" for g in namn))
    for i in range(k):
        print(f"  {namn[i]}   " + "".join("     -" if i == j else f"{likhet[i, j]:6.2f}" for j in range(k)))

    print("\nAntal talare med olika gräns (TALARE_TROSKEL):")
    for troskel in TROSKLAR:
        _, cc = talare.sla_ihop_lika(X, etiketter, troskel)
        print(f"  {troskel:.2f}: {len(cc)} talare" + ("   <- nu" if abs(troskel - TALARE_TROSKEL) < 1e-9 else ""))

    blk = 600
    langd = len(samples) / SR
    starter = np.array(starter)
    print(f"\nNär grupperna pratar (minuter tal per {blk // 60}-minutersblock):")
    print("  block    " + "".join(f"{g:>6}" for g in namn))
    for b0 in range(0, int(langd) + 1, blk):
        v = (starter >= b0) & (starter < b0 + blk)
        print(f"  {b0 // 60:3}–{min(b0 + blk, langd) // 60:3.0f}  "
              + "".join(f"{np.sum(etiketter[v] == g) * STEG_S / 60:6.1f}" for g in range(k)))


if __name__ == "__main__":
    main()
