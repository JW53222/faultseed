#!/usr/bin/env python3
"""Planted-failure test for the jq fail-open defect in protect-files.sh.

BEFORE the fix: protect-files.sh parsed its stdin event with a bare
`jq -r '.tool_input.file_path // empty'` and never checked whether jq
itself succeeded. On a machine without jq (or with a jq that errors when
invoked), the command substitution still completes -- bash captures
whatever landed on stdout, which is nothing -- so FILE_PATH ends up empty,
and the pre-existing `if [[ -z "$FILE_PATH" ]]; then exit 0; fi` guard
(there to legitimately allow tool calls with no file_path at all, e.g. a
Bash tool call) treated "jq is broken" identically to "this event has no
file path." Reproduced with a stub jq on PATH that prints
"jq: command not found" and exits 127: the guard exited 0 and PERMITTED a
Write to `.env`.

This file plants that failure two ways -- jq entirely absent from PATH,
and a jq present but broken (the exact stub from the bug report) -- and
asserts the FIXED guard now BLOCKS (exit 2) and names jq in its message,
instead of silently falling through to the empty-file_path allow path.

Positive controls confirm the fix didn't just start blocking everything:
real jq must still block `.env` FOR THE STATED REASON (the protected-
pattern message, not just any exit 2), and must still ALLOW a genuinely
non-matching path and a genuinely path-less event. Without the
right-reason check, a mutant that blocks unconditionally would pass a
bare "returncode == 2" assertion -- see the mutation-check notes on each
test function below for what was actually run to verify this file's own
sensitivity to that failure mode.
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile

import pytest

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HOOKS_DIR, "protect-files.sh")

# Resolve bash's own full path ONCE, from the real (unmodified) PATH, so
# tests that strip jq's directory out of PATH can still invoke the
# interpreter itself -- subprocess.run(["bash", ...]) would otherwise also
# need PATH to find "bash", and a test that accidentally breaks the
# ability to find bash would not be testing what it claims to test.
BASH = shutil.which("bash") or "/bin/bash"

REAL_JQ = shutil.which("jq")


def _run(payload, env, hook=HOOK):
    ev = json.dumps(payload)
    return subprocess.run(
        [BASH, hook], input=ev, text=True, capture_output=True, env=env
    )


def _env_without_jq():
    """A copy of the real environment with jq's directory stripped out of
    PATH, so `command -v jq` genuinely finds nothing."""
    env = dict(os.environ)
    if REAL_JQ is None:
        return env  # jq already isn't installed here; nothing to strip
    jq_dir = os.path.realpath(os.path.dirname(REAL_JQ))
    dirs = [
        d for d in env.get("PATH", "").split(os.pathsep)
        if d and os.path.realpath(d) != jq_dir
    ]
    env["PATH"] = os.pathsep.join(dirs)
    return env


def _env_with_broken_jq(stub_dir):
    """A copy of the real environment with a stub `jq` placed FIRST on
    PATH that fails exactly the way the bug report's reproduction did:
    prints a "command not found"-shaped line to stderr and exits 127."""
    stub = os.path.join(stub_dir, "jq")
    with open(stub, "w") as f:
        f.write("#!/bin/sh\necho 'jq: command not found' >&2\nexit 127\n")
    st = os.stat(stub)
    os.chmod(stub, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    env["PATH"] = stub_dir + os.pathsep + env.get("PATH", "")
    return env


# --- The planted failure: jq absent or broken must now BLOCK, not allow ---

def test_missing_jq_blocks_instead_of_silently_allowing():
    """jq entirely absent from PATH -- the guard must fail CLOSED (exit 2)
    and name jq, not fall through to the legitimate-empty-path allow.

    Mutation check performed: ran this same assertion against
    `git show HEAD:.claude/hooks/protect-files.sh` (the pre-fix content,
    saved to a scratch copy, HOOK unmodified) -- went RED, returncode 0,
    reproducing the dispatched bug exactly. Ran again against the fixed
    file -- GREEN.
    """
    r = _run({"tool_input": {"file_path": ".env"}}, _env_without_jq())
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "jq" in r.stderr.lower()


def test_broken_jq_on_path_blocks_instead_of_silently_allowing():
    """jq present on PATH but fails when invoked (the exact stub from the
    bug report) -- must also BLOCK. This is the half of the fix a bare
    `command -v jq` presence check alone would NOT catch (jq exists on
    PATH, it just errors), so it exercises the jq-pipeline exit-status
    check specifically, not just the "is jq installed" check.

    Mutation check performed: same as above -- RED (returncode 0) against
    the pre-fix scratch copy, GREEN against the fixed file.
    """
    with tempfile.TemporaryDirectory() as stub_dir:
        r = _run({"tool_input": {"file_path": ".env"}}, _env_with_broken_jq(stub_dir))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "jq" in r.stderr.lower()


# --- Positive controls: real jq must still block for the RIGHT reason,
#     and still allow legitimate non-matching / no-path events ---

@pytest.mark.skipif(REAL_JQ is None, reason="jq not installed on this machine")
def test_real_jq_still_blocks_dotenv_for_the_right_reason():
    """Without the message check, a test that only asserts 'exit 2' cannot
    distinguish this fix from a guard that has started rejecting every
    tool call unconditionally.

    Mutation check performed: ran against a scratch mutant of the FIXED
    file with an unconditional `exit 2` inserted right after
    `INPUT=$(cat)` (blocks everything, never reaches the real pattern
    match or its message) -- went RED (the 'protected pattern' substring
    was absent, since the mutant exits before ever printing it). Ran
    again against the real fixed file -- GREEN.
    """
    r = _run({"tool_input": {"file_path": ".env"}}, dict(os.environ))
    assert r.returncode == 2
    assert "protected pattern '.env'" in r.stderr


@pytest.mark.skipif(REAL_JQ is None, reason="jq not installed on this machine")
def test_real_jq_still_allows_nonmatching_path():
    """Mutation check performed: against the same always-block mutant
    described above -- went RED (returncode 2 instead of 0). GREEN
    against the real fixed file."""
    r = _run({"tool_input": {"file_path": "config.envoy.yaml"}}, dict(os.environ))
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(REAL_JQ is None, reason="jq not installed on this machine")
def test_real_jq_still_allows_event_with_no_file_path():
    """Case 3 from the guard's own header comment: jq SUCCEEDS and simply
    finds no .tool_input.file_path (e.g. a Bash tool call). This must stay
    an ALLOW -- it's a legitimate event shape, not a parse failure, and
    must not be collapsed into the same bucket as jq actually failing.

    Mutation check performed: against the same always-block mutant --
    went RED (returncode 2 instead of 0). GREEN against the real fixed
    file.
    """
    r = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}}, dict(os.environ))
    assert r.returncode == 0, r.stderr
