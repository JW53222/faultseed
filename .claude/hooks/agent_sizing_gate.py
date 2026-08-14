#!/usr/bin/env python3
"""agent_sizing_gate.py  --  PreToolUse hook on the Agent tool.

MANDATE: every Agent spawn must declare an explicit `model`.

An agent-sizing convention can say "pass model explicitly on every Agent call",
but without an auto-trigger (a PreToolUse hook fired before Agent calls) it's
only a suggestion — in practice spawns routinely omit `model` and silently
inherit the parent, which is the wrong default for most work: a large share
of spawns across real usage carried no explicit model, far more than the
number of times the convention was actually consulted.

This hook makes the rule deterministic: an Agent call without an explicit,
recognised `model` is BLOCKED (exit 2), with the sizing heuristic in the message
so the re-issued call is right-sized.

What it does NOT do: it does not second-guess a model that IS set. Opus is
legitimately needed for ~1-in-8 dispatches, and judging haiku-vs-sonnet-vs-opus
needs context the hook doesn't have. The one mechanical rule it enforces is that
the choice must be CONSCIOUS — i.e. present in the tool input.

Scope: fires only for tool_name == "Agent" (the subagent spawn tool). Workflow's
internal agent() calls do not go through this tool, so they are unaffected.

BLOCKS: an Agent spawn with no recognised `model` field, and `model: "opus"`
(the Opus-leaf anti-pattern — Opus/Fable are meant to run as standalone
orchestrator sessions, never a frontier leaf).
ESCAPE: `opus-leaf-ok: <reason>` in the spawn prompt, for the narrow justified
Opus-leaf exception. Rationale is REQUIRED — a bare `opus-leaf-ok:` with only
whitespace after the colon does not clear the block.
"""

import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import load_event, block, allow, emit_event, MODEL_TIERS, FRONTIER_MODEL_TIERS

# Shared with workflow_agent_sizing_gate.py via _common.py -- see the
# MODEL_TIERS / FRONTIER_MODEL_TIERS docstrings there for why this is
# defined once instead of locally (the two gates drifted before) and for
# the vocabulary-coupling caveat.
VALID = MODEL_TIERS
# Frontier models: model tier and rung are coupled — Opus AND Fable both mean
# "promote to a standalone session", never a leaf. Fable is the newer frontier
# tier and gets the identical tripwire treatment as Opus.
FRONTIER = FRONTIER_MODEL_TIERS
# Either sentinel clears the tripwire for either frontier model — the escape
# is about "this frontier leaf is deliberate", not which specific tier it is.
LEAF_OK_SENTINELS = ("opus-leaf-ok:", "fable-leaf-ok:")

MSG = """BLOCKED: this Agent spawn does not declare an explicit `model`.
Every subagent must be sized — an unset model silently inherits the parent
(Opus or Fable), the wrong default for most work.

Re-issue the Agent call with `model` set to haiku or sonnet (a leaf is never
Opus or Fable — see the frontier note):
  - haiku  : single-file edit, clear pattern, sed-like sweep, docs/config, or a
             fix describable in <5 prescriptive sentences
  - sonnet : 2-3 files, an existing pattern to follow, most non-subtle fixes
  - opus / fable : do NOT spawn as a leaf. Frontier-sized work (subtle
             invariants, architecture, multi-file refactor, fan-out >=5)
             belongs in its own standalone session, not a leaf spawn, so
             the model can review its own diffs and delegate sub-work.
             Narrow exception (one bounded judgment, no edits/delegation/
             conversation) -> add `opus-leaf-ok: <reason>` (or
             `fable-leaf-ok: <reason>`) to the prompt.

While re-issuing, also sanity-check `subagent_type` (a read-only/search
agent type for read-only work) and `isolation` (worktree only for parallel
edits that would otherwise collide)."""


def _frontier_leaf_msg(model):
    title = model.title()
    # "an Opus" / "a Sonnet" -- computed, not hardcoded, because the tier set
    # is user-editable (MODEL_TIERS in _common.py). A wrong article in a block
    # message is the kind of small wrongness that makes a reader trust the
    # rest of the message less.
    article = "an" if title[0].upper() in "AEIOU" else "a"
    # Keep the FIRST physical line a complete clause. It is the line quoted by
    # README.md's worked example, docs/guards/agent_sizing_gate.md and
    # examples/README.md, and examples/12 now asserts those quotes against a
    # real run. Breaking mid-clause read badly in a terminal AND made those
    # three documents disagree with each other about what this hook prints.
    return f"""BLOCKED: Agent(model:"{model}") is {article} {title} leaf — full {title} rate, no fan-out.
The Agent tool only makes leaves; a frontier leaf reads code a
Sonnet could and can't spawn its own subagents, so it serializes work a team
would parallelize.

Two correct moves instead:
  1. PROMOTE (the default): run this as its own standalone {title} session
     instead of a leaf spawn, and have THAT session dispatch Sonnet/Haiku
     leaves for the actual edits. {title} orchestrates and reviews diffs;
     Sonnet/Haiku do the edits.
  2. NARROW EXCEPTION: a single bounded judgment that needs {title} reasoning,
     needs NO delegation, and needs NO cross-turn conversation (e.g. one subtle
     oppositional review). Re-issue with `opus-leaf-ok: <reason>` or
     `fable-leaf-ok: <reason>` in the prompt.

Spinning up a separate workspace just so the {title} leaf has somewhere to
edit IS the tripwire — a scratch workspace is a leaf's tool, not a promotion
mechanism."""


def _has_leaf_escape(prompt):
    """Require a real RATIONALE after the sentinel, not a bare marker —
    matches the swallow-ok / tampering-ok contract (the reason is the
    load-bearing part a reviewer checks). A sentinel with only whitespace
    after the colon does NOT clear the block. Either sentinel counts for
    either frontier model."""
    low = prompt.lower()
    for sentinel in LEAF_OK_SENTINELS:
        idx = low.find(sentinel)
        if idx != -1 and prompt[idx + len(sentinel):].strip() != "":
            return True
    return False


def main():
    event = load_event()
    # Defensive: only police the Agent spawn tool. The matcher already scopes
    # this, but a bad matcher must not let this hook block unrelated tools.
    if event.get("tool_name") != "Agent":
        allow()

    ti = event.get("tool_input", {}) or {}
    model = ti.get("model")

    if isinstance(model, str) and model.strip().lower() in VALID:
        norm = model.strip().lower()
        # Frontier-leaf tripwire: every Agent spawn is a leaf (a standalone
        # session is launched separately, not via this tool), so
        # model:"opus"/"fable" here is a frontier leaf — the anti-pattern
        # cell. Block unless the caller takes the narrow exception explicitly
        # via an `opus-leaf-ok:`/`fable-leaf-ok:` sentinel.
        if norm in FRONTIER:
            prompt = str(ti.get("prompt", "") or "")
            if not _has_leaf_escape(prompt):
                block(_frontier_leaf_msg(norm))
        emit_event(
            "agent_spawn",
            payload={
                "subagent_type": ti.get("subagent_type", ""),
                "model": norm,
                "rung": "leaf",
                "worktree": ti.get("isolation") == "worktree",
            },
        )
        allow()

    if model:  # present but not a recognised tier
        block(
            MSG
            + f"\n\n(Got model={model!r}, which is not one of "
            + f"{sorted(VALID)}.)"
        )
    block(MSG)  # missing / empty


if __name__ == "__main__":
    main()
