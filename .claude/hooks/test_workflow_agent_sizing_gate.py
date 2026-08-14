#!/usr/bin/env python3
"""Regression tests for workflow_agent_sizing_gate.py -- the Workflow-tool
sibling of agent_sizing_gate.py (Agent-tool). Modelled on
test_agent_sizing_gate.py: black-box, feed a PreToolUse event (stdin JSON)
to the hook and assert exit code (2 = block via _common.block(), 0 = allow
via _common.allow() -- see _common.py's block()/allow() docstrings).

STRUCTURAL DIFFERENCE FROM THE SIBLING: agent_sizing_gate.py polices ONE
Agent-tool call per event and has a frontier-leaf tripwire (opus/fable are
blocked leaves needing an `opus-leaf-ok:`/`fable-leaf-ok:` escape).
workflow_agent_sizing_gate.py instead statically parses a whole Workflow
script for `agent(...)` call sites and only requires each one to declare
SOME recognised model tier -- opus is a normal, un-blocked tier here (no
frontier-leaf concept), and the escape (`// workflow-model-ok: <reason>`)
covers a missing model, not a frontier model. So the sibling's
fable/opus-frontier-tripwire tests (test_fable_leaf_*, test_opus_leaf_*)
have NO analogue in this gate -- see the closing report for the full
case-by-case mapping.

TWO OF THESE TESTS FOUND REAL BUGS, and that history is kept here because it
is the doctrine working rather than trivia. When this file was written, the
gate's own docstring and block message promised two things it did not do:

  (a) validating the *value* of `model:` against the recognised tier set --
      the set was defined at module scope and never referenced anywhere, so
      `{model: "claude-3"}` sailed through as correctly sized; and
  (b) requiring a non-empty `<reason>` after `// workflow-model-ok:` -- the
      regex matched the bare keyword, so a marker carrying no justification
      cleared the block, unlike every sibling marker in this pack.

Both were confirmed by manual invocation. These tests assert the DOCUMENTED,
correct behavior and were deliberately left FAILING rather than weakened to
match the gate's actual buggy behavior. The gate was then fixed to match its
own documentation, and both went green on their own merits. They are
ordinary regression tests now: the gate cannot quietly lose either property
again without one of them going red.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflow_agent_sizing_gate.py")


def _run(script=None, tool_input=None, tool_name="Workflow", cwd="/tmp"):
    if tool_input is None:
        tool_input = {"script": script}
    ev = json.dumps({"tool_name": tool_name, "tool_input": tool_input, "cwd": cwd})
    proc = subprocess.run(
        [sys.executable, HOOK], input=ev, text=True, capture_output=True
    )
    return proc.returncode, proc.stderr


# --- the planted failure: a Workflow script with an un-sized agent() call ---
def test_missing_model_blocked():
    rc, err = _run(script='agent("do the thing", {subagent_type: "general-purpose"});')
    assert rc == 2
    assert "without an explicit" in err
    assert "line 1" in err


# --- the near-miss: legitimate, fully-sized calls must be ALLOWED ---
def test_sonnet_declared_allowed():
    rc, _ = _run(script='agent("do the thing", {model: "sonnet"});')
    assert rc == 0


def test_haiku_declared_allowed():
    rc, _ = _run(script='agent("do the thing", {model: "haiku"});')
    assert rc == 0


# --- opus is a NORMAL valid tier here (no frontier-leaf tripwire in this
# gate, unlike the Agent-tool sibling where model:"opus" is blocked) ---
def test_opus_declared_allowed_no_frontier_tripwire():
    rc, _ = _run(script='agent("do the thing", {model: "opus"});')
    assert rc == 0


# --- mixed multi-call-site script: only the un-sized site should be
# reported, by its own line number, and the sized siblings must not trip
# the block on their own ---
def test_multi_call_one_missing_reports_correct_line():
    script = (
        'agent("first", {model: "haiku"});\n'
        'agent("second", {subagent_type: "gp"});\n'
        'agent("third", {model: "sonnet"});\n'
    )
    rc, err = _run(script=script)
    assert rc == 2
    assert "line 2" in err
    assert "(1 total)" in err
    # the sized call sites must not themselves appear in the offender list
    assert 'agent("first"' not in err
    assert 'agent("third"' not in err


def test_all_sites_sized_allowed():
    script = (
        'agent("first", {model: "haiku"});\n'
        'agent("second", {model: "sonnet"});\n'
        'agent("third", {model: "opus"});\n'
    )
    rc, _ = _run(script=script)
    assert rc == 0


# --- escape hatch: a missing model WITH a real reason must clear the block ---
def test_escape_with_reason_allows_missing_model():
    rc, _ = _run(
        script='agent("do the thing", {subagent_type: "gp"}); '
        "// workflow-model-ok: deliberate inherit from parent for this probe"
    )
    assert rc == 0


# --- scope: this hook only polices the Workflow tool ---
def test_non_workflow_tool_passthrough_allowed():
    rc, _ = _run(
        tool_name="Edit",
        tool_input={"file_path": "/tmp/whatever.py", "old_string": "a", "new_string": "b"},
    )
    assert rc == 0


# --- named/builtin workflow reference: no script to statically inspect,
# so the documented behavior is to allow rather than over-block ---
def test_named_workflow_without_script_allowed():
    rc, _ = _run(tool_input={"name": "some-builtin-workflow"})
    assert rc == 0


# =============================================================================
# The two below each pinned a real bug in the gate. Both assert the behavior
# the gate's own docstring and block message always promised, and both were
# left failing until the gate was fixed to match its documentation. They are
# regression tests now. If either goes red again, the gate has lost a
# property it claims to have -- fix the gate, not the test.
# =============================================================================

def test_unrecognised_model_value_is_blocked():
    """THE BUG THIS PINS (fixed): the recognised-tier set was defined at
    module scope and the block message told users to set `model:` to one of
    its values -- but the set was never referenced anywhere else in the file.
    `_find_agent_calls()` checked only for the PRESENCE of a `model:` key
    (`has_model = bool(re.search(r"\\bmodel\\s*:", opts_region))`), never
    that its value was a recognised tier, so `agent(p, {model: "claude-3"})`
    sailed through as correctly sized. Observed rc was 0. The gate now
    validates the value and this is rc 2.

    A constant that is defined and then never consulted is the shape worth
    remembering here: nothing about the source reads as broken, and only
    exercising the gate's behavior reveals it."""
    rc, _ = _run(script='agent("do the thing", {model: "claude-3"});')
    assert rc == 2


def test_bare_escape_without_reason_does_not_clear_block():
    """THE BUG THIS PINS (fixed): the gate's docstring documented the escape
    as `// workflow-model-ok: <reason>` with a real reason required, matching
    the sibling `agent_sizing_gate.py`'s `_has_leaf_escape`, which rejects a
    sentinel carrying nothing but whitespace after the colon. But
    `ESCAPE_RE` was `r"//\\s*workflow-model-ok\\b"` -- the bare keyword, no
    colon and no reason required. A marker with zero justification cleared
    the block. Observed rc was 0. It is rc 2 now.

    This was the only escape marker in the pack that was not reason-gated,
    which is why it is worth a regression test rather than a code comment: a
    self-grantable escape hatch silently converts a guard into a formality."""
    rc, _ = _run(
        script='agent("do the thing", {subagent_type: "gp"}); // workflow-model-ok'
    )
    assert rc == 2


# =============================================================================
# GAP: `model:` present but not a static string literal -- the "nonliteral"
# branch (_find_agent_calls's third status, alongside "missing"/"invalid").
# The module docstring documents this as a deliberate design decision (see
# "Limitations": a variable, member expression, function call, ternary, or
# `${}`-interpolated template can't be checked against VALID, so it is
# "treated as unverifiable, not trusted" and BLOCKED, same as a missing
# model -- not silently allowed the way a merely-unrecognized value's
# neighbor might suggest). Before these tests nothing exercised this branch
# at all: a mutation pass confirmed the whole `status, model_value =
# "nonliteral", None` assignment (both the plain-non-literal case and the
# `"${" in raw` template-interpolation case) could be deleted -- collapsing
# every nonliteral into whatever the `lit_match is None` fallthrough left
# `status` as -- with the full 11/11 suite and the example staying green.
#
# The three tests below assert on the DISTINGUISHING MESSAGE text, not just
# exit code, because "missing", "invalid", and "nonliteral" are three
# different verdicts that all block (rc 2) -- asserting only rc could not
# tell a mutant that merges "nonliteral" into "invalid" (or vice versa) from
# correct behavior.
# =============================================================================

def test_recognized_literal_model_allowed():
    """Boundary case 1 of 3: a plain quoted string literal in the
    recognised tier set is the normal, fully-verifiable case -- allowed."""
    rc, _ = _run(script='agent("do the thing", {model: "sonnet"});')
    assert rc == 0


def test_unrecognized_literal_model_blocked_as_invalid_not_nonliteral():
    """Boundary case 2 of 3: `model:` IS a static string literal, just not
    one of the recognised tiers -- this is the "invalid" verdict, distinct
    from "nonliteral" (which is reserved for values that cannot be resolved
    statically at all). Assert on the "invalid" wording specifically so a
    mutant that mislabels this as "nonliteral" (or vice versa) goes red."""
    rc, err = _run(script='agent("do the thing", {model: "claude-3"});')
    assert rc == 2
    assert "is not one of" in err
    assert "cannot verify statically" not in err


def test_variable_model_value_blocked_as_nonliteral_unverifiable():
    """Boundary case 3 of 3: `model:` is a bare identifier (a variable) --
    not a string literal at all, so its value cannot be resolved by static
    parsing. Per the module docstring this is deliberately BLOCKED as
    unverifiable rather than trusted. Assert the distinguishing
    "cannot verify statically" message (not just rc 2) so this cannot be
    confused with "missing" or "invalid" in the block output."""
    rc, err = _run(script="var m = 'sonnet'; agent(\"do the thing\", {model: m});")
    assert rc == 2
    assert "cannot verify statically" in err
    assert "line 1" in err


def test_member_expression_model_value_blocked_as_nonliteral():
    """Same "nonliteral" verdict for a member-expression value (e.g. reading
    off a config object) -- another shape from the docstring's list
    (variable, member expression, function call, ternary, template)."""
    rc, err = _run(
        script='agent("do the thing", {model: config.defaultModel});'
    )
    assert rc == 2
    assert "cannot verify statically" in err


def test_function_call_model_value_blocked_as_nonliteral():
    """Same "nonliteral" verdict for a function-call value."""
    rc, err = _run(
        script='agent("do the thing", {model: pickModel()});'
    )
    assert rc == 2
    assert "cannot verify statically" in err


def test_template_literal_interpolation_model_value_blocked_as_nonliteral():
    """A `${}`-interpolated template literal is syntactically a string
    literal (matches `_MODEL_LITERAL_RE`'s backtick alternative) but its
    VALUE can't be resolved without evaluating JS -- the module docstring
    calls this out as needing "the same treatment as 'nonliteral'"
    (`_find_agent_calls`'s `"${" in raw` branch). This is the one nonliteral
    sub-case that passes the literal-syntax check first before being
    reclassified, so it is worth its own test distinct from the bare-
    variable case above."""
    rc, err = _run(
        script='agent("do the thing", {model: `${tier}`});'
    )
    assert rc == 2
    assert "cannot verify statically" in err


def test_plain_template_literal_without_interpolation_is_a_normal_literal():
    """Near-miss for the template-interpolation case directly above: a
    backtick string with NO `${}` inside it is a fully static literal (its
    raw text is known), so it is checked against VALID exactly like a
    single/double-quoted string -- "opus" is a recognised tier, so this
    allows, distinguishing "nonliteral because backtick" (wrong) from
    "nonliteral only when interpolated" (the documented, correct rule)."""
    rc, _ = _run(script='agent("do the thing", {model: `opus`});')
    assert rc == 0


def test_nonliteral_with_reasoned_escape_allowed():
    """The reasoned escape clears a nonliteral verdict the same way it
    clears "missing" -- the escape check happens after status
    classification and overrides any non-"ok" status uniformly."""
    rc, _ = _run(
        script="var m = pickModel(); agent(\"do the thing\", {model: m}); "
        "// workflow-model-ok: model resolved at runtime from a vetted allowlist"
    )
    assert rc == 0
