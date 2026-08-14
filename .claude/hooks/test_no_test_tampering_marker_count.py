#!/usr/bin/env python3
"""Regression tests for no_test_tampering.py marker-count + comment-strip fixes,
plus the Go tamper grammar: no_test_tampering.py's original patterns were
Python/pytest/unittest + PowerShell/Pester only, so it was silently vacuous
on `_test.go` -- both because no SKIP_PATTERNS entry matched Go syntax AND
because `is_test_file()` (`_common.py`) didn't recognize the `_test.go`
suffix at all, so the hook exited via `allow()` before any pattern ever ran.

Black-box: feed a PreToolUse Edit event (stdin JSON) to the hook and assert exit
code (2 = block, 0 = allow). Pins two hardening changes:
  - the assertion-removal sanction is now per-NET-assertion: ONE sanction marker
    no longer waives a multi-assertion deletion (the old tombstone bypass).
  - full-line `#` comments are stripped before counting asserts, so a `# assert ...`
    comment line can't inflate the removed-assertion count (false positive).

Plus the Go grammar: t.Skip/t.SkipNow (guarded vs blanket), //go:build
ignore / +build ignore on a _test.go file, a discarded assertion target
(`_ = got` / `_ = err`), a commented-out t.Run subtest, and
t.Fatal/t.Fatalf/t.Error/t.Errorf folding into the net-assertion-removed
heuristic. See no_test_tampering.py's module docstring for the full grammar
and _go_blanket_skip_hits()'s docstring for the guard heuristic's known
false-positive shape.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no_test_tampering.py")
TESTPATH = "tests/test_example.py"
GO_TESTPATH = "modules/foo/bar_test.go"  # co-located Go convention, NOT under a tests/ dir --
                                          # exercises the `_test.go` SUFFIX rule in is_test_file(),
                                          # not the pre-existing "/tests/" path-segment rule.

# Build the sanction marker at runtime so this file's own source never carries a
# literal sanction token (the value `_MK` reconstructs) that another scan could trip on.
_MK = "# tampering" + "-ok: justified by the corresponding code change"
_MK_GO = "// tampering" + "-ok: justified by the corresponding code change"


def _run(old_string, new_string):
    ev = json.dumps({"tool_input": {
        "file_path": TESTPATH, "old_string": old_string, "new_string": new_string,
    }})
    return subprocess.run([sys.executable, HOOK], input=ev, text=True,
                          capture_output=True).returncode


# --- the fix: one marker no longer clears a multi-assertion removal ---
def test_two_asserts_removed_one_marker_blocked():
    old = "    assert a == 1\n    assert b == 2"
    new = f"    foo()  {_MK}\n    pass"
    assert _run(old, new) == 2

def test_two_asserts_removed_two_markers_allowed():
    old = "    assert a == 1\n    assert b == 2"
    new = f"    foo()  {_MK}\n    bar()  {_MK}"
    assert _run(old, new) == 0

def test_one_assert_removed_one_marker_allowed():
    old = "    assert a == 1"
    new = f"    foo()  {_MK}"
    assert _run(old, new) == 0


# --- the fix: comment-only `assert` text is stripped, not counted ---
def test_removed_assert_in_comment_not_counted():
    # Removing a COMMENT that merely contains the word "assert" must not register
    # as a removed assertion (was a false positive before the comment-strip).
    old = "    # assert legacy_behavior holds here"
    new = "    do_something()"
    assert _run(old, new) == 0


# --- controls: base behavior preserved ---
def test_real_assert_removed_no_marker_blocked():
    assert _run("    assert a == 1", "    pass") == 2

def test_brand_new_test_allowed():
    assert _run("", "    assert a == 1") == 0


# =============================================================================
# Go tamper grammar
# =============================================================================

def _run_go(old_string, new_string):
    ev = json.dumps({"tool_input": {
        "file_path": GO_TESTPATH, "old_string": old_string, "new_string": new_string,
    }})
    return subprocess.run([sys.executable, HOOK], input=ev, text=True,
                          capture_output=True).returncode


# CERTIFICATION BAR: the tamper canary (blanket skip, must BLOCK) and the
# adversarial legitimate golden (conditional skip, must ALLOW) live in the
# SAME test function on purpose -- a grammar that over-blocks the legitimate
# shape fails in the exact same place it is proven to catch the tamper shape.
def test_go_blanket_skip_blocked_and_conditional_skip_allowed():
    # CANARY: an unconditional t.Skip added to a passing-looking test -- the
    # Go analogue of the Python "make it pass" blanket skip. Must BLOCK.
    canary_new = (
        'func TestBar(t *testing.T) {\n'
        '\tt.Skip("skip because lazy")\n'
        '}'
    )
    assert _run_go("result := Bar()", canary_new) == 2

    # ADVERSARIAL GOLDEN: `if testing.Short() { t.Skip(...) }` is the
    # idiomatic, legitimate CONDITIONAL skip -- Go's analogue of Python's
    # allowed `@pytest.mark.skipif(...)`. Must ALLOW. If the grammar can't
    # tell "guarded" from "blanket" it fails HERE.
    golden_new = (
        'func TestBar(t *testing.T) {\n'
        '\tif testing.Short() {\n'
        '\t\tt.Skip("skipping in short mode")\n'
        '\t}\n'
        '}'
    )
    assert _run_go("result := Bar()", golden_new) == 0


def test_go_conditional_skip_same_line_form_allowed():
    # The one-liner guard form -- `if cond { t.Skip(...) }` on a single line --
    # is the other legitimate shape _go_blanket_skip_hits() recognizes.
    new = 'if runtime.GOOS == "windows" { t.Skip("unix-only") }'
    assert _run_go("result := Bar()", new) == 0


def test_go_build_ignore_on_test_file_blocked():
    assert _run_go("", "//go:build ignore\n\npackage foo") == 2


def test_go_legacy_build_tag_ignore_blocked():
    assert _run_go("", "// +build ignore\n\npackage foo") == 2


def test_go_discard_assignment_blocked():
    # `_ = err` replacing a real error check -- must BLOCK.
    assert _run_go("if err != nil {\n\tt.Fatal(err)\n}", "_ = err") == 2


def test_go_discard_of_call_result_not_blocked():
    # CONTROL for the discard-assignment pattern's own scoping: `_ = someCall()`
    # (discarding a FUNCTION CALL's result, e.g. a cleanup) is a common,
    # legitimate Go idiom and must NOT be caught by the bare-identifier-only
    # regex -- distinguishes "discarded a checked variable" from "discarded an
    # unrelated call's return value".
    assert _run_go("x := setup()", "_ = teardown()") == 0


def test_go_commented_out_subtest_blocked():
    old = 't.Run("case1", func(t *testing.T) { check(t) })'
    new = '// t.Run("case1", func(t *testing.T) { check(t) })'
    assert _run_go(old, new) == 2


def test_go_error_check_removed_without_replacement_blocked():
    # if err != nil { t.Fatal(err) } deleted with nothing assert-y in its
    # place -- folds into the existing net-assertion-removed heuristic via
    # the widened (Go-gated) assert_re.
    assert _run_go("if err != nil {\n\tt.Fatal(err)\n}", "if err != nil {\n}") == 2


def test_go_tampering_ok_escape_on_skip_allowed():
    new = (
        'func TestBar(t *testing.T) {\n'
        f'\tt.Skip("temporarily disabled") {_MK_GO}\n'
        '}'
    )
    assert _run_go("result := Bar()", new) == 0


# --- CONTROL: Python behavior is unaffected by the Go-only gating. `_ = x` is
# a legitimate Python idiom (discarding an unused local/fixture result); the
# Go discard-assignment pattern is deliberately gated on `path` ending in
# `.go` (see GO_ONLY_PATTERNS' module comment) specifically so this stays
# green. Distinguishes "Go support added" from "a shared pattern got
# over-widened and now also fires on Python files".
def test_control_python_discard_assignment_not_blocked():
    assert _run("y = compute()", "_ = compute()\n_ = err") == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError:
            fails += 1
            print(f"FAIL {fn.__name__}")
    raise SystemExit(1 if fails else 0)
