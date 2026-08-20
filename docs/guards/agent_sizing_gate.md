# agent_sizing_gate

## What it blocks

An `Agent` tool call with no recognized `model` field, or with `model` set
to a frontier tier (`opus`/`fable`) without an explicit acknowledgment that
running it as a leaf subagent is deliberate.

## Why this shape is worth a gate

An unset `model` silently inherits whatever the parent session is running —
often Opus, the most expensive tier — for work that a cheaper model would
have handled identically. The gate's own docstring cites the concrete
motivating measurement: across roughly 1600 spawns in this project's
transcript history, the model-sizing convention was actually consulted only
about a dozen times, and a large share of spawns carried no explicit model
at all. That's not a one-off mistake, it's a default silently winning by
omission on nearly every dispatch. The frontier-leaf half of the rule exists
because a subagent spawned via the `Agent` tool is always a leaf — it cannot
itself fan out to further subagents — so paying full Opus/Fable rate for
work that can't parallelize is close to strictly worse than either sizing it
down or promoting it to a real standalone orchestrator session that *can*
fan out.

## BLOCKED

```
$ echo '{"tool_name":"Agent","tool_input":{"prompt":"do the thing","subagent_type":"general-purpose","model":"opus"}}' \
  | python3 agent_sizing_gate.py
BLOCKED: Agent(model:"opus") is an Opus leaf — full Opus rate, no fan-out.
no fan-out. ...
$ echo $?
2
```

## ALLOWED

The nearest legitimate thing: the identical spawn, with the narrow-exception
sentinel and a real reason in the prompt:

```
$ echo '{"tool_name":"Agent","tool_input":{"prompt":"opus-leaf-ok: one subtle oppositional review","subagent_type":"general-purpose","model":"opus"}}' \
  | python3 agent_sizing_gate.py
$ echo $?
0
```

Both commands above were run against this tree this session. A separate,
unrelated near-miss: `model:"sonnet"` or `model:"haiku"` is never flagged at
all — the frontier tripwire applies only to `opus`/`fable`.

## The escape marker

`opus-leaf-ok: <reason>` or `fable-leaf-ok: <reason>`, anywhere in the spawn
prompt (case-insensitive substring search, not line-anchored the way the
Edit-side markers are — the check scans the whole prompt string). Either
sentinel clears either frontier model; the escape is about "this frontier
leaf is deliberate", not about naming the exact tier. A sentinel with only
whitespace after the colon does not clear the block — `_has_leaf_escape`
explicitly checks `.strip() != ""` on the text following it.

## Scope

Universal — fires on every `Agent` tool call, no config file, no env vars.
The hook defensively re-checks `tool_name == "Agent"` itself even though the
`PreToolUse` matcher already scopes it to that tool, so a misconfigured
matcher elsewhere cannot make this hook block an unrelated tool call. On
`allow()`, it emits an `agent_spawn` telemetry event recording the chosen
model and whether the spawn used `isolation: "worktree"`.

## How we know it fires

`test_agent_sizing_gate.py`, 11 test functions. Run this session, from the
repo root:

```
$ python3 -m pytest .claude/hooks/test_agent_sizing_gate.py -q
...........                                                             [100%]
11 passed in 0.21s
```

`test_fable_leaf_blocked_without_reason` asserts `rc == 2` and `"fable" in
err.lower()` for an unescaped `model="fable"` spawn — pinning that Fable
gets the identical frontier treatment as Opus, not a separate weaker check.
`test_missing_model_blocked` asserts `rc == 2` and `"does not declare an
explicit" in err` for a spawn with no `model` key at all.
`test_fable_leaf_blocked_bare_sentinel_no_reason` plants
`fable-leaf-ok:   ` (whitespace only) and confirms the block still fires —
pinning the reason-required behavior this hook shares with every other
marker in the pack except its `Workflow`-tool sibling (see that guard's own
page).

## Known limits

The hook validates only that `model` is one of the four recognized string
values (`haiku`, `sonnet`, `opus`, `fable`) — it has no way to judge whether
the *chosen* tier is actually appropriate for the work described in the
prompt. A spawn with `model:"haiku"` on a task that genuinely needs Opus
reasoning passes this hook cleanly; the gate enforces that a choice was
made, not that the choice was right. The escape-marker check is a substring
search over the whole prompt string rather than line-anchored like the
Edit-side markers, so a sentinel embedded anywhere in a long prompt — even
somewhere that reads oddly out of context — still clears the block.

## The judgment this gate can't make

This gate checks that a tier was named and that a frontier leaf was
deliberate. Deciding *which* tier the work actually warrants — and whether
it should be a leaf at all — is a separate discipline:
[Agent sizing](../agent-sizing.md).
