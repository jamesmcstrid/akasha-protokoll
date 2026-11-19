#!/bin/bash
# Hamtar modellerna till MODELLKATALOG (standard: modeller/ i repot) och kontrollerar sha256.
# Vilka filer, revisioner och kontrollsummor som galler star i app/modeller.py (bara dar).
#   bash mac/hamta-modeller.sh ggml talare    # whisper.cpp + talare: Apple Silicon
#   bash mac/hamta-modeller.sh faster talare  # faster-whisper + talare. Samma som utan argument
# Filer som redan finns hamtas inte igen. En avbruten hamtning fortsatter dar den slutade.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
if [ -x "$REPO/venv/bin/python" ]; then
  exec "$REPO/venv/bin/python" "$REPO/app/modeller.py" "$@"
fi
# Utan venv (installera.sh har inte korts an): tillfallig venv med bara requests.
PY="${PYTHON:-python3.12}"
TMPV="$(mktemp -d)"
trap 'rm -rf "$TMPV"' EXIT
"$PY" -m venv "$TMPV"
"$TMPV/bin/pip" install -q "$(grep '^requests==' "$REPO/app/requirements.txt")"
"$TMPV/bin/python" "$REPO/app/modeller.py" "$@"
