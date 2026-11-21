"""Licenserna i programmen: paketering/samla_licenser.py (med pahittade dist-info-kataloger i en tillfallig katalog) och
paketering/kontrollera_licenser.py (med ett pahittat program). Kraver varken PyInstaller eller ett riktigt bygge."""
import importlib
import io
import os
import re
import shutil
import sys
import tempfile
import tokenize
import unittest
from unittest import mock

import hjalp  # noqa: F401  (sokvagar och tillfallig hemkatalog)

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAKETERING = os.path.join(ROT, "paketering")
sys.path.insert(0, PAKETERING)

import kontroll_hjalp  # noqa: E402
import kontrollera_licenser as kl  # noqa: E402
import samla_licenser as sl  # noqa: E402

MIT = "MIT License\n\nCopyright (c) 2026 Testaren\n\nPermission is hereby granted, free of charge ...\n"


def las(*delar):
    with open(os.path.join(ROT, *delar), encoding="utf-8") as f:
        return f.read()


def skriv(sokvag, data):
    os.makedirs(os.path.dirname(sokvag), exist_ok=True)
    with open(sokvag, "wb") as f:
        f.write(data.encode("utf-8") if isinstance(data, str) else data)


class FalskaPaket:
    """En site-packages-katalog med pahittade paket: METADATA, RECORD och filerna."""

    def __init__(self, test):
        self.rot = tempfile.mkdtemp(prefix="akasha-licens-paket-")
        test.addCleanup(shutil.rmtree, self.rot, True)

    def paket(self, namn, version, filer, licensfiler=None, metadata=None, top_level=None):
        """filer: {relativ sokvag: innehall}; licensfiler: {namn i dist-info: text}."""
        info = f"{namn.replace('-', '_')}-{version}.dist-info"
        alla = dict(filer)
        rader = [f"Metadata-Version: 2.4", f"Name: {namn}", f"Version: {version}"]
        for k, v in (metadata or {}).items():
            rader.append(f"{k}: {v}")
        alla[f"{info}/METADATA"] = "\n".join(rader) + "\n"
        for n, text in (licensfiler or {}).items():
            alla[f"{info}/{n}"] = text
        if top_level:
            alla[f"{info}/top_level.txt"] = "\n".join(top_level) + "\n"
        for rel, data in alla.items():
            skriv(os.path.join(self.rot, rel), data)
        skriv(os.path.join(self.rot, info, "RECORD"), "".join(f"{r},,\n" for r in alla) + f"{info}/RECORD,,\n")
        return self

    def dists(self):
        # importlib.metadata minns katalogens innehall efter dess mtime: ett paket som lagts till inom samma tick syns
        # annars inte
        importlib.invalidate_caches()
        return sl.distributioner([self.rot])

    def filer(self, namn):
        """Alla filer i paketet som (namn i programmet, kalla), som i provet."""
        return sl.alla_installerade(self.dists())[sl.normnamn(namn)]

    def sokvag(self, rel):
        return os.path.join(self.rot, rel)


def ffmpeg_lib(licens="LGPL version 2.1 or later", namn="avcodec"):
    return b"\x00" * 16 + f"lib{namn} license: {licens}".encode() + b"\x00" * 16


def ffmpeg_katalog(test, kompilator=True, gcc=True, mingw=True):
    mapp = tempfile.mkdtemp(prefix="akasha-licens-ffmpeg-")
    test.addCleanup(shutil.rmtree, mapp, True)
    skriv(os.path.join(mapp, "COPYING.LGPLv2.1"), "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1, February 1999\n")
    skriv(os.path.join(mapp, "LICENSE.md"), "# License\nMost files in FFmpeg are under the GNU LGPL version 2.1 or later.\n")
    skriv(os.path.join(mapp, "CREDITS"), "See the Git history of the project.\n")
    skriv(os.path.join(mapp, "configure.txt"), "--prefix=/x --disable-everything --enable-shared\n")
    rader = ["FFmpeg 6.1.6", "tagg: n6.1.6", "commit: f1e3a2bf7a2f2cde936d1ed97f09a26853d20125",
             "kalla: https://github.com/FFmpeg/FFmpeg.git"] + (["kompilator: cc (Rev3, Built by MSYS2 project) 15.2.0"] if kompilator else [])
    rader.append("system: windows" if gcc else "system: linux")
    skriv(os.path.join(mapp, "KALLA.txt"), "\n".join(rader) + "\n")
    if gcc:
        skriv(os.path.join(mapp, "COPYING3"), "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n")
        skriv(os.path.join(mapp, "COPYING.RUNTIME"), "GCC RUNTIME LIBRARY EXCEPTION\nVersion 3.1, 31 March 2009\n")
        if mingw:
            skriv(os.path.join(mapp, "COPYING.MinGW-w64-runtime.txt"), "MinGW-w64 runtime licensing\n***************************\n")
            skriv(os.path.join(mapp, "COPYING.winpthreads.txt"), "Copyright (c) 2011 mingw-w64 project\n")
    return mapp


def whisper_katalog(test):
    mapp = tempfile.mkdtemp(prefix="akasha-licens-whisper-")
    test.addCleanup(shutil.rmtree, mapp, True)
    skriv(os.path.join(mapp, "LICENSE"), "MIT License\n\nCopyright (c) 2023-2024 The ggml authors\n")
    skriv(os.path.join(mapp, "KALLA.txt"), "whisper.cpp v1.9.5\ntagg: v1.9.5\ncommit: d1be6fde11ac6e0407606b4e42fe72d34add8037\n"
                                           "kalla: https://github.com/ggml-org/whisper.cpp\n")
    return mapp


def rader_i_forteckningen(katalog):
    with open(os.path.join(katalog, sl.FORTECKNING), encoding="utf-8") as f:
        text = f.read().splitlines()
    i = text.index(sl.STRECK)
    ut = []
    for r in text[i + 1:]:
        if not r.strip():
            break
        ut.append(r.split(sl.SEP))
    return text, ut


class SamlaLicenser(unittest.TestCase):
    def setUp(self):
        self.p = FalskaPaket(self)
        self.ut = os.path.join(tempfile.mkdtemp(prefix="akasha-licens-ut-"), "licenser")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.ut), True)

    def samla(self, paket, ovriga=(), plattform="linux", **kw):
        return sl.samla(paket, list(ovriga), self.ut, plattform, "0.2.0", dists=self.p.dists(), **kw)

    def lagg_mittpaket(self):
        self.p.paket("mittpaket", "1.0", {"mittpaket/__init__.py": "", "mittpaket/data.bin": "x"},
                     licensfiler={"licenses/LICENSE": MIT, "licenses/NOTICE": "Mittpaket har en notis.\n"},
                     metadata={"License-Expression": "MIT", "Project-URL": "Source, https://example.org/mittpaket"})

    def test_paket_med_licensfil_ger_en_fil_och_en_rad(self):
        self.lagg_mittpaket()
        res = self.samla({"mittpaket": self.p.filer("mittpaket")})
        self.assertEqual(res.fel, [])
        text, rader = rader_i_forteckningen(self.ut)
        self.assertEqual(text[0], "Licenser för Akasha Protokoll 0.2.0 (Linux (provbygge))")
        self.assertTrue(all(len(r) == 5 for r in rader), rader)
        self.assertEqual(rader[0][0], "Akasha Protokoll")
        self.assertIn(["mittpaket", "1.0", "MIT", "https://example.org/mittpaket", "mittpaket.txt"], rader)
        namn = [r[0] for r in rader]
        for del_ in ("Python", "Typsnittet Anton", "Typsnittet Instrument Sans"):
            self.assertIn(del_, namn)
        self.assertNotIn("whisper.cpp", namn)  # Linux-provet har ingen whisper-cli
        for r in rader:  # varje komponent har sin fil
            self.assertTrue(os.path.getsize(os.path.join(self.ut, r[4])) > 0, r)
        paketfil = las_fil(os.path.join(self.ut, "mittpaket.txt"))
        self.assertTrue(paketfil.startswith("mittpaket 1.0\nLicens: MIT\nKälla: https://example.org/mittpaket\n"))
        self.assertIn("Copyright (c) 2026 Testaren", paketfil)
        self.assertIn("===== mittpaket-1.0.dist-info/licenses/NOTICE =====", paketfil)
        self.assertIn("Licensed under the Apache License", las_fil(os.path.join(self.ut, "akasha-protokoll.txt")))
        self.assertIn("SIL OPEN FONT LICENSE", las_fil(os.path.join(self.ut, "typsnitt-anton.txt")).upper())
        self.assertIn("PSF", las_fil(os.path.join(self.ut, "python.txt")).upper())
        self.assertNotIn(sl.MARKERING_OFULLSTANDIG, "\n".join(text[:3]))
        self.assertIn("KB-Whisper", "\n".join(text))  # modellerna namns i inledningen, inte som komponenter
        self.assertNotIn("KB-Whisper", " ".join(namn))

    def test_paket_utan_licensfil_ar_fel_och_forteckningen_markeras(self):
        self.lagg_mittpaket()
        self.p.paket("utanlicens", "2.0", {"utanlicens/__init__.py": ""}, metadata={"License": "MIT"})
        res = self.samla({"mittpaket": self.p.filer("mittpaket"), "utanlicens": self.p.filer("utanlicens")})
        self.assertEqual(len(res.fel), 1, res.fel)
        self.assertIn("utanlicens 2.0", res.fel[0])
        self.assertIn("ingen licensfil", res.fel[0])
        text, rader = rader_i_forteckningen(self.ut)
        self.assertTrue(text[0].startswith(sl.MARKERING_OFULLSTANDIG + ":"))
        self.assertIn("utanlicens 2.0", text[1])
        self.assertNotIn("utanlicens", [r[0] for r in rader])

    def test_kommandoraden_ger_slutkod_1_vid_fel(self):
        self.p.paket("utanlicens", "2.0", {"utanlicens/__init__.py": ""})
        with mock.patch.object(sl, "distributioner", return_value=self.p.dists()), mock.patch("builtins.print"):
            kod = sl.main(["--ut", self.ut, "--plattform", "linux", "--alla-installerade"])
        self.assertEqual(kod, 1)
        self.lagg_mittpaket()
        dists = {k: v for k, v in self.p.dists().items() if k != "utanlicens"}
        with mock.patch.object(sl, "distributioner", return_value=dists), mock.patch("builtins.print"):
            self.assertEqual(sl.main(["--ut", self.ut, "--plattform", "linux", "--alla-installerade"]), 0)

    def test_provet_hoppar_over_byggverktygen(self):
        self.lagg_mittpaket()
        self.p.paket("pyinstaller", "6.22.3", {"PyInstaller/__init__.py": ""}, licensfiler={"COPYING.txt": "GPL"})
        self.p.paket("setuptools", "84.2.1", {"setuptools/__init__.py": ""})  # ingen licens: far inte ge fel
        self.p.paket("faster-whisper", "1.0.3", {"faster_whisper/__init__.py": ""})
        self.assertEqual(sorted(sl.alla_installerade(self.p.dists())), ["mittpaket"])

    def test_samma_projekt_far_texten_fran_syskonet_med_samma_version(self):
        self.p.paket("sherpa_onnx", "2.0.1", {"sherpa_onnx/__init__.py": ""}, licensfiler={"licenses/LICENSE": "Apache License 2.0\n"},
                     metadata={"License": "Apache licensed, as found in the LICENSE file"})
        self.p.paket("sherpa-onnx-core", "2.0.1", {"sherpa_onnx/lib/sherpa-onnx-c-api.dll": "x"},
                     metadata={"License": "Apache-2.0"})
        res = self.samla({"sherpa-onnx-core": self.p.filer("sherpa-onnx-core")})
        self.assertEqual(res.fel, [])
        text = las_fil(os.path.join(self.ut, "sherpa-onnx-core.txt"))
        self.assertIn("samma projekt (k2-fsa/sherpa-onnx)", text)
        self.assertIn("Apache License 2.0", text)
        self.assertIn("sherpa_onnx/lib/sherpa-onnx-c-api.dll (paketets eget bibliotek)", text)

    def test_samma_projekt_med_annan_version_ar_fel(self):
        self.p.paket("sherpa_onnx", "2.0.0", {"sherpa_onnx/__init__.py": ""}, licensfiler={"LICENSE": "Apache\n"})
        self.p.paket("sherpa-onnx-core", "2.0.1", {"sherpa_onnx/lib/x.txt": "x"})
        res = self.samla({"sherpa-onnx-core": self.p.filer("sherpa-onnx-core")})
        self.assertEqual(len(res.fel), 1)
        self.assertIn("annan version (2.0.0)", res.fel[0])

    def test_onnxruntime_far_texterna_ur_paketering_licenstexter(self):
        self.p.paket("sherpa_onnx", "2.0.1", {"sherpa_onnx/__init__.py": ""}, licensfiler={"LICENSE": "Apache\n"})
        self.p.paket("sherpa-onnx-core", "2.0.1", {"sherpa_onnx/lib/onnxruntime.dll": "x",
                                                   "sherpa_onnx/lib/libonnxruntime.1.28.2.dylib": "x"})
        res = self.samla({"sherpa-onnx-core": self.p.filer("sherpa-onnx-core")})
        self.assertEqual(res.fel, [])
        text = las_fil(os.path.join(self.ut, "sherpa-onnx-core.txt"))
        self.assertIn("sherpa_onnx/lib/onnxruntime.dll (ONNX Runtime 1.28.2", text)
        self.assertIn("THIRD PARTY SOFTWARE NOTICES AND INFORMATION", text)
        self.assertIn("Copyright (c) Microsoft Corporation", text)
        self.assertEqual(text.count("===== paketering/licenstexter/onnxruntime-1.28.2/LICENSE ====="), 1)

    def test_onnxruntime_i_en_annan_version_av_paketet_ar_fel(self):
        self.p.paket("sherpa_onnx", "2.1.0", {"sherpa_onnx/__init__.py": ""}, licensfiler={"LICENSE": "Apache\n"})
        self.p.paket("sherpa-onnx-core", "2.1.0", {"sherpa_onnx/lib/onnxruntime.dll": "x"})
        res = self.samla({"sherpa-onnx-core": self.p.filer("sherpa-onnx-core")})
        self.assertEqual(len(res.fel), 1)
        self.assertIn("gäller version 2.0.1", res.fel[0])

    def test_bibliotek_i_paketet_ska_namnas_i_licenstexten(self):
        self.p.paket("bibl", "1.0", {"bibl/__init__.py": "", "bibl/_snabb.cp312-win_amd64.pyd": "x",
                                     "bibl/_snabb.cpython-312-darwin.so": "x",
                                     "bibl.libs/libfrobnicate64_-0123456789abcdef0123456789abcdef.dll": "x",
                                     "bibl.libs/msvcp140-0123456789abcdef0123456789abcdef.dll": "x"},
                     licensfiler={"LICENSE": MIT + "\nThis wheel also bundles Frobnicate (BSD).\n"})
        res = self.samla({"bibl": self.p.filer("bibl")})
        self.assertEqual(res.fel, [])
        text = las_fil(os.path.join(self.ut, "bibl.txt"))
        self.assertIn("libfrobnicate64_-0123456789abcdef0123456789abcdef.dll (licenstexten nedan nämner frobnicate)", text)
        self.assertNotIn("_snabb", text)  # Python-moduler ar inga inbaddade bibliotek
        msvc = las_fil(os.path.join(self.ut, "microsoft-visual-c-runtime.txt"))
        self.assertIn("bibl.libs/msvcp140-0123456789abcdef0123456789abcdef.dll", msvc)
        # ett bibliotek som licenstexten inte namner ar FEL
        self.p.paket("bibl2", "1.0", {"bibl2.libs/libokandsak-0123456789abcdef.dll": "x"}, licensfiler={"LICENSE": MIT})
        res = self.samla({"bibl2": self.p.filer("bibl2")})
        self.assertEqual(len(res.fel), 1)
        self.assertIn("bibl2.libs/libokandsak-0123456789abcdef.dll", res.fel[0])

    def lagg_av(self, extra=None, licens="LGPL version 2.1 or later"):
        filer = {"av/__init__.py": "", "av/_core.cp312-win_amd64.pyd": "x"}
        for n in sl.FFMPEG_BIBLIOTEK:
            filer[f"av.libs/{n}-60-0123456789abcdef0123456789abcdef.dll"] = ffmpeg_lib(licens, n)
        filer.update(extra or {})
        self.p.paket("av", "12.3.0", filer, licensfiler={"LICENSE.txt": "Copyright retained by original committers.\nBSD\n"},
                     metadata={"License": "BSD"})

    def test_pypi_hjulet_av_med_gpl_bibliotek_ar_fel(self):
        self.lagg_av({"av.libs/libx264-164-0123456789abcdef0123456789abcdef.dll": "x",
                      "av.libs/postproc-57-0123456789abcdef0123456789abcdef.dll": "x"}, licens="GPL version 3 or later")
        res = self.samla({"av": self.p.filer("av")}, ffmpeg_licenser=ffmpeg_katalog(self))
        fel = "\n".join(res.fel)
        self.assertIn("PyAV har 2 bibliotek som inte är FFmpegs sju LGPL-bibliotek (libx264, postproc)", fel)
        self.assertIn("bygg-ffmpeg.sh", fel)
        self.assertIn("har licensen GPL version 3 or later", fel)

    def test_av_utan_ffmpegs_licenstexter_ar_fel(self):
        self.lagg_av()
        res = self.samla({"av": self.p.filer("av")})
        self.assertEqual(len(res.fel), 1)
        self.assertIn("FFmpeg: licenstexterna saknas", res.fel[0])

    def test_det_egna_ffmpeg_med_kallan_och_gcc_runtimen(self):
        self.lagg_av()
        res = self.samla({"av": self.p.filer("av")}, plattform="windows", whisper_licens=whisper_katalog(self),
                         ffmpeg_licenser=ffmpeg_katalog(self))
        self.assertEqual(res.fel, [])
        _, rader = rader_i_forteckningen(self.ut)
        ffmpeg = next(r for r in rader if r[0] == "FFmpeg")
        self.assertEqual(ffmpeg[1:3], ["6.1.6", "LGPL-2.1-or-later"])
        self.assertIn("commit f1e3a2bf7a2f2cde936d1ed97f09a26853d20125", ffmpeg[3])
        self.assertIn("ffmpeg-6.1.6-kallkod.tar.xz", ffmpeg[3])
        text = las_fil(os.path.join(self.ut, "ffmpeg.txt"))
        for stycke in ("https://github.com/FFmpeg/FFmpeg, tagg n6.1.6", "Configure-raden: --prefix=/x --disable-everything",
                       "===== COPYING.LGPLv2.1 =====", "===== LICENSE.md =====", "===== CREDITS =====", "av.libs/avcodec-60-",
                       "Källkoden till exakt den här versionen: filen ffmpeg-6.1.6-kallkod.tar.xz"):
            self.assertIn(stycke, text)
        gcc = next(r for r in rader if r[4] == "gcc-mingw-runtime.txt")
        self.assertIn("GCC-exception-3.1", gcc[2])
        self.assertIn("ZPL-2.1", gcc[2])
        text = las_fil(os.path.join(self.ut, "gcc-mingw-runtime.txt"))
        self.assertIn("GCC RUNTIME LIBRARY EXCEPTION", text)
        self.assertIn("MinGW-w64 runtime licensing", text)
        self.assertIn("===== COPYING.winpthreads.txt =====", text)
        self.assertIn("i samma GitHub Release som programmet", ffmpeg[3])
        self.assertIn("finns i samma GitHub Release som\nprogrammet (ffmpeg-6.1.6-kallkod.tar.xz)",
                      las_fil(os.path.join(self.ut, sl.FORTECKNING)))
        whisper = next(r for r in rader if r[0] == "whisper.cpp")
        self.assertEqual(whisper[1:3], ["v1.9.5", "MIT"])
        self.assertIn("d1be6fde11ac6e0407606b4e42fe72d34add8037", whisper[3])

    def test_ffmpeg_pa_windows_kraver_mingw_runtimens_licens(self):
        self.lagg_av()
        res = self.samla({"av": self.p.filer("av")}, ffmpeg_licenser=ffmpeg_katalog(self, mingw=False))
        self.assertEqual(len(res.fel), 1, res.fel)
        self.assertIn("COPYING.MinGW-w64-runtime.txt, COPYING.winpthreads.txt saknas", res.fel[0])
        res = self.samla({"av": self.p.filer("av")}, ffmpeg_licenser=ffmpeg_katalog(self, gcc=False))
        self.assertEqual(res.fel, [])  # Linux och Mac: ingen MinGW
        _, rader = rader_i_forteckningen(self.ut)
        self.assertNotIn("gcc-mingw-runtime.txt", [r[4] for r in rader])

    def vulkan(self, kalla_rader):
        self.lagg_mittpaket()
        whisper = whisper_katalog(self)
        with open(os.path.join(whisper, "KALLA.txt"), "a", encoding="utf-8") as f:
            f.write("".join(r + "\n" for r in kalla_rader))
        mapp = tempfile.mkdtemp(prefix="akasha-licens-vulkan-")
        self.addCleanup(shutil.rmtree, mapp, True)
        ovriga = []
        for n in ("whisper-cli.exe", "ggml-vulkan.dll"):
            skriv(os.path.join(mapp, n), "x")
            ovriga.append((f"whisper/{n}", os.path.join(mapp, n)))
        return self.samla({"mittpaket": self.p.filer("mittpaket")}, ovriga, plattform="windows", whisper_licens=whisper)

    def test_ggml_vulkan_tar_med_khronos_licenserna(self):
        res = self.vulkan(["vulkan-sdk: 1.4.309.0", "spirv-headers: 09913f088a1197aba4aefd300a876b2ebbaa3391"])
        self.assertEqual(res.fel, [])
        _, rader = rader_i_forteckningen(self.ut)
        rad = next(r for r in rader if r[4] == "khronos-vulkan-spirv-headers.txt")
        self.assertEqual(rad[1], "1.4.309.0")
        self.assertIn("Apache-2.0 OR MIT", rad[2])
        text = las_fil(os.path.join(self.ut, "khronos-vulkan-spirv-headers.txt"))
        for stycke in ("paketering/licenstexter/vulkan-headers-1.4.309.0/Apache-2.0.txt",
                       "paketering/licenstexter/vulkan-headers-1.4.309.0/MIT.txt",
                       "paketering/licenstexter/spirv-headers-09913f088a11/LICENSE",
                       "Copyright (c) 2015-2023 The Khronos Group Inc.", "Apache License", "Materials"):
            self.assertIn(stycke, text)

    def test_ggml_vulkan_utan_versionerna_eller_med_okand_version_ar_fel(self):
        res = self.vulkan([])
        self.assertEqual(len(res.fel), 1)
        self.assertIn("vulkan-sdk:", res.fel[0])
        res = self.vulkan(["vulkan-sdk: 9.9.9.9", "spirv-headers: 09913f088a1197aba4aefd300a876b2ebbaa3391"])
        self.assertEqual(len(res.fel), 1)
        self.assertIn("vulkan-headers-9.9.9.9 saknas", res.fel[0])

    def test_python_har_cpythons_licenser_for_det_som_ingar(self):
        self.lagg_mittpaket()
        res = self.samla({"mittpaket": self.p.filer("mittpaket")})
        self.assertEqual(res.fel, [])
        text = las_fil(os.path.join(self.ut, "python.txt"))
        for stycke in ("Licenses and Acknowledgements for Incorporated Software", "\nexpat\n", "\nlibmpdec\n",
                       "\nlibffi\n", "\nzlib\n", "HACL* Contributors", "paketering/licenstexter/cpython-3.12/license.rst"):
            self.assertIn(stycke, text)

    def test_openssl_och_xz_i_python(self):
        binarer = ["Python.framework/Versions/3.12/Python", "libssl.3.dylib", "libcrypto.3.dylib",
                   "python3.12/lib-dynload/_ssl.cpython-312-darwin.so", "python3.12/lib-dynload/_lzma.cpython-312-darwin.so"]
        for plattform, xz in (("mac", "5.2.3"), ("windows", "5.2.5")):
            res = sl.Resultat()
            with mock.patch("ssl.OPENSSL_VERSION_INFO", (3, 0, 16, 0, 0)), \
                    mock.patch("ssl.OPENSSL_VERSION", "OpenSSL 3.0.16 11 Feb 2025"), \
                    mock.patch.object(sl.platform, "python_version", return_value="3.12.10"):
                komp = sl.python_tredjepart(res, binarer, plattform)
            self.assertEqual(res.fel, [])
            self.assertEqual([(k.namn, k.version, k.fil) for k in komp],
                             [("OpenSSL", "3.0.16", "openssl.txt"), ("XZ Utils (liblzma)", xz, "xz.txt")])
            self.assertIn("Apache License", komp[0].text)
            self.assertIn("libssl.3.dylib", komp[0].text)
            self.assertIn("liblzma is in the public domain", komp[1].text)
        # en annan OpenSSL eller Python ar FEL (texterna galler en version)
        res = sl.Resultat()
        with mock.patch("ssl.OPENSSL_VERSION_INFO", (3, 5, 1, 0, 0)), \
                mock.patch.object(sl.platform, "python_version", return_value="3.12.11"):
            self.assertEqual(sl.python_tredjepart(res, binarer, "mac"), [])
        self.assertEqual(len(res.fel), 2, res.fel)
        self.assertIn("openssl-3.5.1 saknas", res.fel[0])
        self.assertIn("XZ_I_PYTHON", res.fel[1])
        self.assertEqual(sl.python_tredjepart(sl.Resultat(), ["python312.dll", "_socket.pyd"], "windows"), [])

    def test_mac_och_windows_kraver_whisper_cpp(self):
        self.lagg_mittpaket()
        for plattform in ("mac", "windows"):
            res = self.samla({"mittpaket": self.p.filer("mittpaket")}, plattform=plattform)
            self.assertEqual(len(res.fel), 1, res.fel)
            self.assertIn("whisper.cpp: licensen saknas", res.fel[0])

    def test_visual_c_runtimen_och_okanda_bibliotek(self):
        self.lagg_mittpaket()
        mapp = tempfile.mkdtemp(prefix="akasha-licens-bin-")
        self.addCleanup(shutil.rmtree, mapp, True)
        for n in ("MSVCP140.dll", "VCOMP140.DLL", "whisper-cli.exe", "okand.dll", "data.txt"):
            skriv(os.path.join(mapp, n), "x")
        skriv(os.path.join(mapp, "whisper-cli"), b"\xcf\xfa\xed\xfe" + b"\x00" * 8)  # Mach-O utan andelse
        ovriga = [(f"whisper/{n}", os.path.join(mapp, n)) for n in ("MSVCP140.dll", "VCOMP140.DLL", "whisper-cli.exe",
                                                                     "whisper-cli", "data.txt")]
        res = self.samla({"mittpaket": self.p.filer("mittpaket")}, ovriga + [("okand.dll", os.path.join(mapp, "okand.dll"))],
                         plattform="windows", whisper_licens=whisper_katalog(self))
        self.assertEqual(len(res.fel), 1, res.fel)
        self.assertIn("okand.dll", res.fel[0])
        msvc = las_fil(os.path.join(self.ut, "microsoft-visual-c-runtime.txt"))
        self.assertIn("whisper/MSVCP140.dll", msvc)
        self.assertIn("whisper/VCOMP140.DLL", msvc)
        self.assertIn("Microsofts licensvillkor för Visual Studio", msvc)
        self.assertIn("Ingen licenstext från Microsoft är kopierad hit", msvc)
        whisper = las_fil(os.path.join(self.ut, "whisper-cpp.txt"))
        self.assertIn("whisper/whisper-cli.exe", whisper)
        self.assertIn("whisper/whisper-cli\n", whisper)
        self.assertNotIn("data.txt", msvc + whisper)
        # pa Linux (provbygget) ar ett okant bibliotek en varning, inte ett fel
        res = self.samla({"mittpaket": self.p.filer("mittpaket")}, [("okand.dll", os.path.join(mapp, "okand.dll"))])
        self.assertEqual(res.fel, [])
        self.assertEqual(len(res.varningar), 1)

    def test_provet_markeras_och_hoppar_over_whisper_och_ffmpeg(self):
        self.lagg_av({"av.libs/libx264-164-0123456789abcdef0123456789abcdef.dll": "x"})
        res = self.samla({"av": self.p.filer("av")}, plattform="windows", prov=True)
        self.assertEqual(res.fel, [])
        text, rader = rader_i_forteckningen(self.ut)
        self.assertTrue(text[0].startswith(sl.MARKERING_PROV + ":"))
        self.assertNotIn("FFmpeg", [r[0] for r in rader])
        self.assertIn("(hoppades över i provet)", las_fil(os.path.join(self.ut, "av.txt")))

    def test_pystray_har_en_mening_om_att_koden_gar_att_byta(self):
        self.p.paket("pystray", "0.19.5", {"pystray/__init__.py": ""}, licensfiler={"COPYING": "GPL 3\n", "COPYING.LGPL": "LGPL 3\n"},
                     metadata={"License": "LGPLv3"})
        res = self.samla({"pystray": self.p.filer("pystray")}, plattform="windows", whisper_licens=whisper_katalog(self))
        self.assertEqual(res.fel, [])
        text = las_fil(os.path.join(self.ut, "pystray.txt"))
        self.assertIn("vanliga .py-filer", text)
        self.assertIn("byta ut", text)
        self.assertIn("===== pystray-0.19.5.dist-info/COPYING.LGPL =====", text)
        self.assertIn("pystray är under LGPL-3.0", las_fil(os.path.join(self.ut, sl.FORTECKNING)))

    def test_fordelningen_av_pyinstallers_filer(self):
        self.lagg_mittpaket()
        dists = self.p.dists()
        annan = os.path.join(tempfile.mkdtemp(prefix="akasha-licens-annan-"), "python312.dll")
        self.addCleanup(shutil.rmtree, os.path.dirname(annan), True)
        skriv(annan, "x")
        toc = [("mittpaket", self.p.sokvag("mittpaket/__init__.py"), "PYMODULE"),
               ("mittpaket/data.bin", self.p.sokvag("mittpaket/data.bin"), "DATA"),
               ("python312.dll", annan, "BINARY"),
               ("saknas", os.path.join(self.p.rot, "finns-inte.py"), "PYMODULE"),
               ("ingen", None, "PYMODULE")]
        filer = sl.kallfiler_ur_toc(toc)
        self.assertEqual(len(filer), 3)
        paket, ovriga = sl.fordela(filer, dists)
        self.assertEqual(list(paket), ["mittpaket"])
        self.assertEqual(len(paket["mittpaket"]), 2)
        self.assertEqual(ovriga, [("python312.dll", annan)])

    def test_katalogen_byts_ut_helt(self):
        self.lagg_mittpaket()
        skriv(os.path.join(self.ut, "gammal.txt"), "från förra bygget")
        self.samla({"mittpaket": self.p.filer("mittpaket")})
        self.assertFalse(os.path.exists(os.path.join(self.ut, "gammal.txt")))
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.ut)) if n.startswith(".licenser-")], [])

    def test_namnen_och_nycklarna(self):
        self.assertEqual(sl.normnamn("Sherpa_ONNX.core"), "sherpa-onnx-core")
        self.assertEqual(sl.nycklar("libscipy_openblas64_-4e39871015dc1470c682dc512497ee22.dll"), {"scipy", "openblas"})
        self.assertEqual(sl.nycklar("libgfortran.5.dylib"), {"gfortran"})
        for n in ("x.pyd", "x.cpython-312-darwin.so", "x.abi3.so", "x.py", "x.txt"):
            self.assertFalse(sl.ar_delat_bibliotek(n), n)
        for n in ("x.dll", "libx.1.dylib", "libx.so.60", "libx.so"):
            self.assertTrue(sl.ar_delat_bibliotek(n), n)
        for n in ("MSVCP140.dll", "VCRUNTIME140_1.dll", "VCOMP140.DLL", "msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll"):
            self.assertTrue(sl.MSVC.match(n), n)
        # Universal C Runtime tas inte med (spec-filen): sadana filer ar FEL om de anda kommer med
        for n in ("msvcrt.dll", "ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll"):
            self.assertFalse(sl.MSVC.match(n), n)
        # filnamnen far inte se ut som det som bygget forbjuder (bygg_windows_verktyg.ar_forbjudet, find i bygg-mac.sh)
        import bygg_windows_verktyg
        for namn in ("sherpa-onnx-core.txt", "microsoft-visual-c-runtime.txt", "ffmpeg.txt", "gcc-mingw-runtime.txt",
                     "khronos-vulkan-spirv-headers.txt"):
            self.assertFalse(bygg_windows_verktyg.ar_forbjudet(namn, False), namn)


def las_fil(sokvag):
    with open(sokvag, encoding="utf-8") as f:
        return f.read()


class KontrolleraLicenser(unittest.TestCase):
    """kontrollera_licenser.py mot ett pahittat Windows-program med licenser/ fran samla_licenser.py."""

    def setUp(self):
        self.p = FalskaPaket(self)
        self.p.paket("mittpaket", "1.0", {"mittpaket/__init__.py": "", "mittpaket/data.bin": "x"},
                     licensfiler={"LICENSE": MIT}, metadata={"License": "MIT"})
        self.p.paket("rentpython", "2.0", {"rentpython/__init__.py": "", "rentpython/modul.py": ""},
                     licensfiler={"LICENSE": MIT}, metadata={"License": "MIT"})
        self.p.paket("utanfor", "3.0", {"utanfor/__init__.py": "", "utanfor/bild.png": "x"},
                     licensfiler={"LICENSE": MIT}, metadata={"License": "MIT"})
        self.prog = os.path.join(tempfile.mkdtemp(prefix="akasha-licens-prog-"), "Akasha Protokoll")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.prog), True)
        self.exe = os.path.join(self.prog, "Akasha Protokoll.exe")
        skriv(self.exe, "MZ")
        skriv(os.path.join(self.prog, "_internal", "mittpaket", "data.bin"), "x")
        skriv(os.path.join(self.prog, "_internal", "static", "app.js"), "x")
        dists = self.p.dists()
        paket = {n: f for n, f in sl.alla_installerade(dists).items() if n != "utanfor"}
        self.res_samla = sl.samla(paket, [], os.path.join(self.prog, "licenser"), "windows", "0.2.0",
                                  whisper_licens=whisper_katalog(self), dists=dists)
        self.assertEqual(self.res_samla.fel, [])

    def kor(self, moduler=None):
        res = kontroll_hjalp.Resultat("prov")
        with mock.patch("builtins.print"):
            kl.kontrollera(self.exe, res, dists=self.p.dists().values(), las_pyz=lambda _p: moduler, toppkarta={})
        return res

    def test_allt_stammer(self):
        res = self.kor(["mittpaket", "rentpython", "rentpython.modul", "json", "os.path", "app", "start", "motor",
                        "_sysconfigdata__darwin_darwin",
                        "pyimod02_importers", "_pyi_rth_utils"])
        self.assertEqual(res.fel_rader, [])
        self.assertTrue(any("alla 2 Python-paket" in r for r in res.ok_rader), res.ok_rader)

    def test_licenser_txt_saknas(self):
        os.remove(os.path.join(self.prog, "licenser", sl.FORTECKNING))
        res = self.kor()
        self.assertEqual(len(res.fel_rader), 1)
        self.assertIn("LICENSER.txt saknas", res.fel_rader[0])

    def test_en_komponents_fil_saknas(self):
        os.remove(os.path.join(self.prog, "licenser", "rentpython.txt"))
        res = self.kor()
        self.assertIn("komponenten rentpython: rentpython.txt saknas eller är tom", res.fel_rader)

    def test_ett_paket_i_programmet_saknas_i_forteckningen(self):
        skriv(os.path.join(self.prog, "_internal", "utanfor", "bild.png"), "x")  # en fil ur paketet, pa disken
        res = self.kor()
        self.assertEqual(len(res.fel_rader), 1, res.fel_rader)
        self.assertIn("paketet utanfor finns i programmet (filen utanfor/bild.png)", res.fel_rader[0])

    def test_en_modul_i_pyz_ur_ett_paket_som_saknas_och_en_okand_modul(self):
        res = self.kor(["utanfor", "nagot_helt_okant.sub"])
        fel = "\n".join(res.fel_rader)
        self.assertIn("paketet utanfor finns i programmet (modulen utanfor)", fel)
        self.assertIn("modulen nagot_helt_okant.sub", fel)
        self.assertEqual(len(res.fel_rader), 2)

    def test_tredjepartskod_i_python_kraver_sin_licens(self):
        for n in ("libssl-3-x64.dll", "_lzma.pyd", "_decimal.pyd", "pyexpat.pyd", "_sha2.pyd"):
            skriv(os.path.join(self.prog, "_internal", n), "x")
        res = self.kor()
        self.assertEqual(len(res.fel_rader), 2, res.fel_rader)
        self.assertIn("OpenSSL finns i programmet (libssl-3-x64.dll)", res.fel_rader[0])
        self.assertIn("XZ Utils (liblzma) finns i programmet (_lzma.pyd)", res.fel_rader[1])
        for del_ in ("libmpdec", "expat", "HACL*"):  # ur CPythons license.rst i python.txt
            self.assertTrue(any(r.startswith(f"{del_} finns i programmet") for r in res.ok_rader), (del_, res.ok_rader))
        licenser = os.path.join(self.prog, "licenser")
        skriv(os.path.join(licenser, "openssl.txt"), "OpenSSL 3.0.16\nApache License\n")
        skriv(os.path.join(licenser, "xz.txt"), "XZ Utils\nliblzma is in the public domain.\n")
        fil = os.path.join(licenser, sl.FORTECKNING)
        text = las_fil(fil).replace(sl.STRECK + "\n", sl.STRECK + "\nOpenSSL | 3.0.16 | Apache-2.0 | x | openssl.txt\n"
                                    "XZ Utils (liblzma) | 5.2.5 | public domain | x | xz.txt\n", 1)
        skriv(fil, text)
        res = self.kor()
        self.assertEqual(res.fel_rader, [])
        # Pythons licensfil utan libmpdec ger FEL
        python = os.path.join(licenser, "python.txt")
        skriv(python, las_fil(python).replace("\nlibmpdec\n", "\n"))
        res = self.kor()
        self.assertEqual(len(res.fel_rader), 1, res.fel_rader)
        self.assertIn("libmpdec finns i programmet (_decimal.pyd) men Pythons licensfil saknar", res.fel_rader[0])

    def test_markerad_ofullstandig_eller_prov(self):
        fil = os.path.join(self.prog, "licenser", sl.FORTECKNING)
        original = las_fil(fil)
        for markering in (sl.MARKERING_OFULLSTANDIG, sl.MARKERING_PROV):
            skriv(fil, f"{markering}: något\n\n" + original)
            res = self.kor()
            self.assertEqual(len(res.fel_rader), 1, res.fel_rader)
            self.assertIn(f"markerad {markering}", res.fel_rader[0])

    def test_trasig_rad_och_tom_forteckning(self):
        fil = os.path.join(self.prog, "licenser", sl.FORTECKNING)
        original = las_fil(fil)
        skriv(fil, original.replace("rentpython | 2.0", "rentpython 2.0", 1))
        res = self.kor()
        self.assertTrue(any("inte fem fält" in f for f in res.fel_rader), res.fel_rader)
        skriv(fil, original.split(sl.STRECK)[0])
        res = self.kor()
        self.assertTrue(any("ingen förteckning" in f for f in res.fel_rader), res.fel_rader)

    def test_pyz_som_inte_gar_att_lasa_ar_fel_och_utan_pyinstaller_info(self):
        def trasig(_p):
            raise ValueError("ingen PYZ")
        res = kontroll_hjalp.Resultat("prov")
        with mock.patch("builtins.print"):
            kl.kontrollera(self.exe, res, dists=self.p.dists().values(), las_pyz=trasig, toppkarta={})
        self.assertTrue(any("PYZ-arkiv gick inte att läsa" in f for f in res.fel_rader), res.fel_rader)
        with mock.patch("builtins.print") as utskrift:
            res = kontroll_hjalp.Resultat("prov")
            kl.kontrollera(self.exe, res, dists=self.p.dists().values(), las_pyz=lambda _p: None, toppkarta={})
        self.assertEqual(res.fel_rader, [])
        self.assertTrue(any("PyInstaller finns inte" in str(a) for a in utskrift.call_args_list))

    def test_platserna_pa_mac_windows_och_linux(self):
        lic, rotter = kl.platser("/x/Akasha Protokoll.app/Contents/MacOS/Akasha Protokoll")
        self.assertEqual(lic.replace("\\", "/").split("/x/")[-1], "Akasha Protokoll.app/Contents/Resources/licenser")
        self.assertEqual([r.replace("\\", "/").rsplit("/", 1)[-1] for r in rotter], ["Frameworks", "Resources"])
        lic, rotter = kl.platser(os.path.join("C:", os.sep, "p", "Akasha Protokoll.exe"))
        self.assertEqual(os.path.basename(lic), "licenser")
        self.assertEqual(os.path.basename(os.path.dirname(lic)), "p")
        lic, rotter = kl.platser("/x/dist/akasha-protokoll/akasha-protokoll")
        self.assertTrue(lic.replace("\\", "/").endswith("akasha-protokoll/_internal/licenser"))

    def test_kommandoraden(self):
        with mock.patch.object(kl.importlib.metadata, "distributions", return_value=list(self.p.dists().values())), \
                mock.patch.object(kl, "pyz_moduler", return_value=None), mock.patch("builtins.print"):
            self.assertEqual(kl.main(["--program", self.exe]), 0)
            os.remove(os.path.join(self.prog, "licenser", sl.FORTECKNING))
            self.assertEqual(kl.main(["--program", self.exe]), 1)


class LicensernaISpecen(unittest.TestCase):
    """Spec-filen med falska PyInstaller-klasser: licenser/ i COLLECT (Mac, Linux) eller bredvid exe-filen (Windows)."""

    def kor_spec(self, plattform, miljo, binarer=()):
        anrop = {}

        def falsk(namn):
            def f(*a, **kw):
                anrop[namn] = (a, kw)
                return mock.MagicMock(pure=[], scripts=[], binaries=list(binarer) if namn == "Analysis" else [], datas=[])
            return f

        mapp = tempfile.mkdtemp(prefix="akasha-spec-licens-")
        self.addCleanup(shutil.rmtree, mapp, True)
        ns = {n: falsk(n) for n in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE")}
        ns.update(SPECPATH=PAKETERING, workpath=os.path.join(mapp, "pyi"), DISTPATH=os.path.join(mapp, "dist"))
        miljo = {"AKASHA_WHISPER_CLI": "", "AKASHA_WHISPER_KATALOG": "", "AKASHA_IKON": "", "AKASHA_VERSIONSFIL": "",
                 "AKASHA_WHISPER_LICENS": whisper_katalog(self), "AKASHA_FFMPEG_LICENSER": "", **miljo}
        with mock.patch.object(sys, "platform", plattform), mock.patch.dict(os.environ, miljo), \
                mock.patch("builtins.print"):
            exec(compile(las("paketering", "akasha-protokoll.spec"), "spec", "exec"), ns)
        return anrop, mapp

    def test_linux_och_mac_far_licenser_i_collect(self):
        for plattform, miljo in (("linux", {}), ("darwin", {"AKASHA_WHISPER_CLI": "/x/whisper-cli"})):
            anrop, mapp = self.kor_spec(plattform, miljo)
            toc = anrop["COLLECT"][0][3]
            mal = sorted(m.replace("\\", "/") for m, _k, typ in toc)
            self.assertIn("licenser/LICENSER.txt", mal, plattform)
            self.assertIn("licenser/akasha-protokoll.txt", mal)
            self.assertTrue(all(typ == "DATA" for _m, _k, typ in toc))
            self.assertTrue(all(os.path.isfile(k) for _m, k, _t in toc))

    def test_windows_utesluter_universal_c_runtime(self):
        kat = tempfile.mkdtemp(prefix="akasha-whisper-")
        self.addCleanup(shutil.rmtree, kat, True)
        skriv(os.path.join(kat, "whisper-cli.exe"), "x")
        binarer = [("ucrtbase.dll", "C:/jdk/bin/ucrtbase.dll", "BINARY"),
                   ("api-ms-win-crt-runtime-l1-1-0.dll", "C:/jdk/bin/api-ms-win-crt-runtime-l1-1-0.dll", "BINARY"),
                   ("python312.dll", "C:/py/python312.dll", "BINARY"), ("VCRUNTIME140.dll", "C:/py/VCRUNTIME140.dll", "BINARY")]
        anrop, _ = self.kor_spec("win32", {"AKASHA_WHISPER_KATALOG": kat}, binarer=binarer)
        self.assertEqual([b[0] for b in anrop["COLLECT"][0][1]], ["python312.dll", "VCRUNTIME140.dll"])
        anrop, _ = self.kor_spec("linux", {}, binarer=binarer)  # bara Windows filtrerar
        self.assertEqual(len(anrop["COLLECT"][0][1]), 4)

    def test_windows_far_licenser_bredvid_exe_filen(self):
        kat = tempfile.mkdtemp(prefix="akasha-whisper-")
        self.addCleanup(shutil.rmtree, kat, True)
        skriv(os.path.join(kat, "whisper-cli.exe"), "x")
        anrop, mapp = self.kor_spec("win32", {"AKASHA_WHISPER_KATALOG": kat})
        self.assertEqual(anrop["COLLECT"][0][3], [])  # inte i _internal
        lic = os.path.join(mapp, "dist", "Akasha Protokoll", "licenser")
        self.assertTrue(os.path.isfile(os.path.join(lic, sl.FORTECKNING)))
        self.assertTrue(os.path.isfile(os.path.join(lic, "whisper-cpp.txt")))


class Bygget(unittest.TestCase):
    """Statiska kontroller: skripten och floden for med licenserna."""

    def test_whisper_cpp_licensen_sparas_och_cachas(self):
        for skript in ("bygg-whisper-cli.sh", "bygg-whisper-cli-windows.sh"):
            text = las("paketering", skript)
            self.assertIn('cp "$UT/src/LICENSE" "$UT/licens/LICENSE"', text)
            self.assertIn('> "$UT/licens/KALLA.txt"', text)
        mac = las(".github", "workflows", "mac-app.yml")
        self.assertIn("path: |\n            build/whisper/whisper-cli\n            build/whisper/licens\n", mac)
        win = las(".github", "workflows", "windows-app.yml")
        self.assertEqual(win.count("path: |\n            build/whisper/kompilerat\n            build/whisper/licens\n"), 2)
        for flode in (mac, win):
            self.assertIn("cp -R build/app/pyi/akasha-protokoll/licenser build/loggar/", flode)

    def test_bygg_skripten_och_kontrollera_kor_kontrollen(self):
        mac = las("paketering", "bygg-mac.sh")
        self.assertIn('paketering/kontrollera_licenser.py --program "$APP/Contents/MacOS/Akasha Protokoll"', mac)
        self.assertIn('AKASHA_WHISPER_LICENS="$WHISPER_LICENS"', mac)
        win = las("paketering", "bygg-windows.sh")
        self.assertIn('paketering/kontrollera_licenser.py --program "$DIST/$NAMN.exe"', win)
        self.assertIn('AKASHA_WHISPER_LICENS="$WHISPER_LICENS_ABS" AKASHA_FFMPEG_LICENSER="$FFMPEG_LICENSER_ABS"', win)
        self.assertIn("kontrollera_licenser.kontrollera(program, lic)", las("paketering", "kontrollera.py"))
        self.assertIn('AKASHA_FFMPEG_LICENSER="$FF/ut/ffmpeg"', las("paketering", "prova-linux.sh"))
        spec = las("paketering", "akasha-protokoll.spec")
        self.assertIn("samla_licenser.samla_for_bygget(a.pure + a.scripts + a.binaries + a.datas", spec)

    def test_floden_bygger_det_egna_ffmpeg_och_aldrig_pypi_hjulet(self):
        nyckel = ("hashFiles('paketering/bygg-ffmpeg.sh', 'paketering/ffmpeg-komponenter.txt', 'paketering/bygg-pyav.sh', "
                  "'paketering/krav-ffmpeg.txt')")
        for namn, venv, system in (("mac-app.yml", "build/venv/bin/pip install", "macos26"),
                                   ("windows-app.yml", "build/venv/Scripts/python -m pip install", "windows2025")):
            text = las(".github", "workflows", namn)
            self.assertIn("grep -v -E '^(faster-whisper|av)==' app/requirements.txt > build/krav.txt", text, namn)
            self.assertNotIn("grep -v '^faster-whisper' app/requirements.txt", text, namn)
            self.assertIn(f"key: ffmpeg-pyav-${{{{ {nyckel} }}}}-{system}-py312", text, namn)
            self.assertIn("bash paketering/bygg-ffmpeg.sh build/ffmpeg", text, namn)
            self.assertIn("bash paketering/bygg-pyav.sh build/ffmpeg python", text, namn)
            self.assertIn(f"{venv} --no-deps --no-index --force-reinstall build/ffmpeg/ut/av-12.3.0-*.whl", text, namn)
            self.assertIn('paketering/kontrollera_ffmpeg.py --hjul "build/ffmpeg/ut/av-12.3.0-*.whl"', text, namn)
            self.assertIn("name: ffmpeg-6.1.6-kallkod\n          path: build/ffmpeg/ut/kallkod", text, namn)
            self.assertIn('AKASHA_FFMPEG_LGPL: "1"', text, namn)
            self.assertIn("AKASHA_FFMPEG_LICENSER: build/ffmpeg/ut/ffmpeg", text, namn)
            # hjulet installeras fore enhetstesterna, som provar att FFmpeg ar LGPL (test_ljud.TestFfmpegArLgpl)
            self.assertLess(text.index("--force-reinstall build/ffmpeg/ut/av-12.3.0"), text.index("- name: Enhetstester"))
        win = las(".github", "workflows", "windows-app.yml")
        for stycke in ("shell: C:\\msys64\\usr\\bin\\bash.exe --login -eo pipefail {0}", "MSYSTEM: UCRT64",
                       'CHERE_INVOKING: "1"', "mingw-w64-ucrt-x86_64-gcc", "mingw-w64-ucrt-x86_64-nasm",
                       "steps.bygg_ffmpeg.outcome", "steps.bygg_pyav.outcome", "steps.pyav.outcome"):
            self.assertIn(stycke, win)
        self.assertIn('paketering/kontrollera_ffmpeg.py --katalog "$APP"', las("paketering", "bygg-mac.sh"))
        self.assertIn('paketering/kontrollera_ffmpeg.py --katalog "$DIST" || fel', las("paketering", "bygg-windows.sh"))

    def test_skripten_for_ffmpeg_och_pyav_pa_windows(self):
        ffmpeg = las("paketering", "bygg-ffmpeg.sh")
        self.assertIn("MINGW*|UCRT64*|CLANG64*|MSYS*|CYGWIN*)", ffmpeg)
        self.assertIn('KOMPILATOR="$(command -v cc || command -v gcc || true)"', ffmpeg)
        self.assertIn("COPYING.MinGW-w64-runtime.txt", ffmpeg)
        pyav = las("paketering", "bygg-pyav.sh")
        self.assertIn('sokvag() { (cd "$1" && { pwd -W 2>/dev/null || pwd; }); }', pyav)
        self.assertIn('KAT="$(sokvag "$KAT")"', pyav)
        self.assertNotIn('tar -xzf "$KAT', pyav)  # GNU tar i Git Bash tar D:/... for en fjarrvard
        whisper = las("paketering", "bygg-whisper-cli-windows.sh")
        self.assertIn('"${VULKAN_SDK_VERSION:-}" "${SPIRV_HEADERS_COMMIT:-}" >> "$UT/licens/KALLA.txt"', whisper)
        for katalog, commit in (("vulkan-headers-1.4.309.0", "952f776f6573aafbb62ea717d871cd1d6816c387"),
                                ("spirv-headers-09913f088a11", "09913f088a1197aba4aefd300a876b2ebbaa3391")):
            self.assertIn(f"commit: {commit}", las_fil(os.path.join(PAKETERING, "licenstexter", katalog, "KALLA.txt")))
        flode = las(".github", "workflows", "windows-app.yml")
        self.assertIn('VULKAN_SDK_VERSION: "1.4.309.0"', flode)
        self.assertIn('SPIRV_HEADERS_COMMIT: "09913f088a1197aba4aefd300a876b2ebbaa3391"', flode)

    def test_licenstexterna_for_onnxruntime_finns_med_kallan(self):
        katalog = os.path.join(PAKETERING, "licenstexter", "onnxruntime-1.28.2")
        self.assertEqual(sorted(os.listdir(katalog)), ["KALLA.txt", "LICENSE", "ThirdPartyNotices.txt"])
        kalla = las_fil(os.path.join(katalog, "KALLA.txt"))
        self.assertRegex(kalla, r"sha256: [0-9a-f]{64}")
        self.assertIn("commit: 33ca9628233dc8f002435e868d4c2e9f82766ca1", kalla)
        self.assertIn("Copyright (c) Microsoft Corporation", las_fil(os.path.join(katalog, "LICENSE")))

    def test_kommentarerna_har_inga_aao(self):
        for namn in ("samla_licenser.py", "kontrollera_licenser.py"):
            with open(os.path.join(PAKETERING, namn), encoding="utf-8") as f:
                kommentarer = [t.string for t in tokenize.generate_tokens(io.StringIO(f.read()).readline)
                               if t.type == tokenize.COMMENT]
            for k in kommentarer:
                self.assertIsNone(re.search("[åäöÅÄÖ]", k), f"{namn}: {k}")
            with open(os.path.join(PAKETERING, namn), encoding="utf-8") as f:
                text = f.read()
            docstring = text.split('"""')[1]
            self.assertIsNone(re.search("[åäöÅÄÖ]", docstring), namn)


if __name__ == "__main__":
    unittest.main()
