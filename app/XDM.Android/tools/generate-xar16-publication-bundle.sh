#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${XDM_XAR16_RUN_ID:?XDM_XAR16_RUN_ID required}"
EVIDENCE_DIR="${XDM_XAR16_EVIDENCE_DIR:-build/xar16/evidence/$RUN_ID}"
OUT_DIR="build/release/publication/xar16-$RUN_ID"
mkdir -p "$OUT_DIR"
python3 tools/verify-xar16-release-evidence.py --evidence-dir "$EVIDENCE_DIR" --require-publication-ready --out "$OUT_DIR/release-metadata.json"
cp "$EVIDENCE_DIR"/phase10-release-attestation.json "$OUT_DIR/"
cp "$EVIDENCE_DIR"/xar16-same-run-artifacts.json "$OUT_DIR/"
cp "$EVIDENCE_DIR"/xar16-device-matrix.json "$OUT_DIR/"
cp "$EVIDENCE_DIR"/xar16-signed-release-journeys.json "$OUT_DIR/"
cp "$EVIDENCE_DIR"/rm04-validation-seal.json "$OUT_DIR/"
# MP12 P04: hash exactly six sealed evidence files, never checksum outputs.
python3 -B ../../scripts/mp12_p04_signed_release.py checksum-write --publication-dir "$OUT_DIR"
echo "$OUT_DIR"
