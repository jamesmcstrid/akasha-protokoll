#!/bin/bash
# Kontrollerar en byggd whisper-cli: bara systembibliotek, alla flaggor som app/motor.py anvander finns,
# och en riktig transkribering av ett testljud med en liten modell vars JSON tolkas av motor.py.
#   bash paketering/kontrollera-whisper-cli.sh CLI PYTHON      (kors fran repots rot, pa Mac)
# CLI = whisper-cli, PYTHON = byggets venv:s python (med numpy och PyAV). Varje kontroll skriver OK: eller FEL:.
set -euo pipefail
trap 'echo "FEL: kontrollera-whisper-cli.sh stannade pa rad $LINENO: $BASH_COMMAND" >&2' ERR

ROT="$(cd "$(dirname "$0")/.." && pwd)"
CLI="${1:?ange whisper-cli}"
PYTHON="${2:?ange Pythonen i byggets venv}"
[ -f "$CLI" ] || { echo "FEL: $CLI finns inte" >&2; exit 1; }
CLI="$(cd "$(dirname "$CLI")" && pwd)/$(basename "$CLI")"
[ -x "$CLI" ] || { echo "FEL: $CLI ar inte korbar" >&2; exit 1; }
PYTHON="$(cd "$(dirname "$PYTHON")" && pwd)/$(basename "$PYTHON")"
# macOS har inget timeout-kommando: samma sak med byggets Python. Gar tiden ut blir det ett Python-fel
# (slutkod 1) i stderr, som den som anropar tar med i sin utskrift.
med_tidsgrans() { "$PYTHON" -c 'import subprocess, sys; sys.exit(subprocess.run(sys.argv[2:], timeout=float(sys.argv[1])).returncode)' "$@"; }
ARB="$(mktemp -d "${TMPDIR:-/tmp}/kontrollera-whisper-cli.XXXXXX")"
echo "Kontrollerar $CLI, arbetskatalog $ARB"
file "$CLI"
ls -l "$CLI"

# 1. Bara systembibliotek (hos anvandaren finns inget Homebrew).
echo "== 1. otool -L"
otool -L "$CLI"
LIBS="$(otool -L "$CLI" | tail -n +2 | sed -E 's/^[[:space:]]+//; s/ \(.*$//')"
OVRIGA=""
while IFS= read -r lib; do
  [ -n "$lib" ] || continue
  case "$lib" in
    /usr/lib/*|/System/Library/*) ;;
    *) OVRIGA="$OVRIGA $lib" ;;
  esac
done <<< "$LIBS"
if [ -n "$OVRIGA" ]; then
  echo "FEL: whisper-cli lankar mot bibliotek utanfor /usr/lib och /System/Library:$OVRIGA" >&2
  exit 1
fi
echo "OK: alla $(echo "$LIBS" | grep -c .) bibliotek ligger i /usr/lib eller /System/Library"

# 2. Flaggorna som motor._whispercpp anvander.
echo "== 2. flaggor i --help"
"$CLI" --help > "$ARB/help.txt" 2>&1 || true
cat "$ARB/help.txt"
SAKNAS=""
for f in -m -f -l -bs -np -pp -oj -of --prompt -t -ml -sow --dtw -nfa -ojf; do
  grep -qE -- "(^|[[:space:],])$f([[:space:],=]|$)" "$ARB/help.txt" || SAKNAS="$SAKNAS $f"
done
if [ -n "$SAKNAS" ]; then
  echo "FEL: whisper-cli saknar flaggorna$SAKNAS som app/motor.py anvander (se --help ovan)" >&2
  exit 1
fi
echo "OK: alla 15 flaggor finns i --help"

# 3. Den lilla modellen, bara for den har kontrollen (ingen modell for programmet, darfor inte i app/modeller.py).
echo "== 3. testmodellen ggml-tiny-q5_1.bin"
URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny-q5_1.bin"
SHA="818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7"
curl -sSfL --retry 3 --retry-delay 5 -o "$ARB/tiny.bin" "$URL"
ls -l "$ARB/tiny.bin"
FAKTISK="$(shasum -a 256 "$ARB/tiny.bin" | awk '{print $1}')"
if [ "$FAKTISK" != "$SHA" ]; then
  echo "FEL: sha256 for testmodellen ar $FAKTISK, vantade $SHA (filens forsta byte: $(head -c 120 "$ARB/tiny.bin" | tr -c '[:print:]' '.'))" >&2
  exit 1
fi
echo "OK: testmodellen har sha256 $SHA"

# 4. Testljudet som 16 kHz mono WAV (whisper-cli laser inte m4a).
echo "== 4. afconvert"
afconvert -f WAVE -d LEI16@16000 -c 1 "$ROT/testljud/en-talare.m4a" "$ARB/en.wav"
ls -l "$ARB/en.wav"
[ -s "$ARB/en.wav" ] || { echo "FEL: afconvert gav ingen WAV-fil" >&2; exit 1; }
echo "OK: testljudet omvandlat till $ARB/en.wav"

# 5. Systeminformation, bara for loggen: anvandes Metal?
echo "== 5. system_info och Metal"
"$CLI" -m "$ARB/tiny.bin" -f "$ARB/en.wav" -l sv > "$ARB/sysinfo.txt" 2>&1 || true
grep -iE "metal|gpu|system_info|backend" "$ARB/sysinfo.txt" > "$ARB/sysinfo-rader.txt" || true
sed -n 1,60p "$ARB/sysinfo-rader.txt"
echo "(information, ingen kontroll)"

# 6. Samma flaggor som motor._whispercpp med ordtider.
echo "== 6. transkribering med ordtider"
KOMMANDO=("$CLI" -m "$ARB/tiny.bin" -f "$ARB/en.wav" -l sv -bs 5 -np -pp -oj -of "$ARB/ut" -ml 1 -sow --dtw tiny -nfa -ojf)
echo "${KOMMANDO[@]}"
T0="$(date +%s)"
if ! "${KOMMANDO[@]}" > "$ARB/korning.txt" 2>&1; then
  echo "--- whisper-cli, sista 40 raderna ---"
  tail -n 40 "$ARB/korning.txt"
  echo "--- diagnos: samma kommando med -ng (utan GPU) ---"
  if "${KOMMANDO[@]}" -ng > "$ARB/korning-ng.txt" 2>&1; then
    echo "Utan GPU (-ng) gick det: felet ligger i Metal pa den har maskinen."
  else
    echo "Inte heller utan GPU gick det. Sista 20 raderna:"
    tail -n 20 "$ARB/korning-ng.txt"
  fi
  echo "FEL: whisper-cli med motor.py:s flaggor avslutades med fel (se raderna ovan)" >&2
  exit 1
fi
T1="$(date +%s)"
tail -n 5 "$ARB/korning.txt"
[ -s "$ARB/ut.json" ] || { echo "FEL: whisper-cli gav ingen $ARB/ut.json (-oj -of)" >&2; exit 1; }
echo "OK: whisper-cli transkriberade testljudet pa $((T1 - T0)) s, $(wc -c < "$ARB/ut.json" | tr -d ' ') byte JSON"

# 7. JSON-filen tolkas som motor.py gor.
echo "== 7. JSON tolkad med app/motor.py"
"$PYTHON" "$ROT/paketering/las_whisper_json.py" "$ARB/ut.json"

# 8. DTW-forvalen som app/modeller.py anvander (medium och large.v3) ska kanna igen av den har
#    versionen. De stora modellerna behovs inte: forvalet tolkas av whisper-cli oavsett modell, och
#    huvudena for medium och large passar inte tiny-modellen (resultatet sager inget om kvaliteten).
echo "== 8. DTW-forval"
FORVAL="$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); import modeller; print(" ".join(sorted(set(modeller.DTW_PER_STORLEK.values()))))' "$ROT/app")" || FORVAL=""
if [ -z "$FORVAL" ]; then
  echo "FEL: kunde inte lasa DTW-forvalen ur app/modeller.py (modeller.DTW_PER_STORLEK), kan inte avgora om de kanns igen" >&2
  exit 1
fi
echo "Forval ur app/modeller.py: $FORVAL"

# 8a. Ett pahittat forval: visar hur den har versionen sager ifran om ett forval inte finns.
echo "--- 8a. okant forval (--dtw finns-inte)"
KOD=0
med_tidsgrans 120 "$CLI" -m "$ARB/tiny.bin" -f "$ARB/en.wav" -l sv -d 3000 -np --dtw finns-inte 2> "$ARB/okant.txt" > /dev/null || KOD=$?
echo "kod $KOD"
tail -n 5 "$ARB/okant.txt"
grep -i dtw "$ARB/okant.txt" > "$ARB/okant-dtw.txt" || true
if [ ! -s "$ARB/okant-dtw.txt" ]; then
  echo "FEL: kan inte avgora om DTW-forvalen kanns igen: whisper-cli sa ingenting om dtw for ett pahittat forval (se okant.txt-raderna ovan), sa jamforelsen har inget att jamfora mot" >&2
  exit 1
fi
echo "Rader om dtw vid okant forval:"
cat "$ARB/okant-dtw.txt"

# 8b. Varje riktigt forval: ingen av dtw-raderna ovan far finnas ordagrant i utskriften. Namnet pa det
#     pahittade forvalet byts ocksa mot forvalets eget i raderna (annars skulle ett felmeddelande som
#     namner forvalet, "unknown ... 'medium'", aldrig vara lika med "unknown ... 'finns-inte'").
for f in $FORVAL; do
  echo "--- 8b. forval $f"
  KOD=0
  med_tidsgrans 120 "$CLI" -m "$ARB/tiny.bin" -f "$ARB/en.wav" -l sv -d 3000 -np -ml 1 -sow --dtw "$f" -nfa -ojf -oj -of "$ARB/dtw-$f" 2> "$ARB/dtw-$f.txt" > /dev/null || KOD=$?
  echo "kod $KOD"
  tail -n 5 "$ARB/dtw-$f.txt"
  if [ -s "$ARB/dtw-$f.json" ]; then echo "JSON-filen blev till (information, ingen kontroll)"; else echo "ingen JSON-fil (information, ingen kontroll)"; fi
  # Utan en enda rad fran whisper.cpp har kommandot inte kommit igang (till exempel tidsgrans), och da
  # saknas det mesta som jamforelsen ska bygga pa.
  if ! grep -q 'whisper_' "$ARB/dtw-$f.txt"; then
    echo "FEL: kan inte avgora om DTW-forvalet $f kanns igen: whisper-cli gav inga whisper_-rader (kod $KOD), se raderna ovan" >&2
    exit 1
  fi
  { cat "$ARB/okant-dtw.txt"; sed "s/finns-inte/$f/g" "$ARB/okant-dtw.txt"; } > "$ARB/mall-$f.txt"
  if grep -n -x -F -f "$ARB/mall-$f.txt" "$ARB/dtw-$f.txt" > "$ARB/lika-$f.txt"; then
    echo "FEL: forvalet $f kanns inte igen: en dtw-rad som for ett pahittat forval (namnet utbytt) finns i utskriften:" >&2
    cat "$ARB/lika-$f.txt" >&2
    exit 1
  fi
  echo "OK: forvalet $f kanns igen (ingen dtw-rad fran det pahittade forvalet finns i utskriften)"
done

echo "KONTROLL AV WHISPER-CLI: OK"
