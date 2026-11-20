"""Ljudfiler -> float32, 16 kHz. PyAV har FFmpeg inbyggt, sa inget behover installeras.

Samma metod som faster-whisper (MIT) anvander i decode_audio, skriven har sa att avkodningen inte
drar in faster-whisper och ctranslate2: programmet for Mac har bara whisper.cpp.
"""
import gc

# Importeras overst, inte i funktionen: ett paketerat program som saknar PyAV ska inte starta alls.
# Da syns det i kontrollen i Actions och inte forst vid forsta transkriberingen.
import av
import numpy as np

SR = 16000
_GRUPP = 500_000  # sampel per omsampling: haller minnet nere for langa moten


def _ramar(behallare):
    """Ljudramar i ordning. Trasiga ramar hoppas over i stallet for att hela filen ger fel."""
    iterator = behallare.decode(audio=0)
    while True:
        try:
            yield next(iterator)
        except StopIteration:
            return
        except av.error.InvalidDataError:
            continue


def avkoda(sokvag, sr=SR, stereo=False):
    """-> float32-array (mono), eller (vanster, hoger) om stereo."""
    omsamplare = av.audio.resampler.AudioResampler(
        format="s16", layout="stereo" if stereo else "mono", rate=sr
    )
    delar = []

    def omsampla(ram):
        for r in omsamplare.resample(ram):
            delar.append(r.to_ndarray().reshape(-1))

    with av.open(sokvag, mode="r", metadata_errors="ignore") as behallare:
        fifo = av.audio.fifo.AudioFifo()
        for ram in _ramar(behallare):
            ram.pts = None
            fifo.write(ram)
            if fifo.samples >= _GRUPP:
                omsampla(fifo.read())
        if fifo.samples:
            omsampla(fifo.read())
        omsampla(None)
    # Omsamplaren haller kvar minne tills den frigors.
    del omsamplare
    gc.collect()
    ljud = (np.concatenate(delar) if delar else np.zeros(0, np.int16)).astype(np.float32) / 32768.0
    if stereo:
        return ljud[0::2], ljud[1::2]
    return ljud
