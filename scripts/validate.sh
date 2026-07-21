#!/usr/bin/env bash
set -euo pipefail

python3 -m pytest research/tests -q

python3 - <<'PY'
from hashlib import sha256
from pathlib import Path

source = Path("intraday_decision_map_v11_aggressive_clean.pine")
expected = "77c6fb4014f3ba93d741bbe445438db0664609326145c82fafe9403b8b80cd03"
actual = sha256(source.read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit(f"frozen Pine SHA mismatch: {actual} != {expected}")
print(f"frozen Pine SHA verified: {actual}")
PY
