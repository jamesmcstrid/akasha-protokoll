"""Skriver SHA256SUMS.txt i samma format som sha256sum: summan, tva mellanslag och filnamnet (utan katalog).

    python paketering/kontrollsummor.py UT_FIL FIL [FIL ...]

Filer som saknas hoppas over med ett tydligt FEL: (slutkod 1) men de andra far sin summa. Hela filen skrivs ocksa ut,
sa att summorna syns i jobbloggen.
"""
import hashlib
import os
import sys

import kontroll_hjalp


def sha256_av(sokvag):
    h = hashlib.sha256()
    with open(sokvag, "rb") as f:
        for bit in iter(lambda: f.read(1 << 20), b""):
            h.update(bit)
    return h.hexdigest()


def rader(filer):
    """-> (rader i sha256sum-format, lista over filer som saknas)."""
    ut, saknas = [], []
    for f in filer:
        if os.path.isfile(f):
            ut.append(f"{sha256_av(f)}  {os.path.basename(f)}")
        else:
            saknas.append(f)
    return ut, saknas


def main(argv=None):
    kontroll_hjalp.utf8_utskrift()
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(__doc__)
        return 2
    utfil, filer = argv[0], argv[1:]
    res = kontroll_hjalp.Resultat("KONTROLLSUMMOR")
    ut, saknas = rader(filer)
    for f in saknas:
        res.fel(f"{f} finns inte: ingen kontrollsumma")
    if ut:
        with open(utfil, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(ut) + "\n")
        res.ok(f"{utfil} skriven med {len(ut)} kontrollsummor")
        print("\n".join(ut))
    return res.sammanfatta()


if __name__ == "__main__":
    sys.exit(main())
