"""En falsk sherpa_onnx for testerna av paketering/kontrollera_windows.py: ingen modell laddas, avtrycket raknas ur
ljudets spektrum. En modellfil som innehaller texten KRASCH far processen att avsluta sig som sherpa-onnx gor vid ett
laddningsfel (exit, inget undantag)."""
import os
import sys

import numpy as np

__version__ = "0.0-falsk"


class SpeakerEmbeddingExtractorConfig:
    def __init__(self, model="", num_threads=1, debug=False, provider="cpu"):
        self.model = model


class _Strom:
    def __init__(self):
        self.x = np.zeros(0, dtype=np.float32)

    def accept_waveform(self, sr, x):
        self.x = np.asarray(x, dtype=np.float32)

    def input_finished(self):
        pass


class SpeakerEmbeddingExtractor:
    dim = 8

    def __init__(self, config):
        try:
            with open(config.model, "rb") as f:
                krasch = b"KRASCH" in f.read(4096)
        except OSError:
            krasch = True
        if krasch:
            sys.stderr.write(f"falsk sherpa-onnx: kan inte lasa {config.model!r}\n")
            sys.stderr.flush()
            os._exit(255)

    def create_stream(self):
        return _Strom()

    def compute(self, s):
        spektrum = np.abs(np.fft.rfft(s.x))[:64]
        return (spektrum.reshape(8, 8).mean(1) + 1e-3).tolist()
