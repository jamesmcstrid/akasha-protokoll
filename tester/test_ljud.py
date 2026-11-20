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
FORMAT = os.path.join(LJUD, "format")
# Exakta langder i sampel vid 16 kHz mono (uppmatta med dagens GPL-bygge av FFmpeg och med det egna LGPL-bygget: lika).
FORMATLANGDER = {"aac-safari.mp4": 81920, "aac.aac": 81920, "aac.mov": 81920, "adpcm.wav": 81640, "alac.m4a": 80000,
                 "flac.flac": 80000, "mp3.mp3": 80000, "opus-stereo.webm": 80000, "opus.ogg": 80000, "opus.opus": 80000,
                 "pcm.wav": 80000, "vorbis.oga": 80128}
# Avkodarna som det egna FFmpeg-bygget har (paketering/ffmpeg-komponenter.txt)
AVKODARE = ("aac", "aac_latm", "opus", "vorbis", "mp3float", "mp2", "mp1", "flac", "alac", "adpcm_ima_wav", "adpcm_ms",
            "pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be", "pcm_s32le", "pcm_s32be", "pcm_f32le", "pcm_f32be",
            "pcm_f64le", "pcm_u8", "pcm_mulaw", "pcm_alaw")
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


class TestFormat(unittest.TestCase):
    """Ett litet exempel av varje format som en inspelning eller en uppladdad fil kan ha (testljud/format/, 5 s var)."""

    def test_filerna_finns(self):
        self.assertEqual(sorted(os.listdir(FORMAT)), sorted(FORMATLANGDER))

    def test_exakta_langder(self):
        for namn, langd in FORMATLANGDER.items():
            with self.subTest(namn):
                x = ljud.avkoda(os.path.join(FORMAT, namn))
                self.assertEqual(x.dtype, np.float32)
                self.assertEqual(len(x), langd)  # exakt: en skillnad betyder ett annat avkodningsresultat
                self.assertGreater(float(np.abs(x).max()), 0.05, "tyst: avkodningen gav inget ljud")
                self.assertLessEqual(float(np.abs(x).max()), 1.0)

    def test_stereo_ger_tva_olika_kanaler(self):
        vanster, hoger = ljud.avkoda(os.path.join(FORMAT, "opus-stereo.webm"), stereo=True)
        self.assertEqual((len(vanster), len(hoger)), (80000, 80000))
        self.assertFalse(np.array_equal(vanster, hoger))
        mono, mono2 = ljud.avkoda(os.path.join(FORMAT, "pcm.wav"), stereo=True)
        self.assertTrue(np.array_equal(mono, mono2))  # en monofil ger samma kanal tva ganger


@unittest.skipUnless(os.environ.get("AKASHA_FFMPEG_LGPL") == "1",
                     "bara med det egna LGPL-bygget av FFmpeg (flodena satter AKASHA_FFMPEG_LGPL=1)")
class TestFfmpegArLgpl(unittest.TestCase):
    def test_ffmpeg_ar_lgpl(self):
        import av
        import av._core as core

        bibliotek = ("libavutil", "libavcodec", "libavformat", "libavfilter", "libavdevice", "libswresample", "libswscale")
        for namn in bibliotek:
            meta = core.library_meta[namn]
            with self.subTest(namn):
                self.assertEqual(meta["license"], "LGPL version 2.1 or later")
                for flagga in ("--enable-gpl", "--enable-version3", "--enable-nonfree"):
                    self.assertNotIn(flagga, meta["configuration"])
                self.assertNotIn("--enable-lib", meta["configuration"])
        for avkodare in AVKODARE:
            with self.subTest(avkodare):
                self.assertIn(avkodare, av.codecs_available)
        self.assertNotIn("libx264", av.codecs_available)
        self.assertNotIn("h264", av.codecs_available)  # inga videoavkodare alls


if __name__ == "__main__":
    unittest.main()
