#!/bin/bash
# Provbygge pa Linux med samma spec som Mac-programmet, och samma kontroll som i Actions. Programmet byggs med det egna
# LGPL-bygget av FFmpeg och PyAV (paketering/bygg-ffmpeg.sh, bygg-pyav.sh); PyPI-hjulet av (GPL) installeras aldrig.
#   bash paketering/prova-linux.sh KATALOG [--utan-nat]
# Kraver gcc, make, nasm, git, xz och python3.12 (FFmpeg tar cirka 25 s att bygga och PyAV cirka 40 s).
set -euo pipefail
ROT="$(cd "$(dirname "$0")/.." && pwd)"
UT="$(realpath -m "${1:?ange en katalog}")"; shift
for verktyg in gcc make nasm git xz python3.12 curl; do
  command -v "$verktyg" > /dev/null || { echo "FEL: $verktyg saknas (behovs for att bygga FFmpeg och PyAV)" >&2; exit 1; }
done
mkdir -p "$UT"

FF="$UT/ffmpeg"
if ! ls "$FF"/ut/av-12.3.0-*.whl > /dev/null 2>&1; then
  if [ -e "$FF" ]; then
    echo "FEL: $FF finns men har inget PyAV-hjul i ut/ (ett avbrutet bygge): ta bort katalogen och kor igen" >&2
    exit 1
  fi
  bash "$ROT/paketering/bygg-ffmpeg.sh" "$FF"
  bash "$ROT/paketering/bygg-pyav.sh" "$FF" python3.12
fi
HJUL="$(ls "$FF"/ut/av-12.3.0-*.whl)"
echo "== Det egna hjulet: $HJUL"

[ -x "$UT/venv/bin/python" ] || python3.12 -m venv "$UT/venv"
# Utan faster-whisper (programmet har whisper.cpp) och utan av: PyPI-hjulet har GPL-bibliotek (x264, x265 m.fl.).
grep -v -E '^(faster-whisper|av)==' "$ROT/app/requirements.txt" > "$UT/krav.txt"
"$UT/venv/bin/pip" install -q -r "$UT/krav.txt" -r "$ROT/paketering/krav-bygg.txt"
# --no-index: ingen reserv till PyPI. --force-reinstall: en tidigare venv kan ha haft PyPI-hjulet.
"$UT/venv/bin/pip" install -q --no-deps --no-index --force-reinstall "$HJUL"
"$UT/venv/bin/pip" show av | sed -n 1,3p
"$UT/venv/bin/python" -c "import av._core as c; print('libavcodec:', c.library_meta['libavcodec']['license'])"

"$UT/venv/bin/python" "$ROT/paketering/kontrollera_ffmpeg.py" --hjul "$HJUL"
"$UT/venv/bin/pyinstaller" --noconfirm --clean --distpath "$UT/dist" --workpath "$UT/pyi" "$ROT/paketering/akasha-protokoll.spec"
"$UT/venv/bin/python" "$ROT/paketering/kontrollera_ffmpeg.py" --katalog "$UT/dist/akasha-protokoll"
strings -n 8 "$UT"/dist/akasha-protokoll/_internal/av.libs/libavcodec-* | grep 'license: '
du -sh "$UT/dist/akasha-protokoll"

EXTRA=(--riktig-rostmodell); [ "${1:-}" = "--utan-nat" ] && EXTRA=()
rm -rf "$UT/hem"
"$UT/venv/bin/python" "$ROT/paketering/kontrollera.py" --program "$UT/dist/akasha-protokoll/akasha-protokoll" \
  --hem "$UT/hem" --port 8680 --vantad-motor faster --vantat-jobbfel faster_whisper ${EXTRA[@]+"${EXTRA[@]}"}
