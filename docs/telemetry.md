# What faultseed records about your sessions

Every Python hook in this pack writes one line to a local JSONL file every
time it fires. This is on by default. Read this before you install, not
after you notice the file.

## Where it goes

`.claude/hooks/state/harness_events.jsonl`, relative to your project root
(`_common.py`'s `_events_path()`, `.claude/hooks/_common.py:615-616`, which
joins `project_dir()` — `CLAUDE_PROJECT_DIR` if set, else the repo root
computed from the hook's own location — with `.claude/hooks/state`).

The directory is created on first write (`os.makedirs(..., exist_ok=True)`,
`_common.py:711`) if it doesn't exist yet. Nothing pre-creates it at install
time; the first hook that fires makes it.

**One guard doesn't write here at all.** `protect-files.sh` is bash, not
Python — it never imports `_common.py` and has no telemetry call anywhere
in its source (checked directly: `grep -n "emit_event\|harness_events"
.claude/hooks/protect-files.sh` returns nothing). Its blocks and allows are
real, but you will not find them in this log. The other 8 guards, plus
`integrator_transcript_compactor.py`, are all Python and all go through
`emit_event()`.

## What's in a line

One JSON object per line, written by `emit_event()`
(`.claude/hooks/_common.py:677-745`). Exact fields:

| Field | What it is |
|---|---|
| `schema_v` | Format version, currently `1` (`EVENT_SCHEMA_V`, `_common.py:611`). |
| `ts` | UTC timestamp, ISO 8601, generated at write time. |
| `event_type` | One of `hook_fire`, `agent_spawn`, `complaint`, `dispatch_import_failure` — see below. |
| `source` | The emitting script's filename stem (e.g. `no_test_tampering`), taken from `sys.argv[0]` when not passed explicitly. |
| `verdict` | `block` / `allow` / `warn`, or `null` for event types that don't have one. |
| `session_id` | `CLAUDE_SESSION_ID` env var if set, else best-effort from the hook's own stdin payload; `""` if neither is available. |
| `agent_role` | `"integrator"` if `GUARDRAILS_INTEGRATOR_ROLE` is set to anything other than `""`, `"0"`, `"false"`, `"False"` (`_common.py:305-318`), else `"coding"`. This env var's name changed during this pack's development — `GUARDRAILS_INTEGRATOR_ROLE` is confirmed against current source at the time this doc was written, not carried over from an older note. If another doc in this pack names it differently, trust the source. |
| `subject` | The target file path from the tool call, best-effort; `""` if not applicable. |
| `harness_version` | Short git SHA of the last commit touching `.claude/` in your repo, memoized once per process; `""` if `git` isn't available or the lookup fails. |
| `payload` | Event-specific detail, shape below. |
| `payload_truncated` | `true` if `payload` was cut to fit the size cap (see below). |

**Verified live** (from probes run while writing this doc — install steps in
`INSTALL.md` trigger these same lines):

```json
{"schema_v":1,"ts":"2026-08-14T02:30:46.652659+00:00","event_type":"agent_spawn","source":"workflow_agent_sizing_gate","verdict":null,"session_id":"","agent_role":"coding","subject":"","harness_version":"","payload":{"kind":"workflow","call_count":1,"models":[],"rung":"leaf","worktree":null},"payload_truncated":false}
{"schema_v":1,"ts":"2026-08-14T02:30:46.653534+00:00","event_type":"hook_fire","source":"workflow_agent_sizing_gate","verdict":"allow","session_id":"","agent_role":"coding","subject":"","harness_version":"","payload":{},"payload_truncated":false}
```

## The four event types

- **`hook_fire`** — emitted by every guard's own `block()`/`allow()`
  (`_common.py:84-98`), and once more by `no_swallowed_errors.py` for a
  warn-only soft hit (`no_swallowed_errors.py:644`). `payload` carries the
  block message (block only, truncated to 800 chars) or is empty.
- **`agent_spawn`** — emitted by `agent_sizing_gate.py` (`:130-138`) and
  `workflow_agent_sizing_gate.py` (`:327-336`) on allow. `payload` records
  the model tier, the launch rung, and whether a worktree was requested.
- **`complaint`** — emitted by `subagent_closing_report.py` (`:365-372`)
  on allow. `payload` is the parsed "changed outside scope" / "known
  problems" lists plus any `harness-friction:` note it found.
- **`dispatch_import_failure`** — emitted by `_dispatch.py` itself
  (`_emit_dispatch_event`, `:295-333`), only on the advisory-hook
  import-failure path. This one is written by a small self-contained
  emitter, not `_common.emit_event` — `_dispatch.py` deliberately doesn't
  import `_common.py` for this call, because `_common.py` failing to
  import is one of the things this path exists to report. Its lines match
  the same JSONL shape but omit `agent_role` and `payload_truncated`.

## Size cap and truncation

`MAX_EVENT_LINE_BYTES = 4096` (`_common.py:612`). `_fit_event_line()`
(`_common.py:656-674`) keeps every field except `payload` intact and
truncates `payload` first: if the full line doesn't fit, it re-serializes
with `payload_truncated: true` and a `payload._truncated` string clipped to
whatever room is left. If even that doesn't fit under the cap (pathological
case), the raw bytes are hard-clipped and closed with `}\n`. You will never
see a line over 4096 bytes; you may see one with a visibly cut-off
`payload._truncated` string.

## It never blocks

The entire body of `emit_event()` is wrapped in one `try/except Exception:
pass` (`_common.py:744-745`), marked `# swallow-ok: telemetry must never
block a guardrail`. A failure to write — unwritable path, disk full,
`CLAUDE_PROJECT_DIR` pointed at something that isn't a directory — is
silently absorbed. The guard's own block/allow decision has already been
made and its `sys.exit()` already called by the time `emit_event()` runs
(`block()`/`allow()` call `emit_event()` before `sys.exit()`, `_common.py:91-98`);
telemetry failing does not change or delay that decision.

## Nothing is transmitted anywhere

Every write in this pack is a local `os.open()` / `os.write()` to a file
under your own `.claude/hooks/state/`. Confirmed by reading every hook
source in this delivery: no hook imports `requests`, `urllib`, `socket`, or
any HTTP client. There is no network call anywhere in the event-emission
path. The file stays on your machine unless you move it there yourself.

## It's gitignored

The shipped `.gitignore` (root of this pack) excludes it:

```
# Generated by the hooks at runtime: local telemetry, never transmitted anywhere.
# See docs/telemetry.md.
.claude/hooks/state/
```

If you're merging this pack's `.gitignore` entries into an existing repo
rather than copying the file wholesale, carry this line over — otherwise
your first `git add -A` after installing will stage the telemetry log.
(The same merge also needs `.claude/settings.json` /
`.claude/settings.local.json`, which the same file ignores for a different
reason — see `INSTALL.md`. **`.claude/PROVENANCE.json`, the generator's
sidecar, is NOT in the shipped `.gitignore`** — verified by running
`git add -A -n` after generating settings.json in a scratch repo; it staged
`.claude/PROVENANCE.json` but not `.claude/settings.json` or the state
directory. Add it yourself if you don't want the sidecar committed.)

## Disabling it

```
export SKIP_HARNESS_TELEMETRY=1
```

`emit_event()` checks `SKIP_HARNESS_TELEMETRY` first, before any path
resolution or directory creation (`_common.py:681-691`) — an opted-out
session never creates so much as an empty `state/` directory. Truthiness
matches `SKIP_HOOK_DISPATCH`'s convention: any value **not** in `("", "0",
"false", "False")` opts out; `SKIP_HARNESS_TELEMETRY=false` does not.

This does not touch guard behavior. A guard still blocks or allows exactly
as it would otherwise — `block()`/`allow()` call `emit_event()` for their
own verdict logging and behave identically whether that call returns early
here or falls through to the write (`_common.py:84-98`). Setting this only
stops the JSONL line from being written; it does not weaken any guard.

Verified live, whole `state/` directory removed first so there's nothing
already on disk to mask the result:

```
$ echo '{"tool_name":"Edit","tool_input":{"file_path":"tests/test_foo.py","old_string":"a","new_string":"b"}}' | \
    SKIP_HARNESS_TELEMETRY=1 python3 .claude/hooks/_dispatch.py no_test_tampering.py
$ ls .claude/hooks/state
ls: cannot access '.claude/hooks/state': No such file or directory
$ echo '{"tool_name":"Edit","tool_input":{"file_path":"tests/test_foo.py","old_string":"a","new_string":"b"}}' | \
    python3 .claude/hooks/_dispatch.py no_test_tampering.py
$ cat .claude/hooks/state/harness_events.jsonl
{"schema_v":1,"ts":"2026-08-14T02:41:47.233605+00:00","event_type":"hook_fire","source":"no_test_tampering","verdict":"allow","session_id":"","agent_role":"coding","subject":"tests/test_foo.py","harness_version":"","payload":{},"payload_truncated":false}
```

The two env vars that exist near it, `GUARDRAILS_STRICT` and
`GUARDRAILS_SWALLOW_NEIGHBORS`, tune `no_swallowed_errors.py`'s detection
behavior and have no effect on telemetry — don't confuse them with the
switch above.

## If you're willing to share it

This is a request, not a default, and ignoring it costs you nothing — the
switch above stays the same either way.

There is no field record yet for how often these guards actually fire, on
what, across real installs — that's the aggregate-effectiveness gap the
README's ["What this does not do"](../README.md#what-this-does-not-do)
names openly rather than guessing at. If you're willing to share your
`harness_events.jsonl`, it helps build that record. It does not make your
own install work any differently, and sharing or not sharing has no effect
on any guard's behavior.

Before sharing anything, **read the file first** — you now know what's in
it, since you just read the field list above. A `hook_fire` block event
carries a message that can quote your code (`payload`, truncated to 800
bytes); `subject` carries a file path from your repo. Skim your own
`.claude/hooks/state/harness_events.jsonl`, or grep it for anything you
don't want to hand over, before you send it anywhere.

If you do want to share it, attaching the file to a GitHub issue on this
repo is the route — there is no other collection mechanism, no upload
built into any hook, and none planned. Beyond helping build the field
record described above, nothing further is promised about what happens to
a file you share.

If you'd rather not: `SKIP_HARNESS_TELEMETRY=1`, above, turns the log off
entirely, at any time, with zero effect on guard behavior.

## Cleaning it up

The file is append-only and grows for as long as hooks fire. To clear it:

```
rm .claude/hooks/state/harness_events.jsonl
```

Safe to delete at any time — nothing reads it back, and the next hook that
fires recreates the directory and file (`os.makedirs(..., exist_ok=True)` +
`O_CREAT`, `_common.py:711-712`), unless you've set `SKIP_HARNESS_TELEMETRY`
(above), in which case nothing recreates it. Deleting the whole `state/`
directory is equally safe for the same reason.
