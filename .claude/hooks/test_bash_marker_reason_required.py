#!/usr/bin/env python3
"""Regression tests: `# test-mutate-ok` / `# delete-tests-ok` now require a
reason, mirroring the Edit-side markers (`tampering-ok:`, `swallow-ok:`,
`falsy-zero-ok:`).

Pins the hardening of no_bash_test_mutation.py and no_bash_test_deletion.py:
previously both markers were bare, self-grantable escape hatches
(`# test-mutate-ok`, `# delete-tests-ok` with no rationale) -- the same
shape as the incident these hooks exist to catch. Now:

  - a bare marker on a command that WOULD be blocked -> still BLOCKED, with a
    distinct "needs a reason" message (not silently treated as no-marker).
  - `<marker>: <non-empty reason>` -> ALLOWED.
  - no marker at all on a blockable command -> BLOCKED (unchanged baseline).

Black-box: feed a PreToolUse Bash event (stdin JSON) to each hook and assert
exit code (2 = block, 0 = allow) plus a distinguishing phrase in stderr for
the bare-marker case.
"""
import json
import os
import subprocess
import sys
import tempfile

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
MUTATION_HOOK = os.path.join(HOOKS_DIR, "no_bash_test_mutation.py")
DELETION_HOOK = os.path.join(HOOKS_DIR, "no_bash_test_deletion.py")


def _make_existing_test_file(d):
    target = os.path.join(d, "tests")
    os.makedirs(target)
    path = os.path.join(target, "test_foo.py")
    open(path, "w").close()


def _run(hook, command, cwd, env_extra=None):
    ev = json.dumps({"tool_input": {"command": command}, "cwd": cwd})
    env = dict(os.environ)
    env.pop("GUARDRAILS_INTEGRATOR_ROLE", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, hook], input=ev, text=True, capture_output=True, env=env
    )


# --- no_bash_test_mutation.py: `# test-mutate-ok` ---

def test_mutation_bare_marker_blocked_with_reason_required_message():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run(MUTATION_HOOK, "sed -i 's/x/y/' tests/test_foo.py # test-mutate-ok", d)
        assert r.returncode == 2
        assert "needs a reason" in r.stderr


def test_mutation_marker_with_reason_allowed():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run(
            MUTATION_HOOK,
            "sed -i 's/x/y/' tests/test_foo.py # test-mutate-ok: matches new evaluator arg",
            d,
        )
        assert r.returncode == 0


def test_mutation_marker_with_only_whitespace_reason_blocked():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run(MUTATION_HOOK, "sed -i 's/x/y/' tests/test_foo.py # test-mutate-ok:   ", d)
        assert r.returncode == 2
        assert "needs a reason" in r.stderr


def test_mutation_no_marker_blocked_normal_message():
    with tempfile.TemporaryDirectory() as d:
        _make_existing_test_file(d)
        r = _run(MUTATION_HOOK, "sed -i 's/x/y/' tests/test_foo.py", d)
        assert r.returncode == 2
        assert "needs a reason" not in r.stderr
        assert "mutates an EXISTING test file" in r.stderr


def test_mutation_non_test_file_allowed_even_with_bare_marker():
    # Bare marker is irrelevant when there's nothing to block in the first place.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "notes.txt")
        open(path, "w").close()
        r = _run(MUTATION_HOOK, "sed -i 's/x/y/' notes.txt # test-mutate-ok", d)
        assert r.returncode == 0


# --- no_bash_test_deletion.py: `# delete-tests-ok` ---

def test_deletion_bare_marker_blocked_with_reason_required_message():
    with tempfile.TemporaryDirectory() as d:
        r = _run(DELETION_HOOK, "rm tests/test_foo.py # delete-tests-ok", d)
        assert r.returncode == 2
        assert "needs a reason" in r.stderr


def test_deletion_marker_with_reason_allowed():
    with tempfile.TemporaryDirectory() as d:
        r = _run(
            DELETION_HOOK,
            "rm tests/test_foo.py # delete-tests-ok: obsolete suite replaced by test_bar.py",
            d,
        )
        assert r.returncode == 0


def test_deletion_marker_with_only_whitespace_reason_blocked():
    with tempfile.TemporaryDirectory() as d:
        r = _run(DELETION_HOOK, "rm tests/test_foo.py # delete-tests-ok:   ", d)
        assert r.returncode == 2
        assert "needs a reason" in r.stderr


def test_deletion_no_marker_blocked_normal_message():
    with tempfile.TemporaryDirectory() as d:
        r = _run(DELETION_HOOK, "rm tests/test_foo.py", d)
        assert r.returncode == 2
        assert "needs a reason" not in r.stderr
        assert "deletes or moves test files" in r.stderr


def test_deletion_non_test_target_allowed_even_with_bare_marker():
    with tempfile.TemporaryDirectory() as d:
        r = _run(DELETION_HOOK, "rm scratch.txt # delete-tests-ok", d)
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
