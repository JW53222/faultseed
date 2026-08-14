#!/usr/bin/env bash
# no_type_checking_stub.py -- blocks a Write/Edit that declares a
# method/function ONLY inside `if TYPE_CHECKING:`, with no matching
# runtime def. It type-checks clean and then AttributeErrors (or silently
# takes the wrong branch) the moment something actually calls it. Also
# ENGINE-QUALITY-scoped, same as no_swallowed_errors.py.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

VIOLATING_CONTENT=$'from typing import TYPE_CHECKING\nclass Foo:\n    if TYPE_CHECKING:\n        def bar(self) -> int: ...\n'
FIXED_CONTENT=$'from typing import TYPE_CHECKING\nclass Foo:\n    if TYPE_CHECKING:\n        # host-provides: Host defines this at runtime\n        def bar(self) -> int: ...\n'

section "no_type_checking_stub.py -- 'bar' is defined ONLY under TYPE_CHECKING"
BLOCK_EVENT=$(jq -n --arg content "$VIOLATING_CONTENT" \
  '{tool_name: "Write", tool_input: {file_path: "'"$ENGINE_IN_SCOPE_DIR"'/foo.py", content: $content}}')
expect_block "$HOOKS_DIR/no_type_checking_stub.py" "$BLOCK_EVENT" \
  "class Foo.bar exists only inside 'if TYPE_CHECKING:', no runtime def, no marker" \
  CLAUDE_PROJECT_DIR="$FIXTURE"

section "no_type_checking_stub.py -- the near-miss: a real host-contract marker"
ALLOW_EVENT=$(jq -n --arg content "$FIXED_CONTENT" \
  '{tool_name: "Write", tool_input: {file_path: "'"$ENGINE_IN_SCOPE_DIR"'/foo.py", content: $content}}')
expect_allow "$HOOKS_DIR/no_type_checking_stub.py" "$ALLOW_EVENT" \
  "same stub, but '# host-provides: Host defines this at runtime' documents which host class actually supplies it" \
  CLAUDE_PROJECT_DIR="$FIXTURE"

finish
