"""Prov efter installation: tjansten, en talare, tva talare och hela flodet via webbsidans API.

    bash halsokoll/prov.sh

Varje kontroll skriver OK eller FEL. Exit 0 = allt gront. Provet skapar en inspelning i listan
och raderar den efterat. Bara standardbiblioteket anvands.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

PORT = os.environ.get("PORT", "8611")
BAS = f"http://127.0.0.1:{PORT}"
HEADER = {"X-Akasha-Protokoll": "1"}
TESTLJUD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testljud")
fel = 0


def resultat(ok, text):
    global fel
    print(("OK:  " if ok else "FEL: ") + text, flush=True)
    if not ok:
        fel += 1
    return ok


def anrop(metod, sokvag, data=None, headers=None, timeout=900):
    req = urllib.request.Request(BAS + sokvag, data=data, method=metod,
                                 headers={**HEADER, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def multipart(falt, filfalt, filnamn):
    grans = uuid.uuid4().hex
    delar = []
    for k, v in falt.items():
        delar.append(f'--{grans}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    with open(os.path.join(TESTLJUD, filnamn), "rb") as f:
        innehall = f.read()
    delar.append(f'--{grans}\r\nContent-Disposition: form-data; name="{filfalt}"; '
                 f'filename="{filnamn}"\r\nContent-Type: audio/mp4\r\n\r\n'.encode() + innehall + b"\r\n")
    delar.append(f"--{grans}--\r\n".encode())
    return b"".join(delar), {"Content-Type": f"multipart/form-data; boundary={grans}"}


def vanta_klar(id_, max_s=900):
    slut, meta = time.time() + max_s, {}
    while time.time() < slut:
        meta = json.loads(anrop("GET", f"/api/inspelningar/{id_}")[1])
        if meta["status"] in ("klar", "fel", "avbruten"):
            break
        time.sleep(2)
    return meta


def talare_for(segment, fras):
    return {s["speaker"] for s in segment if fras.lower() in s["text"].lower()}


def tva_stammer(segment, antal):
    """-> (stammer, man, kvinna): sant om det blev 2 talare, mannen (Carter, Afghanistan) hos en
    och kvinnan (struktur, Forskarna) hos en annan. Facit for testljud/tva-talare.m4a."""
    man = talare_for(segment, "Carter") | talare_for(segment, "Afghanistan")
    kvinna = talare_for(segment, "struktur") | talare_for(segment, "Forskarna")
    return antal == 2 and len(man) == 1 and len(kvinna) == 1 and man != kvinna, man, kvinna


def kolla_tva(segment, antal, etikett, tid=""):
    for s in segment:
        print(f"       [{s['start']:5.1f}] Talare {s['speaker']}: {s['text'][:70]}")
    ok, man, kvinna = tva_stammer(segment, antal)
    resultat(ok, f"{etikett}: {antal} talare, mannen={man}, kvinnan={kvinna} (facit: 2, olika){tid}")


def main():
    # 1. tjansten
    try:
        kod, kropp = anrop("GET", "/health", timeout=10)
    except OSError as e:
        resultat(False, f"tjansten svarar inte pa {BAS}: {e}")
        return
    halsa = json.loads(kropp)
    resultat(kod == 200 and halsa["status"] == "ok", f"/health: {halsa}")
    resultat(halsa.get("talare") == "ok", f"talarmodellerna: {halsa.get('talare')}")
    if kod != 200:
        return

    # 2. en talare
    kropp, h = multipart({}, "audio", "en-talare.m4a")
    kod, svar = anrop("POST", "/transcribe", kropp, h)
    svar = json.loads(svar)
    if resultat(kod == 200, f"en talare: http {kod}"):
        print(f"       {svar['text'][:110]}")
        resultat("dinosaurie" in svar["text"].lower(),
                 f"en talare: 'dinosaurie' finns i texten ({svar['elapsed_s']} s for {svar['duration_s']} s ljud)")

    # 3. tva talare, kant antal och gissat
    for antal in ("2", "auto"):
        kropp, h = multipart({"speakers": antal}, "audio", "tva-talare.m4a")
        kod, svar = anrop("POST", "/transcribe", kropp, h)
        svar = json.loads(svar)
        if resultat(kod == 200, f"tva talare (speakers={antal}): http {kod}"):
            kolla_tva(svar["segments"], svar.get("speakers"), f"tva talare (speakers={antal})",
                      f", {svar['elapsed_s']} s varav talare {svar.get('speakers_elapsed_s')} s")

    # 4. digitalt mote: mikrofonen i vanster kanal, motet i hoger (som en inspelning i Chrome)
    kod, svar = anrop("POST", "/api/inspelningar", json.dumps(
        {"andelse": ".webm", "talare": "3", "kalla": "digitalt", "titel": "Prov digitalt"}).encode(),
        {"Content-Type": "application/json"})
    if resultat(kod == 201, f"digitalt: ny inspelning http {kod}"):
        id_ = json.loads(svar)["id"]
        with open(os.path.join(TESTLJUD, "digitalt-mote.webm"), "rb") as f:
            anrop("POST", f"/api/inspelningar/{id_}/del?nr=0", f.read(), {"Content-Type": "application/octet-stream"})
        anrop("POST", f"/api/inspelningar/{id_}/klar", json.dumps({"starta": True}).encode(),
              {"Content-Type": "application/json"})
        meta = vanta_klar(id_)
        res = meta.get("resultat") or {}
        seg = res.get("segment", [])
        du = talare_for(seg, "Carter") | talare_for(seg, "Afghanistan")
        kvinna = talare_for(seg, "struktur") | talare_for(seg, "Forskarna")
        man = talare_for(seg, "boulevard") | talare_for(seg, "Turkiet")
        ok = (meta.get("status") == "klar" and du == {1} and meta.get("namn", {}).get("1") == "Du"
              and len(kvinna) == 1 and len(man) == 1 and kvinna != man and 1 not in kvinna | man)
        resultat(ok, f"digitalt: du={du} (namn {meta.get('namn', {}).get('1')}), kvinnan={kvinna}, "
                     f"mannen={man} (facit: du 1, de andra olika), tider {res.get('tid_s')}")
        anrop("POST", f"/api/inspelningar/{id_}/radera")

    # 5. hela flodet som webbsidan: ladda upp, vanta, namnge, ladda ner, radera
    kropp, h = multipart({"talare": "2", "titel": "Prov akasha-protokoll"}, "ljud", "tva-talare.m4a")
    kod, svar = anrop("POST", "/api/inspelningar/fil", kropp, h)
    if not resultat(kod == 201, f"flode: uppladdning http {kod} {svar[:120]!r}"):
        return
    id_ = json.loads(svar)["id"]
    meta = vanta_klar(id_)
    if resultat(meta.get("status") == "klar", f"flode: status {meta.get('status')} {meta.get('fel', '')}"):
        res = meta["resultat"]
        kolla_tva(res["segment"], res.get("talare"), "flode: talare", f", tider {res.get('tid_s')}")
        anrop("POST", f"/api/inspelningar/{id_}/namn", json.dumps({"1": "Provnamn"}).encode(),
              {"Content-Type": "application/json"})
        kod, md = anrop("GET", f"/api/inspelningar/{id_}/text.md")
        resultat(kod == 200 and "**Provnamn**" in md.decode(), "flode: namn syns i nedladdad .md")
    kod, _ = anrop("POST", f"/api/inspelningar/{id_}/radera")
    resultat(kod == 200, "flode: provinspelningen raderad")


if __name__ == "__main__":
    main()
    print("PROV: OK" if fel == 0 else f"PROV: FEL ({fel})")
    sys.exit(1 if fel else 0)
