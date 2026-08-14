#!/bin/sh
# smoke-test.sh -- sanity-check the faultseed <-> dsh wiring WITHOUT dsh
# itself. This does NOT prove the dsh bridge dispatches correctly (that
# needs a running `dsh` agent -- see adapters/dsh/README.md's honesty tier).
# It proves the one thing this adapter's own files cannot get wrong silently:
# that _dispatch.py, found via HOOKS_HARNESS_ROOT exactly the way this
# package's cordis.patch.yml configures ${CLAUDE_PLUGIN_ROOT}, still resolves
# and runs a real guardrail hook, and that hook's exit code is still 2 on a
# deny and 0 on an allow -- the exact mapping
# packages/hooks/hook-protocol/src/codec.ts:63-70 (BLOCKING_EXIT_CODE = 2)
# depends on. HOOKS_HARNESS_ROOT is this adapter's own generic env var name
# (deliberately not a faultseed substitution -- see cordis.patch.yml's own
# comment for why), matching the one cordis.patch.yml reads.
#
# Usage: run with no argument or env var at all from inside this checkout --
# it defaults to its own repo root, derived from this script's own location
# (bin/ -> dsh/ -> adapters/ -> checkout root), not a hardcoded path:
#
#   sh bin/smoke-test.sh   # doc-ref-ok: usage line, path is relative to the adapter package root
#
# Set HOOKS_HARNESS_ROOT explicitly only to point at a DIFFERENT faultseed
# checkout than the one this script ships inside:
#
#   HOOKS_HARNESS_ROOT=/absolute/path/to/faultseed sh bin/smoke-test.sh   # doc-ref-ok: usage line, path is relative to the adapter package root
#
# Exits 0 if both checks pass, 1 otherwise.

set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
DEFAULT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
HOOKS_HARNESS_ROOT="${HOOKS_HARNESS_ROOT:-$DEFAULT_ROOT}"

DISPATCH="$HOOKS_HARNESS_ROOT/.claude/hooks/_dispatch.py"
if [ ! -f "$DISPATCH" ]; then
  echo "smoke-test.sh: $DISPATCH not found -- is HOOKS_HARNESS_ROOT correct?" >&2
  exit 1
fi

fail=0

echo "--- deny case: git rm of a test file, via no_bash_test_deletion.py ---"
set +e
out=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"git rm tests/test_foo.py"}}' \
  | CLAUDE_PROJECT_DIR="$HOOKS_HARNESS_ROOT" python3 "$DISPATCH" no_bash_test_deletion.py 2>&1)
code=$?
set -e
echo "$out"
echo "exit code: $code"
if [ "$code" -eq 2 ]; then
  echo "PASS: exit 2, which packages/hooks/hook-protocol/src/codec.ts maps to decision:'block'"
else
  echo "FAIL: expected exit 2, got $code"
  fail=1
fi

echo
echo "--- allow case: an ordinary command, same hook ---"
set +e
out=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' \
  | CLAUDE_PROJECT_DIR="$HOOKS_HARNESS_ROOT" python3 "$DISPATCH" no_bash_test_deletion.py 2>&1)
code=$?
set -e
echo "$out"
echo "exit code: $code"
if [ "$code" -eq 0 ]; then
  echo "PASS: exit 0, which codec.ts leaves undecided (no block)"
else
  echo "FAIL: expected exit 0, got $code"
  fail=1
fi

exit "$fail"
