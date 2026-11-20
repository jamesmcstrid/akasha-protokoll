#!/bin/bash
# Bygger PyAV 12.3.0 fran kallkod mot det egna FFmpeg-bygget (paketering/bygg-ffmpeg.sh) och gor hjulet sjalvstandigt.
#   bash paketering/bygg-pyav.sh KATALOG PYTHON        (kors fran repots rot; Linux, Mac och Git Bash pa Windows)
# KATALOG = samma katalog som bygg-ffmpeg.sh fick (med prefix/). PYTHON = en Python 3.12 att skapa byggets venv med.
# Resultat: KATALOG/ut/av-12.3.0-cp312-*.whl, med de sju FFmpeg-biblioteken inlagda (auditwheel pa Linux, delocate pa Mac,
# delvewheel pa Windows), och ett rokprov som installerar hjulet i en tom venv och avkodar testljud/en-talare.m4a.
# Hamtar bara byggverktygen (krav-ffmpeg.txt, exakta versioner) och PyAV:s sdist fran PyPI med last sha256.
set -euo pipefail
trap 'echo "FEL: bygg-pyav.sh stannade pa rad $LINENO: $BASH_COMMAND" >&2' ERR

SDIST_ADRESS=https://files.pythonhosted.org/packages/00/f8/5adeeae0c42a7130933d168b8d84a21c98a32cb9fcf9222e2541ed0d9c7b/av-12.3.0.tar.gz
SDIST_SHA256=04b1892562aff3277efc79f32bd8f1d0cbb64ed011241cb3e96f9ad471816c22
VERSION=12.3.0
SKRIPT_KAT="$(cd "$(dirname "$0")" && pwd)"
ROT="$(cd "$SKRIPT_KAT/.." && pwd)"

KAT="${1:?ange katalogen som bygg-ffmpeg.sh anvande}"
PYTHON="${2:?ange en Python 3.12}"
KAT="$(cd "$KAT" && pwd)"
PREFIX="$KAT/prefix"
[ -d "$PREFIX/lib" ] || { echo "FEL: $PREFIX/lib saknas: kor paketering/bygg-ffmpeg.sh $KAT forst" >&2; exit 1; }
if [ -e "$KAT/venv" ] || [ -e "$KAT/pyav" ] || [ -e "$KAT/ut/hjul" ]; then
  echo "FEL: $KAT/venv, $KAT/pyav eller $KAT/ut/hjul finns redan. Anvand en tom katalog (eller en ny)." >&2
  exit 1
fi

case "$(uname -s)" in
  Linux) SYSTEM=linux; ANTAL="$(nproc)" ;;
  Darwin)
    SYSTEM=mac; ANTAL="$(sysctl -n hw.ncpu)"
    # samma minos som FFmpeg-bygget och som bygg-mac.sh kontrollerar, och plats i install names for delocate
    export MACOSX_DEPLOYMENT_TARGET=14.0
    export LDFLAGS="-headerpad_max_install_names ${LDFLAGS:-}" ;;
  MINGW*|MSYS*|CYGWIN*) SYSTEM=windows; ANTAL="${NUMBER_OF_PROCESSORS:-2}" ;;
  *) echo "FEL: okant system $(uname -s)" >&2; exit 1 ;;
esac
echo "== System: $SYSTEM, $ANTAL processorer"

echo "== Byggverktyg (krav-ffmpeg.txt) i en egen venv"
"$PYTHON" -m venv "$KAT/venv"
if [ -x "$KAT/venv/bin/python" ]; then VP="$KAT/venv/bin/python"; else VP="$KAT/venv/Scripts/python"; fi
"$VP" -m pip install -q -r "$SKRIPT_KAT/krav-ffmpeg.txt"
"$VP" -m pip list 2>/dev/null | grep -i -E '^(cython|setuptools|wheel|delvewheel|delocate|auditwheel|patchelf) '

echo "== Hamtar PyAV $VERSION (sdist, last sha256)"
mkdir -p "$KAT/pyav" "$KAT/ut"
curl -sSfL --retry 3 --retry-delay 5 -o "$KAT/pyav/av-$VERSION.tar.gz" "$SDIST_ADRESS"
FAKTISK="$("$VP" -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$KAT/pyav/av-$VERSION.tar.gz")"
if [ "$FAKTISK" != "$SDIST_SHA256" ]; then
  echo "FEL: sha256 for av-$VERSION.tar.gz ar $FAKTISK, vantade $SDIST_SHA256" >&2
  exit 1
fi
echo "OK: sdist har sha256 $SDIST_SHA256"
tar -xzf "$KAT/pyav/av-$VERSION.tar.gz" -C "$KAT/pyav"
cd "$KAT/pyav/av-$VERSION"
# src/ i sdist-filen har C-kod genererad med en annan Cython: ta bort den, sa genereras den pa nytt med den lasta versionen
rm -rf src

echo "== Bygger PyAV mot $PREFIX"
# --ffmpeg-dir i stallet for pkg-config: samma vag pa alla system (setup.py anvander inte pkg-config pa Windows)
"$VP" setup.py -q build_ext -j"$ANTAL" --ffmpeg-dir="$PREFIX" bdist_wheel -d "$KAT/pyav/hjul-ra" 2>&1 | tail -n 40
RA="$(ls "$KAT"/pyav/hjul-ra/av-$VERSION-*.whl)"
echo "Hjul fore reparationen: $RA ($(wc -c < "$RA" | tr -d ' ') byte)"

echo "== Gor hjulet sjalvstandigt (de sju FFmpeg-biblioteken in i hjulet)"
mkdir -p "$KAT/ut/hjul"
case "$SYSTEM" in
  linux) PATH="$KAT/venv/bin:$PATH" LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" auditwheel repair -w "$KAT/ut/hjul" "$RA" ;;
  mac) PATH="$KAT/venv/bin:$PATH" DYLD_LIBRARY_PATH="$PREFIX/lib" delocate-wheel --require-archs arm64 -w "$KAT/ut/hjul" -v "$RA" ;;
  windows) "$KAT/venv/Scripts/delvewheel" repair --add-path "$PREFIX/bin" -w "$KAT/ut/hjul" "$RA" ;;
esac
mv "$KAT"/ut/hjul/av-$VERSION-*.whl "$KAT/ut/"
rmdir "$KAT/ut/hjul"
HJUL="$(ls "$KAT"/ut/av-$VERSION-*.whl)"
echo "OK: $HJUL ($(wc -c < "$HJUL" | tr -d ' ') byte)"

echo "== Rokprov: hjulet i en tom venv avkodar testljud/en-talare.m4a"
# (i en annan katalog an kallkoden: annars hittar Python kallkodens av/ i stallet for det installerade hjulet)
cd "$KAT"
"$PYTHON" -m venv "$KAT/prov-venv"
if [ -x "$KAT/prov-venv/bin/python" ]; then PP="$KAT/prov-venv/bin/python"; else PP="$KAT/prov-venv/Scripts/python"; fi
# --no-index och --no-deps: bara det hjul vi byggde, ingen reserv till PyPI-hjulet
"$PP" -m pip install -q --no-deps --no-index "$HJUL"
"$PP" - "$ROT/testljud/en-talare.m4a" <<'PY'
import sys

import av
import av._core as core

print("PyAV", av.__version__)
for namn in ("libavutil", "libavcodec", "libavformat", "libavfilter", "libavdevice", "libswresample", "libswscale"):
    print(f"{namn}: {core.library_meta[namn]['license']}")
sampel = ramar = 0
with av.open(sys.argv[1]) as c:
    for ram in c.decode(audio=0):
        ramar += 1
        sampel += ram.samples
print(f"{ramar} ramar, {sampel} sampel")
# Vantat: dagens GPL-bygge ger samma antal (provat); en skillnad betyder ett annat avkodningsresultat
VANTAT_RAMAR, VANTAT_SAMPEL = 405, 414720
if (ramar, sampel) != (VANTAT_RAMAR, VANTAT_SAMPEL):
    print(f"FEL: vantade {VANTAT_RAMAR} ramar och {VANTAT_SAMPEL} sampel", file=sys.stderr)
    sys.exit(1)
print(f"OK: rokprovet avkodade {sampel} sampel i {ramar} ramar")
PY
echo "== Klar"
