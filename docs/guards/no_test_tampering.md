# no_test_tampering

## What it blocks

An `Edit`/`Write`/`MultiEdit` to a recognized test file that adds a blanket
skip/xfail marker, a no-op assertion, or removes real assertions without
replacing them with something that checks anything.

## Why this shape is worth a gate

The fastest way for an agent to turn a red test suite green is to stop the
test from running, rather than fix the code it's testing. `@pytest.mark.skip`,
`assert True`, or quietly deleting the assertion that was failing all produce
the same outward signal — a passing CI run — while the underlying defect
ships untouched. A human reviewing a diff full of source changes and test
churn together is far less likely to notice one skip decorator slipped in
than they are to notice a wholesale test deletion; this is the shape that
turns a real bug into a shipped regression nobody flagged.

## BLOCKED

```
$ echo '{"tool_input":{"file_path":"tests/test_example.py","old_string":"    assert a == 1","new_string":"    pass"}}' \
  | python3 no_test_tampering.py
BLOCKED: this edit weakens a test instead of fixing the code under test.
  - removes 1 assertion(s) and adds back only 0
...
$ echo $?
2
```

## ALLOWED

The nearest legitimate thing: the same assertion is removed, but the edit
carries a marker naming the code change that justifies it — not a skip, an
honest replacement:

```
$ echo '{"tool_input":{"file_path":"tests/test_example.py","old_string":"    assert a == 1","new_string":"    foo()  # tampering-ok: justified by the corresponding code change"}}' \
  | python3 no_test_tampering.py
$ echo $?
0
```

Both commands above were run against this tree this session. A genuinely
unrelated near-miss is a *conditional* skip: `@pytest.mark.skipif(sys.platform
== "win32", reason="posix-only")` is never flagged — `skipif` always carries a
condition, so it cannot blanket-skip the way bare `skip`/`xfail` can (the
negative-lookahead `(?!if)` in `SKIP_PATTERNS` is what makes that
distinction).

## The escape marker

`# tampering-ok: <reason>` (PowerShell: `<# tampering-ok: <reason> #>`; Go:
`// tampering-ok: <reason>`), on the offending line for a skip/no-op hit, or
one per net-removed assertion for the assertion-removal heuristic — a single
marker no longer waives a multi-assertion deletion in the same edit (a
tombstone-bypass fix). `TAMPERING_OK`'s regex requires a non-whitespace
character after the colon; a bare `# tampering-ok` with nothing after it does
not clear the block.

This marker is not a private escape hatch: per
`.claude/rules/honesty-guardrails.md`, an integrator independently re-checks
at merge time that the stated reason actually matches the code change in the
diff.

## Scope

Universal — no `engine_dirs` gate. It fires on any path `is_test_file()`
recognizes, anywhere in the tree: basename starts `test_`, ends
`_test.py`/`_test.go`, path contains `/tests/` or `/test/`, basename is
`conftest.py`, or ends `.tests.ps1`. That naming convention is fixed in
`_common.py`, not configurable — see Known limits.

## How we know it fires

`test_no_test_tampering_marker_count.py`, 16 test functions. Run this
session, from the repo root:

```
$ python3 -m pytest .claude/hooks/test_no_test_tampering_marker_count.py -q
................                                                        [100%]
16 passed in 0.31s
```

`test_two_asserts_removed_one_marker_blocked` plants two removed asserts with
only one marker and asserts `rc == 2`; `test_go_blanket_skip_blocked_and_conditional_skip_allowed`
plants a bare `t.Skip(...)` (blocked) and the `if testing.Short() { t.Skip(...) }`
guarded form (allowed) in the same function.

## Known limits

`is_test_file()` is a fixed naming convention, not configurable — if your
repo names test files something else (no `test_` prefix, tests colocated
without a `/tests/` path segment, a non-`.py`/`.go`/`.ps1` test runner), this
hook silently protects nothing on those files. Nothing tells you when this
happens; the hook simply never runs its pattern checks because `is_test_file`
returned `False` before any of them execute.

The Go blanket-skip guard heuristic only ever sees the text one edit actually
touches (`added_text`), never the whole file. If an edit modifies only the
`t.Skip(...)` line inside an already-existing, untouched `if` guard written in
an earlier commit, the guard line never appears in the diff, and the
heuristic misclassifies the addition as blanket — a false-positive block, not
a false-negative bypass. The hook's own docstring calls this out explicitly
and treats it as an acceptable asymmetry: the cost of a false block is one
`// tampering-ok:` line, versus building full-file parsing for a line-diff-only
design.

The `_ = <var>` Go discard pattern deliberately requires a bare identifier
with nothing else on the line, to avoid false-positiving on the legitimate
`_ = someCall()` discard-a-call-result idiom — so `_ = someCall()` is never
flagged by this hook. `no_swallowed_errors.py` has its own, separately-scoped
Go `_ = err` discard check (hard-blocked there, but only when the discarded
identifier's name contains "err") — the two hooks' Go coverage does not fully
overlap; see that guard's own limits for what it does and does not catch.
