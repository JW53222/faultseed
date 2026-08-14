# faultseed

Deterministic Claude Code hooks that stop a coding agent from faking
progress: weakening a test, swallowing an error, deleting a test through
the shell, declaring a method that only exists to the type checker. Nine
guards ship in this pack. Each one is a subprocess that reads one JSON
event on stdin and answers with its exit code — not a linter you run
afterward, not a prompt you hope the agent reads, but a gate that refuses
the tool call before it happens.

Nine guards, nine wired hooks — the default install wires those and nothing
else. One further hook ships but is **not** wired by default:
`integrator_transcript_compactor.py`, which is not a guard (it never blocks a
tool call). It archives and prunes transcripts on `PreCompact` and, when
`GUARDRAILS_INTEGRATOR_ROLE` is set, writes into `~/.claude/`. It was
excluded from the default target on exactly that reasoning: a guard pack's
default install should not wire a non-guard that writes to your home
directory. Opt in by adding it to your own `docs/hook-manifest.yaml` target;
[INSTALL.md](INSTALL.md) says what it does.

## The doctrine

> A gate never proven to fail is indistinguishable from a gate that cannot
> fail.

Every guard in this pack ships with a test that plants its own failure
mode — the exact thing the guard exists to catch — and asserts the guard
rejects it. That is the whole pitch.

**Name the category, because it decides how to evaluate this pack:**
faultseed is an **engineering risk guard, not a probabilistic one.** The
claim is categorical — "if an agent attempts shape X, this hook blocks it,
and here is the planted-failure test proving the block fires" — checkable
by reading a test and running a command. It is not the statistical claim
"this reduces your defect rate by some amount," which would need a
population of agent runs, a control, and a measurement this pack does not
have and does not offer. Confusing the two invites a demand for evidence
this pack deliberately doesn't provide — see
[What this does not do](#what-this-does-not-do) for the exact boundary
between what's backed and what isn't.

This is deliberately **not** the claim "faultseed makes your agent honest."
That claim is unfalsifiable and this project does not make it. What it
claims instead is narrow enough that a stranger can check it in an
afternoon: plant the violation, run the hook, read the exit code. §
[Receipts](#receipts) below shows exactly how, with the numbers this
session actually measured.

## What each guard blocks

| Guard | Blocks | Escape marker | Doc |
|---|---|---|---|
| `protect-files` | Edit/Write to `.env*`, `package-lock.json`, `.git/…`, an existing `migrations/…` file | none — hardcoded, no bypass | [page](docs/guards/protect-files.md) |
| `no_test_tampering` | A test file weakened: blanket skip/xfail, `assert True`, assertions removed with no replacement | `# tampering-ok: <reason>` | [page](docs/guards/no_test_tampering.md) |
| `no_swallowed_errors` | An exception handler whose body is a bare `pass`/`...` (plus PowerShell/Go equivalents) | `# swallow-ok: <reason>` | [page](docs/guards/no_swallowed_errors.md) |
| `no_type_checking_stub` | A method defined only inside `if TYPE_CHECKING:`, no runtime `def` | `# host-provides:` / `# type-stub-ok: <reason>` | [page](docs/guards/no_type_checking_stub.md) |
| `no_bash_test_deletion` | `rm` / `git rm` / `git mv` of a test file or tests directory via Bash | `# delete-tests-ok: <reason>` | [page](docs/guards/no_bash_test_deletion.md) |
| `no_bash_test_mutation` | `sed -i` / `awk -i` / `tee` / `dd` / a redirect mutating an EXISTING test file via Bash | `# test-mutate-ok: <reason>` | [page](docs/guards/no_bash_test_mutation.md) |
| `agent_sizing_gate` | An `Agent` spawn with no `model`, or `model: opus`/`fable` without acknowledging the frontier-leaf exception | `opus-leaf-ok:` / `fable-leaf-ok: <reason>` | [page](docs/guards/agent_sizing_gate.md) |
| `workflow_agent_sizing_gate` | A `Workflow` script's `agent()` call site with no `model:` | `// workflow-model-ok: <reason>` | [page](docs/guards/workflow_agent_sizing_gate.md) |
| `subagent_closing_report` | A subagent finishing without both "Changed outside the literal request" and "Known problems not fixed" in its transcript | none — structural exemptions only (`Explore`/`Plan` agent types, `SKIP_SUBAGENT_CLOSING_REPORT=1`) | [page](docs/guards/subagent_closing_report.md) |

Two of these — `no_swallowed_errors` and `no_type_checking_stub` — only
fire inside directories listed in `docs/audit/audit-scope.yaml`'s
`engine_dirs`. Read [What this does not do](#what-this-does-not-do) before
you trust either one on your own repo.

### Worked examples

Every command below was run this session, from the repo root, against the
real hook script. `exit 2` is the only code that blocks; everything else
allows (see [the exit-code contract](#the-exit-code-contract-and-the-fail-open-trap)).

**`protect-files`**
```
$ echo '{"tool_name":"Write","tool_input":{"file_path":".env"}}' | bash .claude/hooks/protect-files.sh
Blocked: .env matches protected pattern '.env'
exit 2   (same shape against config.envoy.yaml instead of .env: exit 0)
```

**`no_test_tampering`** — `Edit` on `tests/test_x.py`, `assert a == 1` → `pass` <!-- doc-ref-ok: tests/test_x.py is an illustrative filename, not a file in this repo -->
```
$ echo '{"tool_name":"Edit","tool_input":{"file_path":"tests/test_x.py","old_string":"    assert a == 1","new_string":"    pass"}}' | python3 .claude/hooks/no_test_tampering.py
BLOCKED: this edit weakens a test instead of fixing the code under test.
exit 2   (same edit with `# tampering-ok: <reason>` added instead of a bare `pass`: exit 0)
```

**`no_swallowed_errors`** — `Write` to `src/foo.py`, a bare `except Exception: pass`
```
$ echo '{"tool_name":"Write","tool_input":{"file_path":"src/foo.py","content":"def foo():\n    try:\n        risky()\n    except Exception:\n        pass\n"}}' | python3 .claude/hooks/no_swallowed_errors.py
BLOCKED: this edit hides a problem instead of solving it.
exit 2   (same body with `# swallow-ok: <reason>` on the pass line: exit 0)
```

**`no_type_checking_stub`** — `Write` to `src/foo.py`, `def bar` defined only under `if TYPE_CHECKING:`
```
$ echo '{"tool_name":"Write","tool_input":{"file_path":"src/foo.py","content":"from typing import TYPE_CHECKING\nclass Foo:\n    if TYPE_CHECKING:\n        def bar(self) -> int: ...\n"}}' | python3 .claude/hooks/no_type_checking_stub.py
BLOCKED: this edit declares a method/function ONLY inside an `if TYPE_CHECKING:` block with no runtime implementation.
exit 2   (same stub with `# host-provides: <reason>` above the def: exit 0)
```

**`no_bash_test_deletion`**
```
$ echo '{"tool_name":"Bash","tool_input":{"command":"rm tests/test_foo.py"}}' | python3 .claude/hooks/no_bash_test_deletion.py
BLOCKED: this Bash command deletes or moves test files out of the suite.
exit 2   (rm of a non-test path: exit 0)
```

**`no_bash_test_mutation`** — `sed -i` on an existing `tests/test_foo.py`. This guard checks
existence on disk relative to the event's `cwd`, so the fixture has to be real:
```
$ F=$(mktemp -d) && mkdir -p "$F/tests" && echo "def test_x(): assert True" > "$F/tests/test_foo.py"
$ echo "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"sed -i s/x/y/ tests/test_foo.py\"},\"cwd\":\"$F\"}" | python3 .claude/hooks/no_bash_test_mutation.py
BLOCKED: this Bash command mutates an EXISTING test file in place.
exit 2   (same sed, but a file that does not exist yet under $F: exit 0)
```

**`agent_sizing_gate`** — `Agent(model="opus", prompt="do the thing")`
```
$ echo '{"tool_name":"Agent","tool_input":{"model":"opus","prompt":"do the thing","subagent_type":"general-purpose"}}' | python3 .claude/hooks/agent_sizing_gate.py
BLOCKED: Agent(model:"opus") is a Opus leaf — full Opus rate, no fan-out.
exit 2   (same call with `opus-leaf-ok: <reason>` in the prompt: exit 0)
```

**`workflow_agent_sizing_gate`** — a `Workflow` script with `agent(p, {subagent_type: "general-purpose"})`, no `model:`
```
$ echo '{"tool_name":"Workflow","tool_input":{"script":"agent(\"do the thing\", {subagent_type: \"general-purpose\"});"},"cwd":"/tmp"}' | python3 .claude/hooks/workflow_agent_sizing_gate.py
BLOCKED: this Workflow has agent() call site(s) without an explicit `model`.
exit 2   (same call with `model: "sonnet"` added: exit 0)
```

**`subagent_closing_report`** — a subagent transcript ending "I did the thing, all good." (no marker lines).
Reads its transcript from a file path, not stdin, so this one needs a fixture line first:
```
$ T=$(mktemp -d)/transcript.jsonl
$ echo '{"message":{"role":"assistant","content":[{"type":"text","text":"I did the thing, all good."}]}}' > "$T"
$ echo "{\"agent_transcript_path\":\"$T\",\"agent_type\":\"sonnet\"}" | CLAUDE_PROJECT_DIR=. python3 .claude/hooks/subagent_closing_report.py
BLOCKED: your closing report is missing required honesty-guardrail lines.
exit 2   (identical transcript but agent_type="Explore": exit 0, exemption fires first)
```

`examples/run_all.sh` runs all nine of these plus two more (the
`engine_dirs` scope-gate footgun, and a missing-`jq`-dependency fail-open
reproduction) end to end and checks every exit code — see
[Quickstart](#quickstart).

## Quickstart

Full install: [INSTALL.md](INSTALL.md) (dependencies: Python >=3.10,
PyYAML, and `jq` — the last one only for `protect-files.sh`, which fails
closed and names it if it's missing). The short version —

```
cp -r .claude/hooks   <your-repo>/.claude/hooks
cp -r .claude/rules   <your-repo>/.claude/rules
mkdir -p <your-repo>/docs/audit
cp docs/hook-manifest.yaml       <your-repo>/docs/hook-manifest.yaml
cp docs/audit/audit-scope.yaml   <your-repo>/docs/audit/audit-scope.yaml
# edit engine_dirs in that file to match your repo -- see INSTALL.md §2
python3 .claude/hooks/generate_settings_json.py \
    --manifest docs/hook-manifest.yaml --target python_default \
    --out .claude/settings.json
```

Then PROVE IT — don't take the install on faith. `examples/run_all.sh`
plants one violation per guard and the nearest legitimate near-miss, runs
the real hook against both, and fails loudly if any check disagrees with
its expected exit code. Run this session, from the repo root:

```
$ bash examples/run_all.sh
...
examples/: all 11 example(s) passed, 26 total check(s).
```

Read one of the `examples/*/run.sh` scripts before you trust the summary
line — each one is short and shows exactly what JSON it feeds the hook and
why the expected answer is what it is.

## The exit-code contract, and the fail-open trap

Exit code 2 blocks. Every other exit code — 0, 1, an uncaught crash landing
on 1, 127 — silently allows the tool call through. This is the Claude Code
hook protocol, not a choice this pack made. It means a hook that crashes,
or that returns 1 to mean "I found a problem," enforces nothing while still
being listed as installed and still looking healthy in any log.

This repo's own history shipped that bug class more than once, not
hypothetically:

- A done-gate existed, ran daily, and detected correctly — and was
  withdrawn anyway. Its verdict paths returned `1` for a genuine new
  regression and `3` for the gate's own vacuity assertion; the hook
  protocol treats neither as blocking, only `2`. A real regression was
  reported and let through; a diff that dodged coverage entirely was
  reported and let through; the only thing that actually blocked was a
  syntax error. Full account, including the stricter classifier that was
  tried next and made things worse (1,427 pre-existing failures on a
  foreign repo, three consecutive false blocks before a loop guard forced
  it through): [docs/no-done-gate.md](docs/no-done-gate.md).
- An import-time crash on Python 3.9 — a module-level PEP-604 union type
  hint in `_common.py` without `from __future__ import annotations` —
  raised `TypeError` at import for 12 of the 13 hooks that imported it.
  Python exits 1 on an uncaught import-time exception, which the hook
  protocol does not block on, so every one of those twelve waved every
  tool call through while `.claude/settings.json` still listed them as
  installed. Nothing in any log distinguished that from "ran, found
  nothing wrong." Source: `.claude/hooks/_dispatch.py`'s own header
  comment (search it for "GUARDRAIL-VS-ADVISORY").

`_dispatch.py` is the fix, and it is the entrypoint every wired hook
command in this pack actually runs through — nothing calls a guard script
directly. Before exec'ing the real hook, it imports the target in-process
and classifies the outcome:

- **Guardrail** (everything not on a short, explicit advisory allowlist —
  in this delivery, just `integrator_transcript_compactor.py`) that fails
  to import: **fail closed**. Block, exit 2, name the hook and the captured
  traceback, never attempt the real exec.
- **Advisory** that fails to import: **fail open, but loud** — a stderr
  warning and a telemetry event, then exit 0.
- **Missing hook file entirely**: fail closed, exit 2, name the resolved
  path and the fix.

The distinction is deliberate and asymmetric: a control whose job is to
deny a tool call is useless broken, so it blocks rather than run silently
wrong; a control that only informs is allowed to degrade rather than stall
every tool call in the session.

A third instance of the same trap lived one level lower, in how a guard
reads its own stdin. `_common.load_event()` used to catch every
read/parse exception and silently return `{}`; each guard's own
early-return logic then treats an empty event as "nothing to check" —
i.e. allow. Garbage bytes, empty stdin, or invalid UTF-8 on a Python
guard's input used to mean exit 0, the same fail-open shape as the two
cases above, while `protect-files.sh` failed closed on the identical
condition via `jq`. Fixed now, and the rule is:

> **Unparseable input blocks. Parsed-but-not-applicable allows.**

The boundary is the entire subtlety. "I cannot read my own input" is a
failure of the control itself, and must fail closed. "I read the event
fine and it isn't about me" is normal operation — most guards receive
events they correctly ignore, and blocking those would be a serious
over-block that makes the pack unusable. The two look similar from the
outside and are opposite in kind. Receipt, run this session:

```
$ printf '\xff\xfe not json garbage' | python3 .claude/hooks/no_test_tampering.py; echo $?
BLOCKED: this guardrail hook could not read/parse its own stdin input (UnicodeDecodeError: ...). Failing closed ...
2
$ printf '\xff\xfe not json garbage' | bash .claude/hooks/protect-files.sh; echo $?
BLOCKED: protect-files.sh cannot run -- jq failed to parse the tool-call event on stdin. ...
2
```

## Receipts

**This suite is being actively extended, and the counts below move —
sometimes within the same session.** There is no fixed commit to pin them
to; re-run the command yourself rather than trusting the numbers below to
still be current by the time you read them.

Command run this session, from the repo root:

```
$ ./run_tests.sh
...
PASS  test suite: .claude/hooks -- 144 passed
PASS  test suite: scripts -- 71 passed
PASS  examples/ planted-failure checks
run_tests.sh: all stages passed.
```

(`examples/` on its own: `all 11 example(s) passed, 26 total check(s)` —
`./run_tests.sh` runs `.claude/hooks/`'s pytest suite, `scripts/`'s pytest
suite, and `examples/run_all.sh` as three independent stages and fails
loudly if any one of them runs zero checks.)

**9 of the 9 shipped guards carry a dedicated test that plants the exact
failure mode the guard exists to catch and asserts the guard blocks it** —
confirmed by reading each guard's test file for an assertion of `returncode
== 2` (or the black-box equivalent) against a constructed violation, not
just a wiring check. `_dispatch.py` itself — the shared entrypoint whose
guardrail-vs-advisory fail-closed/fail-open split is what makes the
individual guards trustworthy at all — has the same kind of test
(`test_dispatch_guardrail_vs_advisory.py`), constructing a real broken
import and asserting the classification on both the guardrail and advisory
paths.

That count moves, and not just upward. This suite is being actively
extended; two tests in `test_workflow_agent_sizing_gate.py` were marked, in
their own docstrings, as deliberately left red pending a fix to the gate
they test — by the time this was written they had already gone green (the
gate was fixed under them), which is itself a demonstration of the doctrine
working as intended: a documented gap, not a silently rounded-up number.

Second, independent route to the same claim, black-box rather than pytest:
`examples/run_all.sh` feeds real hook scripts real stdin JSON for a
planted violation and its near-miss, per guard, and fails loudly on any
mismatch. It now also covers a dependency going missing, not just a bad
input — `examples/11_missing_dependency` reproduces `protect-files.sh`'s
own historical fail-open (a broken `jq` on PATH used to mean every Edit/Write
sailed through unblocked) against the pre-fix commit, side by side with the
current, fixed behavior.

## What this does not do

**What's proven, stated together with what isn't, on purpose:** every guard
fires on its planted failure ([Receipts](#receipts)), and every guard with
an external dependency — a config file, a scope list, a binary on PATH —
fails closed when that dependency is missing or wrong, not silently open
([The exit-code contract](#the-exit-code-contract-and-the-fail-open-trap)).
That is the complete list of what this pack proves.

- **Whether these guards reduce defects across agent runs in aggregate is
  unestablished, and likely high-variance. It has not been measured for
  this pack.** Getting a clean read on marginal defect prevention across
  agent runs is genuinely hard, not glossed over here: any real effect is
  probably small relative to run-to-run variance, and separating it from
  noise needs enough runs to be expensive to collect. Measurements exist
  from an earlier, larger, differently-shaped system this pack's guards
  were extracted out of — different guard set, different install, different
  population of tasks — and they do not transfer here, so this README does
  not cite them. No number, no date for one.
- **Runtime cost is unmeasured.** Every wired guard runs a subprocess on
  the tool call it matches. Nothing here benchmarks what that costs in
  wall-clock time or added turn latency, and nothing here calls it
  negligible. If it matters to your workflow, measure it in your own
  install.
- **It does not run your test suite, and nothing here checks that your
  work is green before an agent finishes.** The guards block specific
  actions — weakening a test, swallowing an error, deleting a test through
  the shell — none of them execute your tests. `subagent_closing_report`
  requires two lines of prose at a natural stopping point; it does not
  verify what those lines claim. Full reasoning, including a measured
  false-fix that made a stricter version of this worse:
  [docs/no-done-gate.md](docs/no-done-gate.md).
- **Every hook writes a local telemetry line each time it fires.** Nothing
  is transmitted anywhere by default — it is a JSONL file on your own disk.
  [docs/telemetry.md](docs/telemetry.md) documents every field, how to turn
  it off (`SKIP_HARNESS_TELEMETRY=1`), and an optional way to share it that
  would help close the aggregate-effectiveness gap named above, if you're
  willing.
- **Several guards are scoped or vocabulary-coupled, and degrade
  silently, not loudly, if your repo differs.** `no_swallowed_errors` and
  `no_type_checking_stub` only fire inside `docs/audit/audit-scope.yaml`'s
  `engine_dirs`, which ships as the literal placeholder `["src"]` — a
  directory outside that list and a directory with no violations produce
  the identical observable output (exit 0, no stderr). `no_test_tampering`
  and the two Bash guards depend on a fixed test-file naming convention
  (`test_*.py`, `*_test.go`, a `/tests/` path segment, `conftest.py`, ...);
  a repo that names tests differently gets zero coverage from those guards
  and no warning that it got zero. Verify both against your own repo before
  relying on either — `examples/10_scope_gate_wrong_directory/run.sh`
  demonstrates the `engine_dirs` footgun directly. The general treatment of
  this failure class — vocabulary coupling vs. topology coupling, and which
  one your own guard is exposed to if you add one — is in
  [CONTRIBUTING.md § Vocabulary and topology coupling](CONTRIBUTING.md#6-vocabulary-and-topology-coupling--the-honest-limits).

## Compatibility

Native: Claude Code, via `.claude/settings.json` generated from
`docs/hook-manifest.yaml` (see [Quickstart](#quickstart)).

An adapter for dsh (DeepSeek Harness) / Cordis exists at
[`adapters/dsh/`](adapters/dsh/README.md). Its own README labels it
**PARTIAL**: the exit-code mapping between a real `_dispatch.py` subprocess
and dsh's real codec was exercised directly and passed, but no actual dsh
agent process was run end to end through the bridge (the monorepo's
toolchain requirements weren't met on the machine that wrote it). Read that
adapter's README for the exact boundary between what was run and what was
only read from source — this README does not repeat or upgrade that claim.

## License, contributing

[MIT License](LICENSE). To add a guard or change one, read
[CONTRIBUTING.md](CONTRIBUTING.md) first — in particular the planted-failure
requirement and the vocabulary/topology-coupling section linked above.
