#!/usr/bin/env python3
"""no_bash_test_mutation.py  --  PreToolUse hook, matcher: Bash

Companion to no_bash_test_deletion.py and no_test_tampering.py.

The Edit/Write hook (no_test_tampering.py) sees weakening of a test file.
The bash-deletion hook (no_bash_test_deletion.py) sees `rm`/`git rm`/`git mv`
of test files. Neither sees a test file mutated IN PLACE via `sed -i`,
`awk -i inplace`, `cat > tests/...`, `> tests/...`, `tee tests/...` —
those bypass the Edit-side tamper guard entirely.

A worker subagent once silently deleted a whole test class (with embedded
assertions) from a test file via a bash-side mechanism, sailed past
no_test_tampering, and shipped the deletion in a branch outside the worker's
stated scope. This hook closes that hole.

What it BLOCKS: a Bash command that mutates an EXISTING test file in place.
What it ALLOWS:
  - Creating a NEW test file (target file does not yet exist on disk).
  - Reading a test file (`cat tests/foo` without a write redirect).
  - Bash commands with `# test-mutate-ok: <reason>` audit comment.
  - Integrator (GUARDRAILS_INTEGRATOR_ROLE=1) bypass — the integrator role
    owns test edits at merge time, so it is exempt from this guard.
    This check is intentionally left at the strict `== "1"` it always had --
    unlike integrator_transcript_compactor.py, unifying this one's truthiness
    would be a real behavior change to a hook that BYPASSES a guard entirely,
    not a maintenance no-op, so it was left as-is on the rename.

Detected mutation shapes (per simple-command in a compound bash line):
  - sed -i / sed --in-place ... <test path>      (gsed too)
  - awk -i inplace ... <test path>               (gawk, mawk too)
  - > <test path>                                truncating redirect
                                                 (cmd > t, `cat ... > t`)
  - >> <test path>                               appending redirect
  - tee [-a] <test path>                         (cmd | tee t)
  - dd of=<test path>

A test path = same rule as no_bash_test_deletion._looks_like_test_path
(contains /tests/ or /test/, ends in test_*.py / *_test.py /
conftest.py / *.Tests.ps1).

Escape: include `# test-mutate-ok: <reason>` in the bash command. The
rationale is REQUIRED -- mirrors the Edit-side markers (`tampering-ok:`,
`swallow-ok:`, `falsy-zero-ok:`): a bare `# test-mutate-ok` with nothing after
the colon does NOT clear the block. (Previously a bare marker sufficed --
a self-grantable escape hatch with the same shape as the incident this hook
exists to catch.)
"""

import os
import re
import shlex
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import load_event, block, allow

# Rationale REQUIRED, mirroring TAMPERING_OK / SWALLOW_OK / FALSY_ZERO_OK.
# Checked per-line (like those) so `$` anchors to one line of a multi-line
# bash command rather than the whole command string.
ESCAPE = re.compile(r"#\s*test-mutate-ok\s*:\s*(\S.*?)\s*$")
BARE_ESCAPE = re.compile(r"#\s*test-mutate-ok\b")


def _has_escape_with_reason(command):
    return any(ESCAPE.search(line) for line in command.splitlines())


def _has_bare_escape(command):
    return any(BARE_ESCAPE.search(line) for line in command.splitlines())

TEST_FILE_RE = re.compile(
    r"(^|/)(test_[^/]*\.py|[^/]*_test\.py|[^/]*\.Tests\.ps1|conftest\.py)$",
    re.IGNORECASE,
)


def _looks_like_test_path(tok):
    t = (tok or "").strip().strip("'\"")
    if not t or t.startswith("-"):
        return False
    tl = t.replace("\\", "/")
    if "/tests/" in tl or "/test/" in tl:
        return True
    if tl in ("tests", "test") or tl.endswith("/tests") or tl.endswith("/test"):
        return True
    if TEST_FILE_RE.search(tl):
        return True
    return False


def _file_exists(path, cwd):
    if not path:
        return False
    p = path if os.path.isabs(path) else os.path.join(cwd, path)
    try:
        return os.path.exists(p)
    except Exception:
        return False


def _split_commands(command):
    return [p.strip() for p in re.split(r"&&|\|\||;|\n|\|", command) if p.strip()]


def _tokens(simple_cmd):
    try:
        return shlex.split(simple_cmd, comments=True)
    except ValueError:
        return simple_cmd.split()


def _check_sed_awk(toks):
    findings = []
    if not toks:
        return findings
    cmd0 = toks[0]
    if cmd0 in ("sed", "gsed"):
        # -i (BSD also accepts `-i ''`); reject only if --in-place flag is present.
        in_place = any(
            t == "-i" or t == "--in-place" or t.startswith("-i") for t in toks[1:]
        )
        if in_place:
            for t in toks[1:]:
                if not t.startswith("-") and _looks_like_test_path(t):
                    findings.append(("sed -i", t))
    if cmd0 in ("awk", "gawk", "mawk"):
        # awk -i inplace 'script' file...
        idx_i = next((i for i, t in enumerate(toks) if t == "-i"), -1)
        in_place = idx_i >= 0 and idx_i + 1 < len(toks) and toks[idx_i + 1] == "inplace"
        if in_place:
            for t in toks[1:]:
                if not t.startswith("-") and t != "inplace" and _looks_like_test_path(t):
                    findings.append(("awk -i inplace", t))
    return findings


def _check_tee(toks):
    findings = []
    if toks and toks[0] == "tee":
        for t in toks[1:]:
            if not t.startswith("-") and _looks_like_test_path(t):
                findings.append(("tee", t))
    return findings


def _check_dd(toks):
    findings = []
    if toks and toks[0] == "dd":
        for t in toks[1:]:
            if t.startswith("of="):
                tgt = t.split("=", 1)[1]
                if _looks_like_test_path(tgt):
                    findings.append(("dd of=", tgt))
    return findings


def _check_redirect(simple):
    """Detect `> path` and `>> path` to test paths. Handles `>foo` and `> foo`."""
    findings = []
    toks = _tokens(simple)
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in (">", ">>"):
            if i + 1 < len(toks):
                tgt = toks[i + 1]
                if _looks_like_test_path(tgt):
                    findings.append((f"redirect {t}", tgt))
            i += 2
            continue
        m = re.match(r"^(>>?)(.+)$", t)
        if m:
            tgt = m.group(2)
            if _looks_like_test_path(tgt):
                findings.append((f"redirect {m.group(1)}", tgt))
        i += 1
    return findings


def main():
    # Strict `== "1"` on purpose, unlike the loose truthiness check
    # elsewhere in this pack (e.g. integrator_transcript_compactor.py,
    # _common.py's agent_role()): this is a GUARD BYPASS, not a maintenance
    # toggle, so it demands the most explicit possible opt-in rather than
    # accepting "true"/"yes"/anything-non-falsy. A loose check here would
    # widen who can skip test-tampering protection by accident (e.g. a
    # stray truthy value picked up from a parent shell), not just widen
    # when a housekeeping hook chooses to run its own maintenance.
    if os.environ.get("GUARDRAILS_INTEGRATOR_ROLE") == "1":
        allow()

    event = load_event()
    ti = event.get("tool_input", {}) or {}
    command = ti.get("command") or ""
    if not command:
        allow()

    cwd = event.get("cwd") or os.getcwd()

    findings = []
    for simple in _split_commands(command):
        toks = _tokens(simple)
        findings.extend(_check_sed_awk(toks))
        findings.extend(_check_tee(toks))
        findings.extend(_check_dd(toks))
        findings.extend(_check_redirect(simple))

    # Filter: creating a NEW test file is fine — only block mutations of
    # files that ALREADY exist on disk.
    real = [(v, t) for (v, t) in findings if _file_exists(t, cwd)]

    if real:
        if _has_escape_with_reason(command):
            allow()

        if _has_bare_escape(command):
            block(
                "BLOCKED: `# test-mutate-ok` needs a reason.\n\n"
                "This marker requires a rationale, same as `tampering-ok:` / "
                "`swallow-ok:` / `falsy-zero-ok:` on the Edit side — a bare "
                "`# test-mutate-ok` with nothing after the colon is a "
                "self-grantable escape hatch and does not clear the block. "
                "State what changed and why the in-place mutation is safe: "
                "`# test-mutate-ok: <reason>`."
            )

        lines = ["BLOCKED: this Bash command mutates an EXISTING test file in place.\n"]
        for verb, tgt in real:
            lines.append(f"  - {verb} -> {tgt}")
        lines.append(
            "\nIn-place test-file mutation via bash bypasses the Edit-side tamper "
            "guard (no_test_tampering.py), which is how a whole test class with "
            "embedded assertions was silently removed in a recent worker run. "
            "Use the Edit tool instead so the tamper guard can see the diff. If "
            "the mutation is intentional and approved (e.g. a refactor that "
            "genuinely preserves coverage), append `# test-mutate-ok: <reason>` "
            "to the command."
        )
        block("\n".join(lines))

    allow()


if __name__ == "__main__":
    main()
