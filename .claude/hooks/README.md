# Honesty-guardrail hooks

Deterministic Claude Code hooks that stop a coding agent from faking
progress. The doctrine they enforce lives in
`.claude/rules/honesty-guardrails.md`; per-guard detail (what it blocks, why,
worked examples) lives in `docs/guards/`; the machine-oriented registry of
every guarded shape is `PATTERNS.md`. This file is the orientation page: what
ships, how it's wired, and the contract every hook is written against.

## What's here

Counted directly with `ls .claude/hooks/` — this is a snapshot, not a fact to
pin; it moved twice while writing this file, as other in-flight work landed
test files. Re-run it yourself. At last count: 14 hooks/libs, 2 docs (this
file and `PATTERNS.md`), 13 test files.

```
.claude/hooks/
  _common.py                    shared helpers: diff parsing, role/path scope, telemetry
  _dispatch.py                  entrypoint every wired hook command actually runs through
  protect-files.sh              PreToolUse(Edit|Write): blocks edits to .env/lockfile/.git/migrations
  no_test_tampering.py          PreToolUse(Edit|Write|MultiEdit): blocks test weakening
  no_swallowed_errors.py        PreToolUse(Edit|Write|MultiEdit): blocks bare except:pass/... swallows, engine_dirs-scoped
  no_type_checking_stub.py      PreToolUse(Edit|Write|MultiEdit): blocks TYPE_CHECKING-only method stubs, engine_dirs-scoped
  no_bash_test_deletion.py      PreToolUse(Bash): blocks rm/git rm/git mv of test files
  no_bash_test_mutation.py      PreToolUse(Bash): blocks in-place edits to existing test files
  agent_sizing_gate.py          PreToolUse(Agent): requires a sized model, blocks Opus/Fable-as-leaf
  workflow_agent_sizing_gate.py PreToolUse(Workflow): same tripwire for in-script agent() calls
  subagent_closing_report.py    SubagentStop: requires the two closing-report marker phrases
  integrator_transcript_compactor.py  PreCompact: transcript archive/prune, never blocks
  generate_settings_json.py     builds .claude/settings.json from docs/hook-manifest.yaml — not itself a hook
  check_interpreter_floor.py    preflight CLI: confirm the interpreter meets this repo's >=3.10 floor — not itself a hook
  PATTERNS.md                   registry of every guarded shape: event, block condition, escape, proof
  README.md                     this file
```

Nine of the files above are guards in the sense this pack cares about (they
can return exit 2 and actually do, under a planted-failure test):
`protect-files.sh`, `no_test_tampering.py`, `no_swallowed_errors.py`,
`no_type_checking_stub.py`, `no_bash_test_deletion.py`,
`no_bash_test_mutation.py`, `agent_sizing_gate.py`,
`workflow_agent_sizing_gate.py`, `subagent_closing_report.py`.
`integrator_transcript_compactor.py` ships and is wired but never blocks
(informational only — see its `docs/guards/` page and `PATTERNS.md` if you
need the fail-open detail). `_common.py`/`_dispatch.py`/
`generate_settings_json.py`/`check_interpreter_floor.py` are shared
infrastructure, not hooks a `settings.json` event points at directly.

Per-guard pages (what it blocks, why the shape is worth a gate, a worked
before/after) live at `docs/guards/<hook>.md`, one per guard, plus a
`docs/guards/README.md` index. `ls docs/guards/` to check what's actually
there before assuming a page exists — this directory is also under active
concurrent edit.

## Role + path scope

Two independent axes decide whether a hook fires, both in `_common.py`:

- **Path scope (engine-quality hooks).** `no_swallowed_errors.py` and
  `no_type_checking_stub.py` only police the directories listed in
  `docs/audit/audit-scope.yaml`'s `engine_dirs`, via `is_engine_path()`. They
  go inert (exit 0, no output) outside those dirs — role-independent.
  `engine_dirs` ships as the literal placeholder `["src"]`; if your source
  lives elsewhere, both hooks silently cover zero code until you edit that
  file yourself. A missing or malformed `audit-scope.yaml` fails the other
  direction, loudly: `AuditScopeLoadError` turns into a block (exit 2), not a
  silent default.
- **Role (`agent_role()`).** `no_bash_test_mutation.py` bypasses itself
  entirely when `GUARDRAILS_INTEGRATOR_ROLE` is set to a truthy value (not `""`, `"0"`,
  `"false"`, `"False"`) — "the integrator owns test edits at merge time."
  Every other guard in this tree is role-independent.

`domain_for_path()` in `_common.py` is a reserved seam for a possible future
domain-scoped hook set. It returns `None` unconditionally today — nothing
in this tree calls it for a decision.

## The exit-code contract

Exit code 2 blocks. Every other exit code (0, 1, 127, an uncaught traceback
landing on 1) is silently non-blocking — this is the Claude Code hook
protocol, not a choice this pack makes. `_common.py`'s `block()` writes to
stderr and calls `sys.exit(2)`; `allow()` calls `sys.exit(0)`.

`_dispatch.py` is the entrypoint every wired hook command actually runs
through — the command a generated `settings.json` writes is `python3
_dispatch.py <hook>.py`, not `python3 <hook>.py` directly. Before exec'ing
the real hook, it does an in-process import/syntax probe and classifies what
happens if that probe fails:

- **GUARDRAIL** (the default — every guard listed above, and any hook name
  `_dispatch.py` doesn't recognize) that fails to import is never exec'd:
  `_dispatch.py` blocks (exit 2) itself, naming the hook and the traceback.
- **ADVISORY** (an explicit, five-name allowlist in `_dispatch.py`, of which
  only `integrator_transcript_compactor.py` actually ships here — the other
  four named entries do not exist in this tree) that fails to import exits 0
  — but loudly, with a stderr `WARNING:` and best-effort telemetry, never
  silently.
- A hook file that doesn't resolve on disk at all is also blocked (exit 2),
  naming the resolved path and the env var that fixes it.

This is proven, not asserted: `test_dispatch_guardrail_vs_advisory.py`
plants a real import failure in a copied hooks dir and checks both the
broken and a positive-control unbroken copy in the same test.

## Env knobs

The complete set actually read by a shipped file, by hook:

| Var | Hook | Effect |
|---|---|---|
| `GUARDRAILS_STRICT` | `no_swallowed_errors.py` | `1` promotes defect-excusing comments (`# TODO: good enough`) from warn-only to hard-block. Default off. |
| `GUARDRAILS_SWALLOW_NEIGHBORS` | `no_swallowed_errors.py` | Sibling-function neighborhood-scan window radius. Default `2`. |
| `GUARDRAILS_INTEGRATOR_ROLE` | `no_bash_test_mutation.py` | Any value not in `("", "0", "false", "False")` bypasses the whole hook. |
| `SKIP_SUBAGENT_CLOSING_REPORT` | `subagent_closing_report.py` | `1` disables the hook entirely (session-level, not per-invocation). |
| `BLESSED_REPO` | `subagent_closing_report.py` | Optional; only used for an informational `git diff --stat` annotation, not for the block/allow decision. |
| `SKIP_HOOK_DISPATCH` | `_dispatch.py` | Any value not in `("", "0", "false", "False")` skips dispatch entirely, checked before any hook resolution. |
| `AUDIT_HARNESS_HOOKS_DIR` | `_dispatch.py` | Overrides where the real hooks directory resolves to (precedence over a co-located default). |
| `CLAUDE_PROJECT_DIR` | `_common.py` | Project root for telemetry output path and `is_engine_path()`'s scope check. |
| `CLAUDE_SESSION_ID` | `_common.py` | Tagged onto emitted telemetry events, if set. |

## Dependencies

Python floor is **>=3.10** — `check_interpreter_floor.py` exists to catch a
module-level `X: int | None` annotation without `from __future__ import
annotations`, which raises `TypeError` at import below 3.10. One third-party
import across the whole tree: `PyYAML` (`_common.py`'s `engine_dirs` loader,
lazily imported, and `generate_settings_json.py`, top-level). `pytest` is
needed to run the test suite, not the hooks themselves.

```
pip install pyyaml pytest   # if either is missing
python3 -m pytest .claude/hooks/ -q
```

## Telemetry

Every hook that blocks or allows writes one JSONL line to
`.claude/hooks/state/harness_events.jsonl`. See `docs/telemetry.md` for the
schema and what's recorded.
