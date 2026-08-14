#!/usr/bin/env python3
"""check_escape_markers.py -- diff-scoped CI/pre-push gate: every escape
marker ADDED in a change must be explicitly acknowledged by the human who
committed it.

THE GAP THIS CLOSES
====================================================================
Every guard in this pack that CAN be legitimately overridden ships an
escape marker that requires a reason after its colon -- see
CONTRIBUTING.md section 5 and .claude/hooks/PATTERNS.md's per-guard
entries for the full, live syntax of each one (deliberately not quoted
here as a complete worked example -- see "Self-scan note" below for why).
The marker stops a BARE bypass (the keyword with nothing after the
colon), but nothing downstream reviews the REASON once it is non-empty.
An agent can attach any well-formed-looking prose as a reason on a real
swallowed exception and every guard in this tree waves it through --
well-formed is not the same as TRUE. In the origin system this pack was extracted from,
an independent reviewer adjudicates every marker's reason against the diff
at merge time (see .claude/rules/honesty-guardrails.md, "Tampering-vouch
review"). This pack shipped the markers but nothing to wire that review
into an installer's own CI/CD or push gate. This script is that.

TWO TIERS
====================================================================
TIER A (deterministic, always on, no dependency beyond git):
  1. Diff the working branch against a base ref/sha.
  2. Extract every escape marker ADDED (a `+` line in the unified diff) in
     the diffed, in-scope files -- see "VOCABULARY" and "SCOPE" below.
  3. A marker with an empty/missing reason (BARE) fails outright,
     regardless of anything in the commit message -- a bare marker is
     already a defect on its own terms (CONTRIBUTING.md section 5); no
     trailer can excuse it.
  4. A marker WITH a reason must be named, `<path>:<line>`, in an
     `Escape-Markers:` trailer somewhere in the commits being merged (see
     "TRAILER FORMAT" below). Un-named = fails. This is what forces a new
     escape marker to be VISIBLE at review time (in the commit message a
     human reads) instead of buried three files deep in a diff.
  Never advisory. This is a gate: a non-zero exit here must fail the CI
  job it runs in, the same way the guards it audits refuse to ship as
  warn-only overrides of a real block (CONTRIBUTING.md section 4).

TIER B (optional, gated on ANTHROPIC_API_KEY):
  For every marker that PASSED Tier A (reasoned, and acknowledged in the
  trailer), invoke a COLD `claude -p` subprocess -- no session reuse, no
  context beyond what this script explicitly hands it -- to judge whether
  the stated reason describes a code change or condition actually visible
  in the diff hunk around the marker. Binary verdict; anything that is not
  the exact token PASS (empty output, a timeout, "FAIL", "unclear",
  garbage) is treated as FAIL. This mirrors the origin's tampering-vouch
  rule stated in .claude/rules/honesty-guardrails.md: "AMBIGUOUS FOLDS
  INTO FAIL... An unexplainable test change is exactly what this guardrail
  exists to surface." A Tier B FAIL fails the whole gate exactly like a
  Tier A miss -- Tier B is optional to RUN, not optional to OBEY once it
  runs.
  ANTHROPIC_API_KEY absent -> Tier B is SKIPPED, loudly (a line in the
  report says so by name), and Tier A alone gates the run -- this is the
  one place this script is allowed to do less than its full job, and it
  says so every time it does. ANTHROPIC_API_KEY PRESENT but the `claude`
  binary is not on PATH is a DIFFERENT case and is NOT a silent skip: the
  operator opted in by setting the key, so a missing dependency fails
  loudly (exit 2, naming `claude`) rather than quietly degrading to
  Tier-A-only -- same "ship your dependency or fail loudly, never degrade
  quietly" rule CONTRIBUTING.md section 10 states for `jq` in
  protect-files.sh.

VOCABULARY -- enumerated from the hooks' OWN source, not re-typed
====================================================================
Every entry below is detected by importing the REAL compiled regex (or, for
agent_sizing_gate.py's prompt-text sentinel, the real matching logic) from
the hook that actually enforces it -- see `_load_hook()` below. This is
the same technique .claude/hooks/test_model_tier_parity.py already uses for
MODEL_TIERS ("a THIRD copy of the vocabulary... exactly how the original
bug survived"): a hardcoded second copy of a marker's syntax in THIS file
could itself drift from the guard it's meant to audit, so nothing here
re-types a marker's accepted syntax where the source hook exposes it as an
importable constant.

  marker id                    | governing hook                | forms
  ------------------------------------------------------------------------
  tampering-ok                 | no_test_tampering.py           | #, <# #>, //
  swallow-ok                   | no_swallowed_errors.py         | #, <# #>, //
  host-provides / type-stub-ok | no_type_checking_stub.py       | #
  delete-tests-ok              | no_bash_test_deletion.py       | # (in a Bash command string)
  test-mutate-ok               | no_bash_test_mutation.py       | # (in a Bash command string)
  workflow-model-ok            | workflow_agent_sizing_gate.py  | // (JS)
  opus-leaf-ok                 | agent_sizing_gate.py           | plain text sentinel, no comment syntax
  fable-leaf-ok                | agent_sizing_gate.py           | plain text sentinel, no comment syntax
  doc-ref-ok                   | scripts/check_doc_refs.py      | plain text (any scanned line)

DELIBERATELY EXCLUDED: `falsy-zero-ok`. `no_falsy_zero.py` is NOT a hook
this pack ships -- CONTRIBUTING.md section 6 and docs/hook-manifest.yaml's
own comment name it as the documented cautionary case for vocabulary
coupling and say plainly why it isn't shipped ("the hazard is portable,
the detector is not"). There is no guard in `.claude/hooks/` for this
script to audit a marker against, so listing it here would be auditing a
marker that clears nothing -- confirmed empirically: `ls .claude/hooks/*.py`
has no `no_falsy_zero.py` entry.

SCOPE -- which files Tier A actually scans, and why
====================================================================
Only files whose extension is one a shipped guard's escape marker actually
lives in as source comment syntax: .py .sh .go .ps1 .psm1 .psd1 .js. Three
deliberate exclusions, stated rather than silently applied:

  1. Markdown/YAML documentation (.md, .yaml, .yml) is OUT OF SCOPE. This
     is the load-bearing one: CONTRIBUTING.md, PATTERNS.md,
     docs/guards/*.md and this pack's own README.md quote realistic,
     fully-formed marker examples dozens of times over as worked
     documentation, not as live escapes guarding real code. Scanning .md would make this
     repo's OWN documentation impossible to touch in a PR without
     constant Escape-Markers-trailer friction over prose that clears
     nothing. `doc-ref-ok` (check_doc_refs.py's own suppression marker,
     which legitimately lives mostly in .md/.yaml prose) is consequently
     under-covered by this scope choice -- named here, not hidden, per
     this pack's own "state the exposure" doctrine
     (CONTRIBUTING.md section 6). If you install this gate somewhere that
     leans on doc-ref-ok heavily, widen SCANNED_EXTS and expect doc-PR
     friction as the tradeoff.
  2. `examples/` and `adapters/` are excluded entirely -- mirrors
     run_tests.sh's own suite-discovery exclusions. `examples/*/run.sh`
     scripts deliberately construct marker-shaped JSON fixtures (a
     `swallow-ok` demo line IS the point of example 03); scanning them
     would flag this pack's own worked demonstrations as unacknowledged
     escapes on every touch.
  3. `is_test_file()` paths (imported from `_common.py`, the same
     predicate every shipped guard already uses for the identical reason)
     are excluded. A planted-failure test MUST construct violating marker
     text as a literal fixture to prove detection works (see this script's
     own scripts/test_check_escape_markers.py) -- scanning test fixtures
     would make writing a NEW test for this repo's escape markers
     self-defeating on the very PR that adds it.
  4. THIS FILE ITSELF (`scripts/check_escape_markers.py`, `SELF_PATH`
     below) is excluded. See "Self-scan note" immediately below for why.

Self-scan note (SELF-CONFIG EXCLUSION), for whoever next touches this
file: `MARKER_SPECS` and the `_BARE_*` regexes above ARE this gate's own
configuration -- the literal enumeration of the vocabulary it audits,
exactly the shape scripts/check_release_clean.py's docstring names and
solves for its own forbidden-terms list ("a gate must never read its own
configuration back to itself and count it as contamination"; see that
file's SELF-CONFIG EXCLUSION section and `_self_config_relpaths()`). A
docstring or comment in THIS file that names a marker in its live,
colon-and-reason form (`<keyword>` immediately followed by `:` and real
text) is not a violation to detect -- it is this file explaining itself --
but Tier A's own regexes cannot tell the two apart by reading raw diff
text, and even the BARE-keyword checks for the three markers with no
required comment prefix (`opus-leaf-ok`, `fable-leaf-ok`, `doc-ref-ok` --
see their governing hooks' own docstrings for why they have none) match
ANY bare mention of the word, including this file's own `MarkerSpec(...)`
table entries and regex definitions. Obfuscating every legitimate
reference to keep the raw substring out of this file (the way
check_release_clean.py's home-path/credential regexes are interrupted by
their own regex syntax) would make `MARKER_SPECS` -- the one place a
reader most needs to see the vocabulary plainly -- unreadable. Excluding
this one file by path is the more honest fix: stated here, verified by
`test_self_path_is_excluded_from_its_own_scan` in
scripts/test_check_escape_markers.py, which fails loudly if `SELF_PATH`
ever drifts from this file's real location. Realistic worked examples of
every marker with a reason live instead in docs/escape-markers.md (a .md
file, out of Tier A's scanned-extension set by design -- see point 1
above), which is exactly where this doctrine says
they belong.

TRAILER FORMAT
====================================================================
`Escape-Markers: <path>:<line>` -- one trailer line per acknowledged
marker, or a comma-separated list on one line. Repeated trailer lines are
supported (git trailer convention -- same shape as `Signed-off-by:`
appearing more than once), and every commit in the range being merged is
searched, not just the tip -- a marker introduced in an early commit and
acknowledged in a later one on the same branch is still covered.

EXIT CODES
====================================================================
  0  EXIT_CLEAN          every added marker (if any) is reasoned AND
                          acknowledged AND (if Tier B ran) adjudicated PASS.
  1  EXIT_UNACKNOWLEDGED  at least one bare marker, one reasoned-but-
                          unacknowledged marker, or one Tier B FAIL.
  2  EXIT_USAGE_ERROR    could not compute the diff at all (no base ref
                          given, bad ref, not a git repo) -- distinct from
                          a real, computed, empty/clean diff. Also used
                          when ANTHROPIC_API_KEY is set but the `claude`
                          binary is missing (see TIER B above).

Usage: python3 check_escape_markers.py --base-ref <ref-or-sha> [--root PATH]
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(REPO_ROOT, ".claude", "hooks")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

EXIT_CLEAN = 0
EXIT_UNACKNOWLEDGED = 1
EXIT_USAGE_ERROR = 2

sys.path.insert(0, HOOKS_DIR)
from _common import is_test_file  # noqa: E402  -- same predicate every shipped guard uses


def _load_module(abs_path, modname):
    """Import a hook/script by file PATH, without running its `if __name__
    == "__main__":` block, so we can read its real, live compiled regex
    objects -- not a re-typed copy of them. See module docstring,
    "VOCABULARY". Mirrors .claude/hooks/test_model_tier_parity.py's own
    `_load_module` helper (same technique, same rationale)."""
    spec = importlib.util.spec_from_file_location(modname, abs_path)
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec'ing, not after: check_doc_refs.py
    # declares `@dataclass` classes, and Python's dataclasses machinery
    # resolves `cls.__module__` via `sys.modules` while the class body is
    # still executing -- skip this and exec_module() raises
    # AttributeError('NoneType' object has no attribute '__dict__') deep
    # inside the stdlib, for a reason that has nothing to do with this
    # module's own logic. test_model_tier_parity.py's own `_load_module`
    # gets away without this because neither hook it loads defines a
    # dataclass; check_doc_refs.py does, so this loader needs the extra step.
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_hook(filename):
    return _load_module(os.path.join(HOOKS_DIR, filename), "_esc_" + filename.replace(".py", "").replace("-", "_"))


_H_TAMPERING = _load_hook("no_test_tampering.py")
_H_SWALLOW = _load_hook("no_swallowed_errors.py")
_H_STUB = _load_hook("no_type_checking_stub.py")
_H_BASH_DEL = _load_hook("no_bash_test_deletion.py")
_H_BASH_MUT = _load_hook("no_bash_test_mutation.py")
_H_WORKFLOW_SIZING = _load_hook("workflow_agent_sizing_gate.py")
_H_DOC_REFS = _load_module(os.path.join(SCRIPTS_DIR, "check_doc_refs.py"), "_esc_check_doc_refs")

# ---------------------------------------------------------------------------
# Bare-keyword companions, for markers whose governing hook doesn't already
# export its own BARE_* regex (no_bash_test_deletion.py / no_bash_test_mutation.py
# / workflow_agent_sizing_gate.py do -- reused directly in the detectors
# below, not re-derived). Each pattern here is the SAME comment-prefix
# alternation the real *_OK regex uses, with the reason-tail requirement
# dropped, so it matches the keyword alone, with or without a trailing
# colon -- used only to tell "marker attempted, no reason" apart from "no
# marker on this line at all" for reporting purposes; it never overrides
# what the real regex above it already decided.
# ---------------------------------------------------------------------------
_BARE_TAMPERING_RE = re.compile(r"(?:#|<#|//)\s*tampering-ok\b")
_BARE_SWALLOW_RE = re.compile(r"(?:#|<#|//)\s*swallow-ok\b")
_BARE_STUB_RE = re.compile(r"#\s*(?:host-provides|type-stub-ok)\b")
_BARE_LEAF_RE = re.compile(r"\b(?:opus-leaf-ok|fable-leaf-ok)\b")
_BARE_DOCREF_RE = re.compile(r"\bdoc-ref-ok\b")


def _detect_tampering(line):
    m = _H_TAMPERING.TAMPERING_OK.search(line)
    if m:
        return True, m.group(1).strip()
    if _BARE_TAMPERING_RE.search(line):
        return False, ""
    return None


def _detect_swallow(line):
    m = _H_SWALLOW.SWALLOW_OK.search(line)
    if m:
        return True, m.group(1).strip()
    if _BARE_SWALLOW_RE.search(line):
        return False, ""
    return None


# Reason-text extraction for host-provides/type-stub-ok, used only for the
# report (detection itself comes from the real _H_STUB.MARKER regex below --
# this pattern is not decision-critical, just cosmetic).
_STUB_REASON_RE = re.compile(r"#\s*(?:host-provides|type-stub-ok)\s*:\s*(\S.*)$")


def _detect_stub(line):
    if _H_STUB.MARKER.search(line):
        rm = _STUB_REASON_RE.search(line)
        return True, (rm.group(1).strip() if rm else "")
    if _BARE_STUB_RE.search(line):
        return False, ""
    return None


def _detect_delete_tests(line):
    m = _H_BASH_DEL.ESCAPE.search(line)
    if m:
        return True, m.group(1).strip()
    if _H_BASH_DEL.BARE_ESCAPE.search(line):
        return False, ""
    return None


def _detect_test_mutate(line):
    m = _H_BASH_MUT.ESCAPE.search(line)
    if m:
        return True, m.group(1).strip()
    if _H_BASH_MUT.BARE_ESCAPE.search(line):
        return False, ""
    return None


def _detect_workflow_model_ok(line):
    m = _H_WORKFLOW_SIZING.ESCAPE_RE.search(line)
    if m:
        return True, m.group(1).strip()
    if _H_WORKFLOW_SIZING.BARE_ESCAPE_RE.search(line):
        return False, ""
    return None


def _detect_leaf_sentinel(line, keyword):
    """agent_sizing_gate.py's `_has_leaf_escape` works over a whole PROMPT
    string via `str.find`, not a compiled regex -- there is no object to
    import here. Mirrored BY HAND against that function's own docstring
    (agent_sizing_gate.py:105-116): the sentinel is "<keyword>:", and it is
    "reasoned" iff non-whitespace text follows the colon on the same
    logical line. This is a per-LINE approximation of a function designed
    to scan a whole (possibly multi-line) prompt; see module docstring's
    "SCOPE" section -- committed source is what this script audits, a live
    Agent-tool prompt string is not."""
    sentinel = keyword + ":"
    idx = line.lower().find(sentinel)
    if idx != -1:
        reason = line[idx + len(sentinel):].strip()
        return (True, reason) if reason else (False, "")
    if _BARE_LEAF_RE.search(line) and keyword in line.lower():
        return False, ""
    return None


def _detect_opus_leaf(line):
    return _detect_leaf_sentinel(line, "opus-leaf-ok")


def _detect_fable_leaf(line):
    return _detect_leaf_sentinel(line, "fable-leaf-ok")


def _detect_doc_ref_ok(line):
    m = _H_DOC_REFS._ESCAPE_MARKER_RE.search(line)
    if m:
        # Reason text = whatever the real regex's match already covers,
        # minus the one non-whitespace char its own `\S` consumed at the
        # tail (`match.end() - 1` backs up onto it) -- deliberately NOT a
        # second, hand-typed `"doc-ref-ok:..."` regex here: that literal
        # substring, in THIS file's own source, is exactly the self-scan
        # trap the module docstring's "Self-scan note" describes (SELF_PATH
        # covers the rest of this file, but there's no reason to re-plant
        # the same hazard when the already-imported match object already
        # has everything needed).
        return True, line[m.end() - 1:].strip()
    if _BARE_DOCREF_RE.search(line):
        return False, ""
    return None


@dataclass(frozen=True)
class MarkerSpec:
    marker_id: str
    provenance: str  # "<hook file>:<real object name>" -- an audit trail, not consumed by logic
    detect: object    # Callable[[str], Optional[Tuple[bool, str]]]; None = marker absent on this line


MARKER_SPECS = (
    MarkerSpec("tampering-ok", "no_test_tampering.py:TAMPERING_OK", _detect_tampering),
    MarkerSpec("swallow-ok", "no_swallowed_errors.py:SWALLOW_OK", _detect_swallow),
    MarkerSpec("host-provides/type-stub-ok", "no_type_checking_stub.py:MARKER", _detect_stub),
    MarkerSpec("delete-tests-ok", "no_bash_test_deletion.py:ESCAPE", _detect_delete_tests),
    MarkerSpec("test-mutate-ok", "no_bash_test_mutation.py:ESCAPE", _detect_test_mutate),
    MarkerSpec("workflow-model-ok", "workflow_agent_sizing_gate.py:ESCAPE_RE", _detect_workflow_model_ok),
    MarkerSpec("opus-leaf-ok", "agent_sizing_gate.py:_has_leaf_escape", _detect_opus_leaf),
    MarkerSpec("fable-leaf-ok", "agent_sizing_gate.py:_has_leaf_escape", _detect_fable_leaf),
    MarkerSpec("doc-ref-ok", "check_doc_refs.py:_ESCAPE_MARKER_RE", _detect_doc_ref_ok),
)

# ---------------------------------------------------------------------------
# Scope -- see module docstring, "SCOPE" and "Self-scan note".
# ---------------------------------------------------------------------------
SCANNED_EXTS = {".py", ".sh", ".go", ".ps1", ".psm1", ".psd1", ".js"}
EXCLUDED_DIR_PREFIXES = ("examples/", "adapters/")
# SELF-CONFIG EXCLUSION (mirrors scripts/check_release_clean.py's
# `_self_config_relpaths()`): this gate's own vocabulary table and regex
# definitions are, by construction, a literal enumeration of every marker
# this script exists to audit -- scanning them means this script can never
# report clean about its own diff. Repo-root-relative, posix-separated, to
# match the paths `_scan_diff()` reports (git diff paths are always posix).
SELF_PATH = "scripts/check_escape_markers.py"


def _in_scope(path):
    if path == SELF_PATH:
        return False
    if any(path.startswith(p) for p in EXCLUDED_DIR_PREFIXES):
        return False
    if os.path.splitext(path)[1].lower() not in SCANNED_EXTS:
        return False
    if is_test_file(path):
        return False
    return True


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------
_FILE_HEADER_RE = re.compile(r"^\+\+\+ b/(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class Hit:
    path: str
    line: int
    marker_id: str
    has_reason: bool
    reason: str
    provenance: str
    diff_context: str


def _compute_diff(repo, base_ref):
    """Returns (diff_text, error). `error` is None on success -- including
    a successfully-computed EMPTY diff (base_ref == HEAD, or a merge with no
    content change), which is a legitimate clean state, not an error. A
    non-None `error` means the diff itself could not be computed at all
    (bad ref, not a git repo, git missing) -- see EXIT_USAGE_ERROR."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "diff", "--unified=3", "--no-color", f"{base_ref}...HEAD"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, proc.stderr.strip() or f"git diff exited {proc.returncode}"
    return proc.stdout, None


def _scan_diff(diff_text):
    """Returns (hits, files_touched, files_scanned). `files_touched` is
    every file the diff mentions at all; `files_scanned` is the subset that
    passed `_in_scope()` -- reported separately so a reader can see "this
    PR touched 12 files, 3 were in this gate's scanned-extension set" and
    sanity-check the scope decision, per this pack's own vacuity doctrine
    (report coverage, don't let a scoped-to-nothing run look identical to a
    genuinely clean one)."""
    hits = []
    files_touched = set()
    files_scanned = set()
    current_file = None
    in_scope = False
    hunk_buffer = []
    new_lineno = 0

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            current_file = None
            in_scope = False
            continue
        fm = _FILE_HEADER_RE.match(raw)
        if fm:
            path = fm.group(1)
            if path == "/dev/null":
                current_file = None
                in_scope = False
                continue
            current_file = path
            files_touched.add(path)
            in_scope = _in_scope(path)
            if in_scope:
                files_scanned.add(path)
            continue
        if current_file is None:
            continue
        hm = _HUNK_HEADER_RE.match(raw)
        if hm:
            new_lineno = int(hm.group(1))
            hunk_buffer = [raw]
            continue
        if raw.startswith("---") or raw.startswith("\\ No newline"):
            continue
        hunk_buffer.append(raw)
        if raw.startswith("+"):
            if in_scope:
                text = raw[1:]
                for spec in MARKER_SPECS:
                    result = spec.detect(text)
                    if result is None:
                        continue
                    has_reason, reason = result
                    hits.append(Hit(
                        path=current_file, line=new_lineno, marker_id=spec.marker_id,
                        has_reason=has_reason, reason=reason, provenance=spec.provenance,
                        diff_context="\n".join(hunk_buffer[-40:]),
                    ))
            new_lineno += 1
        elif raw.startswith("-"):
            pass  # removed line -- does not consume a NEW-file line number
        else:
            new_lineno += 1  # context line

    return hits, files_touched, files_scanned


# ---------------------------------------------------------------------------
# Escape-Markers commit trailer
# ---------------------------------------------------------------------------
_TRAILER_RE = re.compile(r"^Escape-Markers:\s*(.+)$", re.MULTILINE)
_TOKEN_RE = re.compile(r"^(.+):(\d+)$")


def _collect_trailer_locations(repo, base_ref):
    """Returns (locations, malformed_tokens). `locations` is the set of
    (path, line) pairs acknowledged by an `Escape-Markers:` trailer in ANY
    commit in `base_ref..HEAD` -- not just the tip, so a marker introduced
    early and acknowledged later on the same branch is still covered.
    Returns (set(), []) if the commit range can't be read (caller already
    validated the base ref via `_compute_diff` before this is called, so
    that should not happen in practice; degrading to "nothing acknowledged"
    here is the safe direction -- it can only make the gate MORE strict,
    never silently permissive)."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "log", f"{base_ref}..HEAD", "--format=%B%x00"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set(), []
    if proc.returncode != 0:
        return set(), []

    locations = set()
    malformed = []
    for body in proc.stdout.split("\x00"):
        for m in _TRAILER_RE.finditer(body):
            for token in m.group(1).split(","):
                token = token.strip()
                if not token:
                    continue
                tm = _TOKEN_RE.match(token)
                if not tm:
                    malformed.append(token)
                    continue
                locations.add((tm.group(1).strip(), int(tm.group(2))))
    return locations, malformed


# ---------------------------------------------------------------------------
# Tier B -- optional, ANTHROPIC_API_KEY-gated LLM adjudication
# ---------------------------------------------------------------------------
_TIER_B_PROMPT_TEMPLATE = """You are an independent, COLD reviewer auditing exactly one escape marker \
in a code diff. You have no prior context beyond what is shown below -- do not assume anything \
about this project you were not told here.

Marker kind: {marker_id}
Location: {path}:{line}
Stated reason (from the marker itself, or an Escape-Markers commit trailer): {reason!r}

Diff hunk containing this marker (unified diff format; a leading '+' is an added line, '-' is a \
removed line, ' ' is unchanged context):
-----
{diff_context}
-----

Question: does the stated reason describe a code change or condition that is ACTUALLY VISIBLE in \
the diff hunk above? A generic reason ("needed for this to work", "approved"), a reason that does \
not match what the hunk shows, or a reason you cannot confirm from the hunk alone, is NOT good \
enough.

Answer with EXACTLY one word, alone on the last line of your response: PASS or FAIL.
"""


def _build_tier_b_prompt(hit):
    return _TIER_B_PROMPT_TEMPLATE.format(
        marker_id=hit.marker_id, path=hit.path, line=hit.line,
        reason=hit.reason, diff_context=hit.diff_context,
    )


def _tier_b_adjudicate(hit, claude_bin, timeout=90):
    """Returns (passed: bool, detail: str). Every non-PASS outcome --
    including a timeout, a launch failure, empty output, or any verdict
    text other than the exact token PASS -- folds to FAIL. See module
    docstring, TIER B, and .claude/rules/honesty-guardrails.md's
    "AMBIGUOUS FOLDS INTO FAIL" rule, which this mirrors."""
    prompt = _build_tier_b_prompt(hit)
    try:
        proc = subprocess.run(
            [claude_bin, "-p", prompt], capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"claude -p timed out after {timeout}s"
    except OSError as exc:
        return False, f"claude -p failed to launch: {exc}"

    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    verdict = lines[-1].upper() if lines else ""
    if verdict == "PASS":
        return True, proc.stdout.strip()
    detail = proc.stdout.strip() or (
        f"(no stdout; exit {proc.returncode}; stderr: {proc.stderr.strip()[:300]})"
    )
    return False, detail


# ---------------------------------------------------------------------------
# Reporting + main
# ---------------------------------------------------------------------------

def _print_hit(h, status):
    print(f"  [{status}] {h.path}:{h.line}  ({h.marker_id})  reason={h.reason!r}  <- {h.provenance}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="repo root (default: current directory)")
    parser.add_argument(
        "--base-ref", default=None,
        help="ref or sha to diff against (also read from GUARDRAILS_ESCAPE_BASE_REF if omitted)",
    )
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    base_ref = args.base_ref or os.environ.get("GUARDRAILS_ESCAPE_BASE_REF")
    if not base_ref:
        sys.stderr.write(
            "FATAL: no base ref given. Pass --base-ref <ref-or-sha> or set "
            "GUARDRAILS_ESCAPE_BASE_REF. This is a diff-scoped gate; it has "
            "nothing to diff against without one -- a push event with no PR "
            "base (e.g. a direct push to main) should not invoke this "
            "script at all. See .github/workflows/ci.yml's escape-markers "
            "job for the no-op-loudly handling of that case.\n"
        )
        return EXIT_USAGE_ERROR

    diff_text, err = _compute_diff(root, base_ref)
    if err is not None:
        sys.stderr.write(
            f"FATAL: could not compute a diff against base ref {base_ref!r} "
            f"in {root!r}: {err}\n"
        )
        return EXIT_USAGE_ERROR

    hits, files_touched, files_scanned = _scan_diff(diff_text)
    trailer_locations, malformed_trailers = _collect_trailer_locations(root, base_ref)

    print(f"check_escape_markers.py -- diffing {base_ref} ...HEAD in {root}")
    print(f"  {len(files_touched)} file(s) touched by the diff, {len(files_scanned)} in this gate's scanned-extension scope")
    if malformed_trailers:
        print(f"  WARNING: {len(malformed_trailers)} malformed Escape-Markers trailer token(s) ignored (want '<path>:<line>'): {malformed_trailers[:10]}")

    bare_hits = [h for h in hits if not h.has_reason]
    reasoned_hits = [h for h in hits if h.has_reason]
    unacknowledged = [h for h in reasoned_hits if (h.path, h.line) not in trailer_locations]
    acknowledged = [h for h in reasoned_hits if (h.path, h.line) in trailer_locations]

    print(f"  {len(hits)} escape marker(s) added: {len(reasoned_hits)} reasoned, {len(bare_hits)} bare")

    tier_b_failures = []
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Tier B (LLM adjudication): SKIPPED -- ANTHROPIC_API_KEY is not set. Tier A alone is gating this run.")
    elif not acknowledged:
        print("Tier B (LLM adjudication): nothing to adjudicate (0 reasoned+acknowledged marker(s)).")
    else:
        claude_bin = shutil.which("claude")
        if not claude_bin:
            sys.stderr.write(
                "FATAL: ANTHROPIC_API_KEY is set (Tier B was requested) but "
                "the `claude` binary is not on PATH. This is a missing "
                "dependency the operator opted into, not an absent-key "
                "skip -- failing loudly rather than silently falling back "
                "to Tier A alone. Install the Claude Code CLI, or unset "
                "ANTHROPIC_API_KEY to run Tier A only.\n"
            )
            return EXIT_USAGE_ERROR
        print(f"Tier B (LLM adjudication): running against {len(acknowledged)} reasoned+acknowledged marker(s) via {claude_bin} -p ...")
        for h in acknowledged:
            ok, detail = _tier_b_adjudicate(h, claude_bin)
            if not ok:
                tier_b_failures.append((h, detail))
        print(f"Tier B (LLM adjudication): {len(acknowledged) - len(tier_b_failures)} PASS, {len(tier_b_failures)} FAIL")

    if bare_hits:
        print("\nBARE markers (no reason -- fails regardless of any trailer):")
        for h in bare_hits:
            _print_hit(h, "BARE")
    if unacknowledged:
        print("\nUNACKNOWLEDGED markers (reasoned, but not named in an Escape-Markers: trailer):")
        for h in unacknowledged:
            _print_hit(h, "UNACKNOWLEDGED")
    if tier_b_failures:
        print("\nTier B ADJUDICATION FAILURES (reason acknowledged, but the cold reviewer could not confirm it against the diff):")
        for h, detail in tier_b_failures:
            _print_hit(h, "TIER-B-FAIL")
            print(f"        reviewer said: {detail.splitlines()[-1] if detail else '(empty)'}")

    if bare_hits or unacknowledged or tier_b_failures:
        print(
            "\nFAIL -- add `Escape-Markers: <path>:<line>[, <path>:<line> ...]` "
            "to a commit message in this range for every reasoned marker "
            "above, and remove or properly reason every bare one. See "
            "docs/escape-markers.md."
        )
        return EXIT_UNACKNOWLEDGED

    print("\ncheck_escape_markers.py :: PASS")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
