#!/bin/bash
# Hamtar modellerna till MODELLKATALOG (standard: modeller/ i repot) och kontrollerar sha256.
# Revisionerna ar lasta, sa alla far exakt samma vikter.
#
#   bash mac/hamta-modeller.sh          # KB-Whisper (faster-whisper, 1,5 GB) + talare (46 MB)
#   bash mac/hamta-modeller.sh ggml     # KB-Whisper for whisper.cpp (1,5 GB), for MOTOR=whispercpp
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
MODELLER="${MODELLKATALOG:-$REPO/modeller}"
MODELLER="${MODELLER/#\~/$HOME}"
PY="${PYTHON:-python3.12}"
KB_REPO="KBLab/kb-whisper-medium"
KB_REV="0abe10b9d7f75d0902656e5c06c5c4d549604dc5"

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

case "${1:-standard}" in
  standard)
    echo "== KB-Whisper medium (KBLab, Apache-2.0)"
    hf_hamta "$KB_REPO" "$KB_REV" "$MODELLER/kb-whisper-medium" \
      model.bin config.json preprocessor_config.json tokenizer.json vocabulary.json
    kontrollera "$MODELLER/kb-whisper-medium/model.bin" \
      4a4a32952026bcfa0bcfaa76b0b006f232ffba6a8f5bccbcb12e4a1153a40494
    echo "== Talaridentifiering: pyannote segmentation-3.0 (MIT) och NeMo TitaNet small (CC-BY-4.0)"
    hf_hamta csukuangfj/sherpa-onnx-pyannote-segmentation-3-0 \
      9403a6902bb58e3d5ae8c7e77c3422de279db2e0 "$MODELLER/talare" model.onnx LICENSE
    mv "$MODELLER/talare/model.onnx" "$MODELLER/talare/segmentation-3-0.onnx"
    hf_hamta csukuangfj/speaker-embedding-models \
      0743f301363dec56491a490f6d6cbc9d67f9a3bf "$MODELLER/talare" nemo_en_titanet_small.onnx
    kontrollera "$MODELLER/talare/segmentation-3-0.onnx" \
      220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079
    kontrollera "$MODELLER/talare/nemo_en_titanet_small.onnx" \
      ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e
    ;;
  ggml)
    echo "== KB-Whisper medium, GGML for whisper.cpp"
    hf_hamta "$KB_REPO" "$KB_REV" "$MODELLER/kb-whisper-medium-ggml" ggml-model.bin
    kontrollera "$MODELLER/kb-whisper-medium-ggml/ggml-model.bin" \
      1b7842bc1c3f79fb3bf043a0a3590961d625a49ef3ccbdceb00e738c5dd8b015
    ;;
  *) echo "okant lage: $1 (inget argument eller ggml)" >&2; exit 2 ;;
esac
