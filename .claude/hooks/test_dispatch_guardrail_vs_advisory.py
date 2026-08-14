#!/usr/bin/env python3
"""Regression tests for _dispatch.py -- the hook ENTRYPOINT every wired hook
command is actually invoked through (docs/hook-manifest.yaml never entries
_dispatch.py itself; it is the shared boundary settings.json execs, per
README.md).

_dispatch.py is the single point where the whole hook layer can go quietly
dead: a hook that cannot import must never be silently exec'd (fail-open)
unless it is explicitly enumerated as advisory (see _dispatch.py's own
GUARDRAIL-VS-ADVISORY docstring section). This file constructs a broken hook
and asserts _dispatch.py's response for both the guardrail and advisory
classifications.

Black-box throughout: never imports _dispatch.py, only invokes the REAL
`.claude/hooks/_dispatch.py` (this repo's own, unmodified) as a subprocess,
pointed via AUDIT_HARNESS_HOOKS_DIR / CLAUDE_PROJECT_DIR at synthetic
tmp_path fixtures -- so a "broken hook" is a controlled copy, never a
mutation of this repo's real hook files.

Every fail-closed / fail-open assertion below checks BOTH the exit code AND
specific stderr content (the hook name + the injected error marker), not
exit code alone -- a copy that is broken for the WRONG reason (e.g. a
malformed shutil.copytree leaving every file missing) would also exit 2/0
and would look identical to a genuine pass under an exit-code-only check.
Guardrail/advisory tests additionally carry a positive control: the same
setup, minus the injected raise, must exit 0 -- proving the harness under
test (our own copy-and-dispatch scaffolding) works at all.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
REAL_DISPATCH = HOOKS_DIR / "_dispatch.py"

# A benign PreToolUse Edit event that no_test_tampering.py allows immediately
# (is_test_file() is False for a non-test path) -- used whenever we need a
# hook to run to completion without exercising its own body logic.
BENIGN_EVENT = (
    '{"tool_input": {"file_path": "src/not_a_test.py", '
    '"old_string": "x", "new_string": "y"}}'
)


def _copy_working_hooks(dst: Path) -> Path:
    """A full, unbroken copy of every *.py/*.sh hook in this repo's real
    .claude/hooks/ (test_*.py and docs excluded -- irrelevant to dispatch)."""
    dst.mkdir(parents=True, exist_ok=True)
    for name in os.listdir(HOOKS_DIR):
        src = HOOKS_DIR / name
        if not src.is_file():
            continue
        if name.startswith("test_") or name.endswith(".md"):
            continue
        shutil.copy2(src, dst / name)
    return dst


def _inject_import_raise(file_path: Path, marker: str) -> None:
    """Insert a genuine `raise` into a copied module so importing it fails for
    real. NOT `from __future__ import annotations` removal -- confirmed (via
    live probe, recorded in this session's fact sheet) that a missing future
    import does NOT break import on Python 3.10+ (module-level PEP-604 unions
    are legal there), which would be a false-negative "break" on this
    interpreter. A real `raise` breaks import on every interpreter.

    Inserted AFTER any leading `from __future__ import ...` line, not at line
    0 unconditionally: `from __future__ import annotations` must be the
    first statement in a module (Python enforces this as a SyntaxError, not
    merely a convention) -- _common.py carries one, so a naive prepend
    produces a SyntaxError instead of the intended RuntimeError, which is a
    genuine (if different) import failure but not the one the marker
    assertion below is checking for."""
    original = file_path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("from __future__ import"):
            insert_at = i + 1
            break
    lines.insert(insert_at, f"raise RuntimeError({marker!r})\n")
    file_path.write_text("".join(lines), encoding="utf-8")


def _run_dispatch(hook_rel, *, audit_hooks_dir=None, project_dir=None,
                   extra_env=None, stdin=BENIGN_EVENT, timeout=30):
    env = dict(os.environ)
    for k in ("AUDIT_HARNESS_HOOKS_DIR", "SKIP_HOOK_DISPATCH", "CLAUDE_PROJECT_DIR"):
        env.pop(k, None)
    if audit_hooks_dir is not None:
        env["AUDIT_HARNESS_HOOKS_DIR"] = str(audit_hooks_dir)
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(REAL_DISPATCH), hook_rel],
        input=stdin, text=True, capture_output=True, env=env, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# GUARDRAIL fail-closed
# ---------------------------------------------------------------------------

def test_guardrail_import_failure_blocks_and_never_execs(tmp_path):
    marker = "PLANTED_GUARDRAIL_IMPORT_FAILURE_9f3a"
    broken_dir = _copy_working_hooks(tmp_path / "hooks_broken")
    # no_test_tampering.py imports _common -- breaking _common.py breaks
    # every hook that imports it, including this guardrail one.
    _inject_import_raise(broken_dir / "_common.py", marker)

    rc, _out, err = _run_dispatch(
        "no_test_tampering.py",
        audit_hooks_dir=broken_dir,
        project_dir=tmp_path / "proj_broken",
    )

    assert rc == 2, f"guardrail import failure must BLOCK (exit 2), got {rc}: {err}"
    # rc == 2 specifically (not 1) is itself part of the "never exec'd the
    # broken hook" proof: if _dispatch.py had exec'd the broken hook anyway,
    # the hook's own uncaught ImportError would exit 1 (Python's default for
    # an uncaught exception) -- non-blocking, and a different code than the
    # deliberate sys.exit(2) _block_guardrail_import_failure() writes. rc==2
    # is only reachable via the in-process probe catching the failure BEFORE
    # any exec is attempted.
    assert rc != 1
    assert "no_test_tampering.py" in err
    assert "guardrail" in err.lower()
    assert "BLOCKED" in err
    # The captured traceback must name the SPECIFIC injected error, not a
    # generic "something broke" message -- proves the probe surfaced the
    # real cause, not a coincidental block for the wrong reason.
    assert marker in err

    # Positive control: identical dispatch, unbroken copy -- must ALLOW.
    ok_dir = _copy_working_hooks(tmp_path / "hooks_ok")
    rc_ok, _out_ok, err_ok = _run_dispatch(
        "no_test_tampering.py",
        audit_hooks_dir=ok_dir,
        project_dir=tmp_path / "proj_ok",
    )
    assert rc_ok == 0, (
        f"positive control (unbroken copy, same hook) must ALLOW, got {rc_ok}: {err_ok}"
    )


def test_guardrail_missing_hook_file_blocks_naming_resolved_path(tmp_path):
    ok_dir = _copy_working_hooks(tmp_path / "hooks_ok")
    missing_rel = "totally_missing_hook_zzz.py"

    rc, _out, err = _run_dispatch(
        missing_rel,
        audit_hooks_dir=ok_dir,
        project_dir=tmp_path / "proj",
    )

    assert rc == 2
    assert "cannot resolve harness hook" in err
    # The resolved (nonexistent) absolute path must be named, not just the bare
    # filename -- an operator fixing this needs to know WHERE it looked.
    resolved = str(ok_dir / missing_rel)
    assert resolved in err

    # Positive control: same dir, a hook that DOES exist -- must ALLOW.
    rc_ok, _out_ok, err_ok = _run_dispatch(
        "no_test_tampering.py", audit_hooks_dir=ok_dir, project_dir=tmp_path / "proj2",
    )
    assert rc_ok == 0, f"positive control must ALLOW, got {rc_ok}: {err_ok}"


# ---------------------------------------------------------------------------
# Default-to-guardrail polarity: an unlisted hook name is NOT advisory.
#
# Isolated deliberately from the _common.py-breaking recipe above: both
# synthetic files below carry the IDENTICAL raise -- the only variable is
# the hook_rel NAME, which is exactly the thing _is_guardrail() branches on.
# ---------------------------------------------------------------------------

def test_unlisted_hook_name_defaults_to_guardrail_not_advisory(tmp_path):
    marker = "PLANTED_POLARITY_MARKER_c1d2"
    d = tmp_path / "hooks_polarity"
    d.mkdir()
    unknown_name = "brand_new_unrecognized_hook_xyz.py"
    known_advisory_name = "integrator_transcript_compactor.py"  # real _ADVISORY_HOOKS member
    for name in (unknown_name, known_advisory_name):
        (d / name).write_text(f"raise RuntimeError({marker!r})\n", encoding="utf-8")

    rc_unknown, _o1, err_unknown = _run_dispatch(
        unknown_name, audit_hooks_dir=d, project_dir=tmp_path / "proj1",
    )
    rc_known, _o2, err_known = _run_dispatch(
        known_advisory_name, audit_hooks_dir=d, project_dir=tmp_path / "proj2",
    )

    # Same broken content, different hook_rel name -> different verdict.
    # This is the load-bearing safety property: an unrecognized hook_rel
    # defaults to GUARDRAIL (fail closed), not advisory (fail open).
    assert rc_unknown == 2, (
        f"unlisted hook_rel must default to GUARDRAIL (blocked), got {rc_unknown}: {err_unknown}"
    )
    assert unknown_name in err_unknown
    assert marker in err_unknown

    assert rc_known == 0, (
        f"the explicitly-enumerated advisory hook must fail OPEN, got {rc_known}: {err_known}"
    )
    assert marker in err_known


# ---------------------------------------------------------------------------
# ADVISORY fail-open-but-loud
# ---------------------------------------------------------------------------

def test_advisory_import_failure_allows_but_warns_loudly(tmp_path):
    marker = "PLANTED_ADVISORY_IMPORT_FAILURE_7ee1"
    broken_dir = _copy_working_hooks(tmp_path / "hooks_broken")
    # integrator_transcript_compactor.py does NOT import _common.py (confirmed
    # by reading its source -- it has no `from _common import` line), so
    # breaking _common.py alone would not touch it. Break the advisory hook
    # itself directly, matching the fact sheet's live-verified recipe.
    _inject_import_raise(broken_dir / "integrator_transcript_compactor.py", marker)

    rc, _out, err = _run_dispatch(
        "integrator_transcript_compactor.py",
        audit_hooks_dir=broken_dir,
        project_dir=tmp_path / "proj_broken",
        stdin="{}",
    )

    assert rc == 0, f"advisory import failure must fail OPEN (exit 0), got {rc}: {err}"
    # A silently-failed-open advisory hook would ALSO exit 0 -- the exit code
    # alone cannot distinguish "caught and warned" from "broke silently".
    # The stderr assertions below are the actual test.
    assert err.strip() != "", "advisory fail-open must be LOUD, not silent"
    assert "integrator_transcript_compactor.py" in err
    assert "WARNING" in err or "advisory" in err.lower()
    assert marker in err

    # Positive control: identical dispatch, unbroken copy, same trivial
    # stdin -- must ALLOW *and* produce no warning (the hook's own
    # docstring says it exits 0 unconditionally on trivial/no-op input; the
    # broken case above also exits 0, so the warning text is the only thing
    # that actually distinguishes "ran clean" from "caught and warned").
    ok_dir = _copy_working_hooks(tmp_path / "hooks_ok")
    rc_ok, _out_ok, err_ok = _run_dispatch(
        "integrator_transcript_compactor.py",
        audit_hooks_dir=ok_dir,
        project_dir=tmp_path / "proj_ok",
        stdin="{}",
    )
    assert rc_ok == 0
    assert "WARNING" not in err_ok, (
        f"unbroken advisory hook must not warn: {err_ok!r}"
    )


# ---------------------------------------------------------------------------
# SKIP_HOOK_DISPATCH checked FIRST, before any resolution that could itself fail
# ---------------------------------------------------------------------------

def test_skip_hook_dispatch_checked_before_resolution(tmp_path):
    nonexistent_dir = tmp_path / "does_not_exist_at_all"
    assert not nonexistent_dir.exists()

    rc, _out, err = _run_dispatch(
        "irrelevant_hook_name.py",
        audit_hooks_dir=nonexistent_dir,   # would ordinarily -> _block() (exit 2)
        project_dir=tmp_path / "proj",
        extra_env={"SKIP_HOOK_DISPATCH": "1"},
    )
    # If the skip check were NOT checked first, resolve_hooks_dir() would
    # return nonexistent_dir, main() would find the target missing, and
    # _block() would exit 2 -- so rc==0 here is only possible if the skip
    # check genuinely runs before any resolution/existence check.
    assert rc == 0, f"SKIP_HOOK_DISPATCH must short-circuit before resolution, got {rc}: {err}"


# ---------------------------------------------------------------------------
# Hooks-dir resolution precedence: env var wins; co-located default works.
# harness.env's own precedence step is not covered here (out of the brief's
# minimum -- both endpoints of the chain are pinned, which is what actually
# protects against a reordering regression).
# ---------------------------------------------------------------------------

def test_env_var_hooks_dir_wins_over_colocated_default(tmp_path):
    working_dir = _copy_working_hooks(tmp_path / "hooks_via_env")
    # The co-located default candidate deliberately has NO hooks in it --
    # if resolution ignored AUDIT_HARNESS_HOOKS_DIR and fell through to the
    # co-located default, the dispatched hook would be reported missing.
    decoy_project = tmp_path / "proj_decoy"
    (decoy_project / ".claude" / "hooks").mkdir(parents=True)

    rc, _out, err = _run_dispatch(
        "no_test_tampering.py",
        audit_hooks_dir=working_dir,
        project_dir=decoy_project,
    )
    assert rc == 0, (
        f"AUDIT_HARNESS_HOOKS_DIR must take precedence over the co-located "
        f"default, got {rc}: {err}"
    )
    assert "cannot resolve harness hook" not in err


def test_colocated_default_hooks_dir_used_when_no_env_override(tmp_path):
    project = tmp_path / "proj_colocated"
    colocated_hooks = project / ".claude" / "hooks"
    _copy_working_hooks(colocated_hooks)

    rc, _out, err = _run_dispatch(
        "no_test_tampering.py",
        audit_hooks_dir=None,   # deliberately absent -- AUDIT_HARNESS_HOOKS_DIR unset
        project_dir=project,
    )
    assert rc == 0, (
        f"co-located $CLAUDE_PROJECT_DIR/.claude/hooks default must be used "
        f"when AUDIT_HARNESS_HOOKS_DIR is unset, got {rc}: {err}"
    )
    assert "cannot resolve harness hook" not in err


if __name__ == "__main__":
    import inspect
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        params = inspect.signature(fn).parameters
        try:
            if "tmp_path" in params:
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            fails += 1
            print(f"ERROR {fn.__name__}: {e}")
    raise SystemExit(1 if fails else 0)
