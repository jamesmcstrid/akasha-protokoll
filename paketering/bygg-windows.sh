#!/bin/bash
# Bygger Akasha Protokoll for Windows med PyInstaller, kontrollerar paketet och packar det som en zip-fil.
#   bash paketering/bygg-windows.sh WHISPERKATALOG      (kors fran repots rot, i Git Bash, med byggets venv i build/venv)
# WHISPERKATALOG = katalogen med whisper-cli.exe och DLL-filerna (paketering/bygg-whisper-cli-windows.sh, build/whisper/ut).
# Resultat: dist/Akasha Protokoll/ (Akasha Protokoll.exe och _internal\), dist/Akasha-Protokoll-windows-x64.zip och en
# uppackad kopia i build/uppackad/<katalogen UPPACKAD nedan>/Akasha Protokoll/ (den som kontrollera.py provar: programmet
# ska fungera fran en sokvag med a-ring, a-prickar och o-prickar och mellanslag, som en installation under anvandarens profil).
# AKASHA_VERSION och AKASHA_BYGGNUMMER (om satta) lases av spec-filen och versionsresursen.
# Kontrollerna efter bygget (steg 4-7) stoppar inte vid forsta felet: alla kors, zip-filen skapas anda, och skriptet
# ger slutkod 1 sist om nagot var FEL. Bara ett misslyckat PyInstaller-bygge stoppar direkt.
set -euo pipefail
trap 'echo "FEL: bygg-windows.sh stannade pa rad $LINENO: $BASH_COMMAND" >&2' ERR

ROT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROT"
WHISPER="${1:?ange katalogen med whisper-cli.exe och DLL-filerna}"
PY="build/venv/Scripts/python"
VERKTYG="paketering/bygg_windows_verktyg.py"
NAMN="Akasha Protokoll"
ZIP="dist/Akasha-Protokoll-windows-x64.zip"
UPPACKAD="build/uppackad/Åsa Ölund"
VERSION="${AKASHA_VERSION:-0.2.0}"
BYGGNUMMER="${AKASHA_BYGGNUMMER:-1}"
FEL_ANTAL=0
FELLISTA=""

fel() {
  echo "FEL: $*"
  FEL_ANTAL=$((FEL_ANTAL + 1))
  FELLISTA="$FELLISTA
  $*"
}
# Windows-sokvag (D:/a/...) for miljovariabler till Python: Git Bash omskriver annars /d/a/... pa egen hand.
winsokvag() { (cd "$1" && { pwd -W 2>/dev/null || pwd; }); }

[ -f "$PY" ] || [ -f "$PY.exe" ] || { echo "FEL: $PY saknas (skapa venv och installera paketering/krav-bygg.txt)" >&2; exit 1; }
[ -f paketering/ikon-1024.png ] || { echo "FEL: paketering/ikon-1024.png saknas" >&2; exit 1; }
"$PY" -c "import PyInstaller, pefile, PIL, pystray; print('PyInstaller', PyInstaller.__version__, '| pefile', pefile.__version__, '| Pillow', PIL.__version__)" \
  || { echo "FEL: PyInstaller, pefile, Pillow eller pystray saknas i build/venv (paketering/krav-bygg.txt)" >&2; exit 1; }
mkdir -p build/app dist
if [ ! -d "$WHISPER" ]; then
  fel "$WHISPER finns inte: programmet byggs utan whisper-cli (en tom katalog)"
  mkdir -p "$WHISPER"
fi
WHISPER_ABS="$(winsokvag "$WHISPER")"

# 1. Ikonen: .ico med storlekarna 16-256 ur paketering/ikon-1024.png.
echo "== 1. ikon"
IKON=""
if "$PY" "$VERKTYG" ikon paketering/ikon-1024.png build/app/ikon.ico; then
  IKON="$(winsokvag build/app)/ikon.ico"
else
  fel "ikonen gick inte att skapa (exe-filen far PyInstallers standardikon)"
fi

# 2. Versionsresursen (Egenskaper, fliken Information).
echo "== 2. versionsresurs"
VERSIONSFIL=""
if "$PY" "$VERKTYG" versionsfil build/app/versionsfil.txt "$VERSION" "$BYGGNUMMER"; then
  VERSIONSFIL="$(winsokvag build/app)/versionsfil.txt"
else
  fel "versionsfilen gick inte att skriva"
fi

# 3. PyInstaller. Utskriften sparas i build/app/pyinstaller.log (laddas upp som artefakt).
echo "== 3. PyInstaller"
rm -rf "dist/$NAMN"
AKASHA_WHISPER_KATALOG="$WHISPER_ABS" AKASHA_IKON="$IKON" AKASHA_VERSIONSFIL="$VERSIONSFIL" \
  AKASHA_VERSION="$VERSION" AKASHA_BYGGNUMMER="$BYGGNUMMER" \
  "$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/app/pyi \
  paketering/akasha-protokoll.spec 2>&1 | tee build/app/pyinstaller.log
DIST="dist/$NAMN"
[ -d "$DIST" ] || { echo "FEL: PyInstaller gav inget $DIST" >&2; exit 1; }
echo "OK: PyInstaller gav $DIST"
VARNINGSFIL="$(find build/app/pyi -name 'warn-*.txt' | sed -n 1p)"
if [ -n "$VARNINGSFIL" ]; then
  echo "-- PyInstallers varningsfil $VARNINGSFIL: $(wc -l < "$VARNINGSFIL" | tr -d ' ') rader; de som galler import pa toppnivan:"
  { grep -E 'top-level' "$VARNINGSFIL" | sed -n 1,40p; } || true
fi

# 4. Innehallet.
echo "== 4. innehallet"
for fil in "$DIST/$NAMN.exe" "$DIST/_internal/whisper/whisper-cli.exe" "$DIST/_internal/whisper/whisper.dll" \
           "$DIST/_internal/ikon.png" "$DIST/_internal/static/app.js" "$DIST/_internal/python312.dll"; do
  if [ -f "$fil" ]; then echo "OK: $fil finns"; else fel "$fil saknas"; fi
done
if ls "$DIST/_internal/whisper"/ggml-cpu-*.dll > /dev/null 2>&1; then
  echo "OK: $(ls "$DIST/_internal/whisper"/ggml-cpu-*.dll | wc -l | tr -d ' ') processorvarianter (ggml-cpu-*.dll) bredvid whisper-cli.exe"
else
  fel "ingen ggml-cpu-*.dll bredvid whisper-cli.exe"
fi
echo "Filerna i $DIST/_internal/whisper:"
ls -l "$DIST/_internal/whisper" 2>/dev/null || true
"$PY" "$VERKTYG" exeinfo "$DIST/$NAMN.exe" || fel "versionsresurs, ikon eller undersystem i $NAMN.exe stammer inte (se raderna ovan)"

# 5. Beroenden: varje exe, dll och pyd ska hitta alla sina importer (Windows motsvarighet till otool -L) och vara x64.
echo "== 5. DLL-beroenden och arkitektur"
"$PY" paketering/kontrollera_pe.py "$DIST" --system-katalog "${SYSTEMROOT:-C:\\Windows}\\System32" --ut build/app/pe-importer.txt \
  || fel "DLL-beroendena stammer inte (se raderna ovan, hela tabellen i build/app/pe-importer.txt)"

# 6. faster-whisper-stacken och tkinter ska inte finnas i paketet (A6).
echo "== 6. ingen faster-whisper-stack i paketet"
"$PY" "$VERKTYG" forbjudet "$DIST" || fel "det som inte ska vara med finns i paketet (se raderna ovan)"

# 7. Storlek.
echo "== 7. storlek"
"$PY" "$VERKTYG" storlekar "$DIST" | tee build/app/storlekar.txt

# 8. Zip-filen (mappen "Akasha Protokoll" overst) och en uppackad kopia i en katalog med a-ring och o-prickar i namnet.
echo "== 8. zip och uppackad kopia"
if "$PY" "$VERKTYG" zip "$DIST" "$ZIP"; then
  ls -l "$ZIP"
  "$PY" "$VERKTYG" uppacka "$ZIP" "$UPPACKAD" || fel "uppackningen av $ZIP till $UPPACKAD misslyckades"
  if [ -f "$UPPACKAD/$NAMN/$NAMN.exe" ]; then
    echo "OK: den uppackade kopian har $UPPACKAD/$NAMN/$NAMN.exe"
  else
    fel "den uppackade kopian saknar $UPPACKAD/$NAMN/$NAMN.exe"
  fi
else
  fel "zip-filen gick inte att skapa"
fi

echo "== Sammanfattning av bygget"
if [ "$FEL_ANTAL" -gt 0 ]; then
  echo "FEL: $FEL_ANTAL fel i bygget:$FELLISTA"
  exit 1
fi
echo "OK: bygget klart: $DIST, $ZIP och $UPPACKAD/$NAMN"
