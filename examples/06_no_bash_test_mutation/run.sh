#!/usr/bin/env bash
# no_bash_test_mutation.py -- blocks a Bash in-place edit (sed -i, awk -i,
# tee, dd of=, > / >>) targeting a test file that ALREADY EXISTS on disk.
# Unlike the deletion hook, this one DOES check existence (relative to the
# event's top-level "cwd" field) -- creating a brand-new test file via
# redirect is allowed, only mutating an existing one is blocked.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT
mkdir -p "$FIXTURE/tests"
echo "def test_x(): assert True" > "$FIXTURE/tests/test_foo.py"
echo "scratch" > "$FIXTURE/notes.txt"

section "no_bash_test_mutation.py -- 'sed -i' on an EXISTING test file, no marker"
BLOCK_EVENT=$(jq -n --arg cwd "$FIXTURE" \
  '{tool_input: {command: "sed -i 's/x/y/' tests/test_foo.py"}, cwd: $cwd}')
expect_block "$HOOKS_DIR/no_bash_test_mutation.py" "$BLOCK_EVENT" \
  "in-place edit of tests/test_foo.py, which exists on disk relative to cwd -- bypasses no_test_tampering.py's Edit-side view"

section "no_bash_test_mutation.py -- the near-miss: same command, a non-test file"
ALLOW_EVENT=$(jq -n --arg cwd "$FIXTURE" \
  '{tool_input: {command: "sed -i 's/x/y/' notes.txt # test-mutate-ok"}, cwd: $cwd}')
expect_allow "$HOOKS_DIR/no_bash_test_mutation.py" "$ALLOW_EVENT" \
  "notes.txt isn't a test file -- nothing to block, the bare marker here is irrelevant either way"

finish
