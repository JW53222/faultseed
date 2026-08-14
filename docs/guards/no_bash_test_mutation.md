# no_bash_test_mutation

## What it blocks

A `Bash` command that mutates an EXISTING test file in place — `sed -i`,
`awk -i inplace`, `tee`, `dd of=`, or a truncating/appending redirect (`>`,
`>>`) — targeting a file that already exists on disk and looks like a test.

## Why this shape is worth a gate

`no_test_tampering.py` watches the Edit tool for a test being weakened;
`no_bash_test_deletion.py` watches for the test file disappearing entirely.
Neither sees a test mutated in place via the shell — `sed -i` rewrites the
file directly, bypassing the Edit tool (and its tamper guard) altogether.
This is not a hypothetical: a worker subagent in this project's history
silently deleted a whole test class, assertions included, via a bash-side
mechanism, and it sailed past `no_test_tampering.py` because that hook never
saw an Edit event for the change at all — the file just changed underneath
it. This hook closes that specific hole.

## Scope — read this before the examples below

`Bash` matcher, no `engine_dirs` gate. **One env var turns this hook off
completely: `GUARDRAILS_INTEGRATOR_ROLE=1` bypasses the whole hook
unconditionally, before the event is even parsed** — no marker, no reason,
no trace in the block message, because nothing ever gets far enough to
produce one. The rationale stated in the hook's own docstring is that the
integrator owns test edits at merge time, so this hook's job is already done
by that point. No other env vars are read. If you're reasoning about whether
this hook is actually protecting a given shell session, check that variable
first — everything else on this page is moot if it's set.

(This env var carried a different name in older copies of this hook, before
this release's rename. Verified live, from the repo root: the retired name
now does nothing at all — setting it has zero effect, it's just an ordinary
unrecognized variable to this code. Only `GUARDRAILS_INTEGRATOR_ROLE=1`
bypasses the hook. If you have automation or documentation elsewhere still
setting the old name, it silently stopped working and needs updating to
`GUARDRAILS_INTEGRATOR_ROLE`.)

## BLOCKED

```
$ mkdir -p .scratch/tests && touch .scratch/tests/test_foo.py
$ echo '{"tool_input":{"command":"sed -i '"'"'s/x/y/'"'"' tests/test_foo.py"},"cwd":".scratch"}' \
  | python3 .claude/hooks/no_bash_test_mutation.py
BLOCKED: this Bash command mutates an EXISTING test file in place.
  - sed -i -> tests/test_foo.py
...
$ echo $?
2
```
Run from the repo root; `cwd` is a relative path where `tests/test_foo.py`
actually exists on disk — the existence check is what distinguishes
"mutating a real test" from "creating a new one".

## ALLOWED

The nearest legitimate thing is not the same command with a marker slapped
on a real test file — a *bare* marker there is explicitly its own violation
(see below). The genuine near-miss is the identical marker syntax on a
target that was never a test file to begin with:

```
$ echo '{"tool_input":{"command":"sed -i '"'"'s/x/y/'"'"' notes.txt # test-mutate-ok"},"cwd":".scratch"}' \
  | python3 .claude/hooks/no_bash_test_mutation.py
$ echo $?
0
```

Both commands above were run against this tree this session, from the repo
root. A second, structurally-guaranteed near-miss: `sed -i` on a test path
that does **not** yet exist on disk is always allowed — creating a
brand-new test file is not a mutation.

## The escape marker

`# test-mutate-ok: <reason>`, same reason-required structure as its deletion
sibling — a bare `# test-mutate-ok` on a command that would otherwise block
produces a distinct "needs a reason" message rather than silently passing
(same 2026-07-22 hardening as `no_bash_test_deletion.py`, closing the same
self-grantable-escape-hatch shape).

## How we know it fires

`test_bash_marker_reason_required.py`, `test_mutation_*` functions (5 of the
file's 10 — the other 5 are its `no_bash_test_deletion.py` sibling's
`test_deletion_*` functions). Run this session, from the repo root:

```
$ python3 -m pytest .claude/hooks/test_bash_marker_reason_required.py -q
..........                                                              [100%]
10 passed in 0.21s
```

`test_mutation_marker_with_reason_allowed` runs
`sed -i 's/x/y/' tests/test_foo.py # test-mutate-ok: matches new evaluator arg`
against an existing `tests/test_foo.py` fixture and asserts `returncode ==
0` — proving the reasoned marker actually clears a real, existing-file
mutation, not just a no-op case.

## Known limits

Mutation detection targets a specific, named set of shell mechanisms
(`sed`/`gsed -i`, `awk`/`gawk`/`mawk -i inplace`, `tee`, `dd of=`, `>`/`>>`
redirects). A mutation mechanism outside that list — a Python one-liner that
opens and rewrites the file, a language-specific file-write call inside a
`bash -c "python3 -c '...'"` wrapper, an editor macro — is invisible to this
hook. It shares `no_bash_test_deletion.py`'s per-simple-command splitting
limitation (crude compound-command parsing, not full shell semantics) and
its fixed test-path naming convention (`_looks_like_test_path`, same rule as
the deletion hook — a repo with a different test-file convention gets no
coverage here either). Concretely, that regex recognizes
`test_*.py`/`*_test.py`/`*.Tests.ps1`/`conftest.py` but not Go's `*_test.go`
suffix — `docs/hook-manifest.yaml` flags this hook's Go gap explicitly
(`fixed_for_go: false`). Verified live this session, from the repo root:
`sed -i 's/x/y/' modules/foo/bar_test.go` against an existing `bar_test.go`
fixture returns `rc == 0` — the mutation is not recognized as touching a
test file at all, unless the Go file happens to sit under a `/tests/`/
`/test/` path segment.

And, worth repeating from the Scope section because it's the single most
important fact on this page: **`GUARDRAILS_INTEGRATOR_ROLE=1` is a full,
unconditional off-switch for this hook** — anyone able to set that env var
in the agent's shell environment disables test-mutation protection
entirely, by design (the integrator role is trusted to own test edits at
merge). That trust boundary lives outside this hook; the hook itself does
not verify who set the variable, and produces no message or telemetry
signal when the bypass fires — it returns before `load_event()` is ever
called.
