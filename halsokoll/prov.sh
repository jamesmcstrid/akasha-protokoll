#!/bin/bash
# Prov efter installation. Tar nagra minuter pa CPU. Se halsokoll/prov.py.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
PY="$REPO/venv/bin/python"; [ -x "$PY" ] || PY=python3
exec "$PY" "$REPO/halsokoll/prov.py"
