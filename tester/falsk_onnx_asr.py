"""Falska onnx_asr och onnxruntime for testerna av app/pianissimo.py: ingen modell laddas. Varje bit ljud ger
orden "Hej du. Ja" med tider relativt bitens borjan. Moduler() ger det som ska in i sys.modules (mock.patch.dict)
sa att testerna fungerar lika med och utan de riktiga paketen installerade."""
import importlib.machinery
import types


class Resultat:
    tokens = [" Hej", " du", ".", " ▁Ja"]
    timestamps = [0.0, 0.5, 0.9, 1.5]


class FalskModell:
    def __init__(self):
        self.langder = []  # antal sampel i varje bit som modellen har fatt

    def with_timestamps(self):
        return self

    def recognize(self, samples):
        self.langder.append(len(samples))
        return Resultat()


def moduler():
    """-> ({namn: modul}, modellen som load_model ger, lista med load_model:s anrop (argument, kwargs))."""
    modell, anrop = FalskModell(), []
    asr = types.ModuleType("onnx_asr")
    asr.load_model = lambda *a, **kw: (anrop.append((a, kw)), modell)[1]
    ort = types.ModuleType("onnxruntime")
    ort.SessionOptions = types.SimpleNamespace  # onnxruntime.SessionOptions() med en intra_op_num_threads
    for m in (asr, ort):
        m.__spec__ = importlib.machinery.ModuleSpec(m.__name__, None)  # importlib.util.find_spec kraver den
    return {"onnx_asr": asr, "onnxruntime": ort}, modell, anrop
