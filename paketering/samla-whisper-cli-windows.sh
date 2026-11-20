#!/bin/bash
# Samlar whisper-cli for programmet: kopierar det kompilerade (bygg-whisper-cli-windows.sh eller cachen), kopierar in
# C-runtime-DLL:erna som filerna importerar, skriver fillistan och kontrollerar processorvarianter och beroenden.
#   PYTHON=build/venv/Scripts/python bash paketering/samla-whisper-cli-windows.sh KOMPILERAT UT
#   (till exempel build/whisper/kompilerat build/whisper/ut)
# Kors efter varje bygge och varje cachetraff: det som cachas ar bara det kompilerade, sa att en rattning har inte
# tvingar fram ett nytt bygge av whisper.cpp. Stannar vid forsta felet (det ar ett kort steg).
set -euo pipefail
trap 'echo "FEL: samla-whisper-cli-windows.sh stannade pa rad $LINENO: $BASH_COMMAND" >&2' ERR

KOMPILERAT="${1:?ange katalogen med det kompilerade}"
UT="${2:?ange en utkatalog}"
PYTHON="${PYTHON:-python}"
# Alla sokvagar nedan ar relativa till repots rot: en sokvag i MSYS-form (/d/a/...) fran pwd eller $0 forstar inte ett
# Windows-program (python, cmake, git), och MSYS_NO_PATHCONV=1 hindrar omskrivningen. Anroparen kor fran repots rot.
cd "$(dirname "$0")/.."
VERKTYG="paketering/bygg_windows_verktyg.py"

[ -f "$KOMPILERAT/whisper-cli.exe" ] || { echo "FEL: $KOMPILERAT/whisper-cli.exe saknas (bygget eller cachen gav inget kompilerat)" >&2; ls -l "$KOMPILERAT" >&2 || true; exit 1; }
rm -rf "$UT"
mkdir -p "$UT"
cp "$KOMPILERAT"/* "$UT/"

echo "== C-runtime-DLL:er (vcruntime140, msvcp140, vcomp140 ...): kopieras in bredvid programmet"
"$PYTHON" "$VERKTYG" runtime "$UT"

echo "== Filerna i $UT"
"$PYTHON" "$VERKTYG" lista "$UT"

echo "== Processorvarianter (ggml-cpu-*.dll)"
VARIANTER="$(find "$UT" -name 'ggml-cpu-*.dll' | sort)"
if [ -z "$VARIANTER" ]; then
  echo "FEL: ingen ggml-cpu-<variant>.dll i $UT: whisper-cli skulle sakna processorstod" >&2
  exit 1
fi
echo "$VARIANTER" | sed 's|.*/||'
echo "OK: $(echo "$VARIANTER" | grep -c .) processorvarianter"
[ -f "$UT/whisper.dll" ] && [ -f "$UT/ggml.dll" ] && [ -f "$UT/ggml-base.dll" ] || {
  echo "FEL: whisper.dll, ggml.dll eller ggml-base.dll saknas i $UT" >&2
  exit 1
}
echo "OK: whisper-cli.exe, whisper.dll, ggml.dll och ggml-base.dll finns"

echo "== Beroenden (alla importer ska hittas i samma katalog eller bland Windows egna DLL-filer)"
"$PYTHON" "paketering/kontrollera_pe.py" "$UT" --system-katalog "${SYSTEMROOT:-C:\\Windows}\\System32"
echo "== Klar"
