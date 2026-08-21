#!/bin/bash
# Thin wrapper. Prefer: python3 scripts/bake_enterprise.py --payload … --out …
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)
PAYLOAD=${1:-"$ROOT/dist/switchbay-enterprise-darwin-arm64"}
OUT=${2:-"$ROOT/dist/bake"}
exec python3 "$ROOT/scripts/bake_enterprise.py" --payload "$PAYLOAD" --out "$OUT"
