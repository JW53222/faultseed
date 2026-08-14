#!/usr/bin/env python3
"""no_bash_test_deletion.py  --  PreToolUse hook, matcher: Bash

The Edit/Write hooks (no_test_tampering.py) police WEAKENING a test file, but
they never see a wholesale DELETE done via the shell. The motivating incident
was a large test file removed wholesale with `git rm`, which slipped past
every Edit|Write guard because deletion isn't an Edit.

This hook inspects Bash commands for `git rm` / `rm` (and `git mv` away from a
tests path) that target test files or test directories, and BLOCKS, surfacing
the deletion to the human. Deleting tests is sometimes legitimate (removing a
genuinely obsolete suite), but it must be a DELIBERATE, surfaced decision — not
something that happens quietly inside a larger shell one-liner.

Detected shapes (on the command string):
  - rm / rm -rf / rm -f ... <something that looks like a test file or tests dir>
  - git rm [-r] [-f] ... <ditto>
  - git mv <tests-path> <non-tests-path>   (moving a test out of the suite)

A test path = a token containing `/tests/`, ending in a test filename
(`test_*.py`, `*_test.py`, `*.Tests.ps1`, `conftest.py`), or being a bare
`tests`/`test` directory token.

Escape hatch: include `# delete-tests-ok: <reason>` anywhere in the command to
proceed. The rationale is REQUIRED -- mirrors the Edit-side markers
(`tampering-ok:`, `swallow-ok:`, `falsy-zero-ok:`): a bare `# delete-tests-ok`
with nothing after the colon does NOT clear the block. (Previously a bare
marker sufficed -- a self-grantable escape hatch with the same shape as the
incident this hook exists to catch.) Exit 2 blocks; the message tells the
agent to confirm with the human or add the marker with a reason.
"""

import re
import shlex
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import load_event, block, allow

# Rationale REQUIRED, mirroring TAMPERING_OK / SWALLOW_OK / FALSY_ZERO_OK.
# Checked per-line (like those) so `$` anchors to one line of a multi-line
# bash command rather than the whole command string.
ESCAPE = re.compile(r"#\s*delete-tests-ok\s*:\s*(\S.*?)\s*$")
BARE_ESCAPE = re.compile(r"#\s*delete-tests-ok\b")


def _has_escape_with_reason(command):
    return any(ESCAPE.search(line) for line in command.splitlines())


def _has_bare_escape(command):
    return any(BARE_ESCAPE.search(line) for line in command.splitlines())

# token "looks like a test target"
TEST_FILE_RE = re.compile(
    r"(^|/)(test_[^/]*\.py|[^/]*_test\.py|[^/]*\.Tests\.ps1|conftest\.py)$",
    re.IGNORECASE,
)


def _looks_like_test_path(tok):
    t = tok.strip().strip("'\"")
    if not t or t.startswith("-"):
        return False
    tl = t.replace("\\", "/")
    if "/tests/" in tl or "/test/" in tl:
        return True
    if tl in ("tests", "test") or tl.endswith("/tests") or tl.endswith("/test"):
        return True
    if TEST_FILE_RE.search(tl):
        return True
    # glob targeting tests, e.g. tests/services/test_*  or  tests/foo/*
    if (tl.startswith("tests/") or tl.startswith("test/") or "/tests/" in tl) and (
        "*" in tl or tl.endswith("/")
    ):
        return True
    return False


def _split_commands(command):
    """Split a compound shell line into individual simple commands on
    &&, ||, ;, | and newlines. Crude but sufficient to isolate each rm/git."""
    parts = re.split(r"&&|\|\||;|\n|\|", command)
    return [p.strip() for p in parts if p.strip()]


def _tokens(simple_cmd):
    try:
        return shlex.split(simple_cmd, comments=True)
    except ValueError:
        return simple_cmd.split()


def _is_rm(toks):
    return bool(toks) and toks[0] == "rm"


def _is_git_rm(toks):
    return len(toks) >= 2 and toks[0] == "git" and toks[1] == "rm"


def _is_git_mv(toks):
    return len(toks) >= 2 and toks[0] == "git" and toks[1] == "mv"


def main():
    event = load_event()
    ti = event.get("tool_input", {}) or {}
    command = ti.get("command") or ""
    if not command:
        allow()

    findings = []
    for simple in _split_commands(command):
        toks = _tokens(simple)
        if not toks:
            continue

        if _is_rm(toks) or _is_git_rm(toks):
            # operands after the verb (skip flags)
            start = 1 if _is_rm(toks) else 2
            targets = [t for t in toks[start:] if not t.startswith("-")]
            for t in targets:
                if _looks_like_test_path(t):
                    verb = "rm" if _is_rm(toks) else "git rm"
                    findings.append(f"{verb} {t}")

        elif _is_git_mv(toks):
            operands = [t for t in toks[2:] if not t.startswith("-")]
            if len(operands) >= 2:
                src, dst = operands[0], operands[-1]
                # moving a test OUT of a tests location (dst not a test path)
                if _looks_like_test_path(src) and not _looks_like_test_path(dst):
                    findings.append(f"git mv {src} -> {dst}")

    if findings:
        if _has_escape_with_reason(command):
            allow()

        if _has_bare_escape(command):
            block(
                "BLOCKED: `# delete-tests-ok` needs a reason.\n\n"
                "This marker requires a rationale, same as `tampering-ok:` / "
                "`swallow-ok:` / `falsy-zero-ok:` on the Edit side — a bare "
                "`# delete-tests-ok` with nothing after the colon is a "
                "self-grantable escape hatch and does not clear the block. "
                "State what you're deleting and why: "
                "`# delete-tests-ok: <reason>`."
            )

        lines = [
            "BLOCKED: this Bash command deletes or moves test files out of the suite.\n"
        ]
        for f in findings:
            lines.append(f"  - {f}")
        lines.append(
            "\nDeleting tests via the shell bypasses the Edit/Write tamper guards "
            "(this is exactly how the motivating incident's test delete slipped "
            "through). Removing a test is sometimes right, but it must be a deliberate, "
            "surfaced decision. Confirm with the human first. If the deletion is "
            "intended and approved, append `# delete-tests-ok: <reason>` to the "
            "command."
        )
        block("\n".join(lines))

    allow()


if __name__ == "__main__":
    main()
