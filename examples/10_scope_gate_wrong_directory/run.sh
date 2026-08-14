#!/usr/bin/env bash
# THIS IS NOT A GUARD. It demonstrates the sharpest install footgun in this
# pack: no_swallowed_errors.py and no_type_checking_stub.py are
# ENGINE-QUALITY hooks -- they only run inside the directories listed in
# docs/audit/audit-scope.yaml's `engine_dirs`. That scope check is silent
# when it excludes you: a file outside engine_dirs produces exit 0, and
# exit 0 is indistinguishable from "the guard looked and found nothing
# wrong." A missing/malformed audit-scope.yaml blocks loudly (exit 2,
# every edit); a WRONG list in it just goes quiet forever.
#
# Same violating content, run twice: once under the currently-configured
# in-scope directory (blocked, exactly like example 03), once under a
# directory that is guaranteed not to be in engine_dirs (allowed -- not
# because the code is fine, but because nothing looked).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

VIOLATING_CONTENT=$'def foo():\n    try:\n        risky()\n    except Exception:\n        pass\n'

echo "Currently configured engine_dirs (docs/audit/audit-scope.yaml): includes '$ENGINE_IN_SCOPE_DIR'"
echo "Directory used for the out-of-scope half below: '$ENGINE_OUT_OF_SCOPE_DIR' (confirmed NOT in engine_dirs)"

section "in scope: $ENGINE_IN_SCOPE_DIR/foo.py, same swallow bug as example 03"
BLOCK_EVENT=$(jq -n --arg content "$VIOLATING_CONTENT" \
  '{tool_name: "Write", tool_input: {file_path: "'"$ENGINE_IN_SCOPE_DIR"'/foo.py", content: $content}}')
expect_block "$HOOKS_DIR/no_swallowed_errors.py" "$BLOCK_EVENT" \
  "identical bug, path is inside engine_dirs -- caught" \
  CLAUDE_PROJECT_DIR="$FIXTURE"

section "SAME bug, WRONG directory: $ENGINE_OUT_OF_SCOPE_DIR/foo.py"
SILENT_EVENT=$(jq -n --arg content "$VIOLATING_CONTENT" \
  '{tool_name: "Write", tool_input: {file_path: "'"$ENGINE_OUT_OF_SCOPE_DIR"'/foo.py", content: $content}}')
expect_allow "$HOOKS_DIR/no_swallowed_errors.py" "$SILENT_EVENT" \
  "THIS IS THE FOOTGUN, NOT A PASS: exit 0 here means the hook never looked, not that the code is clean. If your real source lives under a directory not listed in engine_dirs, no_swallowed_errors.py and no_type_checking_stub.py are dead weight there -- installed, firing, checking nothing -- and nothing will tell you. Edit engine_dirs to match your actual layout and re-run this example." \
  CLAUDE_PROJECT_DIR="$FIXTURE"

finish
