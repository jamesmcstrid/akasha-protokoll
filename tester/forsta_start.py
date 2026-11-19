"""Startar Akasha Meet som vid forsta start (inga modeller), med en falsk Hugging Face.

    python tester/forsta_start.py [--port 8622] [--katalog DIR] [--sekunder 8]
           [--fel avbrott|kontrollsumma|inget-nat|disk] [--bara-talare]

Sidan kan provas for hand eller med ett skript (Chromium). Allt gar mot FalskHF i tester/falsk_hf.py:
adaptern stoppar alla andra varden an de falska, sa inget nar natet. Samma start som pa riktigt
(app.main()), bara att modellernas manifest har pahittat innehall och mycket mindre filer.
"""
import argparse
import math
import os
import sys
import tempfile
from urllib.parse import urlparse

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--port", type=int, default=8622)
ap.add_argument("--katalog", help="data och modeller hamnar har (standard: en ny tillfallig katalog)")
ap.add_argument("--sekunder", type=float, default=8, help="ungefar hur lang tid hamtningen tar")
ap.add_argument("--fel", choices=["avbrott", "kontrollsumma", "inget-nat", "disk"])
ap.add_argument("--bara-talare", action="store_true", help="taligenkanningen finns redan, bara rostmodellen saknas")
args = ap.parse_args()

katalog = os.path.abspath(args.katalog or tempfile.mkdtemp(prefix="akasha-forsta-start-"))
# Fore all import av appen: installningar.py laser miljon nar den importeras.
os.environ["DATAKATALOG"] = os.path.join(katalog, "data")
os.environ["MODELLKATALOG"] = os.path.join(katalog, "modeller")
os.environ["MOTOR"] = "faster"
os.environ["MODELL"] = "medium"
os.environ["PORT"] = str(args.port)

HAR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HAR), "app"))
sys.path.insert(0, HAR)

import falsk_hf  # noqa: E402
import modeller  # noqa: E402

# Storlekarna ar bara for att sidan ska se rimlig ut (150 MB och 40 MB): innehallet ar pahittat.
paket, innehall = falsk_hf.falska_paket(
    storlek_for={"model.bin": 150_000_000, "nemo_en_titanet_small.onnx": 40_257_283})
modeller.PAKET = paket
modeller.PAUSER = (0.5, 0.5)

if args.bara_talare:
    for fil in paket[("faster", "medium")]:
        os.makedirs(os.path.dirname(fil.sokvag()), exist_ok=True)
        with open(fil.sokvag(), "wb") as f:
            f.write(innehall[urlparse(fil.url).path])

# Fordrojningen per bit (64 KiB) raknas ut sa att allt som ska hamtas tar ungefar --sekunder.
filer = list(paket["talare"]) + ([] if args.bara_talare else list(paket[("faster", "medium")]))
bitar = sum(math.ceil(fil.storlek / falsk_hf.BIT) for fil in filer)
kwargs = {"fordrojning": args.sekunder / bitar}

if args.fel == "avbrott":
    # Under FRAMSTEG_MIN per forsok: ett forsok som lagt till mer raknas inte mot FORSOK, och da
    # skulle felet aldrig visas. Efter tre avbrott i rad ger hamta() upp; sedan ar kallan hel.
    kwargs.update(bryt_efter=500_000, bryt_ganger=modeller.FORSOK)
elif args.fel == "kontrollsumma":
    modelbin = next(f for f in paket[("faster", "medium")] if f.namn == "model.bin")
    kwargs.update(trasig_sokvag=urlparse(modelbin.url).path, trasig_ganger=1)
elif args.fel == "inget-nat":
    kwargs.update(natfel_ganger=modeller.FORSOK)


def logga(url, rang):
    print(f"falsk källa: {urlparse(url).hostname} {rang or ''}".rstrip(), flush=True)


falsk = falsk_hf.FalskHF(innehall, logg=logga, **kwargs)
modeller.ny_session = lambda: falsk_hf.session_med(falsk)  # en och samma FalskHF hela korningen

if args.fel == "disk":
    riktig_hamta = modeller.hamta
    forsta = [True]

    def hamta_med_diskfel(*a, **k):
        # Bara forsta hamtningen ser en nastan full disk. ledigt patchas inte globalt: GET
        # /api/modeller anropar den ocksa.
        if not forsta[0]:
            return riktig_hamta(*a, **k)
        forsta[0] = False
        riktig_ledigt = modeller.ledigt
        modeller.ledigt = lambda *a: 1000
        try:
            return riktig_hamta(*a, **k)
        finally:
            modeller.ledigt = riktig_ledigt

    modeller.hamta = hamta_med_diskfel

print(f"Första start: http://127.0.0.1:{args.port} (modeller i {katalog})", flush=True)
import app  # noqa: E402

app.main()
