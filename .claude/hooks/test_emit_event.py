#!/usr/bin/env python3
"""Regression tests for _common.emit_event() (see docs/telemetry.md for the
wire-format contract this pins).

Direct unit tests against the function (not a subprocess black-box, since
emit_event has no stdin contract of its own — it's a plain helper other hooks
call). Each test points CLAUDE_PROJECT_DIR at an isolated tmp dir so events
land in a throwaway harness_events.jsonl and tests never collide.

Pins:
  - atomic append: N calls -> N well-formed JSON lines, none interleaved/corrupted
  - <4096B truncation: an oversized payload gets shrunk + payload_truncated=True,
    and the final line still fits under MAX_EVENT_LINE_BYTES
  - harness_version memo: subprocess.run (the `git log` call) fires at most once
    per process even across many emit_event() calls
  - the swallow: an unwritable events path must not raise
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".claude", "hooks"))
import _common  # noqa: E402


def _fresh_project_dir():
    d = tempfile.mkdtemp(prefix="htelem-test-")
    os.environ["CLAUDE_PROJECT_DIR"] = d
    _common._HARNESS_VERSION = None  # reset the per-process memo between tests
    return d


def _read_lines(project_dir):
    path = os.path.join(project_dir, ".claude", "hooks", "state", "harness_events.jsonl")
    with open(path, "r", encoding="utf-8") as f:
        return [ln for ln in f.read().splitlines() if ln.strip()]


def test_emit_event_appends_well_formed_line():
    d = _fresh_project_dir()
    try:
        _common.emit_event("hook_fire", source="unit_test", verdict="allow",
                            subject="foo.py", payload={"k": "v"})
        lines = _read_lines(d)
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["schema_v"] == 1
        assert obj["event_type"] == "hook_fire"
        assert obj["source"] == "unit_test"
        assert obj["verdict"] == "allow"
        assert obj["subject"] == "foo.py"
        assert obj["payload"] == {"k": "v"}
        assert obj["payload_truncated"] is False
        assert "ts" in obj and "harness_version" in obj
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_emit_event_default_source_is_caller_stem():
    d = _fresh_project_dir()
    try:
        _common.emit_event("hook_fire", verdict="block")
        obj = json.loads(_read_lines(d)[0])
        # No source passed -> falls back to Path(sys.argv[0]).stem, i.e. this
        # test runner's own script name (pytest / test_emit_event).
        assert obj["source"] == os.path.splitext(os.path.basename(sys.argv[0]))[0]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_emit_event_atomic_append_many_calls_no_interleave():
    d = _fresh_project_dir()
    try:
        n = 200
        for i in range(n):
            _common.emit_event("hook_fire", source="loop", verdict="allow",
                                payload={"i": i})
        lines = _read_lines(d)
        assert len(lines) == n
        seen = set()
        for ln in lines:
            obj = json.loads(ln)  # raises if a line got interleaved/corrupted
            seen.add(obj["payload"]["i"])
        assert seen == set(range(n))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_emit_event_truncates_oversized_payload():
    d = _fresh_project_dir()
    try:
        huge = {"blob": "x" * 20000}
        _common.emit_event("hook_fire", source="unit_test", verdict="block",
                            payload=huge)
        lines = _read_lines(d)
        assert len(lines) == 1
        line_bytes = lines[0].encode("utf-8")
        assert len(line_bytes) < _common.MAX_EVENT_LINE_BYTES
        obj = json.loads(lines[0])
        assert obj["payload_truncated"] is True
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_harness_version_memoized_across_calls():
    d = _fresh_project_dir()
    calls = {"n": 0}
    real_run = _common.subprocess.run

    def counting_run(*args, **kwargs):
        calls["n"] += 1
        return real_run(*args, **kwargs)

    _common.subprocess.run = counting_run
    try:
        _common.emit_event("hook_fire", verdict="allow")
        _common.emit_event("hook_fire", verdict="allow")
        _common.emit_event("hook_fire", verdict="allow")
        assert calls["n"] == 1, f"expected 1 git subprocess call, got {calls['n']}"
    finally:
        _common.subprocess.run = real_run
        shutil.rmtree(d, ignore_errors=True)


def test_emit_event_unwritable_path_does_not_raise():
    # Point CLAUDE_PROJECT_DIR at a plain FILE (not a dir) so
    # os.makedirs(<project>/.claude/hooks/state) hits NotADirectoryError.
    fd, blocker = tempfile.mkstemp(prefix="htelem-blocker-")
    os.close(fd)
    os.environ["CLAUDE_PROJECT_DIR"] = blocker
    _common._HARNESS_VERSION = None
    try:
        _common.emit_event("hook_fire", verdict="block", payload={"x": 1})
        # No exception -> the swallow held. Nothing else to assert; a raise
        # here would fail the test on its own.
    finally:
        os.remove(blocker)


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
