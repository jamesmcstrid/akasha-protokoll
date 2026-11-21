#!/bin/bash
# Bygger whisper-cli fran kallkod (whisper.cpp fran dess officiella repo, pa en fast tagg) for Apple Silicon.
#   bash paketering/bygg-whisper-cli.sh VERSION UTKATALOG
# Resultat: UTKATALOG/whisper-cli. Kors i Actions (paketering/ ar inte till for anvandarens Mac).
set -euo pipefail
trap 'echo "FEL: bygg-whisper-cli.sh stannade pa rad $LINENO: $BASH_COMMAND" >&2' ERR

VERSION="${1:?ange whisper.cpp-version (tagg), till exempel v1.9.5}"
UT="${2:?ange en utkatalog}"

if [ -e "$UT/src" ] || [ -e "$UT/bygg" ]; then
  echo "FEL: $UT/src eller $UT/bygg finns redan. Anvand en tom utkatalog." >&2
  exit 1
fi
mkdir -p "$UT"

echo "== Hamtar whisper.cpp $VERSION"
git clone --quiet --depth 1 --branch "$VERSION" https://github.com/ggml-org/whisper.cpp.git "$UT/src"
# Raden "warning: refs/tags/... is not a commit!" vid kloningen ar vantad (taggen ar annoterad och
#   klonas grunt) och betyder inget.
# Taggen far inte flyttas i tysthet: commiten ar last till det som byggdes och kontrollerades i
#   Mac-korning 1. Ny version: lagg till en rad har (cache-nyckeln i flodet foljer med skriptet).
case "$VERSION" in
  v1.9.5) VANTAD=d1be6fde11ac6e0407606b4e42fe72d34add8037 ;;   # uppmatt i Mac-korning 1
  *) VANTAD="" ;;
esac
FAKTISK="$(git -C "$UT/src" rev-parse HEAD)"
echo "whisper.cpp $VERSION = $FAKTISK"
if [ -n "$VANTAD" ] && [ "$FAKTISK" != "$VANTAD" ]; then
  echo "FEL: taggen $VERSION pekar pa $FAKTISK, vantade $VANTAD" >&2
  exit 1
fi
[ -n "$VANTAD" ] || echo "OBS: $VERSION ar inte last till en commit i bygg-whisper-cli.sh"

# whisper.cpp:s licens och kallan foljer med programmet (samla_licenser.py, via spec-filen och bygg-mac.sh):
#   UTKATALOG/licens/LICENSE ur kallkoden och KALLA.txt. Floden cachar katalogen tillsammans med whisper-cli.
mkdir -p "$UT/licens"
cp "$UT/src/LICENSE" "$UT/licens/LICENSE"
printf 'whisper.cpp %s\ntagg: %s\ncommit: %s\nkalla: https://github.com/ggml-org/whisper.cpp\n' \
  "$VERSION" "$VERSION" "$FAKTISK" > "$UT/licens/KALLA.txt"
echo "OK: licensen i $UT/licens ($(wc -c < "$UT/licens/LICENSE" | tr -d ' ') byte)"

# Statiskt (BUILD_SHARED_LIBS=OFF): inga libwhisper/libggml-dylib som skulle behova ligga bredvid
#   programmet; hos anvandaren finns inget Homebrew.
# Metal med biblioteket inbaddat (GGML_METAL_EMBED_LIBRARY=ON): ingen .metal-fil behovs bredvid binaren.
# GGML_NATIVE=OFF utan GGML_CPU_ARM_ARCH: maskinen som bygger far inte avgora vilka processorer
#   programmet gar pa. Utan GGML_CPU_ARM_ARCH lagger ggml ingen -march, och kompilatorns standardmal
#   for arm64 pa macOS galler (loggen nedan visar vilka processorfunktioner det ger).
# GGML_OPENMP=OFF: hittar CMake en libomp pa byggmaskinen lankas den annars in, och den finns inte
#   hos anvandaren.
# Okanda CMake-flaggor ger bara en varning ("Manually-specified variables were not used"): leta efter
#   den raden i loggen nedan.
echo "== Kompilatorns processorfunktioner (arm64, macOS 14.0)"
echo | cc -arch arm64 -mmacosx-version-min=14.0 -E -dM - \
  | grep -E '__ARM_NEON|__ARM_FEATURE_(DOTPROD|FP16_VECTOR_ARITHMETIC|FP16_SCALAR_ARITHMETIC|MATMUL_INT8|BF16)' || true

echo "== CMake: konfigurerar"
cmake -S "$UT/src" -B "$UT/bygg" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 \
  -DBUILD_SHARED_LIBS=OFF -DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON \
  -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF \
  -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DWHISPER_SDL2=OFF -DWHISPER_CURL=OFF

echo "== CMake: sammanfattning av valen (ur cache-filen)"
grep -E '^(CMAKE_BUILD_TYPE|CMAKE_OSX_ARCHITECTURES|CMAKE_OSX_DEPLOYMENT_TARGET|BUILD_SHARED_LIBS|GGML_METAL|GGML_METAL_EMBED_LIBRARY|GGML_NATIVE|GGML_OPENMP|GGML_BLAS|GGML_ACCELERATE|WHISPER_[A-Z_]+):' "$UT/bygg/CMakeCache.txt" || true

echo "== CMake: bygger whisper-cli"
cmake --build "$UT/bygg" --config Release -j "$(sysctl -n hw.ncpu)" --target whisper-cli

BIN="$UT/bygg/bin/whisper-cli"
if [ ! -f "$BIN" ]; then
  echo "Hittade inte $BIN. Alla filer som heter whisper-cli under $UT/bygg:"
  find "$UT/bygg" -name whisper-cli -type f
  BIN="$(find "$UT/bygg" -name whisper-cli -type f | sed -n 1p)"
  if [ -z "$BIN" ]; then
    echo "FEL: bygget gav ingen whisper-cli" >&2
    exit 1
  fi
fi
cp "$BIN" "$UT/whisper-cli"
chmod +x "$UT/whisper-cli"

echo "== Bibliotek som whisper-cli lankar mot"
otool -L "$UT/whisper-cli"

echo "== CMake-cachen: OpenMP, Metal, BLAS, Accelerate"
grep -iE "OPENMP|METAL|BLAS|ACCELERATE" "$UT/bygg/CMakeCache.txt" | grep -v '^//' || true

echo "== Klar"
file "$UT/whisper-cli"
ls -l "$UT/whisper-cli"
