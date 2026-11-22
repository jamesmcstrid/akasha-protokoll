"""Ordforstarkning for Pianissimo: ORDLISTA och svarstavade ord gor att modellen hellre valjer de orden.

Bearbetad kopia av Klangs kod, som i sin tur ar en numpy-portning av NeMos "GPU-PB"-traed (ContextGraph och
GPUBoostingTreeModel, NeMo 2.7, Apache-2.0):
  Kalla:    https://huggingface.co/KlangAI/pianissimo-sv-onnx, filerna phrase_boost.py och pianissimo_onnx.py
  Revision: 63730c6021234f26b9bbae9a07a04fec39e7a52e (samma som modellen i modeller.py)
  Licens:   CC-BY-4.0 (modellrepot). Se NOTICE.
Andringar mot originalet: de tva filerna ar en; namnen ar svenska; sentencepiece laddas forst nar en ordlista
anvands och tokeniseraren skickas in som en funktion, sa att traedet kan provas utan paketet; log_softmax ar
skriven har i stallet for hamtad ur onnx-asr:s interna utils; avstangningen ar en egen funktion; ingen
alfa-parameter (1,0). Avkodningsslingan ar onnx-asr 0.12.0:s (asr.py, _AsrWithTransducerDecoding._decoding)
med tillagget av bonusen, utan dess TensorRT-gren och assert-rader. Versionen i app/krav-pianissimo.txt ar
last, eftersom en annan version kan ha en annan slinga.

Ordlistan galler bara under en transkribering: forstark() satter in avkodningen pa modellen och stang_av() tar bort
den igen (se pianissimo.transkribera).
"""
import functools
import math
import types
from collections import deque

import numpy as np


class _Nod:
    __slots__ = ("id", "barn", "tecken_poang", "nod_poang", "ar_slut", "tillbaka")

    def __init__(self, nod_id, tecken_poang, nod_poang, ar_slut):
        self.id = nod_id
        self.barn = {}
        self.tecken_poang = tecken_poang
        self.nod_poang = nod_poang
        self.ar_slut = ar_slut
        self.tillbaka = None  # langsta ordsvans som ocksa ar en borjan pa nagon fras (Aho-Corasick)


class Forstarkning:
    """Ett trad over fraserna, token for token. poang(tillstand) ger bonusen for varje token fran ett tillstand."""

    def __init__(self, fraser, koda, vocab_storlek, kontext_poang=1.0, djup_skalning=2.0):
        """koda: fras -> lista med token-id (SentencePiece)."""
        self.vocab_storlek = vocab_storlek
        self.rot = _Nod(0, 0.0, 0.0, False)
        self.rot.tillbaka = self.rot
        self.noder = [self.rot]
        for fras in dict.fromkeys(fraser):
            self._lagg_till(koda(fras), kontext_poang, djup_skalning)
        self._fyll_tillbaka()
        self._minne = {}

    def _lagg_till(self, tecken, kontext_poang, djup_skalning):
        nod = self.rot
        for i, t in enumerate(tecken):
            sista = i == len(tecken) - 1
            barn = nod.barn.get(t)
            if barn is None:
                tecken_poang = kontext_poang * djup_skalning + math.log(i + 1) if i > 0 else kontext_poang
                barn = _Nod(len(self.noder), tecken_poang, nod.nod_poang + tecken_poang, sista)
                nod.barn[t] = barn
                self.noder.append(barn)
            else:
                barn.tecken_poang = max(kontext_poang, barn.tecken_poang)
                barn.nod_poang = nod.nod_poang + barn.tecken_poang
                barn.ar_slut = sista or barn.ar_slut
            nod = barn

    def _fyll_tillbaka(self):
        ko = deque()
        for barn in self.rot.barn.values():
            barn.tillbaka = self.rot
            ko.append(barn)
        while ko:
            nod = ko.popleft()
            for t, barn in nod.barn.items():
                tb = nod.tillbaka
                while t not in tb.barn and tb is not self.rot:
                    tb = tb.tillbaka
                barn.tillbaka = tb.barn.get(t, self.rot)
                ko.append(barn)

    def poang(self, tillstand):
        """-> (bonus per token, nasta tillstand per token) fran tillstand."""
        if tillstand not in self._minne:
            bonus = np.zeros(self.vocab_storlek, dtype=np.float32)
            nasta = np.full(self.vocab_storlek, -1, dtype=np.int64)
            nod, atertag = self.noder[tillstand], 0.0
            while True:
                for t, barn in nod.barn.items():
                    if nasta[t] < 0:
                        bonus[t] = atertag + barn.tecken_poang
                        nasta[t] = barn.id
                if nod is self.rot:
                    osatt = nasta < 0
                    bonus[osatt] = atertag
                    nasta[osatt] = 0
                    break
                if not nod.ar_slut:
                    atertag += nod.tillbaka.nod_poang - nod.nod_poang  # en fras som aldrig blev klar tar bonusen tillbaka
                nod = nod.tillbaka
            self._minne[tillstand] = (bonus, nasta)
        return self._minne[tillstand]


def _log_softmax(x):
    x = x - x.max()
    return x - np.log(np.exp(x).sum())


def _avkodning(self, encoder_ut, encoder_langder, /, *, trad, **kwargs):
    """onnx-asr:s avkodningsslinga for transducers (0.12.0) med frasbonusen lagd pa varje vald token."""
    behov_logprob = kwargs.get("need_logprobs")
    for kodning, kodning_langd in zip(encoder_ut, encoder_langder, strict=True):
        forra_tillstand = self._create_state()
        tokens, tider, logprobs = [], [], []
        forstark_tillstand = 0
        t = 0
        sagda = 0
        while t < kodning_langd:
            logits, steg, tillstand = self._decode(tokens, forra_tillstand, kodning[t])
            token = int(logits.argmax())
            if token != self._blank_idx:
                bonus, nasta = trad.poang(forstark_tillstand)
                token = int(np.argmax(logits[: self._blank_idx] + bonus))
                forstark_tillstand = int(nasta[token])
                forra_tillstand = tillstand
                tokens.append(token)
                tider.append(t)
                sagda += 1
                if behov_logprob:
                    logprobs.append(_log_softmax(logits)[token])
            if steg > 0:
                t += steg
                sagda = 0
            elif token == self._blank_idx or sagda == self._max_tokens_per_step:
                t += 1
                sagda = 0
        yield tokens, tider, logprobs if behov_logprob else None


def forstark(modell, fraser, tokeniserare):
    """Satter in ordforstarkningen pa en onnx-asr-modell. tokeniserare: sokvag till SentencePiece-modellen.
    Kastar om nagot ar fel, och da ar modellen orord."""
    import sentencepiece

    asr = modell.asr
    if asr._blank_idx != asr._vocab_size - 1:
        raise ValueError("blank ar inte sista token i ordlistan")
    koda = sentencepiece.SentencePieceProcessor(model_file=str(tokeniserare)).encode
    trad = Forstarkning(fraser, koda, vocab_storlek=asr._blank_idx)
    asr._decoding = types.MethodType(functools.partial(_avkodning, trad=trad), asr)


def stang_av(modell):
    """Tar bort ordforstarkningen: modellen avkodar som onnx-asr gor sjalv."""
    modell.asr.__dict__.pop("_decoding", None)
