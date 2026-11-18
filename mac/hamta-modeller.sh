#!/bin/bash
# Hamtar modellerna till MODELLKATALOG (standard: modeller/ i repot) och kontrollerar sha256.
# Revisionerna ar lasta, sa alla far exakt samma vikter. Storleken (medium eller large) styrs av
# MODELL i .env.
#
#   bash mac/hamta-modeller.sh ggml talare    # whisper.cpp + talare (40 MB): Apple Silicon
#   bash mac/hamta-modeller.sh faster talare  # faster-whisper + talare. Samma som utan argument
#   medium: 1,5 GB i bada fallen. large: 1,1 GB for whisper.cpp, 3,1 GB for faster-whisper.
# mac/installera.sh valjer sjalv vilka som behovs.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
MODELLER="${MODELLKATALOG:-$REPO/modeller}"
MODELLER="${MODELLER/#\~/$HOME}"
PY="${PYTHON:-python3.12}"
MODELL="${MODELL:-medium}"
case "$MODELL" in
  medium)
    KB_REV="0abe10b9d7f75d0902656e5c06c5c4d549604dc5"
    CT2_SHA="4a4a32952026bcfa0bcfaa76b0b006f232ffba6a8f5bccbcb12e4a1153a40494"
    GGML_FIL="ggml-model.bin"
    GGML_SHA="1b7842bc1c3f79fb3bf043a0a3590961d625a49ef3ccbdceb00e738c5dd8b015" ;;
  large)
    KB_REV="d5d5984b4d8f7c4847a8ea203f1976285fb28300"
    CT2_SHA="69ed56887f68417f651d50fd5f225c60dfc0f9515bef85bb0f1404825c6f01de"
    GGML_FIL="ggml-model-q5_0.bin"  # kvantiserad (1,1 GB), som KBLab rekommenderar for whisper.cpp
    GGML_SHA="6d2863812d7410322bb7d8647a5c7260761300fa946714c9ed66d22bb30bcb19" ;;
  *) echo "FEL: MODELL=$MODELL, ska vara medium eller large" >&2; exit 2 ;;
esac
KB_REPO="KBLab/kb-whisper-$MODELL"

# hf_hamta REPO REVISION KATALOG FIL...  (tillfallig venv med huggingface_hub)
hf_hamta() {
  local repo="$1" rev="$2" mal="$3"; shift 3
  local tmpv
  tmpv="$(mktemp -d)"
  "$PY" -m venv "$tmpv"
  "$tmpv/bin/pip" install -q "huggingface_hub>=0.24"
  mkdir -p "$mal"
  "$tmpv/bin/python" - "$repo" "$rev" "$mal" "$@" <<'PY'
import sys
from huggingface_hub import hf_hub_download
repo, rev, mal, *filer = sys.argv[1:]
for f in filer:
    print("  hamtar", repo, f, flush=True)
    hf_hub_download(repo_id=repo, filename=f, revision=rev, local_dir=mal)
PY
  rm -rf "$tmpv"
}

# kontrollera FIL SHA256
kontrollera() {
  local faktisk
  faktisk="$(shasum -a 256 "$1" | cut -d' ' -f1)"
  if [ "$faktisk" = "$2" ]; then
    echo "OK: $(basename "$1")"
  else
    echo "FEL: $(basename "$1") har sha256 $faktisk, vantade $2"; exit 1
  fi
}

faster() {
  echo "== KB-Whisper $MODELL for faster-whisper (KBLab, Apache-2.0)"
  hf_hamta "$KB_REPO" "$KB_REV" "$MODELLER/kb-whisper-$MODELL" \
    model.bin config.json preprocessor_config.json tokenizer.json vocabulary.json
  kontrollera "$MODELLER/kb-whisper-$MODELL/model.bin" "$CT2_SHA"
}

ggml() {
  echo "== KB-Whisper $MODELL for whisper.cpp (KBLab, Apache-2.0)"
  hf_hamta "$KB_REPO" "$KB_REV" "$MODELLER/kb-whisper-$MODELL-ggml" "$GGML_FIL"
  kontrollera "$MODELLER/kb-whisper-$MODELL-ggml/$GGML_FIL" "$GGML_SHA"
}

talare() {
  echo "== Talaridentifiering: rostmodellen NeMo TitaNet small (NVIDIA, CC-BY-4.0, 40 MB)"
  hf_hamta csukuangfj/speaker-embedding-models \
    0743f301363dec56491a490f6d6cbc9d67f9a3bf "$MODELLER/talare" nemo_en_titanet_small.onnx
  kontrollera "$MODELLER/talare/nemo_en_titanet_small.onnx" \
    ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e
}

[ $# -gt 0 ] || set -- faster talare
for lage in "$@"; do
  case "$lage" in
    faster|ggml|talare) "$lage" ;;
    *) echo "okant lage: $lage (faster, ggml eller talare)" >&2; exit 2 ;;
  esac
done
