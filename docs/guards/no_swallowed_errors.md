# no_swallowed_errors

## What it blocks

An `Edit`/`Write`/`MultiEdit` that adds an exception handler whose entire
body is a bare `pass` or `...` (Python), an empty/masking `catch {}` or
`-ErrorAction SilentlyContinue`/`Ignore` (PowerShell), or one of several
error-discard shapes (Go) — anywhere in the neighborhood of the edit, not
just the lines actually touched.

## Why this shape is worth a gate

A caught-and-ignored exception is a failure that still happens, just quietly.
The caller believes the operation succeeded; downstream code proceeds on that
false premise, and by the time the actual consequence surfaces — bad data,
a stuck queue, a state machine wedged in an impossible corner — the original
exception is long gone from any log. This is a specific, high-leverage
dishonesty pattern for an agent under pressure to look done: `except:
pass` makes an error message disappear from the terminal in one keystroke,
with no acknowledgment that the underlying problem is still there.

## BLOCKED

```
$ cat ev.json   # {"tool_name":"Write","tool_input":{"file_path":"src/foo.py","content":"def foo():\n    try:\n        risky()\n    except Exception:\n        pass\n"}}
$ CLAUDE_PROJECT_DIR=$PWD python3 .claude/hooks/no_swallowed_errors.py < ev.json
BLOCKED: this edit hides a problem instead of solving it.
  - line 4: `except Exception:` silently swallows an error. Handle it,
    re-raise it, or let it propagate — do not bury it. ...
$ echo $?
2
```

## ALLOWED

The nearest legitimate thing: the identical handler, marked as a deliberate
degrade rather than an unexamined swallow:

```
$ cat ev.json   # same file, except line now reads:
  #   except Exception:  # swallow-ok: deliberate degrade-to-default
$ CLAUDE_PROJECT_DIR=$PWD python3 .claude/hooks/no_swallowed_errors.py < ev.json
$ echo $?
0
```

Both commands above were run against this tree this session, from the repo
root, with `CLAUDE_PROJECT_DIR=$PWD` set only so `_common.emit_event`'s
telemetry writer has a project dir to append to (it lands in the gitignored
`.claude/hooks/state/harness_events.jsonl` — harmless scratch state, not
something that ships). It does not affect the `engine_dirs` scope decision
itself — that's resolved relative to `_common.py`'s own on-disk location,
not `CLAUDE_PROJECT_DIR` (see Scope below). A genuinely unrelated near-miss: a
handler that logs and re-raises is never flagged at all —
`except Exception:\n    logger.warning(...)\n    raise` — because the AST
tier matches only the bare `pass`/`...` body shape (see Known limits).

## The escape marker

`# swallow-ok: <reason>` (PowerShell `<# ... #>`, Go `//`). Handler-aware: it
can sit on the `except` line, the sole `pass`/`...` body line, or a comment
line between them — any of the three natural places a developer would
annotate. A bare `# swallow-ok` with nothing after the colon does not clear
the block (`SWALLOW_OK` requires a non-whitespace captured group).

## Scope

ENGINE-QUALITY for Python/PowerShell: gated on `is_engine_path(path)`, which
reads the `engine_dirs` list from `docs/audit/audit-scope.yaml`. In this tree
that list is the literal placeholder `["src"]` — this is why every probe in
this doc uses a `src/...` path. An edit outside `engine_dirs` is `allow()`ed
before any pattern ever runs. Go gets a separate, narrower scope check
(`_is_go_generated`: `_bindata.go` suffix or a `// Code generated ... DO NOT
EDIT.` marker are exempted) that does **not** consult `engine_dirs` at all —
Go coverage is scoped by "is this a `.go` production file", full stop.

Two env vars change behavior: `GUARDRAILS_STRICT=1` promotes excuse-comment
soft hits (`# TODO: good enough`, `# known issue`) to hard blocks;
`GUARDRAILS_SWALLOW_NEIGHBORS=N` (default `2`) widens or narrows the
sibling-function scan radius.

**If `engine_dirs` doesn't match your repo's real source layout, this hook
silently covers zero code.** Nothing errors, nothing warns — an edit outside
the configured directories is indistinguishable, from the outside, between
"clean" and "never checked." The only way to notice is to deliberately plant
a violation outside `engine_dirs` and confirm it's `allow()`ed when you
expected a block — which is exactly what
`test_engine_scope_gate_both_directions` does (see below).

## How we know it fires

`test_no_swallowed_errors.py`, filed specifically because this hook shipped
in an earlier delivery of this tree with **zero** test coverage. Run this
session:

```
$ python3 -m pytest .claude/hooks/test_no_swallowed_errors.py -q
..........                                                              [100%]
10 passed in 0.24s
```

`test_bare_pass_swallow_blocked` plants the bare-`pass` shape and asserts
`rc == 2`; `test_swallow_ok_marker_on_except_line_allowed` (and its
pass-line/comment-line siblings) assert `rc == 0`;
`test_engine_scope_gate_both_directions` plants the identical violating
content at `src/foo.py` (blocked) and `other/foo.py` (allowed) in one test
function, so the scope-gate pairing can't drift apart into two tests that
silently stop agreeing;
`test_neighborhood_scan_blocks_sibling_swallow_not_touched` plants a swallow
in a sibling function the edit never touches and confirms the neighborhood
scan still blocks it.

## Known limits

The AST tier flags **only** a handler whose entire body is a lone
`pass`/`...` — a handler that does anything else (logs, sets a fallback
value, re-raises with different text) is never flagged by this check, even
if the log message is uninformative or the fallback is silently wrong. This
is a deliberate, narrow shape, stated in the hook's own comments — it is not
a general "does this except block handle the error well" reviewer.

The Go regex tier operates on **added text only**, with no neighborhood scan
— unlike the Python AST tier, an edit that builds a Go swallow around a
touched line (leaving the swallow itself just outside `added`) is not
caught. Go's ignored-second-return shape (`x, _ := call()`) is **soft-only**
(a warning, not a block) because the hook cannot tell, from source text
alone, whether the callee returns `(T, error)` (a real dropped error) or
`(T, bool)` (the ordinary "found" idiom) — this is the one place in the
pack where a warn tier is used deliberately rather than as a shortcut (see
`no_test_tampering.md` for the corresponding, differently-scoped
`_ = err`-shaped discard on the tampering-hook side). Go's `_ = err` bare
discard, by contrast, **is** hard-blocked here, but only when the discarded
identifier's name contains the substring "err" (case-insensitive) — `_ =
count` is never flagged.

`engine_dirs` is a topology-coupled config, not a scan of your repo (see
Scope above) — the placeholder value in this tree (`["src"]`) is a
common-convention guess. If a licensee's source lives under `backend/`,
`app/`, or `lib/` instead, this hook (and `no_type_checking_stub.py`, which
shares the same config) cover nothing until that list is corrected.
