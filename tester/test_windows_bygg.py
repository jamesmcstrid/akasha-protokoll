"""Logiken i Windows-bygget (paketering/): beroendekontrollen, kontrollen av whisper-cli, byggverktygen och
kontrollen av sokvagar och talare. Allt gar att kora pa Linux utan pefile (de som behover det hoppas over)."""
import importlib.util
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

import hjalp  # noqa: F401  (sokvagar och tillfallig hemkatalog)

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAKETERING = os.path.join(ROT, "paketering")
sys.path.insert(0, PAKETERING)

import bygg_windows_verktyg as verktyg  # noqa: E402
import kontrollera_pe as pe  # noqa: E402
import kontrollera_whisper_cli_windows as kcli  # noqa: E402
import kontrollera_windows as kwin  # noqa: E402

HAR_PEFILE = importlib.util.find_spec("pefile") is not None
HAR_PIL = importlib.util.find_spec("PIL") is not None
X64 = pe.MASKINER["x64"]


def skriv(sokvag, data):
    with open(sokvag, "wb") as f:
        f.write(data)


def las_text(*delar):
    """En textfil i repot (UTF-8), som stangs direkt efter lasningen."""
    with open(os.path.join(ROT, *delar), encoding="utf-8") as f:
        return f.read()


def info(importer=(), fordrojda=(), maskin=X64, magic=pe.PE32_PLUS, fel=None):
    return pe.PEInfo(maskin, magic, list(importer), list(fordrojda), fel)


def trad(filer, ovriga=()):
    """filer: {"sokvag/fil.dll": PEInfo}; ovriga: filer utan PE-information (till exempel .py)."""
    per_katalog = {"": set()}
    for sokvag in list(filer) + list(ovriga):
        katalog, _, namn = sokvag.rpartition("/")
        delar = katalog.split("/") if katalog else []
        for i in range(len(delar) + 1):
            per_katalog.setdefault("/".join(delar[:i]), set())
        per_katalog[katalog].add(namn.lower())
    return pe.Trad(per_katalog, dict(filer))


class BeroendeLogik(unittest.TestCase):
    def test_import_i_samma_katalog_hittas(self):
        t = trad({"lib/sherpa-onnx-c-api.dll": info(["onnxruntime.dll", "KERNEL32.dll"]),
                  "lib/onnxruntime.dll": info(["KERNEL32.dll"])})
        r = pe.kontrollera(t)
        self.assertEqual(r.fel, [])
        self.assertEqual(r.vagar["samma katalog"], 1)

    def test_saknad_dll_ger_fel_med_bada_filnamnen(self):
        t = trad({"lib/sherpa-onnx-c-api.dll": info(["onnxruntime.dll", "KERNEL32.dll"])})
        r = pe.kontrollera(t)
        self.assertEqual(len(r.fel), 1)
        self.assertIn("lib/sherpa-onnx-c-api.dll", r.fel[0])
        self.assertIn("onnxruntime.dll", r.fel[0])
        self.assertEqual(list(r.saknas), ["onnxruntime.dll"])

    def test_versaler_spelar_ingen_roll(self):
        t = trad({"a.dll": info(["VCRUNTIME140.dll"]), "vcruntime140.DLL": info()})
        self.assertEqual(pe.kontrollera(t).fel, [])

    def test_fordrojd_import_kontrolleras(self):
        t = trad({"a.dll": info(["KERNEL32.dll"], fordrojda=["finns-inte.dll"])})
        r = pe.kontrollera(t)
        self.assertEqual(len(r.fel), 1)
        self.assertIn("finns-inte.dll (fordrojd)", r.fel[0])

    def test_fel_arkitektur(self):
        for maskin, namn in ((0x14C, "x86"), (0xAA64, "arm64")):
            r = pe.kontrollera(trad({"a.dll": info(maskin=maskin)}))
            self.assertEqual(len(r.fel), 1)
            self.assertIn(f"fel arkitektur, {namn}", r.fel[0])
        r = pe.kontrollera(trad({"a.dll": info(magic=0x10B)}))
        self.assertIn("inte PE32+", r.fel[0])
        self.assertEqual(pe.kontrollera(trad({"a.dll": info(maskin=0xAA64)}), maskin=0xAA64).fel, [])

    def test_fil_som_inte_ar_pe_ger_fel(self):
        r = pe.kontrollera(trad({"a.dll": info(fel="inte en giltig PE-fil (x)")}))
        self.assertEqual(r.fel, ["a.dll: inte en giltig PE-fil (x)"])

    def test_windows_egna_dll_behover_inte_finnas(self):
        t = trad({"a.dll": info(["KERNEL32.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "ext-ms-win-x.dll", "USER32.dll",
                                 "ucrtbase.dll", "dxgi.dll"])})
        r = pe.kontrollera(t)
        self.assertEqual(r.fel, [])
        self.assertEqual(len(r.system), 6)

    def test_vulkan_1_ar_system_dll_men_ggml_vulkan_levereras_av_oss(self):
        t = trad({"ggml-vulkan.dll": info(["vulkan-1.dll", "KERNEL32.dll"])})
        r = pe.kontrollera(t)
        self.assertEqual(r.fel, [])
        self.assertIn("vulkan-1", r.system)
        # ggml-vulkan.dll som saknas i paketet hittas inte hos System32
        t = trad({"a.dll": info(["ggml-vulkan.dll"])})
        self.assertEqual(len(pe.kontrollera(t, system_stammar={"ggml-vulkan"}).fel), 1)

    def test_c_runtimen_ar_aldrig_windows_egen_ens_med_system_katalog(self):
        t = trad({"a.dll": info(["vcruntime140.dll", "MSVCP140.dll", "vcomp140.dll"])})
        stammar = {"vcruntime140", "msvcp140", "vcomp140", "kernel32"}
        r = pe.kontrollera(t, system_stammar=stammar)
        self.assertEqual(len(r.fel), 3)

    def test_egna_bibliotek_godtas_aldrig_fran_system32(self):
        namn = ["onnxruntime.dll", "DirectML.dll", "libomp140.x86_64.dll", "libiomp5md.dll", "sherpa-onnx-c-api.dll",
                "whisper.dll", "ggml-base.dll", "ggml-cpu-haswell.dll"]
        t = trad({"a.dll": info(namn)})
        r = pe.kontrollera(t, system_stammar={pe.stam(n) for n in namn} | {"kernel32"})
        self.assertEqual(len(r.fel), len(namn), r.fel)
        self.assertEqual(r.system, {})
        # finns de i paketet hittas de som vanligt
        ok = trad({"a.dll": info(namn), **{n: info() for n in namn}})
        self.assertEqual(pe.kontrollera(ok, system_stammar={pe.stam(n) for n in namn}).fel, [])

    def test_vc_saknas_namnger_inte_onnxruntime(self):
        self.assertEqual(pe.vc_saknas(trad({"a.dll": info(["onnxruntime.dll", "VCRUNTIME140.dll"])})), ["VCRUNTIME140.dll"])

    def test_system_katalog_godtar_andra_dll_och_listar_dem(self):
        t = trad({"a.dll": info(["avicap32x.dll", "kernel32.dll"])})
        self.assertEqual(len(pe.kontrollera(t).fel), 1)
        r = pe.kontrollera(t, system_stammar={"avicap32x"})
        self.assertEqual(r.fel, [])
        self.assertEqual(list(r.system_utanfor_listan), ["avicap32x"])

    def test_python_delen_hittar_internal_och_roten(self):
        t = trad({"Prog.exe": info(["python312.dll"]), "_internal/python312.dll": info(),
                  "_internal/sherpa_onnx/lib/x.pyd": info(["python312.dll", "onnxruntime.dll"]),
                  "_internal/onnxruntime.dll": info()})
        self.assertEqual(pe.kontrollera(t).fel, [])

    def test_sjalvstandig_katalog_ser_inte_internal(self):
        filer = {"_internal/vcruntime140.dll": info(),
                 "_internal/whisper/whisper-cli.exe": info(["vcruntime140.dll", "whisper.dll"]),
                 "_internal/whisper/whisper.dll": info()}
        t = trad(filer)
        # utan "sjalvstandig" hittas vcruntime140.dll i _internal, med den ska den ligga i whisper/
        self.assertEqual(pe.kontrollera(t).fel, [])
        r = pe.kontrollera(t, sjalvstandiga=["_internal/whisper"])
        self.assertEqual(len(r.fel), 1)
        self.assertIn("_internal/whisper/whisper-cli.exe", r.fel[0])
        self.assertIn("vcruntime140.dll", r.fel[0])
        filer["_internal/whisper/vcruntime140.dll"] = info()
        self.assertEqual(pe.kontrollera(trad(filer), sjalvstandiga=["_internal/whisper"]).fel, [])

    def test_libs_katalogerna_hittas_av_python_delen(self):
        t = trad({"_internal/numpy/_core/x.pyd": info(["libscipy_openblas64_-abc.dll"]),
                  "_internal/numpy.libs/libscipy_openblas64_-abc.dll": info(["KERNEL32.dll"]),
                  "_internal/python312.dll": info()})
        r = pe.kontrollera(t)
        self.assertEqual(r.fel, [])
        self.assertEqual(r.vagar["numpy.libs"], 1)

    def test_vc_saknas_namnger_det_som_ska_kopieras(self):
        t = trad({"whisper-cli.exe": info(["whisper.dll", "VCRUNTIME140.dll", "KERNEL32.dll"]),
                  "ggml-cpu-x64.dll": info(["VCOMP140.DLL", "python312.dll"]),
                  "whisper.dll": info(["MSVCP140.dll"]), "msvcp140.dll": info()})
        self.assertEqual(pe.vc_saknas(t), ["VCOMP140.DLL", "VCRUNTIME140.dll"])

    def test_kopiera_runtime_kopierar_transitivt_och_stoppar_vid_saknad(self):
        mapp = tempfile.mkdtemp(prefix="akasha-pe-")
        self.addCleanup(shutil.rmtree, mapp, True)
        kalla = os.path.join(mapp, "kalla")
        ut = os.path.join(mapp, "ut")
        os.makedirs(kalla)
        os.makedirs(ut)
        for namn in ("whisper-cli.exe", "msvcp140.dll", "vcruntime140.dll"):
            skriv(os.path.join(ut if namn.endswith(".exe") else kalla, namn), b"x")
        importer = {"whisper-cli.exe": ["MSVCP140.dll", "VCOMP140X.dll"], "msvcp140.dll": ["VCRUNTIME140.dll"],
                    "vcruntime140.dll": []}

        def las(sokvag):
            return info(importer.get(os.path.basename(sokvag).lower(), []))

        def hitta(namn):
            s = os.path.join(kalla, namn.lower())
            return (s, None) if os.path.isfile(s) else (None, "sokte i kalla")

        res = verktyg.kontroll_hjalp.Resultat("prov")
        with mock.patch.object(pe, "las_pe", las), mock.patch.object(verktyg, "hitta_runtime", hitta):
            with mock.patch("builtins.print"):
                verktyg.kopiera_runtime(ut, res)
        self.assertEqual(sorted(n.lower() for n in os.listdir(ut)), ["msvcp140.dll", "vcruntime140.dll", "whisper-cli.exe"])
        self.assertEqual(len(res.fel_rader), 1)  # VCOMP140X.dll finns inte
        self.assertIn("VCOMP140X.dll", res.fel_rader[0])

    def test_hitta_runtime_tar_hogsta_redist_versionen_for_system32(self):
        mapp = tempfile.mkdtemp(prefix="akasha-pe-")
        self.addCleanup(shutil.rmtree, mapp, True)
        sys32 = os.path.join(mapp, "Windows", "System32")
        os.makedirs(sys32)
        skriv(os.path.join(sys32, "vcruntime140.dll"), b"sys")
        skriv(os.path.join(sys32, "msvcp140.dll"), b"sys")
        def redist(version, mapp_namn, fil, data):
            d = os.path.join(mapp, "VS", "VC", "Redist", "MSVC", version, "x64", mapp_namn)
            os.makedirs(d, exist_ok=True)
            skriv(os.path.join(d, fil), data)
            return os.path.join(d, fil)
        redist("14.9.1", "Microsoft.VC143.CRT", "vcruntime140.dll", b"gammal")
        ny = redist("14.44.35207", "Microsoft.VC143.CRT", "vcruntime140.dll", b"ny")
        redist("14.50.0", "Microsoft.VC143.CRT.debug_nonredist", "vcruntime140.dll", b"debug")
        omp = redist("14.44.35207", "Microsoft.VC143.OpenMP", "vcomp140.dll", b"omp")
        with mock.patch.dict(os.environ, {"SystemRoot": os.path.join(mapp, "Windows")}), \
             mock.patch.object(verktyg, "vs_kataloger", lambda: [os.path.join(mapp, "VS")]):
            self.assertEqual(verktyg.hitta_runtime("vcruntime140.dll")[0], ny)  # 14.44 > 14.9, inte debug
            self.assertEqual(verktyg.hitta_runtime("vcomp140.dll")[0], omp)
            # finns den inte i Redist tas System32
            self.assertEqual(verktyg.hitta_runtime("msvcp140.dll")[0], os.path.join(sys32, "msvcp140.dll"))
            sokvag, text = verktyg.hitta_runtime("finns-inte.dll")
            self.assertIsNone(sokvag)
            self.assertIn("finns-inte.dll", text)

    def test_kopiera_runtime_skriver_kalla_och_versioner(self):
        mapp = tempfile.mkdtemp(prefix="akasha-pe-")
        self.addCleanup(shutil.rmtree, mapp, True)
        ut = os.path.join(mapp, "ut")
        os.makedirs(ut)
        skriv(os.path.join(ut, "whisper-cli.exe"), b"x")
        kalla = os.path.join(mapp, "vcruntime140.dll")
        skriv(kalla, b"x")
        skriv(os.path.join(mapp, "VCRUNTIME140.dll"), b"y")  # samma fil i (falska) System32
        res = verktyg.kontroll_hjalp.Resultat("prov")
        with mock.patch.object(pe, "las_pe", lambda s: info(["VCRUNTIME140.dll"] if s.endswith(".exe") else [])), \
             mock.patch.object(verktyg, "hitta_runtime", lambda n: (kalla, None)), \
             mock.patch.object(verktyg, "filversion", lambda s: "14.44.35211.0"), \
             mock.patch.object(verktyg, "system32", lambda: mapp), mock.patch("builtins.print"):
            verktyg.kopiera_runtime(ut, res)
        self.assertEqual(len(res.ok_rader), 1)
        self.assertIn("version 14.44.35211.0", res.ok_rader[0])
        self.assertIn("samma fil i System32: version 14.44.35211.0", res.ok_rader[0])


def bygg_pe(maskin, importer):
    """En minimal PE32+-fil med en importtabell (for pefile-provet): varje DLL importerar en funktion."""
    n = len(importer)
    beskr = 20 * (n + 1)                      # importbeskrivningarna och en nollpost
    tradar = 0x1000 + beskr                   # en trad (8 byte + nollpost) per DLL
    namn_rva = tradar + 16 * n + 8 * n        # sedan hint/namn-poster (8 byte) och sist DLL-namnen
    delar, trad_data, hint_data, namn_data = bytearray(), bytearray(), bytearray(), bytearray()
    for i, dll in enumerate(importer):
        trad_rva = tradar + 16 * i
        hint_rva = tradar + 16 * n + 8 * i
        delar += struct.pack("<IIIII", trad_rva, 0, 0, namn_rva + len(namn_data), trad_rva)
        trad_data += struct.pack("<QQ", hint_rva, 0)
        hint_data += b"\0\0f\0".ljust(8, b"\0")
        namn_data += dll.encode("ascii") + b"\0"
    delar += b"\0" * 20 + trad_data + hint_data + namn_data
    sektion = bytes(delar).ljust(0x200, b"\0")
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, 0x20B)
    struct.pack_into("<Q", opt, 24, 0x140000000)
    struct.pack_into("<II", opt, 32, 0x1000, 0x200)
    struct.pack_into("<HH", opt, 48, 6, 0)
    struct.pack_into("<II", opt, 56, 0x2000, 0x200)
    struct.pack_into("<H", opt, 68, 3)
    struct.pack_into("<I", opt, 108, 16)
    struct.pack_into("<II", opt, 120, 0x1000, 20 * (len(importer) + 1))
    coff = struct.pack("<HHIIIHH", maskin, 1, 0, 0, 0, 240, 0x2022)
    rubrik = bytearray(b"MZ" + b"\0" * 58 + struct.pack("<I", 0x40)) + b"PE\0\0" + coff + opt
    rubrik += struct.pack("<8sIIIIIIHHI", b".idata", 0x200, 0x1000, 0x200, 0x200, 0, 0, 0, 0, 0xC0000040)
    return bytes(rubrik.ljust(0x200, b"\0")) + sektion


@unittest.skipUnless(HAR_PEFILE, "pefile saknas (finns i byggets venv, inte i testmiljon)")
class BeroendeMedPefile(unittest.TestCase):
    def skriv(self, mapp, namn, maskin, importer):
        with open(os.path.join(mapp, namn), "wb") as f:
            f.write(bygg_pe(maskin, importer))

    def test_las_pe_laser_importtabellen_och_arkitekturen(self):
        mapp = tempfile.mkdtemp(prefix="akasha-pe-")
        self.addCleanup(shutil.rmtree, mapp, True)
        self.skriv(mapp, "a.dll", X64, ["b.dll", "KERNEL32.dll"])
        i = pe.las_pe(os.path.join(mapp, "a.dll"))
        self.assertIsNone(i.fel)
        self.assertEqual((i.maskin, i.magic, i.importer), (X64, pe.PE32_PLUS, ["b.dll", "KERNEL32.dll"]))

    def test_hela_kontrollen_pa_riktiga_filer(self):
        mapp = tempfile.mkdtemp(prefix="akasha-pe-")
        self.addCleanup(shutil.rmtree, mapp, True)
        self.skriv(mapp, "a.dll", X64, ["b.dll", "KERNEL32.dll"])
        self.skriv(mapp, "b.dll", X64, ["KERNEL32.dll"])
        self.skriv(mapp, "c.dll", 0x14C, ["KERNEL32.dll"])
        with open(os.path.join(mapp, "d.dll"), "wb") as f:
            f.write(b"inte en pe-fil")
        r = pe.kontrollera(pe.las_trad(mapp))
        self.assertEqual(len(r.fel), 2, r.fel)
        self.assertTrue(any("c.dll: fel arkitektur, x86" in f for f in r.fel))
        self.assertTrue(any(f.startswith("d.dll: inte en giltig PE-fil") for f in r.fel))
        os.remove(os.path.join(mapp, "b.dll"))
        r = pe.kontrollera(pe.las_trad(mapp))
        self.assertTrue(any("a.dll: importerar b.dll" in f for f in r.fel), r.fel)

    def test_main_ger_slutkod_och_tabell(self):
        mapp = tempfile.mkdtemp(prefix="akasha-pe-")
        self.addCleanup(shutil.rmtree, mapp, True)
        self.skriv(mapp, "a.dll", X64, ["KERNEL32.dll"])
        tabell = os.path.join(mapp, "tabell.txt")
        with mock.patch("builtins.print"):
            self.assertEqual(pe.main([mapp, "--ut", tabell]), 0)
            self.skriv(mapp, "b.dll", X64, ["saknas.dll"])
            self.assertEqual(pe.main([mapp]), 1)
        with open(tabell, encoding="utf-8") as f:
            self.assertIn("a.dll  x64", f.read())


class DtwAvgorande(unittest.TestCase):
    OKANT_LADDNING = "error: unknown dtw preset 'finns-inte'\n"
    LADDNING = ("whisper_init_from_file_with_params_no_state: loading model from 'm.bin'\n"
                "whisper_model_load: type = 1\nwhisper_print_progress_callback: progress = 100%\n")
    OKANT_RADER = LADDNING + "whisper_init_state: dtw preset 'finns-inte' is unknown\n"

    def test_satt_laddning_nar_whisper_stoppar_fore_laddningen(self):
        self.assertEqual(kcli.valj_satt(self.OKANT_LADDNING, 1), ("laddning", None))

    def test_satt_rader_nar_modellen_laddas_och_en_dtw_rad_finns(self):
        self.assertEqual(kcli.valj_satt(self.OKANT_RADER, 0), ("rader", None))

    def test_ingen_slutsats_nar_det_inte_gar_att_avgora(self):
        for text, kod in (("", 1), (self.LADDNING, 0), (self.OKANT_LADDNING, None), (self.OKANT_LADDNING, 0),
                          (self.OKANT_LADDNING, 3221225781), (self.OKANT_LADDNING, -11)):
            satt, orsak = kcli.valj_satt(text, kod)
            self.assertIsNone(satt, (text, kod))
            self.assertIn("dtw-rad", orsak)

    def test_kant_forval_i_satt_laddning(self):
        ok, text = kcli.avgor_forval("laddning", self.OKANT_LADDNING, self.LADDNING, "medium", 0)
        self.assertTrue(ok, text)

    def test_okant_forval_i_satt_laddning_ger_fel(self):
        ok, text = kcli.avgor_forval("laddning", self.OKANT_LADDNING, "error: unknown dtw preset 'medium'\n", "medium", 1)
        self.assertFalse(ok)
        self.assertIn("modellen laddades aldrig", text)

    def test_okant_forval_i_satt_rader_ger_fel_men_kant_gar_igenom(self):
        okant = self.OKANT_RADER
        ok, _ = kcli.avgor_forval("rader", okant, self.LADDNING, "medium", 0)
        self.assertTrue(ok)
        ok, text = kcli.avgor_forval("rader", okant, self.LADDNING + "whisper_init_state: dtw preset 'medium' is unknown\n",
                                     "medium", 0)
        self.assertFalse(ok)
        self.assertIn("pahittat forval", text)

    def test_kodtext_for_windows_koder(self):
        self.assertIn("STATUS_DLL_NOT_FOUND", kcli.kodtext(3221225781))
        self.assertIn("0xC0000135", kcli.kodtext(-1073741515))
        self.assertEqual(kcli.kodtext(1), "kod 1")
        self.assertEqual(kcli.kodtext(None), "ingen slutkod")


def falsk_cli(mapp):
    """En startbar fil som kor tester/falsk_whisper_cli.py med den Python som kor testerna."""
    sokvag = os.path.join(mapp, "falsk-cli")
    with open(sokvag, "w", encoding="utf-8") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" "{os.path.join(ROT, "tester", "falsk_whisper_cli.py")}" "$@"\n')
    os.chmod(sokvag, os.stat(sokvag).st_mode | stat.S_IXUSR)
    modell = os.path.join(mapp, "modell.bin")
    with open(modell, "wb") as f:
        f.write(b"inte en riktig modell")
    return sokvag, modell


@unittest.skipIf(os.name == "nt", "den falska whisper-cli ar en sh-fil")
class KontrollAvWhisperCliMedFalskCli(unittest.TestCase):
    def kor(self, **miljo):
        mapp = tempfile.mkdtemp(prefix="akasha-kcli-")
        self.addCleanup(shutil.rmtree, mapp, True)
        cli, modell = falsk_cli(mapp)
        ordtider = os.path.join(mapp, "ordtider.json")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", **miljo}
        p = subprocess.run([sys.executable, os.path.join(PAKETERING, "kontrollera_whisper_cli_windows.py"), "--cli", cli,
                            "--modell", modell, "--arbetskatalog", os.path.join(mapp, "arb"), "--ordtider-ut", ordtider],
                           capture_output=True, env=env, timeout=240)
        return p.returncode, p.stdout.decode("utf-8", "replace"), ordtider

    def test_allt_ok(self):
        kod, ut, ordtider = self.kor()
        self.assertEqual(kod, 0, ut)
        self.assertIn("KONTROLL AV WHISPER-CLI: OK", ut)
        self.assertIn("OK: alla 14 flaggor finns i --help", ut)
        self.assertIn("OK: forvalet medium kanns igen", ut)
        self.assertIn("OK: ordtiderna kommer från DTW", ut)
        self.assertIn("Åsa Ölund", ut)  # modellkatalogen heter sa
        self.assertTrue(os.path.isfile(ordtider))

    def test_saknad_flagga_och_saknad_dtw_ger_fel_men_skriptet_fortsatter(self):
        kod, ut, _ = self.kor(FALSK_CLI_SAKNAR_FLAGGA="-nfa", FALSK_CLI_UTAN_DTW="1")
        self.assertEqual(kod, 1, ut)
        self.assertIn("FEL: whisper-cli saknar flaggorna -nfa", ut)
        self.assertIn("FEL: ordtiderna kommer inte från DTW", ut)
        self.assertIn("OK: forvalet medium kanns igen", ut)  # senare kontroller kordes anda
        self.assertIn("KONTROLL AV WHISPER-CLI: FEL", ut)

    def test_whisper_cli_som_avslutas_med_dll_kod_ger_fel_och_forklaring(self):
        kod, ut, _ = self.kor(FALSK_CLI_KOD="3221225781")
        self.assertEqual(kod, 1, ut)
        self.assertIn("FEL: motor._whispercpp() kastade MotorFel", ut)


class Byggverktyg(unittest.TestCase):
    def test_versionstexten_ar_ascii_och_gar_att_tolka_som_pyinstaller_gor(self):
        text = verktyg.versionstext("0.2.0", "17")
        text.encode("ascii")
        funna = {}

        def klass(namn):
            def skapa(*a, **kw):
                return (namn, a, kw)
            return skapa

        miljo = {n: klass(n) for n in ("VSVersionInfo", "FixedFileInfo", "StringFileInfo", "StringTable", "StringStruct",
                                       "VarFileInfo", "VarStruct")}
        ver = eval(compile(text, "versionsfil", "eval"), miljo)  # noqa: S307  (egen text, samma sak som PyInstaller gor)
        ffi = ver[2]["ffi"]
        self.assertEqual(ffi[2]["filevers"], (0, 2, 0, 17))
        strangar = {st[1][0]: st[1][1] for st in ver[2]["kids"][0][1][0][0][1][1]}
        funna.update(strangar)
        self.assertEqual(funna["LegalCopyright"], "© 2026 Dennis Fredin. Apache-2.0.")
        self.assertEqual(funna["ProductName"], "Akasha Protokoll")
        self.assertEqual(funna["OriginalFilename"], "Akasha Protokoll.exe")
        self.assertEqual(funna["FileVersion"], "0.2.0.17")

    def test_forbjudna_namn(self):
        for namn, katalog in (("faster_whisper", True), ("ctranslate2", True), ("ctranslate2.dll", False),
                              ("tokenizers", True), ("huggingface_hub", True), ("hf_xet", True),
                              ("tkinter", True), ("_tkinter.pyd", False), ("tcl86t.dll", False)):
            self.assertTrue(verktyg.ar_forbjudet(namn, katalog), namn)
        # onnxruntime ska vara med (Pianissimo), och sherpa-onnx har en egen onnxruntime.dll
        for namn in ("onnxruntime.dll", "onnxruntime_pybind11_state.pyd", "sherpa_onnx", "av", "numpy", "static"):
            self.assertFalse(verktyg.ar_forbjudet(namn, False), namn)
        for namn in ("onnxruntime", "onnxruntime-1.32.0.dist-info", "onnx_asr", "sentencepiece"):
            self.assertFalse(verktyg.ar_forbjudet(namn, True), namn)

    def test_hitta_forbjudna_i_ett_trad(self):
        mapp = tempfile.mkdtemp(prefix="akasha-verktyg-")
        self.addCleanup(shutil.rmtree, mapp, True)
        for sokvag in ("_internal/sherpa_onnx/lib/onnxruntime.dll", "_internal/ctranslate2/ctranslate2.dll",
                       "_internal/onnxruntime/capi/onnxruntime.dll", "_internal/numpy/x.pyd"):
            os.makedirs(os.path.join(mapp, os.path.dirname(sokvag)), exist_ok=True)
            skriv(os.path.join(mapp, sokvag), b"x")
        funna = [os.path.relpath(f, mapp).replace(os.sep, "/") for f in verktyg.hitta_forbjudna(mapp)]
        self.assertEqual(funna, ["_internal/ctranslate2", "_internal/ctranslate2/ctranslate2.dll"])

    def test_pianissimo_i_ett_trad(self):
        mapp = tempfile.mkdtemp(prefix="akasha-verktyg-")
        self.addCleanup(shutil.rmtree, mapp, True)
        filer = ("_internal/onnx_asr/preprocessors/data/fbanks.npz", "_internal/onnx_asr-0.12.0.dist-info/METADATA",
                 "_internal/onnxruntime/capi/onnxruntime.dll", "_internal/onnxruntime/capi/onnxruntime_pybind11_state.pyd",
                 "_internal/sentencepiece/_sentencepiece.cp312-win_amd64.pyd")
        for sokvag in filer:
            os.makedirs(os.path.join(mapp, os.path.dirname(sokvag)), exist_ok=True)
            skriv(os.path.join(mapp, sokvag), b"x")
        self.assertEqual(verktyg.saknad_pianissimo(mapp), [])
        os.remove(os.path.join(mapp, filer[2]))  # sherpa-onnx egen onnxruntime.dll racker inte
        os.makedirs(os.path.join(mapp, "_internal/sherpa_onnx/lib"))
        skriv(os.path.join(mapp, "_internal/sherpa_onnx/lib/onnxruntime.dll"), b"x")
        self.assertEqual(verktyg.saknad_pianissimo(mapp), ["onnxruntime/capi/onnxruntime.dll"])

    def test_zip_har_katalogen_overst_och_uppackningen_kan_ligga_under_asa_olund(self):
        mapp = tempfile.mkdtemp(prefix="akasha-verktyg-")
        self.addCleanup(shutil.rmtree, mapp, True)
        dist = os.path.join(mapp, "dist", "Akasha Protokoll")
        os.makedirs(os.path.join(dist, "_internal", "whisper"))
        skriv(os.path.join(dist, "Akasha Protokoll.exe"), b"exe")
        skriv(os.path.join(dist, "_internal", "whisper", "whisper-cli.exe"), b"cli")
        zipfil = os.path.join(mapp, "dist", "ut.zip")
        self.assertEqual(verktyg.packa_zip(dist, zipfil), 2)
        import zipfile
        with zipfile.ZipFile(zipfil) as z:
            self.assertEqual(sorted(z.namelist()), ["Akasha Protokoll/Akasha Protokoll.exe",
                                                    "Akasha Protokoll/_internal/whisper/whisper-cli.exe"])
        mal = os.path.join(mapp, "uppackad", "Åsa Ölund")
        with mock.patch("builtins.print"):
            self.assertEqual(verktyg.main(["uppacka", zipfil, mal]), 0)
        with open(os.path.join(mal, "Akasha Protokoll", "_internal", "whisper", "whisper-cli.exe"), "rb") as f:
            self.assertEqual(f.read(), b"cli")

    def test_storlekar_sorterar_storst_forst(self):
        mapp = tempfile.mkdtemp(prefix="akasha-verktyg-")
        self.addCleanup(shutil.rmtree, mapp, True)
        os.makedirs(os.path.join(mapp, "stor"))
        skriv(os.path.join(mapp, "stor", "a"), b"x" * 100)
        skriv(os.path.join(mapp, "liten"), b"x" * 10)
        self.assertEqual(verktyg.storlekar_i(mapp), [(100, "stor"), (10, "liten")])

    @unittest.skipUnless(HAR_PIL, "Pillow saknas (finns i byggets venv pa Windows)")
    def test_ikonen_far_alla_sju_storlekarna(self):
        mapp = tempfile.mkdtemp(prefix="akasha-verktyg-")
        self.addCleanup(shutil.rmtree, mapp, True)
        res = verktyg.kontroll_hjalp.Resultat("prov")
        ico = os.path.join(mapp, "ikon.ico")
        verktyg.skapa_ikon(os.path.join(PAKETERING, "ikon-1024.png"), ico, res)
        self.assertEqual(res.fel_rader, [])
        self.assertTrue(res.ok_rader)


def ladda_kontrollera(plattform):
    """paketering/kontrollera.py inladdad med en annan sys.platform (konstanterna rakas ut vid import)."""
    spec = importlib.util.spec_from_file_location(f"kontrollera_{plattform}", os.path.join(PAKETERING, "kontrollera.py"))
    modul = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "platform", plattform):
        spec.loader.exec_module(modul)
    return modul


class KontrolleraPerPlattform(unittest.TestCase):
    def setUp(self):
        self.hem = tempfile.mkdtemp(prefix="akasha-kontr-")
        self.addCleanup(shutil.rmtree, self.hem, True)

    def miljo(self, plattform, extra=None):
        k = ladda_kontrollera(plattform)
        k.args = mock.Mock(port=8611)
        with mock.patch.dict(os.environ, extra or {}, clear=True):
            return k, k.programmiljo(self.hem)

    @unittest.skipIf(os.name == "nt", "os.environ skiljer inte pa stora och sma bokstaver pa Windows: tmpdir och TMPDIR blir en nyckel")
    def test_linux_och_mac_far_samma_miljo_som_forut(self):
        for plattform in ("linux", "darwin"):
            k, miljo = self.miljo(plattform, {"HTTPS_PROXY": "http://p:1", "TMPDIR": "/t"})
            self.assertEqual(miljo, {"HOME": self.hem, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PORT": "8611",
                                     "LANG": "sv_SE.UTF-8", "TMPDIR": "/t", "HTTPS_PROXY": "http://p:1"})
            self.assertEqual(k.START_TIDSGRANS, 60)
        self.assertEqual(ladda_kontrollera("linux").NY_PROGRAMKATALOG, (".local", "share", "akasha-protokoll"))
        self.assertEqual(ladda_kontrollera("darwin").NY_PROGRAMKATALOG, ("Library", "Application Support", "Akasha Protokoll"))

    def test_windows_miljon_har_userprofile_localappdata_och_temp_under_hem(self):
        k, miljo = self.miljo("win32", {"SYSTEMROOT": "C:\\Windows", "HOME": "/ska/inte/med", "PATH": "/ska/inte/med",
                                        "NUMBER_OF_PROCESSORS": "4", "HTTPS_PROXY": "http://p:1"})
        self.assertEqual(miljo["USERPROFILE"], self.hem)
        self.assertEqual(miljo["LOCALAPPDATA"], os.path.join(self.hem, "AppData", "Local"))
        self.assertEqual(miljo["TEMP"], os.path.join(self.hem, "AppData", "Local", "Temp"))
        self.assertEqual(miljo["TMP"], miljo["TEMP"])
        self.assertTrue(os.path.isdir(miljo["TEMP"]))
        self.assertEqual(miljo["SYSTEMROOT"], "C:\\Windows")
        self.assertEqual(miljo["PORT"], "8611")
        self.assertEqual(miljo["NUMBER_OF_PROCESSORS"], "4")
        self.assertEqual(miljo["HTTPS_PROXY"], "http://p:1")
        self.assertNotIn("HOME", miljo)
        self.assertNotIn("/ska/inte/med", miljo["PATH"])
        self.assertTrue(miljo["PATH"].startswith(os.path.join("C:\\Windows", "System32")))
        self.assertEqual(k.NY_PROGRAMKATALOG, ("AppData", "Local", "Akasha Protokoll"))
        self.assertEqual(k.GAMMAL_PROGRAMKATALOG, ("AppData", "Local", "Akasha Meet"))
        self.assertEqual(k.START_TIDSGRANS, 120)

    def test_kontrollera_stoppar_som_forut_men_fortsatter_med_flaggan(self):
        k = ladda_kontrollera("linux")
        self.assertFalse(k.FORTSATT)
        with mock.patch("builtins.print"), self.assertRaises(SystemExit) as stopp:
            k.kontrollera(False, "ok", "fel ett")
        self.assertEqual(stopp.exception.code, 1)
        self.assertEqual(k.fel_lista, [])  # utan flaggan samlas inget
        with mock.patch("builtins.print") as skriv:
            self.assertTrue(k.kontrollera(True, "allt ar bra", "x"))
        skriv.assert_called_once_with("OK: allt ar bra", flush=True)
        k.FORTSATT = True
        with mock.patch("builtins.print") as skriv:
            self.assertFalse(k.kontrollera(False, "ok", "fel ett"))
            self.assertFalse(k.kontrollera(False, "ok", "fel tva"))
            self.assertTrue(k.kontrollera(True, "ok tre", "x"))  # fortsatter efter felen
        self.assertEqual(k.fel_lista, ["fel ett", "fel tva"])
        skriv.assert_any_call("FEL: fel ett", flush=True)
        with mock.patch("builtins.print") as skriv:
            k.sammanfatta_fel()
        skriv.assert_any_call("--- 2 FEL i kontrollen ---", flush=True)
        skriv.assert_any_call("FEL: fel tva", flush=True)
        # slut() (programmet startar eller svarar inte) stoppar anda, med listan
        with mock.patch("builtins.print") as skriv, self.assertRaises(SystemExit):
            k.slut("startar inte")
        self.assertEqual(k.fel_lista[-1], "startar inte")
        skriv.assert_any_call("--- 3 FEL i kontrollen ---", flush=True)

    def test_windows_lagger_inte_den_gamla_programkatalogen_och_tal_att_loggen_saknas(self):
        text = las_text("paketering", "kontrollera.py")
        # Windows: bara inspelningsmappen flyttas, med en INFO-rad om varfor; Mac och Linux oforandrade
        self.assertIn("if not WIN:\n        flyttpar.append((gammal_program", text)
        self.assertIn("if not WIN:\n        kontrolleras.append((gammal_program", text)
        self.assertIn("kan inte byta namn medan", text)
        self.assertIn("ligger i programkatalogen", text)
        # loggfilen far saknas: ingen open() utan isfile i steg 9, 9b och slut()
        for rad in text.splitlines():
            if "open(logg" in rad:
                self.assertTrue("os.path.isfile(logg)" in rad or "if sokvag" in rad or "with open(logg" in rad, rad)
        self.assertIn('read() if os.path.isfile(logg) else ""', text)

    def test_formaten_skickas_till_transcribe_och_400_med_ljudet_kunde_inte_lasas_ger_fel(self):
        import http.server
        import threading

        anrop = []

        class Handlare(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                langd = int(self.headers.get("Content-Length", 0))
                kropp = self.rfile.read(langd)
                namn = kropp.split(b'filename="')[1].split(b'"')[0].decode()
                anrop.append((self.path, namn, self.headers.get("X-Akasha-Protokoll")))
                if namn == "mp3.mp3":
                    status, text = 400, '{"error": "ljudet kunde inte lasas: Invalid data"}'
                else:
                    status, text = 502, '{"error": "whisper-cli avslutades med kod 3"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(text.encode())

            def log_message(self, *a):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handlare)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        katalog = os.path.join(ROT, "testljud", "format")
        antal = len(os.listdir(katalog))

        k = ladda_kontrollera("linux")
        k.args = mock.Mock(port=server.server_address[1])
        with mock.patch("builtins.print"), self.assertRaises(SystemExit):  # utan flaggan: stopp vid forsta felet
            k.kontrollera_format(katalog)
        k = ladda_kontrollera("linux")
        k.args = mock.Mock(port=server.server_address[1])
        k.FORTSATT = True
        anrop.clear()
        with mock.patch("builtins.print"):
            k.kontrollera_format(katalog)
        self.assertEqual(len(anrop), antal)  # alla tolv filer skickades
        self.assertTrue(all(a[0] == "/transcribe" and a[2] == "1" for a in anrop))
        self.assertEqual(len(k.fel_lista), 1)  # bara mp3.mp3 (400); 502 betyder att avkodningen lyckades
        self.assertIn("mp3.mp3", k.fel_lista[0])
        self.assertIn("ljudet kunde inte läsas", k.fel_lista[0])
        self.assertIn("kontrollera_format(os.path.join(ROT, \"testljud\", \"format\"))",
                      las_text("paketering", "kontrollera.py"))

    def test_flaggan_finns_och_flodet_anger_den_inte_for_mac(self):
        text = las_text("paketering", "kontrollera.py")
        self.assertIn('"--fortsatt-efter-fel"', text)
        mac = las_text(".github", "workflows", "mac-app.yml")
        self.assertNotIn("fortsatt-efter-fel", mac)
        win = las_text(".github", "workflows", "windows-app.yml")
        self.assertIn("--fortsatt-efter-fel", win)

    def test_tasklist_hittar_bara_rader_med_avbildningens_namn(self):
        k = ladda_kontrollera("win32")
        svar = mock.Mock(stdout=b'"whisper-cli.exe","123","Console","1","50 000 K"\r\n')
        with mock.patch.object(k.subprocess, "run", return_value=svar) as kor:
            self.assertEqual(len(k.tasklist("whisper-cli.exe")), 1)
        self.assertEqual(kor.call_args[0][0][:3], ["tasklist", "/FI", "IMAGENAME eq whisper-cli.exe"])
        svar = mock.Mock(stdout=b"INFO: No tasks are running which match the specified criteria.\r\n")
        with mock.patch.object(k.subprocess, "run", return_value=svar):
            self.assertEqual(k.tasklist("whisper-cli.exe"), [])


@unittest.skipIf(os.name == "nt", "pa Windows kor flodet windows-app.yml skriptet pa riktigt, med den riktiga rostmodellen")
class KontrollAvSokvagarOchTalare(unittest.TestCase):
    """paketering/kontrollera_windows.py med en falsk sherpa_onnx (tester/falsk_sherpa): ingen riktig rostmodell."""

    def kor(self, modellinnehall):
        mapp = tempfile.mkdtemp(prefix="akasha-kwin-")
        self.addCleanup(shutil.rmtree, mapp, True)
        hem = os.path.join(mapp, "Åsa Ölund")
        modell = os.path.join(kwin.modellkatalog(hem), "talare", "nemo_en_titanet_small.onnx")
        os.makedirs(os.path.dirname(modell))
        skriv(modell, modellinnehall.ljust(40257283, b"x"))
        ordtider = os.path.join(mapp, "ordtider.json")
        with open(ordtider, "w", encoding="utf-8") as f:
            f.write('[[1.0, 1.4, " Hej"], [1.6, 2.0, " Åsa"], [2.2, 2.6, " och"], [2.8, 3.2, " välkomna"], [3.4, 3.8, "."]]')
        env = {**os.environ, "PYTHONPATH": os.path.join(ROT, "tester", "falsk_sherpa"), "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([sys.executable, os.path.join(PAKETERING, "kontrollera_windows.py"), "--hem", hem,
                            "--ordtider", ordtider], capture_output=True, env=env, timeout=240)
        return p.returncode, p.stdout.decode("utf-8", "replace")

    def test_modellen_laddas_fran_sokvagen_och_dela_upp_gar(self):
        kod, ut = self.kor(b"en modell")
        fel = [r for r in ut.splitlines() if r.startswith("FEL:")]
        # den enda avvikelsen: modellen ar inte den riktiga (sha256), allt annat ska vara OK
        self.assertEqual(len([f for f in fel if "sha256" in f]), 2, ut)  # raden i steg 1 och i sammanfattningen
        self.assertEqual(len(fel), 2, ut)
        self.assertEqual(kod, 1)
        self.assertIn("OK: röstavtrycket har längd 8", ut)
        self.assertIn("OK: talare.dela_upp() (två talare, påhittade ordtider)", ut)
        self.assertIn("OK: talare.dela_upp() (en talare, riktiga ordtider", ut)
        self.assertIn("avkodad med PyAV", ut)

    def test_en_krasch_i_sherpa_ger_fel_med_sokvagen_och_diagnos(self):
        kod, ut = self.kor(b"KRASCH")
        self.assertEqual(kod, 1)
        self.assertIn("FEL: sherpa-onnx klarade inte röstmodellen på sökvägen", ut)
        self.assertIn("Åsa Ölund", ut)
        self.assertIn("INFO: diagnos: relativ sokvag med arbetskatalogen satt till modellkatalogen: fungerade inte", ut)
        self.assertIn("INFO: diagnos: en kopia i en ASCII-katalog", ut)
        self.assertIn("FEL: talare.dela_upp()", ut)  # kraschen stoppar inte skriptet


class Kontrollskripten(unittest.TestCase):
    def test_skripten_utan_nagon_utskrift_som_inte_ar_utf8(self):
        # Actions-maskinens konsol ar inte UTF-8: en utskrift med a-ring och pilar far inte krascha skripten.
        kod = textwrap.dedent("""
            import io, sys
            sys.path.insert(0, sys.argv[1])
            sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
            import kontroll_hjalp
            kontroll_hjalp.utf8_utskrift()
            print("Åsa Ölund → ok")
            sys.stdout.flush()
            sys.__stdout__.write("klart\\n")
        """)
        p = subprocess.run([sys.executable, "-c", kod, PAKETERING], capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))


class FilernaStangs(unittest.TestCase):
    """Testerna som laser kontrollera.py och flodena stanger filerna: ResourceWarning ger fel."""

    TESTER = ("test_windows_lagger_inte_den_gamla_programkatalogen_och_tal_att_loggen_saknas",
              "test_formaten_skickas_till_transcribe_och_400_med_ljudet_kunde_inte_lasas_ger_fel",
              "test_flaggan_finns_och_flodet_anger_den_inte_for_mac")

    def test_ingen_resourcewarning(self):
        import gc
        import warnings
        fangade = []
        gammal_hook = sys.unraisablehook
        sys.unraisablehook = lambda u: fangade.append(repr(u.exc_value))  # varningar nar en fil stads bort
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", ResourceWarning)
                for namn in self.TESTER:
                    res = unittest.TestResult()
                    KontrolleraPerPlattform(namn).run(res)
                    self.assertEqual((res.errors, res.failures), ([], []), namn)
                gc.collect()
        finally:
            sys.unraisablehook = gammal_hook
        self.assertEqual(fangade, [])


if __name__ == "__main__":
    unittest.main()
