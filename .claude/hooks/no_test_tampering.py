#!/usr/bin/env python3
"""no_test_tampering.py  --  PreToolUse hook, matcher: Edit|Write|MultiEdit

Blocks the most common way an agent fakes a green run: editing the TEST to
fit broken code instead of fixing the code. We only police changes to test
files; production code is free to change.

Blocked patterns when ADDED to a test file:
  Python / pytest / unittest:
  - @pytest.mark.skip / xfail   (BLANKET skip/xfail — the "make it pass" move)
  - pytest.skip(...) / pytest.xfail(...)
  - unittest @skip / self.skipTest(...)
  - assert True  (the classic "make it pass" no-op)
  - a previously-real assertion deleted and replaced with nothing meaningful
  PowerShell / Pester:
  - -Skip on It/Describe/Context, or Set-ItResult -Skipped/-Inconclusive
  - a Should assertion removed and not replaced
  Go (`_test.go`, gated on `is_test_file()` recognizing the suffix — see
  `_common.py`):
  - an UNGUARDED `t.Skip(...)` / `t.SkipNow()` (blanket skip — see
    `_go_blanket_skip_hits()` for the guard heuristic and its known limits)
  - `//go:build ignore` / legacy `// +build ignore` added to a `_test.go` file
  - `t.Fatal`/`t.Fatalf`/`t.Error`/`t.Errorf` removed without replacement
    (folds into the existing net-assertion-removed heuristic below)
  - an assertion target discarded instead of checked: `_ = got` / `_ = err`
  - a `t.Run(...)` subtest commented out

ALLOWED (MI2): a conditional `@pytest.mark.skipif(...)` is a normal tool — a
platform / dependency / environment guard, not test tampering. `skipif` ALWAYS
takes a condition (it cannot blanket-skip the way `skip` can), so it is
permitted. Only the unconditional `skip` / `xfail` family is blocked.

Go's analogue of `skipif` is a `t.Skip(...)` GUARDED by a preceding `if`
(`if testing.Short() { t.Skip(...) }`, a `runtime.GOOS` check, a missing-binary
probe, an unset integration-env check, etc. — same-line or the idiomatic
2-line form). Go's call syntax carries no condition of its own the way
`skipif(...)` does, so "guarded" is inferred from context (the same line, or
the nearest non-comment preceding added line opening an `if` block) rather
than read off the call itself — see `_go_blanket_skip_hits()`'s docstring for
the exact rule and its known false-positive shape.

We deliberately do NOT block adding brand-new tests, importing pytest, etc.

This is advisory-with-teeth: if the test genuinely IS wrong, the agent is
told to stop and ask you rather than silently rewrite it. That is the whole
point — surface the decision to a human instead of letting it be made quietly.

ESCAPE: `# tampering-ok: <reason>` (or PowerShell `<# tampering-ok: <reason> #>`,
Go `// tampering-ok: <reason>`) on the offending line. Rationale is REQUIRED —
a bare `# tampering-ok` with nothing after the colon does not clear the block
(see TAMPERING_OK regex).
"""

import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import load_event, extract, block, allow, is_test_file, added_lines

SKIP_PATTERNS = [
    # --- Python ---
    # Block blanket @skip / @xfail but NOT @skipif (MI2). The negative
    # lookahead `(?!if)` lets `skip` match while `skipif` does not; `xfail` is
    # always blanket here. A conditional `skipif(...)` is an allowed platform/dep
    # guard.
    (re.compile(r"@(pytest\.mark\.)?(skip(?!if)|xfail)\b"), "a blanket skip/xfail marker"),
    (re.compile(r"\bpytest\.(skip|xfail)\s*\("), "a pytest.skip()/xfail() call"),
    (re.compile(r"@unittest\.skip"), "a unittest skip decorator"),
    (re.compile(r"\bself\.skipTest\s*\("), "a self.skipTest() call"),
    (re.compile(r"^\s*assert\s+True\s*(#.*)?$"), "an `assert True` no-op"),
    # --- Pester (PowerShell) ---
    (re.compile(r"\b(It|Describe|Context)\b[^\n]*-Skip\b", re.IGNORECASE),
     "a Pester -Skip on It/Describe/Context"),
    (re.compile(r"\bSet-ItResult\b[^\n]*-(Skipped|Inconclusive)\b", re.IGNORECASE),
     "a Set-ItResult -Skipped/-Inconclusive"),
]

# --- Go ---
# Kept SEPARATE from SKIP_PATTERNS (not merged in) and gated on `path`
# ending in `.go` in main() -- `_ = <var>` in particular is a legitimate,
# fairly common PYTHON idiom too (discarding an unused local/fixture
# result), so applying it to every test file regardless of language would
# introduce a brand-new false-positive class on the Python side this hook
# already covers correctly. Scoping to Go files keeps the existing Python/
# Pester behavior byte-for-byte unchanged.
GO_ONLY_PATTERNS = [
    # `//go:build ignore` / legacy `// +build ignore` dropped onto a _test.go
    # file removes it from compilation entirely -- the file-level analogue of
    # a blanket skip.
    (re.compile(r"^//go:build\b.*\bignore\b|^//\s*\+build\b.*\bignore\b"),
     "a //go:build ignore / +build ignore tag on a _test.go file"),
    # An assertion target discarded instead of checked: `_ = got` / `_ = err`.
    # Deliberately requires a BARE identifier with nothing else on the line
    # (no trailing `(...)`, no `.field`) so it does not fire on the common,
    # legitimate `_ = someCall()` / `_ = obj.Close()` discard-a-call-result
    # idiom -- only a standalone-variable discard matches.
    (re.compile(r"^\s*_\s*=\s*[A-Za-z_][A-Za-z0-9_]*\s*$"),
     "a discard assignment replacing a real check (Go `_ = <var>`)"),
    # A commented-out subtest. Legitimate code essentially never ADDS a
    # brand-new commented-out t.Run(...) line, so no removed/added
    # correlation is required -- the shape alone is the signal.
    (re.compile(r"^\s*//.*\bt\.Run\s*\("), "a commented-out t.Run(...) subtest"),
]

# Line-aware escape marker: `# tampering-ok: <reason>` (mirrors no_swallowed_errors'
# `# swallow-ok:` and no_falsy_zero's `# falsy-zero-ok:`). The rationale is
# REQUIRED — a bare `# tampering-ok` with nothing after does NOT count. A SANCTIONED
# test edit (e.g. dropping an assertion pin for a provably-deleted code path)
# carries this marker so it has a CLEAN application path instead of pressuring
# a guardrail bypass. It is NOT a free pass: the reason must ARTICULATE the
# code change the test now matches (not "approved") -- a reviewer checking the
# marker against the diff should be able to confirm the cited change actually
# exists before accepting it.
# `//` added alongside `#`/`<#` so a Go `// tampering-ok: <reason>` line-comment
# clears the block the same way Python's `#` and PowerShell's `<# ... #>` do.
TAMPERING_OK = re.compile(r"(?:#|<#|//)\s*tampering-ok\s*:\s*(\S.*?)\s*(?:#>)?\s*$")

# --- Go blanket-skip guard heuristic -----------------------------------------
#
# Go's `t.Skip(...)`/`t.SkipNow()` carries no condition in its own call syntax
# the way `pytest.mark.skipif(cond)` does -- the guard, if any, is external: a
# preceding `if`. So "conditional vs blanket" cannot be read off the skip call
# alone; it requires looking at the line(s) around it.
GO_SKIP_RE = re.compile(r"\bt\.Skip(?:Now)?\s*\(")
GO_IF_GUARD_RE = re.compile(r"^\s*if\b.*\{\s*$")
GO_COMMENT_LINE_RE = re.compile(r"^\s*//")


def _go_blanket_skip_hits(lines):
    """Return (label, line) for every ADDED `t.Skip`/`t.SkipNow` call that is
    NOT guarded by an `if`, in a list of already-stripped added lines.

    A call is treated as GUARDED (allowed) when either:
      - the SAME line has an `if` keyword before the skip call (the one-liner
        `if cond { t.Skip(...) }` form), or
      - walking BACKWARD from the skip line, skipping over pure `//` comment
        lines, the first non-comment line opens an `if` block (`if cond {`) --
        the idiomatic 2-line form:
            if testing.Short() {
                t.Skip("skipping in short mode")
            }

    KNOWN LIMITATION (stated here rather than glossed over): this hook only
    ever sees the text actually touched by ONE edit (`added_text`), never the
    whole file. If an edit modifies ONLY the `t.Skip(...)` line inside an
    ALREADY-EXISTING, untouched `if` guard -- e.g. a MultiEdit/Edit whose
    old_string/new_string is just that one line, with the enclosing `if`
    written in an earlier, separate commit -- the guard line never appears in
    `added_text` at all, and this heuristic will misclassify the addition as
    blanket (a false-positive BLOCK, not a false-negative bypass). The escape
    hatch is the same one every other shape here uses:
    `// tampering-ok: <reason>` on the skip line. The asymmetry is deliberate:
    a false-positive block costs one justification line; the alternative (a
    line-local regex that can't see the true guard) would have to either
    trust an unverifiable claim or approximate full-file parsing, neither of
    which fits this hook's existing line-diff-only design.
    """
    hits = []
    for i, line in enumerate(lines):
        m = GO_SKIP_RE.search(line)
        if not m:
            continue
        if re.search(r"\bif\b", line[: m.start()]):
            continue  # same-line guard
        guarded = False
        j = i - 1
        while j >= 0:
            if GO_COMMENT_LINE_RE.match(lines[j]):
                j -= 1
                continue
            guarded = bool(GO_IF_GUARD_RE.match(lines[j]))
            break
        if guarded:
            continue
        hits.append((
            "an unconditional t.Skip(...)/t.SkipNow() (Go) -- wrap it in an "
            "`if` guard (testing.Short(), a runtime/platform/env check) or "
            "justify with // tampering-ok",
            line,
        ))
    return hits


def _has_tampering_ok(line):
    """True iff `line` carries a `# tampering-ok: <reason>` with a real reason."""
    return bool(TAMPERING_OK.search(line))


def _strip_comment_lines(text):
    """Drop full-line `#` (Python/PowerShell-block) and `//` (Go) comments so
    a `# assert ...` / `// t.Fatal(...) example` comment/docstring line does
    not inflate the removed/added assertion counts (false positive)."""
    return "\n".join(
        ln for ln in text.splitlines()
        if not (ln.lstrip().startswith("#") or ln.lstrip().startswith("//"))
    )


def main():
    event = load_event()
    path, added, removed = extract(event)

    if not is_test_file(path):
        allow()

    # Go-only patterns/heuristics are gated on the file being a `.go` file
    # (in practice, given the is_test_file() check above, a `_test.go`) so the
    # existing Python/Pester behavior is byte-for-byte unchanged on non-Go
    # files -- see GO_ONLY_PATTERNS' module comment for why this matters
    # (`_ = <var>` is a legitimate Python idiom too).
    is_go = bool(path) and path.replace("\\", "/").lower().endswith(".go")
    active_patterns = SKIP_PATTERNS + (GO_ONLY_PATTERNS if is_go else [])

    # A SANCTIONED edit carries `# tampering-ok: <reason>`. For a SKIP/xfail hit the
    # marker must sit on the offending line itself (line-aware, like swallow-ok). For
    # the removed-assertion heuristic (e.g. deleting a test for code that no longer
    # exists) the marker is a tombstone anywhere in the added lines.
    # Count sanction markers. For the removed-assertion heuristic, ONE marker no
    # longer waives an arbitrary number of removals — require a marker per NET
    # assertion removed, so a single unrelated `# tampering-ok` can't clear a
    # multi-assertion deletion in the same edit.
    added_lines_list = list(added_lines(added))
    marker_count = sum(1 for line in added_lines_list if _has_tampering_ok(line))

    hits = []
    for line in added_lines_list:
        if _has_tampering_ok(line):
            continue  # this line carries its own sanction marker (line-aware)
        for pat, label in active_patterns:
            if label and pat.search(line):
                hits.append((label, line))

    if is_go:
        # Needs neighboring-line context (the `if` guard, if any), so it runs
        # over the full materialized list rather than per-line like the
        # patterns above -- see _go_blanket_skip_hits()'s docstring.
        hits.extend(
            h for h in _go_blanket_skip_hits(added_lines_list) if not _has_tampering_ok(h[1])
        )

    # Heuristic: a real assertion was removed and nothing assert-y replaced it.
    # Counts Python asserts and Pester `Should` assertions always; Go's
    # t.Fatal/t.Fatalf/t.Error/t.Errorf only when `is_go` (same false-positive
    # rationale as GO_ONLY_PATTERNS -- a bare `t.Fatal(` is not idiomatic
    # Python, but there is no reason to widen the regex for files it can't
    # apply to). Strip full-line comments first so a `# assert ...` /
    # `// t.Fatal(...)` comment line doesn't inflate the count.
    assert_re = r"\bassert\b|\bself\.assert|\bShould\b"
    if is_go:
        assert_re += r"|\bt\.(Fatal|Fatalf|Error|Errorf)\b"
    removed_asserts = len(re.findall(assert_re, _strip_comment_lines(removed)))
    added_asserts = len(re.findall(assert_re, _strip_comment_lines(added)))
    net_removed = removed_asserts - added_asserts
    weakened = net_removed > 0 and marker_count < net_removed

    if hits or weakened:
        lines = ["BLOCKED: this edit weakens a test instead of fixing the code under test.\n"]
        for label, line in hits:
            lines.append(f"  - introduces {label}: {line!r}")
        if weakened:
            lines.append(
                f"  - removes {removed_asserts} assertion(s) and adds back only {added_asserts}"
            )
        lines.append(
            "\nIf this code path is genuinely broken, the correct action is to FIX the "
            "source, not the test. If you believe the TEST ITSELF is wrong, you MAY "
            "change it — but NOT silently. Put `# tampering-ok: <reason>` on the "
            "offending line. The reason is REQUIRED and must either (a) name the code "
            "change that necessitates the test edit, or (b) cite the specific evidence "
            "the test contradicts — sibling cases, the docstring, the documented "
            "contract — when the source is correct and the test is simply wrong. An "
            "independent reviewer checks that claim against the diff at merge."
        )
        block("\n".join(lines))

    allow()


if __name__ == "__main__":
    main()
