#!/bin/bash
# Stoppar Akasha Meet och tar bort launchd-agenten. Inspelningarna och modellerna lamnas kvar.
#   bash mac/avinstallera.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
ETIKETT="local.akasha-meet"
launchctl bootout "gui/$(id -u)/$ETIKETT" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$ETIKETT.plist"
DATA="${DATAKATALOG:-$HOME/AkashaMeet}"
echo "Akasha Meet ar stoppad och startar inte langre vid inloggning."
echo "Kvar finns (ta bort for hand om du vill):"
echo "  inspelningar och texter: ${DATA/#\~/$HOME}"
echo "  modeller och venv:       $REPO/modeller  $REPO/venv"
