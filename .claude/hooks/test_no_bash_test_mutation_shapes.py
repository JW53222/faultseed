#!/usr/bin/env python3
"""Shape-coverage regression tests for no_bash_test_mutation.py.

New file rather than an addition to test_bash_marker_reason_required.py:
that file is specifically about the `# test-mutate-ok` reason-required
escape hatch (its own docstring says so -- 5 of its 10 tests are the
`test_mutation_*` functions covering marker behavior on top of a single
shape, `sed -i`). This file is about a different property: whether each of
the FIVE documented detection shapes (`sed -i`, `awk -i inplace`, `tee`,
`dd of=`, and a truncating/appending `>`/`>>` redirect) is actually
exercised at all. Mixing the two concerns into one file would blur what
each is pinning.

Before this file: only `sed -i` had any coverage (in
test_bash_marker_reason_required.py and examples/06_no_bash_test_mutation).
docs/guards/no_bash_test_mutation.md documents five shapes; a mutation pass
confirmed the other four -- awk, tee, dd, and the plain redirect -- could be
disabled (together, and awk alone) with the whole suite staying green. This
file closes that gap: each shape gets a block case (mutating an EXISTING
test file) and an ALLOW near-miss, per the guard's own documented rules --
    - only a target that already exists on disk is a "mutation"; creating
      a brand-new test file via the same mechanism is allowed
    - a target that isn't a test path at all is never in scope
    - `# test-mutate-ok: <reason>` clears a real block; a bare marker with
      no reason does not (mirrors the other escape markers in this pack)
and the escape marker is exercised on a newly-covered shape (`awk -i
inplace`), not just on `sed -i` as before.

Black-box: feed a PreToolUse Bash event (stdin JSON) to the hook and assert
exit code (2 = block, 0 = allow) plus a distinguishing phrase in stderr.

Payload strings below intentionally avoid the word "assert" (the target
file's actual future content is irrelevant to this hook -- it never reads
what the command WOULD write, only whether the command's shape+target are a
mutation of an existing test path) so that later edits to this file don't
tangle with no_test_tampering.py's own assertion-count heuristic, which
scans line text rather than parsing Python/shell semantics.
"""
import json
import os
import subprocess
import sys
import tempfile

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
MUTATION_HOOK = os.path.join(HOOKS_DIR, "no_bash_test_mutation.py")


def _make_existing_test_file(d, name="test_foo.py"):
    target = os.path.join(d, "tests")
    os.makedirs(target, exist_ok=True)
    path = os.path.join(target, name)
    open(path, "w").close()
    return path


def _run(command, cwd, env_extra=None):
    ev = json.dumps({"tool_input": {"command": command}, "cwd": cwd})
    env = dict(os.environ)
    env.pop("GUARDRAILS_INTEGRATOR_ROLE", None)
    # Point telemetry at a throwaway dir so this test suite never writes
    # into the real repo's .claude/hooks/state/ (or anywhere else outside
    # tmp_path-equivalent scratch).
    env["CLAUDE_PROJECT_DIR"] = cwd
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, MUTATION_HOOK], input=ev, text=True, capture_output=True, env=env
    )


# =============================================================================
# awk -i inplace
# =============================================================================

def test_awk_inplace_blocks_existing_test_file():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run("awk -i inplace '{print}' tests/test_foo.py", d)
        assert r.returncode == 2
        assert "mutates an EXISTING test file" in r.stderr
        assert "awk -i inplace" in r.stderr


def test_awk_inplace_allowed_on_non_test_file():
    # Nearest legitimate thing to the block above: identical mechanism,
    # target was never a test file.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "notes.txt")
        open(path, "w").close()
        r = _run("awk -i inplace '{print}' notes.txt", d)
        assert r.returncode == 0


def test_awk_without_inplace_flag_allowed_even_on_test_file():
    # The other genuine near-miss: ordinary awk (no -i) only prints to
    # stdout, it never rewrites the file -- not a mutation shape at all,
    # regardless of target.
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run("awk '{print}' tests/test_foo.py", d)
        assert r.returncode == 0


def test_awk_inplace_escape_bare_marker_blocked_with_reason_required_message():
    # Escape marker exercised on a newly-covered shape, not just sed -i.
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run("awk -i inplace '{print}' tests/test_foo.py # test-mutate-ok", d)
        assert r.returncode == 2
        assert "needs a reason" in r.stderr


def test_awk_inplace_escape_with_reason_allowed():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run(
            "awk -i inplace '{print}' tests/test_foo.py "
            "# test-mutate-ok: reformat whitespace only, coverage unchanged",
            d,
        )
        assert r.returncode == 0


# =============================================================================
# tee
# =============================================================================

def test_tee_blocks_existing_test_file():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run("echo 'new body' | tee tests/test_foo.py", d)
        assert r.returncode == 2
        assert "mutates an EXISTING test file" in r.stderr
        assert "tee" in r.stderr


def test_tee_allowed_creating_new_test_file():
    # Structurally-guaranteed near-miss called out in the guard's own
    # docstring: creating a brand-new test file is not a mutation.
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tests"))
        r = _run("echo 'new body' | tee tests/test_new.py", d)
        assert r.returncode == 0


def test_tee_allowed_on_non_test_file():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "notes.txt")
        open(path, "w").close()
        r = _run("echo 'scratch' | tee notes.txt", d)
        assert r.returncode == 0


# =============================================================================
# dd of=
# =============================================================================

def test_dd_of_blocks_existing_test_file():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run("dd if=/dev/zero of=tests/test_foo.py bs=1 count=1", d)
        assert r.returncode == 2
        assert "mutates an EXISTING test file" in r.stderr
        assert "dd of=" in r.stderr


def test_dd_of_allowed_on_non_test_file():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "notes.txt")
        open(path, "w").close()
        r = _run("dd if=/dev/zero of=notes.txt bs=1 count=1", d)
        assert r.returncode == 0


# =============================================================================
# redirect: > (truncating) and >> (appending)
# =============================================================================

def test_redirect_truncate_blocks_existing_test_file():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run("echo 'new body' > tests/test_foo.py", d)
        assert r.returncode == 2
        assert "mutates an EXISTING test file" in r.stderr
        assert "redirect >" in r.stderr


def test_redirect_append_blocks_existing_test_file():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run("echo 'extra line' >> tests/test_foo.py", d)
        assert r.returncode == 2
        assert "mutates an EXISTING test file" in r.stderr
        assert "redirect >>" in r.stderr


def test_redirect_truncate_allowed_creating_new_test_file():
    # Explicit documented ALLOW case: target file does NOT yet exist on
    # disk -- creating it via redirect is not a mutation.
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tests"))
        r = _run("echo 'new body' > tests/test_new.py", d)
        assert r.returncode == 0


def test_redirect_allowed_on_non_test_file():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "notes.txt")
        open(path, "w").close()
        r = _run("echo 'scratch' > notes.txt", d)
        assert r.returncode == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            fails += 1
            print(f"ERROR {fn.__name__}: {e}")
    raise SystemExit(1 if fails else 0)
