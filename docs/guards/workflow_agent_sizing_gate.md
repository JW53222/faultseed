# workflow_agent_sizing_gate

## What it blocks

A `Workflow` tool call whose inline script (or `scriptPath` file) contains an
`agent(...)` call site with no `model:` key, or a `model:` value that isn't
one of `haiku`/`sonnet`/`opus`, or a `model:` value that isn't a static
string literal the hook can verify (a variable, expression, or template
interpolation).

## Why this shape is worth a gate

`agent_sizing_gate.py` (its sibling doc) closes this gap for the `Agent`
tool, but the `Workflow` tool spawns subagents at runtime via its own
`agent(prompt, opts)` calls inside the script body — those spawns never go
through the `Agent` tool's `PreToolUse` hook at all, because the Workflow
runtime drives them directly. A single Workflow script can spawn dozens of
agents in one call; every one of them silently inherits the parent's model
(often Opus, during an ultracode/effort session) unless sized explicitly.
Without this hook, the entire workflow population is exempt from the
sizing mandate the `Agent`-tool sibling enforces — the exact blind spot a
batch of un-sized, expensive spawns would exploit invisibly.

## BLOCKED

```
$ echo '{"tool_name":"Workflow","tool_input":{"script":"agent(\"do a thing\", {subagent_type: \"general-purpose\"});"}}' \
  | python3 workflow_agent_sizing_gate.py
BLOCKED: this Workflow has agent() call site(s) without an explicit `model`.
...
Un-sized / invalid agent() call site(s) (1 total):
  - line 1: agent("do a thing", {subagent_type: "general-purpose"})
$ echo $?
2
```

## ALLOWED

The nearest legitimate thing: the identical call with `model: "sonnet"`
added to the opts object:

```
$ echo '{"tool_name":"Workflow","tool_input":{"script":"agent(\"do a thing\", {subagent_type: \"general-purpose\", model: \"sonnet\"});"}}' \
  | python3 workflow_agent_sizing_gate.py
$ echo $?
0
```

Both commands above were run against this tree this session, along with
three additional probes confirming the current (fixed) state described
below: a bare `// workflow-model-ok` with no reason still blocks (`rc == 2`,
with a distinct note naming which line carries the unreasoned marker); a
recognized-looking but invalid value (`model: "claude-3"`) blocks (`rc ==
2`, naming the bad value); and the reasoned form,
`// workflow-model-ok: deliberate inherit from parent`, allows (`rc == 0`).

## The escape marker

`// workflow-model-ok: <reason>` on the same line as the `agent()` call. As
of this release, the reason is required: `ESCAPE_RE` matches only
`// workflow-model-ok: <non-whitespace text>`, and a separate
`BARE_ESCAPE_RE` detects the no-reason form specifically so the block
message can name it as a *failed* escape attempt ("carries `//
workflow-model-ok` with no reason after the colon") rather than silently
falling through to the generic missing-model message.

## Scope

Universal — fires only for `tool_name == "Workflow"`. No config file, no env
vars. A named/builtin workflow reference (`tool_input.name` with no inline
`script`/`scriptPath`) cannot be statically introspected and is allowed
through unconditionally — the hook's own stance, stated in its source, is
that the agent-sizing hygiene of a named workflow is its author's
responsibility, not something this static parser can verify from the
`Workflow` call site alone.

## How we know it fires

`test_workflow_agent_sizing_gate.py`. Run this session:

```
$ python3 -m pytest .claude/hooks/test_workflow_agent_sizing_gate.py -q
...........                                                             [100%]
11 passed in 0.23s
```

All 11 pass, including the two `_FINDING`-suffixed tests
(`test_unrecognised_model_value_should_be_blocked_FINDING`,
`test_bare_escape_without_reason_should_not_clear_block_FINDING`) that were
filed red against two real defects in this hook and are pinned in this
doc's Known limits below.

## Known limits

**Until this release, this hook had two real defects, now fixed — worth
knowing if you're running an older copy.** The escape marker's regex used
to be a bare presence check (`r"//\s*workflow-model-ok\b"`) with no reason
requirement — unlike every other marker in this pack, a plain
`// workflow-model-ok` with no colon and no text cleared the block. And the
hook used to check only *whether* a `model:` key existed, not whether its
value was a recognized tier — `agent(p, {model: "claude-3"})` sailed
through as "sized" even though `"claude-3"` isn't one of `haiku`/`sonnet`/
`opus`. Both gaps are closed as of the current source (verified live above);
if you're auditing a fork or an older release of this pack, check
`workflow_agent_sizing_gate.py`'s `ESCAPE_RE` and `_find_agent_calls`'
status logic directly rather than trusting this description without
re-verifying against the copy you actually have.

What the hook still cannot do, by design, not by oversight: it is a static
parser over the script's *text*, not a JS interpreter. It cannot resolve
`agent(prompt, opts)` where `opts` is a variable built elsewhere in the
script, and it cannot resolve a `model:` value that isn't a plain quoted
string literal (a variable, a member expression, a function call, a
template literal with `${}` interpolation). Both cases are treated as
unverifiable and BLOCKED rather than trusted — a safe-default choice stated
directly in the source, but it means a legitimately-computed `model` value
(e.g. `model: pickModel(taskSize)`) will always need the
`// workflow-model-ok:` escape, since the hook has no way to evaluate what
`pickModel` returns.
