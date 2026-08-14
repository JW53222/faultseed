#!/usr/bin/env python3
"""Regression tests for agent_sizing_gate.py's frontier-leaf tripwire.

Black-box: feed a PreToolUse event (stdin JSON) to the hook and assert exit
code (2 = block, 0 = allow). Pins the fable extension: the hook used to
string-match `"opus"` only for the frontier-leaf tripwire, so a
`model:"fable"` leaf either fell through the recognised-tier check entirely
or was blocked for the wrong reason (unrecognised model) with no escape
hatch. It must now be treated identically to opus -- blocked as a frontier
leaf unless the prompt carries `opus-leaf-ok:`/`fable-leaf-ok:` with a real
reason -- while opus's existing behavior stays unchanged.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_sizing_gate.py")


def _run(model=None, prompt="do the thing", subagent_type="general-purpose"):
    tool_input = {"prompt": prompt, "subagent_type": subagent_type}
    if model is not None:
        tool_input["model"] = model
    ev = json.dumps({"tool_name": "Agent", "tool_input": tool_input})
    proc = subprocess.run(
        [sys.executable, HOOK], input=ev, text=True, capture_output=True
    )
    return proc.returncode, proc.stderr


# --- fable leaf: blocked, with the fable escape available ---
def test_fable_leaf_blocked_without_reason():
    rc, err = _run(model="fable")
    assert rc == 2
    assert "fable" in err.lower()


def test_fable_leaf_blocked_bare_sentinel_no_reason():
    rc, _ = _run(model="fable", prompt="fable-leaf-ok:   ")
    assert rc == 2


def test_fable_leaf_with_fable_reason_passes():
    rc, _ = _run(model="fable", prompt="fable-leaf-ok: single bounded review, no delegation")
    assert rc == 0


def test_fable_leaf_with_opus_reason_also_passes():
    # Either sentinel clears either frontier model per the task spec.
    rc, _ = _run(model="fable", prompt="opus-leaf-ok: single bounded review, no delegation")
    assert rc == 0


# --- opus behavior unchanged ---
def test_opus_leaf_blocked_without_reason():
    rc, err = _run(model="opus")
    assert rc == 2
    assert "opus" in err.lower()


def test_opus_leaf_with_opus_reason_passes():
    rc, _ = _run(model="opus", prompt="opus-leaf-ok: one subtle oppositional review")
    assert rc == 0


def test_opus_leaf_with_fable_reason_also_passes():
    rc, _ = _run(model="opus", prompt="fable-leaf-ok: one subtle oppositional review")
    assert rc == 0


# --- non-frontier tiers unaffected ---
def test_sonnet_leaf_passes():
    rc, _ = _run(model="sonnet")
    assert rc == 0


def test_haiku_leaf_passes():
    rc, _ = _run(model="haiku")
    assert rc == 0


# --- missing / unrecognised model still blocked ---
def test_missing_model_blocked():
    rc, err = _run(model=None)
    assert rc == 2
    assert "does not declare an explicit" in err


def test_unrecognised_model_blocked():
    rc, err = _run(model="claude-3")
    assert rc == 2
    assert "not one of" in err
