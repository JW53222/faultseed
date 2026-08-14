#!/usr/bin/env bash
# run_tests.sh -- the one command a stranger runs to find out whether this
# pack of guards actually works.
#
# House style: "A gate never proven to fail is indistinguishable from a
# gate that cannot fail." This script's job is to prove that, not just
# assert it -- it runs every unit-test suite in the tree AND the examples/
# planted-failure checks (each of which plants a real violation and
# confirms the guard actually rejects it), and it treats a suite/stage that
# runs ZERO checks as a distinct FAILURE, not a quiet pass. A test runner
# that can print "OK" having tested nothing is the exact defect this repo
# exists to make loud.
#
# Usable from any working directory: every path below is resolved relative
# to this script's own location, not $PWD.
set -uo pipefail   # deliberately NOT -e: each stage below is allowed to
                    # fail without aborting the others, so a red stage
                    # never hides the state of the rest. Failures are
                    # collected and the script exits nonzero at the end if
                    # any stage failed.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

STAGE_RESULTS=()
ANY_FAILED=0

pass_stage() {
  STAGE_RESULTS+=("PASS  $1")
  echo "----> PASS: $1"
}

fail_stage() {
  STAGE_RESULTS+=("FAIL  $1")
  ANY_FAILED=1
  echo "----> FAIL: $1" >&2
}

echo "======================================================================"
echo "run_tests.sh -- prerequisites"
echo "======================================================================"

# This repo's own floor, stated identically in .claude/hooks/_common.py's
# header comment and .claude/hooks/check_interpreter_floor.py's docstring:
# a module-level PEP-604 union annotation in _common.py raises TypeError on
# import under Python < 3.10. Below that floor every hook fails OPEN
# (ImportError -> exit 1 -> non-blocking in the Claude Code hook protocol).
FLOOR_MAJOR=3
FLOOR_MINOR=10

PYTHON_BIN="${PYTHON:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "FATAL: no '$PYTHON_BIN' on PATH." >&2
  echo "Install Python >= ${FLOOR_MAJOR}.${FLOOR_MINOR} and re-run, or set PYTHON=/path/to/python3." >&2
  exit 1
fi

PY_VER="$("$PYTHON_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
PY_FLOOR_OK="$("$PYTHON_BIN" -c "import sys; print(1 if sys.version_info[:2] >= (${FLOOR_MAJOR}, ${FLOOR_MINOR}) else 0)")"
if [[ "$PY_FLOOR_OK" != "1" ]]; then
  echo "FATAL: $PYTHON_BIN is $PY_VER; this repo's floor is >= ${FLOOR_MAJOR}.${FLOOR_MINOR}" >&2
  echo "(see .claude/hooks/check_interpreter_floor.py and .claude/hooks/_common.py's header comment)." >&2
  echo "Install a newer Python and re-run, or set PYTHON=/path/to/python${FLOOR_MAJOR}.${FLOOR_MINOR}+." >&2
  exit 1
fi
echo "python : $PYTHON_BIN ($PY_VER) -- meets the >=${FLOOR_MAJOR}.${FLOOR_MINOR} floor"

if ! "$PYTHON_BIN" -c "import pytest" >/dev/null 2>&1; then
  echo "FATAL: pytest is not importable under $PYTHON_BIN." >&2
  echo "Install it:  $PYTHON_BIN -m pip install pytest" >&2
  exit 1
fi
echo "pytest : $("$PYTHON_BIN" -c 'import pytest; print(pytest.__version__)')"

if ! "$PYTHON_BIN" -c "import yaml" >/dev/null 2>&1; then
  echo "FATAL: PyYAML is not importable under $PYTHON_BIN." >&2
  echo "It's needed by .claude/hooks/_common.py's engine-path scoping (is_engine_path)." >&2
  echo "Install it:  $PYTHON_BIN -m pip install pyyaml" >&2
  exit 1
fi
echo "PyYAML : $("$PYTHON_BIN" -c 'import yaml; print(yaml.__version__)')"

if ! command -v jq >/dev/null 2>&1; then
  echo "FATAL: jq is not on PATH." >&2
  echo "protect-files.sh reads its event with jq, and examples/ builds hook events with it." >&2
  echo "Install it: apt install jq  /  brew install jq  /  see https://jqlang.org/download/" >&2
  exit 1
fi
echo "jq     : $(jq --version)"

# ----------------------------------------------------------------------
# Stage: discover and run every pytest suite in the tree.
#
# "Discover, don't hardcode a list that will rot": rather than naming
# .claude/hooks/ and scripts/ literally, this scans for every file matching
# test_*.py / *_test.py (excluding examples/, adapters/, and VCS/cache
# noise) and runs pytest once per distinct top-two-level directory that
# contains one. .claude/hooks/ is discovered this way today; a future
# scripts/ suite (or anything else) is picked up automatically the moment
# it exists, with no edit to this script required.
# ----------------------------------------------------------------------
echo
echo "======================================================================"
echo "run_tests.sh -- discovering test suites"
echo "======================================================================"

mapfile -t TEST_FILES < <(
  find . -type f \( -name 'test_*.py' -o -name '*_test.py' \) \
    -not -path './examples/*' \
    -not -path './adapters/*' \
    -not -path './.git/*' \
    -not -path '*/__pycache__/*' \
    -not -path './.pytest_cache/*' \
    -not -path './.venv/*' \
    2>/dev/null | sort
)

declare -A SEEN_DIRS
TEST_DIRS=()
for f in "${TEST_FILES[@]}"; do
  rel="${f#./}"
  d="$(dirname "$rel")"
  # Collapse to the containing top-TWO-level directory (e.g. .claude/hooks,
  # scripts) so pytest runs once per logical suite, not once per file.
  IFS='/' read -r a b _ <<< "$d/__end__"
  if [[ -n "${b:-}" && "$b" != "__end__" ]]; then
    top="$a/$b"
  else
    top="$a"
  fi
  if [[ -z "${SEEN_DIRS[$top]:-}" ]]; then
    SEEN_DIRS[$top]=1
    TEST_DIRS+=("$top")
  fi
done

if [[ "${#TEST_DIRS[@]}" -eq 0 ]]; then
  fail_stage "test discovery -- VACUITY: no test_*.py / *_test.py files found anywhere in the tree"
else
  echo "found ${#TEST_DIRS[@]} suite(s): ${TEST_DIRS[*]}"
fi

run_pytest_stage() {
  local label="$1" dir="$2"
  echo
  echo "== $label ($dir) =="
  local out rc passed
  out=$("$PYTHON_BIN" -m pytest "$dir" -q --tb=short 2>&1)
  rc=$?
  echo "$out"
  if [[ $rc -eq 5 ]]; then
    fail_stage "$label -- VACUITY: pytest collected zero tests under $dir (exit 5)"
    return
  fi
  if [[ $rc -ne 0 ]]; then
    fail_stage "$label -- pytest exited $rc under $dir (see output above)"
    return
  fi
  # Vacuity guard even on a clean exit: an all-skipped/xfailed/deselected
  # suite can exit 0 while asserting nothing. Require at least one real
  # PASS, not just a zero exit code.
  passed=$(printf '%s\n' "$out" | grep -oE '[0-9]+ passed' | tail -1 | grep -oE '^[0-9]+' || true)
  passed="${passed:-0}"
  if [[ "$passed" -eq 0 ]]; then
    fail_stage "$label -- VACUITY: pytest exited 0 under $dir but 0 tests actually passed (all skipped/xfailed/deselected?)"
    return
  fi
  pass_stage "$label -- $passed passed"
}

for d in "${TEST_DIRS[@]}"; do
  run_pytest_stage "test suite: $d" "$d"
done

# ----------------------------------------------------------------------
# Stage: examples/ planted-failure checks. Each example plants a real
# violation and a legitimate near-miss, runs the actual hook, and asserts
# the exit code -- see examples/README.md. This is what makes "the tests
# pass" and "the guards demonstrably block things" the same claim.
# ----------------------------------------------------------------------
echo
echo "======================================================================"
echo "run_tests.sh -- examples/ planted-failure checks"
echo "======================================================================"

if [[ ! -d examples ]]; then
  fail_stage "examples/ -- VACUITY: examples/ directory does not exist"
elif [[ ! -x examples/run_all.sh ]]; then
  fail_stage "examples/ -- examples/run_all.sh is missing or not executable"
else
  if EX_OUT=$(bash examples/run_all.sh 2>&1); then
    echo "$EX_OUT"
    pass_stage "examples/ planted-failure checks"
  else
    echo "$EX_OUT"
    fail_stage "examples/ planted-failure checks (see output above)"
  fi
fi

# ----------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------
echo
echo "======================================================================"
echo "SUMMARY"
echo "======================================================================"
for r in "${STAGE_RESULTS[@]}"; do
  echo "$r"
done

if [[ "$ANY_FAILED" -ne 0 ]]; then
  echo
  echo "run_tests.sh: FAILED -- one or more stages above are red." >&2
  exit 1
fi

echo
echo "run_tests.sh: all stages passed."
exit 0
