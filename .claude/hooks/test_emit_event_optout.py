#!/usr/bin/env python3
"""Regression tests: SKIP_HARNESS_TELEMETRY opts out of _common.emit_event().

Public-repo requirement: local-only telemetry (harness_events.jsonl) must
still be disableable, because "you can't turn it off" is a bad trade for a
stranger even when the data never leaves the machine. Pins:

  - the off switch actually suppresses the write
  - the state/ directory is NOT created at all when it is set -- this is the
    assertion that distinguishes a real opt-out from a cosmetic one (a switch
    that still creates an empty dir on disk is not really "off")
  - the default (unset) still writes, unchanged
  - a guard's exit code (block()/allow() verdict) is identical whether the
    switch is on or off -- disabling telemetry must never change a verdict,
    since emit_event() is called FROM block()/allow() for its own logging

Direct unit tests against _common.emit_event() for the first three (same
pattern as test_emit_event.py), plus one subprocess black-box test against a
real hook (no_test_tampering.py) for the verdict-parity check.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOKS_DIR)
import _common  # noqa: E402

TAMPERING_HOOK = os.path.join(HOOKS_DIR, "no_test_tampering.py")


def _fresh_project_dir():
    d = tempfile.mkdtemp(prefix="htelem-optout-test-")
    os.environ["CLAUDE_PROJECT_DIR"] = d
    _common._HARNESS_VERSION = None  # reset the per-process memo between tests
    return d

def _state_dir(project_dir):
    return os.path.join(project_dir, ".claude", "hooks", "state")


def _events_path(project_dir):
    return os.path.join(_state_dir(project_dir), "harness_events.jsonl")


def test_optout_suppresses_the_write():
    d = _fresh_project_dir()
    os.environ["SKIP_HARNESS_TELEMETRY"] = "1"
    try:
        _common.emit_event("hook_fire", source="unit_test", verdict="allow")
        assert not os.path.exists(_events_path(d))
    finally:
        os.environ.pop("SKIP_HARNESS_TELEMETRY", None)
        shutil.rmtree(d, ignore_errors=True)


def test_optout_does_not_create_state_dir_at_all():
    # The assertion that distinguishes a real opt-out from a cosmetic one:
    # not just "no file", but the directory itself must never be created.
    d = _fresh_project_dir()
    os.environ["SKIP_HARNESS_TELEMETRY"] = "1"
    try:
        _common.emit_event("hook_fire", source="unit_test", verdict="block",
                            payload={"message": "x"})
        assert not os.path.exists(_state_dir(d))
        assert not os.path.exists(os.path.join(d, ".claude", "hooks"))
    finally:
        os.environ.pop("SKIP_HARNESS_TELEMETRY", None)
        shutil.rmtree(d, ignore_errors=True)


def test_default_unset_still_writes():
    d = _fresh_project_dir()
    os.environ.pop("SKIP_HARNESS_TELEMETRY", None)
    try:
        _common.emit_event("hook_fire", source="unit_test", verdict="allow")
        assert os.path.exists(_events_path(d))
        with open(_events_path(d), "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["verdict"] == "allow"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_optout_falsy_values_still_write():
    # Matches the pack's established truthiness convention: "0"/"false"/"False"
    # (and "") are all treated as OFF (i.e. telemetry stays ON), same as
    # GUARDRAILS_STRICT / SKIP_HOOK_DISPATCH / agent_role()'s TS-role check.
    for falsy in ("0", "false", "False", ""):
        d = _fresh_project_dir()
        os.environ["SKIP_HARNESS_TELEMETRY"] = falsy
        try:
            _common.emit_event("hook_fire", source="unit_test", verdict="allow")
            assert os.path.exists(_events_path(d)), f"falsy value {falsy!r} should not opt out"
        finally:
            os.environ.pop("SKIP_HARNESS_TELEMETRY", None)
            shutil.rmtree(d, ignore_errors=True)


def _run_tampering_hook(env_extra):
    # A minimal blockable event: an Edit to a test file removing an assertion
    # with no marker -- no_test_tampering.py must block this (rc == 2)
    # regardless of telemetry opt-out state.
    ev = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/tmp/test_probe_optout.py",
            "old_string": "    assert a == 1",
            "new_string": "    pass",
        },
    }
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, TAMPERING_HOOK],
        input=json.dumps(ev), text=True, capture_output=True, env=env,
    )


def test_guard_verdict_identical_with_optout_on_and_off():
    d = tempfile.mkdtemp(prefix="htelem-optout-verdict-")
    try:
        r_off = _run_tampering_hook({"CLAUDE_PROJECT_DIR": d, "SKIP_HARNESS_TELEMETRY": "0"})
        r_on = _run_tampering_hook({"CLAUDE_PROJECT_DIR": d, "SKIP_HARNESS_TELEMETRY": "1"})
        assert r_off.returncode == r_on.returncode == 2, (
            f"expected both to block (rc=2): off={r_off.returncode} on={r_on.returncode}"
        )
        # The block message itself (what the agent sees) must also be identical --
        # only the telemetry side effect may differ.
        assert r_off.stderr == r_on.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
