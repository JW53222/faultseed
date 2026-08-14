#!/usr/bin/env python3
"""subagent_closing_report.py  --  SubagentStop hook

Enforces the "Required closing report" rule from
.claude/rules/honesty-guardrails.md on every subagent completion:

  Every coding task ends with two explicit lines:
    1. Changed outside the literal request: ...
    2. Known problems not fixed: ...

If the subagent's transcript shows no co-occurring pair of these markers,
block (exit 2) and force the subagent to address it before completing.

Bonus: if the recent text mentions an `incoming/<branch>` push, fetch the
diff-stat from the blessed tree and append it to the block message —
forces the subagent to confirm every file in the diff is in its stated
scope (or to add the unintended files to the 'Changed outside' list).

Why this exists: prose rules in .claude/rules/ are model-followed only.
A subagent that lies in its closing report ships without machine
pushback. The motivating incident: a worker silently shipped out-of-scope
file deletions while reporting "none outside scope" — the orchestrator
caught it via diff review, but nothing in the harness did. This hook closes
that hole at the hook layer instead of relying on every orchestrator to
remember to diff-check.

Payload (SubagentStop event, per code.claude.com/docs/en/hooks):
  session_id, transcript_path, cwd, agent_id, agent_type

Exit 2 = block (subagent must continue and address). Exit 0 = allow.

Escape: env SKIP_SUBAGENT_CLOSING_REPORT=1 disables the hook entirely.
Use only for debugging where the closing-report rule does not apply.

Auto-exempt: read-only/research subagent types in EXEMPT_AGENT_TYPES
(Explore, Plan) are allowed unconditionally — their deliverable is prose,
not a diff, so there is no code-scope to police. This makes real the
"research-only Explore runs" carve-out the env-var note above always
described but never actually implemented in code (it required the env var,
which is off by default, so Explore agents were blocked and their findings
got stranded behind a footer-only final turn).

----- BUG-FIX HISTORY -----

Single-message scope: the prior version of this hook
only inspected the LAST assistant message in the transcript. An agent
that wrote a perfect closing report in entry N, then dispatched more
subagents (whose tool calls became entries N+1..N+M with no marker
text), still got blocked. Fix: scan ALL assistant text in the transcript
and accept if the two markers co-occur within MARKER_COOCCUR_WINDOW
characters of each other.

Brittle phrasing (same incident): the prior check required the exact
substring 'changed outside the literal request'. Four of twelve agent
attempts wrote `**Changed outside literal request**: none` (no "the").
Fix: regex with optional "the", optional plural "problem(s)", any
surrounding markdown.

Co-occurrence window: 2000 chars guards against FP (one agent paragraph
mentions the rule, another unrelated paragraph mentions the other
marker). A real closing report has them within ~500 chars of each other.
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import load_event, block, allow, emit_event, project_dir

SKIP_ENV = "SKIP_SUBAGENT_CLOSING_REPORT"

# Read-only / research-only subagent types are EXEMPT. Their entire
# deliverable is prose findings, not a diff, so the closing-report rule
# (which is about owning the scope of a code change) does not apply. The
# docstring above has always named "research-only Explore runs" as a
# should-skip case, but the exemption was previously only reachable via the
# SKIP_SUBAGENT_CLOSING_REPORT env var — which is off by default, so Explore
# agents got blocked anyway. The blocked agent then commonly recovered by
# emitting ONLY the bare 'none/none' footer as a fresh final turn; since the
# Agent tool surfaces only a subagent's LAST message to its parent, the
# parent received the footer INSTEAD of the analysis (the findings stayed
# stranded one turn back in the subagent transcript). Branching on
# agent_type here makes the documented carve-out real and kills that
# artifact at the source. These types are read-only by definition (no
# Edit/Write tool), so there is no code-scope to police.
EXEMPT_AGENT_TYPES = frozenset({"Explore", "Plan"})

# Tolerant of common phrasing drift: optional "the" between "outside" and
# "literal request", optional plural "problem(s)", intervening whitespace.
# Surrounding markdown bold/italic markers don't interfere because we apply
# the regex over raw text without stripping them — the keywords still match.
#
# STRUCTURAL REQUIREMENT:
# The marker phrase MUST be followed by a structural separator
# (`:`, `:**`, `—`, `-`) before any value text. This rejects conjunctive
# prose like "...include the Changed outside the literal request and
# Known problems not fixed sections at the end" — the previous version
# allowed any agent who paraphrased the rule during planning to satisfy
# the hook without writing an actual closing report. A real report
# uses a colon to introduce the value; planning prose uses "and".
MARKER_CHANGED_RE = re.compile(
    r"changed\s+outside\s+(?:the\s+)?literal\s+request[*\s]*[:\-—]",
    re.IGNORECASE,
)
MARKER_KNOWN_RE = re.compile(
    r"known\s+problems?\s+not\s+fixed[*\s]*[:\-—]",
    re.IGNORECASE,
)
# Both markers must co-occur within this character window. Guards against
# incidental mentions in unrelated paragraphs (e.g. an agent quoting the
# rule earlier in the transcript). A real closing report has them within a
# few hundred chars of each other.
MARKER_COOCCUR_WINDOW = 2000
# How many of the most-recent non-empty assistant text blocks to scan for
# markers. The closing report is by definition at the END of the work —
# restricting to recent blocks guards against an agent who mentions the
# markers in EARLY planning prose then never writes a real closing report.
# K=10 leaves headroom for "write report, then 5-10 brief follow-ups or
# subagent dispatches" (the motivating case for RECENT_BLOCKS_TO_SCAN),
# without sweeping in arbitrary mid-task planning.
RECENT_BLOCKS_TO_SCAN = 10

# Deliberate friction channel: an agent may flag harness friction (slow,
# false-positive'd, confusing) inline with `# harness-friction: <text>` or
# `**harness-friction**: <text>`. Captured into the `complaint` event
# payload, not penalized — see .claude/rules/honesty-guardrails.md
# closing-report section.
FRICTION_RE = re.compile(
    r"(?:#\s*harness-friction|\*\*harness-friction\*\*)\s*:\s*(.+)",
    re.IGNORECASE,
)

BRANCH_RE = re.compile(r"\bincoming/[A-Za-z0-9_./-]+")

# Cap how many branch diffstats we surface (limit hook output).
MAX_BRANCHES = 3
DIFFSTAT_TIMEOUT_S = 5


def _read_assistant_text_blocks(transcript_path):
    """Return a list of non-empty assistant text strings, in chronological
    order. Each entry corresponds to one assistant text block. Returns []
    if we can't read or parse the transcript.

    We deliberately collect EVERY block (not just the last assistant
    message's text) because subagents commonly write the closing report,
    then dispatch more sub-subagents whose tool_use blocks become the
    latest assistant entries. Restricting to the last message produced
    FN blocks on legitimate reports (see BUG-FIX HISTORY above).

    The caller restricts to the LAST RECENT_BLOCKS_TO_SCAN before checking
    markers — so the rule is "closing report must be in the recent end of
    the transcript", not "anywhere in the transcript ever". That guards
    against the FP where an agent mentions the rule in early planning
    prose then never writes an actual closing report.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return []
    blocks = []
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                msg = obj.get("message") if isinstance(obj, dict) else None
                if not isinstance(msg, dict):
                    msg = obj if isinstance(obj, dict) else None
                if not msg or msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    if content.strip():
                        blocks.append(content)
                elif isinstance(content, list):
                    parts = []
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            t = b.get("text")
                            if isinstance(t, str):
                                parts.append(t)
                    joined = "\n".join(parts).strip()
                    if joined:
                        blocks.append(joined)
    except Exception:
        return []
    return blocks


def _markers_present(text_blocks):
    """Given a chronological list of non-empty assistant text blocks,
    return (ok, missing_list). ok=True iff both markers (each followed by
    a structural separator like ':' or '—') co-occur within
    MARKER_COOCCUR_WINDOW characters of each other inside the LAST
    RECENT_BLOCKS_TO_SCAN blocks. missing_list names what specifically
    was wrong so the block message can explain.
    """
    if not text_blocks:
        return False, ["no-text"]
    # Look only at the recent end of the transcript — closing report is by
    # definition at the end. Restricts FP from early planning prose.
    recent = "\n\n".join(text_blocks[-RECENT_BLOCKS_TO_SCAN:])

    changed_positions = [m.start() for m in MARKER_CHANGED_RE.finditer(recent)]
    known_positions = [m.start() for m in MARKER_KNOWN_RE.finditer(recent)]

    missing = []
    if not changed_positions:
        missing.append("changed-outside-scope")
    if not known_positions:
        missing.append("known-not-fixed")
    if missing:
        return False, missing

    # Both markers exist — check co-occurrence within the window.
    for cp in changed_positions:
        for kp in known_positions:
            if abs(cp - kp) <= MARKER_COOCCUR_WINDOW:
                return True, []
    # Present but never near each other — likely incidental mentions.
    return False, ["markers-present-but-not-paired"]


def _blessed_root():
    # project_dir() already resolves CLAUDE_PROJECT_DIR with a structural
    # __file__-relative fallback -- no hardcoded literal needed here.
    return project_dir()


def _diffstat(branch):
    """Return `git diff --stat` of what the BRANCH changed since its fork point.

    Uses `main...branch` (3-dot, symmetric / merge-base..branch), NOT
    `main..branch` (2-dot). The 2-dot form shows everything different
    between the two endpoints, so files added to main AFTER the branch's
    fork point appear as "deletions" in the branch's diff — the
    diff-vs-merge-tree gotcha. The 3-dot form shows only what the branch
    actually added/removed since diverging, which is what "did the worker
    stay in scope" needs."""
    root = _blessed_root()
    try:
        out = subprocess.check_output(
            ["git", "-C", root, "diff", "--stat", f"main...{branch}"],
            stderr=subprocess.DEVNULL,
            timeout=DIFFSTAT_TIMEOUT_S,
        ).decode("utf-8", errors="replace")
        return out.strip()
    except Exception:
        return None


def _extract_after(text, match_end, stop_positions, cap=500):
    """Best-effort value text following a marker's match end: stop at the
    nearest later stop position (the other marker) or a blank-line paragraph
    break, capped at `cap` chars. Used only to populate the telemetry
    `complaint` payload — never affects the block/allow verdict."""
    later_stops = [p for p in stop_positions if p > match_end]
    end = min(later_stops) if later_stops else len(text)
    para_break = text.find("\n\n", match_end)
    if para_break != -1 and para_break < end:
        end = para_break
    end = min(end, match_end + cap)
    return text[match_end:end].strip(" \n:*-\u2014")


def _extract_friction(text_blocks):
    """Scan ALL text blocks for `# harness-friction: <text>` /
    `**harness-friction**: <text>` markers. Returns a bounded list of notes."""
    friction = []
    for block_text in text_blocks:
        for m in FRICTION_RE.finditer(block_text):
            note = m.group(1).strip()
            if note:
                friction.append(note[:300])
    return friction[:20]


def _split_into_items(text):
    """Split extracted closing-report text into a list[str] (one per line /
    bullet), stripping leading bullet/number markers. A single-paragraph
    (no line breaks) extraction falls back to a one-element list. Empty text
    -> []. Any downstream consumer of the telemetry payload that expects
    known_problems/changed_outside as LISTS would iterate a bare scalar
    string per-CHARACTER instead, which this guards against."""
    text = (text or "").strip()
    if not text:
        return []
    items = []
    for raw in re.split(r"\n+", text):
        s = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", raw).strip()
        if s:
            items.append(s)
    return items if items else [text]


def main():
    if os.environ.get(SKIP_ENV) == "1":
        allow()

    event = load_event()

    # Research-only subagents (Explore, Plan) produce prose, not diffs —
    # the closing-report rule has no code-scope to police, and blocking them
    # strands their findings behind a footer-only final turn (see
    # EXEMPT_AGENT_TYPES note above). Allow before doing any transcript work.
    agent_type = event.get("agent_type") or event.get("subagent_type") or ""
    if agent_type in EXEMPT_AGENT_TYPES:
        allow()

    # SubagentStop events expose TWO transcript paths (Claude Code added
    # `agent_transcript_path` for the Agent-tool subagent split):
    #   - `transcript_path`        — the PARENT session's JSONL
    #   - `agent_transcript_path`  — the SUBAGENT's own JSONL
    # The subagent's closing report only ever lives in the subagent's file
    # (the parent transcript sees the Agent tool's result block, not the
    # subagent's per-turn assistant text). Before this fix the hook read
    # `transcript_path` (parent) and so could never find the markers — it
    # blocked every honest worker on every SubagentStop regardless of
    # whether the closing report was actually correct, and in at least one
    # case a worker stuck in that false-block loop escalated into an
    # audit-tampering attempt trying to get past it.
    # Prefer the agent-specific path when present; fall back to the legacy
    # `transcript_path` for Stop-event compatibility / older harness versions.
    transcript_path = (
        event.get("agent_transcript_path")
        or event.get("transcript_path")
        or os.environ.get("CLAUDE_TRANSCRIPT_PATH")
    )
    blocks = _read_assistant_text_blocks(transcript_path)
    # Defensive: if for any reason we can't recover blocks from the subagent
    # file, the event payload itself carries `last_assistant_message` (the
    # subagent's final text). Use it so we still grade on real subagent text
    # instead of degrading to "no markers found, block" against the parent.
    if not blocks:
        lam = event.get("last_assistant_message")
        if isinstance(lam, str) and lam.strip():
            blocks = [lam]

    if not blocks:
        # We couldn't read the transcript or it had no assistant text —
        # don't block (would FP on every agent flow whose transcript
        # shape we don't recognize, or non-coding agents like Explore).
        allow()

    ok, missing = _markers_present(blocks)
    if ok:
        recent = "\n\n".join(blocks[-RECENT_BLOCKS_TO_SCAN:])
        changed_positions = [m.end() for m in MARKER_CHANGED_RE.finditer(recent)]
        known_positions = [m.end() for m in MARKER_KNOWN_RE.finditer(recent)]
        changed_text = (
            _extract_after(recent, changed_positions[0], known_positions)
            if changed_positions else ""
        )
        known_text = (
            _extract_after(recent, known_positions[0], changed_positions)
            if known_positions else ""
        )
        emit_event(
            "complaint",
            payload={
                "changed_outside": _split_into_items(changed_text),
                "known_problems": _split_into_items(known_text),
                "friction": _extract_friction(blocks),
            },
        )
        allow()

    # Pull branch references from the recent blocks only — these are the
    # branches the subagent is claiming to have pushed.
    recent_text = "\n\n".join(blocks[-RECENT_BLOCKS_TO_SCAN:])
    branches = sorted(set(BRANCH_RE.findall(recent_text)))[:MAX_BRANCHES]
    diff_sections = []
    for b in branches:
        ds = _diffstat(b)
        if ds:
            diff_sections.append(f"\n--- git diff --stat main...{b} ---\n{ds}")

    lines = [
        "BLOCKED: your closing report is missing required honesty-guardrail lines.\n"
    ]
    for m in missing:
        if m == "changed-outside-scope":
            lines.append(
                "  - missing: 'Changed outside the literal request: ...' "
                "(write 'none' if you touched nothing beyond scope; the "
                "phrase must be followed by a colon, not 'and')"
            )
        elif m == "known-not-fixed":
            lines.append(
                "  - missing: 'Known problems not fixed: ...' "
                "(write 'none' if you fixed everything you noticed; the "
                "phrase must be followed by a colon, not 'and')"
            )
        elif m == "markers-present-but-not-paired":
            lines.append(
                "  - both markers appear in your recent output, but never within "
                f"{MARKER_COOCCUR_WINDOW} characters of each other — write "
                "them together as a paired closing block at the END of your "
                "final message."
            )
        elif m == "no-text":
            lines.append(
                "  - your assistant transcript has no recoverable text "
                "blocks (only tool_use). Write a final text reply that "
                "includes the closing report."
            )
    lines.append(
        "\nPer .claude/rules/honesty-guardrails.md 'Required closing report', "
        "every coding task MUST end with two explicit lines:\n"
        "  1. **Changed outside the literal request** — anything you touched "
        "beyond what was asked (write 'none' if empty).\n"
        "  2. **Known problems not fixed** — anything you noticed but did not "
        "solve, and why (write 'none' if empty).\n"
        "If both are honestly 'none', say so explicitly.\n"
        "Phrasing is flexible: `**Changed outside literal request**` "
        "(without 'the') is accepted, as are minor wording variants. The "
        "two lines must appear together at the end of your final reply."
    )
    if diff_sections:
        lines.append(
            "\nYou referenced pushed branch(es) in your recent output. The "
            "diff-stat from blessed is below — confirm EVERY file listed is in "
            "your stated scope, or move it to the 'Changed outside' list. "
            "A prior worker run shipped out-of-scope file deletions while "
            "reporting 'none outside scope'; this surface exists to make that "
            "kind of dishonesty hook-blocked rather than orchestrator-caught."
        )
        lines.extend(diff_sections)

    block("\n".join(lines))


if __name__ == "__main__":
    main()
