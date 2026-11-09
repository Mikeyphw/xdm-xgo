#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 -B -m unittest discover -s tests/media-parity -p 'test_*.py' -v
python3 -B tests/media-parity/reference_oracle.py
python3 -B tests/media-parity/acceptance.py --out "${RUNNER_TEMP:-/tmp}/mp00-acceptance.json"
echo 'MP00_BASELINE_PASS (does not imply 140/140 parity)'
