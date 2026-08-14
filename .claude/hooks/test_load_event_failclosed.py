#!/usr/bin/env python3
"""Regression tests for _common.load_event()'s fail-closed behavior on
unparseable stdin (independent oppositional review, finding M4).

BEFORE this fix: load_event() caught every exception raised while reading
or parsing stdin (malformed JSON, invalid UTF-8, an empty stream) and
silently returned {} -- every calling hook's own early-return logic then
treats an empty event as "nothing to check here", i.e. ALLOW. That is the
exact fail-open shape this pack's README condemns for guardrail hooks, and
it disagreed with protect-files.sh, which fails CLOSED on the same kind of
input.

AFTER: an unparseable/undecodable/unreadable stdin now calls block() (exit
2, message names the cause). A SUCCESSFULLY parsed event -- even one that
is empty ({}) or simply doesn't apply to the calling hook -- is unaffected;
json.load() succeeded, so load_event() returns it normally and each hook's
own logic decides. The positive controls below pin that this boundary did
not shift: several hooks correctly receive and ignore events with no
tool_input, or tool_names they don't police, and this fix must not turn
those into blocks.

Direct unit tests against _common.load_event() (not a subprocess
black-box), same pattern as test_emit_event.py -- so the stdin stream can
be constructed precisely, including invalid UTF-8 bytes, which cannot be
expressed as a normal subprocess `input=<str>`.
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".claude", "hooks"))
import _common  # noqa: E402


def _run_load_event(stdin_stream):
    """Run _common.load_event() against `stdin_stream`. Returns
    (exit_code_or_None, result_or_None, stderr_text)."""
    real_stdin = sys.stdin
    sys.stdin = stdin_stream
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            try:
                result = _common.load_event()
                code = None
            except SystemExit as e:
                result = None
                code = e.code
    finally:
        sys.stdin = real_stdin
    return code, result, stderr.getvalue()


# ---------------------------------------------------------------------------
# Negative cases: genuinely unparseable/undecodable/unreadable input MUST block.
# ---------------------------------------------------------------------------

def test_malformed_json_blocks():
    code, _result, err = _run_load_event(io.StringIO("this is not { json at all"))
    assert code == 2, f"malformed JSON must BLOCK (exit 2), got {code!r}: {err}"
    assert err.strip() != "", "block() must write a message naming the cause"
    assert "stdin" in err.lower()


def test_empty_stdin_blocks():
    # json.load("") raises JSONDecodeError ("Expecting value") -- zero bytes
    # is unparseable, not the same thing as a parsed-but-empty `{}` below.
    code, _result, err = _run_load_event(io.StringIO(""))
    assert code == 2, f"empty stdin must BLOCK (exit 2), got {code!r}: {err}"
    assert err.strip() != ""


def test_invalid_utf8_blocks():
    # \xff is not a valid UTF-8 start byte -- .read() raises UnicodeDecodeError.
    bad = io.TextIOWrapper(io.BytesIO(b"\xff\xfe\x00garbage"), encoding="utf-8")
    code, _result, err = _run_load_event(bad)
    assert code == 2, f"invalid UTF-8 stdin must BLOCK (exit 2), got {code!r}: {err}"
    assert err.strip() != ""


def test_unreadable_stdin_blocks():
    class _ExplodingStdin:
        def read(self, *a, **kw):
            raise OSError("stdin is not readable")

    code, _result, err = _run_load_event(_ExplodingStdin())
    assert code == 2, f"an unreadable stdin stream must BLOCK (exit 2), got {code!r}: {err}"
    assert err.strip() != ""


# ---------------------------------------------------------------------------
# Positive controls: a SUCCESSFUL parse must never block, even when the
# event is empty or doesn't apply. This is the boundary M4 is careful about.
# ---------------------------------------------------------------------------

def test_empty_dict_still_allows():
    code, result, err = _run_load_event(io.StringIO("{}"))
    assert code is None, f"a successfully-parsed {{}} event must not block, got exit {code}: {err}"
    assert result == {}


def test_valid_not_applicable_event_still_allows():
    payload = '{"tool_name": "Bash", "tool_input": {"command": "ls"}}'
    code, result, err = _run_load_event(io.StringIO(payload))
    assert code is None, f"a valid, merely-inapplicable event must not block, got exit {code}: {err}"
    assert result["tool_name"] == "Bash"


def test_valid_event_with_no_file_path_still_allows():
    payload = '{"tool_name": "Edit", "tool_input": {}}'
    code, result, err = _run_load_event(io.StringIO(payload))
    assert code is None, f"a valid event missing file_path must not block, got exit {code}: {err}"
    assert result["tool_input"] == {}


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
