# Installing faultseed

This installs a small pack of deterministic Claude Code hooks into a repo you
already have. Nine of them block specific dishonest-looking edits before
Claude Code makes them; the rest are the shared machinery that runs them and
generates their wiring.

**The doctrine, stated once:** a gate never proven to fail is
indistinguishable from a gate that cannot fail. Every PROVE IT block below
plants a real violation and a real near-miss and shows you both outcomes.
Skipping them means you've copied some files, not installed a control.

## What you're installing

**9 guards** — each is a `PreToolUse`, `SubagentStop`, or `Bash`-matcher hook
that can block a tool call with exit code 2:

| Guard | Fires on | Blocks |
|---|---|---|
| `protect-files.sh` | `Edit`\|`Write` | Writes to `.env`, `package-lock.json`, anything under a `.git/`/`migrations/` path segment |
| `no_test_tampering.py` | `Edit`\|`Write`\|`MultiEdit` | Blanket `skip`/`xfail`, assertion removal, in files `is_test_file()` recognizes |
| `no_swallowed_errors.py` | `Edit`\|`Write`\|`MultiEdit` | Bare `except: pass`/`...` in `engine_dirs`-scoped Python (plus PowerShell/Go patterns) |
| `no_type_checking_stub.py` | `Edit`\|`Write`\|`MultiEdit` | A method defined only inside `if TYPE_CHECKING:`, in `engine_dirs`-scoped Python |
| `no_bash_test_deletion.py` | `Bash` | `rm`/`git rm` of a test file, `git mv` out of the test tree |
| `no_bash_test_mutation.py` | `Bash` | `sed -i`/`awk -i`/`tee`/redirect mutation of an *existing* test file |
| `agent_sizing_gate.py` | `Agent` | An `Agent` launch missing `model`, or a frontier model (`opus`/`fable`) with no leaf-escape sentinel |
| `workflow_agent_sizing_gate.py` | `Workflow` | An `agent(...)` call site inside a Workflow script with no `model:` |
| `subagent_closing_report.py` | `SubagentStop` | A subagent transcript missing the two required closing-report lines |

**4 shared-infrastructure files** — not hooks themselves, never appear in
`settings.json`:

- `_common.py` — shared diff-parsing, path-scope, and telemetry helpers every hook above imports.
- `_dispatch.py` — the entrypoint every wired hook command actually runs through.
- `generate_settings_json.py` — builds `.claude/settings.json` from `docs/hook-manifest.yaml`.
- `check_interpreter_floor.py` — standalone preflight: confirms the interpreter that will run these hooks meets the >=3.10 floor.

Plus a tenth hook that ships but isn't a guard: `integrator_transcript_compactor.py`
(`PreCompact`, transcript archiving/pruning — informational, never blocks; see
the exit-code section below for why that distinction matters).

**Config it reads**: `docs/hook-manifest.yaml` (declares which hooks exist and
their eligibility) and `docs/audit/audit-scope.yaml` (declares your
`engine_dirs` — see §2, the step most likely to bite you).

### Dependencies

Python **>=3.10** is a hard floor: `_common.py` uses a module-level `X | None`
annotation, which raises `TypeError` at import on anything older
(`_common.py:22-34`, comment cites the mechanism directly).
This environment: `Python 3.13.5`.

The hooks themselves need **only the stdlib**, with one lazy exception:
`PyYAML`, imported inside `_common.py`'s `_load_engine_dirs()`
(`_common.py:212`) — so it's only required by the two hooks that call
`is_engine_path()` (`no_swallowed_errors.py`, `no_type_checking_stub.py`).
`generate_settings_json.py` also imports it, at module level, so the
generator hard-fails without it regardless of which hooks you wire.
Running the test suite additionally needs `pytest`, which is not a hook
dependency, just a test-runner one.

One-line install:

```
pip install pyyaml pytest
```

Verified from a genuinely clean venv with neither package present:

```
$ python3 -c "import yaml"
ModuleNotFoundError: No module named 'yaml'
$ pip install --quiet pyyaml pytest
$ python3 -c "import yaml, pytest; print('yaml', yaml.__version__); print('pytest', pytest.__version__)"
yaml 6.0.3
pytest 9.1.1
```

And confirmed the *other direction*: a hook that doesn't call
`is_engine_path()` runs fine with no PyYAML installed at all —
`no_test_tampering.py`, same clean venv, blocked a planted `@pytest.mark.skip`
correctly with `ModuleNotFoundError: No module named 'yaml'` still true for
the interpreter running it.

`protect-files.sh` (the one non-Python guard) needs the **`jq`** binary on
PATH — it parses its stdin event with it, and this is an external
dependency `pip install pyyaml pytest` above does not cover:

```
apt install jq       # Debian/Ubuntu
brew install jq      # macOS
yum install jq        # RHEL/CentOS/Fedora
```

Without jq, the guard now fails **closed** (exit 2, naming jq in the
message) rather than silently permitting every Edit/Write — see
`docs/guards/protect-files.md` "Scope" and
`.claude/hooks/test_protect_files_missing_jq.py` for the planted-failure
test that pins this.

## Quickstart

Run in your own repo. Every command below was actually run, against a fresh
scratch repo, to produce the output shown.

**1. Copy the files in.**

```
cp -r <this-pack>/.claude/hooks   <your-repo>/.claude/hooks
cp -r <this-pack>/.claude/rules   <your-repo>/.claude/rules
mkdir -p <your-repo>/docs/audit
cp <this-pack>/docs/hook-manifest.yaml       <your-repo>/docs/hook-manifest.yaml
cp <this-pack>/docs/audit/audit-scope.yaml   <your-repo>/docs/audit/audit-scope.yaml
```

Merge these lines from this pack's `.gitignore` into your own — the first is
what keeps `docs/telemetry.md`'s local-only log out of your commits:

```
.claude/hooks/state/
.claude/settings.json
.claude/settings.local.json
.claude/PROVENANCE.json
.claude/tools.json
```

`PROVENANCE.json` is the sidecar the generator writes next to
`settings.json`, and it is on that list for a specific reason rather than
tidiness: it records the `abs_root` you generated with, so committing it
publishes an absolute filesystem path from your machine. An earlier draft of
this pack's own `.gitignore` missed it — caught with `git add -A -n` in a
scratch repo, which staged `PROVENANCE.json` while correctly skipping
`settings.json` and the state directory.

**2. Edit `docs/audit/audit-scope.yaml`'s `engine_dirs` to match your repo.**
Do not skip this — it's §2 below, and getting it wrong is silent.

**3. Generate `.claude/settings.json`.**

```
$ python3 .claude/hooks/generate_settings_json.py \
    --manifest docs/hook-manifest.yaml --target python_default \
    --out .claude/settings.json
wrote .claude/settings.json
wrote .claude/PROVENANCE.json
```

Real output, this session, from a scratch repo seeded with one file
(`src/app.py`) and nothing else. The generated `settings.json` wired all 9 <!-- doc-ref-ok: src/app.py is the scratch repo's own file, created by the reader -->
guards plus the one advisory hook, every command routed through
`_dispatch.py`:

```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" protect-files.sh"}]},
      {"matcher": "Edit|Write|MultiEdit", "hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" no_test_tampering.py"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" no_swallowed_errors.py"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" no_type_checking_stub.py"}
      ]},
      {"matcher": "Agent", "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" agent_sizing_gate.py"}]},
      {"matcher": "Workflow", "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" workflow_agent_sizing_gate.py"}]},
      {"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" no_bash_test_deletion.py"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" no_bash_test_mutation.py"}
      ]}
    ],
    "SubagentStop": [{"hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" subagent_closing_report.py"}]}],
    "PreCompact": [{"hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py\" integrator_transcript_compactor.py"}]}]
  }
}
```

**PROVE IT.** Open the file you just generated and check it against the guard
table above. If a guard you expected is missing, or one you didn't expect is
present, your `--target` is wrong — fix the target, regenerate, don't
hand-edit the output.

**4. See it block something, right now, without waiting for Claude Code.**
Every generated command is `python3 .claude/hooks/_dispatch.py <hook>` fed
a JSON tool-call event on stdin — you can call that directly:

```
$ echo '{"tool_name":"Write","tool_input":{"file_path":".env","content":"SECRET=1"}}' | \
    python3 .claude/hooks/_dispatch.py protect-files.sh
Blocked: .env matches protected pattern '.env'
exit=2
$ echo '{"tool_name":"Write","tool_input":{"file_path":"config.envoy.yaml","content":"x: 1"}}' | \
    python3 .claude/hooks/_dispatch.py protect-files.sh
exit=0
```

That's the whole install proven in one command: a real violation blocked,
a real near-miss (a filename that merely contains `.env` as a substring)
allowed.

**5. Done.** Restart or reload Claude Code so it picks up the new
`.claude/settings.json`.

## §2. `engine_dirs` — read this even if you're in a hurry

Two guards, `no_swallowed_errors.py` and `no_type_checking_stub.py`, only
police files under the source directories you list in `engine_dirs`
(`docs/audit/audit-scope.yaml`). This is read by `_common.py`'s
`is_engine_path()` (`_common.py:256-281`), which loads and caches the list
via `_load_engine_dirs()` (`_common.py:197-232`) — resolved **relative to
where `_common.py` itself lives**, not to `CLAUDE_PROJECT_DIR`
(`_AUDIT_SCOPE_ROOT`, `_common.py:169`; the file's own comment at
`_common.py:155-168` explains why: a self-locating check must not have its
ground shift under a `CLAUDE_PROJECT_DIR` override).

**Get this wrong and the two hooks silently cover zero code** — they still
run, still report "allow" on every edit, and look installed. There is no
warning for a scope that matches nothing.

There is a loud failure mode, but it's the opposite shape: if
`audit-scope.yaml` is **missing or malformed**, `is_engine_path()` doesn't
default to permissive — it raises `AuditScopeLoadError`, which
`is_engine_path()` turns into `block()` (exit 2) on **every single edit**,
not just engine-scoped ones (`_common.py:264-266`, `274-280`). A missing
config is a loud block; a wrong-but-present config is a silent no-op. Know
which failure mode you're looking at.

The shipped file ships with a placeholder:

```yaml
engine_dirs:
  - "src"
```

Edit the list to your actual source roots before relying on either hook.

**PROVE IT — three directions.** Run every command below from your repo
root; all three were actually run this way (relative paths, `$PWD` as the
project dir) to produce the output shown.

**1. Inside `engine_dirs` → blocked.**

```
$ printf 'def foo():\n    try:\n        risky()\n    except Exception:\n        pass\n' > src/foo.py
$ python3 -c "
import json
print(json.dumps({'tool_name':'Write','tool_input':{'file_path':'src/foo.py','content':open('src/foo.py').read()}}))
" | python3 .claude/hooks/_dispatch.py no_swallowed_errors.py
BLOCKED: this edit hides a problem instead of solving it.

  - line 4: `except Exception:` silently swallows an error. Handle it, re-raise it, or let it propagate — do not bury it. If the swallow is genuinely correct (optional-import fallback, idiomatic asyncio cancel/queue drain, deliberate degrade-to-default), put `# swallow-ok: <reason>` on the `except` line or its `pass` line.
...
exit=2
```

**2. Outside `engine_dirs` → allowed.** Identical content, `docs/notes/foo.py`:

```
$ mkdir -p docs/notes && cp src/foo.py docs/notes/foo.py
$ python3 -c "
import json
print(json.dumps({'tool_name':'Write','tool_input':{'file_path':'docs/notes/foo.py','content':open('docs/notes/foo.py').read()}}))
" | python3 .claude/hooks/_dispatch.py no_swallowed_errors.py
exit=0
```

**3. Missing config → loud block, not a quiet allow.**

```
$ mv docs/audit/audit-scope.yaml docs/audit/audit-scope.yaml.bak
$ python3 -c "
import json
print(json.dumps({'tool_name':'Write','tool_input':{'file_path':'src/foo.py','content':open('src/foo.py').read()}}))
" | python3 .claude/hooks/_dispatch.py no_swallowed_errors.py
BLOCKED: cannot load docs/audit/audit-scope.yaml's engine_dirs — an
engine-quality guardrail cannot determine path scope without it:
audit-scope.yaml not found at <your-repo>/docs/audit/audit-scope.yaml —
engine-quality guardrails cannot determine path scope without it.
Fix or restore audit-scope.yaml. This is a guardrail-config failure, not
a finding about this specific edit.
exit=2
$ mv docs/audit/audit-scope.yaml.bak docs/audit/audit-scope.yaml
```

The error message's `audit-scope.yaml not found at ...` line names the
resolved absolute path on your own machine — `<your-repo>` above stands in
for whatever that path was on the machine this was verified on; the
message itself is real, unedited output, just with that one
machine-specific segment generalized so this doc doesn't ship someone's
local filesystem layout.

If (1) doesn't block in your repo, your `engine_dirs` don't match your real
layout and both engine-quality guards are inert for your entire codebase
while `.claude/settings.json` still lists them as wired.

## §3. Test-naming convention — check it before you trust `no_test_tampering.py`

`is_test_file()` (`_common.py:101-114`) is a **fixed, non-configurable**
convention: basename starts `test_`, ends `_test.py`/`_test.go`, path
contains `/tests/` or `/test/`, basename is `conftest.py`, or ends
`.tests.ps1`. There is no schema for this in `hook-manifest.yaml`. If your
tests are named otherwise (`*Test.java`, `*.spec.ts`, `check_*.py`), this
guard will never recognize them — not an error, just silent non-coverage.

**PROVE IT — both directions.** Run from your repo root:

```
$ mkdir -p tests && cat > tests/test_foo.py <<'EOF'
def test_adds():
    assert 1 + 1 == 2
EOF
```

Blanket skip on a real test → **blocked**:

```
$ python3 -c "
import json
print(json.dumps({
  'tool_name':'Edit',
  'tool_input':{
    'file_path':'tests/test_foo.py',
    'old_string':'def test_adds():\n    assert 1 + 1 == 2\n',
    'new_string':'@pytest.mark.skip\ndef test_adds():\n    assert 1 + 1 == 2\n'
  }
}))
" | python3 .claude/hooks/_dispatch.py no_test_tampering.py
BLOCKED: this edit weakens a test instead of fixing the code under test.

  - introduces a blanket skip/xfail marker: '@pytest.mark.skip'
...
exit=2
```

The same test, a real platform guard instead → **allowed**:

```
$ python3 -c "
import json
print(json.dumps({
  'tool_name':'Edit',
  'tool_input':{
    'file_path':'tests/test_foo.py',
    'old_string':'def test_adds():\n    assert 1 + 1 == 2\n',
    'new_string':'@pytest.mark.skipif(sys.platform == \"win32\", reason=\"posix only\")\ndef test_adds():\n    assert 1 + 1 == 2\n'
  }
}))
" | python3 .claude/hooks/_dispatch.py no_test_tampering.py
exit=0
```

Sanctioned edits carry `# tampering-ok: <reason>` — the reason must name the
specific code change the test now matches, not "test needed updating." A
bare marker with no reason does not clear the block (the regex requires a
non-whitespace character after the colon).

## §4. Run the rest of the suite

```
$ python3 -m pytest .claude/hooks/ -q
130 passed
```

Or run everything at once — the hook tests, the `scripts/` tests, and the
`examples/` planted-failure checks — with `./run_tests.sh`. That script fails
loudly if any stage is red, and treats a suite that collected zero tests as a
failure rather than a pass.

**All nine guards carry a planted-failure test** that constructs a violating
input and asserts rejection, plus the legitimate near-miss that must be
allowed. So does `_dispatch.py`, the wiring layer — the single point where
the whole pack could go quietly dead.

Worth knowing, since it is the kind of thing a pack usually hides: four of
those guards had **no test at all** when this pack was assembled
(`no_swallowed_errors.py`, `no_type_checking_stub.py`,
`workflow_agent_sizing_gate.py`, and `subagent_closing_report.py`'s block
path), and `_dispatch.py`'s cited test did not exist. Writing the missing
tests found four real bugs in the guards they covered. The count above is a
snapshot — re-run it rather than trusting this line.

If some of these encode a convention you don't share, disable them in your
own `docs/hook-manifest.yaml` and **regenerate** — editing the manifest
without rerunning `generate_settings_json.py` changes nothing, because
`.claude/settings.json` is the generated artifact Claude Code actually
reads.

## The exit-code contract, and the fail-open trap

**Exit code 2 blocks. Every other exit code silently allows.** This is the
Claude Code hook protocol, not a choice this pack made. A hook that crashes
on import, or returns 1 for "I found a problem," enforces nothing while
still being listed in `settings.json` as installed.

`_dispatch.py` is the entrypoint every generated command actually runs
(`... _dispatch.py <hook-name>`, not the hook file directly). Before
`exec`-ing the real hook, it does an in-process import/syntax probe
(`_check_importable`, `_dispatch.py:252-292` per the shipped comments) and
classifies the failure:

- **Guardrail** (anything not in the explicit `_ADVISORY_HOOKS` set,
  `_dispatch.py:239`) that fails to import → **fail CLOSED**:
  `_block_guardrail_import_failure` (`_dispatch.py:336`), exit 2. The broken
  hook is never exec'd.
- **Advisory** (`_ADVISORY_HOOKS`, `_dispatch.py:239`; in this delivery the
  only member that actually ships is `integrator_transcript_compactor.py`)
  that fails to import → **fail OPEN, but loud**:
  `_warn_advisory_import_failure` (`_dispatch.py:354`), a stderr `WARNING`
  plus a `dispatch_import_failure` telemetry event, then exit 0.
- **Missing hook file entirely** → `_block` (`_dispatch.py:368`), exit 2,
  names the resolved path.

**Verified live, both classifications**, by copying the hooks tree to a temp
dir and injecting `raise RuntimeError(...)` at import time. Run from your
repo root:

```
$ cp -r .claude/hooks /tmp/hooks-broken
$ python3 -c "
p = '/tmp/hooks-broken/_common.py'
src = open(p).read()
open(p, 'w').write(src.replace('import json\n', 'import json\nraise RuntimeError(\"simulated import-time breakage\")\n', 1))
"
$ echo '{}' | AUDIT_HARNESS_HOOKS_DIR=/tmp/hooks-broken python3 /tmp/hooks-broken/_dispatch.py no_test_tampering.py
BLOCKED: guardrail hook 'no_test_tampering.py' failed to load (/tmp/hooks-broken/no_test_tampering.py) -- a guardrail that cannot import cannot enforce anything, and the Claude Code hook protocol only treats exit 2 as blocking (a plain uncaught-exception exit 1 from the real hook would have been silently read as PERMIT). Refusing to run it, and refusing to silently wave this tool call through.
Import error:
Traceback (most recent call last):
  ...
RuntimeError: simulated import-time breakage

Fix the hook (or whatever it imports) before this control can run again. If this hook is genuinely meant to fail open, that is a deliberate classification change -- add it to _ADVISORY_HOOKS in this file, with a reason, rather than leaving it silently broken.
exit=2
```

That's `_common.py` broken, which every guardrail imports — fail-closed,
not a crash that quietly permits the edit. The advisory path needs its own
target, because `integrator_transcript_compactor.py` doesn't import
`_common.py` at all (breaking `_common.py` alone has no effect on it):

```
$ cp -r .claude/hooks /tmp/hooks-broken2
$ python3 -c "
p = '/tmp/hooks-broken2/integrator_transcript_compactor.py'
lines = open(p).read().split('\n')
for i, line in enumerate(lines):
    if line.startswith('import '):
        lines.insert(i + 1, 'raise RuntimeError(\"simulated advisory import-time breakage\")')
        break
open(p, 'w').write('\n'.join(lines))
"
$ echo '{}' | AUDIT_HARNESS_HOOKS_DIR=/tmp/hooks-broken2 python3 /tmp/hooks-broken2/_dispatch.py integrator_transcript_compactor.py
WARNING: advisory hook 'integrator_transcript_compactor.py' failed to load (/tmp/hooks-broken2/integrator_transcript_compactor.py) and will not run this invocation. Classified advisory (context-injection/telemetry, never a denial), so this fails OPEN by design -- but never silently: this warning plus a dispatch_import_failure telemetry event are the loud signal that replaces it. See _dispatch.py's GUARDRAIL-VS-ADVISORY docstring section.
Import error:
Traceback (most recent call last):
  ...
RuntimeError: simulated advisory import-time breakage

exit=0
$ rm -rf /tmp/hooks-broken /tmp/hooks-broken2
```

## The generator's dimensions, honestly

`generate_settings_json.py` resolves hook eligibility across four axes
declared in `docs/hook-manifest.yaml`'s header. A normal install touches
exactly one of them:

- **`--target`** (a name under `targets:`, e.g. `python_default` →
  `profile: python`) — **this is the one you pick.** It decides which of a
  hook's `class` values (`P` = always eligible, `GG` = eligible for Python
  always / for Go only if `fixed_for_go: true`, `PP` = Python-only, `LIB` =
  never a hook) apply.
- **`--pack`** (default `B`) selects `mechanical` vs. `doctrine` layers.
  Every hook in this delivery is `layer: mechanical`, so pack `B` and pack
  `C` produce byte-identical output here. Leave it at the default.
- **`--stage`** (default `none`) is an extension point for a
  knowledge-docs/knowledge-tools layer this delivery doesn't populate — no
  hook or doc in this manifest carries a `stage`-relevant layer, so any
  `--stage` value produces the same `settings.json` as `--stage none`.
  Leave it alone.
- **`class`** isn't a flag — it's per-hook data in the manifest, already
  baked into the table above.

`--pack` and `--stage` exist because the manifest format is shared with the
origin's own larger, multi-profile experiments. In this delivery they're
inert knobs: real, documented, and safe to ignore. Don't treat them as
something you need to understand to install nine hooks.

Two more flags exist for portability, not normal use: `--abs-root` (bake an
absolute path into every hook command, for a settings.json mounted against
a different working tree than `$CLAUDE_PROJECT_DIR` points at) and
`--interpreter` (pin the exact `python3` instead of resolving it from `PATH`
at hook-run time, which can drift mid-session if something activates a
venv). Both default to unset and produce the var-relative, bare-`python3`
output shown in the Quickstart.

## Known escape hatches (session-level)

Per-guard escape markers (`# tampering-ok:`, `# swallow-ok:`, etc.) belong
in each guard's own docs — they're per-invocation, not per-session. These
four turn off enforcement for a whole session or invocation and you should
know all of them before you rely on this pack:

| Env var | Effect | Exact truthiness |
|---|---|---|
| `SKIP_HOOK_DISPATCH` | Bypasses `_dispatch.py` entirely — no guard in this pack runs. Checked first, before any hook resolution (`_dispatch.py:386-387`). | Any value **not** in `("", "0", "false", "False")` skips. Setting it to `"false"` does NOT skip. |
| `SKIP_SUBAGENT_CLOSING_REPORT` | Disables `subagent_closing_report.py` only. | Strict: must be exactly `"1"` (`subagent_closing_report.py:304`). `"true"` does **not** disable it. |
| `GUARDRAILS_INTEGRATOR_ROLE` | Bypasses `no_bash_test_mutation.py`'s test-file-mutation check entirely — "the integrator owns test edits at merge time." Checked directly inside the hook, not via `_common.agent_role()`. | Strict: must be exactly `"1"` (`no_bash_test_mutation.py:183`). This var was renamed during this pack's development; the name and line above were confirmed by grepping current source at the time this doc was written, not carried over from an older note — re-grep before relying on it if you're tracking an active branch. |
| `GUARDRAILS_STRICT` | Promotes `no_swallowed_errors.py`'s warn-only excuse-comment hits to hard blocks. | **Inverted from the others**: triggers on anything `!= "0"` (`no_swallowed_errors.py:146`) — so `GUARDRAILS_STRICT=false` does NOT turn it off, it turns strict mode ON. Only `"0"` (or unset) is off. |

`GUARDRAILS_SWALLOW_NEIGHBORS=N` (default `2`) is a tuning knob, not an
escape hatch — it widens or narrows `no_swallowed_errors.py`'s neighborhood
scan, it doesn't disable anything.

Three different truthiness conventions across four variables in one small
pack. Don't assume one from another; the table above is checked against
current source, not inferred.

## The run-shape caveat — this one bites silently

`subagent_closing_report.py` fires on `SubagentStop`, a **natural
termination**. If you run agents non-interactively under a turn or token
budget, a run that gets cut off before it would have stopped on its own
never reaches that event — the hook never runs, and you get no report at
all.

**"No report" and "nothing to report" then look identical downstream.**
Both produce silence. One means the agent finished clean; the other means
the run was truncated and you have no idea what state it left things in.
Collapsing those two is the same silent-vacuity shape as an `engine_dirs`
scope that matches nothing: an empty result reads as success either way.

Why there is no Stop-event hook that runs your suite for you — a version of
one existed, detected correctly, and was withdrawn rather than patched — is
in [docs/no-done-gate.md](docs/no-done-gate.md), together with the measured
failure of the obvious repair. Read it before you build your own.

There is no Stop-event hook in this delivery — only `SubagentStop`, and only
for subagent completions, not top-level session termination. If a document
you've read elsewhere describes a Stop hook that runs your verification
command itself, that isn't what ships here.

**What to do about it**: this is a fix for your runner, not for the hook.
Whatever consumes an agent run — CI job, dispatcher, orchestrator — must
treat "terminated without a closing report" as a distinct **failing**
outcome, never as "nothing to report." That requires knowing both the exit
reason and whether a report was actually emitted; branching on exit status
alone isn't enough. This pack gives you the enforcement mechanism for a run
that reaches its own end; it does not give you a way to distinguish a clean
finish from a truncation, and you should not assume it does.

## Uninstalling

Every control here is a file plus a manifest entry. To remove one guard:
delete its file, remove its entry from `docs/hook-manifest.yaml`, regenerate
`settings.json`. To remove the whole pack:

```
rm -rf .claude/hooks .claude/rules/honesty-guardrails.md
rm -f  docs/hook-manifest.yaml docs/audit/audit-scope.yaml
rm -f  .claude/settings.json .claude/settings.local.json .claude/PROVENANCE.json
```

`docs/audit/audit-scope.yaml` is safe to remove along with the hooks — it
exists only to feed `is_engine_path()`; nothing else in this delivery reads
it. Nothing in this pack writes outside your repo, phones home, or requires
a background service (see `docs/telemetry.md`) — the only state left behind
is `.claude/hooks/state/harness_events.jsonl`, which the `rm -rf
.claude/hooks` above already removes.
