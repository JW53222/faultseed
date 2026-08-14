# Honesty Guardrails

A task is done when the actual problem is solved — not when output looks
complete or tests are green. Nine hooks in `.claude/hooks/` enforce the most
load-bearing rules below deterministically at the moment you try to make the
edit; the rest are conventions this document asks you to follow, with no
machine watching. Each rule below says explicitly which case it is — that
distinction matters: a rule you think is enforced when it isn't is worse than
no rule at all. The machine-checkable registry of every guarded shape,
including the exact escape marker and the test that proves it fires, is
`.claude/hooks/PATTERNS.md`.

## Machine-enforced (a hook blocks this)

- **NEVER edit a test to make it pass silently.** No silent rewrite, weaken,
  skip, or xfail. A conditional `@pytest.mark.skipif(...)` (a real
  platform/dep guard) is fine; blanket `skip`/`xfail`, `assert True`, or net
  assertion removal is not. If a test appears wrong, an edit is allowed but
  must carry `# tampering-ok: <reason>` naming the actual code change the
  test now matches — a bare marker, or one fewer marker than assertions
  removed, does not clear the block. (Enforced: `no_test_tampering.py`,
  `PreToolUse` on `Edit`/`Write`/`MultiEdit`, test files only.)
- **NEVER delete or move a test file via the shell to dodge a failure.**
  `rm`/`git rm` of a test path, or `git mv` moving a test out of the suite,
  is blocked. (Enforced: `no_bash_test_deletion.py`, `PreToolUse` on `Bash`.
  Escape: `# delete-tests-ok: <reason>`, reason required.)
- **NEVER mutate an existing test file in place via the shell** (`sed -i`,
  `tee`, a truncating `>`/`>>` redirect, etc.) to route around
  `no_test_tampering.py`'s Edit/Write coverage. Creating a brand-new test
  file this way is fine. (Enforced: `no_bash_test_mutation.py`, `PreToolUse`
  on `Bash`. Escape: `# test-mutate-ok: <reason>`, reason required. Bypassed
  entirely by `GUARDRAILS_INTEGRATOR_ROLE=1` — exactly `"1"`, nothing else;
  `true`/`yes`/any other value leaves the guard active. That strictness is
  the rule for this pack: **a variable that DISABLES a control demands the
  most explicit possible opt-in, while a variable that only enables
  maintenance can be permissive.** The bypass exists because a merge
  integrator legitimately edits and moves tests while merging other people's
  branches.)
- **NEVER swallow an error to get past it.** No bare `except: pass`/`...`,
  no PowerShell `catch {}` or `-ErrorAction SilentlyContinue`/`Ignore`.
  Handle it, re-raise, or let it propagate. A genuinely correct swallow
  (optional-import probe, deliberate degrade-to-default) is audited with
  `# swallow-ok: <reason>` on the `except` line, the body line, or a comment
  line between them — a bare marker does not clear it. (Enforced:
  `no_swallowed_errors.py`, `PreToolUse` on `Edit`/`Write`/`MultiEdit`,
  **scoped to the directories in `docs/audit/audit-scope.yaml`'s
  `engine_dirs`** — it is silently inert on any file outside that list, so
  set `engine_dirs` to your actual source layout before trusting this one.
  Scans a neighborhood around the edit, not just the diff, so you can't
  build around a nearby swallow.)
- **NEVER declare a method only inside `if TYPE_CHECKING:` with no runtime
  `def`.** It type-checks clean but AttributeErrors (or silently takes a
  wrong branch) at runtime — applies per-class, including mixins, no blanket
  exemption. (Enforced: `no_type_checking_stub.py`, same `Edit`/`Write`/
  `MultiEdit` event, same `engine_dirs` scoping caveat as above. Escape:
  `# host-provides: <reason>` or `# type-stub-ok: <reason>`, reason
  required.)
- **NEVER edit `.env`/`.env.*`, `package-lock.json`, anything under a
  `.git/` directory segment, or an existing file under a `migrations/`
  directory segment.** (Enforced: `protect-files.sh`, `PreToolUse` on
  `Edit`/`Write`. No escape — hardcoded blocklist by design; route a
  legitimate change through a normal commit/PR path outside the agent.)
- **A subagent must not report done without the closing report below.**
  (Enforced: `subagent_closing_report.py`, `SubagentStop` — see "Required
  closing report.")
- **An `Agent`/`Workflow` tool spawn must declare a sized `model`.** Missing
  or unrecognized `model`, or `opus`/`fable` without a leaf-escape sentinel
  (`opus-leaf-ok: <reason>` / `fable-leaf-ok: <reason>` in the spawn prompt),
  blocks. (Enforced: `agent_sizing_gate.py` for the `Agent` tool,
  `workflow_agent_sizing_gate.py` for in-script `agent()` calls inside a
  `Workflow` tool — same reason-required escape, plus it validates the
  `model` value against a recognized set once the key is present, not just
  that the key exists.)

### How these guards behave when they cannot read their own input

**Unparseable input blocks. Parsed-but-not-applicable allows.**

The two are opposite in kind and look similar from outside. Malformed JSON,
invalid UTF-8, or unreadable stdin means *the control failed* — it does not
know what it was asked about — and a control that cannot function must not
wave the action through. Whereas an event that parses cleanly and simply
isn't about this guard (`{}`, no `tool_input`, a tool this hook doesn't
police) is normal operation: most guards see events they correctly ignore
all day, and blocking those would make the pack unusable.

This is not a general input sanitizer, and should not grow into one. It
exists only so that "I cannot read my input" stops being reported as
"nothing to check here." (Enforced: `_common.load_event()` blocks on a
read/parse failure and names the cause; `protect-files.sh` already failed
closed on the same condition via `jq`, and the two now agree.)

## Doctrine — not machine-enforced here

Nothing in this tree checks these. Follow them because they're good practice,
not because a hook will stop you.

- **A defect-excusing comment is not a fix.** `# TODO: good enough` / `#
  known issue` is allowed but must be reported in the closing report's
  "known problems not fixed" list. *Partial exception:* `no_swallowed_errors.py`
  does flag these comments — but only as a warning (`GUARDRAILS_STRICT=1` to
  promote to a hard block), and only inside `engine_dirs`. Treat that as a
  nudge, not a backstop.
- **Never hardcode a value to match expected test output.** No hook detects
  this shape.
- **If the genuinely hard part of a task can't be solved, leave it honestly
  failing** with a clear explanation, rather than hiding the hole behind a
  green run.
- **Scope-reduction claims need a code-path receipt.** When you propose to
  *not* implement something because "X already works through existing code
  Y," produce either the literal call chain (file:line at each hop) or a
  pinning test that would go red if Y broke. Never infer reachability from a
  function's name, signature, or docstring alone — a handler registered in a
  plugin registry but never reached at runtime, or a safety check unit-tested
  in isolation but never wired into the real control loop, both look correct
  from the interface and are wrong in exactly this way. No hook checks for
  this; it's a discipline you apply to your own reasoning.
- **Scope discipline.** Change only what the task requires — no unrelated
  refactors, renames, or "improvements." If a fix needs to touch code outside
  the stated task, stop and ask first.

## Required closing report

End every coding task with these two lists (write "none" if empty):

1. **Changed outside the literal request** — anything touched beyond what was
   asked.
2. **Known problems not fixed** — anything noticed but not solved, and why.
   Includes anything you'd normally have papered over.

For a **subagent**, this is machine-enforced: `subagent_closing_report.py`
fires on `SubagentStop` and blocks (exit 2) unless both marker phrases
("Changed outside the literal request", "Known problems not fixed") appear
in the transcript's own recent assistant text, within 2000 characters of
each other. `Explore`/`Plan`-type agents are exempt (their deliverable is
prose, not a diff). For the **top-level session**, there is no equivalent —
this tree ships no `Stop`-event hook, so the requirement is a convention for
you to hold yourself to, not something that will block you from finishing
without it.
