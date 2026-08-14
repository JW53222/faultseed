#!/usr/bin/env bash
# no_bash_test_deletion.py -- blocks a Bash `rm`/`git rm`/`git mv` that
# deletes or moves a test file out of the suite. Pure pattern match on the
# command's target path (test_*.py, *_test.py, a /tests/ segment, ...) --
# it does not need the target file to actually exist on disk.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT
mkdir -p "$FIXTURE/tests"
: > "$FIXTURE/tests/test_foo.py"
: > "$FIXTURE/scratch.txt"

section "no_bash_test_deletion.py -- 'rm tests/test_foo.py', no marker"
BLOCK_EVENT=$(jq -n --arg cwd "$FIXTURE" \
  '{tool_input: {command: "rm tests/test_foo.py"}, cwd: $cwd}')
expect_block "$HOOKS_DIR/no_bash_test_deletion.py" "$BLOCK_EVENT" \
  "an agent shelling out to rm a test file bypasses the Edit-side tamper guard entirely"

section "no_bash_test_deletion.py -- the near-miss: deleting a NON-test file"
ALLOW_EVENT=$(jq -n --arg cwd "$FIXTURE" \
  '{tool_input: {command: "rm scratch.txt # delete-tests-ok"}, cwd: $cwd}')
expect_allow "$HOOKS_DIR/no_bash_test_deletion.py" "$ALLOW_EVENT" \
  "scratch.txt isn't a test path at all -- the marker on this line is a no-op, there was nothing to block"

finish
