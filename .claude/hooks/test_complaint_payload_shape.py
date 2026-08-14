#!/usr/bin/env python3
"""Regression test: subagent_closing_report.py's `complaint` event payload
must emit `changed_outside` / `known_problems` as list[str]. A prior version
emitted them as bare strings (whatever _extract_after returned) -- any
downstream consumer of the telemetry feed that iterates them as lists would
have a non-empty string payload silently iterated per-CHARACTER instead,
filling the complaint feed with single-char garbage.

Black-box: writes a synthetic subagent transcript with a well-formed closing
report, feeds a SubagentStop event to the hook, and inspects the resulting
harness_events.jsonl `complaint` row.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HOOKS_DIR, "subagent_closing_report.py")

CLOSING_REPORT_TEXT = """Did the thing.

**Changed outside the literal request:**
- touched foo.py for an unrelated import fix
- touched bar.py to satisfy the linter

**Known problems not fixed:**
- pre-existing lint warning in baz.py, out of scope
"""


def _write_transcript(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }) + "\n")


def _run():
    d = tempfile.mkdtemp(prefix="htelem-complaint-test-")
    transcript = os.path.join(d, "transcript.jsonl")
    _write_transcript(transcript, CLOSING_REPORT_TEXT)
    ev = json.dumps({
        "agent_transcript_path": transcript,
        "agent_type": "sonnet",
    })
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = d
    env.pop("SKIP_SUBAGENT_CLOSING_REPORT", None)
    proc = subprocess.run([sys.executable, HOOK], input=ev, text=True,
                          capture_output=True, env=env, cwd=HOOKS_DIR)
    events_path = os.path.join(d, ".claude", "hooks", "state", "harness_events.jsonl")
    events = []
    if os.path.exists(events_path):
        with open(events_path) as f:
            events = [json.loads(ln) for ln in f if ln.strip()]
    return proc.returncode, events, d


def test_closing_report_allowed():
    rc, events, d = _run()
    try:
        assert rc == 0, "a well-formed closing report must be allowed"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_complaint_payload_is_list_of_str():
    rc, events, d = _run()
    try:
        complaints = [e for e in events if e.get("event_type") == "complaint"]
        assert len(complaints) == 1, f"expected exactly 1 complaint event, got {len(complaints)}"
        payload = complaints[0]["payload"]
        for key in ("changed_outside", "known_problems"):
            val = payload[key]
            assert isinstance(val, list), f"{key} must be a list, got {type(val).__name__}: {val!r}"
            for item in val:
                assert isinstance(item, str), f"{key} item must be str, got {type(item).__name__}: {item!r}"
            # The regression emitted the raw extracted string; iterating a
            # non-trivial string per-character never yields a multi-char
            # item, so this pins the fix rather than an accidental pass.
            assert any(len(item) > 3 for item in val), (
                f"{key} looks character-split, not line-split: {val!r}"
            )
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_friction_marker_still_a_list():
    # Control: the friction channel was always list[str] and must stay so.
    d = tempfile.mkdtemp(prefix="htelem-complaint-test-")
    try:
        transcript = os.path.join(d, "transcript.jsonl")
        text = CLOSING_REPORT_TEXT + "\n# harness-friction: the FP scan is noisy on main\n"
        _write_transcript(transcript, text)
        ev = json.dumps({"agent_transcript_path": transcript, "agent_type": "sonnet"})
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = d
        env.pop("SKIP_SUBAGENT_CLOSING_REPORT", None)
        subprocess.run([sys.executable, HOOK], input=ev, text=True,
                        capture_output=True, env=env, cwd=HOOKS_DIR)
        events_path = os.path.join(d, ".claude", "hooks", "state", "harness_events.jsonl")
        with open(events_path) as f:
            events = [json.loads(ln) for ln in f if ln.strip()]
        complaint = [e for e in events if e.get("event_type") == "complaint"][0]
        friction = complaint["payload"]["friction"]
        assert isinstance(friction, list)
        assert any("FP scan is noisy" in item for item in friction)
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            fails += 1
            print(f"ERROR {fn.__name__}: {e}")
    raise SystemExit(1 if fails else 0)
