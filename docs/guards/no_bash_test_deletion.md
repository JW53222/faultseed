# no_bash_test_deletion

## What it blocks

A `Bash` command containing `rm`/`git rm` of a path that looks like a test
file or test directory, or a `git mv` that moves a test file OUT of a tests
location.

## Why this shape is worth a gate

`no_test_tampering.py` watches `Edit`/`Write`/`MultiEdit` for a test being
weakened in place, but a wholesale delete via the shell isn't an edit at all
— it never reaches that hook, or any Edit-tool guard. This is exactly how a
2,400-line test file was removed in one `git rm` in this project's own
history: the deletion slipped past every Edit/Write tamper guard because
deletion isn't an Edit. A test suite that shrinks silently is worse than one
that stays red — a red test tells you something is broken; a deleted test
tells you nothing, forever.

## BLOCKED

```
$ echo '{"tool_input":{"command":"rm tests/test_foo.py"}}' | python3 no_bash_test_deletion.py
BLOCKED: this Bash command deletes or moves test files out of the suite.
  - rm tests/test_foo.py
...
$ echo $?
2
```

## ALLOWED

The nearest legitimate thing is not "the same delete with a marker" — a bare
marker on an actual test deletion is explicitly caught as a *different*
violation (see the escape-marker section). The genuine near-miss is the same
marker syntax on a command that was never going to be blocked in the first
place, because its target isn't a test path:

```
$ echo '{"tool_input":{"command":"rm scratch.txt # delete-tests-ok"}}' | python3 no_bash_test_deletion.py
$ echo $?
0
```

Both commands above were run against this tree this session.

## The escape marker

`# delete-tests-ok: <reason>`, checked per-line. A **bare** marker
(`# delete-tests-ok` with nothing after it) on a command that WOULD be
blocked is explicitly caught and produces a distinct "needs a reason"
message rather than silently being treated as no-marker-at-all — this was
tightened on 2026-07-22 after the bare form was found to be a
self-grantable escape hatch with the same shape as the incident that
motivated this hook in the first place.

## Scope

Universal — `Bash` matcher only, no `engine_dirs` gate, no env-var reads. It
cannot go silently inert the way the engine-scoped hooks can; its only
failure surface is its own `_looks_like_test_path()` heuristic missing a
naming convention (see Known limits).

## How we know it fires

`test_bash_marker_reason_required.py`, `test_deletion_*` functions. Run this
session:

```
$ python3 -m pytest .claude/hooks/test_bash_marker_reason_required.py -q
..........                                                              [100%]
10 passed in 0.21s
```
(this file covers both `no_bash_test_deletion.py` and its
`no_bash_test_mutation.py` sibling — 5 `test_deletion_*` functions and 5
`test_mutation_*` functions)

`test_deletion_bare_marker_blocked_with_reason_required_message` plants
`rm tests/test_foo.py # delete-tests-ok` and asserts `returncode == 2` and
`"needs a reason" in r.stderr` — pinning the bare-marker case as its own
distinct block message, not a silent pass-through.

## Known limits

`_looks_like_test_path()` is a fixed convention: a path segment `/tests/` or
`/test/`, a bare `tests`/`test` directory token, or a filename matching
`test_*.py` / `*_test.py` / `*.Tests.ps1` / `conftest.py` (optionally with a
glob). A repo that names or locates its tests differently — no `test_`
prefix, tests colocated as `*.spec.ts`, a `spec/` directory instead of
`tests/` — will not have those paths recognized, and this hook silently
allows their deletion. Concretely, `TEST_FILE_RE` recognizes
`test_*.py`/`*_test.py`/`*.Tests.ps1`/`conftest.py` but not Go's `*_test.go`
convention — `docs/hook-manifest.yaml`'s own entry for this hook flags this
explicitly (`fixed_for_go: false`), unlike its `no_test_tampering.py` and
`no_swallowed_errors.py` siblings, which both have Go-aware detection. A
`git rm modules/foo/bar_test.go` is not recognized as a test deletion by
this hook (the `/tests/`-path-segment rule can still catch it if the Go file
happens to sit under a `/tests/`/`/test/` directory, but the filename-suffix
rule alone will not).

Detection is per simple-command, split on `&&`, `||`, `;`, `|`, and newline —
a "crude but sufficient" split per the hook's own comment. An adversarial
shell construction that hides the delete from this splitter (e.g. inside a
subshell, a variable expansion, or a here-doc passed to another interpreter)
is not something this hook attempts to parse; it is a heuristic over the
literal command string, not a full shell-semantics evaluator.
