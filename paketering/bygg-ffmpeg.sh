#!/bin/bash
# Bygger ett minimalt FFmpeg 6.1.6 (LGPL-2.1-or-later, inga externa bibliotek) som delade bibliotek, fran kallkod.
#   bash paketering/bygg-ffmpeg.sh KATALOG        (kors fran repots rot: Linux, Mac, och MSYS2 UCRT64 pa Windows)
# Resultat:
#   KATALOG/prefix/          installationen (lib/, include/, och pa Windows bin/ med DLL-filerna och lib/ med importbibliotek)
#   KATALOG/ut/ffmpeg/       COPYING.LGPLv2.1, LICENSE.md, CREDITS, configure.txt (hela configure-raden), KALLA.txt
#   KATALOG/ut/kallkod/      ffmpeg-6.1.6-kallkod.tar.xz (kallkoden som byggdes) med bygg-ffmpeg.sh och ffmpeg-komponenter.txt bredvid
# Flaggorna som ar lika pa alla system star i paketering/ffmpeg-komponenter.txt; systemets tillagg star har.
# Hamtar bara kallkoden fran GitHub-spegeln av FFmpeg, pa en fast tagg och commit.
set -euo pipefail
trap 'echo "FEL: bygg-ffmpeg.sh stannade pa rad $LINENO: $BASH_COMMAND" >&2' ERR

TAGG=n6.1.6
VERSION=6.1.6
VANTAD=f1e3a2bf7a2f2cde936d1ed97f09a26853d20125
ADRESS=https://github.com/FFmpeg/FFmpeg.git
SKRIPT_KAT="$(cd "$(dirname "$0")" && pwd)"
KOMPONENTER="$SKRIPT_KAT/ffmpeg-komponenter.txt"

KAT="${1:?ange en utkatalog}"
[ -f "$KOMPONENTER" ] || { echo "FEL: $KOMPONENTER saknas" >&2; exit 1; }
if [ -e "$KAT/kalla" ] || [ -e "$KAT/prefix" ] || [ -e "$KAT/ut" ]; then
  echo "FEL: $KAT/kalla, $KAT/prefix eller $KAT/ut finns redan. Anvand en tom utkatalog." >&2
  exit 1
fi
mkdir -p "$KAT"
KAT="$(cd "$KAT" && pwd)"
PREFIX="$KAT/prefix"

case "$(uname -s)" in
  Linux)
    SYSTEM=linux
    TILLAGG=(--enable-pthreads)
    ANTAL="$(nproc)" ;;
  Darwin)
    SYSTEM=mac
    # minos 14.0 (bygg-mac.sh steg 4 faller annars bygget) och plats i install names for delocate
    export MACOSX_DEPLOYMENT_TARGET=14.0
    TILLAGG=(--enable-pthreads --arch=arm64 --extra-cflags=-mmacosx-version-min=14.0
             "--extra-ldflags=-mmacosx-version-min=14.0 -Wl,-headerpad_max_install_names")
    ANTAL="$(sysctl -n hw.ncpu)" ;;
  MINGW*|UCRT64*|CLANG64*|MSYS*|CYGWIN*)  # MSYS2: uname -s foljer MSYSTEM (UCRT64_NT-... i UCRT64)
    SYSTEM=windows
    # w32threads sags uttryckligen (configure raknar tradarna som autodetekterade), och libgcc lankas in statiskt:
    # annars skulle DLL-filerna behova libgcc_s_seh-1.dll
    TILLAGG=(--enable-w32threads --extra-ldflags=-static-libgcc)
    ANTAL="${NUMBER_OF_PROCESSORS:-2}" ;;
  *) echo "FEL: okant system $(uname -s)" >&2; exit 1 ;;
esac
echo "== System: $SYSTEM, $ANTAL processorer"

echo "== Hamtar FFmpeg $TAGG"
git clone --quiet --depth 1 --branch "$TAGG" "$ADRESS" "$KAT/kalla"
FAKTISK="$(git -C "$KAT/kalla" rev-parse HEAD)"
echo "FFmpeg $TAGG = $FAKTISK"
if [ "$FAKTISK" != "$VANTAD" ]; then
  echo "FEL: taggen $TAGG pekar pa $FAKTISK, vantade $VANTAD. Taggen far inte flyttas i tysthet." >&2
  exit 1
fi

# flaggorna ur komponentfilen (utan kommentarer och tomma rader)
FLAGGOR=()
while IFS= read -r rad; do
  rad="${rad%$'\r'}"
  case "$rad" in ''|'#'*) continue ;; esac
  FLAGGOR+=("$rad")
done < "$KOMPONENTER"
echo "== ${#FLAGGOR[@]} flaggor ur ffmpeg-komponenter.txt, systemets tillagg: ${TILLAGG[*]}"

# Kompilatorn som configure anvander (cc pa Linux och Mac, gcc i MSYS2 UCRT64, dar cc kan saknas)
KOMPILATOR="$(command -v cc || command -v gcc || true)"
[ -n "$KOMPILATOR" ] || { echo "FEL: varken cc eller gcc finns" >&2; exit 1; }
echo "== Kompilator: $KOMPILATOR"
"$KOMPILATOR" --version | sed -n 1p

echo "== configure"
mkdir -p "$KAT/bygg"
cd "$KAT/bygg"
"$KAT/kalla/configure" --prefix="$PREFIX" "${FLAGGOR[@]}" ${TILLAGG[@]+"${TILLAGG[@]}"} > configure.log 2>&1 \
  || { tail -40 configure.log; echo "-- slutet av ffbuild/config.log:"; tail -60 ffbuild/config.log 2>/dev/null || true
       echo "FEL: configure misslyckades" >&2; exit 1; }
grep -E '^License' configure.log
echo "-- Externa bibliotek (ska vara tomma):"
sed -n '/^External libraries:/,/^$/p;/^External libraries providing hardware acceleration:/,/^$/p' configure.log

echo "== make -j$ANTAL"
make -j"$ANTAL" > make.log 2>&1 || { tail -40 make.log; echo "FEL: make misslyckades" >&2; exit 1; }
make install > install.log 2>&1 || { tail -40 install.log; echo "FEL: make install misslyckades" >&2; exit 1; }

if [ "$SYSTEM" = windows ]; then
  # dlltool-importbiblioteken ligger i bin/ (configure, mingw); PyAV:s setup.py letar efter dem i lib/
  cp "$PREFIX"/bin/*.lib "$PREFIX/lib/"
  ANTAL_LIB="$(ls "$PREFIX"/lib/*.lib | wc -l | tr -d ' ')"
  [ "$ANTAL_LIB" = 7 ] || { echo "FEL: $ANTAL_LIB .lib-filer i $PREFIX/lib, vantade sju" >&2; ls "$PREFIX/lib" >&2; exit 1; }
  echo "OK: sju .lib-filer kopierade till $PREFIX/lib"
fi

echo "== Licensen i det som byggdes"
grep -E '^License' configure.log | sed 's/^/OK: /'

echo "== Licenstexter, configure-raden och kallkoden"
UT="$KAT/ut"
mkdir -p "$UT/ffmpeg" "$UT/kallkod"
for fil in COPYING.LGPLv2.1 LICENSE.md CREDITS; do
  cp "$KAT/kalla/$fil" "$UT/ffmpeg/$fil"
done
# hela configure-raden, som den star inbyggd i biblioteken
grep -E '^#define FFMPEG_CONFIGURATION ' "$KAT/bygg/config.h" | sed -E 's/^#define FFMPEG_CONFIGURATION "(.*)"$/\1/' > "$UT/ffmpeg/configure.txt"
[ -s "$UT/ffmpeg/configure.txt" ] || { echo "FEL: hittade inte FFMPEG_CONFIGURATION i config.h" >&2; exit 1; }
{
  echo "FFmpeg $VERSION"
  echo "tagg: $TAGG"
  echo "commit: $FAKTISK"
  echo "kalla: $ADRESS"
  echo "kompilator: $("$KOMPILATOR" --version | sed -n 1p)"
  echo "system: $SYSTEM"
} > "$UT/ffmpeg/KALLA.txt"
if [ "$SYSTEM" = windows ]; then
  # MinGW-runtimens licenstexter (libgcc ar inlankad: GCC Runtime Library Exception)
  for hjalp in COPYING3 COPYING.RUNTIME; do
    fil="$(find /ucrt64 -name "$hjalp*" -path '*gcc*' 2>/dev/null | sed -n 1p)"
    [ -n "$fil" ] && cp "$fil" "$UT/ffmpeg/$hjalp" || echo "VARNING: hittade inte $hjalp for MinGW-runtimen"
  done
  # mingw-w64-runtimen (startkoden och delar av libmingwex lankas in i varje DLL): dess licenstext
  fil="$(find /ucrt64/share/licenses -name 'COPYING.MinGW-w64-runtime*' 2>/dev/null | sed -n 1p)"
  [ -n "$fil" ] && cp "$fil" "$UT/ffmpeg/COPYING.MinGW-w64-runtime.txt" || echo "VARNING: hittade inte mingw-w64-runtimens licens"
  ls -l "$UT/ffmpeg"
fi
# kallkoden som arkiv: samma innehall varje gang (git archive ar deterministiskt, xz med en trad)
git -C "$KAT/kalla" archive --format=tar --prefix=ffmpeg-$VERSION/ HEAD | xz -6 -T1 > "$UT/kallkod/ffmpeg-$VERSION-kallkod.tar.xz"
cp "$SKRIPT_KAT/bygg-ffmpeg.sh" "$SKRIPT_KAT/ffmpeg-komponenter.txt" "$UT/kallkod/"
tar -tJf "$UT/kallkod/ffmpeg-$VERSION-kallkod.tar.xz" | grep -x "ffmpeg-$VERSION/COPYING.LGPLv2.1" > /dev/null \
  || { echo "FEL: kallkodsarkivet saknar COPYING.LGPLv2.1" >&2; exit 1; }
echo "OK: kallkodsarkivet $(ls -l "$UT/kallkod/ffmpeg-$VERSION-kallkod.tar.xz" | awk '{print $5}') byte"

echo "== configure-raden"
cat "$UT/ffmpeg/configure.txt"
echo "== Biblioteken"
ls -l "$PREFIX/lib" | sed -n '1,40p'
if [ "$SYSTEM" = windows ]; then ls -l "$PREFIX/bin"; fi
echo "== Klar"
