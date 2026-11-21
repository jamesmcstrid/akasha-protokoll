"""Avkodningen med PyAV (ljud.py): langder, stereo, jamforelse med faster-whisper och att motorn inte drar in det."""
import hjalp  # noqa: F401  (maste importeras forst)

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest import mock

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


def gammal_float32(delar):
    """Omvandlingen som avkoda() gjorde fore minnesrattningen, ordagrant."""
    return (np.concatenate(delar) if delar else np.zeros(0, np.int16)).astype(np.float32) / 32768.0


def skriv_lang_wav(sokvag, sekunder, kanaler=1, sr=16000):
    """Syntetiskt ljud (sinus och brus), 16 bit PCM."""
    n = int(sekunder * sr)
    t = np.arange(n) / sr
    x = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.05 * np.random.default_rng(0).standard_normal(n)
    if kanaler == 2:
        x = np.stack([x, 0.3 * np.sin(2 * np.pi * 330 * t)], axis=1).reshape(-1)
    with wave.open(sokvag, "wb") as w:
        w.setnchannels(kanaler)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())


class TestMinnet(unittest.TestCase):
    """avkoda() ska ge samma float32-varden som forut, med lagre minnestopp."""

    def test_samma_som_forut_pa_testljuden(self):
        filer = [os.path.join(LJUD, n) for n in LANGDER] + [os.path.join(FORMAT, n) for n in FORMATLANGDER]
        for sokvag in filer:
            for stereo in (False, True):
                with self.subTest(os.path.basename(sokvag), stereo=stereo):
                    nu = ljud.avkoda(sokvag, stereo=stereo)
                    with mock.patch.object(ljud, "_till_float32", gammal_float32):
                        forut = ljud.avkoda(sokvag, stereo=stereo)
                    for a, b in (zip(nu, forut) if stereo else [(nu, forut)]):
                        self.assertEqual((a.dtype, a.shape, a.strides), (b.dtype, b.shape, b.strides))
                        self.assertEqual(a.tobytes(), b.tobytes())  # bit for bit

    def test_till_float32_bit_for_bit(self):
        rng = np.random.default_rng(3)
        delar = [np.array([-32768, -1, 0, 1, 32767], np.int16), np.zeros(0, np.int16)]
        delar += [rng.integers(-32768, 32768, size=n, dtype=np.int16) for n in (1, 1000, 77_777)]
        vantat = gammal_float32(list(delar))
        kopia = list(delar)
        ut = ljud._till_float32(kopia)
        self.assertEqual(ut.dtype, np.float32)
        self.assertEqual(ut.tobytes(), vantat.tobytes())
        self.assertEqual(kopia, [])  # delarna slapps under tiden
        self.assertEqual((ut[0], ut[4]), (-1.0, np.float32(32767 / 32768)))
        tom = ljud._till_float32([])
        self.assertEqual((tom.dtype, tom.shape), (np.float32, (0,)))

    def test_minnestoppen_ar_lagre_an_forut(self):
        # Forut: 2,5 ganger resultatets storlek (int16-delarna, en sammanfogad int16-array och tva
        # float32-arrayer). Nu: delarna och resultatet, 1,5 ganger. Grans 2,0 med marginal.
        import tracemalloc
        katalog = tempfile.mkdtemp(prefix="akasha-ljud-")
        self.addCleanup(shutil.rmtree, katalog, True)
        for kanaler, stereo in ((1, False), (2, True)):
            with self.subTest(kanaler=kanaler):
                fil = os.path.join(katalog, f"lang-{kanaler}.wav")
                skriv_lang_wav(fil, 120, kanaler)  # 2 min: flera grupper om _GRUPP sampel
                tracemalloc.start()
                try:
                    x = ljud.avkoda(fil, stereo=stereo)
                    topp = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                storlek = x[0].base.nbytes if stereo else x.nbytes  # stereo: vyer i samma array
                self.assertEqual(storlek, 120 * 16000 * kanaler * 4)
                self.assertLess(topp, 2.0 * storlek, f"topp {topp / storlek:.2f} ganger resultatet")


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
