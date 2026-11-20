"""Avkodningen med PyAV (ljud.py): langder, stereo, jamforelse med faster-whisper och att motorn inte drar in det."""
import hjalp  # noqa: F401  (maste importeras forst)

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

import ljud

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
LJUD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testljud")
LANGDER = {"en-talare.m4a": 414_720, "tva-talare.m4a": 916_480, "digitalt-mote.webm": 1_272_640}
FASTER = importlib.util.find_spec("faster_whisper") is not None


class TestAvkoda(unittest.TestCase):
    def test_langd_och_omfang(self):
        for namn, langd in LANGDER.items():
            with self.subTest(namn):
                x = ljud.avkoda(os.path.join(LJUD, namn))
                self.assertEqual(x.dtype, np.float32)
                self.assertAlmostEqual(len(x), langd, delta=160)
                self.assertLessEqual(float(np.abs(x).max()), 1.0)

    def test_stereo(self):
        vanster, hoger = ljud.avkoda(os.path.join(LJUD, "digitalt-mote.webm"), stereo=True)
        self.assertEqual(len(vanster), len(hoger))
        self.assertGreater(len(vanster), 0)
        vanster, hoger = ljud.avkoda(os.path.join(LJUD, "en-talare.m4a"), stereo=True)
        self.assertTrue(np.array_equal(vanster, hoger))

    @unittest.skipUnless(FASTER, "faster-whisper finns inte")
    def test_samma_som_faster_whisper(self):
        from faster_whisper.audio import decode_audio

        for namn in LANGDER:
            sokvag = os.path.join(LJUD, namn)
            with self.subTest(namn, stereo=False):
                self.assertTrue(np.array_equal(ljud.avkoda(sokvag), decode_audio(sokvag, sampling_rate=ljud.SR)))
            with self.subTest(namn, stereo=True):
                egna = ljud.avkoda(sokvag, stereo=True)
                deras = decode_audio(sokvag, sampling_rate=ljud.SR, split_stereo=True)
                self.assertTrue(np.array_equal(egna[0], deras[0]) and np.array_equal(egna[1], deras[1]))

    def test_fil_som_inte_ar_ljud(self):
        katalog = tempfile.mkdtemp(prefix="akasha-ljud-")
        self.addCleanup(shutil.rmtree, katalog, True)
        fil = os.path.join(katalog, "inte-ljud.wav")
        with open(fil, "wb") as f:
            f.write(b"inte ljud")
        with self.assertRaises(Exception):
            ljud.avkoda(fil)


class TestInteFasterWhisper(unittest.TestCase):
    def test_app_drar_inte_in_faster_whisper(self):
        kod = (
            "import sys; sys.path.insert(0, %r); import app; "
            "print(sorted(m for m in ('faster_whisper', 'ctranslate2', 'onnxruntime', 'tokenizers') if m in sys.modules))"
        ) % APP
        svar = subprocess.run([sys.executable, "-c", kod], env=dict(os.environ), capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(svar.stdout.strip(), "[]", svar.stderr)


if __name__ == "__main__":
    unittest.main()
