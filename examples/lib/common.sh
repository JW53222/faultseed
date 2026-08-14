# Shared helpers for faultseed examples. Sourced by each example's run.sh
# -- not meant to be run directly (it has no shebang and does nothing on
# its own).
#
# Every example follows the same shape: build the exact JSON a Claude Code
# hook receives on stdin, run the real (unmodified) hook script against it,
# and check the observed exit code against what the fact sheet says it
# should be. Exit 2 = blocked. Any other exit code = allowed. That is the
# whole Claude Code hook protocol -- see .claude/hooks/_common.py's block()
# docstring.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.claude/hooks"
PY="${PYTHON:-python3}"

CHECKS_RUN=0

section() {
  echo
  echo "--- $* ---"
}

# Which top-level directory is currently "in scope" for the engine-quality
# guards (no_swallowed_errors.py / no_type_checking_stub.py), and a
# directory guaranteed NOT to be, read live from docs/audit/audit-scope.yaml
# rather than hardcoded -- that file is real repo configuration another
# session can edit, and a hardcoded "src" here would silently go stale if
# it does. See example 10 for why this distinction is the whole point.
read -r ENGINE_IN_SCOPE_DIR ENGINE_OUT_OF_SCOPE_DIR < <("$PY" - "$REPO_ROOT/docs/audit/audit-scope.yaml" <<'PYEOF'
import sys
import yaml

data = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
engine_dirs = set(data.get("engine_dirs") or [])
in_scope = sorted(engine_dirs)[0] if engine_dirs else "src"
for candidate in ("docs", "notes", "scratch", "outside_scope_demo"):
    if candidate not in engine_dirs:
        out_scope = candidate
        break
else:
    out_scope = "outside_scope_demo_zzz"
print(in_scope, out_scope)
PYEOF
)

# run_hook HOOK_PATH JSON_STDIN [ENV_ASSIGN...]
# Runs the real hook with JSON on stdin exactly as Claude Code's hook
# protocol delivers it. Sets HOOK_RC (exit code) and HOOK_STDERR (stderr
# only -- stdout is discarded, since none of these hooks use it).
run_hook() {
  local hook="$1" json="$2"
  shift 2
  # Every example's run.sh runs under `set -e`. A bare `VAR=$(cmd)`
  # assignment is NOT exempt from -e when cmd fails (only commands guarded
  # by if/while/&&/|| are) -- so without the set +e/-e bracket here, the
  # FIRST blocked hook (exit 2) would abort the whole example script before
  # HOOK_RC is even captured, and every expect_block call would silently
  # never run.
  set +e
  if [[ "$hook" == *.py ]]; then
    HOOK_STDERR=$(printf '%s' "$json" | env "$@" "$PY" "$hook" 2>&1 >/dev/null)
  else
    HOOK_STDERR=$(printf '%s' "$json" | env "$@" bash "$hook" 2>&1 >/dev/null)
  fi
  HOOK_RC=$?
  set -e
}

# expect_block HOOK_PATH JSON_STDIN DESCRIPTION [ENV_ASSIGN...]
# Asserts the hook blocks (exit 2). Exits this script loudly on mismatch --
# a guard that fails to block the violation it exists for is the exact
# defect this whole repo is about, so this is not something to soften into
# a warning.
expect_block() {
  local hook="$1" json="$2" desc="$3"
  shift 3
  run_hook "$hook" "$json" "$@"
  CHECKS_RUN=$((CHECKS_RUN + 1))
  if [[ "$HOOK_RC" -eq 2 ]]; then
    echo "BLOCKED (exit 2) -- $desc"
    echo "  guard said: $(printf '%s' "$HOOK_STDERR" | head -1)"
  else
    echo "FAIL -- expected exit 2 (block) for: $desc" >&2
    echo "  observed exit $HOOK_RC" >&2
    echo "  stderr: $HOOK_STDERR" >&2
    exit 1
  fi
}

# expect_allow HOOK_PATH JSON_STDIN DESCRIPTION [ENV_ASSIGN...]
# Asserts the hook allows (exit 0) -- the near-miss / legitimate case, so
# the reader sees the guard discriminate rather than just refuse everything.
expect_allow() {
  local hook="$1" json="$2" desc="$3"
  shift 3
  run_hook "$hook" "$json" "$@"
  CHECKS_RUN=$((CHECKS_RUN + 1))
  if [[ "$HOOK_RC" -eq 0 ]]; then
    echo "ALLOWED (exit 0) -- $desc"
  else
    echo "FAIL -- expected exit 0 (allow) for: $desc" >&2
    echo "  observed exit $HOOK_RC" >&2
    echo "  stderr: $HOOK_STDERR" >&2
    exit 1
  fi
}

# finish -- call this at the end of every example's run.sh. Enforces the
# same vacuity rule run_tests.sh enforces on the test suites: an example
# that ran zero checks is a FAILURE, not a quiet pass, because a script
# that prints reassuring text without ever calling expect_block/expect_allow
# is exactly the "looks installed, proves nothing" failure mode this repo
# exists to catch.
finish() {
  if [[ "$CHECKS_RUN" -eq 0 ]]; then
    echo "VACUITY: this example ran zero checks" >&2
    exit 1
  fi
  echo
  echo "$CHECKS_RUN check(s) ran in this example."
}
