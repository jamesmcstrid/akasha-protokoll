#!/bin/bash
# Installerar Akasha Meet for inloggad anvandare. Gar att kora igen (t.ex. efter git pull).
#   bash mac/installera.sh
#
# Gor: venv med beroenden, valjer motor, hamtar modellerna (cirka 1,6 GB, bara forsta gangen),
# skapar .env, lagger en launchd-agent som startar tjansten vid inloggning, och oppnar webbsidan.
# Pa Mac med Apple Silicon installeras whisper-cpp (Homebrew) sa att grafikprocessorn anvands.
# Kraver: Homebrew och python3.12 (brew install python@3.12).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3.12}"
LA="$HOME/Library/LaunchAgents"
ETIKETT="local.akasha-meet"
UIDN="$(id -u)"

command -v "$PY" >/dev/null || { echo "FEL: $PY saknas. Kor: brew install python@3.12"; exit 1; }
[ "$(uname -s)" = "Darwin" ] || echo "OBS: skriptet ar gjort for macOS (launchd)."

[ -f "$REPO/.env" ] || { cp "$REPO/.env.example" "$REPO/.env"; echo "== skapade .env (standardinstallningar)"; }
set -a; . "$REPO/.env"; set +a
MOTOR="${MOTOR:-auto}"
PORT="${PORT:-8611}"
DATA="${DATAKATALOG:-$HOME/AkashaMeet}"; DATA="${DATA/#\~/$HOME}"
MODELLER="${MODELLKATALOG:-$REPO/modeller}"; MODELLER="${MODELLER/#\~/$HOME}"

echo "== venv och beroenden"
[ -d "$REPO/venv" ] || "$PY" -m venv "$REPO/venv"
"$REPO/venv/bin/pip" install -q --upgrade pip
"$REPO/venv/bin/pip" install -q -r "$REPO/app/requirements.txt"

# Samma val som appen gor (app/motor.py, valj_motor): auto blir whisper.cpp med Metal pa
# Apple Silicon, annars faster-whisper.
CLI="${WHISPERCPP_BIN:-whisper-cli}"
har_cli() { PATH="/opt/homebrew/bin:/usr/local/bin:$PATH" command -v "$CLI" >/dev/null; }
AKTIV="$MOTOR"
if [ "$MOTOR" = "auto" ]; then
  AKTIV=faster
  if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
    if ! har_cli && command -v brew >/dev/null; then
      echo "== installerar whisper-cpp (Homebrew), sa att grafikprocessorn anvands"
      brew install whisper-cpp
    fi
    if har_cli; then AKTIV=whispercpp; fi
  fi
fi
if [ "$AKTIV" = "whispercpp" ] && ! har_cli; then
  echo "FEL: MOTOR=whispercpp men $CLI saknas. Kor: brew install whisper-cpp"; exit 1
fi

echo "== modeller i $MODELLER (motor: $AKTIV)"
if [ "$AKTIV" = "whispercpp" ]; then
  [ -f "$MODELLER/kb-whisper-medium-ggml/ggml-model.bin" ] || bash "$REPO/mac/hamta-modeller.sh" ggml
else
  [ -f "$MODELLER/kb-whisper-medium/model.bin" ] || bash "$REPO/mac/hamta-modeller.sh" faster
fi
if [ -f "$MODELLER/talare/segmentation-3-0.onnx" ] && [ -f "$MODELLER/talare/nemo_en_titanet_small.onnx" ]; then
  echo "finns"
else
  bash "$REPO/mac/hamta-modeller.sh" talare
fi

mkdir -p "$DATA" "$LA"
chmod 700 "$DATA"   # motesinspelningar: bara du kommer at dem
LOGG="$DATA/akasha-meet.log"

echo "== launchd: $ETIKETT"
TJANST="gui/$UIDN/$ETIKETT"
sed -e "s#__REPO__#$REPO#g" -e "s#__LOGG__#$LOGG#g" "$REPO/mac/$ETIKETT.plist" > "$LA/$ETIKETT.plist"
if command -v plutil >/dev/null; then
  plutil -lint "$LA/$ETIKETT.plist" >/dev/null || { echo "FEL: $LA/$ETIKETT.plist ar ogiltig"; exit 1; }
fi
# En tidigare installation stoppas forst. bootout blir klar i bakgrunden, och om bootstrap kors
# innan den gamla tjansten ar borta svarar macOS "Bootstrap failed: 5". Vanta darfor (hogst 15 s).
if launchctl print "$TJANST" >/dev/null 2>&1; then
  launchctl bootout "$TJANST" 2>/dev/null || true
  for _ in $(seq 1 30); do
    launchctl print "$TJANST" >/dev/null 2>&1 || break
    sleep 0.5
  done
fi
# En avstangd tjanst (Systeminstallningar > Inloggningsobjekt) ger ocksa fel 5 vid bootstrap.
launchctl enable "$TJANST" 2>/dev/null || true
if ! launchctl bootstrap "gui/$UIDN" "$LA/$ETIKETT.plist"; then
  if launchctl print "$TJANST" >/dev/null 2>&1; then
    echo "Tjansten var redan inlagd. Startar om den."
    launchctl kickstart -k "$TJANST"
  else
    echo "FEL: launchd startar inte tjansten. Kontrollera Systeminstallningar > Allmant >"
    echo "Inloggningsobjekt att 'bash' ar tillaten i bakgrunden, och kor sedan:"
    echo "  bash mac/avinstallera.sh && bash mac/installera.sh"
    exit 1
  fi
fi

echo "== vantar pa tjansten"
for _ in $(seq 1 30); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/health"; then break; fi
  sleep 1
done
if curl -s "http://127.0.0.1:$PORT/health" | grep -q '"status": *"ok"'; then
  echo "Klart. Akasha Meet: http://127.0.0.1:$PORT  (motor: $AKTIV, inspelningar i $DATA)"
  command -v open >/dev/null && open "http://127.0.0.1:$PORT"
else
  echo "Tjansten svarar inte som den ska. Se loggen: $LOGG"
  curl -s "http://127.0.0.1:$PORT/health" || true
  exit 1
fi
