"""Shared helpers for honesty-guardrail hooks.

Every command hook receives a JSON object on stdin describing the tool call.
For Edit/Write/MultiEdit the fields we care about are roughly:

  tool_name            "Edit" | "Write" | "MultiEdit"
  tool_input.file_path absolute path being written
  tool_input.content       (Write)  full new file body
  tool_input.new_string    (Edit)   replacement text
  tool_input.old_string    (Edit)   text being replaced
  tool_input.edits[]       (MultiEdit) list of {old_string, new_string}

We normalise all of that into:
  - path: the target file path (str | None)
  - added_text: everything NEW being introduced, concatenated (str)
  - removed_text: everything being REMOVED, concatenated (str)

`added_text` is what almost every guard inspects: it is the text that will
exist in the file after this edit that did not come from the user.
"""

# PEP-604 union syntax (`X | None`) is used below in a MODULE-LEVEL variable
# annotation (`_ENGINE_DIRS_CACHE: tuple | None = None`). Module-level
# annotations are evaluated eagerly at import time -- so without this
# future-import, `import _common` raises `TypeError: unsupported operand
# type(s) for |: 'type' and 'NoneType'` on any interpreter below 3.10. Hooks
# import into whatever interpreter the AUDITED target's environment
# provides, which is not guaranteed to meet this repo's own 3.10+ floor.
# Every other hook module in this pack imports this file, so an import
# failure here is a single point of failure for all of them, and it fails
# OPEN (ImportError -> exit 1 -> non-blocking in the Claude Code hook
# protocol), not closed. See check_interpreter_floor.py and INSTALL.md's
# Dependencies section for the fail-open mechanism this caused and the
# preflight check that now catches it.
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_event():
    """Read and parse the hook JSON from stdin. Never raise on bad input."""
    global _LAST_EVENT
    try:
        ev = json.load(sys.stdin)
    except Exception:
        ev = {}
    _LAST_EVENT = ev if isinstance(ev, dict) else {}
    return _LAST_EVENT


def extract(event):
    """Return (path, added_text, removed_text) from an Edit/Write/MultiEdit event."""
    ti = event.get("tool_input", {}) or {}
    path = ti.get("file_path")

    added_parts = []
    removed_parts = []

    # Write: whole-file content
    if "content" in ti and ti["content"] is not None:
        added_parts.append(str(ti["content"]))

    # Edit: single old/new
    if ti.get("new_string") is not None:
        added_parts.append(str(ti["new_string"]))
    if ti.get("old_string") is not None:
        removed_parts.append(str(ti["old_string"]))

    # MultiEdit: list of edits
    for e in ti.get("edits", []) or []:
        if e.get("new_string") is not None:
            added_parts.append(str(e["new_string"]))
        if e.get("old_string") is not None:
            removed_parts.append(str(e["old_string"]))

    return path, "\n".join(added_parts), "\n".join(removed_parts)


def block(message):
    """Block the tool call: write feedback to stderr and exit 2.

    Exit 2 is the magic number — Claude Code feeds stderr back to the agent
    as a blocked action it must address. Exit 1 does NOT block; it is a
    non-blocking error. So this must be exactly 2.
    """
    emit_event("hook_fire", verdict="block", payload={"message": str(message)[:800]})
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(2)


def allow():
    emit_event("hook_fire", verdict="allow")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Model-tier vocabulary, shared by the two agent-sizing gates:
# agent_sizing_gate.py (the Agent tool, one call per event) and
# workflow_agent_sizing_gate.py (the Workflow tool, static-parses every
# agent() call site in a script). Both used to define their own local
# `VALID` set and drifted (one recognised "fable", the other didn't) --
# defining it once here and having both gates import it is what keeps that
# from recurring. See test_model_tier_parity.py for the regression canary.
#
# THIS IS VOCABULARY COUPLING, NOT A GENERAL PROPERTY: "haiku", "sonnet",
# "opus", "fable" are Claude model-tier names. A user running these guards
# against a different model lineup (a different provider, or a future Claude
# lineup with different tier names) must edit this set to match their own
# model names -- otherwise both gates will reject every `model:` value the
# user actually passes, because none of them will be in this list.
MODEL_TIERS = frozenset({"haiku", "sonnet", "opus", "fable"})

# Frontier tiers within MODEL_TIERS: agent_sizing_gate.py's sizing heuristic
# couples model tier to rung -- opus and fable both mean "this belongs in a
# standalone orchestrator session", never a leaf spawn -- and blocks a leaf
# spawn using either unless the caller takes the documented narrow exception.
# workflow_agent_sizing_gate.py has no frontier-leaf concept (opus/fable are
# ordinary valid tiers there, per that module's docstring), so only
# agent_sizing_gate.py consumes this constant.
FRONTIER_MODEL_TIERS = frozenset({"opus", "fable"})


def is_test_file(path):
    if not path:
        return False
    p = path.replace("\\", "/").lower()
    base = p.rsplit("/", 1)[-1]
    return (
        base.startswith("test_")
        or base.endswith("_test.py")
        or base.endswith("_test.go")  # Go: co-located, e.g. modules/foo/bar_test.go
        or "/tests/" in p
        or "/test/" in p
        or base == "conftest.py"
        or base.endswith(".tests.ps1")  # Pester
    )


def added_lines(added_text):
    """Yield non-empty stripped lines of added text."""
    for raw in added_text.splitlines():
        s = raw.strip()
        if s:
            yield s


# ---------------------------------------------------------------------------
# Role + path scoping
#
# Two orthogonal dimensions decide whether an engine-quality hook fires:
#
#   1. PATH SCOPE  — engine-quality hooks (no_falsy_zero, no_type_checking_stub,
#      no_swallowed_errors) only police the engine source dirs configured in
#      docs/audit/audit-scope.yaml's `engine_dirs`. An edit outside those dirs, or
#      anything outside those trees is INERT for these hooks — role-independent.
#      This is what dissolves most of the "don't hamstring other roles" concern
#      at the path layer.
#
#   2. ROLE        — coding (default), integrator (GUARDRAILS_INTEGRATOR_ROLE=1), and a
#      reserved hook for a future domain dimension. The honesty/safety hooks
#      (no_test_tampering, no_bash_test_deletion) stay UNIVERSAL regardless of
#      role -- they never consult agent_role() at all. A role-aware consumer
#      (like no_bash_test_mutation's integrator bypass) makes its OWN scoped
#      decision per role instead of getting one handed down from here.
#
# `agent_role()` returns a single string today; `domain_for_path()` is the
# placeholder seam for the forward-note folder/domain hook sets — it always
# returns None now, so callers can already branch on it without a rewrite when
# domains land.
# ---------------------------------------------------------------------------

# Engine source roots live in docs/audit/audit-scope.yaml's `engine_dirs`
# section, not inline here -- keep the source-tree-specific config in one
# small file rather than baking dir names into hook logic.
# is_engine_path() loads and caches it lazily below.
#
# _AUDIT_SCOPE_ROOT resolves relative to THIS FILE, not project_dir(). That
# distinction is load-bearing: a regression test may set CLAUDE_PROJECT_DIR to
# a throwaway temp dir, to isolate an on-disk Edit fixture from the real tree,
# without meaning to also relocate where audit-scope.yaml is looked up.
# project_dir() is correct for relativizing the EDITED file's path (that
# legitimately follows CLAUDE_PROJECT_DIR so fixture roots resolve
# correctly), but audit-scope.yaml is guardrail INFRASTRUCTURE config, not
# part of the edit under test — it lives next to this script, not wherever
# CLAUDE_PROJECT_DIR happens to point for a given invocation. Using
# project_dir() here would reproduce a specific self-inflicted hazard: a
# self-locating check whose ground shifts under it and silently stops
# working under a legitimate CLAUDE_PROJECT_DIR override, without ever
# printing an error a human would notice mid-suite (it manifests as a
# spurious BLOCK on a case that should ALLOW).
_AUDIT_SCOPE_ROOT = Path(__file__).resolve().parent.parent.parent


class AuditScopeLoadError(RuntimeError):
    """Raised when audit-scope.yaml's `engine_dirs` section is missing or
    malformed.

    Deliberately NOT given a silent embedded-defaults fallback. But also
    deliberately NOT a module-level `sys.exit()` the way a standalone script
    with its own config loader can afford to do it: a standalone script fails
    once, visibly, when a human runs it directly. This module is re-imported
    by every honesty-guardrail hook on every Edit/Write/MultiEdit call — a
    module-level sys.exit(1) here would take down hooks that never call
    is_engine_path() at all, and per this module's own `block()` docstring,
    exit(1) is NON-blocking (only exit(2) blocks), so it would actually fail
    OPEN: every engine-quality hook would silently stop checking anything the
    instant this config went missing — precisely the "guardrail keeps
    appearing to run but checks nothing" failure mode this whole pack exists
    to prevent. is_engine_path() converts this exception into an explicit
    `block()` (loud, exit 2) instead, confining the blast radius to exactly
    the hooks that use engine-path scoping and making the failure impossible
    to miss.
    """


_ENGINE_DIRS_CACHE: tuple | None = None


def _load_engine_dirs():
    """Load, validate, and cache the `engine_dirs` list from
    docs/audit/audit-scope.yaml. Raises AuditScopeLoadError on any failure;
    callers (is_engine_path) are responsible for turning that into a loud
    block() rather than a silent fallback."""
    global _ENGINE_DIRS_CACHE
    if _ENGINE_DIRS_CACHE is not None:
        return _ENGINE_DIRS_CACHE
    scope_path = _AUDIT_SCOPE_ROOT / "docs" / "audit" / "audit-scope.yaml"
    if not scope_path.exists():
        raise AuditScopeLoadError(
            f"audit-scope.yaml not found at {scope_path} — engine-quality "
            "guardrails cannot determine path scope without it."
        )
    try:
        import yaml
    except ImportError as exc:
        raise AuditScopeLoadError(f"PyYAML not importable: {exc}") from exc
    try:
        raw_text = scope_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_text)
    except (OSError, yaml.YAMLError) as exc:
        raise AuditScopeLoadError(
            f"audit-scope.yaml at {scope_path} could not be loaded: {exc}"
        ) from exc
    if not isinstance(data, dict) or "engine_dirs" not in data:
        raise AuditScopeLoadError(
            f"audit-scope.yaml at {scope_path} is missing required section 'engine_dirs'"
        )
    dirs = data["engine_dirs"]
    if not isinstance(dirs, list) or not all(isinstance(d, str) for d in dirs):
        raise AuditScopeLoadError(
            f"audit-scope.yaml section 'engine_dirs' must be a list of strings, got {dirs!r}"
        )
    _ENGINE_DIRS_CACHE = tuple(dirs)
    return _ENGINE_DIRS_CACHE


def project_dir():
    """Repo root: CLAUDE_PROJECT_DIR if Claude Code set it, else walk up from
    this file (.claude/hooks/_common.py -> repo root is two dirs up)."""
    pd = os.environ.get("CLAUDE_PROJECT_DIR")
    if pd:
        return os.path.abspath(pd)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rel_to_project(path):
    """Best-effort path of `path` relative to the project dir, '/'-normalised.
    If `path` is already relative or outside the project, return it normalised."""
    if not path:
        return ""
    p = path.replace("\\", "/")
    root = project_dir().replace("\\", "/").rstrip("/")
    if p.startswith(root + "/"):
        p = p[len(root) + 1:]
    return p.lstrip("./")


def is_engine_path(path):
    """True iff `path` lives under an engine source dir (as configured in
    by default — see docs/audit/audit-scope.yaml's `engine_dirs`).

    Engine-quality hooks call this first and `allow()` immediately when it is
    False, so they go inert for docs/frontend/strategy edits without any
    per-hook path logic. Resolves both absolute and project-relative inputs.

    A missing/malformed audit-scope.yaml BLOCKs the calling hook (loud, exit 2)
    instead of silently allowing or crashing every hook that imports this
    module — see AuditScopeLoadError's docstring.
    """
    rel = _rel_to_project(path)
    if not rel:
        return False
    first = rel.split("/", 1)[0]
    try:
        engine_dirs = _load_engine_dirs()
    except AuditScopeLoadError as exc:
        block(
            "BLOCKED: cannot load docs/audit/audit-scope.yaml's engine_dirs — "
            f"an engine-quality guardrail cannot determine path scope without "
            f"it: {exc}\nFix or restore audit-scope.yaml. This is a "
            "guardrail-config failure, not a finding about this specific edit."
        )
    return first in engine_dirs


# Generated / vendored trees that live under an engine dir but are NOT
# hand-authored engine source: mutation-test output, a compiled/vendored
# trainer cache, anything similar a user configures. Findings there are build
# artifacts, not honesty failures. Shared by ALL engine-quality file hooks
# (was private to no_swallowed_errors; false positives on other engine-
# quality hooks over the same generated trees showed the exemption belongs to
# the class, not one hook).
#
# Loaded from docs/audit/audit-scope.yaml's `generated_paths`, same file and
# resolution root as `engine_dirs` / `_load_engine_dirs()` above -- but NOT
# the same hardcoded-tuple shape those used to be: this used to be a literal
# tuple of ANOTHER project's paths baked into this module (a specific
# pack-authoring mistake -- live runtime config carrying one origin
# codebase's own vocabulary, the exact failure mode PATTERNS.md's vocabulary-
# coupling entry warns about, and made worse here because no `backend/`
# directory exists in this pack or in any adopter's repo by coincidence, so
# the hardcoded list was silently inert for every user of this pack). See
# _load_generated_paths()'s docstring for why "section missing" and "section
# malformed" get deliberately DIFFERENT treatment, unlike engine_dirs' single
# "missing-or-malformed -> block" policy.
_GENERATED_PATHS_CACHE: tuple | None = None


def _load_generated_paths():
    """Load, validate, and cache the `generated_paths` list from
    docs/audit/audit-scope.yaml. Same file, same resolution root
    (_AUDIT_SCOPE_ROOT), same load/parse plumbing as `_load_engine_dirs()` --
    but a DIFFERENT missing-key policy, decided deliberately:

      - SECTION ABSENT ENTIRELY (not in the parsed YAML dict) -> returns an
        empty tuple, no error. `generated_paths` exempts trees from two
        engine-quality guards; an empty list means "exempt nothing", which
        can only make those guards check MORE of a user's tree, never less --
        the safe direction, so there is nothing to protect against by
        blocking here. Most repos have no generated/vendored trees to
        exempt at all (this pack ships with the section commented out, see
        audit-scope.yaml), and `engine_dirs`' hard-block-on-missing policy
        would make every fresh install fail closed on ordinary engine edits
        until the user adds a section they may not even need -- the kind of
        friction that gets a guardrail disabled rather than configured.
      - SECTION PRESENT BUT MALFORMED (not a list of strings) -> raises
        AuditScopeLoadError, same as a malformed engine_dirs. This is a real
        authoring mistake (someone tried to configure the exemption and got
        the shape wrong) -- silently treating it the same as "not
        configured" would hide the mistake instead of surfacing it, which is
        a DIFFERENT failure than the merely-absent case above and must not
        collapse into the same safe default.

    Callers (is_generated_path) turn AuditScopeLoadError into a loud block(),
    exactly like _load_engine_dirs()'s callers do."""
    global _GENERATED_PATHS_CACHE
    if _GENERATED_PATHS_CACHE is not None:
        return _GENERATED_PATHS_CACHE
    scope_path = _AUDIT_SCOPE_ROOT / "docs" / "audit" / "audit-scope.yaml"
    if not scope_path.exists():
        # In practice every caller of is_generated_path() calls
        # is_engine_path() first (see no_swallowed_errors.py's GATE ORDER
        # note), which already requires this same file to exist -- so this
        # branch is unreachable via the shipped call order. Kept anyway so a
        # standalone caller of is_generated_path() fails loud rather than
        # silently, instead of relying on that ordering.
        raise AuditScopeLoadError(
            f"audit-scope.yaml not found at {scope_path} — engine-quality "
            "guardrails cannot determine the generated-path exemption list "
            "without it."
        )
    try:
        import yaml
    except ImportError as exc:
        raise AuditScopeLoadError(f"PyYAML not importable: {exc}") from exc
    try:
        raw_text = scope_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_text)
    except (OSError, yaml.YAMLError) as exc:
        raise AuditScopeLoadError(
            f"audit-scope.yaml at {scope_path} could not be loaded: {exc}"
        ) from exc
    if not isinstance(data, dict) or "generated_paths" not in data:
        _GENERATED_PATHS_CACHE = ()
        return _GENERATED_PATHS_CACHE
    paths = data["generated_paths"]
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise AuditScopeLoadError(
            "audit-scope.yaml section 'generated_paths' must be a list of "
            f"strings, got {paths!r}"
        )
    _GENERATED_PATHS_CACHE = tuple(paths)
    return _GENERATED_PATHS_CACHE


def is_generated_path(path):
    """True iff `path` is under a generated/vendored tree that engine-quality
    hooks should not police, as configured in docs/audit/audit-scope.yaml's
    `generated_paths`.

    An unconfigured (section-absent) audit-scope.yaml is NOT an error here --
    see _load_generated_paths()'s docstring for why that differs from
    is_engine_path()'s missing-engine_dirs handling. A malformed section
    still BLOCKs the calling hook (loud, exit 2), same polarity as
    is_engine_path()."""
    rel = _rel_to_project(path)
    if not rel:
        return False
    try:
        generated_paths = _load_generated_paths()
    except AuditScopeLoadError as exc:
        block(
            "BLOCKED: cannot load docs/audit/audit-scope.yaml's "
            "generated_paths — an engine-quality guardrail cannot determine "
            f"the generated-path exemption list: {exc}\nFix or restore "
            "audit-scope.yaml. This is a guardrail-config failure, not a "
            "finding about this specific edit."
        )
    return any(rel.startswith(pre) for pre in generated_paths)


def agent_role():
    """The current agent role.

      'integrator'  — the blessed-repo guardian (GUARDRAILS_INTEGRATOR_ROLE=1).
                      Keeps the universal safety hooks; a role-aware guard or
                      Stop-hook a user wires up on top of this pack can branch
                      on this to run its own scoped check for this role
                      instead of the default one (see no_bash_test_mutation's
                      integrator bypass for the one example already shipped).
      'coding'      — the default worker.

    Reserved seam for future domain-specific roles this pack doesn't define
    today (see domain_for_path() below for the matching path-side seam).
    """
    if os.environ.get("GUARDRAILS_INTEGRATOR_ROLE", "") not in ("", "0", "false", "False"):
        return "integrator"
    return "coding"


def domain_for_path(path):
    """Reserved seam for the forward-note domain dimension (folder/domain hook
    sets mirroring the context-docs + dep-map partitions: frontend / data-ingress
    / engine, each with its own shard-tests). Returns None today; callers may
    branch on it now so adding domains later needs no signature change."""
    return None


# ---------------------------------------------------------------------------
# Blessed-repo location + tracked-file test
#
# A "blessed" repo is one whose git-TRACKED files are edit-restricted for
# automated sessions: they MAY write UNTRACKED scratch there (notes, planning
# docs, test output) but must NOT modify git-TRACKED files. A modified
# tracked file is exactly what aborts a merge-owning session's `git checkout`
# / `git merge`. This module provides the location-resolution and
# tracked-file-test PRIMITIVES (`blessed_root()`, `is_under_blessed()`,
# `is_tracked_in_blessed()`) that a guard hook can build on to enforce that
# restriction. No hook shipped in this pack currently consumes them; they
# exist so a user who wants that guard doesn't have to reinvent
# root-resolution from scratch. An integrator-role session (see
# GUARDRAILS_INTEGRATOR_ROLE / agent_role() above) is the natural role to
# exempt from such a guard, since it owns the merge.
#
# blessed_root() replaces a hardcoded source-tree literal with a derivation
# chain:
#   1. env BLESSED_REPO, if set and non-empty
#   2. harness.env at the repo root containing this file, if it sets that name
#   3. derive from this file's own repo (`git rev-parse --show-toplevel`):
#        a. remote 'blessed' whose URL is a LOCAL FILESYSTEM PATH -> that path
#        b. else remote 'origin' whose URL is a LOCAL FILESYSTEM PATH -> that path
#        c. else -> the repo itself
#   4. unresolvable (not a git repo) -> hard fail via block() (exit 2, BLOCKING),
#      never a silent default and never a bare exit(1) -- see _fatal_no_blessed_root().
#
# No hardcoded absolute path appears anywhere in this chain.
#
# LAZY RESOLUTION (harness-portability, hook-enforce fix): blessed_root() is
# NEVER called at module import time. `BLESSED_REPO` is exposed as a
# module-level name for backward compatibility (some tests do
# `from _common import BLESSED_REPO`), but it is served by `__getattr__`
# below, which calls blessed_root() on first ACCESS, not on import. Internal
# callers (is_under_blessed, is_tracked_in_blessed) call blessed_root()
# directly rather than reading a cached module global.
#
# WHY THIS MATTERS: this module is imported by every honesty-guardrail hook,
# including ones that never touch blessed-repo logic at all (no_falsy_zero,
# no_type_checking_stub, etc.). A prior version resolved the root eagerly at
# `import _common` time with `BLESSED_REPO = blessed_root()` at module scope.
# On a tree where the root cannot resolve, that raised the FATAL case DURING
# IMPORT -- before the importing hook's own detection logic ever ran -- and
# used to do it via a bare `sys.exit(1)`. Exit 1 is NON-BLOCKING in the Claude
# Code hook protocol (only exit 2 blocks), so the net effect was every
# importing hook silently no-opped (hook fired, exit 1, tool call PERMITTED)
# on any tree where the root didn't resolve -- fail-open on the whole hook
# fleet, not just blessed-repo checks. Lazy resolution means an import alone
# can never kill a hook, and the unresolvable case now blocks (exit 2) with
# an actionable message instead of silently passing.
# ---------------------------------------------------------------------------

def _parse_env_file(path):
    """Minimal KEY=VALUE parser for harness.env -- no python-dotenv dependency.
    Handles '#' comments, blank lines, an 'export ' prefix, and surrounding
    single/double quotes. A line with no '=' is skipped, not an error."""
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except OSError:
        return out
    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key] = val
    return out


def _git_toplevel(start_dir):
    """`git rev-parse --show-toplevel` from `start_dir`; '' if not a git repo,
    git is unavailable, or the call errors."""
    try:
        r = subprocess.run(
            ["git", "-C", start_dir, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def _remote_url(repo, name):
    """URL git has recorded for remote `name` in `repo`; '' if that remote
    doesn't exist or git errors."""
    try:
        r = subprocess.run(
            ["git", "-C", repo, "remote", "get-url", name],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def _is_local_filesystem_remote(url):
    """LOAD-BEARING predicate: a remote URL counts as "local" iff it resolves
    to an EXISTING DIRECTORY on this filesystem. `https://...` and
    `git@host:...` must NEVER match -- without
    this check, a foreign repo cloned from GitHub would resolve its blessed
    root to a URL string instead of falling through to case 4c (the repo
    itself). Do not relax this to a substring/prefix check."""
    if not url:
        return False
    if "://" in url:  # https://, ssh://, git://, file://, ...
        return False
    if re.match(r"^[A-Za-z0-9_.-]+@[^:/]+:", url):  # scp-like git@host:path
        return False
    return os.path.isdir(url)


def _fatal_no_blessed_root():
    """Step 5: nothing resolved. Hard-fail rather than silently defaulting to
    the source tree -- naming harness.env, BLESSED_REPO, and a concrete
    absolute path the operator can create (mirrors project_dir()'s own
    non-git __file__-walk, since git can't tell us the real repo root here).

    Routes through block() (exit 2) rather than a bare sys.exit(1). Exit 1 is
    NON-BLOCKING in the Claude Code hook protocol -- only exit 2 blocks the
    tool call. An unresolvable blessed root is exactly the kind of guardrail-
    infrastructure failure that must stop the operation, not merely log an
    error the caller can outrun (see is_engine_path()'s AuditScopeLoadError
    handling above, which established this same block()-not-exit(1) pattern
    for the sibling "config the guardrail depends on is missing" case)."""
    fallback_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    harness_env_path = os.path.join(fallback_root, "harness.env")
    block(
        "BLOCKED: cannot resolve the blessed repo root -- the directory "
        "containing this hook is not inside a git repository, and "
        "BLESSED_REPO is not set in the environment.\n"
        "Fix: set the BLESSED_REPO environment variable, or create "
        f"{harness_env_path} and set BLESSED_REPO=<path-to-blessed-repo> in it.\n"
    )


def blessed_root():
    """Resolve the blessed integration repo root. See the precedence chain in
    the module comment above.

    Deliberately NOT memoized/cached: env-var checks are cheap (no
    subprocess), and a cached result would go stale the instant a caller
    re-execs a hook module with a different BLESSED_REPO in the same process
    (exactly what the test suite does when it reloads a hook fresh per test
    via importlib) -- that staleness is worse than the couple of extra `git`
    calls recomputing costs on the rare path that reaches step 4."""
    v = os.environ.get("BLESSED_REPO", "").strip()
    if v:
        return v.rstrip("/")

    repo = _git_toplevel(os.path.dirname(os.path.abspath(__file__)))
    if not repo:
        _fatal_no_blessed_root()  # never returns (block() -> exit 2)

    env_path = os.path.join(repo, "harness.env")
    if os.path.isfile(env_path):
        parsed = _parse_env_file(env_path)
        v = (parsed.get("BLESSED_REPO") or "").strip()
        if v:
            return v.rstrip("/")

    blessed_url = _remote_url(repo, "blessed")
    if _is_local_filesystem_remote(blessed_url):
        return blessed_url.rstrip("/")

    origin_url = _remote_url(repo, "origin")
    if _is_local_filesystem_remote(origin_url):
        return origin_url.rstrip("/")

    return repo.rstrip("/")


# NOTE: no `BLESSED_REPO = blessed_root()` here. That used to run at import
# time and could sys.exit() before any importing hook's detection logic ran
# (see the LAZY RESOLUTION comment above blessed_root()'s docstring block).
# `BLESSED_REPO` is still importable as `from _common import BLESSED_REPO`
# for backward compatibility -- see the module `__getattr__` below, which
# resolves it lazily, on first ACCESS rather than on import.


def __getattr__(name):
    """PEP 562 module-level lazy attribute. Only `BLESSED_REPO` is served
    this way -- everything else in this module is a normal top-level def.

    `from _common import BLESSED_REPO` (a couple of test files still do this)
    triggers a call to blessed_root() at the moment of ACCESS, not at
    `import _common` time. A plain `import _common` (what every honesty hook
    actually does) never touches this and so can never be killed by an
    unresolvable blessed root -- that resolution only happens if/when
    something actually asks for BLESSED_REPO."""
    if name == "BLESSED_REPO":
        return blessed_root()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def resolve_target(cwd, path):
    """Absolute, '/'-normalised path of `path` resolved against `cwd` (the
    event's cwd). Returns '' when it cannot be resolved (relative path + no cwd)."""
    if not path:
        return ""
    p = str(path).strip().strip("'\"").replace("\\", "/")
    if not p:
        return ""
    if not os.path.isabs(p):
        if not cwd:
            return ""
        p = cwd.rstrip("/") + "/" + p
    return os.path.normpath(p)


def is_under_blessed(abs_path, root=None):
    """True iff `abs_path` is the blessed repo root or a path inside it. A
    separate clone of the same repo, checked out elsewhere on disk for a
    parallel session to work in, is NOT under blessed even though its
    contents match -- this is a path check, not a content check.

    `root` lets a caller that already resolved blessed_root() (e.g.
    is_tracked_in_blessed) pass it through instead of triggering a second
    resolution; defaults to a fresh blessed_root() call so this function is
    still safe to call standalone."""
    if not abs_path:
        return False
    if root is None:
        root = blessed_root()
    d = os.path.normpath(str(abs_path).replace("\\", "/")).rstrip("/")
    return d == root or d.startswith(root + "/")


def is_tracked_in_blessed(abs_path):
    """True iff `abs_path` is a git-TRACKED file in the blessed repo.

    Untracked / git-ignored / nonexistent paths return False -- those are the
    allowed scratch writes. If git cannot answer (not a repo, git missing), FAIL
    SAFE = True (treat as protected) so an unclassifiable blessed write is blocked
    rather than silently allowed.
    """
    root = blessed_root()
    if not is_under_blessed(abs_path, root=root):
        return False
    rel = os.path.normpath(str(abs_path).replace("\\", "/"))[len(root):].lstrip("/")
    if not rel:
        return False  # the repo root itself is not a file
    try:
        r = subprocess.run(
            ["git", "-C", root, "ls-files", "--error-unmatch", "--", rel],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Telemetry — harness_events.jsonl emitter
#
# Fire-and-forget event capture for hook verdicts, stop-gates, agent spawns,
# and closing-report complaints. Wire format (schema_v=1) is documented in
# docs/telemetry.md — any downstream consumer of harness_events.jsonl parses
# these lines directly, so do not change field names/shape without updating
# that doc.
#
# MUST NEVER block or slow a guardrail: the whole body is one audited swallow.
# ---------------------------------------------------------------------------

_HARNESS_VERSION = None  # module memo; None = not yet computed, "" = computed-but-unknown
_LAST_EVENT = {}          # most recent load_event() payload, for best-effort session_id/subject

EVENT_SCHEMA_V = 1
MAX_EVENT_LINE_BYTES = 4096


def _events_path():
    return os.path.join(project_dir(), ".claude", "hooks", "state", "harness_events.jsonl")


def _harness_version():
    """git short-sha of the last commit that touched .claude/, memoized per process."""
    global _HARNESS_VERSION
    if _HARNESS_VERSION is not None:
        return _HARNESS_VERSION
    try:
        r = subprocess.run(
            ["git", "-C", project_dir(), "log", "-1", "--format=%h", "--", ".claude/"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        _HARNESS_VERSION = r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        _HARNESS_VERSION = ""
    return _HARNESS_VERSION


def _event_session_id():
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    try:
        return str(_LAST_EVENT.get("session_id") or "")
    except Exception:
        return ""


def _event_subject():
    """Best-effort target file from the last-loaded hook event's tool_input."""
    try:
        ti = _LAST_EVENT.get("tool_input", {}) or {}
        return str(ti.get("file_path") or ti.get("path") or ti.get("target") or "")
    except Exception:
        return ""


def _fit_event_line(obj):
    """Serialize obj to a JSONL line, truncating `payload` first (the only
    unbounded field) to stay under MAX_EVENT_LINE_BYTES so a single os.write()
    stays atomic. Returns (line_bytes, truncated)."""
    line = (json.dumps(obj, default=str, separators=(",", ":")) + "\n").encode("utf-8")
    if len(line) < MAX_EVENT_LINE_BYTES:
        return line, False

    slim = dict(obj)
    slim["payload"] = {}
    slim["payload_truncated"] = True
    overhead = len((json.dumps(slim, default=str, separators=(",", ":")) + "\n").encode("utf-8"))
    room = max(0, MAX_EVENT_LINE_BYTES - overhead - 24)  # slack for the wrapper key/quoting
    payload_str = json.dumps(obj.get("payload", {}), default=str)[:room]
    slim["payload"] = {"_truncated": payload_str}
    line = (json.dumps(slim, default=str, separators=(",", ":")) + "\n").encode("utf-8")
    if len(line) >= MAX_EVENT_LINE_BYTES:
        line = line[: MAX_EVENT_LINE_BYTES - 2] + b"}\n"  # last-resort hard clip
    return line, True


def emit_event(event_type, source=None, verdict=None, subject="", payload=None):
    """Append one telemetry line to harness_events.jsonl. Fire-and-forget: never
    raises, never blocks the caller beyond one small local O_APPEND write.

    SKIP_HARNESS_TELEMETRY opts out of this entirely -- checked FIRST, before
    any path resolution or directory creation, so an opted-out user never gets
    so much as an empty state/ dir on disk. This is local-only telemetry (it
    is never transmitted anywhere) but a public tool must ship a real off
    switch for it regardless -- see block()/allow(), which call this for their
    own verdict logging and must behave identically whether this returns early
    here or falls through to the write below. Loose truthiness (`not in ("",
    "0", "false", "False")`) matches the dominant convention in this tree
    (agent_role()'s GUARDRAILS_INTEGRATOR_ROLE check, _dispatch.py's
    SKIP_HOOK_DISPATCH)."""
    if os.environ.get("SKIP_HARNESS_TELEMETRY", "") not in ("", "0", "false", "False"):
        return
    try:
        if source is None:
            source = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else ""
        obj = {
            "schema_v": EVENT_SCHEMA_V,
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "source": source,
            "verdict": verdict,
            "session_id": _event_session_id(),
            "agent_role": agent_role(),
            "subject": subject or _event_subject(),
            "harness_version": _harness_version(),
            "payload": payload or {},
            "payload_truncated": False,
        }
        line, _truncated = _fit_event_line(obj)
        path = _events_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        pass  # swallow-ok: telemetry must never block a guardrail
