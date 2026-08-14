#!/usr/bin/env bash
# Runs every examples/*/run.sh in order, aggregates their check counts, and
# fails loudly (nonzero exit) if any example failed OR if the grand total
# of checks run across all examples is zero. Usable standalone
# (./examples/run_all.sh) or as a stage of ../run_tests.sh.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TOTAL_CHECKS=0
ANY_FAILED=0
EXAMPLE_COUNT=0

for ex in "$DIR"/*/run.sh; do
  [[ -f "$ex" ]] || continue
  EXAMPLE_COUNT=$((EXAMPLE_COUNT + 1))
  name="$(basename "$(dirname "$ex")")"
  echo
  echo "==================================================================="
  echo "example: $name"
  echo "==================================================================="
  if OUTPUT=$(bash "$ex" 2>&1); then
    echo "$OUTPUT"
    n=$(printf '%s\n' "$OUTPUT" | grep -oE '^[0-9]+ check\(s\) ran' | grep -oE '^[0-9]+' || true)
    n="${n:-0}"
    TOTAL_CHECKS=$((TOTAL_CHECKS + n))
    echo "-> $name: OK ($n check(s))"
  else
    echo "$OUTPUT"
    echo "-> $name: FAILED" >&2
    ANY_FAILED=1
  fi
done

echo
echo "==================================================================="
if [[ "$EXAMPLE_COUNT" -eq 0 ]]; then
  echo "VACUITY: examples/ contains no */run.sh scripts at all" >&2
  exit 1
fi

if [[ "$ANY_FAILED" -ne 0 ]]; then
  echo "examples/: at least one example FAILED -- see output above." >&2
  exit 1
fi

if [[ "$TOTAL_CHECKS" -eq 0 ]]; then
  echo "VACUITY: $EXAMPLE_COUNT example(s) ran but the total check count is zero" >&2
  exit 1
fi

echo "examples/: all $EXAMPLE_COUNT example(s) passed, $TOTAL_CHECKS total check(s)."
