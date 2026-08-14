#!/usr/bin/env python3
"""no_swallowed_errors.py  --  PreToolUse hook, matcher: Edit|Write|MultiEdit

Blocks the second big honesty failure: hiding a problem in SOURCE code rather
than solving it. Two families:

  1. Swallowed exceptions:
        except: pass
        except Exception: pass
        except ...: ...        where the body only logs/continues past a real failure
  2. Defect-excusing comments used AS a substitute for a fix:
        # TODO / FIXME / HACK / XXX
        # known issue / good enough / this is fine / will fix later
     ...but ONLY when they look like an excuse, not normal annotation.

PATH SCOPE (role-variant design)
--------------------------------
This is an ENGINE-QUALITY hook. For Python/PowerShell it fires ONLY on the
engine source dirs configured in audit-scope.yaml's `engine_dirs` — see
`_common.is_engine_path`.
An edit to docs, frontend, or a strategy JSON goes through untouched. That
path gate dissolves most of the "don't hamstring other roles" concern before
role even matters.

For Go there is no backend/frontend split the way `is_engine_path`'s
`engine_dirs` config models it — a Go-dominant codebase has no such split, so
"in scope" reduces to "any `.go` production file that is not generated" (see
`_is_go_generated()`). This is a DELIBERATELY MINIMAL local check, not a new
config system: `is_engine_path()` itself is left untouched (still used
unchanged for Python/PowerShell, still shared by other hooks that must stay
Python-only) and Go gets its own narrow, self-contained scope predicate
instead of being folded into `docs/audit/audit-scope.yaml`'s `engine_dirs`,
which is a Python/PowerShell-only config shape.

GATE ORDER — established BEFORE any pattern was touched (the lesson: the
real defect is often one layer up from where it looks). For a `.go` file, an
earlier version of this hook's scope gate was a bare extension check —
`if path and not (is_py or is_ps): allow()` — which meant `is_engine_path`
was NEVER REACHED, because the extension gate fired first and exited
immediately for any `.go` path. Adding a Go grammar without widening this
gate first would have repeated exactly that trap: a perfect analyzer bolted
onto a hook that never reaches it.

GO SWALLOW SHAPES DETECTED (diff-scoped — see NEIGHBORHOOD SCAN note below):
  - `_ = err` (discarding an error-shaped value; scoped to identifiers whose
    name contains "err", case-insensitive, to avoid re-importing the
    bare-identifier-discard false-positive class into every Go local var)
  - an empty `if err != nil { }` body
  - `if err != nil { return nil }` — a checked error silently swallowed by
    returning nil instead of the error (single-return-value shape)
  - a commented-out or otherwise-defeated check is NOT separately detected;
    see the KNOWN LIMITATION note on the ignored-second-return-value shape
    below

GO SHAPE NOT RELIABLY DETECTABLE — SAID PLAINLY, NOT PAPERED OVER: "an
ignored second return value where the callee returns `(T, error)`" (e.g.
`data, _ := ReadFile(...)`) cannot be distinguished from the equally common,
equally legitimate `(T, bool)` "found" idiom without knowing the callee's
real signature — this hook sees one file's diff text, not a type-checked
call graph. Widening the regex to catch every `, _ :=` would put this hook
back in the false-positive class it was written to avoid. This shape is
surfaced as a WARN-ONLY soft-hit (mirrors the existing `EXCUSE_COMMENT`
soft-hit tier, `GUARDRAILS_STRICT=1` promotes it to a hard block same as
excuse comments) rather than silently dropped OR silently promoted to a hard
block that would be wrong roughly as often as it's right.

LEGITIMATE GO SHAPES THAT MUST STAY ALLOWED (adversarial goldens, designed to
stay green by construction rather than via a special-cased carve-out):
`defer f.Close()` (a bare call statement, no return value ever bound to
anything, so no pattern here can match it at all); `_ = f.Close()`
(discarding a CALL RESULT, not a bare identifier — the `_ = <name>` pattern
requires a bare identifier with nothing else on the line, exactly mirroring
the discard-a-variable vs. discard-a-call's-return-value distinction
`no_test_tampering.py` itself makes).

NEIGHBORHOOD SCAN — not diff-only
----------------------------------------
The earlier version inspected only `new_string` (the added fragment). That is a
hole: an agent can *build around* a pre-existing swallowed error — keep the bad
`except: pass` out of new_string — and sail past the guard, leaving the hole.

Instead, for a Python edit we reconstruct the FULL post-edit file (Write gives
the whole body; Edit/MultiEdit applies the substitutions to the on-disk file in
memory), locate the lines this edit touched, and scan a NEIGHBORHOOD window
around them:

  WINDOW = the enclosing function of each touched line, PLUS its sibling
  functions within +/-2 positions in the same parent scope (class body or
  module). If a touched line is at class-body / module level (not inside any
  function), the window is that whole class body / module.

Any swallow inside that window BLOCKS unless it carries `# swallow-ok: <reason>`.
This forces the agent to confront nearby unhandled swallows rather than
work around them. The window is a TUNABLE knob (GUARDRAILS_SWALLOW_NEIGHBORS,
default 2 sibling functions each side); it is deliberately a *function-level*
window, not the whole file, so an edit isn't blocked by an audited swallow
ten functions away.

Whole-file Writes are scanned in full (the whole file IS the edit).

ESCAPE MARKER
-------------
A swallow carrying `# swallow-ok: <reason>` is permitted, exactly mirroring
no_falsy_zero's `# falsy-zero-ok:` and no_type_checking_stub's
`# host-provides:`: the rationale is REQUIRED — a bare `# swallow-ok` with no
reason is itself a violation. Detection is HANDLER-AWARE: the marker must sit
inside the specific handler it excuses — on the `except` line, on the sole
`pass`/`...` body line, or on a comment line between them (the natural spots a
dev annotates). A marker elsewhere in the file does not cover an unrelated
swallow. (A prior audit found real sites annotated on the `pass` line that an
earlier except-line-only rule could not see — the tolerance exists so a
correct annotation in any of the three natural positions counts.)

Go's `//` line-comment syntax is honored the same way: `// swallow-ok:
<reason>` on any line spanned by the hit (the `if`/discard line, or a comment
line between the braces for the multi-line empty-check and swallowed-return-
nil shapes) clears a Go hit, rationale still required. A GO_DISCARD_ERR shape
(`_ = err`) is single-line, so its marker must trail on that same line.

PowerShell swallows (catch {}, -ErrorAction SilentlyContinue, global
$ErrorActionPreference) are detected on the added text (no AST), and also
honor a `# swallow-ok: <reason>` marker on any line spanned by the hit --
including a comment line sitting between an empty catch's two braces, not
just the line the `catch` keyword is on. Detection SHAPE and marker
EXEMPTION are deliberately separate concerns here: the empty-catch/empty-
err-check/swallowed-return-nil patterns treat whitespace AND comments as
equally "no real code between the braces" (a bare whitespace-only pattern
between delimiters used to mean any comment -- marked or not -- broke the
match outright and silently bypassed detection), while
`_match_has_swallow_ok` alone decides whether a hit is excused.

EXCUSE COMMENTS (`# TODO: good enough`, `# known issue`) are WARN-ONLY by
default. GUARDRAILS_STRICT=1 promotes them to a hard block.

Knobs:
  GUARDRAILS_STRICT=1            -> promote excuse comments to hard-block too.
  GUARDRAILS_SWALLOW_NEIGHBORS=N -> sibling-function window radius (default 2).
"""

import ast
import os
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import (
    load_event,
    extract,
    block,
    allow,
    is_test_file,
    is_engine_path,
    is_generated_path,
    emit_event,
)

STRICT = os.environ.get("GUARDRAILS_STRICT", "0") != "0"
NEIGHBORS = int(os.environ.get("GUARDRAILS_SWALLOW_NEIGHBORS", "2"))

# Line-aware escape marker: `# swallow-ok: <reason>`. Rationale REQUIRED; a bare
# `# swallow-ok` (or `# swallow-ok:` with nothing after) does NOT count, exactly
# like the falsy-zero gate. `<#` covers a PowerShell block-comment opener.
# `//` recognized too, so a Go `// swallow-ok: <reason>` line-comment clears
# a Go hit the same way Python's `#` and PowerShell's `<# ... #>` do.
SWALLOW_OK = re.compile(r"(?:#|<#|//)\s*swallow-ok\s*:\s*(\S.*?)\s*(?:#>)?\s*$")

# --- PowerShell swallow patterns (regex over added text) ---
# Between the braces we allow whitespace AND comments (`# ...` to end of
# line, `<# ... #>` block) -- not just whitespace. A bare `\s*` here was the
# bug: a comment is not whitespace, so `catch {\n  # some comment\n}` (a
# genuinely empty handler with a human annotation) failed to match at all,
# which means ANY comment -- not just an unmarked one, a valid `swallow-ok:`
# marker too -- silently defeated detection. Shape (empty-aside-from-
# comments) and exemption (a valid swallow-ok marker) are separate concerns:
# this fragment only widens what counts as "empty"; `_match_has_swallow_ok`
# below is the only thing that clears a hit, same as everywhere else in this
# hook.
_PS_WS_OR_COMMENT = r"(?:\s|#[^\r\n]*|<#[\s\S]*?#>)*"
PS_EMPTY_CATCH = re.compile(
    r"catch\s*(\[[^\]]*\]\s*)?\{" + _PS_WS_OR_COMMENT + r"\}", re.IGNORECASE
)
PS_NULL_CATCH = re.compile(
    r"catch\s*(\[[^\]]*\]\s*)?\{" + _PS_WS_OR_COMMENT
    + r"(\$null|continue|return)?" + _PS_WS_OR_COMMENT + r"\}",
    re.IGNORECASE,
)
PS_EA_MASK = re.compile(r"-ErrorAction\s+(SilentlyContinue|Ignore)\b", re.IGNORECASE)
PS_GLOBAL_EA = re.compile(
    r"\$ErrorActionPreference\s*=\s*['\"]?(SilentlyContinue|Ignore)['\"]?",
    re.IGNORECASE,
)

EXCUSE_COMMENT = re.compile(
    r"(#|<#)\s*(?:"
    r"todo|fixme|hack|xxx"
    r"|known[ -]?issue|good enough|this is fine|will fix( this)? later"
    r"|not (?:my )?problem|ignore (?:this|for now)|temporary (?:fix|hack)"
    r")",
    re.IGNORECASE,
)

PY_EXTS = (".py",)
PS_EXTS = (".ps1", ".psm1", ".psd1")
GO_EXTS = (".go",)

# --- Go generated-file detection ---------------------------------------------
# Deliberately NOT a new config system (docs/audit/audit-scope.yaml's
# `engine_dirs` has no Go section, and building one for this hook alone would
# be scope creep). Two narrow, self-contained checks:
#   1. A project's own generated-bindata convention (`*_bindata.go` is a
#      common one) -- build output, not hand-authored source.
#   2. The Go-ecosystem-standard "// Code generated ... DO NOT EDIT." marker
#      (recognized by `go generate`, gofmt, IDEs) -- catches any OTHER
#      generated file this repo has or gains, without hardcoding more paths.
GO_BINDATA_SUFFIX = "_bindata.go"
GO_GENERATED_MARKER = re.compile(r"^\s*//\s*Code generated .*DO NOT EDIT\.\s*$", re.MULTILINE)


def _is_go_generated(path, full_src):
    base = (path or "").replace("\\", "/").rsplit("/", 1)[-1]
    if base.endswith(GO_BINDATA_SUFFIX):
        return True
    return bool(GO_GENERATED_MARKER.search(full_src or ""))


# --- Go swallow patterns — regex over added text, mirroring the
# EXISTING PowerShell tier (_powershell_hits), not the Python AST tier. Go
# cannot be ast.parse'd by this Python module, so there is no neighborhood-
# scan for Go the way there is for Python -- KNOWN LIMITATION, stated here
# rather than silently narrower: an edit that builds a Go swallow around a
# touched line (leaving the swallow itself just outside `added`) is not
# caught the way the Python neighborhood scan would catch the equivalent.
# ---------------------------------------------------------------------------
# `_ = err` -- bare identifier discard, scoped to error-shaped names (case-
# insensitive "err" substring) so this does NOT fire on discarding an
# unrelated bare local (`_ = count`), and does NOT fire on discarding a CALL's
# result (`_ = f.Close()`) -- the bare-identifier-only shape is deliberate,
# mirroring no_test_tampering.py's `_ = <var>` vs `_ = someCall()` split.
#
# The trailing `(?://.*)?` is deliberate, not decorative: an EARLIER version
# anchored straight to end-of-line (`...\s*$`) with nothing permitted after
# the identifier, so ANY trailing text -- not just an unmarked comment, a
# well-formed `// swallow-ok: <reason>` too -- made the whole pattern fail to
# match, meaning the escape-marker check (`_line_has_swallow_ok`, called
# separately below) was never even reached. Detection (does this line discard
# an error-shaped bare identifier) and exemption (does it carry a valid
# marker) are separate concerns; conflating them by anchoring the SHAPE
# pattern to "nothing else on the line" was the bug. `_ = f.Close()` still
# does not match: a `.` immediately after the identifier is neither
# whitespace nor a `//` comment opener, so the call-result-discard shape
# stays unflagged exactly as before.
GO_DISCARD_ERR = re.compile(r"^\s*_\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?://.*)?$")
# Whitespace-or-comment filler allowed between Go braces -- same rationale as
# GO_DISCARD_ERR above and `_PS_WS_OR_COMMENT` below: a comment is not
# whitespace, so a bare `\s*` let any comment (marked or not) defeat "this
# block is empty" detection. `//` line comments and `/* ... */` block
# comments (non-greedy, `[\s\S]` so it can span lines without needing DOTALL
# elsewhere in the pattern) are both treated as filler, not as "real code".
_GO_WS_OR_COMMENT = r"(?:\s|//[^\n]*|/\*[\s\S]*?\*/)*"
# Empty `if err != nil { }` body (same-line, multi-line, or with a comment
# -- marked or not -- sitting between the braces; only `swallow-ok:` with a
# real reason, checked separately, clears a hit).
GO_EMPTY_ERR_CHECK = re.compile(
    r"\bif\s+\w*[Ee]rr\w*\s*!=\s*nil\s*\{" + _GO_WS_OR_COMMENT + r"\}", re.MULTILINE
)
# `if err != nil { return nil }` -- the checked error exists, but the ONLY
# thing the block does is return nil instead of the error. Same-line and
# 3-line forms, and forms with a comment before/after `return nil`.
# Deliberately narrow (a single `return nil` statement and nothing else,
# comments aside, in the block) so a block that logs/wraps/re-returns the
# error alongside a zero value is NOT caught by this pattern.
GO_SWALLOWED_RETURN_NIL = re.compile(
    r"\bif\s+\w*[Ee]rr\w*\s*!=\s*nil\s*\{" + _GO_WS_OR_COMMENT
    + r"return\s+nil\s*;?" + _GO_WS_OR_COMMENT + r"\}",
    re.MULTILINE,
)
# Ignored second return value: `x, _ := call(...)`. WARN-ONLY (soft hit) --
# see the module docstring's "GO SHAPE NOT RELIABLY DETECTABLE" section for
# why this is not a hard block: without the callee's real signature this is
# indistinguishable from the equally common, equally legitimate `(T, bool)`
# "found" idiom.
GO_IGNORED_SECOND_RETURN = re.compile(
    r"^\s*[A-Za-z_][A-Za-z0-9_.\[\]]*\s*,\s*_\s*:?=\s*[A-Za-z_][A-Za-z0-9_.]*\s*\(", re.MULTILINE
)


def _go_hits(added):
    """Return (hard_hits, soft_hits) for the Go regex tier. Operates on
    ADDED text only (see the module docstring's KNOWN LIMITATION note)."""
    hard = []
    soft = []
    lines = added.splitlines()

    for i, line in enumerate(lines):
        m = GO_DISCARD_ERR.match(line)
        if m and re.search(r"(?i)err", m.group(1)) and not _line_has_swallow_ok(line):
            hard.append(
                f"`{line.strip()}` discards an error value instead of handling "
                "it. Handle it, return it, or log it -- or if this really is a "
                "deliberate drop (already handled above, or a cleanup path), "
                "mark it `// swallow-ok: <reason>`."
            )

    for m in GO_EMPTY_ERR_CHECK.finditer(added):
        if _match_has_swallow_ok(added, m):
            continue
        hard.append(
            "an empty `if err != nil { }` body -- the error is checked and then "
            "silently discarded. Handle it, return it, or log it, or mark the "
            "line `// swallow-ok: <reason>` if the empty check is genuinely "
            "intentional."
        )

    for m in GO_SWALLOWED_RETURN_NIL.finditer(added):
        if _match_has_swallow_ok(added, m):
            continue
        hard.append(
            "`if err != nil { return nil }` -- a checked error is discarded by "
            "returning nil instead of returning the error. If the caller "
            "genuinely does not need to see this error, mark it "
            "`// swallow-ok: <reason>`."
        )

    for m in GO_IGNORED_SECOND_RETURN.finditer(added):
        ln_idx = added.count("\n", 0, m.start())
        line = lines[ln_idx] if ln_idx < len(lines) else ""
        if _line_has_swallow_ok(line):
            continue
        soft.append(
            f"`{line.strip()}` discards a second return value -- if the callee "
            "returns `(T, error)` this silently drops the error; if it returns "
            "`(T, bool)` (a \"found\" idiom) this is normal Go. Cannot tell "
            "which without the callee's real signature, so this is a WARNING, "
            "not a block -- confirm the discarded value isn't an error."
        )

    return hard, soft


def _line_has_swallow_ok(line):
    """True iff `line` carries a `# swallow-ok: <reason>` with a real reason."""
    m = SWALLOW_OK.search(line)
    return bool(m and m.group(1).strip())


def _match_has_swallow_ok(text, m):
    """True iff any line spanned by regex match `m` in `text` carries a valid
    `swallow-ok: <reason>` marker. Now that GO_EMPTY_ERR_CHECK,
    GO_SWALLOWED_RETURN_NIL, PS_EMPTY_CATCH, and PS_NULL_CATCH can match
    across multiple lines (a comment sitting between the braces), the marker
    can legitimately land on any of them -- the opening line, an interior
    comment line, or the closing line -- mirroring the Python AST tier's
    handler-aware window (except line / body line / comment line between).
    Checking only the line at `m.start()` would miss a correctly-placed
    marker on an interior line and wrongly keep blocking it."""
    lines = text.splitlines()
    start_ln = text.count("\n", 0, m.start())
    end_ln = text.count("\n", 0, m.end())
    return any(
        _line_has_swallow_ok(lines[i])
        for i in range(start_ln, min(end_ln, len(lines) - 1) + 1)
    )


# --------------------------------------------------------------------------- #
# Python: AST-based swallow detection + neighborhood window
# --------------------------------------------------------------------------- #

def _reconstruct_post_edit(event, path, added):
    """Best-effort full post-edit Python source (mirrors no_type_checking_stub).

    Write: the content IS the file. Edit/MultiEdit: read the on-disk file and
    apply the substitution(s) in memory. Returns (src, edited_spans) where
    edited_spans is a list of (start_line, end_line) the edit introduced. For a
    Write the whole file is the span. If we can't read the file, fall back to
    the fragment with a single span covering all of it.
    """
    ti = event.get("tool_input", {}) or {}
    tool = event.get("tool_name", "")

    if tool == "Write" or ti.get("content") is not None:
        content = ti.get("content") or added
        n = content.count("\n") + 1
        return content, [(1, n)]

    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError:
        n = added.count("\n") + 1
        return added, [(1, n)]

    edits = []
    if ti.get("old_string") is not None:
        edits.append((ti["old_string"], ti.get("new_string") or ""))
    for e in ti.get("edits", []) or []:
        if e.get("old_string") is not None:
            edits.append((e["old_string"], e.get("new_string") or ""))

    spans = []
    for old, new in edits:
        if old and old in src:
            idx = src.index(old)
            src = src[:idx] + new + src[idx + len(old):]
            start_line = src.count("\n", 0, idx) + 1
            end_line = start_line + new.count("\n")
            spans.append((start_line, end_line))
    if not spans:
        # Couldn't locate the edit (e.g. new file / not found). Be safe: scan
        # the whole reconstructed source rather than nothing.
        spans = [(1, src.count("\n") + 1)]
    return src, spans


def _toplevel_units(body):
    """Ordered list of (start, end, node) for the top-level statements of a
    statement list that are functions OR class bodies we descend into. We use
    this to build the sibling-function window. Plain statements between funcs
    are kept as (start,end,None) so window radius counts real positions."""
    units = []
    for stmt in body:
        start = getattr(stmt, "lineno", None)
        end = getattr(stmt, "end_lineno", start)
        if start is None:
            continue
        units.append((start, end, stmt))
    return units


def _func_index_containing(units, line):
    """Index into `units` of the function/stmt that contains `line`, else None."""
    for i, (s, e, _node) in enumerate(units):
        if s <= line <= e:
            return i
    return None


def _collect_swallows(node, src_lines):
    """Yield (lineno, except_text, marked) for every `except ...: <body that
    only swallows>` inside `node`'s subtree. A swallow = handler whose body is
    a single `pass`, or `...` (Ellipsis), or nothing meaningful. We also flag a
    handler that only `logger.debug`s and then passes? No — to stay aligned
    with the original regex semantics and keep false positives at zero, we
    flag ONLY the bare `pass` / `...` body shape (the unambiguous swallow)."""
    for n in ast.walk(node):
        if isinstance(n, ast.ExceptHandler):
            body = [b for b in n.body if not _is_docstring(b)]
            is_swallow = len(body) == 1 and (
                isinstance(body[0], ast.Pass)
                or (
                    isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and body[0].value.value is Ellipsis
                )
            )
            if not is_swallow:
                continue
            ln = n.lineno
            except_line = src_lines[ln - 1] if 1 <= ln <= len(src_lines) else ""
            # HANDLER-AWARE marker window: except line through the sole body
            # statement (covers the `except` line, comment lines inside the
            # handler, and the `pass`/`...` line — the three natural spots).
            body_ln = body[0].lineno
            marked = any(
                _line_has_swallow_ok(src_lines[i - 1])
                for i in range(ln, min(body_ln, len(src_lines)) + 1)
            )
            yield (ln, except_line.strip(), marked)


def _is_docstring(stmt):
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _neighborhood_nodes(tree, edited_spans):
    """Return the set of AST nodes whose subtree forms the neighborhood window
    for the edit. For each edited line we find the enclosing scope and, when it
    is a function inside a class/module body, include +/-NEIGHBORS sibling
    functions. When the edited line is at class-body / module level (not inside
    a function), the whole enclosing class body / module is the window."""
    windows = []
    edited_lines = set()
    for s, e in edited_spans:
        edited_lines.update(range(s, e + 1))

    # Candidate parent scopes: module + every class. For each, lay out its
    # top-level units and see if any edited line lands inside a function unit.
    scopes = [("module", tree, tree.body)]
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef):
            scopes.append(("class", n, n.body))

    matched_function = False
    for _kind, scope_node, body in scopes:
        units = _toplevel_units(body)
        if not units:
            continue
        for line in edited_lines:
            idx = _func_index_containing(units, line)
            if idx is None:
                continue
            _s, _e, node = units[idx]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                matched_function = True
                lo = max(0, idx - NEIGHBORS)
                hi = min(len(units) - 1, idx + NEIGHBORS)
                for j in range(lo, hi + 1):
                    windows.append(units[j][2])

    if not matched_function:
        # Edit landed at class-body / module level (between functions, in a
        # class attribute area, decorators, imports, etc.). Scan the smallest
        # enclosing scope: the innermost class whose span contains an edited
        # line, else the whole module.
        best = None
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                s = getattr(n, "lineno", None)
                e = getattr(n, "end_lineno", s)
                if s is None:
                    continue
                if any(s <= ln <= e for ln in edited_lines):
                    if best is None or (e - s) < (best[1] - best[0]):
                        best = (s, e, n)
        windows.append(best[2] if best else tree)

    return windows


def _python_hits(event, path, added):
    """Return (hard_hits, marked_count) for the Python neighborhood scan."""
    src, edited_spans = _reconstruct_post_edit(event, path, added)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # Post-edit file doesn't parse — fall back to the OLD diff-only regex on
        # the added fragment so we still catch a newly-introduced `except: pass`
        # even before the file is syntactically whole. Other tooling reports the
        # syntax error itself.
        return _python_regex_fallback(added), 0

    src_lines = src.splitlines()
    nodes = _neighborhood_nodes(tree, edited_spans)

    seen = set()
    hard = []
    for node in nodes:
        for ln, text, marked in _collect_swallows(node, src_lines):
            if ln in seen:
                continue
            seen.add(ln)
            if marked:
                continue
            hard.append((ln, text))
    return hard, 0


# Diff-only fallback regexes (only used when the post-edit file won't parse).
PY_BARE_SWALLOW = re.compile(r"except[^\n:]*:\s*\n\s*pass\b", re.MULTILINE)
PY_INLINE_SWALLOW = re.compile(r"except[^\n:]*:\s*pass\b")


def _python_regex_fallback(added):
    hits = []
    lines = added.splitlines()
    for m in list(PY_BARE_SWALLOW.finditer(added)) + list(PY_INLINE_SWALLOW.finditer(added)):
        # Honor a swallow-ok marker on any line the match spans (the `except`
        # line or the `pass` line), mirroring the AST path's handler window.
        ln_start = added.count("\n", 0, m.start())
        ln_end = added.count("\n", 0, m.end())
        if any(_line_has_swallow_ok(ln) for ln in lines[ln_start:ln_end + 1]):
            continue
        line = lines[ln_start] if ln_start < len(lines) else ""
        hits.append((ln_start + 1, line.strip()))
    return hits


# --------------------------------------------------------------------------- #
# PowerShell (regex over added text, with line-aware marker honoring)
# --------------------------------------------------------------------------- #

def _powershell_hits(added):
    hits = []
    for pat, why in (
        (PS_EMPTY_CATCH, "an empty/no-op `catch { }` that silently swallows a "
                         "terminating error. Handle it, rethrow with `throw`, or "
                         "remove the try."),
        (PS_NULL_CATCH, "a `catch { }` whose body only nulls/continues/returns, "
                        "swallowing the error. Handle or rethrow it."),
        (PS_EA_MASK, "a `-ErrorAction SilentlyContinue/Ignore` masking a real "
                     "failure. Use `-ErrorAction Stop` inside a try/catch."),
        (PS_GLOBAL_EA, "a global `$ErrorActionPreference = 'SilentlyContinue'` "
                       "that hides all errors in scope. Scope it to the call."),
    ):
        for m in pat.finditer(added):
            if _match_has_swallow_ok(added, m):
                continue
            hits.append(why)
    return hits


def main():
    event = load_event()
    path, added, _removed = extract(event)

    is_py = bool(path) and path.endswith(PY_EXTS)
    is_ps = bool(path) and path.endswith(PS_EXTS)
    is_go = bool(path) and path.endswith(GO_EXTS)

    # Police only Python/PowerShell/Go source, never test files. GATE ORDER:
    # this extension check is the OUTERMOST blocker for a .go file --
    # established BEFORE `is_engine_path` was ever touched, per the module
    # docstring's "GATE ORDER" note. `is_engine_path`/`is_generated_path`
    # only make sense for the Python/PowerShell branch (engine_dirs config);
    # Go gets its own narrow scope check below instead.
    if path and not (is_py or is_ps or is_go):
        allow()
    if is_test_file(path):
        allow()

    if is_go:
        full_src, _spans = _reconstruct_post_edit(event, path, added)
        if _is_go_generated(path, full_src):
            allow()
    else:
        # Engine-quality hook (Python/PowerShell): only police the engine
        # source dirs configured in audit-scope.yaml -- unchanged from the
        # Python/PowerShell-only version of this hook.
        if path and not is_engine_path(path):
            allow()
        if is_generated_path(path):
            allow()

    hard_hits = []
    soft_hits = []

    if is_py:
        py_hits, _ = _python_hits(event, path, added)
        for ln, text in py_hits:
            hard_hits.append(
                f"line {ln}: `{text}` silently swallows an error. Handle it, "
                "re-raise it, or let it propagate — do not bury it. If the "
                "swallow is genuinely correct (optional-import fallback, "
                "idiomatic asyncio cancel/queue drain, deliberate degrade-to-"
                "default), put `# swallow-ok: <reason>` on the `except` line "
                "or its `pass` line."
            )
    elif not path:
        # No path (malformed/Bash-shaped event): fall back to the regex on added.
        for ln, text in _python_regex_fallback(added):
            hard_hits.append(
                f"`{text}` silently swallows an error. Handle, re-raise, or mark "
                "with `# swallow-ok: <reason>`."
            )

    if is_ps:
        hard_hits.extend(_powershell_hits(added))

    if is_go:
        go_hard, go_soft = _go_hits(added)
        hard_hits.extend(go_hard)
        soft_hits.extend(go_soft)

    for m in EXCUSE_COMMENT.finditer(added):
        snippet = m.group(0)
        (hard_hits if STRICT else soft_hits).append(
            f"a defect-excusing comment ({snippet!r}). A comment is not a fix. "
            "If you cannot solve it, leave the code in an honestly-failing state "
            "and report it — do not annotate the hole and move on."
        )

    if hard_hits:
        msg = ["BLOCKED: this edit hides a problem instead of solving it.\n"]
        msg += [f"  - {h}" for h in hard_hits]
        if soft_hits:
            msg += [f"  - (note) {h}" for h in soft_hits]
        if is_go:
            # Honest scope note: Go is diff-scoped like the PowerShell
            # tier, NOT neighborhood-scanned like Python -- do not claim more
            # coverage than _go_hits() actually provides (see module
            # docstring's KNOWN LIMITATION note).
            msg.append(
                "\nThis check scans the lines you ADDED in this edit (not the "
                "whole file, and not a neighborhood window the way the Python "
                "side gets). If it is genuinely appropriate, audit it with "
                "`// swallow-ok: <reason>`. If the underlying problem is truly "
                "out of scope, STOP and tell the human rather than encoding a "
                "silent workaround."
            )
        else:
            msg.append(
                "\nThis hook scans the NEIGHBORHOOD of your edit (the enclosing "
                "function +/- adjacent functions), not just the lines you changed — "
                "so you cannot build around a pre-existing swallow. Fix the nearby "
                "swallow, or if it is genuinely appropriate, audit it with "
                "`# swallow-ok: <reason>`. If the underlying problem is truly out of "
                "scope, STOP and tell the human rather than encoding a silent workaround."
            )
        block("\n".join(msg))

    if soft_hits:
        emit_event("hook_fire", verdict="warn", payload={"soft_hits": soft_hits[:20]})
        sys.stderr.write("WARNING (allowed): " + "; ".join(soft_hits) + "\n")
    allow()


if __name__ == "__main__":
    main()
