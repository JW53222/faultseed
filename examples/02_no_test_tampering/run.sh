#!/usr/bin/env bash
# no_test_tampering.py -- blocks an Edit/Write that removes a real
# assertion from a test file without a justified `# tampering-ok: <reason>`
# marker. Scoped by filename convention (test_*.py, *_test.py, /tests/,
# conftest.py) -- see .claude/hooks/_common.py's is_test_file().
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

section "no_test_tampering.py -- an assertion is deleted with no marker"
BLOCK_EVENT=$(jq -n --arg path "$FIXTURE/tests/test_thing.py" \
  '{tool_name: "Edit", tool_input: {file_path: $path, old_string: "    assert a == 1", new_string: "    pass"}}')
expect_block "$HOOKS_DIR/no_test_tampering.py" "$BLOCK_EVENT" \
  "'assert a == 1' replaced by a bare 'pass', no marker -- an assertion just silently disappeared"

section "no_test_tampering.py -- the near-miss: same removal, with a justified marker"
ALLOW_EVENT=$(jq -n --arg path "$FIXTURE/tests/test_thing.py" \
  '{tool_name: "Edit", tool_input: {file_path: $path, old_string: "    assert a == 1", new_string: "    foo()  # tampering-ok: justified by the corresponding code change"}}')
expect_allow "$HOOKS_DIR/no_test_tampering.py" "$ALLOW_EVENT" \
  "same removal, but carries a non-empty '# tampering-ok: <reason>' -- a BARE marker with no reason would NOT clear this (try it: drop the ': justified...' text and re-run)"

finish
