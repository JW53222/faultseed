#!/usr/bin/env python3
"""integrator_transcript_compactor.py — archive + prune the integrator transcript.

NOT A GUARD: this hook never denies a tool call (see _dispatch.py's
_ADVISORY_HOOKS), and it copies session transcripts under $HOME
(see ARCHIVE_DIR below) when active. Because of both of those, it is
excluded from the `python_default` target in docs/hook-manifest.yaml
(`profiles: {python: false}` on its entry) -- it does NOT ship wired by
default. See the independent oppositional review, findings L1/L2.

AS SHIPPED, this module implements TWO code paths but only ONE is wired to
any hook event:
  - PreCompact      -> ARCHIVE the full pre-compaction transcript (lossless
                       copy). This is the ONLY event docs/hook-manifest.yaml
                       declares for this hook (see its `events:` list) --
                       and, per the exclusion above, even this is not part
                       of python_default's generated settings.json; a
                       downstream user must wire it explicitly (e.g. flip
                       the manifest override to `profiles: {python: true}`,
                       or add the PreCompact binding to their own
                       settings.json directly) to get archiving at all.
  - SessionStart    -> would PRUNE the live transcript (on source in
                       {compact, resume}) to [header line] + [last
                       compaction summary .. EOF], re-rooted. `prune()`
                       below is real and unit-tested, but SessionStart
                       appears NOWHERE in docs/hook-manifest.yaml or in any
                       settings.json this repo's generator can produce --
                       so this path, which is the one that MUTATES the live
                       transcript, is UNREACHABLE via any wiring this pack
                       ships. It only runs if a downstream integrator
                       registers this same module on SessionStart in a
                       settings.json of their own, outside this pack.

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

# UNDISCLOSED-ELSEWHERE $HOME WRITE (independent oppositional review, finding
# L2): this hook copies the FULL transcript -- prompts, tool calls, tool
# output -- into the invoking user's home directory whenever it runs
# (gated by GUARDRAILS_INTEGRATOR_ROLE, see the module docstring's
# ISOLATION note; inert otherwise). No user-facing doc besides this comment
# and the module docstring above states that plainly. Anyone wiring this
# hook should know their session transcripts land on local disk outside the
# project tree, retained up to ARCHIVE_KEEP snapshots per session_id.
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
            pass  # swallow-ok: this only prunes OLD retained snapshots beyond
            # ARCHIVE_KEEP; the fresh archive() copy this call is protecting
            # (shutil.copy2 above) has already succeeded by this point, so a failure
            # here just leaves one extra old snapshot on disk instead of losing data,
            # and this hook's contract (see module docstring) is "exit 0 always" --
            # a maintenance hook must never block Claude Code over disk cleanup.
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
