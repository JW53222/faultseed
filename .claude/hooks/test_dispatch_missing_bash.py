#!/usr/bin/env python3
"""Planted-failure test for the bash fail-open defect in _dispatch.py's
`.sh`-hook syntax probe.

THE DEFECT: `_check_sh_syntax()` ran `subprocess.run(["bash", "-n", target],
...)` with no try/except. If `bash` itself is missing or unrunnable, that
raises `FileNotFoundError` (or another `OSError`) uncaught out of `main()`.
Python exits 1 on an uncaught exception, and the Claude Code hook protocol
treats exit 1 as NON-BLOCKING -- so `_dispatch.py`, whose entire job is to
make a broken hook fail LOUD instead of silently permitting the tool call,
would itself fail OPEN on exactly the guardrail it was supposed to be
protecting. Same class as the jq fail-open in protect-files.sh (see
test_protect_files_missing_jq.py) and the PEP-604-import fail-open
check_interpreter_floor.py exists to catch -- an external dependency the
guard needs to RUN AT ALL, missing, escaping as a silent non-blocking exit.

THE FIX mirrors check_interpreter_floor.py's own interpreter probe: wrap the
subprocess call in try/except OSError and return an error string (the same
contract `_check_sh_syntax` already uses for an actual `bash -n` syntax
finding), so the failure flows through _dispatch.py's EXISTING
guardrail/advisory classification in `main()` instead of escaping as an
uncaught exception. No new branching was needed in `main()` -- it already
treats any non-None probe result as a load/probe failure and routes it
through `_block_guardrail_import_failure` / `_warn_advisory_import_failure`
by hook_rel, regardless of which probe function produced it.

Black-box throughout: never imports _dispatch.py, only invokes the REAL
`.claude/hooks/_dispatch.py` (this repo's own, unmodified) as a subprocess,
pointed via AUDIT_HARNESS_HOOKS_DIR / CLAUDE_PROJECT_DIR at synthetic
tmp_path fixtures -- mirrors test_dispatch_guardrail_vs_advisory.py's own
copy-and-dispatch scaffolding (duplicated here rather than imported, since
that file is owned separately and test files in this pack do not import
each other).

Every assertion checks BOTH the exit code AND a SPECIFIC, distinguishing
piece of stderr content, not exit code alone -- an exit-code-only check
cannot tell a real, diagnosed block apart from a mutant that blocks (or
allows) unconditionally for the wrong reason. The planted-failure test
checks that "bash" is named; the two "unaffected by bash's absence" and
"real bash present" controls check for the SPECIFIC guardrail message
(`no_test_tampering.py`'s "weakens a test", protect-files.sh's "protected
pattern '.env'") rather than a bare exit code, precisely so an over-broad
"block/allow/skip everything" mutant cannot pass by accident -- each of
these was verified against a real mutant of that exact shape (see each
function's own "Mutation check performed" note). Positive controls confirm
the fix didn't just start blocking everything: with real bash on PATH, the
same guardrail .sh hook still dispatches, allows a benign event, and still
blocks a real hit; a genuine syntax error in a .sh hook is still caught and
named as a syntax error specifically (not conflated with "bash is
missing"); and a `.py` guardrail hook (whose probe never shells out to bash
at all) is completely unaffected by bash's absence.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
REAL_DISPATCH = HOOKS_DIR / "_dispatch.py"

# Resolve bash's own full path ONCE, from the real (unmodified) PATH, so a
# test that strips bash's directory out of PATH can still invoke bash
# directly where needed (e.g. to build a stub). subprocess.run(["bash", ...])
# inside _dispatch.py itself is exactly what we are testing the ABSENCE of.
REAL_BASH = shutil.which("bash")

BENIGN_EVENT_NO_PATH = '{"tool_input": {}}'


def _copy_working_hooks(dst: Path) -> Path:
    """A full, unbroken copy of every *.py/*.sh hook in this repo's real
    .claude/hooks/ (test_*.py and docs excluded -- irrelevant to dispatch).
    Mirrors test_dispatch_guardrail_vs_advisory.py's helper of the same
    shape."""
    dst.mkdir(parents=True, exist_ok=True)
    for name in os.listdir(HOOKS_DIR):
        src = HOOKS_DIR / name
        if not src.is_file():
            continue
        if name.startswith("test_") or name.endswith(".md"):
            continue
        shutil.copy2(src, dst / name)
    return dst


def _env_without_bash():
    """A copy of the real environment with bash's directory stripped out of
    PATH, so `_dispatch.py`'s own `subprocess.run(["bash", ...])` genuinely
    cannot find it -- mirrors test_protect_files_missing_jq.py's
    `_env_without_jq`."""
    env = dict(os.environ)
    if REAL_BASH is None:
        return env  # bash already isn't installed here; nothing to strip
    bash_dir = os.path.realpath(os.path.dirname(REAL_BASH))
    dirs = [
        d for d in env.get("PATH", "").split(os.pathsep)
        if d and os.path.realpath(d) != bash_dir
    ]
    env["PATH"] = os.pathsep.join(dirs)
    return env


def _run_dispatch(hook_rel, *, audit_hooks_dir, project_dir, env=None,
                   stdin=BENIGN_EVENT_NO_PATH, timeout=30):
    full_env = dict(os.environ) if env is None else dict(env)
    for k in ("AUDIT_HARNESS_HOOKS_DIR", "SKIP_HOOK_DISPATCH", "CLAUDE_PROJECT_DIR"):
        full_env.pop(k, None)
    full_env["AUDIT_HARNESS_HOOKS_DIR"] = str(audit_hooks_dir)
    full_env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    proc = subprocess.run(
        [sys.executable, str(REAL_DISPATCH), hook_rel],
        input=stdin, text=True, capture_output=True, env=full_env, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# THE PLANTED FAILURE: bash missing from PATH must BLOCK, not silently PERMIT
# ---------------------------------------------------------------------------

def test_missing_bash_blocks_sh_guardrail_instead_of_silently_permitting(tmp_path):
    """protect-files.sh is a real guardrail .sh hook shipped in this pack.
    With bash stripped from PATH, _dispatch.py's syntax probe cannot run at
    all -- this must fail CLOSED (exit 2, naming bash), not escape as an
    uncaught FileNotFoundError (exit 1, non-blocking, tool call permitted).

    Mutation check performed: ran this same assertion against
    `git show HEAD:.claude/hooks/_dispatch.py` (the pre-fix content, saved to
    a scratch copy alongside an unmodified _common.py and protect-files.sh)
    -- went RED: returncode 1, stderr a raw Python traceback ending in
    `FileNotFoundError: [Errno 2] No such file or directory: 'bash'`, no
    "BLOCKED" text, no exit 2. Ran again against the fixed _dispatch.py --
    GREEN.
    """
    hooks_dir = _copy_working_hooks(tmp_path / "hooks_ok")

    rc, _out, err = _run_dispatch(
        "protect-files.sh",
        audit_hooks_dir=hooks_dir,
        project_dir=tmp_path / "proj",
        env=_env_without_bash(),
    )

    assert rc == 2, f"missing bash must BLOCK (exit 2), got {rc}: {err}"
    # rc == 2 specifically (not 1) is itself part of the "never exec'd the
    # unverified hook" proof: an uncaught FileNotFoundError from the old code
    # exits 1 (Python's default for an uncaught exception), not the
    # deliberate sys.exit(2) _block_guardrail_import_failure() writes.
    assert rc != 1
    assert "bash" in err.lower()
    assert "protect-files.sh" in err
    assert "BLOCKED" in err
    assert "Traceback" not in err, (
        "a raw Python traceback in stderr means the failure escaped the "
        "probe uncaught rather than being handled and reported -- exactly "
        "the pre-fix defect shape"
    )


def test_missing_bash_does_not_affect_py_guardrail_dispatch(tmp_path):
    """A `.py` guardrail hook's probe (`_check_importable`) never shells out
    to bash at all -- bash's absence must not affect it.

    Deliberately uses an event `no_test_tampering.py` is known to BLOCK
    (a real assertion removed, no `tampering-ok:` marker), not an ALLOW
    event: an allow-only assertion cannot distinguish "the hook genuinely
    ran its own body logic" from "dispatch silently no-op'd and exited 0
    for an unrelated reason" (e.g. an over-broad "skip everything when bash
    is missing" mutant) -- both look identical under `rc == 0`. Asserting
    the SPECIFIC block (rc == 2, the hook's own "weakens a test" message)
    proves the guardrail's real code path executed.

    Mutation check performed: a scratch mutant that made `_skip_requested()`
    (checked before anything hook-specific) always return True went RED
    against the version of this test that only asserted an allow event
    (rc == 0) -- the mutant exits 0 too, for the wrong reason, so that
    assertion passed anyway and the mutant went undetected. Switching to
    this block-event assertion catches it: the "always skip" mutant now
    returns rc == 0 where this test expects rc == 2 -- RED, as it should be.
    Restored, re-ran -- GREEN.
    """
    hooks_dir = _copy_working_hooks(tmp_path / "hooks_ok")

    rc, _out, err = _run_dispatch(
        "no_test_tampering.py",
        audit_hooks_dir=hooks_dir,
        project_dir=tmp_path / "proj",
        env=_env_without_bash(),
        stdin=json.dumps({"tool_input": {
            "file_path": "tests/test_example.py",
            "old_string": "    assert a == 1",
            "new_string": "    pass",
        }}),
    )

    assert rc == 2, (
        f"a .py guardrail's dispatch must be unaffected by bash's absence "
        f"and must still reach its own BLOCK verdict, got {rc}: {err}"
    )
    assert "weakens a test" in err


# ---------------------------------------------------------------------------
# Positive controls: real bash present -- fix must not have started
# blocking everything, and the pre-existing syntax-error path (a REAL bash
# -n finding, as opposed to bash being unrunnable) must still work exactly
# as before.
# ---------------------------------------------------------------------------

def test_real_bash_still_dispatches_sh_guardrail_normally(tmp_path):
    """Same guardrail hook, unmodified environment (real bash on PATH).
    Checks BOTH a block and an allow, not just one exit code: a benign event
    (no file_path) must ALLOW, and a real protected-file write must still
    BLOCK for protect-files.sh's OWN stated reason. An allow-only assertion
    cannot distinguish real dispatch from an over-broad mutant that
    accidentally allows everything -- the block case rules that out.

    Mutation check performed: against a scratch mutant of the fixed
    _check_sh_syntax() with the `try:`/`except OSError:` replaced by an
    unconditional `return "always broken"` -- went RED on BOTH assertions
    below (every .sh dispatch reports a probe failure regardless of bash's
    presence or the event content, so the benign event no longer exits 0
    and the .env write blocks for the probe-failure reason, not
    protect-files.sh's own "protected pattern" reason). GREEN against the
    real fixed file.
    """
    hooks_dir = _copy_working_hooks(tmp_path / "hooks_ok")

    rc_allow, _out, err_allow = _run_dispatch(
        "protect-files.sh",
        audit_hooks_dir=hooks_dir,
        project_dir=tmp_path / "proj_allow",
        env=dict(os.environ),
    )
    assert rc_allow == 0, f"positive control (real bash) must ALLOW, got {rc_allow}: {err_allow}"

    rc_block, _out, err_block = _run_dispatch(
        "protect-files.sh",
        audit_hooks_dir=hooks_dir,
        project_dir=tmp_path / "proj_block",
        env=dict(os.environ),
        stdin=json.dumps({"tool_input": {"file_path": ".env"}}),
    )
    assert rc_block == 2, f"positive control (real bash) must still BLOCK a real hit, got {rc_block}: {err_block}"
    assert "protected pattern '.env'" in err_block, (
        "must block for protect-files.sh's OWN stated reason, not a "
        "generic dispatch-probe failure"
    )


def test_real_bash_still_catches_genuine_sh_syntax_error(tmp_path):
    """A REAL `bash -n` syntax finding (not bash being missing) must still
    be caught and BLOCKED, and the message must be a syntax diagnostic, not
    the "could not run bash" wording the missing-bash case produces --
    confirms the fix didn't collapse two distinct failure shapes into one
    generic message.

    Mutation check performed: reverted `_check_sh_syntax` to the pre-fix
    version (no try/except) against this same planted syntax error -- still
    went GREEN there too (a real bash on PATH, a genuine non-zero `bash -n`
    exit, no exception raised) -- confirming this test exercises the
    PRE-EXISTING syntax-check path, not the new OSError-handling path, and
    that the fix did not regress it.
    """
    hooks_dir = _copy_working_hooks(tmp_path / "hooks_ok")
    broken_sh = hooks_dir / "broken_syntax_hook.sh"
    broken_sh.write_text("#!/bin/bash\nif [[ true; then\n  echo oops\n")
    broken_sh.chmod(0o755)

    rc, _out, err = _run_dispatch(
        "broken_syntax_hook.sh",
        audit_hooks_dir=hooks_dir,
        project_dir=tmp_path / "proj",
        env=dict(os.environ),
    )
    assert rc == 2, f"a genuine .sh syntax error must BLOCK, got {rc}: {err}"
    assert "syntax error" in err.lower(), err
    assert "could not run bash" not in err, (
        "a genuine syntax error must not be reported with the "
        "bash-is-missing wording -- the two failure shapes must stay "
        "distinguishable"
    )
