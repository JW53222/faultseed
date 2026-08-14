# examples/

Eleven scripts. Each one plants a real violation, runs the actual (unmodified)
guard against it exactly as Claude Code's hook protocol would invoke it, and
shows you the guard block it. Each one also plants a legitimate near-miss and
shows the same guard let it through — so you see the guard discriminate, not
just refuse everything.

Run the whole set:

```
./run_all.sh
```

or one at a time:

```
./03_no_swallowed_errors/run.sh
```

Every script cleans up its own temp fixtures (`mktemp -d` + `trap ... EXIT`)
and touches nothing outside them. Nothing here writes to this repo.

## What "block" and "allow" mean

Exit code 2 blocks. Every other exit code (0, 1, anything) silently allows.
That's the Claude Code hook protocol, not this pack's choice — see
`.claude/hooks/_common.py`'s `block()` docstring. A hook that crashes or
exits 1 for "found a problem" enforces nothing while looking installed. Every
script below prints the observed exit code next to what it means, not just
"PASS"/"FAIL".

## Which example demonstrates which guard

| # | Directory | Guard | What you'll see it catch |
|---|-----------|-------|---------------------------|
| 01 | `01_protect_files/` | `protect-files.sh` | Edit to `.env` blocked; `config.envoy.yaml` (a mid-string `.env` substring, not the dotenv shape) allowed |
| 02 | `02_no_test_tampering/` | `no_test_tampering.py` | An assertion silently deleted, no marker, blocked; the same removal with a justified `# tampering-ok:` reason allowed |
| 03 | `03_no_swallowed_errors/` | `no_swallowed_errors.py` | A bare `except Exception: pass` blocked inside `engine_dirs`; the same code with `# swallow-ok: <reason>` allowed |
| 04 | `04_no_type_checking_stub/` | `no_type_checking_stub.py` | A method defined only under `if TYPE_CHECKING:` (no runtime `def`) blocked; the same stub with `# host-provides: <reason>` allowed |
| 05 | `05_no_bash_test_deletion/` | `no_bash_test_deletion.py` | `rm tests/test_foo.py` blocked; `rm scratch.txt` (not a test path) allowed |
| 06 | `06_no_bash_test_mutation/` | `no_bash_test_mutation.py` | `sed -i` on an existing test file blocked; the same command on a non-test file allowed |
| 07 | `07_agent_sizing_gate/` | `agent_sizing_gate.py` | An `Agent(model="opus", ...)` leaf with no escape sentinel blocked; the same call with `opus-leaf-ok: <reason>` allowed; a missing `model` field blocked outright |
| 08 | `08_workflow_agent_sizing_gate/` | `workflow_agent_sizing_gate.py` | A `Workflow` script with an un-sized `agent()` call blocked; `model: "sonnet"` declared allowed; a *bare* `// workflow-model-ok` (no reason) blocked; the same marker *with* a reason allowed |
| 09 | `09_subagent_closing_report/` | `subagent_closing_report.py` | A subagent transcript missing both required closing-report markers blocked; the identical markerless transcript allowed when `agent_type` is an exempt role (`Explore`) |
| 10 | `10_scope_gate_wrong_directory/` | scope config, not a guard | The *same* swallowed-error bug from #03, once inside `engine_dirs` (blocked) and once outside it (silently allowed) — the sharpest install footgun in this pack |
| 11 | `11_missing_dependency/` | `protect-files.sh`, and the class of bug it belongs to | A real, previously-shipped fail-open: with `jq` missing or broken, the *original* guard silently PERMITTED a write to `.env`. Reproduces the old behavior live against a pinned pre-fix copy of the hook, then shows the fixed guard failing closed instead |

Examples 10 and 11 aren't guard demos in the same sense as 01–09 — they're
warnings, and they're the same failure class told two ways. Every other
example perturbs the guard's **input** (the JSON event). These two perturb
its **environment**: #10 is a missing/misconfigured *config file*
(`engine_dirs` not covering your actual source layout); #11 is a missing or
broken *binary dependency* (`jq`, which `protect-files.sh` shells out to).
Both can produce exit 0 — "allowed" — for a reason that has nothing to do
with the code being fine: the guard never ran the check at all. That axis
(missing binary, missing config, failed import) is easy to leave untested,
because a manual verification pass naturally exercises the happy path — the
binary is on your PATH and the config is set up right, because you're the
one who set the machine up. Run 10 and 11 first if you're installing this
pack fresh, before you trust anything else in this directory.

## Run it yourself: real output

This is `./run_all.sh`'s actual output, pasted, not reconstructed. Re-run it
yourself — the header of every guard message that changes between
invocations (the fixture's own `mktemp -d` path) is the only thing that will
differ.

```
===================================================================
example: 01_protect_files
===================================================================

--- protect-files.sh -- an agent tries to Edit a .env file ---
BLOCKED (exit 2) -- Edit targeting .env (a real secrets file shape)
  guard said: Blocked: /tmp/tmp.yVTlpEUrdZ/.env matches protected pattern '.env'

--- protect-files.sh -- the near-miss: a filename that merely CONTAINS 'env' ---
ALLOWED (exit 0) -- config.envoy.yaml -- '.env' as a mid-string substring, not the dotenv basename shape. This is the 2026-08-08 fix: an older cut of this hook blocked this file too.

2 check(s) ran in this example.
-> 01_protect_files: OK (2 check(s))

===================================================================
example: 02_no_test_tampering
===================================================================

--- no_test_tampering.py -- an assertion is deleted with no marker ---
BLOCKED (exit 2) -- 'assert a == 1' replaced by a bare 'pass', no marker -- an assertion just silently disappeared
  guard said: BLOCKED: this edit weakens a test instead of fixing the code under test.

--- no_test_tampering.py -- the near-miss: same removal, with a justified marker ---
ALLOWED (exit 0) -- same removal, but carries a non-empty '# tampering-ok: <reason>' -- a BARE marker with no reason would NOT clear this (try it: drop the ': justified...' text and re-run)

2 check(s) ran in this example.
-> 02_no_test_tampering: OK (2 check(s))

===================================================================
example: 03_no_swallowed_errors
===================================================================

--- no_swallowed_errors.py -- a bare 'except: pass' inside src/ (in engine_dirs) ---
BLOCKED (exit 2) -- except Exception: pass, no marker, path is under 'src/' which IS in engine_dirs
  guard said: BLOCKED: this edit hides a problem instead of solving it.

--- no_swallowed_errors.py -- the near-miss: same file, marked as a deliberate degrade ---
ALLOWED (exit 0) -- identical except-block, but 'pass  # swallow-ok: intentional degrade' on the body line

2 check(s) ran in this example.
-> 03_no_swallowed_errors: OK (2 check(s))

===================================================================
example: 04_no_type_checking_stub
===================================================================

--- no_type_checking_stub.py -- 'bar' is defined ONLY under TYPE_CHECKING ---
BLOCKED (exit 2) -- class Foo.bar exists only inside 'if TYPE_CHECKING:', no runtime def, no marker
  guard said: BLOCKED: this edit declares a method/function ONLY inside an `if TYPE_CHECKING:` block with no runtime implementation.

--- no_type_checking_stub.py -- the near-miss: a real host-contract marker ---
ALLOWED (exit 0) -- same stub, but '# host-provides: Host defines this at runtime' documents which host class actually supplies it

2 check(s) ran in this example.
-> 04_no_type_checking_stub: OK (2 check(s))

===================================================================
example: 05_no_bash_test_deletion
===================================================================

--- no_bash_test_deletion.py -- 'rm tests/test_foo.py', no marker ---
BLOCKED (exit 2) -- an agent shelling out to rm a test file bypasses the Edit-side tamper guard entirely
  guard said: BLOCKED: this Bash command deletes or moves test files out of the suite.

--- no_bash_test_deletion.py -- the near-miss: deleting a NON-test file ---
ALLOWED (exit 0) -- scratch.txt isn't a test path at all -- the marker on this line is a no-op, there was nothing to block

2 check(s) ran in this example.
-> 05_no_bash_test_deletion: OK (2 check(s))

===================================================================
example: 06_no_bash_test_mutation
===================================================================

--- no_bash_test_mutation.py -- 'sed -i' on an EXISTING test file, no marker ---
BLOCKED (exit 2) -- in-place edit of tests/test_foo.py, which exists on disk relative to cwd -- bypasses no_test_tampering.py's Edit-side view
  guard said: BLOCKED: this Bash command mutates an EXISTING test file in place.

--- no_bash_test_mutation.py -- the near-miss: same command, a non-test file ---
ALLOWED (exit 0) -- notes.txt isn't a test file -- nothing to block, the bare marker here is irrelevant either way

2 check(s) ran in this example.
-> 06_no_bash_test_mutation: OK (2 check(s))

===================================================================
example: 07_agent_sizing_gate
===================================================================

--- agent_sizing_gate.py -- Agent(model="opus", ...) with no escape sentinel ---
BLOCKED (exit 2) -- a frontier model spawned as a leaf -- full frontier cost, no fan-out, serializes work a team would parallelize
  guard said: BLOCKED: Agent(model:"opus") is a Opus leaf — full Opus rate,

--- agent_sizing_gate.py -- the near-miss: a bounded, justified frontier leaf ---
ALLOWED (exit 0) -- same model, but the prompt carries 'opus-leaf-ok: <reason>' -- a deliberate, narrow exception, not silence

--- agent_sizing_gate.py -- also blocked: no model declared at all ---
BLOCKED (exit 2) -- 'model' field missing entirely -- every dispatch must declare an explicit tier
  guard said: BLOCKED: this Agent spawn does not declare an explicit `model`.

3 check(s) ran in this example.
-> 07_agent_sizing_gate: OK (3 check(s))

===================================================================
example: 08_workflow_agent_sizing_gate
===================================================================

--- workflow_agent_sizing_gate.py -- agent() call with no model: at all ---
BLOCKED (exit 2) -- un-sized agent() call site -- would silently inherit the parent's model (Opus during an ultracode session)
  guard said: BLOCKED: this Workflow has agent() call site(s) without an explicit `model`.

--- workflow_agent_sizing_gate.py -- near-miss: model: "sonnet" declared ---
ALLOWED (exit 0) -- same call, model: "sonnet" present -- a normal, explicitly sized dispatch

--- workflow_agent_sizing_gate.py -- a bare escape marker with no reason ---
BLOCKED (exit 2) -- '// workflow-model-ok' with no ':' and no reason text -- still blocked (verified live: this used to silently clear the block with zero justification; that gap is closed as of this run, see the note below)
  guard said: BLOCKED: this Workflow has agent() call site(s) without an explicit `model`.

--- workflow_agent_sizing_gate.py -- the real near-miss: escape marker WITH a reason ---
ALLOWED (exit 0) -- same call, marker now carries a real reason after the colon

4 check(s) ran in this example.
-> 08_workflow_agent_sizing_gate: OK (4 check(s))

===================================================================
example: 09_subagent_closing_report
===================================================================

--- subagent_closing_report.py -- transcript has neither required marker ---
BLOCKED (exit 2) -- a 'looks fine, I checked' closing message with neither 'Changed outside the literal request:' nor 'Known problems not fixed:'
  guard said: BLOCKED: your closing report is missing required honesty-guardrail lines.

--- subagent_closing_report.py -- the near-miss: an EXEMPT agent type, same transcript ---
ALLOWED (exit 0) -- identical markerless transcript, but agent_type is "Explore" (read-only/research) -- the exemption fires before the transcript is even read

2 check(s) ran in this example.
-> 09_subagent_closing_report: OK (2 check(s))

===================================================================
example: 10_scope_gate_wrong_directory
===================================================================
Currently configured engine_dirs (docs/audit/audit-scope.yaml): includes 'src'
Directory used for the out-of-scope half below: 'docs' (confirmed NOT in engine_dirs)

--- in scope: src/foo.py, same swallow bug as example 03 ---
BLOCKED (exit 2) -- identical bug, path is inside engine_dirs -- caught
  guard said: BLOCKED: this edit hides a problem instead of solving it.

--- SAME bug, WRONG directory: docs/foo.py ---
ALLOWED (exit 0) -- THIS IS THE FOOTGUN, NOT A PASS: exit 0 here means the hook never looked, not that the code is clean. If your real source lives under a directory not listed in engine_dirs, no_swallowed_errors.py and no_type_checking_stub.py are dead weight there -- installed, firing, checking nothing -- and nothing will tell you. Edit engine_dirs to match your actual layout and re-run this example.

2 check(s) ran in this example.
-> 10_scope_gate_wrong_directory: OK (2 check(s))

===================================================================
example: 11_missing_dependency
===================================================================

--- state 1 -- real jq, planted violation: Write to .env ---
BLOCKED (exit 2) -- the guard works: real jq on PATH, .env write, blocked
  guard said: Blocked: /tmp/tmp.aEsq4zFDFy/.env matches protected pattern '.env'

--- state 2 -- jq on PATH is a broken stub (exit 127), same violation ---
BLOCKED (exit 2) -- the FIXED guard: same .env write, jq broken -- fails CLOSED and names jq in its message
  guard said: BLOCKED: protect-files.sh cannot run -- jq failed to parse the

--- state 3 -- the historical defect, reproduced: same broken jq, PRE-FIX guard code ---
ALLOWED (exit 0) -- THIS IS THE BUG, NOT A PASS: same broken-jq PATH, same .env write, run against the pre-fix protect-files.sh (embedded in the example as a static fixture, from before this repo's own jq fail-open fix). Exit 0 -- the write to .env would have gone through. The guard was listed, running, and reporting nothing wrong, while protecting nothing.

Why this is its own example, not a footnote on 01_protect_files: every
other example here perturbs the guard's INPUT. This one perturbs its
ENVIRONMENT -- a missing binary, a missing config file, a failed import
are all the same shape (see also: 10_scope_gate_wrong_directory, a
missing-CONFIG variant of the same class). That axis was untested by
construction across the whole pack, which is exactly why this fail-open
survived repeated verification: every round exercised the happy path
and never asked what happens when a dependency is absent.

3 check(s) ran in this example.
-> 11_missing_dependency: OK (3 check(s))

===================================================================
examples/: all 11 example(s) passed, 26 total check(s).
```

Command: `./examples/run_all.sh`. Exit code: `0`.

## A finding surfaced while building this, not quietly worked around

Example 08's third check (`workflow_agent_sizing_gate.py`, a bare
`// workflow-model-ok` marker with no reason) used to be a documented
**gap**: an earlier probe of this exact codepath, during this same work
session, observed that marker clearing the block with zero justification —
the one escape hatch in this pack that didn't require a real reason, unlike
`tampering-ok:` / `swallow-ok:` / `delete-tests-ok:` / `test-mutate-ok:` /
`opus-leaf-ok:` everywhere else. Another agent working in this repo
concurrently fixed it mid-session; re-verified live (see the pasted output
above) that a bare marker is now blocked and only a marker with an actual
`<reason>` clears it. Reported here rather than silently adjusted, per this
repo's own house style: a claim that turns out to be about a moving target
gets stated as of when it was checked, not smoothed over.

## What this doesn't cover

- **Every guard has an example, but not every hook does.** `_dispatch.py`
  (the entrypoint that classifies a hook as GUARDRAIL-fail-closed vs.
  ADVISORY-fail-open on import failure), `check_interpreter_floor.py`
  (a preflight CLI, not a hook), and `integrator_transcript_compactor.py`
  (an advisory hook that never blocks) aren't demonstrated here — none of
  them is a guard an agent's tool call gets blocked by in the sense this
  directory is showing. Their behavior is covered by the hooks' own unit
  tests (`.claude/hooks/test_*.py`), which `run_tests.sh` also runs.
- **These are the exit-code contract only.** No example here spins up a
  real Claude Code session; each one invokes the real hook script directly
  over stdin, exactly as the hook protocol does, which is everything the
  protocol's contract (exit 2 = block, anything else = allow) depends on —
  but it does not prove the hook is actually *wired up* in a given
  installation's `settings.json`. That's a separate, install-time concern.
- **jq is a hard dependency here.** `protect-files.sh` reads its event with
  `jq`, and every example in this directory builds its JSON fixtures with
  it too. `run_tests.sh` checks for `jq` up front and fails loudly with an
  install command if it's missing, rather than letting these examples fail
  with a confusing "command not found" partway through. Example 11 is about
  a *different* jq-absence: not this directory's own tooling, but
  `protect-files.sh`'s dependency on it once installed for real, on an end
  user's machine that this pack doesn't control.
- **The environment axis (10, 11) is demonstrated for two guards, not
  audited across all of them.** `no_swallowed_errors.py` /
  `no_type_checking_stub.py` share the missing-config failure mode (10) by
  construction — same `is_engine_path()` call. `protect-files.sh`'s
  jq-dependency fail-open (11) was found and fixed once; nothing here
  systematically checks whether any *other* hook shells out to a binary
  that could go missing the same way. `.claude/hooks/_common.py`'s only
  other external dependency is PyYAML, which is checked in
  `run_tests.sh`'s own prerequisites, not demonstrated as a live failure
  mode here.
