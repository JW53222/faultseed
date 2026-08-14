#!/usr/bin/env bash
# THIS IS NOT A GUARD DEMO IN THE SAME SENSE AS THE OTHER TEN. Every other
# example in this directory perturbs the guard's INPUT (the JSON event on
# stdin). This one perturbs its ENVIRONMENT (a missing/broken binary on
# PATH) -- an axis that was untested by construction across the whole pack,
# which is exactly why the bug below survived repeated verification: every
# round exercised the happy path and never asked what happens when a
# dependency is absent.
#
# protect-files.sh parses its event with `jq`. `jq` was documented nowhere
# in this pack. On a machine without it (or with a jq that errors when
# invoked), the ORIGINAL guard exited 0 and PERMITTED a write to `.env` --
# listed in settings.json, running, reporting success, protecting nothing.
# It has since been fixed to fail CLOSED. See
# .claude/hooks/test_protect_files_missing_jq.py, which this example
# borrows its stub-jq technique from.
#
# Three states, run in this order because the ordering IS the lesson:
#   1. real jq, planted violation                -> BLOCKED (the guard works)
#   2. broken jq stub on PATH, same violation     -> BLOCKED (fixed: fails closed)
#   3. the SAME broken-jq PATH, against the ORIGINAL pre-fix guard code
#      -> ALLOWED. Not a pass -- the historical bug, reproduced live.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

# --- Build a stub `jq` that fails exactly the way the bug report's
# reproduction did: prints a "command not found"-shaped line to stderr and
# exits 127. Lives entirely under $FIXTURE, so the same trap that removes
# the fixture also removes the stub -- there is no separate cleanup step to
# forget, and nothing here is ever placed on this shell's own $PATH: every
# hook invocation below passes its PATH override as a `PATH=... env`
# argument scoped to that one child process only (see expect_block/
# expect_allow -> run_hook in ../lib/common.sh), so this script's actual
# PATH is never mutated and there is nothing to restore. If this script
# dies partway (Ctrl-C, a failed assertion), the trap still fires and the
# stub directory is removed with it -- no stray `jq` is left on anyone's
# machine.
STUB_DIR="$FIXTURE/stub-bin"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/jq" <<'STUB'
#!/bin/sh
echo 'jq: command not found' >&2
exit 127
STUB
chmod +x "$STUB_DIR/jq"
BROKEN_JQ_PATH="$STUB_DIR:$PATH"

# --- The pre-fix protect-files.sh, exactly as it read before this pack's
# jq fail-open was found and fixed. Embedded as a static fixture (not read
# live from git) so this example stays stable regardless of what this
# repo's git history looks like later -- captured from and verifiable
# against commit ecd26c6 ("Import the guard hooks"):
#   git show ecd26c6:.claude/hooks/protect-files.sh
# The only change from the current, fixed .claude/hooks/protect-files.sh
# is the missing jq-availability/exit-status check: this version pipes
# straight into `jq -r ... // empty` with nothing checking whether jq
# itself succeeded.
PRE_FIX_HOOK="$FIXTURE/protect-files.pre-fix.sh"
cat > "$PRE_FIX_HOOK" <<'PREFIX'
#!/bin/bash
# Prevent edits to sensitive files

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

BASENAME=$(basename -- "$FILE_PATH")

block() {
  echo "Blocked: $FILE_PATH matches protected pattern '$1'" >&2
  exit 2
}

if [[ "$BASENAME" == ".env" || "$BASENAME" == .env.* ]]; then
  block ".env"
fi

if [[ "$BASENAME" == "package-lock.json" ]]; then
  block "package-lock.json"
fi

for dirpat in ".git/" "migrations/"; do
  case "/$FILE_PATH" in
    */"$dirpat"*)
      if [[ "$dirpat" == "migrations/" && ! -e "$FILE_PATH" ]]; then
        continue
      fi
      block "$dirpat"
      ;;
  esac
done

exit 0
PREFIX

VIOLATING_EVENT=$(jq -n --arg path "$FIXTURE/.env" \
  '{tool_name: "Write", tool_input: {file_path: $path, content: "SECRET=1\n"}}')

section "state 1 -- real jq, planted violation: Write to .env"
expect_block "$HOOKS_DIR/protect-files.sh" "$VIOLATING_EVENT" \
  "the guard works: real jq on PATH, .env write, blocked"

section "state 2 -- jq on PATH is a broken stub (exit 127), same violation"
expect_block "$HOOKS_DIR/protect-files.sh" "$VIOLATING_EVENT" \
  "the FIXED guard: same .env write, jq broken -- fails CLOSED and names jq in its message" \
  PATH="$BROKEN_JQ_PATH"

section "state 3 -- the historical defect, reproduced: same broken jq, PRE-FIX guard code"
expect_allow "$PRE_FIX_HOOK" "$VIOLATING_EVENT" \
  "THIS IS THE BUG, NOT A PASS: same broken-jq PATH, same .env write, run against the pre-fix protect-files.sh (commit ecd26c6, before this repo's own jq fail-open fix). Exit 0 -- the write to .env would have gone through. The guard was listed, running, and reporting nothing wrong, while protecting nothing." \
  PATH="$BROKEN_JQ_PATH"

echo
echo "Why this is its own example, not a footnote on 01_protect_files: every"
echo "other example here perturbs the guard's INPUT. This one perturbs its"
echo "ENVIRONMENT -- a missing binary, a missing config file, a failed import"
echo "are all the same shape (see also: 10_scope_gate_wrong_directory, a"
echo "missing-CONFIG variant of the same class). That axis was untested by"
echo "construction across the whole pack, which is exactly why this fail-open"
echo "survived repeated verification: every round exercised the happy path"
echo "and never asked what happens when a dependency is absent."

finish
