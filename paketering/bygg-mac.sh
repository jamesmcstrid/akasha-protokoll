#!/bin/bash
# Bygger Akasha Meet.app med PyInstaller, kontrollerar paketet och packar det som en zip-fil.
#   bash paketering/bygg-mac.sh CLI          (kors fran repots rot, pa Mac, med byggets venv i build/venv)
# CLI = den byggda whisper-cli (paketering/bygg-whisper-cli.sh). Resultat: dist/Akasha Meet.app,
# dist/Akasha-Meet-mac-arm64.zip och en uppackad kopia i build/uppackad (den som kontrollera.py provar).
# AKASHA_VERSION och AKASHA_BYGGNUMMER (om satta) lases av spec-filen.
set -euo pipefail
trap 'echo "FEL: bygg-mac.sh stannade pa rad $LINENO: $BASH_COMMAND" >&2' ERR

ROT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROT"
CLI="${1:?ange sokvagen till whisper-cli}"
[ -x "$CLI" ] || { echo "FEL: $CLI finns inte eller ar inte korbar" >&2; exit 1; }
CLI="$(cd "$(dirname "$CLI")" && pwd)/$(basename "$CLI")"
[ -x build/venv/bin/pyinstaller ] || { echo "FEL: build/venv/bin/pyinstaller saknas (skapa venv och installera paketering/krav-bygg.txt)" >&2; exit 1; }
[ -f paketering/ikon-1024.png ] || { echo "FEL: paketering/ikon-1024.png saknas" >&2; exit 1; }
mkdir -p build/app dist

# 1. Ikonen: en .iconset med de storlekar iconutil kraver, sedan .icns.
echo "== 1. ikon"
ICONSET="build/app/ikon.iconset"
mkdir -p "$ICONSET"
for rad in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" "64 icon_32x32@2x" \
           "128 icon_128x128" "256 icon_128x128@2x" "256 icon_256x256" "512 icon_256x256@2x" \
           "512 icon_512x512" "1024 icon_512x512@2x"; do
  # shellcheck disable=SC2086
  set -- $rad
  sips -z "$1" "$1" paketering/ikon-1024.png --out "$ICONSET/$2.png" > /dev/null
done
ls "$ICONSET"
iconutil -c icns "$ICONSET" -o build/app/ikon.icns
[ -s build/app/ikon.icns ] || { echo "FEL: iconutil gav ingen build/app/ikon.icns" >&2; exit 1; }
echo "OK: ikonen build/app/ikon.icns ($(wc -c < build/app/ikon.icns | tr -d ' ') byte)"

# 2. PyInstaller. Utskriften sparas i build/app/pyinstaller.log (laddas upp som artefakt).
echo "== 2. PyInstaller"
AKASHA_WHISPER_CLI="$CLI" AKASHA_IKON="$ROT/build/app/ikon.icns" \
  build/venv/bin/pyinstaller --noconfirm --clean --distpath dist --workpath build/app/pyi \
  paketering/akasha-meet.spec 2>&1 | tee build/app/pyinstaller.log
APP="dist/Akasha Meet.app"
[ -d "$APP" ] || { echo "FEL: PyInstaller gav inget $APP" >&2; exit 1; }
echo "OK: PyInstaller gav $APP"

# 3. Info.plist, signatur och whisper-cli i paketet.
echo "== 3. Info.plist och signatur"
plutil -p "$APP/Contents/Info.plist" | tee build/app/info-plist.txt
grep -q 'NSPrincipalClass' build/app/info-plist.txt || { echo "FEL: Info.plist saknar NSPrincipalClass" >&2; exit 1; }
grep -qE 'LSMinimumSystemVersion.*14\.0' build/app/info-plist.txt || { echo "FEL: Info.plist har inte LSMinimumSystemVersion 14.0" >&2; exit 1; }
echo "OK: Info.plist har NSPrincipalClass och LSMinimumSystemVersion 14.0"
codesign --verify --deep --strict --verbose=2 "$APP"
echo "OK: codesign --verify --deep --strict godkande $APP"
SIGNATUR="$(codesign -dv "$APP" 2>&1)"
echo "$SIGNATUR"
case "$SIGNATUR" in
  *Signature=adhoc*) echo "OK: signaturen ar ad hoc" ;;
  *) echo "FEL: codesign -dv visar inte Signature=adhoc (se raderna ovan)" >&2; exit 1 ;;
esac
if [ ! -x "$APP/Contents/Frameworks/whisper-cli" ]; then
  echo "FEL: $APP/Contents/Frameworks/whisper-cli saknas eller ar inte korbar. Filer som heter whisper-cli i paketet:" >&2
  find "$APP" -name 'whisper-cli*' >&2
  exit 1
fi
echo "OK: Contents/Frameworks/whisper-cli finns och ar korbar"

# 4. Alla Mach-O-filer: arm64 och minos hogst 14.0.
echo "== 4. Mach-O: arkitektur och minos"
find "$APP" -type f -print0 | xargs -0 file | grep -F 'Mach-O' | grep -vF '(for architecture ' | sed -E 's/: +Mach-O .*$//' > build/app/macho-filer.txt
echo "$(grep -c . build/app/macho-filer.txt) Mach-O-filer i paketet"
: > build/app/macho-minos.txt
FELARKITEKTUR=""
FELMINOS=""
UTANMINOS=""
while IFS= read -r fil; do
  ARKITEKTURER="$(lipo -archs "$fil" 2>&1)" || ARKITEKTURER="lipo-fel: $ARKITEKTURER"
  case " $ARKITEKTURER " in
    *" arm64 "*) ;;
    *) FELARKITEKTUR="$FELARKITEKTUR
  $ARKITEKTURER  $fil" ;;
  esac
  # (awk laser all indata: ett tidigt exit skulle ge otool SIGPIPE och, med pipefail, ett tomt svar.)
  # LC_BUILD_VERSION har "minos X", aldre filer LC_VERSION_MIN_MACOSX har "version X".
  MINOS="$(otool -arch arm64 -l "$fil" 2>/dev/null | awk '
      /cmd LC_BUILD_VERSION/ {b=1}
      /cmd LC_VERSION_MIN_MACOSX/ {v=1}
      b && !klar && $1=="minos" {print $2; klar=1}
      v && !klar && $1=="version" {print $2; klar=1}')" || MINOS=""
  if [ -z "$MINOS" ]; then
    UTANMINOS="$UTANMINOS
  $fil"
    echo "okand  $ARKITEKTURER  $fil" >> build/app/macho-minos.txt
    continue
  fi
  echo "$MINOS  $ARKITEKTURER  $fil" >> build/app/macho-minos.txt
  OVER="$(awk -v v="$MINOS" 'BEGIN {
      split(v, a, "."); split("14.0.0", b, ".")
      for (i = 1; i <= 3; i++) { x = a[i] + 0; y = b[i] + 0; if (x > y) { print 1; exit } if (x < y) { print 0; exit } }
      print 0 }')"
  if [ "$OVER" = "1" ]; then
    FELMINOS="$FELMINOS
  $MINOS  $fil"
  fi
done < build/app/macho-filer.txt
echo "Antal filer per minos-version:"
awk '{print $1}' build/app/macho-minos.txt | sort | uniq -c
if [ -n "$UTANMINOS" ]; then
  echo "VARNING: ingen minos hittades i dessa filer (kontrolleras inte):$UTANMINOS"
fi
if [ -n "$FELARKITEKTUR" ]; then
  echo "FEL: filer utan arm64:$FELARKITEKTUR" >&2
  exit 1
fi
if [ -n "$FELMINOS" ]; then
  echo "FEL: filer som kraver nyare an macOS 14.0 (minos):$FELMINOS" >&2
  exit 1
fi
echo "OK: alla Mach-O-filer har arm64 och minos hogst 14.0 (hela listan i build/app/macho-minos.txt)"

# 5. faster-whisper-stacken ska inte finnas i paketet (A6).
echo "== 5. ingen faster-whisper-stack i paketet"
find "$APP" \( -iname 'faster_whisper*' -o -iname 'ctranslate2*' -o -iname 'onnxruntime*' -o -iname 'tokenizers*' \
  -o -iname 'huggingface_hub*' -o -iname 'hf_xet*' \) > build/app/forbjudet.txt
if [ -s build/app/forbjudet.txt ]; then
  echo "FEL: det som inte ska vara med finns i paketet:" >&2
  cat build/app/forbjudet.txt >&2
  exit 1
fi
echo "OK: ingen av faster_whisper, ctranslate2, onnxruntime, tokenizers, huggingface_hub, hf_xet finns i paketet"

# 6. Storlek.
echo "== 6. storlek"
du -sh "$APP"
du -sk "$APP/Contents/Frameworks"/* | sort -rn > build/app/storlekar.txt
echo "De 15 storsta posterna i Contents/Frameworks (kB):"
sed -n 1,15p build/app/storlekar.txt

# 7. Zip-filen (ditto behaller korbarhet, symboliska lankar och signatur) och en uppackad kopia.
echo "== 7. zip och uppackad kopia"
ZIP="dist/Akasha-Meet-mac-arm64.zip"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
rm -rf build/uppackad
mkdir -p build/uppackad
ditto -x -k "$ZIP" build/uppackad
UPPACKAD="build/uppackad/Akasha Meet.app"
[ -d "$UPPACKAD" ] || { echo "FEL: zip-filen gav inget $UPPACKAD vid uppackning. Innehall i build/uppackad:" >&2; ls build/uppackad >&2; exit 1; }
codesign --verify --deep --strict --verbose=2 "$UPPACKAD"
echo "OK: codesign --verify --deep --strict godkande den uppackade kopian"
[ -x "$UPPACKAD/Contents/MacOS/Akasha Meet" ] || { echo "FEL: den uppackade kopian saknar korbar Contents/MacOS/Akasha Meet" >&2; exit 1; }
ls -l "$ZIP"
echo "OK: $ZIP ar $(wc -c < "$ZIP" | tr -d ' ') byte"

# 8. Gatekeeper, bara information: sa har ser macOS pa programmet, och efter nedladdning (karantan).
echo "== 8. spctl (information, inget fel)"
echo "-- utan karantan:"
spctl -a -vv "$APP" 2>&1 || true
xattr -w com.apple.quarantine "0081;$(printf %x "$(date +%s)");Safari;" "$UPPACKAD"
echo "-- med karantan (uppackade kopian):"
spctl -a -vv "$UPPACKAD" 2>&1 || true
xattr -dr com.apple.quarantine "$UPPACKAD" || true  # tillbaka som forut, sa att kontrollera.py kan starta programmet
if xattr "$UPPACKAD" | grep -q 'com.apple.quarantine'; then
  echo "FEL: karantanmarkeringen gick inte att ta bort fran $UPPACKAD" >&2
  exit 1
fi
echo "OK: bygget klart: $APP, $ZIP och $UPPACKAD"
