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
    ljud = _till_float32(delar)
    if stereo:
        return ljud[0::2], ljud[1::2]
    return ljud


def _till_float32(delar):
    """int16-delar -> en float32-array i [-1, 1). Toemmer listan.

    Delarna kopieras in en i taget i en array som allokeras en gang, och varje del slapps direkt
    efter. Hogst finns da int16-delarna (2 byte per sampel) och resultatet (4 byte), 6 byte per
    sampel. Tidigare fanns delarna, en sammanfogad int16-array och tva float32-arrayer samtidigt:
    10 byte per sampel (tva timmar i stereo: 2,3 GB, nu 1,4 GB). Vardena ar desamma bit for bit:
    int16 -> float32 ar exakt, och divisionen sker i float32 som forut.
    """
    ljud = np.empty(sum(len(d) for d in delar), dtype=np.float32)
    delar.reverse()  # pop() tar da delarna i ordning och slapper var och en efter kopieringen
    pos = 0
    while delar:
        del_ = delar.pop()
        n = len(del_)
        np.divide(del_, 32768.0, out=ljud[pos:pos + n], dtype=np.float32)
        pos += n
        del del_
    return ljud
