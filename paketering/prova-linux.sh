#!/bin/bash
# Provbygge pa Linux med samma spec som Mac-programmet, och samma kontroll som i Actions.
#   bash paketering/prova-linux.sh KATALOG [--utan-nat]
set -euo pipefail
ROT="$(cd "$(dirname "$0")/.." && pwd)"
UT="$(realpath -m "${1:?ange en katalog}")"; shift
mkdir -p "$UT"
[ -x "$UT/venv/bin/python" ] || python3.12 -m venv "$UT/venv"
grep -v '^faster-whisper' "$ROT/app/requirements.txt" > "$UT/krav.txt"
"$UT/venv/bin/pip" install -q -r "$UT/krav.txt" -r "$ROT/paketering/krav-bygg.txt"
"$UT/venv/bin/pyinstaller" --noconfirm --clean --distpath "$UT/dist" --workpath "$UT/pyi" "$ROT/paketering/akasha-protokoll.spec"
EXTRA=(--riktig-rostmodell); [ "${1:-}" = "--utan-nat" ] && EXTRA=()
rm -rf "$UT/hem"
"$UT/venv/bin/python" "$ROT/paketering/kontrollera.py" --program "$UT/dist/akasha-protokoll/akasha-protokoll" \
  --hem "$UT/hem" --port 8680 --vantad-motor faster --vantat-jobbfel faster_whisper ${EXTRA[@]+"${EXTRA[@]}"}
