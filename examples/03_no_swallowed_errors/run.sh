#!/usr/bin/env bash
# no_swallowed_errors.py -- blocks a Write/Edit that introduces a bare
# `except ...: pass` (or `...`) with no `# swallow-ok: <reason>` marker.
# ENGINE-QUALITY hook: only fires inside the directories listed in
# engine_dirs. Runs against the demo engine_dirs config ../lib/common.sh
# builds (engine_dirs: ["src"]), standing in for an already-configured
# repo -- not this repo's own shipped docs/audit/audit-scope.yaml, which
# ships unconfigured on purpose (see example 10 and
# .claude/hooks/test_engine_dirs_sentinel.py). See example 10 for what
# happens to the exact same violation OUTSIDE that scope.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

VIOLATING_CONTENT=$'def foo():\n    try:\n        risky()\n    except Exception:\n        pass\n'
FIXED_CONTENT=$'def foo():\n    try:\n        risky()\n    except Exception:\n        pass  # swallow-ok: intentional degrade\n'

section "no_swallowed_errors.py -- a bare 'except: pass' inside $ENGINE_IN_SCOPE_DIR/ (in engine_dirs)"
BLOCK_EVENT=$(jq -n --arg content "$VIOLATING_CONTENT" \
  '{tool_name: "Write", tool_input: {file_path: "'"$ENGINE_IN_SCOPE_DIR"'/foo.py", content: $content}}')
expect_block "$HOOKS_DIR/no_swallowed_errors.py" "$BLOCK_EVENT" \
  "except Exception: pass, no marker, path is under '$ENGINE_IN_SCOPE_DIR/' which IS in engine_dirs" \
  CLAUDE_PROJECT_DIR="$FIXTURE"

section "no_swallowed_errors.py -- the near-miss: same file, marked as a deliberate degrade"
ALLOW_EVENT=$(jq -n --arg content "$FIXED_CONTENT" \
  '{tool_name: "Write", tool_input: {file_path: "'"$ENGINE_IN_SCOPE_DIR"'/foo.py", content: $content}}')
expect_allow "$HOOKS_DIR/no_swallowed_errors.py" "$ALLOW_EVENT" \
  "identical except-block, but 'pass  # swallow-ok: intentional degrade' on the body line" \
  CLAUDE_PROJECT_DIR="$FIXTURE"

finish
