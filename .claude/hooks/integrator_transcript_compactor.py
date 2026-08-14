#!/usr/bin/env python3
"""integrator_transcript_compactor.py — archive + prune the integrator transcript.

Registered on TWO hook events (see settings.json):
  - PreCompact      -> ARCHIVE the full pre-compaction transcript (lossless copy).
  - SessionStart    -> on source in {compact, resume}: PRUNE the live transcript
                       to [header line] + [last compaction summary .. EOF],
                       re-rooted.

ISOLATION: no-op unless GUARDRAILS_INTEGRATOR_ROLE is set truthy (the
integrator session). It never touches any other session's transcript.

Truthiness: loose check (`not in ("", "0", "false", "False")`), matching
_common.py's agent_role() -- this used to be a stricter `== "1"` check while
_common.py's was loose, so the same env value could mean different things in
the two files (e.g. GUARDRAILS_INTEGRATOR_ROLE=true selected the integrator
role in agent_role() but did NOT trigger this hook's archive/prune). Unified
to loose here on the rename: widening what this hook recognizes as "on" can
only ever cause it to run its own maintenance (archive/prune) in a case it
previously skipped -- never the other way around -- and it never blocks
Claude Code (see the module docstring's "Exit 0 always"), so the unification
carries no guard-bypass risk the way the no_bash_test_mutation.py check does.

NOTE: an earlier version of this hook also did SessionStart[resume] "bootstrap
inject" — appending a synthetic user turn telling the integrator to (re)spawn
a polling queue-watcher. That was REMOVED once submission notification moved
to a push mechanism external to this hook (the integrator is now notified of
new work directly, as it arrives). No polling, no synthetic turns needed.
This hook is now pure transcript maintenance.

SAFETY MODEL:
  - PreCompact always snapshots the full file first; prune() also archives
    before mutating. The archive is the recovery path (cp it back over the live
    transcript) if a prune ever makes resume unhappy.
  - Prune keeps the file's first line (the `last-prompt` header) and everything
    from the LAST `isCompactSummary` onward, nulling that entry's parentUuid.

Exit 0 always — a transcript-maintenance hook must never block Claude Code.
"""

import datetime
import json
import os
import pathlib
import shutil
import sys

ARCHIVE_DIR = pathlib.Path.home() / ".claude" / "integrator-transcript-archive"
ARCHIVE_KEEP = 12
PRUNE_MIN_LINES = 200


def _ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def archive(transcript_path: str, session_id: str) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / f"{session_id}-{_ts()}.jsonl"
    shutil.copy2(transcript_path, dest)
    snaps = sorted(ARCHIVE_DIR.glob(f"{session_id}-*.jsonl"))
    for old in snaps[:-ARCHIVE_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    sys.stderr.write(f"[integrator-compactor] archived -> {dest}\n")


def _atomic_write(transcript_path: str, lines) -> None:
    tmp = transcript_path + ".compactor.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp, transcript_path)


def prune(transcript_path: str, session_id: str) -> None:
    with open(transcript_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) < PRUNE_MIN_LINES:
        return

    archive(transcript_path, session_id)

    last_summary_idx = None
    for i, line in enumerate(lines):
        if '"isCompactSummary"' not in line:
            continue
        try:
            if json.loads(line).get("isCompactSummary") is True:
                last_summary_idx = i
        except json.JSONDecodeError:
            continue
    if last_summary_idx is None or last_summary_idx == 0:
        return

    try:
        summary = json.loads(lines[last_summary_idx])
        summary["parentUuid"] = None
        lines[last_summary_idx] = json.dumps(summary, ensure_ascii=False) + "\n"
    except json.JSONDecodeError:
        return

    kept = [lines[0]] + lines[last_summary_idx:]
    _atomic_write(transcript_path, kept)
    sys.stderr.write(
        f"[integrator-compactor] pruned {len(lines)} -> {len(kept)} lines "
        f"(kept header + summary@{last_summary_idx}..EOF)\n"
    )


def main():
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        sys.exit(0)

    if os.environ.get("GUARDRAILS_INTEGRATOR_ROLE", "") in ("", "0", "false", "False"):
        sys.exit(0)

    tpath = ev.get("transcript_path")
    if not tpath or not os.path.isfile(tpath):
        sys.exit(0)
    session_id = ev.get("session_id") or "integrator"
    event = ev.get("hook_event_name", "")
    source = ev.get("source")

    try:
        if event == "PreCompact":
            archive(tpath, session_id)
        elif event == "SessionStart" and source in ("compact", "resume"):
            prune(tpath, session_id)
    except Exception as e:  # never block Claude Code on a maintenance error
        sys.stderr.write(f"[integrator-compactor] non-fatal: {e}\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
