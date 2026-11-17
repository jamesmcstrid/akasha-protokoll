#!/bin/bash
# Startar Akasha Meet. Anropas av launchd (se local.akasha-meet.plist), men gar ocksa att kora
# for hand: bash mac/kor.sh   (stoppa med Ctrl-C)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
# launchd har en minimal PATH; Homebrew-verktyg (whisper-cli) maste hittas.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$REPO/app"
exec "$REPO/venv/bin/python" app.py
