#!/usr/bin/env python3
"""Regression tests for subagent_closing_report.py's BLOCK path.

test_complaint_payload_shape.py already covers the ALLOW path (a well-formed
closing report -> exit 0 + correctly-shaped `complaint` telemetry). This file
covers what that sibling does not: a control that has only ever been shown
to accept has not been shown to do anything. Every test here plants a
transcript that SHOULD be rejected and asserts the block (exit 2).

Black-box: writes a synthetic subagent transcript, feeds a SubagentStop event
to the real (unmodified) subagent_closing_report.py over stdin, and asserts
on returncode + stderr content. Uses pytest's tmp_path fixture for isolation
and points CLAUDE_PROJECT_DIR at it so _common.emit_event's telemetry writer
never touches this repo's real .claude/hooks/state/harness_events.jsonl.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
HOOK = HOOKS_DIR / "subagent_closing_report.py"

# Structurally valid markers (colon immediately after the phrase) -- pulled
# from the hook's own docstring example / MARKER_*_RE requirements.
CHANGED_MARKER = "**Changed outside the literal request:** none"
KNOWN_MARKER = "**Known problems not fixed:** none"


def _write_transcript(path: Path, text: str) -> None:
    """One assistant-role JSONL line whose content is a single text block --
    matches the sibling test's fixture shape."""
    path.write_text(
        json.dumps({
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }) + "\n",
        encoding="utf-8",
    )


def _run(event: dict, project_dir: Path, env_extra=None):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.pop("SKIP_SUBAGENT_CLOSING_REPORT", None)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(event), text=True,
        capture_output=True, env=env, cwd=HOOKS_DIR, timeout=30,
    )
    return proc.returncode, proc.stderr


# ---------------------------------------------------------------------------
# The planted failure: no markers at all.
# ---------------------------------------------------------------------------

def test_no_markers_at_all_blocks_naming_both_missing(tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(
        transcript,
        "I did the thing, all good. Everything looks fine and I verified it manually.",
    )
    rc, err = _run(
        {"agent_transcript_path": str(transcript), "agent_type": "sonnet"},
        tmp_path / "proj",
    )
    assert rc == 2, f"marker-less transcript must BLOCK, got {rc}: {err}"
    assert "BLOCKED: your closing report is missing required honesty-guardrail lines" in err
    assert "Changed outside the literal request" in err
    assert "Known problems not fixed" in err


# ---------------------------------------------------------------------------
# One marker present, the other missing -- still blocked, and the block
# message must name only the ONE actually missing (proves the hook really
# recognized the present marker, not just "found nothing at all").
# ---------------------------------------------------------------------------

def test_changed_present_known_missing_still_blocked(tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(
        transcript,
        f"{CHANGED_MARKER}\n\nI verified everything else works, no other notes.",
    )
    rc, err = _run(
        {"agent_transcript_path": str(transcript), "agent_type": "sonnet"},
        tmp_path / "proj",
    )
    assert rc == 2, f"one marker missing must still BLOCK, got {rc}: {err}"
    assert "missing: 'Known problems not fixed" in err
    assert "missing: 'Changed outside the literal request" not in err


def test_known_present_changed_missing_still_blocked(tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(
        transcript,
        f"Did the work. {KNOWN_MARKER}",
    )
    rc, err = _run(
        {"agent_transcript_path": str(transcript), "agent_type": "sonnet"},
        tmp_path / "proj",
    )
    assert rc == 2, f"one marker missing must still BLOCK, got {rc}: {err}"
    assert "missing: 'Changed outside the literal request" in err
    assert "missing: 'Known problems not fixed" not in err


# ---------------------------------------------------------------------------
# Both markers present but separated by more than MARKER_COOCCUR_WINDOW
# (2000 chars, per subagent_closing_report.py) -- blocked, distinct message.
# ---------------------------------------------------------------------------

def test_markers_present_but_beyond_cooccurrence_window_blocked(tmp_path):
    filler = "filler " * 400  # 2800 chars, comfortably over the 2000-char window
    text = f"{CHANGED_MARKER}\n\n{filler}\n\n{KNOWN_MARKER}"
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, text)
    rc, err = _run(
        {"agent_transcript_path": str(transcript), "agent_type": "sonnet"},
        tmp_path / "proj",
    )
    assert rc == 2, f"markers too far apart must BLOCK, got {rc}: {err}"
    assert "never within 2000 characters of each other" in err


# ---------------------------------------------------------------------------
# Prose-vs-structural: conjunctive prose that MENTIONS both phrases without
# a structural separator must NOT satisfy the gate. Real past bug (see the
# STRUCTURAL REQUIREMENT fix in the hook's own BUG-FIX HISTORY section).
# ---------------------------------------------------------------------------

def test_conjunctive_prose_mentioning_both_phrases_does_not_satisfy_gate(tmp_path):
    text = (
        "For a complete report I need to include the Changed outside the "
        "literal request and Known problems not fixed sections at the end "
        "of this message, so future readers know what happened."
    )
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, text)
    rc, err = _run(
        {"agent_transcript_path": str(transcript), "agent_type": "sonnet"},
        tmp_path / "proj",
    )
    assert rc == 2, (
        f"conjunctive prose mentioning both phrases (no colon separator) must "
        f"NOT satisfy the gate, got {rc}: {err}"
    )
    # Neither regex matched at all (prose, not a real report) -- both named missing.
    assert "Changed outside the literal request" in err
    assert "Known problems not fixed" in err


# ---------------------------------------------------------------------------
# Exemptions, pinned as exemptions (not accidents of transcript content).
# ---------------------------------------------------------------------------

def test_exempt_agent_types_allowed_despite_marker_less_transcript(tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "Findings only, no markers here at all.")
    for exempt_type in ("Explore", "Plan"):
        rc, err = _run(
            {"agent_transcript_path": str(transcript), "agent_type": exempt_type},
            tmp_path / f"proj-{exempt_type}",
        )
        assert rc == 0, (
            f"agent_type={exempt_type!r} must be exempt even with no markers, "
            f"got {rc}: {err}"
        )

    # Contrast: the SAME marker-less transcript with a non-exempt agent_type
    # must block -- proves the allow above is the exemption firing, not the
    # transcript coincidentally passing.
    rc_non_exempt, err_non_exempt = _run(
        {"agent_transcript_path": str(transcript), "agent_type": "sonnet"},
        tmp_path / "proj-nonexempt",
    )
    assert rc_non_exempt == 2, (
        f"non-exempt agent_type with the same marker-less transcript must "
        f"block, got {rc_non_exempt}: {err_non_exempt}"
    )


def test_skip_env_disables_hook_entirely(tmp_path):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, "No markers here either.")
    ev = {"agent_transcript_path": str(transcript), "agent_type": "sonnet"}

    rc_skip, err_skip = _run(ev, tmp_path / "proj-skip", env_extra={
        "SKIP_SUBAGENT_CLOSING_REPORT": "1",
    })
    assert rc_skip == 0, f"SKIP_SUBAGENT_CLOSING_REPORT=1 must disable the hook, got {rc_skip}: {err_skip}"

    # Contrast: without the skip env, the identical event blocks -- proves
    # the allow above is the escape hatch firing, not a coincidence.
    rc_noskip, err_noskip = _run(ev, tmp_path / "proj-noskip")
    assert rc_noskip == 2, (
        f"without the skip env the identical event must block, got "
        f"{rc_noskip}: {err_noskip}"
    )


# ---------------------------------------------------------------------------
# Transcript-path selection: prefers the subagent's OWN transcript
# (agent_transcript_path) over the parent's (transcript_path) -- a
# documented past bug (see subagent_closing_report.py's own BUG-FIX HISTORY:
# the hook used to read the PARENT transcript, which never has the
# subagent's own closing report, and blocked every honest worker).
# ---------------------------------------------------------------------------

def test_prefers_own_transcript_over_parent(tmp_path):
    # Direction 1: agent's own transcript HAS the report, parent's does not.
    # If the hook wrongly preferred the parent, this would block.
    agent_own = tmp_path / "agent_own.jsonl"
    _write_transcript(agent_own, f"{CHANGED_MARKER}\n\n{KNOWN_MARKER}")
    parent = tmp_path / "parent.jsonl"
    _write_transcript(parent, "Parent session text, no markers, unrelated content.")

    rc_allow, err_allow = _run(
        {
            "agent_transcript_path": str(agent_own),
            "transcript_path": str(parent),
            "agent_type": "sonnet",
        },
        tmp_path / "proj-allow",
    )
    assert rc_allow == 0, (
        f"agent's own transcript has a valid report; must ALLOW regardless "
        f"of the parent's content, got {rc_allow}: {err_allow}"
    )

    # Direction 2: agent's own transcript does NOT have the report, parent's
    # does. If the hook fell back to the parent whenever its own transcript
    # were merely inadequate (rather than absent), this would wrongly allow.
    agent_own_bad = tmp_path / "agent_own_bad.jsonl"
    _write_transcript(agent_own_bad, "Own transcript text, no markers.")
    parent_good = tmp_path / "parent_good.jsonl"
    _write_transcript(parent_good, f"{CHANGED_MARKER}\n\n{KNOWN_MARKER}")

    rc_block, err_block = _run(
        {
            "agent_transcript_path": str(agent_own_bad),
            "transcript_path": str(parent_good),
            "agent_type": "sonnet",
        },
        tmp_path / "proj-block",
    )
    assert rc_block == 2, (
        f"agent's own transcript lacks the report; must BLOCK even though "
        f"the parent's has one -- the parent must never be consulted when "
        f"agent_transcript_path is present, got {rc_block}: {err_block}"
    )


if __name__ == "__main__":
    import inspect
    import tempfile
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        params = inspect.signature(fn).parameters
        try:
            if "tmp_path" in params:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            fails += 1
            print(f"ERROR {fn.__name__}: {e}")
    raise SystemExit(1 if fails else 0)
