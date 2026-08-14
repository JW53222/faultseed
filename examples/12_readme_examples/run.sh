#!/usr/bin/env bash
# THIS IS NOT A GUARD DEMO. It is a check on the OTHER ten examples' shared
# claim: README.md's "### Worked examples" section (nine command/output/
# exit-code triples, plus a one-time `sed` configure step) asserts it was
# really run against the real hooks. Nothing enforced that assertion stays
# true after the day it was written -- and it has drifted twice, silently,
# each time found only by an external reviewer reading the prose by eye:
#
#   1. A worked example printed "exit 2" and the real command actually
#      returned 0 -- the guard only blocks mutating a test file that
#      already exists on disk, and the copy-pasteable command omitted that
#      precondition.
#   2. A later commit changed the shipped `engine_dirs` default to an
#      unconfigured sentinel. The two engine-scoped worked examples then
#      blocked with a CONFIG-ERROR message instead of the one documented,
#      and their near-miss claims went false with them.
#
# `examples/` is machine-checked by run_tests.sh; README prose is not.
# That asymmetry is the bug this example closes: it parses the worked
# examples out of README.md at RUN TIME (extract_readme_blocks.py, in this
# directory -- read its module docstring for the exact parsing rule) and
# executes what it finds, so a stale claim in the prose fails the suite
# instead of waiting for the next external reviewer to notice.
#
# WHAT COUNTS AS CHECKED (declared subset, not everything in the section):
#   - Every fenced block with a "$ " command line and an "exit N" line: its
#     last command's real exit code must equal N, and the real first line
#     of its stderr must equal the block's one documented output line.
#   - The one fenced block with commands but no "exit N" line (the
#     `engine_dirs` `sed` configure step): executed, in document order, so
#     the two engine-scoped checkable blocks that follow it see its
#     effect -- but not itself asserted beyond "didn't error", since its
#     substance IS the two checks right after it.
#   - The parenthetical near-miss claim after "exit N" ("same shape
#     against config.envoy.yaml instead of .env: exit 0") is captured by
#     the parser and printed on failure, but NOT executed -- deriving a
#     second command from that English prose would itself be exactly the
#     fragile, overfit-to-today's-wording parser this task warned against.
#   - The parser floors its own block count (see CHECKABLE_FLOOR/
#     SETUP_FLOOR below) so a parser that silently stops matching --
#     because the section heading or fence shape changed -- fails loudly
#     instead of reporting a quiet, meaningless PASS. A parser matching
#     zero blocks and exiting 0 is the exact "looks installed, checks
#     nothing" defect this whole repo exists to catch.
#
# WHY A SEPARATE SANDBOX, NOT common.sh's HOOKS_DIR: ../lib/common.sh
# already builds a synthetic hooks tree for exactly this class of problem
# (a private docs/audit/audit-scope.yaml so examples don't depend on this
# repo's own shipped config) -- see its header comment. But that tree
# writes engine_dirs: ["src"] directly, SKIPPING the unconfigured-sentinel
# state entirely. This example specifically needs to execute the README's
# literal `sed` step against a file that STARTS in the real shipped
# (sentinel) state, the way a reader's fresh clone does -- so it builds its
# own sandbox using the SAME technique (copy the real hook files, give them
# a private docs/audit/audit-scope.yaml) but seeds that yaml from this
# repo's actual shipped file instead of a pre-baked "src" config. Nothing
# below ever writes to this repo's own docs/audit/audit-scope.yaml.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

SANDBOX="$(mktemp -d)"
BLOCKS_FILE="$(mktemp)"
trap 'rm -rf "$SANDBOX"; rm -f "$BLOCKS_FILE"' EXIT

mkdir -p "$SANDBOX/.claude/hooks" "$SANDBOX/docs/audit"
# Same file list ../lib/common.sh copies, for the same reason: every hook a
# worked example in README.md invokes, plus _common.py they all import.
for _hook_file in _common.py agent_sizing_gate.py no_bash_test_deletion.py \
    no_bash_test_mutation.py no_swallowed_errors.py no_test_tampering.py \
    no_type_checking_stub.py protect-files.sh subagent_closing_report.py \
    workflow_agent_sizing_gate.py; do
  cp "$REPO_ROOT/.claude/hooks/$_hook_file" "$SANDBOX/.claude/hooks/$_hook_file"
done
unset _hook_file
# The one difference from common.sh's tree: carry over the REAL shipped
# audit-scope.yaml (sentinel and all) instead of a pre-configured one, so
# the README's own `sed` configure step has something real to act on.
cp "$REPO_ROOT/docs/audit/audit-scope.yaml" "$SANDBOX/docs/audit/audit-scope.yaml"

# README_PATH override exists ONLY so this example's own drift-detection
# claim is falsifiable on demand (point it at a doctored copy and watch a
# planted mismatch get caught). Nothing in this repo sets it; a normal run
# always checks this repo's real, unmodified README.md.
README_PATH="${README_PATH:-$REPO_ROOT/README.md}"

section "parsing $README_PATH's Worked examples section"
python3 "$DIR/extract_readme_blocks.py" "$README_PATH" > "$BLOCKS_FILE"
# extract_readme_blocks.py itself exits 1 with a message on stderr for any
# block shape it can't make sense of (ambiguous output-line count, missing
# command, unterminated fence, missing section) -- `set -e` above means
# this script already stopped if that happened. Reaching here means every
# fenced block in the section matched one of the two declared shapes.

CHECKABLE_COUNT=$(jq -s '[.[] | select(.kind=="checkable")] | length' "$BLOCKS_FILE")
SETUP_COUNT=$(jq -s '[.[] | select(.kind=="setup")] | length' "$BLOCKS_FILE")
TOTAL_COUNT=$(jq -s 'length' "$BLOCKS_FILE")

# Floors, not targets: this is the exact count the section holds as of this
# writing (9 checkable worked examples + 1 setup step, the engine_dirs
# `sed`). If README.md legitimately grows more worked examples later, raise
# these -- don't remove them. If it ever drops BELOW these, that's either a
# real section shrink (which should be a deliberate, reviewed floor change)
# or this parser silently losing the plot -- either way, this must not pass
# quietly.
CHECKABLE_FLOOR=9
SETUP_FLOOR=1

CHECKS_RUN=$((CHECKS_RUN + 1))
if [[ "$CHECKABLE_COUNT" -lt "$CHECKABLE_FLOOR" || "$SETUP_COUNT" -lt "$SETUP_FLOOR" ]]; then
  echo "VACUITY: parser found $CHECKABLE_COUNT checkable + $SETUP_COUNT setup block(s)," >&2
  echo "floor is $CHECKABLE_FLOOR checkable + $SETUP_FLOOR setup. Either README.md's" >&2
  echo "Worked examples section genuinely shrank (lower the floor deliberately, in" >&2
  echo "this file) or extract_readme_blocks.py silently stopped matching blocks it" >&2
  echo "used to match -- the exact failure mode this example exists to catch." >&2
  exit 1
fi
echo "FLOOR OK -- $TOTAL_COUNT block(s) found ($CHECKABLE_COUNT checkable, $SETUP_COUNT setup), floor is $((CHECKABLE_FLOOR + SETUP_FLOOR))"

# run_readme_block SCRIPT -- runs a block's commands (already newline-joined,
# in document order) as one bash script, cwd=$SANDBOX, exactly like
# ../lib/common.sh's run_hook: stdout discarded, stderr captured into
# BLOCK_STDERR, exit code into BLOCK_RC. No `&&`/`set -e` chaining between a
# block's own commands -- a bash script's exit status is its LAST
# statement's by default, which is what "run these lines in order in a
# terminal" means; an earlier line failing surfaces naturally in the final
# command's own behavior (e.g. a missing fixture file), not by us guessing.
run_readme_block() {
  local script="$1"
  set +e
  BLOCK_STDERR=$(cd "$SANDBOX" && bash -c "$script" 2>&1 >/dev/null)
  BLOCK_RC=$?
  set -e
}

section "executing ${TOTAL_COUNT} block(s), in document order, against the sandbox"

while IFS= read -r block_json; do
  kind=$(jq -r '.kind' <<<"$block_json")
  title=$(jq -r '.title' <<<"$block_json")
  doc_line=$(jq -r '.line' <<<"$block_json")
  mapfile -t commands < <(jq -r '.commands[]' <<<"$block_json")
  script=$(printf '%s\n' "${commands[@]}")

  run_readme_block "$script"

  if [[ "$kind" == "setup" ]]; then
    CHECKS_RUN=$((CHECKS_RUN + 1))
    if [[ "$BLOCK_RC" -ne 0 ]]; then
      echo "FAIL -- setup step at README.md:$doc_line ('$title') exited $BLOCK_RC, expected 0" >&2
      echo "  command(s):" >&2
      printf '    %s\n' "${commands[@]}" >&2
      echo "  stderr: $BLOCK_STDERR" >&2
      exit 1
    fi
    echo "SETUP OK -- README.md:$doc_line ('$title') ran cleanly"
    continue
  fi

  expected_exit=$(jq -r '.expected_exit' <<<"$block_json")
  expected_first_line=$(jq -r '.expected_first_line' <<<"$block_json")
  actual_first_line=$(printf '%s' "$BLOCK_STDERR" | head -1)

  CHECKS_RUN=$((CHECKS_RUN + 1))
  if [[ "$BLOCK_RC" -eq "$expected_exit" ]]; then
    echo "EXIT MATCH -- README.md:$doc_line ('$title'): exit $BLOCK_RC, as documented"
  else
    echo "FAIL -- README.md:$doc_line ('$title'): documented \`exit $expected_exit\`, observed exit $BLOCK_RC" >&2
    echo "  command(s):" >&2
    printf '    %s\n' "${commands[@]}" >&2
    echo "  stderr: $BLOCK_STDERR" >&2
    exit 1
  fi

  CHECKS_RUN=$((CHECKS_RUN + 1))
  if [[ "$actual_first_line" == "$expected_first_line" ]]; then
    echo "OUTPUT MATCH -- README.md:$doc_line ('$title'): first stderr line as documented"
  else
    echo "FAIL -- README.md:$doc_line ('$title'): first stderr line differs from README.md" >&2
    echo "  documented: $expected_first_line" >&2
    echo "  actual:     $actual_first_line" >&2
    exit 1
  fi
done < <(jq -c '.' "$BLOCKS_FILE")

finish
