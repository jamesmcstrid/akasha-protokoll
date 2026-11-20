"""Beviset mot riktiga Hugging Face: ett avbrott och en fortsattning av rostmodellen (40 MB).

Kor bara for hand, eftersom det kraver natet:
    AKASHA_RIKTIG_HAMTNING=1 venv/bin/python -m unittest discover -s tester -p test_riktig_hamtning.py -v
Hamtar aldrig taligenkanningen (1,5 GB).
"""
import hashlib
import os
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import urlparse

import hjalp  # noqa: F401  (satter sokvagen till app/)

import modeller


@unittest.skipUnless(os.environ.get("AKASHA_RIKTIG_HAMTNING") == "1", "nar natet: satt AKASHA_RIKTIG_HAMTNING=1")
class TestRiktigHamtning(unittest.TestCase):
    def test_avbrott_och_fortsattning(self):
        with tempfile.TemporaryDirectory(prefix="akasha-protokoll-riktig-") as katalog, \
                mock.patch.object(modeller, "MODELLKATALOG", katalog):
            fil = modeller.PAKET["talare"][0]  # det riktiga manifestet
            logg = []  # (status, varde, Range) for varje svar, ocksa omdirigeringarna
            s = modeller.ny_session()
            s.hooks["response"].append(lambda r, *a, **k: logg.append(
                (r.status_code, urlparse(r.url).hostname, r.request.headers.get("Range"))))

            avbryt = threading.Event()

            def framsteg(fas, byte):
                if byte > 5_000_000:
                    avbryt.set()

            with self.assertRaises(modeller.HamtFel) as ctx:
                modeller.hamta_fil(fil, s, framsteg=framsteg, avbryt=avbryt)
            self.assertEqual(ctx.exception.kod, "avbruten")
            delvis = fil.sokvag() + ".delvis"
            n = os.path.getsize(delvis)
            self.assertGreater(n, 5_000_000)
            self.assertLess(n, fil.storlek)
            self.assertFalse(os.path.exists(fil.sokvag()))

            logg.clear()
            self.assertEqual(modeller.hamta_fil(fil, s), "hamtad")
            statusar = [(st, varde) for st, varde, _ in logg]
            self.assertEqual(statusar[0], (302, "huggingface.co"), logg)
            fortsatt = [(st, varde, rang) for st, varde, rang in logg if st == 206]
            self.assertEqual(len(fortsatt), 1, logg)
            st, varde, rang = fortsatt[0]
            self.assertNotEqual(varde, "huggingface.co")
            self.assertEqual(rang, f"bytes={n}-")

            sha = hashlib.sha256()
            with open(fil.sokvag(), "rb") as f:
                for bit in iter(lambda: f.read(1 << 20), b""):
                    sha.update(bit)
            self.assertEqual(sha.hexdigest(), fil.sha256)
            self.assertFalse(os.path.exists(delvis))


if __name__ == "__main__":
    unittest.main()
