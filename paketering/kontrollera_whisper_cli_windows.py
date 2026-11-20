"""Kontrollerar en byggd whisper-cli: beroenden (bara Windows), alla flaggor som app/motor.py anvander, DTW-forvalen
och en riktig transkribering av ett testljud med en liten modell, genom programmets egen kod (motor.cli_kommando
och motor._whispercpp) med en modellkatalog som heter "Asa Olund" (med a-ring och o-prickar) och prompten
"Asa Oberg, Goteborg" (med a-ring och o-prickar).

    python paketering/kontrollera_whisper_cli_windows.py --cli SOKVAG [--modell FIL] [--arbetskatalog KAT]
           [--ordtider-ut FIL] [--hoppa-pe] [--tidsgrans 900]

Kors med byggets venv (motor.py behover numpy och PyAV), fran repots rot. Samma skript gar att kora pa Linux med en
Linux-byggd whisper-cli och en modell som anges med --modell (da hoppas PE-kontrollen over). Utan --modell hamtas
testmodellen ggml-tiny-q5_1.bin (lasta sha256) till arbetskatalogen: bara for den har kontrollen, aldrig KB-Whisper.

Varje kontroll skriver OK: eller FEL: och skriptet fortsatter efter ett FEL sa langt det gar. Sist kommer en
sammanfattning; slutkod 1 om nagot var FEL.
"""
import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.request

import kontroll_hjalp

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAGGOR = ["-m", "-f", "-l", "-bs", "-pp", "-oj", "-of", "--prompt", "-t", "-ml", "-sow", "--dtw", "-nfa", "-ojf"]
# Samma lasta testmodell som paketering/kontrollera-whisper-cli.sh (Mac).
MODELL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny-q5_1.bin"
MODELL_SHA = "818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7"
KATALOGNAMN = "Åsa Ölund"
PROMPT = "Åsa Öberg, Göteborg"
# Raderna som whisper.cpp skriver nar den laser modellfilen:
LADDAR = re.compile(r"whisper_model_load|whisper_init_from_file")
KANDA_KODER = {
    0xC0000135: "STATUS_DLL_NOT_FOUND: en DLL som whisper-cli importerar hittades inte",
    0xC0000139: "STATUS_ENTRYPOINT_NOT_FOUND: en DLL hittades men har inte funktionen som importeras (fel version)",
    0xC000007B: "STATUS_INVALID_IMAGE_FORMAT: fel arkitektur (32 mot 64 bitar) i en exe eller dll",
    0xC0000005: "STATUS_ACCESS_VIOLATION: programmet kraschade",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN: programmet avbröts (abort)",
    0xC0000142: "STATUS_DLL_INIT_FAILED: en DLL kunde inte startas",
}


def kodtext(kod):
    """Slutkod -> text. Windows ger slutkoder som 3221225781 (0xC0000135) nar en process inte kan starta."""
    if kod is None:
        return "ingen slutkod"
    u = kod & 0xFFFFFFFF if kod < 0 else kod
    if u in KANDA_KODER:
        return f"kod {kod} (0x{u:08X}, {KANDA_KODER[u]})"
    return f"kod {kod}" + (f" (0x{u:08X})" if u > 255 else "")


# --- DTW-forvalen: avgorandet utan kontroll av kvalitet (samma som i kontrollera-whisper-cli.sh, steg 8) ----------

def har_laddning(text):
    return bool(LADDAR.search(text))


def dtw_rader(text):
    return [r for r in text.splitlines() if "dtw" in r.lower()]


def valj_satt(okant, kod):
    """Korningen med det pahittade forvalet (stderr, slutkod) -> ("laddning" | "rader", None) eller (None, orsak).
    laddning: whisper-cli stoppade fore modelladdningen. rader: den laddade modellen och sa ifran med en dtw-rad."""
    if not har_laddning(okant) and okant.strip() and kod is not None and 0 < kod < 128:
        return "laddning", None
    if har_laddning(okant) and dtw_rader(okant):
        return "rader", None
    return None, (f"det pahittade forvalet gav varken ett stopp fore modelladdningen ({kodtext(kod)}) eller en "
                  f"dtw-rad efter den")


def avgor_forval(satt, okant, text, forval, kod):
    """-> (ok, text). text = stderr fran korningen med `forval`."""
    if satt == "laddning" and not har_laddning(text):
        return False, f"forvalet {forval} kanns inte igen (modellen laddades aldrig, som for ett okant forval)"
    # Dtw-raderna fran det pahittade forvalet, ocksa med namnet utbytt mot forvalets, far inte finnas ordagrant i
    # utskriften (annars skulle "unknown ... 'medium'" aldrig vara lika med "... 'finns-inte'").
    rader = dtw_rader(okant)
    mall = {r for r in rader} | {r.replace("finns-inte", forval) for r in rader}
    lika = [r for r in text.splitlines() if r in mall]
    if lika:
        return False, (f"forvalet {forval} kanns inte igen: en dtw-rad som for ett pahittat forval finns i "
                       f"utskriften: {lika[0]!r}")
    if satt == "laddning":
        return True, f"forvalet {forval} kanns igen (modellen laddades; {kodtext(kod)})"
    return True, f"forvalet {forval} kanns igen (ingen dtw-rad fran det pahittade forvalet finns i utskriften; {kodtext(kod)})"


# --- hjalp ----------------------------------------------------------------------------------------------------

def kor(cmd, cwd=None, tidsgrans=120):
    """-> (slutkod eller None vid tidsgrans/start misslyckades, stderr+stdout som text)."""
    try:
        p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=tidsgrans)
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or b"").decode("utf-8", "replace") + f"\n[tidsgrans {tidsgrans} s]"
    except OSError as e:
        return None, f"[kunde inte starta {cmd[0]}: {e}]"
    return p.returncode, p.stdout.decode("utf-8", "replace")


def sha256_av(sokvag):
    h = hashlib.sha256()
    with open(sokvag, "rb") as f:
        for bit in iter(lambda: f.read(1 << 20), b""):
            h.update(bit)
    return h.hexdigest()


def rel(sokvag, bas):
    return os.path.relpath(sokvag, bas)


class Kontroll:
    def __init__(self, args):
        self.args = args
        self.res = kontroll_hjalp.Resultat("KONTROLL AV WHISPER-CLI")
        self.cli = os.path.abspath(args.cli)
        self.arb = os.path.abspath(args.arbetskatalog or tempfile.mkdtemp(prefix="kontrollera-whisper-cli-"))
        os.makedirs(self.arb, exist_ok=True)
        # Katalogen heter "Asa Olund" (med a-ring och o-prickar): modellkatalogen och allt under den har sadana tecken i sokvagen.
        self.modellkatalog = os.path.join(self.arb, KATALOGNAMN, "modeller")
        self.samples = None
        self.modell_pa_plats = False

    # --- miljon: ska vara satt fore import av app/ ---------------------------------------------------------
    def stall_in_app(self):
        os.makedirs(self.modellkatalog, exist_ok=True)
        os.environ["MODELLKATALOG"] = self.modellkatalog
        os.environ["DATAKATALOG"] = os.path.join(self.arb, KATALOGNAMN, "data")
        os.environ["MOTOR"] = "whispercpp"
        os.environ["MODELL"] = "medium"
        os.environ["WHISPERCPP_BIN"] = self.cli
        sys.path.insert(0, os.path.join(ROT, "app"))
        global motor, modeller, ljud, plattform
        import ljud
        import modeller
        import motor
        import plattform

    # --- stegen ---------------------------------------------------------------------------------------------
    def steg_1_beroenden(self):
        self.res.steg("1. beroenden (PE-kontroll)")
        if os.name != "nt" or self.args.hoppa_pe:
            self.res.info("PE-kontrollen hoppades over (bara Windows)")
            return
        import kontrollera_pe

        system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        kod = kontrollera_pe.main([os.path.dirname(self.cli), "--system-katalog", system])
        self.res.kontrollera(kod == 0, "whisper-cli och DLL-filerna bredvid den hittar alla sina beroenden",
                             "beroendena stämmer inte (se raderna ovan)")

    def steg_2_flaggor(self):
        self.res.steg("2. flaggor i --help")
        kod, text = kor([self.cli, "--help"], tidsgrans=60)
        print(text)
        print(f"--help: {kodtext(kod)}")
        if not text.strip():
            self.res.fel(f"--help gav ingen utskrift ({kodtext(kod)}): whisper-cli startar inte alls. "
                         "Se stegen for beroenden ovan")
            return
        saknas = [f for f in FLAGGOR if not re.search(rf"(^|[\s,]){re.escape(f)}([\s,=]|$)", text, re.M)]
        self.res.kontrollera(not saknas, f"alla {len(FLAGGOR)} flaggor finns i --help",
                             f"whisper-cli saknar flaggorna {' '.join(saknas)} som app/motor.py anvander (se --help ovan)")

    def steg_3_modell(self):
        self.res.steg("3. testmodellen ggml-tiny-q5_1.bin")
        mal = modeller.GGML_MODELL
        os.makedirs(os.path.dirname(mal), exist_ok=True)
        if self.args.modell:
            kalla = os.path.abspath(self.args.modell)
            if not os.path.isfile(kalla):
                self.res.fel(f"--modell {kalla} finns inte")
                return
            self.res.info(f"använder --modell {kalla}")
        else:
            kalla = os.path.join(self.arb, "tiny.bin")
            try:
                req = urllib.request.Request(MODELL_URL, headers={"User-Agent": "akasha-protokoll-bygg"})
                with urllib.request.urlopen(req, timeout=120) as r, open(kalla, "wb") as f:
                    shutil.copyfileobj(r, f)
            except Exception as e:
                self.res.fel(f"kunde inte hämta testmodellen från {MODELL_URL}: {type(e).__name__}: {e}")
                return
        sha = sha256_av(kalla)
        if sha == MODELL_SHA:
            self.res.ok(f"testmodellen har sha256 {sha} ({os.path.getsize(kalla)} byte)")
        elif self.args.modell:
            self.res.info(f"modellen är inte den låsta testmodellen (sha256 {sha}); fortsätter med den ändå")
        else:
            with open(kalla, "rb") as f:
                borjan = f.read(120)
            self.res.fel(f"sha256 för testmodellen är {sha}, väntade {MODELL_SHA} (filens första byte: {borjan!r})")
            return
        shutil.copyfile(kalla, mal)
        self.modell_pa_plats = True
        self.res.ok(f"modellen lagd på GGML-modellens plats: {mal}")

    def steg_4_ljud(self):
        self.res.steg("4. testljudet")
        ljudfil = os.path.join(ROT, "testljud", "en-talare.m4a")
        self.samples = ljud.avkoda(ljudfil)
        langd = len(self.samples) / motor.SR
        self.res.kontrollera(langd > 5, f"testljudet avkodat med PyAV: {langd:.1f} s, {len(self.samples)} sampel",
                             f"testljudet gav bara {langd:.1f} s")

    def steg_5_system_info(self):
        self.res.steg("5. system_info och backend-DLL:er (information)")
        if not self.modell_pa_plats:
            self.res.info("hoppas over: ingen modell")
            return
        import numpy as np

        tyst = os.path.join(self.modellkatalog, "kontroll-tyst.wav")
        with open(tyst, "wb") as f:
            f.write(motor.wav_16k_mono(np.zeros(motor.SR, dtype=np.float32)))
        kod, text = kor([self.cli, "-m", rel(modeller.GGML_MODELL, self.modellkatalog), "-f", rel(tyst, self.modellkatalog),
                         "-l", "sv"], cwd=self.modellkatalog, tidsgrans=120)
        rader = [r for r in text.splitlines()
                 if re.search(r"system_info|backend|load|ggml|AVX|SSE|NEON|FMA|CPU|n_threads", r, re.I)]
        print("\n".join(rader[:60]) or "(inga rader)")
        print(f"(information, ingen kontroll; {kodtext(kod)})")
        os.remove(tyst)

    def steg_6_transkribering(self):
        self.res.steg("6. transkribering genom motor.cli_kommando() och motor._whispercpp()")
        if not self.modell_pa_plats or self.samples is None:
            self.res.fel("hoppas över: modellen eller testljudet saknas (se stegen ovan)")
            return
        motor.DTW = "tiny"  # bara har, i kontrollen: testmodellen ar tiny
        # Kommandot som motorn bygger: relativa sokvagar, och pa Windows en svarsfil med prompten som UTF-8.
        for system in (plattform.system(), "Windows"):
            argv, svar = motor.cli_kommando(self.cli, "tmp-akasha-protokoll-EXEMPEL", True, PROMPT, 0, system)
            print(f"-- kommando för system={system}: {argv}")
            if svar is not None:
                print("-- svarsfilens innehåll:")
                print(svar.rstrip("\n"))
        _, svar = motor.cli_kommando(self.cli, "tmp-akasha-protokoll-EXEMPEL", True, PROMPT, 0, "Windows")
        self.res.kontrollera(PROMPT.encode("utf-8") in svar.encode("utf-8")
                             and self.modellkatalog not in svar and "--prompt\n" + PROMPT + "\n" in svar,
                             "svarsfilen har prompten som UTF-8 på egen rad och inga absoluta sökvägar",
                             "svarsfilen har inte prompten på egen rad eller har absoluta sökvägar")

        loggrader = []

        class Fangare(logging.Handler):
            def emit(self, post):
                loggrader.append(post.getMessage())

        logg = logging.getLogger("akasha-protokoll")
        gammal_niva = logg.level
        logg.setLevel(logging.INFO)
        fangare = Fangare()
        logg.addHandler(fangare)
        framsteg = []
        try:
            text, segs, tider = motor._whispercpp(self.samples, True, PROMPT, framsteg.append)
        except Exception as e:
            self.res.fel(f"motor._whispercpp() kastade {type(e).__name__}: {e}")
            traff = re.search(r"avslutades med kod (-?\d+)", str(e))
            if traff:
                print(f"whisper-cli: {kodtext(int(traff.group(1)))}")
            return
        finally:
            logg.removeHandler(fangare)
            logg.setLevel(gammal_niva)
        for rad in loggrader:
            print(f"logg: {rad}")
        self.res.ok(f"motor._whispercpp() lyckades (kod 0), {len(framsteg)} framstegsrapporter"
                    + (f", sista {framsteg[-1]:.0%}" if framsteg else ""))
        self.res.kontrollera(bool(text.strip()), f"texten har {len(text)} tecken", "texten är tom")
        langd = len(self.samples) / motor.SR
        self.res.kontrollera(len(tider) >= 5, f"{len(tider)} ord med tider", f"bara {len(tider)} ord (väntade minst 5)")
        self.res.kontrollera(bool(tider) and len(tider[0]) == 4,
                             "ordtiderna kommer från DTW (motor.dtw_ordtider() gav tider med sannolikhet)",
                             "ordtiderna kommer inte från DTW: motor.dtw_ordtider() gav None (--dtw eller -ojf fungerade inte)")
        utanfor = [t for t in tider if not (0 <= t[0] <= t[1] <= langd + 1)]
        self.res.kontrollera(not utanfor, f"alla ordtider ligger mellan 0 och {langd + 1:.0f} s",
                             f"{len(utanfor)} ord har tider utanför 0-{langd + 1:.0f} s, till exempel {utanfor[:1]}")
        print("De första tio orden: " + " | ".join(f"{t[2].strip()} {t[0]:.2f}-{t[1]:.2f}" for t in tider[:10]))
        print(f"Texten börjar: {text[:120]}")
        kvar = [n for n in os.listdir(self.modellkatalog) if n.startswith(motor.TMP_PREFIX)]
        self.res.kontrollera(not kvar, "ingen tmp-akasha-protokoll-* ligger kvar under modellkatalogen",
                             f"kvar under modellkatalogen: {kvar}")
        if self.args.ordtider_ut:
            with open(self.args.ordtider_ut, "w", encoding="utf-8") as f:
                json.dump([[t[0], t[1], t[2]] for t in tider], f, ensure_ascii=False)
            self.res.info(f"ordtiderna sparade i {self.args.ordtider_ut}")

    def steg_7_dtw_forval(self):
        self.res.steg("7. DTW-förval (de som app/modeller.py använder)")
        if not self.modell_pa_plats:
            self.res.fel("hoppas över: ingen modell")
            return
        import numpy as np

        forval = sorted(set(modeller.DTW_PER_STORLEK.values()))
        print(f"Förval ur app/modeller.py: {' '.join(forval)}")
        wav = os.path.join(self.modellkatalog, "kontroll-dtw.wav")
        with open(wav, "wb") as f:
            f.write(motor.wav_16k_mono(self.samples if self.samples is not None else np.zeros(motor.SR, np.float32)))
        modell = rel(modeller.GGML_MODELL, self.modellkatalog)
        ljudfil = rel(wav, self.modellkatalog)

        print("--- 7a. okänt förval (--dtw finns-inte)")
        kod_o, okant = kor([self.cli, "-m", modell, "-f", ljudfil, "-l", "sv", "-d", "3000", "--dtw", "finns-inte"],
                           cwd=self.modellkatalog)
        self.visa_utdrag(okant, kod_o)
        satt, orsak = valj_satt(okant, kod_o)
        if satt is None:
            self.res.fel(f"kan inte avgöra om DTW-förvalen känns igen: {orsak}")
            os.remove(wav)
            return
        print(f"Sätt att avgöra: {satt}")
        for f in forval:
            print(f"--- 7b. förval {f}")
            utfil = os.path.join(self.modellkatalog, f"kontroll-dtw-{f}")
            kod, text = kor([self.cli, "-m", modell, "-f", ljudfil, "-l", "sv", "-d", "3000", "-ml", "1", "-sow", "--dtw", f,
                             "-nfa", "-ojf", "-oj", "-of", rel(utfil, self.modellkatalog)], cwd=self.modellkatalog)
            self.visa_utdrag(text, kod)
            ok, besked = avgor_forval(satt, okant, text, f, kod)
            (self.res.ok if ok else self.res.fel)(besked)
            for rest in (utfil + ".json",):
                if os.path.exists(rest):
                    os.remove(rest)
        os.remove(wav)

    @staticmethod
    def visa_utdrag(text, kod):
        """Kod, om modellen laddades och de rader som behovs for att lasa av steget."""
        rader = text.splitlines()
        print(f"{kodtext(kod)}; laddar modellen: {'ja' if har_laddning(text) else 'nej'}; "
              f"{len(rader)} rader, varav med dtw: {len(dtw_rader(text))}")
        urval = [r for r in rader if re.search(r"dtw|error|assert|abort|whisper_model_load: (type|n_text_layer|n_audio_layer)|"
                                               r"whisper_init_from_file|output_json", r, re.I)]
        print("\n".join(urval[:20]))
        print("(sista 3 raderna:)\n" + "\n".join(rader[-3:]))


def main(argv=None):
    kontroll_hjalp.utf8_utskrift()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cli", required=True, help="whisper-cli (whisper-cli.exe på Windows)")
    ap.add_argument("--modell", help="en GGML-modell att använda i stället för att hämta testmodellen")
    ap.add_argument("--arbetskatalog", help="katalog att arbeta i (standard: en ny tillfällig)")
    ap.add_argument("--ordtider-ut", help="spara ordtiderna från transkriberingen här (JSON)")
    ap.add_argument("--hoppa-pe", action="store_true", help="hoppa över PE-kontrollen (annars bara på Windows)")
    ap.add_argument("--tidsgrans", type=int, default=900, help="hela skriptet avbryts efter så här många sekunder")
    args = ap.parse_args(argv)
    if not os.path.isfile(args.cli):
        print(f"FEL: {args.cli} finns inte", flush=True)
        return 1

    def avbryt():
        print(f"FEL: kontrollen avbröts efter {args.tidsgrans} s (något hänger sig)", flush=True)
        os._exit(3)

    vakt = threading.Timer(args.tidsgrans, avbryt)
    vakt.daemon = True
    vakt.start()
    k = Kontroll(args)
    print(f"Kontrollerar {k.cli}, arbetskatalog {k.arb}")
    try:
        k.stall_in_app()
    except Exception:
        traceback.print_exc()
        k.res.fel("kunde inte importera app/ (numpy och PyAV behövs: kör med byggets venv)")
        return k.res.sammanfatta()
    for steg in (k.steg_1_beroenden, k.steg_2_flaggor, k.steg_3_modell, k.steg_4_ljud, k.steg_5_system_info,
                 k.steg_6_transkribering, k.steg_7_dtw_forval):
        try:
            steg()
        except Exception as e:
            traceback.print_exc()
            k.res.fel(f"{steg.__name__}: oväntat fel {type(e).__name__}: {e}")
    vakt.cancel()
    return k.res.sammanfatta()


if __name__ == "__main__":
    sys.exit(main())
