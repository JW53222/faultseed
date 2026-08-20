# Agent sizing

`agent_sizing_gate` and `workflow_agent_sizing_gate` enforce two mechanical
rules: `model` must be set explicitly, and a frontier tier as a leaf must carry
an acknowledgment. Neither can tell you whether the tier you picked is the right
one for the work. This page is the judgment the gates can't make.

It is a convention, not an enforced one. Nothing here blocks. The two gates
above exist because the convention alone did not hold — see "Why a gate at all."

## The coupling: the model implies the rung

The tier you pick *is* a claim about the shape of the work.

- **Haiku / Sonnet → leaf subagent.** Bounded and fully specified: read, edit,
  test, return. The hands.
- **Frontier tier → standalone orchestrator session** running its own
  Haiku/Sonnet leaves. A frontier model earns its rate by judging and
  delegating. It does not read source in order to make edits.
- **Frontier-as-leaf is the anti-pattern cell.** Full frontier rate, no fan-out.
  If your frontier subagent is reading code to edit it, it is mis-sized.

That last cell is what the gate's escape marker is about. It is not forbidden;
it is required to be deliberate.

## The three rungs

1. **Inline** — you do it yourself with Edit/Write/Bash.
2. **Leaf subagent** — a one-shot worker that runs, returns, dies.
3. **Standalone session** — a full peer session you launch and converse with,
   which fans out to its *own* leaves.

**The one-hop wall.** A leaf cannot spawn subagents. Work that needs its own
fan-out cannot be a leaf, regardless of how well specified it is. This is the
single most common reason a correctly-scoped leaf fails halfway.

## Step 1 — measure blast radius before you size

Cross-cutting work mis-reads as small. "Just edit `_common.py`" looks like a
one-file leaf until you grep and find 16 importers. Measure fan-out *first*:

- `grep -rl <symbol>`, or a call-graph query if you have one.
- **Know what your indexer does not index.** If your tool covers `src/` but not
  `docs/` or `frontend/`, it returns clean for the half it never looked at, and
  a clean answer from a tool that did not look is the failure mode this whole
  pack is about. Fall back to `grep -rl` for the uncovered tree.

**Weight fan-out by per-site judgment, not by count.**

- Fan-out ≥ ~5 *where each site needs an independent decision* → rung 3.
- Fan-out ≥ ~5 but *mechanical and identical* (the same rename everywhere) →
  still a leaf, or an inline `sed` sweep.

Promoting a 16-site mechanical rename to a full session burns exactly the cost
this discipline exists to save.

## Step 2 — pick the rung

**Inline (rung 1)** when any of these hold:

- Single-file change under ~100 lines, fully specified
- Doc or comment change, no behavior touched
- One-line guard, log, constant rename, type annotation
- A regex sweep across known files
- Verification in under ~5 tool calls

A subagent costs roughly 50–100k tokens of prelude before its first tool call.
That is dead weight on a trivial fix.

**Leaf subagent (rung 2)** when:

- The work needs more than ~10 tool calls of investigation plus edit
- 3+ files need coordinated changes, *but* fan-out is under ~5 and the change is
  fully specified
- You want it running in parallel with other work
- You need protected context — large outputs that would otherwise pollute your
  own conversation

**Standalone session (rung 3)** when **any** hold:

- Fan-out ≥ ~5 where each site needs independent judgment
- Multi-phase work needing its own subagent fan-out (the one-hop wall)
- **Frontier judgment that drives edits**: architecture, a multi-file refactor
  where the worker decides what stays, moves, or dies, or a cross-cutting risk
  surface (auth, migrations, anything regulated). That judgment belongs to an
  orchestrator that delegates the edits — not to one frontier session grinding
  through files.
- You will converse across turns — revise, redirect — rather than fire and
  forget
- It should carry its own session history and its own hook coverage
- You have 2+ such tracks at once
- **Operationally heavyweight**: a full re-index, a GPU job, a migration apply.
  This forces rung 3 independent of line count.

## The narrow frontier-leaf exception

A frontier leaf is justified only when all three hold:

1. A single bounded judgment that genuinely needs frontier reasoning
2. **No** delegation
3. **No** cross-turn conversation

An oppositional review is the canonical example. Put `opus-leaf-ok: <reason>`
(or `fable-leaf-ok:`) in the prompt — the gate requires it. If any of the three
fail, promote instead.

**Tripwire.** A workspace-setup helper that spins up a worker at a frontier tier
still creates a frontier leaf. Workspace setup is not promotion. If the work is
frontier-sized, launch a standalone session; *it* uses the helper for its own
Haiku/Sonnet leaves.

## Division of labor

- **Orchestrator (frontier):** reads the problem, designs, slices the work,
  dispatches leaves, does a light correctness pass on their diffs, owns the
  heavyweight steps.
- **Leaves (Haiku/Sonnet):** read code, make the specified edit, test, return.
- **Frontier model reading source to write an edit → wrong rung.**

## Cost, and why the default matters

Rates move; the ratio is the point. At the time of writing a frontier tier runs
roughly 2× the next tier down. That multiplier applies to *every* rung-3 spawn,
which is why the sensible default is the cheaper orchestrator and promotion is
opt-in per job. Flipping the default doubles the cost of work that never needed
it.

Reserve the top tier for the longest-horizon, most cross-cutting jobs —
multi-phase migrations, deletion-class work, audit-hardening lanes — where long
autonomy and diff-review judgment compound.

*Caveat worth knowing:* safety classifiers may transparently route some flagged
queries from one frontier model to another. You get a different model's answer,
not a refusal — harmless for most work, but it means "which model answered" is
not fully under your control.

## Why a gate at all

The convention above is not new, and it did not hold on its own. Measured across
one project's transcript history: roughly **1,600 agent spawns, and the sizing
convention was consulted about a dozen times.** A large share of those spawns
carried no explicit `model` at all and silently inherited the parent's — which,
for an orchestrator, means the most expensive tier by default, on work that a
cheaper model would have done.

That is the case for `agent_sizing_gate`: a convention with no auto-trigger is a
suggestion, and the omission is invisible because inheriting a model is not an
error. Nothing fails. You just pay frontier rates for a file rename.

## What this does not tell you

The gates check that a tier was *named* and that a frontier leaf was
*acknowledged*. Neither they nor this page can check that the tier is correct
for the work — that judgment is yours, and no hook in this pack simulates it.
Treat a green gate as "the decision was made on purpose," never as "the decision
was right."
