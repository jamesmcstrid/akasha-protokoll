#!/bin/bash
# Bygger whisper-cli for Windows (x64) fran kallkod: whisper.cpp fran dess officiella repo, pa en fast tagg,
# med whisper.cpp:s egna Windows-flaggor (jobbet "windows" i dess release.yml), utom SDL2.
#   bash paketering/bygg-whisper-cli-windows.sh VERSION UTKATALOG       (kors fran repots rot, i Git Bash)
#   PYTHON=build/venv/Scripts/python bash paketering/bygg-whisper-cli-windows.sh v1.9.5 build/whisper
# Resultat: UTKATALOG/ut/ med whisper-cli.exe, whisper.dll, ggml.dll, ggml-base.dll, en ggml-cpu-<variant>.dll per
# processorvariant och C-runtime-DLL:erna som filerna importerar. Kors i Actions (paketering/ ar inte till for anvandaren).
# PYTHON ska ha pefile (byggets venv): den hittar vilka C-runtime-DLL:er som ska kopieras in.
set -euo pipefail
trap 'echo "FEL: bygg-whisper-cli-windows.sh stannade pa rad $LINENO: $BASH_COMMAND" >&2' ERR

VERSION="${1:?ange whisper.cpp-version (tagg), till exempel v1.9.5}"
UT="${2:?ange en utkatalog}"
PYTHON="${PYTHON:-python}"
ROT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -e "$UT/src" ] || [ -e "$UT/bygg" ] || [ -e "$UT/ut" ]; then
  echo "FEL: $UT/src, $UT/bygg eller $UT/ut finns redan. Anvand en tom utkatalog." >&2
  exit 1
fi
mkdir -p "$UT"

echo "== Hamtar whisper.cpp $VERSION"
git clone --quiet --depth 1 --branch "$VERSION" https://github.com/ggml-org/whisper.cpp.git "$UT/src"
# Raden "warning: refs/tags/... is not a commit!" vid kloningen ar vantad (taggen ar annoterad och
#   klonas grunt) och betyder inget.
# Taggen far inte flyttas i tysthet: commiten ar last till det som byggdes och kontrollerades i Mac-korning 1
#   (samma tabell som i bygg-whisper-cli.sh). Ny version: lagg till en rad i bada skripten.
case "$VERSION" in
  v1.9.5) VANTAD=d1be6fde11ac6e0407606b4e42fe72d34add8037 ;;
  *) VANTAD="" ;;
esac
FAKTISK="$(git -C "$UT/src" rev-parse HEAD)"
echo "whisper.cpp $VERSION = $FAKTISK"
if [ -n "$VANTAD" ] && [ "$FAKTISK" != "$VANTAD" ]; then
  echo "FEL: taggen $VERSION pekar pa $FAKTISK, vantade $VANTAD" >&2
  exit 1
fi
[ -n "$VANTAD" ] || echo "OBS: $VERSION ar inte last till en commit i bygg-whisper-cli-windows.sh"

# Flaggorna ar whisper.cpp:s egna for Windows x64 (release.yml, jobbet windows, vid commiten):
#   BUILD_SHARED_LIBS=ON            whisper.dll och ggml*.dll bredvid whisper-cli.exe
#   GGML_NATIVE=OFF                 maskinen som bygger far inte avgora vilka processorer programmet gar pa
#   GGML_BACKEND_DL=ON och GGML_CPU_ALL_VARIANTS=ON
#                                   en ggml-cpu-<variant>.dll per processorgeneration; den basta valjs nar
#                                   programmet startar (ggml letar i whisper-cli.exe:s katalog och i arbetskatalogen)
# Dessutom av: SDL2 (inget mikrofonprogram), tester, server och curl.
# OpenMP (GGML_OPENMP) ar pa som standard; vcomp140.dll tas med bland C-runtime-filerna nedan om den importeras.
# C-runtimen lankas dynamiskt (/MD, CMake:s standard): vcruntime140.dll och de andra kopieras in bredvid
#   programmet, eftersom hos anvandaren inte alltid finns Visual C++ Redistributable.
echo "== Byggmiljon"
cmake --version | sed -n 1p
echo "-- CMakes standardgenerator (markerad med *):"
cmake --help | grep -E '^\*' || true
# Git Bash kan inte namnge variabeln ProgramFiles(x86): vanliga platsen, annars vad som ligger i PATH.
VSWHERE="/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"
[ -f "$VSWHERE" ] || VSWHERE="$(command -v vswhere 2>/dev/null || true)"
if [ -n "$VSWHERE" ] && [ -f "$VSWHERE" ]; then
  echo "-- Visual Studio (vswhere):"
  "$VSWHERE" -latest -products '*' -property displayName || true
  "$VSWHERE" -latest -products '*' -property catalog_productDisplayVersion || true
else
  echo "-- vswhere hittades inte (information)"
fi

echo "== CMake: konfigurerar"
cmake -S "$UT/src" -B "$UT/bygg" -A x64 \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
  -DGGML_NATIVE=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON \
  -DWHISPER_SDL2=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DWHISPER_CURL=OFF 2>&1 | tee "$UT/cmake-konfigurera.log"

echo "== CMake: sammanfattning av valen (ur cache-filen)"
grep -E '^(CMAKE_GENERATOR|CMAKE_GENERATOR_PLATFORM|CMAKE_C_COMPILER|CMAKE_CXX_COMPILER|CMAKE_BUILD_TYPE|CMAKE_MSVC_RUNTIME_LIBRARY|BUILD_SHARED_LIBS|GGML_[A-Z0-9_]+|WHISPER_[A-Z0-9_]+|OpenMP[A-Za-z0-9_]*):' "$UT/bygg/CMakeCache.txt" || true
echo "-- Kompilatorn (ur konfigureringen):"
grep -iE 'The (C|CXX) compiler identification|OpenMP|Found OpenMP|ARCH|Adding CPU backend variant' "$UT/cmake-konfigurera.log" | sed -n 1,60p || true
echo "-- Okanda flaggor (ska vara tomt):"
grep -E 'Manually-specified variables were not used' -A6 "$UT/cmake-konfigurera.log" || echo "(inga)"

# Alla standardmal i stallet for att gissa malnamn: backend-DLL:erna (ggml-cpu-*) ar inga beroenden av
# whisper-cli och byggs inte av --target whisper-cli. Ett mal som inte hor till saken kan fela: da raknas bygget
# anda som lyckat om filerna nedan finns (felet skrivs ut hogre upp).
echo "== CMake: bygger alla standardmal (Release)"
KOD=0
cmake --build "$UT/bygg" --config Release -j "${NUMBER_OF_PROCESSORS:-2}" 2>&1 | tee "$UT/cmake-bygg.log" || KOD=$?
echo "cmake --build slutkod: $KOD"
echo "-- Fel och varningar fran bygget (de 40 forsta fel, de 10 forsta varningarna):"
{ grep -E ' error [A-Z]+[0-9]+| fatal error ' "$UT/cmake-bygg.log" | sed -n 1,40p; } || true
{ grep -E ' warning [A-Z]+[0-9]+' "$UT/cmake-bygg.log" | sed -n 1,10p; } || true

echo "== Hittar whisper-cli.exe och DLL-filerna"
BIN="$(find "$UT/bygg" -name whisper-cli.exe -not -path '*CMakeFiles*' | sed -n 1p)"
if [ -z "$BIN" ]; then
  echo "Alla .exe och .dll under $UT/bygg:"
  find "$UT/bygg" \( -name '*.exe' -o -name '*.dll' \) -not -path '*CMakeFiles*' | sort
  echo "FEL: bygget gav ingen whisper-cli.exe (slutkod $KOD)" >&2
  exit 1
fi
BIN_KAT="$(dirname "$BIN")"
echo "whisper-cli.exe: $BIN"
mkdir -p "$UT/ut"
cp "$BIN" "$UT/ut/"
# Alla DLL-filer som byggdes ligger normalt bredvid exe-filen (whisper.cpp satter utkatalogen till bin/).
cp "$BIN_KAT"/*.dll "$UT/ut/" 2>/dev/null || echo "VARNING: inga .dll i $BIN_KAT"
# Och om nagon byggdes pa annat stalle, till exempel i ett eget undermapp per mal:
for dll in $(find "$UT/bygg" \( -name 'whisper.dll' -o -name 'ggml*.dll' \) -not -path '*CMakeFiles*'); do
  if [ ! -f "$UT/ut/$(basename "$dll")" ]; then
    echo "VARNING: $dll lag inte bredvid whisper-cli.exe, kopieras in"
    cp "$dll" "$UT/ut/"
  fi
done

echo "== C-runtime-DLL:er (vcruntime140, msvcp140, vcomp140 ...): kopieras in bredvid programmet"
"$PYTHON" "$ROT/paketering/bygg_windows_verktyg.py" runtime "$UT/ut"

echo "== Filerna i $UT/ut"
"$PYTHON" "$ROT/paketering/bygg_windows_verktyg.py" lista "$UT/ut"

echo "== Processorvarianter (ggml-cpu-*.dll)"
VARIANTER="$(find "$UT/ut" -name 'ggml-cpu-*.dll' | sort)"
if [ -z "$VARIANTER" ]; then
  echo "FEL: ingen ggml-cpu-<variant>.dll byggdes: whisper-cli skulle sakna processorstod. Bygget gav (slutkod $KOD):" >&2
  find "$UT/bygg" -name '*.dll' -not -path '*CMakeFiles*' >&2
  exit 1
fi
echo "$VARIANTER" | sed 's|.*/||'
echo "OK: $(echo "$VARIANTER" | grep -c .) processorvarianter"
[ -f "$UT/ut/whisper.dll" ] && [ -f "$UT/ut/ggml.dll" ] && [ -f "$UT/ut/ggml-base.dll" ] || {
  echo "FEL: whisper.dll, ggml.dll eller ggml-base.dll saknas i $UT/ut" >&2
  exit 1
}
echo "OK: whisper-cli.exe, whisper.dll, ggml.dll och ggml-base.dll finns"

echo "== Beroenden (alla importer ska hittas i samma katalog eller bland Windows egna DLL-filer)"
SYS="${SYSTEMROOT:-C:\\Windows}\\System32"
"$PYTHON" "$ROT/paketering/kontrollera_pe.py" "$UT/ut" --system-katalog "$SYS"
echo "== Klar"
