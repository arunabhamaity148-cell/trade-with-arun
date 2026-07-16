#!/usr/bin/env bash
# Build a distributable ZIP containing the entire project.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="trade_with_arun"
OUT="$ROOT/${NAME}.zip"
rm -f "$OUT"
# exclude transient artifacts
EXCLUDES=( ".git" ".venv" "*.pyc" "__pycache__" "*.egg-info" ".pytest_cache" )
ARGS=()
for pat in "${EXCLUDES[@]}"; do ARGS+=( -x "$pat" ); done
( cd "$ROOT/.." && zip -r "$OUT" "$NAME" "${ARGS[@]}" )
echo "Built $OUT"
