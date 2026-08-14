#!/usr/bin/env python3
"""Canary: agent_sizing_gate.py (Agent tool) and workflow_agent_sizing_gate.py
(Workflow tool) must recognise the SAME model-tier vocabulary.

Why this exists: the two gates used to each define their own local `VALID`
set and drifted -- agent_sizing_gate.py recognised "fable",
workflow_agent_sizing_gate.py did not. Until a recent fix, that drift was
latent (the Workflow gate only checked that a `model:` key was PRESENT,
never its value), so nobody noticed. Once the value check went live, the
drift became a real, observable disagreement: the exact same tier name is
accepted by one gate's Agent tool call and rejected by the other's
Workflow `agent()` call. Both gates now import the vocabulary from
_common.MODEL_TIERS instead of defining it locally (see that constant's
docstring in _common.py) -- this file is the regression test that keeps it
that way.

Deliberately NOT done here: comparing each gate's `VALID` against a
hardcoded list of tier names written in this file. A hardcoded list here
would be a THIRD copy of the vocabulary that can itself drift out of sync
with the other two and go unnoticed -- exactly how the original bug
survived (a `VALID` constant existed in the Workflow gate the whole time,
correctly spelled, just never consulted). Instead this file always derives
"the vocabulary" from the two gates themselves, two independent ways:

  1. STRUCTURAL: import both hook modules directly and read their
     module-level `VALID` set. Confirms the two sets are equal to each
     other AND to `_common.MODEL_TIERS` (so if someone re-locals `VALID`
     in one gate again -- reintroducing a private copy -- this fails even
     if the private copy happens to start out correctly spelled).
  2. BEHAVIORAL: for every tier in the union of both gates' `VALID` (plus
     one synthetic definitely-invalid tier as a positive control), actually
     INVOKE both hooks as subprocesses with that tier and compare whether
     each one recognised it. This is the check that would have caught the
     original bug even if the structural constants had looked identical on
     paper but one gate ignored its own constant (which is precisely what
     happened) -- constants can be defined and then not consulted; only
     exercising the actual gate BEHAVIOR proves the constant is load-bearing.

One legitimate, INTENTIONAL behavioral difference between the two gates has
to be neutralised for the comparison to be meaningful: agent_sizing_gate.py
additionally blocks a frontier tier (opus/fable) as a leaf-spawn anti-pattern
(the "frontier tripwire"), a policy workflow_agent_sizing_gate.py does not
have and must not gain (see that module's docstring: "opus is a normal,
un-blocked tier here"). That tripwire is a RUNG policy on top of
recognition, not a question of whether the tier is recognised at all, so
`_agent_recognized()` below clears it with both leaf-escape sentinels before
checking accept/reject -- isolating "is this tier valid vocabulary" from
"is this tier's rung allowed as a leaf".
"""
import importlib.util
import json
import os
import subprocess
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_HOOK = os.path.join(HOOKS_DIR, "agent_sizing_gate.py")
WORKFLOW_HOOK = os.path.join(HOOKS_DIR, "workflow_agent_sizing_gate.py")

sys.path.insert(0, HOOKS_DIR)
import _common  # noqa: E402


def _load_module(path, name):
    """Import a hook script as a module by path, without running its
    `if __name__ == "__main__":` block, so we can read its module-level
    `VALID` constant directly (the real one, not a re-typed copy)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


agent_mod = _load_module(AGENT_HOOK, "_canary_agent_sizing_gate")
workflow_mod = _load_module(WORKFLOW_HOOK, "_canary_workflow_agent_sizing_gate")


def _run(hook, event):
    proc = subprocess.run(
        [sys.executable, hook], input=json.dumps(event), text=True, capture_output=True
    )
    return proc.returncode, proc.stderr


def _agent_recognized(tier):
    """True iff agent_sizing_gate.py treats `tier` as a recognised model
    tier, with the (gate-specific, intentional) frontier tripwire
    neutralised via both leaf-escape sentinels -- see module docstring."""
    event = {
        "tool_name": "Agent",
        "tool_input": {
            "model": tier,
            "subagent_type": "general-purpose",
            "prompt": "opus-leaf-ok: parity probe / fable-leaf-ok: parity probe",
        },
    }
    rc, _ = _run(AGENT_HOOK, event)
    return rc == 0


def _workflow_recognized(tier):
    """True iff workflow_agent_sizing_gate.py treats `tier` as a recognised
    model tier for a single, fully-formed agent() call site."""
    script = 'agent("do the thing", {model: "%s"});' % tier
    event = {"tool_name": "Workflow", "tool_input": {"script": script}, "cwd": "/tmp"}
    rc, _ = _run(WORKFLOW_HOOK, event)
    return rc == 0


# ---------------------------------------------------------------------------
# 1. Structural: the two gates' effective vocabularies must be equal, and
#    both must equal the shared source of truth.
# ---------------------------------------------------------------------------

def test_gate_valid_sets_are_equal_to_each_other():
    assert agent_mod.VALID == workflow_mod.VALID


def test_gate_valid_sets_derive_from_shared_common_constant():
    assert agent_mod.VALID == _common.MODEL_TIERS
    assert workflow_mod.VALID == _common.MODEL_TIERS


# ---------------------------------------------------------------------------
# 2. Behavioral: actually run both hooks for every tier and compare
#    accept/reject. Derived from the modules' own VALID, not a literal list
#    written in this file -- see module docstring for why.
# ---------------------------------------------------------------------------

_CANDIDATE_TIERS = sorted(agent_mod.VALID | workflow_mod.VALID) + [
    "definitely-not-a-real-model-tier",  # positive control: must be rejected by both
]


def test_both_gates_agree_on_every_candidate_tier():
    disagreements = []
    for tier in _CANDIDATE_TIERS:
        a = _agent_recognized(tier)
        w = _workflow_recognized(tier)
        if a != w:
            disagreements.append((tier, a, w))
    assert not disagreements, (
        "agent_sizing_gate.py and workflow_agent_sizing_gate.py disagree on "
        f"whether these tiers are recognised (tier, agent_recognized, "
        f"workflow_recognized): {disagreements}"
    )


def test_positive_control_rejected_by_both():
    """Sanity check for the behavioral probe itself: an obviously-fake tier
    must be rejected by BOTH gates. If this ever goes green for the wrong
    reason (e.g. the probes always return True), the parity test above
    would pass vacuously -- this pins that the probes can actually detect
    a rejection."""
    assert _agent_recognized("definitely-not-a-real-model-tier") is False
    assert _workflow_recognized("definitely-not-a-real-model-tier") is False


def test_every_real_tier_is_recognized_by_both():
    """Sanity check for the other direction: every tier actually in the
    shared vocabulary must be accepted by both probes. If this ever goes
    green for the wrong reason (e.g. the probes always return False), the
    parity test above would also pass vacuously -- this pins that the
    probes can actually detect an acceptance."""
    for tier in sorted(_common.MODEL_TIERS):
        assert _agent_recognized(tier) is True, tier
        assert _workflow_recognized(tier) is True, tier
