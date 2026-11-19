"""En falsk Hugging Face for testerna och for tester/forsta_start.py.

FalskHF ar en requests-adapter som monteras pa en requests.Session. All riktig kod i
app/modeller.py (adresser, omdirigeringar, https-krav, sha256) kors oforandrad; bara transporten
ar falsk. Det finns ingen flagga eller miljovariabel i app/ som byter adress.
"""
import hashlib
import os
import time
from urllib.parse import urlparse

import requests
import urllib3

import modeller

CDN = "https://cdn.test.hf.co"
BIT = 65536  # kroppen levereras i sma bitar, sa att avbrott och fordrojning kan provas


class _Kropp:
    """Stand-in for urllib3:s svar: requests anropar stream(), close() och release_conn()."""

    def __init__(self, data, bryt_efter=None, fordrojning=0.0):
        self.data = data
        self.bryt_efter = bryt_efter
        self.fordrojning = fordrojning

    def stream(self, amt=BIT, decode_content=True):
        steg = max(1, min(amt or BIT, BIT))
        slut = len(self.data) if self.bryt_efter is None else min(self.bryt_efter, len(self.data))
        i = 0
        while i < slut:
            if self.fordrojning:
                time.sleep(self.fordrojning)
            yield self.data[i:min(i + steg, slut)]
            i += steg
        if self.bryt_efter is not None and self.bryt_efter < len(self.data):
            raise urllib3.exceptions.ProtocolError("Connection broken: avbrott", None)

    def close(self):
        pass

    def release_conn(self):
        pass


class FalskHF(requests.adapters.BaseAdapter):
    def __init__(self, innehall, bryt_efter=None, bryt_ganger=1, ignorera_range=False, status=None,
                 natfel_ganger=0, natfel=requests.exceptions.ConnectionError, trasig_sokvag=None,
                 trasig_ganger=0, cdn=CDN, fordrojning=0.0, logg=None):
        super().__init__()
        self.innehall = innehall
        self.bryt_efter = bryt_efter
        self.bryt_ganger = bryt_ganger
        self.ignorera_range = ignorera_range
        self.status = status
        self.natfel_ganger = natfel_ganger
        self.natfel = natfel
        self.trasig_sokvag = trasig_sokvag
        self.trasig_ganger = trasig_ganger
        self.cdn = cdn
        self.fordrojning = fordrojning
        self.logg = logg
        self.anrop = []  # (url, Range-rubriken)

    def _svar(self, request, kod, rubriker=None, kropp=b"", raw=None):
        svar = requests.Response()
        svar.status_code = kod
        svar.headers = requests.structures.CaseInsensitiveDict(rubriker or {})
        svar.url = request.url
        svar.request = request
        svar.raw = raw if raw is not None else _Kropp(kropp)
        return svar

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        rang = request.headers.get("Range")
        self.anrop.append((request.url, rang))
        if self.logg:
            self.logg(request.url, rang)
        delar = urlparse(request.url)
        if delar.hostname not in ("huggingface.co", "cdn.test.hf.co"):
            raise AssertionError(f"testet nådde en okänd adress: {request.url}")
        if self.natfel_ganger > 0:
            self.natfel_ganger -= 1
            raise self.natfel("falskt nätfel")
        if self.status is not None:
            return self._svar(request, self.status)
        if delar.hostname == "huggingface.co":
            return self._svar(request, 302, {"Location": self.cdn + delar.path})
        data = self.innehall[delar.path]
        if self.trasig_sokvag == delar.path and self.trasig_ganger > 0:
            self.trasig_ganger -= 1
            data = data[:-1] + bytes([data[-1] ^ 0xFF])
        start = 0
        if rang and not self.ignorera_range:
            start = int(rang.split("=")[1].rstrip("-"))
            if start >= len(data):
                return self._svar(request, 416, {"Content-Range": f"bytes */{len(data)}"})
        bryt = None
        if self.bryt_efter is not None and self.bryt_ganger > 0:
            self.bryt_ganger -= 1
            bryt = self.bryt_efter
        kropp = _Kropp(data[start:], bryt, self.fordrojning)
        if start:
            return self._svar(request, 206, {"Content-Range": f"bytes {start}-{len(data) - 1}/{len(data)}"},
                              raw=kropp)
        return self._svar(request, 200, raw=kropp)

    def close(self):
        pass


def falska_paket(storlek_per_fil=200_000, storlek_for=None):
    """Ger (paket, innehall): samma repo, revision, katalog och namn som modeller.PAKET men med
    pahittat innehall. innehall ar nyckelad pa URL-sokvag, for FalskHF."""
    storlek_for = storlek_for or {}
    nytt, innehall = {}, {}
    for nyckel, filer in modeller.PAKET.items():
        ut = []
        for fil in filer:
            data = os.urandom(storlek_for.get(fil.namn, storlek_per_fil))
            ut.append(modeller.Fil(fil.repo, fil.revision, fil.namn, fil.katalog, len(data),
                                   hashlib.sha256(data).hexdigest()))
            innehall[urlparse(ut[-1].url).path] = data
        nytt[nyckel] = tuple(ut)
    return nytt, innehall


def session_med(adapter):
    session = requests.Session()
    session.mount("https://", adapter)
    return session
