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
PY="${PYTHON:-python3}"

CHECKS_RUN=0

section() {
  echo
  echo "--- $* ---"
}

# --- Synthetic hooks tree ---------------------------------------------
# $HOOKS_DIR does NOT point at this repo's real, installed .claude/hooks/.
# It points at a throwaway COPY, built fresh below, so every example runs
# against a KNOWN, fixed engine_dirs value instead of whatever this repo's
# own docs/audit/audit-scope.yaml happens to ship right now.
#
# Why this is necessary, not just tidy: that shipped file's `engine_dirs`
# is UNCONFIGURED_ENGINE_DIRS_SENTINEL by design (see its own header
# comment and _common.py's UNCONFIGURED_ENGINE_DIRS_SENTINEL) -- a fresh
# install BLOCKS every edit until a real value replaces it. `_AUDIT_SCOPE_ROOT`
# (_common.py) resolves relative to wherever the hook .py FILE physically
# lives on disk, not CLAUDE_PROJECT_DIR, so no per-example CLAUDE_PROJECT_DIR
# override can point a REAL, in-place hook at a different config -- the
# only way to give these examples a working, demonstrable engine_dirs is to
# run a COPY of the hooks from somewhere that carries its own config. Same
# technique .claude/hooks/test_engine_dirs_sentinel.py and
# test_no_swallowed_errors.py's `_copied_hook` use for the identical reason.
#
# ALL 11 examples share this one copy (not just the two engine-quality
# ones) so that examples which don't care about engine_dirs at all still
# run the exact same, unmodified guard code as a real install -- only the
# copy's docs/audit/audit-scope.yaml differs from this repo's real one.
# Every file below is the actual guard/library file this repo ships;
# nothing here is rewritten or mocked.
SYNTH_HOOKS_ROOT="${TMPDIR:-/tmp}/faultseed-examples-synth-hooks"
rm -rf "$SYNTH_HOOKS_ROOT"
mkdir -p "$SYNTH_HOOKS_ROOT/.claude/hooks" "$SYNTH_HOOKS_ROOT/docs/audit"
for _hook_file in _common.py agent_sizing_gate.py no_bash_test_deletion.py \
    no_bash_test_mutation.py no_swallowed_errors.py no_test_tampering.py \
    no_type_checking_stub.py protect-files.sh subagent_closing_report.py \
    workflow_agent_sizing_gate.py; do
  cp "$REPO_ROOT/.claude/hooks/$_hook_file" "$SYNTH_HOOKS_ROOT/.claude/hooks/$_hook_file"
done
unset _hook_file
cat > "$SYNTH_HOOKS_ROOT/docs/audit/audit-scope.yaml" <<'YAML'
engine_dirs:
  - "src"
YAML
HOOKS_DIR="$SYNTH_HOOKS_ROOT/.claude/hooks"

# Which top-level directory is "in scope" for the engine-quality guards
# (no_swallowed_errors.py / no_type_checking_stub.py) under the synthetic
# config just written above, and a directory guaranteed NOT to be. Fixed
# values, not read live from any file, because we just wrote that file
# ourselves a few lines up -- see example 10 for why this in-scope/
# out-of-scope distinction is the whole point.
ENGINE_IN_SCOPE_DIR="src"
ENGINE_OUT_OF_SCOPE_DIR="docs"

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
