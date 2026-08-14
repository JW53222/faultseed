#!/usr/bin/env python3
"""workflow_agent_sizing_gate.py  --  PreToolUse hook on the Workflow tool.

Sibling to agent_sizing_gate.py for workflow-internal `agent()` calls.

The Workflow tool spawns subagents at runtime via `agent(prompt, opts)`
inside the script body. Those spawns DO NOT go through the Agent tool's
PreToolUse hook (the Workflow runtime drives them directly), so the
existing agent_sizing_gate sees zero of them. A single Workflow can
spawn dozens of agents — every one inheriting the parent's model
(Opus during a /effort ultracode session) by default. The agent-sizing
mandate is silently bypassed for the entire workflow population.

This hook closes the gap STATICALLY at the Workflow PreToolUse: parse
the script the user is about to run, find every `agent(...)` call site,
require each one to declare an explicit `model: 'haiku' | 'sonnet' | 'opus'`.
Block if any site is missing it, listing the offending line numbers so
the script can be fixed in one pass.

Why static-parse instead of a runtime hook? The Workflow runtime doesn't
expose a PreToolUse-equivalent for its internal agent() calls, and
modifying the runtime is outside our control. Static parsing covers the
case at the only surface we own: the Workflow tool call itself.

Scope: fires only for tool_name == "Workflow". Limitations:
  - Skips agent() calls inside JS comments and string literals (handled
    via lexer-style strip).
  - Cannot resolve `agent(prompt, opts)` where `opts` is a variable
    constructed elsewhere. Flags such calls as missing-model (safe
    default; user can refactor to inline the opts).
  - Same "can't resolve statically" problem applies one level down: a
    `model:` value that isn't a static string literal (a variable, member
    expression, function call, ternary, template literal with `${}`, an
    unquoted bareword, ...) can't be checked against VALID either. It gets
    the same safe default as the opts-variable case -- BLOCKED as
    unverifiable rather than silently trusted, so an un-inlined value can't
    become a bypass for anything that isn't a plain quoted string.
  - Brace-matched call extraction; multi-line calls and nested objects
    handled correctly.

Escape: include `// workflow-model-ok: <reason>` on the same line as the
agent() call (e.g. for a deliberate inherit-from-parent case). The reason
is REQUIRED -- a bare `// workflow-model-ok` with nothing after the colon
does NOT clear the block (mirrors tampering-ok / swallow-ok / delete-tests-ok
elsewhere in this pack).
"""

import os
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import load_event, block, allow, emit_event, MODEL_TIERS

# Shared with agent_sizing_gate.py via _common.py -- see the MODEL_TIERS
# docstring there for why this is defined once instead of locally (the two
# gates drifted before: this set used to omit "fable") and for the
# vocabulary-coupling caveat. NOTE: this gate has no frontier-leaf concept
# (unlike the Agent-tool sibling) -- opus and fable are both ordinary valid
# tiers here, so only MODEL_TIERS is imported, not FRONTIER_MODEL_TIERS.
VALID = MODEL_TIERS
# Rationale REQUIRED, mirroring TAMPERING_OK / SWALLOW_OK / DELETE_TESTS_OK
# elsewhere in this pack: a bare `// workflow-model-ok` with nothing after
# the colon is a self-grantable escape hatch and must NOT clear the block.
ESCAPE_RE = re.compile(r"//\s*workflow-model-ok\s*:\s*(\S.*?)\s*$", re.IGNORECASE)
# Matches the bare keyword (with or without a colon/reason) -- used only to
# detect a FAILED escape attempt so the block message can tell the user
# what's missing, instead of silently falling through to the generic block.
BARE_ESCAPE_RE = re.compile(r"//\s*workflow-model-ok\b", re.IGNORECASE)
# `model:` key finder (searched against the STRIPPED opts region, so it
# can't match inside a string/comment) and a static-string-literal matcher
# (matched against the ORIGINAL opts region at the same offset, since the
# stripped region has already blanked string contents). Deliberately no
# trailing `\s*` here -- see the whitespace-skip comment at the call site:
# the stripped region's post-colon spaces are ambiguous (real whitespace OR
# a blanked-out string), and a greedy \s* would eat straight through a
# blanked literal to the next real character.
_MODEL_KEY_RE = re.compile(r"\bmodel\s*:")
_MODEL_LITERAL_RE = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"|`([^`\n]*)`")

MSG_PREFIX = """BLOCKED: this Workflow has agent() call site(s) without an explicit `model`.
Every subagent must be sized — an unset model silently inherits whatever
model is running this session, the wrong default for most work.

Workflows commonly spawn dozens of agents; un-sized calls amplify the cost
linearly. Fix the call sites listed below before re-issuing the Workflow.

Set `model:` to one of haiku | sonnet | opus | fable on each agent() call:
  - haiku       : single-file edit, clear pattern, sed-like sweep, docs/config,
                  or a fix describable in <5 prescriptive sentences
  - sonnet      : 2-3 files, an existing pattern to follow, most non-subtle fixes
  - opus / fable: subtle invariants (parity / async / TOCTOU / races),
                  architecture, multi-file refactors where the worker must
                  judge what stays/moves (~1 in 8 dispatches actually need
                  this)

Escape for a deliberate inherit-from-parent: append
`// workflow-model-ok: <reason>` on the same line as the agent() call.
"""


def _strip_js_comments_and_strings(src):
    """Lexer-lite: replace JS line comments, block comments, and string
    literals with same-length blanks so that downstream regex doesn't
    match inside them. Preserves overall character positions so we can
    still report sensible line numbers."""
    out = list(src)
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        # Line comment
        if c == "/" and nxt == "/":
            j = i
            while j < n and src[j] != "\n":
                if src[j] != "\n":
                    out[j] = " "
                j += 1
            i = j
            continue
        # Block comment
        if c == "/" and nxt == "*":
            j = i + 2
            out[i] = " "
            out[i + 1] = " "
            while j < n - 1 and not (src[j] == "*" and src[j + 1] == "/"):
                if src[j] != "\n":
                    out[j] = " "
                j += 1
            # blank the closing */
            if j < n - 1:
                out[j] = " "
                out[j + 1] = " "
                j += 2
            i = j
            continue
        # Strings: ' " `  (template literal naive — no ${} handling)
        if c in ("'", '"', "`"):
            quote = c
            j = i + 1
            out[i] = " "
            while j < n:
                if src[j] == "\\" and j + 1 < n:
                    if src[j] != "\n":
                        out[j] = " "
                    if src[j + 1] != "\n":
                        out[j + 1] = " "
                    j += 2
                    continue
                if src[j] == quote:
                    out[j] = " "
                    j += 1
                    break
                if src[j] != "\n":
                    out[j] = " "
                j += 1
            i = j
            continue
        i += 1
    return "".join(out)


def _find_agent_calls(stripped, original):
    """Yield (line_number, status, call_substring_of_original, model_value,
    bare_escape) for every `agent(...)` site, with paren-balanced extraction.

    status is one of:
      "ok"         -- an explicit, recognised `model:` literal (or the
                       line carries a reasoned `// workflow-model-ok:` escape)
      "missing"    -- no `model:` key at all
      "invalid"    -- `model:` is a string literal, but not in VALID
      "nonliteral" -- `model:` is present but isn't a static string literal
                       (variable, expression, call, unquoted bareword, ...)

    bare_escape is True when the line carries `// workflow-model-ok` with
    no reason after the colon -- i.e. a failed escape attempt that did NOT
    clear the block, surfaced separately so the caller can tell the user
    what's missing rather than just re-stating the generic block message.
    """
    # \bagent\s*\(  — match keyword 'agent' followed by '(' possibly with whitespace.
    # Stripped source has all strings/comments blanked, so we won't match inside them.
    for m in re.finditer(r"\bagent\s*\(", stripped):
        start = m.start()
        # Walk forward in STRIPPED to find balanced closing paren — strings
        # and comments inside the call are already blanks so they don't
        # interfere with paren counting.
        depth = 0
        j = m.end() - 1  # position of '('
        end = None
        while j < len(stripped):
            ch = stripped[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
            j += 1
        if end is None:
            continue  # unbalanced; let the runtime complain
        call_stripped = stripped[start:end]
        call_original = original[start:end]
        # Detect `model: ...` (or `model :`) somewhere in the opts portion.
        # Use the STRIPPED slice so strings/comments don't false-match.
        # Skip the leading `agent(` and check from first comma onward,
        # to avoid matching `model` inside the prompt argument's name.
        first_comma = call_stripped.find(",")
        opts_stripped = call_stripped[first_comma:] if first_comma != -1 else ""
        opts_original = call_original[first_comma:] if first_comma != -1 else ""
        key_match = _MODEL_KEY_RE.search(opts_stripped)
        if key_match is None:
            status, model_value = "missing", None
        else:
            # Read the value back from ORIGINAL at the same offset: stripped
            # and original are character-for-character the same length, and
            # key_match was found outside any string/comment, so the offset
            # carries over. A quoted literal's CONTENTS only survive in
            # original -- stripped has already blanked them.
            #
            # Skip whitespace using ORIGINAL, not a trailing \s* on the
            # stripped match: the space between `:` and a quoted value is
            # real in both, but the blanked-out characters *inside* a string
            # are ALSO spaces in stripped, indistinguishable from real
            # whitespace there. A greedy \s* on stripped would consume past
            # the whole blanked literal to the next real character (e.g. the
            # closing `}`), overshooting the quote it needs to land on.
            pos = key_match.end()
            while pos < len(opts_original) and opts_original[pos] in " \t\r\n":
                pos += 1
            lit_match = _MODEL_LITERAL_RE.match(opts_original, pos)
            if lit_match is None:
                # Not a static string literal (variable, member expression,
                # call, ternary, unquoted bareword, ...) -- can't be checked
                # against VALID. Treated as unverifiable, not trusted (see
                # module docstring "Limitations").
                status, model_value = "nonliteral", None
            else:
                raw = next(g for g in lit_match.groups() if g is not None)
                if "${" in raw:
                    # Template literal with interpolation -- can't resolve
                    # without evaluating JS. Same treatment as "nonliteral".
                    status, model_value = "nonliteral", None
                else:
                    norm = raw.strip().lower()
                    status, model_value = ("ok", norm) if norm in VALID else ("invalid", raw)
        # Check for the same-line escape comment in the ORIGINAL.
        line_start = original.rfind("\n", 0, start) + 1
        line_end = original.find("\n", end)
        if line_end == -1:
            line_end = len(original)
        line_text = original[line_start:line_end]
        bare_escape = False
        if ESCAPE_RE.search(line_text):
            status, model_value = "ok", None
        elif status != "ok" and BARE_ESCAPE_RE.search(line_text):
            bare_escape = True
        # Line number (1-indexed).
        line_no = original.count("\n", 0, start) + 1
        yield (line_no, status, call_original.strip().splitlines()[0], model_value, bare_escape)


def _load_script(tool_input, cwd):
    """Return (script_text, source_label). Prefer inline script; fall back
    to scriptPath. Returns (None, label) on failure."""
    inline = tool_input.get("script")
    if isinstance(inline, str) and inline.strip():
        return inline, "inline script"
    script_path = tool_input.get("scriptPath")
    if isinstance(script_path, str) and script_path:
        full = script_path if os.path.isabs(script_path) else os.path.join(cwd, script_path)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                return f.read(), f"scriptPath={script_path}"
        except OSError:
            return None, f"scriptPath={script_path} (unreadable)"
    # Named workflow (`name`) reference — we can't introspect a builtin.
    name = tool_input.get("name")
    if isinstance(name, str) and name:
        return None, f"name={name}"
    return None, "unknown"


def main():
    event = load_event()
    if event.get("tool_name") != "Workflow":
        allow()

    ti = event.get("tool_input", {}) or {}
    cwd = event.get("cwd") or os.getcwd()
    script, source_label = _load_script(ti, cwd)

    if script is None:
        # Named/builtin workflow — we can't statically inspect it.
        # Allow rather than over-block; the agent-sizing hygiene of named
        # workflows is their author's responsibility.
        allow()

    stripped = _strip_js_comments_and_strings(script)
    missing = []
    invalid = []
    nonliteral = []
    bare_escape_lines = []
    models_seen = []
    call_count = 0
    for line_no, status, snippet, model_value, bare_escape in _find_agent_calls(stripped, script):
        call_count += 1
        # Trim long snippets for the block message.
        short = snippet if len(snippet) <= 100 else snippet[:97] + "..."
        if bare_escape:
            bare_escape_lines.append(line_no)
        if status == "missing":
            missing.append((line_no, short))
        elif status == "invalid":
            invalid.append((line_no, short, model_value))
        elif status == "nonliteral":
            nonliteral.append((line_no, short))
        elif model_value:
            models_seen.append(model_value)

    offenders = len(missing) + len(invalid) + len(nonliteral)
    if not offenders:
        if call_count:
            # One Workflow tool call can spawn a batch of agent() leaves; this
            # is a batch-level agent_spawn (not one row per call site).
            emit_event(
                "agent_spawn",
                payload={
                    "kind": "workflow",
                    "call_count": call_count,
                    "models": models_seen,
                    "rung": "leaf",
                    "worktree": None,
                },
            )
        allow()

    entries = []  # (line_no, detail_text)
    for ln, s in missing:
        entries.append((ln, f"  - line {ln}: {s}"))
    for ln, s, v in invalid:
        entries.append(
            (ln, f"  - line {ln}: model={v!r} is not one of {sorted(VALID)}: {s}")
        )
    for ln, s in nonliteral:
        entries.append(
            (ln, f"  - line {ln}: model is not a static string literal "
                 f"(variable/expression/template) -- cannot verify statically: {s}")
        )
    entries.sort(key=lambda e: e[0])

    detail_lines = "\n".join(t for _, t in entries[:20])
    if len(entries) > 20:
        detail_lines += f"\n  ... ({len(entries) - 20} more)"

    msg = (
        MSG_PREFIX
        + f"\nSource: {source_label}\n"
        + f"\nUn-sized / invalid agent() call site(s) ({offenders} total):\n"
        + detail_lines
    )
    if bare_escape_lines:
        lines_str = ", ".join(str(ln) for ln in sorted(set(bare_escape_lines)))
        msg += (
            f"\n\nNote: line(s) {lines_str} carry `// workflow-model-ok` with no "
            "reason after the colon. This marker requires a rationale, same as "
            "`tampering-ok:` / `swallow-ok:` / `delete-tests-ok:` elsewhere in "
            "this pack -- a bare marker does not clear the block. State why: "
            "`// workflow-model-ok: <reason>`."
        )
    block(msg)


if __name__ == "__main__":
    main()
