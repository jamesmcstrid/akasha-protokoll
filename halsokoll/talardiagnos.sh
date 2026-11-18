#!/bin/bash
# Se halsokoll/talardiagnos.py. Läser .env så att samma inställningar gäller som för tjänsten.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
PY="$REPO/venv/bin/python"; [ -x "$PY" ] || PY=python3
exec "$PY" "$REPO/halsokoll/talardiagnos.py" "$@"
