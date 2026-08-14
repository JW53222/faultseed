# Contributing to faultseed

faultseed is a pack of deterministic Claude Code hooks. The whole pitch is one
doctrine:

> A gate never proven to fail is indistinguishable from a gate that cannot
> fail.

A guard that has only ever been shown to accept clean input has not been
shown to do anything — it behaves exactly like a hook that returns success
unconditionally, and nothing in the repo would tell you the difference. This
document exists to make that bar concrete enough that you can hit it without
asking someone.

Everything below is checked against this tree as it stands right now. Where
I quote a command, I ran it. Where I quote a test, it exists at that path.

## 1. The planted-failure requirement

A PR adding a new guard is not accepted without a test that **constructs a
violating input and asserts the guard rejects it.** Not "the guard runs
without crashing." Not "the guard is wired in the manifest." A real,
synthetic bug, fed to the real hook, asserted blocked.

You need **both directions**, in the same test file:

1. The violation is rejected (`returncode == 2`, and check the stderr
   message names the actual thing you planted — asserting only the return
   code lets an unrelated regression pass silently).
2. The nearest legitimate thing is **allowed**. This is the half that
   actually distinguishes a working guard from one that rejects everything
   it sees — a hook that returns `exit 2` unconditionally also "passes" a
   BLOCKED-only test suite.

Worked example, `.claude/hooks/test_no_swallowed_errors.py`:

```python
def test_bare_pass_swallow_blocked(tmp_path):
    ...
    assert rc == 2

def test_swallow_ok_marker_on_except_line_allowed(tmp_path):
    ...
    assert rc == 0
```

and `protect-files.sh`'s test, `test_protect_files_env_overmatch.py`:
`test_blocks_dotenv_exact` asserts `r.returncode == 2` for a `Write` to
`.env`; `test_allows_envoy_config_yaml` asserts `r.returncode == 0` for
`config.envoy.yaml` — the near-miss the hook's own docstring says it used to
over-match on. That pairing (BLOCKED shape / ALLOWED near-miss, same test
file, same hook) is the shape every new guard's tests should follow.

Black-box convention used throughout this tree: pipe a JSON `PreToolUse`
event on stdin to the hook via `subprocess.run([sys.executable, HOOK],
input=ev, ...)` and assert on `proc.returncode` / `proc.stderr`. See
`.claude/hooks/test_agent_sizing_gate.py` or
`.claude/hooks/test_no_swallowed_errors.py` for the pattern; copy the `_run`
helper rather than reinventing it.

## 2. The mutation check — a test must be seen RED once

A test that has never been observed failing has not been shown to test
anything. It could be checking the wrong field, catching the wrong
exception, or passing because of a typo that makes the assertion vacuous.

Before you open the PR:

1. Write the test.
2. Break the guard on purpose — comment out the check, invert the
   condition, or (fastest) temporarily hardcode `sys.exit(0)` before the
   detection logic runs.
3. Run the test. Watch it fail. If it doesn't fail, your test isn't
   attached to the thing you think it's attached to — fix the test, not the
   guard.
4. Restore the guard.
5. Run the test again. Confirm green.

This is not optional ceremony. `.claude/hooks/test_no_swallowed_errors.py`'s
own docstring records exactly this: it was filed because
`no_swallowed_errors.py` shipped with zero test coverage — "confirmed by
reading all 7 shipped test files before writing this one." A guard can sit
in the tree, be listed in the manifest, and be invoked by real edits for a
long time before anyone notices no test ever watched it fail. Do the
mutation check yourself so your PR isn't the next instance of that gap.

## 3. Fail closed on hook crash

Claude Code's hook protocol has one rule that matters more than anything a
guard's own logic does: **exit code 2 blocks. Every other exit code (0, 1,
127, an uncaught traceback landing on 1) silently allows the tool call
through.** This is the platform's contract, not this repo's choice, and it
is a fail-**open** trap — a hook that crashes enforces nothing while still
looking installed in `settings.json`.

`.claude/hooks/_common.py`'s `block()` says it plainly in its own
docstring (`_common.py:84`):

> "Exit 2 is the magic number — Claude Code feeds stderr back to the agent
> as a blocked action it must address. Exit 1 does NOT block; it is a
> non-blocking error. So this must be exactly 2."

`_dispatch.py` is the entrypoint every wired hook command actually runs
through (not `python3 your_hook.py` directly — the generated
`settings.json` command is `python3 _dispatch.py your_hook.py`). Before
exec'ing your hook, it does an in-process import/syntax probe and
classifies what happens if that probe fails:

- **GUARDRAIL** (the default — anything not on the explicit advisory
  allowlist below) that fails to import: `_dispatch.py` does **not** exec
  the broken hook. It blocks (exit 2) itself, naming the hook and the
  traceback. A guard that can't even load is refused, not silently skipped.
- **ADVISORY** (an explicit, small, hardcoded set —
  `_dispatch.py:239`'s `_ADVISORY_HOOKS = frozenset({"transcript_context_scan.py",
  "file_context_hint.py", "prompt_context_hint.py", "covmap_diffcheck.py",
  "integrator_transcript_compactor.py"})`) that fails to import: `_dispatch.py`
  exits 0 — but loudly, with a stderr `WARNING:` and a best-effort telemetry
  event, never silently.
- A hook file that doesn't resolve on disk at all: also blocked (exit 2),
  naming the resolved path and the env vars that fix it.

**If you are adding a new advisory (never-blocks) hook, you must add its
filename to `_ADVISORY_HOOKS` in `.claude/hooks/_dispatch.py` yourself.**
Anything you don't add defaults to GUARDRAIL — which is the safe direction
(a hook you intended as advisory-only will fail CLOSED, not open, if you
forget the allowlist entry), but it means your advisory hook will start
hard-blocking on any import error instead of warning, which is surprising
behavior you should know about rather than discover in the field.

To prove this yourself rather than take it on faith: copy `.claude/hooks/`
to a temp dir, add a `raise RuntimeError("boom")` at the top of your new
hook (or of `_common.py`, if your hook imports it), and run

```
echo '{}' | AUDIT_HARNESS_HOOKS_DIR=<tmp>/hooks python3 _dispatch.py your_hook.py
```

A guardrail hook should exit 2 with `BLOCKED: guardrail hook '...' failed to
load`. An advisory hook (only after you've added it to `_ADVISORY_HOOKS`)
should exit 0 with a `WARNING:` on stderr.

## 4. No advisory-only gates

A "warning" that never blocks is a comment with extra steps. If a shape is
worth writing a guard for, the guard blocks it (exit 2). If it isn't worth
blocking, it isn't worth shipping as a guard — file it as a doc note or a
lint suggestion instead, somewhere that doesn't claim enforcement it doesn't
provide.

The one place this pack itself deviates: `no_swallowed_errors.py` has a
soft/warn tier. Excuse comments (`# TODO: good enough`, `# known issue`) are
`emit_event(..., verdict="warn")` + stderr, then `allow()` — not a block —
**unless** `GUARDRAILS_STRICT=1` is set, which promotes them to hard-block.
Same for Go's ignored-second-return (`x, _ := call()`): soft-only, not
hard-blocked.

The actual rule behind that exception, so you know when it applies to your
own guard rather than becoming an excuse to dodge rule 4: **a warn tier is
legitimate only when the shape cannot be distinguished from legitimate code
without information the hook does not have.** `x, _ := call()` is
indistinguishable, by source alone, from the ordinary Go `(value, ok)`
idiom — the hook would need the callee's real signature to tell them apart,
and it doesn't have it. An excuse comment is legitimate craft on some edits
and a smell on others; the hook can see the comment but not the surrounding
judgment call it's excusing. If your guard's shape is instead just "we
haven't gotten around to writing the check tightly enough to block it," that
is not this exception — tighten the detection or don't ship it, don't park
it as advisory.

## 5. Escape markers

Every guard that can be legitimately overridden ships a marker, and the
marker **requires a reason**. A bare marker with nothing after the colon is
itself a violation — it defeats the "state why" purpose of having a marker
at all. Every marker in this tree enforces this at the regex level by
requiring a non-whitespace character after the colon, not by a separate "is
this bare" check layered on top.

The markers as they exist in this tree today:

| Hook | Marker | Reason required |
|---|---|---|
| `no_test_tampering.py` | `# tampering-ok: <reason>` (`<# tampering-ok: <reason> #>` PowerShell, `// tampering-ok: <reason>` Go) | yes |
| `no_swallowed_errors.py` | `# swallow-ok: <reason>` (handler-aware: on the `except` line, the `pass`/`...` body line, or a comment line between them) | yes |
| `no_type_checking_stub.py` | `# host-provides: <reason>` or `# type-stub-ok: <reason>` | yes |
| `no_bash_test_deletion.py` | `# delete-tests-ok: <reason>` | yes |
| `no_bash_test_mutation.py` | `# test-mutate-ok: <reason>` | yes |
| `agent_sizing_gate.py` | `opus-leaf-ok: <reason>` or `fable-leaf-ok: <reason>` in the spawn prompt | yes |
| `workflow_agent_sizing_gate.py` | `// workflow-model-ok: <reason>` on the same line as the `agent()` call | yes |
| `protect-files.sh` | none | n/a — hardcoded blocklist, no bypass by design |

**A fixed defect, worth knowing the shape of.** `workflow_agent_sizing_gate.py`
used to have exactly the bare-marker hole this rule exists to prevent: its
`ESCAPE_RE` matched the keyword alone, no colon or reason required, so `//
workflow-model-ok` with nothing after it cleared the block — and, separately,
the gate's `VALID = {"haiku", "sonnet", "opus"}` check was defined but never
actually consulted, so `agent(p, {model: "claude-3"})` sailed through as
"sized." Both were caught the way this document asks you to catch your own
gaps: `.claude/hooks/test_workflow_agent_sizing_gate.py` was written to
assert the *documented* (correct) behavior rather than the gate's actual
(buggy) behavior, landed intentionally red, and stayed the visible record of
the gap until the fix landed. Both are fixed now — `ESCAPE_RE` requires a
non-whitespace reason after the colon, a bare `// workflow-model-ok` gets its
own distinct "this marker requires a rationale... a bare marker does not
clear the block" message (`workflow_agent_sizing_gate.py:363-368`) rather
than silently passing, and an unrecognized `model:` value is reported by name
against the `VALID` set (`workflow_agent_sizing_gate.py:247, 343-344`).
Verified, this session:

```
$ python3 -m pytest .claude/hooks/test_workflow_agent_sizing_gate.py -q
...........                                                              [100%]
11 passed in 0.23s
```

The lesson to take from this rather than the specific bug: a red,
`_FINDING`-suffixed test that documents a real gap and is deliberately left
failing (see section 9's provenance ledger) is exactly what let this defect
get found, tracked, and closed without anyone forgetting it existed in the
meantime — it is the working version of what sections 10/11's `jq` and
data-dependency incidents describe going wrong when the equivalent test was
never written at all.

## 6. Vocabulary and topology coupling — the honest limits

This is the part most likely to bite someone using this pack outside the
repo it was built in, and it will not be obvious from a green test suite.
There are two ways a guard can be real, correctly tested, green in this
repo, and still do close to nothing once it leaves.

**Vocabulary coupling.** A guard whose detection is a list of names or
substrings enumerated from one codebase degrades *silently* on a codebase
that names things differently — it doesn't error, it just stops firing.
Worked example already in this pack's own history: `no_falsy_zero.py` (not
shipped as a guard in this delivery, but documented as the cautionary
case in `docs/hook-manifest.yaml`'s own comment on the hook) matched a
hardcoded suffix list — `_pct`, `_capital`, `_multiplier`, `_fees`,
`_slippage`, `commission`, `slippage`, `leverage`, `point_value` — pulled
from one trading codebase's config-field names. It blocks
`config.point_value or 100` and allows `config.retry_count or 5` — the
identical `X or NUMBER` falsy-zero bug, one config field over. On a
codebase whose fields are `retry_count`/`max_workers`/`timeout_seconds`
instead, the guard is close to inert while `settings.json` still lists it
as installed. The owner's own ruling on it (`docs/hook-manifest.yaml`'s
`no_falsy_zero.py` entry): "the hazard is portable, the detector is not" —
which is why it isn't shipped as a wired guard here at all.

**Topology coupling.** A guard that depends on a repo layout, branch model,
or service the origin repo has that the installing repo does not. This
pack's own `docs/audit/audit-scope.yaml` is the live instance: two of the
shipped guards (`no_swallowed_errors.py`, `no_type_checking_stub.py`) only
fire inside `engine_dirs`, and that list ships as the literal placeholder
`["src"]` — a common-convention guess, not a scan of the installing repo's
actual layout. The file says so itself: *"If your source lives elsewhere,
the engine-quality hooks will silently cover zero code until you fix this
list."* `.claude/hooks/test_no_swallowed_errors.py`'s own docstring names
the sharper hazard this creates for a test suite specifically: *"a
silently-wrong `engine_dirs` would disable this (and
`no_type_checking_stub.py`) across a user's ENTIRE codebase without any
test here noticing"* — which is why that test file pins the scope gate in
both directions explicitly (`test_engine_scope_gate_both_directions`, using
an in-scope `src/...` fixture and an out-of-scope `other/...` fixture in
the same test, not two separate tests that could drift apart). A more
severe version of the same failure mode — a done-gate defining "inherited
failure" against a reference branch, installed on a target repo carrying
over a thousand pre-existing failures, so the ledger never populates and
the gate degrades to blocking on everything — is why this pack ships no
Stop-hook done-gate at all. It was withdrawn for a second, related reason
as well: its exit codes never reached the exit-2 blocking threshold, so it
detected correctly and enforced nothing. Both findings, with the measured
numbers, are in [docs/no-done-gate.md](docs/no-done-gate.md); see also
section 10 below. Topology coupling doesn't fail quietly the way vocabulary
coupling does — it produces plausible-looking wrong behavior, which is
worse than silence, because silence is at least honest about having
nothing to say.

**What this means for your PR:** state, in the PR description, which of
these two your guard is exposed to. If your detection is a name/keyword
list, say so and say whether the concept it detects generalizes past this
repo's naming. If it depends on a config file (like `engine_dirs`) or a
repo convention (a branch name, a directory layout), name the config and
what happens if it's missing or wrong for the installing repo — "silently
covers nothing" and "blocks everything" are both real answers, and they are
very different problems for an installer to debug.

Prefer a **structural** match over a **vocabulary** match wherever you have
the choice. `no_type_checking_stub.py` is the good example: it detects "a
method defined only inside `if TYPE_CHECKING:`, with no runtime `def`
sharing the same class/module scope" via AST — a structural shape that
holds regardless of what the method or class is named. `no_falsy_zero.py`
is the bad example: a suffix list. If your guard can be expressed as an AST
shape (a call pattern, a decorator, a control-flow shape) instead of a name
list, do that — it's the difference between a guard that generalizes and
one that quietly stops working the moment it leaves this repo.

## 7. The vacuous-pass hazard

A guard scoped to the wrong directory (or the wrong file extension, or the
wrong tool matcher) finds nothing and reports success. **Zero findings and a
broken configuration produce the identical observable output** — exit 0,
no stderr. Nothing distinguishes "this codebase has no violations" from "this
guard never looked at the right files" unless a test forces the guard to
look somewhere it should NOT find anything, and asserts that it doesn't.

Concretely: if your guard is scoped at all (an `engine_dirs` check, a
`is_test_file()` gate, a file-extension filter, a tool-name matcher), your
test suite must pin the scope in **both directions**:

- a violation **inside** the scope is blocked, and
- the identical violation **outside** the scope is allowed (not just "a
  clean file outside scope is allowed" — the actual bug, sitting outside
  scope, must sail through, so the test proves the boundary rather than
  proving the detector works on the one file you happened to pick).

`test_no_swallowed_errors.py::test_engine_scope_gate_both_directions` is the
template — same swallow shape, `src/...` path blocked, `other/...` path
(same content) allowed, in one test function so the pairing can't drift
apart into two tests that silently stop agreeing with each other.

## 8. Practical mechanics

**Where a hook goes:** `.claude/hooks/<your_hook>.py` (or `.sh` — see
`protect-files.sh` for the shell-script shape). Shared helpers
(`block`/`allow`/`is_test_file`/`is_engine_path`/`emit_event`/...) live in
`.claude/hooks/_common.py`; import it the way every other hook does
(`sys.path.insert(0, os.path.dirname(__file__))` then `from _common import
...`) — do not copy-paste its logic into your hook.

**Test file naming:** `.claude/hooks/test_<your_hook>.py`, black-box,
subprocess-invoking the real hook — see section 1's convention and any of
the existing `test_*.py` files in `.claude/hooks/` for the shape. Run your
file alone first:

```
$ python3 -m pytest .claude/hooks/test_your_hook.py -q  # doc-ref-ok: test_your_hook.py is a placeholder for the test YOU add, not a file here
```

then the whole hooks suite before opening a PR:

```
$ python3 -m pytest .claude/hooks/ -q
```

Observed just now on this tree:

```
144 passed in 2.63s
```

This repo is under active concurrent development — the passing count moved
five times (76 → 86 → 98 → 130 → 144) across the runs made while
writing and later revising this document, as other in-flight PRs landed new test files and
fixed a real bug (see section 5). Treat the number itself as a snapshot, not
a fact to pin — run the command yourself rather than trusting this line. As
of this run the suite is fully green (0 failed); if your run shows red,
that's either a regression to chase down before you open a PR, or (rarer,
see section 5's history) a deliberate `_FINDING`-suffixed test documenting a
gap someone hasn't closed yet — the test name and its docstring will tell
you which. For the whole repo, including the planted-failure examples/
directory, use `./run_tests.sh` from the repo root instead — it's the
single command described in its own header as "the one command a stranger
runs to find out whether this pack of guards actually works."

Dependencies: Python **>=3.10** (this repo's own floor — a module-level
`X: int | None` annotation without `from __future__ import annotations`
raises `TypeError` at import below 3.10; `check_interpreter_floor.py` exists
specifically to catch this before `_dispatch.py` execs a hook with too-old
an interpreter). One third-party import across the whole hooks tree,
`PyYAML` (used by `_common.py`'s `is_engine_path` config load and by
`generate_settings_json.py`). No `requirements.txt`/`pyproject.toml` ships
in this tree — `pip install pyyaml pytest` before the commands above if
either is missing.

**Registering the hook.** Add an entry under `hooks:` in
`docs/hook-manifest.yaml`:

```yaml
your_hook.py:
  class: P              # P = wireable day one, language-agnostic.
                         # GG = has real language-grammar gaps (see the
                         #      manifest's own header comment for the full
                         #      class table: P/GG/TD/PP/LIB/UNWIRED/PUSH).
  layer: mechanical      # enforcement machinery, not a doctrine doc.
  events:
    - {event: PreToolUse, matcher: "Edit|Write|MultiEdit"}
```

Match `matcher`/`event` to what your hook actually needs to see — copy an
existing entry whose tool surface matches yours (`Bash` for the
`no_bash_test_*` pair, `Agent`/`Workflow` for the sizing gates, `Edit|Write`
for file-content guards) rather than guessing the schema from scratch. The
manifest's own header comments (`docs/hook-manifest.yaml:1-161`) document
every axis (`class`, `layer`, `profiles`, `pack`, `stage`) in detail —
read them before adding a nonstandard combination.

Then regenerate `settings.json` for whichever target you're installing
against:

```
$ python3 .claude/hooks/generate_settings_json.py --manifest docs/hook-manifest.yaml --target <target-name> --pack <pack> --out .claude/settings.json
```

(`--help` lists every flag; `targets:`/`packs:` at the bottom of
`docs/hook-manifest.yaml` name what's available in this tree.) No
`.claude/settings.json` is checked into this repo — you must run the
generator yourself and confirm your hook appears in the output before
claiming it's wired.

**PROVE IT once, for real, before you claim the guard works:** after
regenerating `settings.json`, make an edit through the actual tool your
guard watches (an `Edit`/`Write`/`Bash`/`Agent` call, not a direct `python3
your_hook.py` invocation) that should trip it, in your own working repo,
and confirm it blocks. A guard that only ever ran inside `pytest` has not
been proven to be wired — the manifest entry and the test suite are two
separate claims, and only the live PROVE-IT step confirms both are true
together.

**What a PR must contain:**

1. The hook (`.claude/hooks/<name>.py`).
2. Its test file (section 1), including the near-miss/ALLOWED case.
3. A recorded mutation check (section 2) — say in the PR description that
   you broke the guard, watched the test go red, and restored it. This
   repo doesn't have a bot that checks this for you; it's an honesty claim
   you're making, same as the closing-report convention below.
4. A `docs/hook-manifest.yaml` entry (section 8, above).
5. If your guard has an escape marker, confirm the regex requires a
   non-whitespace reason (section 5) and add a test asserting a bare marker
   does **not** clear the block.
6. A one-paragraph statement of vocabulary/topology exposure (section 6).
7. If the guard is scoped, a both-directions scope test (section 7).
8. A statement of every dependency your guard has — file, sidecar, env var,
   binary — and what happens when each one is absent (section 10).
9. If your guard has any such dependency, a test that breaks the
   dependency itself (not the input) and asserts the guard fails closed
   (section 11).

**This list is a bar, not a gate.** Nothing in this repo enforces items 1–9
above by machine — no CI job rejects a PR for a missing one, and that's a
deliberate choice, not a gap someone forgot to close. Most of them can't be
enforced. CI can confirm a test file exists and that it currently passes. It
cannot confirm that you broke your guard on purpose, watched the test go
red, and restored it — the one step (section 2) that separates a test that
proves the guard catches something from a test that merely runs. A CI job
asserting "mutation check performed" would be a checkbox, and a checkbox
standing in for an unverifiable claim is precisely the control-shaped object
this pack exists everywhere else to make legible — see section 9's
PROVEN-FAILS/NEGATIVE-ONLY split below, or section 5's requirement that an
escape marker carry an actual reason instead of just being present. So this
stays a bar a contributor and a reviewer uphold between themselves, and this
document says so plainly rather than implying enforcement it doesn't have.
The bar is a bar, not a gate — and pretending otherwise would be the exact
overclaim this pack refuses everywhere else.

That does not make the nine items optional. There is no bot behind this
list, which means it depends entirely on the people on either side of a PR
actually meaning it: the author doing the mutation check for real instead of
writing the PR description as if they had, and the reviewer asking to see
it rather than trusting a checked box that isn't there to check.

## 9. Provenance ledger — classify your own test honestly

When you (or anyone reading this repo's test suite) records what a test
actually proves, three buckets exist, and they are not interchangeable:

- **PROVEN-FAILS** — a violating input is constructed, fed to the real
  hook, and rejection (`exit 2`) is asserted. This is what section 1
  requires. `test_no_swallowed_errors.py::test_bare_pass_swallow_blocked`
  is PROVEN-FAILS.
- **NEGATIVE-ONLY** — a test exists, but it only asserts the guard *accepts
  clean input*, or only asserts the guard is *wired* (its name appears in a
  generated hook list, or it's importable). This is the dangerous bucket:
  it looks like coverage in a test count, and it proves nothing about
  whether the guard catches what it's for. `workflow_agent_sizing_gate.py`
  was in exactly this state before `test_workflow_agent_sizing_gate.py`
  landed — its Agent-tool sibling had a real behavioral test, and this
  Workflow-tool copy of the same tripwire had none, of any kind.
- **UNTESTED** — no test references the hook at all. Confirm with
  `grep -rl "your_hook" .claude/hooks/test_*.py` before you assume
  otherwise; don't infer coverage from a hook's name or from it "being
  similar to" a tested sibling.

Do not fold NEGATIVE-ONLY into "tested" in a PR description, a comment, or
a status doc — it collapses the one distinction this whole pack exists to
preserve. If you cannot get your own guard to PROVEN-FAILS before you run
out of time on a PR, say so directly and file the gap (a tracking note in
the PR, or a comment on the hook naming the missing case) rather than
letting a NEGATIVE-ONLY test read as done. An honestly-filed gap is exactly
the outcome this doctrine is trying to make cheap to produce — a
NEGATIVE-ONLY test dressed up as coverage is the one outcome it exists to
prevent.

## 10. Ship your dependencies, or fail loudly without them

If your guard reads a file, a sidecar, an environment variable, or shells
out to a binary, one of two things must be true: that dependency ships with
the guard, or the guard checks for it and fails loudly (exit 2, a message
naming exactly what's missing) when it's absent. **Never degrade quietly.**
Correct code with a missing input degrades into whatever its fallback
happens to be — which nobody chose, nobody tested, and nobody would have
shipped on purpose.

Two real instances, found independently, both in this general shape:

**A data dependency.** A done-gate this pack does *not* ship (see
`docs/no-done-gate.md`) classified test failures as new-vs-inherited by
reading a state file. The only thing that wrote that state file was a shell
script that never shipped alongside it. So the state was always absent, the
classifier never engaged, and the gate silently fell back to blocking on
*any* non-zero result. Installed on a repo carrying 1,427 pre-existing
failures, it blocked three consecutive full-suite runs — on failures the
agent had not caused — before a loop guard forced it through. The
classifier's code was correct throughout. `docs/no-done-gate.md` names the
general rule this produced: *"A control's data dependencies must ship with
it, or its degraded path becomes its only path."*

**A binary dependency.** `protect-files.sh`, in this repo, right now, parses
its stdin event with `jq`. Read the guard's own header comment
(`.claude/hooks/protect-files.sh:22-35`) for the incident this fixed: before
the fix, a missing `jq` produced `jq: command not found` on stderr, the
`$(...)` substitution still exited 0, `FILE_PATH` ended up empty, and the
existing `-z "$FILE_PATH"` check read that the same way it reads "this event
has no file_path" — so the guard silently **allowed** the write. On a
machine without `jq`, the guard ran, reported nothing wrong, and protected
nothing, while still appearing installed and green in every test that
happened to run on a machine that had `jq`.

It now fails closed. Verified live, this session, by running the guard with
`jq` removed from `PATH`:

```
$ echo '{"tool_input":{"file_path":".env"}}' | PATH="/tmp/no-jq-path" .claude/hooks/protect-files.sh; echo "exit=$?"
BLOCKED: protect-files.sh cannot run -- 'jq' is not installed (or not
on PATH). This guard depends on jq to parse the tool-call event and
check the target file_path against protected patterns (.env,
package-lock.json, .git/, migrations/). A guardrail that cannot parse
its input cannot enforce anything, and the Claude Code hook protocol
only treats exit 2 as blocking -- so silently exiting 0 here would
look installed while protecting nothing. Refusing to silently wave
this tool call through. Install jq (e.g. 'apt install jq' / 'brew
install jq' / 'yum install jq') and retry.
exit=2
```

The source (`protect-files.sh:37-58`) tells apart three outcomes on
purpose, because collapsing any two of them reopens the hole: `jq` missing
→ block, naming `jq`; `jq` present but erroring on this input → block,
naming the jq error; `jq` succeeds and the event legitimately has no
`.tool_input.file_path` (not every tool call has one) → allow. Only the
third is a real "nothing to check here" — the first two are "I couldn't
check," which must never look like the third.

**What your PR must say:** name every file, env var, and binary your guard
depends on, and for each one, what happens when it's absent — "ships with
the guard" or "checked for, and here's the exit-2 message" are both
acceptable answers; "assumed present" is not.

**How to find them, and why the obvious method lies.** Grep for
**invocation syntax**, not for tool names as words: a command in command
position, `subprocess.run([...])`, `command -v`, a backtick or `$(...)`
substitution. Grepping for the bare name counts prose. A reviewer sweeping
this pack found five `git` hits in `protect-files.sh` and briefly believed
there was an undocumented third dependency; four were the word "git" in
comments, and the fifth was the string `".git/"` — a path pattern the guard
matches against, not a program it runs. Every doc comment that mentions a
tool reads as a dependency under a name-based grep, so a sweep run that way
produces a list you then have to disbelieve, which is worse than no list.

Run correctly against this pack, that sweep returns exactly two external
binaries — `jq` in `protect-files.sh` and `bash` in `_dispatch.py`'s shell
syntax probe. Everything else is Python-internal or re-execs the hook
target itself. Two independent people got the same answer, which is the
only reason this paragraph states a number.

## 11. Test the guard's environment, not only its input

Every planted-failure test required by section 1 perturbs the guard's
**input** — a bad line in the file being edited, a bad command on the Bash
line. None of those tests touch the guard's **environment**. That gap is
exactly how the `jq` fail-open in section 10 survived repeated
verification: two separate people ran `protect-files.sh`'s test suite, both
rounds exercised the happy path (planted violation blocked, near-miss
allowed), and neither asked what happens when `jq` itself is missing. The
guard's *logic* was tested exhaustively. Its *environment* was never tested
at all — and that's precisely the axis an exit-code-based protocol punishes
hardest: a guard that dies for an environmental reason exits something
other than 2, and something other than 2 reads as PERMIT (section 3).

So: **if your guard has any dependency named under section 10, its test
suite needs at least one case that breaks that dependency — not the guard's
input — and asserts the guard still fails CLOSED (`exit 2`).** A missing
binary, an unreadable/malformed config file, an import that raises. Same
"both directions" discipline as section 1: also assert the guard behaves
correctly when the dependency is healthy, so the environment test can't
pass by accident.

The worked example in this tree:
`test_dispatch_guardrail_vs_advisory.py::test_guardrail_import_failure_blocks_and_never_execs`
doesn't plant a bad diff — it copies the hooks directory, injects a `raise`
into `_common.py` (breaking the *import*, i.e. the guard's environment, not
anything it's asked to evaluate), and asserts `_dispatch.py` blocks (exit 2)
rather than exec'ing the broken hook. It then runs the identical dispatch
against an unbroken copy as a positive control and asserts `exit 0` — the
same both-directions shape, aimed at the environment axis instead of the
input axis.

One honest gap, stated rather than hidden: as of this writing,
`protect-files.sh`'s own `jq`-fail-closed behavior — the exact incident that
produced this rule — has **no dedicated test** in this tree. No
`test_protect_files_missing_jq.py` or equivalent exists (`find . -iname
"*jq*test*"` finds nothing); the live proof in section 10 above was run by
hand, this session, not by an automated test that will catch a regression
here. If you're touching `protect-files.sh`, writing that test — spawn the
guard with a `PATH` that has every other tool it needs but not `jq`, assert
`exit 2` and the `jq`-naming message, then assert `exit 2` differently (or
`exit 0` on a non-`.env` path) with `jq` present — closes a real gap, not a
hypothetical one.

---

## Closing report

**Changed outside the literal request:** none — this PR is `CONTRIBUTING.md`
only, no other file was created or modified.

**Known problems not fixed:** `protect-files.sh`'s `jq`-missing fail-closed
path (section 10) has no automated test of its own yet — section 11 names
this explicitly as the gap a follow-up PR should close, with the exact test
shape needed. This is the one open item; it's a gap in the pack's test
coverage, not in this document. `./run_tests.sh`, run from the repo root as
the final check on this change, exits 0 (all three stages — `.claude/hooks`,
`scripts`, and `examples/ planted-failure checks` — PASS; the exact
per-stage counts move too often under concurrent development to quote here
without going stale, see the hedge above, so re-run it yourself rather than
trusting a number pinned in this closing report) — a `scripts/` suite
failure I observed mid-session (unrelated to this document, from another
in-flight change to `check_doc_refs.py`) was gone by the time of this final
run, so there is nothing to report there.
`scripts/check_doc_refs.py --root .` itself exits nonzero right now, but
only because `CONTRIBUTING.md` is untracked (`git ls-files` confirms) and
the tool's own `test_untracked_file_is_not_a_valid_resolution_target`
deliberately treats an untracked file as an invalid citation target — that
resolves itself once this file is staged, which I was told not to do.
