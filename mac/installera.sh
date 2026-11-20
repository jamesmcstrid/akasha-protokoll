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

# launchd startar tjansten med bash, och macOS later inte en bakgrundstjanst lasa i Skrivbord,
# Dokument, Hamtade filer (Apple) eller i iCloud Drive, molnmappar och /Volumes (antaget).
# Darfor stannar vi har, innan nagot ar installerat eller hamtat.
# plattform.py anvander bara standardbiblioteket, sa den gar att kora med systemets python3.12
# innan venv finns. -B: skriv ingen __pycache__ i repot innan kontrollen ar gjord.
VERKLIG="$(cd "$REPO" && pwd -P)"
SKYDDAD="$("$PY" -B -c 'import sys; sys.path.insert(0, sys.argv[1]); import plattform; print(plattform.skyddad_plats(sys.argv[2]) or "")' "$REPO/app" "$VERKLIG")"
if [ -n "$SKYDDAD" ]; then
  # forsta lediga namn: akasha-meet, akasha-meet-ny, akasha-meet-ny2, ...
  MAL="$HOME/akasha-meet"; N=1
  while [ -e "$MAL" ]; do
    if [ "$N" -eq 1 ]; then MAL="$HOME/akasha-meet-ny"; else MAL="$HOME/akasha-meet-ny$N"; fi
    N=$((N + 1))
  done
  RUBRIK="Gor sa har:"
  FINNS=""
  if [ -f "$HOME/akasha-meet/mac/installera.sh" ]; then
    PULL=""; [ -d "$HOME/akasha-meet/.git" ] && PULL=" && git pull"
    FINNS="Det finns redan en Akasha Meet-mapp i $HOME/akasha-meet. Kor installationen darifran i stallet:
  cd \"$HOME/akasha-meet\"$PULL && bash mac/installera.sh

"
    RUBRIK="Eller flytta den har mappen:"
  fi
  cat <<TEXT
FEL: Akasha Meet ligger i $VERKLIG.
macOS later inte bakgrundstjanster lasa i den mappen ($SKYDDAD), sa tjansten skulle inte
kunna starta harifran. Inget har installerats eller hamtats an.

${FINNS}$RUBRIK
  1. Flytta mappen till din hemkatalog (mappen med huset i Finder). I Terminal:
       mv "$VERKLIG" "$MAL"
  2. Har du kort installationen i den gamla mappen tidigare, ta bort mappen venv i den
     flyttade mappen. Den fungerar inte efter en flytt och skapas igen:
       rm -rf "$MAL/venv"
     Modellerna i modeller/ och installningarna i .env foljer med och hamtas inte igen.
  3. Kor installationen fran den nya platsen:
       cd "$MAL" && bash mac/installera.sh
Inspelningarna i ~/AkashaMeet paverkas inte.
TEXT
  exit 1
fi

[ -f "$REPO/.env" ] || { cp "$REPO/.env.example" "$REPO/.env"; echo "== skapade .env (standardinstallningar)"; }
set -a; . "$REPO/.env"; set +a
MOTOR="${MOTOR:-auto}"
PORT="${PORT:-8611}"
DATA="${DATAKATALOG:-$HOME/AkashaMeet}"; DATA="${DATA/#\~/$HOME}"

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

echo "== modeller (motor: $AKTIV, KB-Whisper ${MODELL:-medium})"
if [ "$AKTIV" = "whispercpp" ]; then LAGE=ggml; else LAGE=faster; fi
"$REPO/venv/bin/python" "$REPO/app/modeller.py" "$LAGE" talare

mkdir -p "$DATA" "$LA"
chmod 700 "$DATA"   # motesinspelningar: bara du kommer at dem
LOGG="$DATA/akasha-meet.log"

TJANST="gui/$UIDN/$ETIKETT"
# Ar programmet (Akasha Meet.app) igang pa porten utan att launchd-tjansten finns ska vi inte lagga
# in den: annars kraschar tjansten om och om igen pa den upptagna porten, medan vantan nedan far
# svar fran programmet och sager "Klart".
if ! launchctl print "$TJANST" >/dev/null 2>&1 && curl -s -o /dev/null "http://127.0.0.1:$PORT/health"; then
  echo "FEL: Akasha Meet (programmet) ar igang pa port $PORT. Avsluta det forst (Akasha Meet > Avsluta Akasha Meet) och kor skriptet igen."; exit 1
fi

# Loggen fylls pa av launchd over tid. Vi minns hur lang den ar nu, sa att vi i slutet bara
# visar det den har starten skrev och inte gamla rader fran en tidigare misslyckad installation.
FORE=0
if [ -f "$LOGG" ]; then FORE="$(wc -l < "$LOGG" | tr -d ' ')" || FORE=0; fi
case "$FORE" in ''|*[!0-9]*) FORE=0 ;; esac

echo "== launchd: $ETIKETT"
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
  # || true: inget har far avbryta skriptet (set -e) innan forklaringen ar skriven
  NYA="$(tail -n +$((FORE + 1)) "$LOGG" 2>/dev/null || true)"
  echo "Tjansten svarar inte som den ska. Det sista den skrev i loggen ($LOGG):"
  echo "-----"
  if [ -n "$NYA" ]; then printf '%s\n' "$NYA" | tail -n 15 || true; else echo "(tjansten skrev inget i loggen)"; fi
  echo "-----"
  launchctl print "$TJANST" 2>/dev/null | grep -E "^[[:space:]]*(state|last exit code) =" || true
  case "$NYA" in
    *"Operation not permitted"*)
      echo "\"Operation not permitted\" betyder att macOS inte later tjansten lasa mappen $REPO."
      echo "Flytta mappen till din hemkatalog, ta bort venv i den och kor installationen igen"
      echo "(se README, Felsokning). Modellerna foljer med."
      ;;
    *)
      echo "Skicka raderna ovan till den som hjalper dig. Loggen innehaller inga inspelningar eller texter."
      ;;
  esac
  exit 1
fi
