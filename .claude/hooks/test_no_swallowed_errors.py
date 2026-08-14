#!/usr/bin/env python3
"""Regression tests for no_swallowed_errors.py -- the AST-based swallowed-
exception guard. Filed because this hook shipped with ZERO test coverage: no
other test file in this pack imports or subprocess-invokes it (confirmed by
reading every other shipped test file before writing this one).

Black-box: feed a PreToolUse Edit/Write event (stdin JSON) to the real hook
and assert exit code (2 = block, 0 = allow), mirroring
test_no_test_tampering_marker_count.py's and test_agent_sizing_gate.py's
`[sys.executable, HOOK]` + stdin-JSON convention.

SCOPE GOTCHA (read before extending this file)
------------------------------------------------
no_swallowed_errors.py is ENGINE-SCOPED for Python: it calls
`is_engine_path(path)` and allow()s immediately for anything outside
`engine_dirs`. That list is loaded from docs/audit/audit-scope.yaml,
resolved relative to `_common.py`'s own on-disk location
(`_AUDIT_SCOPE_ROOT`), NOT `CLAUDE_PROJECT_DIR`.

This suite does NOT depend on THIS REPO'S OWN shipped
docs/audit/audit-scope.yaml. That file is user-facing config -- a fresh
clone's own copy ships `engine_dirs: [UNCONFIGURED_ENGINE_DIRS_SENTINEL]`
(see that file's own header comment and _common.py's
UNCONFIGURED_ENGINE_DIRS_SENTINEL) and BLOCKS everything until a real
value replaces it, so a test suite that read the shipped file directly
would either need constant re-syncing or would break the moment the
default is (correctly) left unconfigured. Instead every fixture below runs
a throwaway COPY of `_common.py` + `no_swallowed_errors.py` under
`tmp_path/.claude/hooks/`, alongside a synthetic
`tmp_path`'s docs/audit/audit-scope.yaml pinning `engine_dirs: ["src"]` --
see `_copied_hook()`. Because `_AUDIT_SCOPE_ROOT` resolves relative to the
hook's own on-disk `__file__`, running the copy from under tmp_path makes
it read the copy's synthetic config, not this repo's real one -- the same
technique `test_engine_dirs_sentinel.py` and
`test_generated_paths_exemption_actually_reaches_the_hook` (below) already
use. "in scope" therefore always means "first path segment is 'src'" for
every test in this file, regardless of what the real shipped
audit-scope.yaml says. Every fixture below uses `src/...` for in-scope
cases and a different top segment (`other/...`) for out-of-scope cases --
and `test_engine_scope_gate_both_directions` pins the pairing explicitly,
because a silently-wrong `engine_dirs` would disable this (and
no_type_checking_stub.py) across a user's ENTIRE codebase without any test
here noticing.

We still set CLAUDE_PROJECT_DIR to a throwaway tmp_path per invocation --
not because it affects the scope decision (it doesn't, see above), but
because `_common.emit_event` appends telemetry to
`.claude/hooks/state/harness_events.jsonl` under project_dir(), and we do
not want these test runs polluting the real repo's telemetry file.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REAL_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))


def _copied_hook(tmp_path):
    """Copy `_common.py` + `no_swallowed_errors.py` into
    `tmp_path/.claude/hooks/` alongside a synthetic
    `tmp_path`'s docs/audit/audit-scope.yaml pinning `engine_dirs: ["src"]` --
    decouples this suite from whatever THIS REPO'S OWN
    docs/audit/audit-scope.yaml happens to ship (see the module docstring's
    SCOPE GOTCHA). Idempotent per tmp_path: a test that calls this more than
    once (e.g. both an in-scope and out-of-scope case) reuses the same copy
    instead of re-writing it."""
    hooks_dir = tmp_path / ".claude" / "hooks"
    if not hooks_dir.exists():
        hooks_dir.mkdir(parents=True)
        for name in ("_common.py", "no_swallowed_errors.py"):
            (hooks_dir / name).write_text(
                (Path(REAL_HOOKS_DIR) / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
        scope_dir = tmp_path / "docs" / "audit"
        scope_dir.mkdir(parents=True)
        (scope_dir / "audit-scope.yaml").write_text('engine_dirs:\n  - "src"\n', encoding="utf-8")
    return hooks_dir / "no_swallowed_errors.py"


def _env(tmp_path, **extra):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    # Never inherit an ambient override from the outer test-runner's shell.
    env.pop("GUARDRAILS_SWALLOW_NEIGHBORS", None)
    env.pop("GUARDRAILS_STRICT", None)
    env.update(extra)
    return env


def _run_write(tmp_path, rel_path, content, hook_path=None, **env_extra):
    """Write event -- content is the whole post-edit file, no disk read needed.

    `hook_path` defaults to a per-tmp_path COPY of the hook (see
    `_copied_hook`) so the scope decision is pinned to a synthetic
    `engine_dirs: ["src"]`, independent of this repo's real shipped
    audit-scope.yaml; a caller may pass a different on-disk copy instead --
    see test_generated_paths_exemption_actually_reaches_the_hook, which
    builds its own copy with an additional `generated_paths` section."""
    ev = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": rel_path, "content": content},
    })
    return subprocess.run(
        [sys.executable, hook_path or str(_copied_hook(tmp_path))], input=ev, text=True,
        capture_output=True, cwd=str(tmp_path), env=_env(tmp_path, **env_extra),
    )


def _run_edit(tmp_path, rel_path, old_string, new_string, **env_extra):
    """Edit event -- the hook reads the on-disk file at `rel_path` (relative to
    cwd) and applies old_string -> new_string in memory before re-parsing, so
    the fixture file must already exist on disk (see `_write_file`)."""
    ev = json.dumps({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": rel_path,
            "old_string": old_string,
            "new_string": new_string,
        },
    })
    return subprocess.run(
        [sys.executable, str(_copied_hook(tmp_path))], input=ev, text=True, capture_output=True,
        cwd=str(tmp_path), env=_env(tmp_path, **env_extra),
    )


def _write_file(tmp_path, rel_path, content):
    full = tmp_path / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


# --------------------------------------------------------------------------- #
# Planted failure: bare `pass` / `...` swallow
# --------------------------------------------------------------------------- #

def test_bare_pass_swallow_blocked(tmp_path):
    content = (
        "def foo():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    r = _run_write(tmp_path, "src/foo.py", content)
    assert r.returncode == 2
    assert "silently swallows an error" in r.stderr


def test_bare_ellipsis_swallow_blocked(tmp_path):
    content = (
        "def foo():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        ...\n"
    )
    r = _run_write(tmp_path, "src/foo.py", content)
    assert r.returncode == 2
    assert "silently swallows an error" in r.stderr


# --------------------------------------------------------------------------- #
# Escape marker: `# swallow-ok: <reason>`, handler-aware (except line / body
# line / comment line between them all count).
# --------------------------------------------------------------------------- #

def test_swallow_ok_marker_on_except_line_allowed(tmp_path):
    content = (
        "def foo():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:  # swallow-ok: deliberate degrade-to-default\n"
        "        pass\n"
    )
    r = _run_write(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


def test_swallow_ok_marker_on_pass_line_allowed(tmp_path):
    content = (
        "def foo():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        pass  # swallow-ok: deliberate degrade-to-default\n"
    )
    r = _run_write(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


def test_swallow_ok_marker_on_comment_line_between_allowed(tmp_path):
    content = (
        "def foo():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        # swallow-ok: deliberate degrade-to-default\n"
        "        pass\n"
    )
    r = _run_write(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


def test_bare_swallow_ok_marker_not_cleared(tmp_path):
    # No reason after the marker -- the rule stated across this whole pack:
    # a bare `# swallow-ok` is itself a violation, not a valid escape.
    content = (
        "def foo():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:  # swallow-ok\n"
        "        pass\n"
    )
    r = _run_write(tmp_path, "src/foo.py", content)
    assert r.returncode == 2
    assert "silently swallows an error" in r.stderr


# --------------------------------------------------------------------------- #
# Near-miss: a handler that actually handles the error must NOT be flagged --
# the hook deliberately matches only the bare pass/... body shape.
# --------------------------------------------------------------------------- #

def test_handled_exception_not_flagged(tmp_path):
    content = (
        "def foo():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        logger.warning('oops, degrading')\n"
        "        raise\n"
    )
    r = _run_write(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------- #
# Engine-scope gate, both directions (see module docstring). The identical
# violating content is blocked in-scope and allowed out-of-scope -- proving
# the scope check is load-bearing, not merely present.
# --------------------------------------------------------------------------- #

def test_engine_scope_gate_both_directions(tmp_path):
    content = (
        "def foo():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    in_scope = _run_write(tmp_path, "src/foo.py", content)
    assert in_scope.returncode == 2, in_scope.stderr

    out_of_scope = _run_write(tmp_path, "other/foo.py", content)
    assert out_of_scope.returncode == 0, out_of_scope.stderr


# --------------------------------------------------------------------------- #
# Neighborhood scan: the hook reconstructs the FULL post-edit file and
# scans a window around the touched lines -- not just the diff -- so an agent
# cannot build a fix around a pre-existing swallow left just outside the edit.
# --------------------------------------------------------------------------- #

_SIBLING_FILE = (
    "def func0():\n"
    "    return 0\n"
    "\n"
    "def func1():\n"
    "    try:\n"
    "        risky()\n"
    "    except Exception:\n"
    "        pass\n"
    "\n"
    "def func2():\n"
    "    x = 1\n"
    "    return x\n"
    "\n"
    "def func3():\n"
    "    return 3\n"
)


def test_neighborhood_scan_blocks_sibling_swallow_not_touched(tmp_path):
    # Edit only touches func2 -- the added text itself contains no swallow at
    # all. func1's swallow sits one sibling-position away (well within the
    # default +/-2 window), so it must still block. This is the exact "build
    # around it" hole the neighborhood scan exists to close.
    _write_file(tmp_path, "src/neighbors_sibling.py", _SIBLING_FILE)
    r = _run_edit(
        tmp_path, "src/neighbors_sibling.py",
        "    x = 1\n    return x",
        "    x = 2\n    return x",
    )
    assert r.returncode == 2
    assert "silently swallows an error" in r.stderr
    assert "NEIGHBORHOOD" in r.stderr


_WIDE_FILE = (
    "def func0():\n"
    "    return 0\n"
    "\n"
    "def func1():\n"
    "    return 1\n"
    "\n"
    "def func2():\n"
    "    return 2\n"
    "\n"
    "def func3():\n"
    "    x = 1\n"
    "    return x\n"
    "\n"
    "def func4():\n"
    "    return 4\n"
    "\n"
    "def func5():\n"
    "    return 5\n"
    "\n"
    "def func6():\n"
    "    try:\n"
    "        risky()\n"
    "    except Exception:\n"
    "        pass\n"
)


# --------------------------------------------------------------------------- #
# Generated/vendored exemption (`is_generated_path`, _common.py). Loaded
# from docs/audit/audit-scope.yaml's `generated_paths` -- see that file's
# comment and _common._load_generated_paths()'s docstring for the missing-
# vs-malformed policy. These tests pin `is_engine_path`/`is_generated_path`
# in both directions the same way test_engine_scope_gate_both_directions
# above pins engine_dirs: point CLAUDE_PROJECT_DIR at a synthetic tmp_path
# repo carrying its OWN audit-scope.yaml (via AUDIT_HARNESS_HOOKS_DIR-style
# monkeypatching would require importing _common directly; instead we patch
# _common._AUDIT_SCOPE_ROOT in-process the same way _common.py documents
# _AUDIT_SCOPE_ROOT is resolved relative to the HOOK's own on-disk location,
# not CLAUDE_PROJECT_DIR -- so a subprocess-based black-box test cannot
# point audit-scope.yaml at a tmp_path fixture at all; this is why the
# tests below import no_swallowed_errors.py's dependency (_common) directly
# in-process rather than using the subprocess `_run_write`/`_run_edit`
# helpers the rest of this file uses).
# --------------------------------------------------------------------------- #

def _write_scoped_repo(tmp_path, generated_paths_yaml=""):
    """A synthetic repo: docs/audit/audit-scope.yaml with engine_dirs=['src']
    plus whatever `generated_paths_yaml` snippet is given (empty string ->
    section omitted entirely)."""
    scope_dir = tmp_path / "docs" / "audit"
    scope_dir.mkdir(parents=True, exist_ok=True)
    (scope_dir / "audit-scope.yaml").write_text(
        'engine_dirs:\n  - "src"\n' + generated_paths_yaml, encoding="utf-8"
    )
    (tmp_path / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)


def _fresh_common_module(scope_root):
    """Import _common.py fresh (bypassing sys.modules caching, since other
    tests in this process may already have imported and cached it with a
    different _AUDIT_SCOPE_ROOT / _GENERATED_PATHS_CACHE) with
    `_AUDIT_SCOPE_ROOT` patched to `scope_root` -- mirrors how
    `_AUDIT_SCOPE_ROOT` is documented as resolved relative to this file's
    own on-disk location, not CLAUDE_PROJECT_DIR, so the only way to point
    it at a tmp_path fixture is to patch the module attribute directly."""
    import importlib.util
    hook_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_common.py")
    spec = importlib.util.spec_from_file_location("_common_scoped_test", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._AUDIT_SCOPE_ROOT = scope_root
    return mod


def test_generated_paths_missing_section_exempts_nothing(tmp_path):
    """Section omitted entirely -- must default to "exempt nothing" (empty
    tuple), not raise and not silently exempt everything. This is the safe-
    default policy _load_generated_paths()'s docstring commits to: an
    unconfigured install checks MORE of the tree, never less."""
    _write_scoped_repo(tmp_path, generated_paths_yaml="")
    mod = _fresh_common_module(tmp_path)

    assert mod._load_generated_paths() == ()
    assert mod.is_generated_path("src/gen/foo.py") is False
    assert mod.is_generated_path("src/anything/at/all.py") is False


def test_generated_paths_configured_prefix_is_exempted(tmp_path):
    """A path under a configured generated_paths prefix -> exempted (True).
    The identical file OUTSIDE that prefix -> NOT exempted (False) -- both
    directions pinned in one test, same pairing discipline as
    test_engine_scope_gate_both_directions above, so a mutant that exempts
    everything (or nothing) regardless of configuration cannot pass by
    accident."""
    _write_scoped_repo(tmp_path, generated_paths_yaml='generated_paths:\n  - "src/gen/"\n')
    mod = _fresh_common_module(tmp_path)

    assert mod.is_generated_path("src/gen/foo.py") is True
    assert mod.is_generated_path("src/gen/nested/bar.py") is True
    assert mod.is_generated_path("src/not_gen/foo.py") is False


def test_generated_paths_exemption_actually_reaches_the_hook(tmp_path):
    """End-to-end, not just the _common.py primitive: the SAME violating
    content that test_engine_scope_gate_both_directions blocks in-scope must
    now be ALLOWED when it sits under a configured generated_paths prefix,
    and still BLOCKED for the identical content one directory over -- proves
    the exemption is wired into no_swallowed_errors.py's actual gate order,
    not just correct in isolation.

    `_AUDIT_SCOPE_ROOT` resolves relative to the HOOK's own on-disk
    location (three parents up from _common.py -- see that file's
    comment), not CLAUDE_PROJECT_DIR, so pointing this at a synthetic
    audit-scope.yaml means running a COPY of the hook (_common.py +
    no_swallowed_errors.py, no other dependency -- confirmed by reading
    no_swallowed_errors.py's imports) from inside tmp_path, with a
    tmp_path-local docs/audit/audit-scope.yaml sitting where that copy's
    own _AUDIT_SCOPE_ROOT will resolve it to. Nothing outside tmp_path is
    ever written -- unlike mutating this repo's real audit-scope.yaml in
    place, which a real concurrent test run (this suite runs hooks in
    parallel processes) could race against.
    """
    hooks_dir = tmp_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    real_hooks_dir = os.path.dirname(os.path.abspath(__file__))
    for name in ("_common.py", "no_swallowed_errors.py"):
        (hooks_dir / name).write_text(
            (Path(real_hooks_dir) / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    scope_dir = tmp_path / "docs" / "audit"
    scope_dir.mkdir(parents=True)
    (scope_dir / "audit-scope.yaml").write_text(
        'engine_dirs:\n  - "src"\ngenerated_paths:\n  - "src/gen/"\n', encoding="utf-8"
    )
    copied_hook = hooks_dir / "no_swallowed_errors.py"

    content = (
        "def foo():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    exempted = _run_write(tmp_path, "src/gen/foo.py", content, hook_path=str(copied_hook))
    assert exempted.returncode == 0, exempted.stderr

    still_blocked = _run_write(tmp_path, "src/not_gen/foo.py", content, hook_path=str(copied_hook))
    assert still_blocked.returncode == 2, still_blocked.stderr
    assert "silently swallows an error" in still_blocked.stderr


def test_neighbors_env_var_widens_window(tmp_path):
    # func6's swallow sits 3 sibling-positions away from the edited func3.
    # Default window radius is 2 (func6 excluded -> allow). Setting
    # GUARDRAILS_SWALLOW_NEIGHBORS=3 widens the window to include func6 ->
    # block. Same edit, only the env var differs -- pins that the knob is
    # actually wired, not just documented.
    _write_file(tmp_path, "src/neighbors_env.py", _WIDE_FILE)

    default = _run_edit(
        tmp_path, "src/neighbors_env.py",
        "    x = 1\n    return x",
        "    x = 2\n    return x",
    )
    assert default.returncode == 0, default.stderr

    widened = _run_edit(
        tmp_path, "src/neighbors_env.py",
        "    x = 1\n    return x",
        "    x = 2\n    return x",
        GUARDRAILS_SWALLOW_NEIGHBORS="3",
    )
    assert widened.returncode == 2
    assert "silently swallows an error" in widened.stderr


# --------------------------------------------------------------------------- #
# Go swallow shapes (module docstring's "GO SWALLOW SHAPES DETECTED"). Filed
# because a mutation pass proved these ~130 lines of detector logic
# (GO_DISCARD_ERR, GO_EMPTY_ERR_CHECK, GO_SWALLOWED_RETURN_NIL,
# GO_IGNORED_SECOND_RETURN and their soft/hard split) had ZERO coverage:
# disabling the whole Go branch left every other test in this file green.
#
# SCOPE NOTE: unlike Python/PowerShell, Go source is NOT gated by
# `engine_dirs` at all -- confirmed by reading main()'s branch structure:
# the `is_go` branch only checks `_is_go_generated()`, never
# `is_engine_path()` (that call lives exclusively in the `else` branch that
# handles Python/PowerShell). Per the module docstring's own "For Go there
# is no backend/frontend split" paragraph, "in scope" for Go reduces to "any
# .go file that isn't generated." Every Go fixture below therefore
# deliberately uses a path OUTSIDE `src/` (the synthetic engine_dirs this
# suite's `_copied_hook` pins) to prove that independence isn't accidental --
# if a future change wired Go through `is_engine_path()` too, these fixtures
# would start silently allowing (exit 0) instead of blocking, and fail loud.
# --------------------------------------------------------------------------- #

def test_go_bare_err_discard_blocked(tmp_path):
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\t_ = err\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 2, r.stderr
    assert "discards an error value" in r.stderr


def test_go_empty_err_check_blocked(tmp_path):
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil {\n"
        "\t}\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 2, r.stderr
    assert "empty `if err != nil { }` body" in r.stderr


def test_go_swallowed_return_nil_blocked(tmp_path):
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil { return nil }\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 2, r.stderr
    assert "a checked error is discarded by returning nil" in r.stderr


def test_go_swallow_ok_marker_clears_hard_hit(tmp_path):
    # `// swallow-ok: <reason>` on the offending line clears a Go hard hit,
    # same rationale-required contract as Python's `# swallow-ok:`. Uses the
    # single-line `if err != nil { }` form (see finding below for why the
    # bare-discard shape can't be used to pin this): GO_EMPTY_ERR_CHECK's
    # match itself ends at `}`, so `ln_idx` (computed from the match START)
    # lands on the SAME line the trailing comment sits on, and
    # `_line_has_swallow_ok` genuinely inspects that whole line -- verified
    # directly against the hook that an unrelated garbage comment in this
    # exact position does NOT clear the hit (only a real `swallow-ok:
    # <reason>` marker does), so this is pinning the real mechanism, not a
    # match failure that happens to look like one.
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil { }  // swallow-ok: deliberate no-op cleanup path\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 0, r.stderr


def test_go_bare_swallow_ok_marker_not_cleared(tmp_path):
    # Same rule as the Python bare-marker test above: no reason after the
    # colon does NOT count as an escape. Same single-line shape as the test
    # above so this is a true positive/negative pair over the SAME pattern.
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil { }  // swallow-ok\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 2, r.stderr
    assert "empty `if err != nil { }` body" in r.stderr


def test_go_bare_discard_err_any_trailing_comment_bypasses_detection_FINDING(tmp_path):
    """FINDING, not a coverage gap: GO_DISCARD_ERR is
    `^\\s*_\\s*=\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*$` -- anchored to END OF LINE.
    The module docstring claims "Go's `//` line-comment syntax is honored
    the same way: `// swallow-ok: <reason>` on the offending line clears a
    Go hit, rationale still required" -- implying only a VALID, rationale'd
    marker should clear a `_ = err` hit.

    Verified directly against the real hook (not this test's assumption):
    appending ANY trailing text to `_ = err` -- not just a valid
    `swallow-ok` marker, literally any comment at all, e.g.
    `_ = err  // just a comment` -- makes GO_DISCARD_ERR fail to match at
    all, silently bypassing detection with no warning and no rationale
    check performed. This is a stronger break than "bare marker without
    reason clears it" (already bad); an outright non-marker comment clears
    it too, exactly the same as a well-formed one, because the underlying
    regex never distinguishes them -- it simply stops matching once
    anything follows the identifier on the line.

    This test asserts the DOCUMENTED behavior (an unmarked, non-`swallow-ok`
    comment must not silence a real error discard) and is EXPECTED TO FAIL
    against the current guard. Per this task's instructions: do not weaken
    this assertion to match the buggy behavior -- report it.
    """
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\t_ = err  // just a comment, not a swallow-ok marker at all\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 2, (
        "FINDING: GO_DISCARD_ERR's end-of-line anchor lets ANY trailing "
        "comment (not just a valid swallow-ok marker) silently bypass "
        "detection of a bare `_ = err` discard. Actual result: "
        f"returncode={r.returncode!r}, stderr={r.stderr!r}"
    )


def test_go_ignored_second_return_is_soft_warn_not_block(tmp_path):
    # The documented soft/hard split: an ignored second return (`x, _ :=
    # call()`) cannot be distinguished from Go's legitimate `(T, bool)`
    # "found" idiom without the callee's real signature, so it is WARN-ONLY
    # -- exit 0, but a warning still reaches stderr. This is the exact
    # pairing the task calls out as nothing currently pins: a hard shape
    # must exit 2 (tests above) and this soft shape must exit 0 while still
    # warning.
    content = (
        "package pkg\n"
        "func f() {\n"
        "\tx, _ := call()\n"
        "\t_ = x\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 0, r.stderr
    assert "WARNING (allowed):" in r.stderr
    assert "discards a second return value" in r.stderr


def test_go_defer_close_not_flagged(tmp_path):
    # Legitimate shape from the module docstring: a bare call statement, no
    # return value ever bound to anything -- no pattern here can match it.
    content = (
        "package pkg\n"
        "func f() {\n"
        "\tdefer fh.Close()\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 0, r.stderr
    assert "WARNING" not in r.stderr


def test_go_discard_call_result_not_bare_identifier_not_flagged(tmp_path):
    # `_ = f.Close()` discards a CALL's result, not a bare identifier -- the
    # `_ = <name>` discard pattern requires a bare identifier with nothing
    # else on the line, so this must NOT be flagged (module docstring's
    # "LEGITIMATE GO SHAPES THAT MUST STAY ALLOWED").
    content = (
        "package pkg\n"
        "func f() {\n"
        "\t_ = fh.Close()\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 0, r.stderr
    assert "WARNING" not in r.stderr


def test_go_discard_non_error_identifier_not_flagged(tmp_path):
    # GO_DISCARD_ERR is scoped to identifiers whose name contains "err"
    # (case-insensitive) -- discarding an unrelated bare local must not fire.
    content = (
        "package pkg\n"
        "func f() {\n"
        "\tcount := computeCount()\n"
        "\t_ = count\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 0, r.stderr


def test_go_generated_bindata_suffix_exempt(tmp_path):
    # `_bindata.go` suffix -- build output, never hand-authored source.
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\t_ = err\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo_bindata.go", content)
    assert r.returncode == 0, r.stderr


def test_go_generated_marker_comment_exempt(tmp_path):
    # The Go-ecosystem-standard "Code generated ... DO NOT EDIT." marker.
    content = (
        "// Code generated by protoc-gen-go. DO NOT EDIT.\n"
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\t_ = err\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.pb.go", content)
    assert r.returncode == 0, r.stderr


def test_go_test_file_exempt(tmp_path):
    # is_test_file() recognises `_test.go` -- policed the same as Python
    # test files (exempt regardless of engine scope).
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\t_ = err\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo_test.go", content)
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------- #
# Regression pins for the cross-brace comment fix: GO_EMPTY_ERR_CHECK and
# GO_SWALLOWED_RETURN_NIL were BOTH anchored so a comment sitting between the
# braces stopped the pattern matching at all -- which meant the swallow-ok
# marker check (_match_has_swallow_ok) was never reached, so ANY comment
# (marker or not, reasoned or not) silently cleared the hit. Confirmed by
# probe: rc=0 (allowed) before the fix, rc=2 (blocked) after, for content
# identical to `test_go_empty_err_check_blocked` / `test_go_swallowed_
# return_nil_blocked` above but with a plain non-marker comment inserted
# between the braces.
#
# Each pattern gets the same four-shape grid used for GO_DISCARD_ERR/
# PS_EMPTY_CATCH's earlier FINDING pins, now that the bug they found is
# fixed:
#   1. non-marker comment between the braces -> still BLOCKED (the actual
#      regression -- this is the shape that used to slip through silently)
#   2. valid `swallow-ok: <reason>` marker on its OWN LINE between the
#      braces -> ALLOWED (the marker-window generalization that shipped
#      alongside the fix: from "the line the match starts on" to "any line
#      the match spans")
#   3. bare `swallow-ok` (no reason) in that same between-the-braces
#      position -> still BLOCKED (this exact position was UNREACHABLE
#      before the fix, since detection never fired there at all -- most
#      worth pinning)
#   4. no comment at all -> still BLOCKED (already covered by the existing
#      `_blocked` tests above; not repeated here)
#
# Case 1 also does double duty as the guard against the trap named in the
# task: a "marker clears it" test can pass for the wrong reason (detection
# never fired), not because marker recognition worked. Comparing case 1
# (blocked) against case 2 (allowed) over the IDENTICAL brace position
# proves the marker path -- not a match failure -- is what flips the result.
# --------------------------------------------------------------------------- #

def test_go_empty_err_check_non_marker_comment_still_blocked(tmp_path):
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil {\n"
        "\t\t// just a comment, not a swallow-ok marker at all\n"
        "\t}\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 2, r.stderr
    assert "empty `if err != nil { }` body" in r.stderr


def test_go_empty_err_check_marker_on_own_line_between_braces_allowed(tmp_path):
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil {\n"
        "\t\t// swallow-ok: deliberate no-op cleanup path\n"
        "\t}\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 0, r.stderr


def test_go_empty_err_check_bare_marker_on_own_line_between_braces_not_cleared(tmp_path):
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil {\n"
        "\t\t// swallow-ok\n"
        "\t}\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 2, r.stderr
    assert "empty `if err != nil { }` body" in r.stderr


def test_go_swallowed_return_nil_non_marker_comment_still_blocked(tmp_path):
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil {\n"
        "\t\t// just a comment, not a swallow-ok marker at all\n"
        "\t\treturn nil\n"
        "\t}\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 2, r.stderr
    assert "a checked error is discarded by returning nil" in r.stderr


def test_go_swallowed_return_nil_marker_on_own_line_between_braces_allowed(tmp_path):
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil {\n"
        "\t\t// swallow-ok: deliberate degrade-to-default\n"
        "\t\treturn nil\n"
        "\t}\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 0, r.stderr


def test_go_swallowed_return_nil_bare_marker_on_own_line_between_braces_not_cleared(tmp_path):
    content = (
        "package pkg\n"
        "func f() error {\n"
        "\terr := doThing()\n"
        "\tif err != nil {\n"
        "\t\t// swallow-ok\n"
        "\t\treturn nil\n"
        "\t}\n"
        "\treturn nil\n"
        "}\n"
    )
    r = _run_write(tmp_path, "pkg/foo.go", content)
    assert r.returncode == 2, r.stderr
    assert "a checked error is discarded by returning nil" in r.stderr


# --------------------------------------------------------------------------- #
# PowerShell swallow shapes (module docstring's "PowerShell swallows" note).
# UNLIKE Go, PowerShell IS gated by `engine_dirs` (the `else` branch of
# main() -- is_ps is not is_go, so it goes through `is_engine_path()` the
# same as Python). Every in-scope fixture below therefore uses `src/...`
# (this suite's synthetic engine_dirs) and the scope-both-directions test
# pins that an identical violation is allowed outside it, mirroring
# `test_engine_scope_gate_both_directions` above but for the PS branch
# specifically (that existing test only exercises the Python AST tier).
# --------------------------------------------------------------------------- #

def test_ps_empty_catch_blocked(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "empty/no-op `catch { }`" in r.stderr


def test_ps_error_action_silently_continue_blocked(tmp_path):
    content = "Do-Thing -ErrorAction SilentlyContinue\n"
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "-ErrorAction SilentlyContinue/Ignore" in r.stderr


def test_ps_error_action_ignore_blocked(tmp_path):
    content = "Do-Thing -ErrorAction Ignore\n"
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "-ErrorAction SilentlyContinue/Ignore" in r.stderr


def test_ps_global_error_action_preference_blocked(tmp_path):
    content = "$ErrorActionPreference = 'SilentlyContinue'\n"
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "global `$ErrorActionPreference" in r.stderr


def test_ps_swallow_ok_marker_clears_hard_hit(tmp_path):
    # Single-line `catch { }` form: PS_EMPTY_CATCH's match ends at the
    # closing brace, so `_line_has_swallow_ok` genuinely inspects the same
    # line the trailing comment sits on. (The two-line `catch {\n}` form
    # with a comment placed BETWEEN the braces is a separate, broken case --
    # see the FINDING test below; it is NOT used here because it would pass
    # for the wrong reason: the pattern fails to match at all once anything
    # non-whitespace sits between the braces, regardless of whether it is a
    # real marker.)
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch { }  # swallow-ok: cleanup path, safe to ignore\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 0, r.stderr


def test_ps_bare_swallow_ok_marker_not_cleared(tmp_path):
    # Same single-line shape as the test above, so this is a true
    # positive/negative pair over the SAME pattern.
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch { }  # swallow-ok\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "empty/no-op `catch { }`" in r.stderr


def test_ps_empty_catch_multiline_any_comment_between_braces_bypasses_detection_FINDING(tmp_path):
    """FINDING, not a coverage gap: PS_EMPTY_CATCH is
    `catch\\s*(\\[[^\\]]*\\]\\s*)?\\{\\s*\\}` -- it requires ONLY whitespace
    between the braces. PS_NULL_CATCH has the same shape. Neither the module
    docstring nor the PATTERNS.md registry document a same-line-only
    restriction for the PowerShell escape marker; the handler-aware marker
    convention documented for Python (`# swallow-ok:` on the `except` line,
    the body line, OR a comment line between them) suggests a comment placed
    between an empty catch's two braces should be a natural, honored
    position too.

    Verified directly against the real hook (not this test's assumption):
    when `catch {` and the closing `}` are on SEPARATE lines (the natural
    multi-statement style used throughout this file's OWN existing fixtures,
    e.g. `test_ps_empty_catch_blocked` above), inserting ANY comment between
    them -- not just a valid swallow-ok marker, a plain unrelated comment --
    makes the regex fail to match at all, silently bypassing detection with
    no warning. This is the same root-cause class as the Go
    GO_DISCARD_ERR finding above: a delimiter-adjacency pattern that
    requires pure whitespace breaks the instant ANY text (marked or not) is
    inserted where a human would naturally put an audit comment.

    This test asserts the DOCUMENTED intent (an unmarked, non-`swallow-ok`
    comment between the braces must not silence a real empty-catch swallow)
    and is EXPECTED TO FAIL against the current guard. Per this task's
    instructions: do not weaken this assertion to match the buggy behavior
    -- report it.
    """
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {  # just a comment, not a swallow-ok marker at all\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, (
        "FINDING: PS_EMPTY_CATCH/PS_NULL_CATCH's `\\{\\s*\\}` pattern lets "
        "ANY comment placed between a multi-line catch's braces (not just a "
        "valid swallow-ok marker) silently bypass detection of an empty "
        f"catch. Actual result: returncode={r.returncode!r}, "
        f"stderr={r.stderr!r}"
    )


def test_ps_engine_scope_gate_both_directions(tmp_path):
    # PowerShell goes through `is_engine_path()` exactly like Python (unlike
    # Go, which is scope-independent -- see the Go section above). The
    # identical violating content is blocked under the synthetic
    # engine_dirs=["src"] and allowed one directory over.
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "}\n"
    )
    in_scope = _run_write(tmp_path, "src/foo.ps1", content)
    assert in_scope.returncode == 2, in_scope.stderr

    out_of_scope = _run_write(tmp_path, "other/foo.ps1", content)
    assert out_of_scope.returncode == 0, out_of_scope.stderr


def test_ps_test_file_exempt(tmp_path):
    # is_test_file() recognises Pester's `.tests.ps1` suffix.
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.tests.ps1", content)
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------- #
# Regression pins for PS_NULL_CATCH -- the third pattern hit by the same
# cross-brace-comment anchoring bug as GO_EMPTY_ERR_CHECK/GO_SWALLOWED_
# RETURN_NIL above (and, before the fix, PS_EMPTY_CATCH -- see that
# pattern's own FINDING test further up, now presumably fixed the same way).
# `catch { $null|continue|return }` written across multiple lines, with a
# comment sitting between the `catch {` and the closing `}`, used to fail to
# match at all once ANY comment (marker or not) was present -- silently
# bypassing detection with no warning, exactly the shape the task calls out
# as the one most likely to survive if under-tested: "a test for one of
# three [variants] is the shape that let this bug survive in the first
# place." All three variants (`$null`, `continue`, `return`) get the full
# four-shape grid: non-marker comment still blocks (the regression itself),
# a correctly-reasoned marker on its own line between the braces clears it
# (the marker-window generalization that shipped with the fix), a bare
# marker in that same position does NOT clear it (unreachable before the
# fix, most worth pinning), and the plain no-comment baseline still blocks
# (proves the block isn't coming from some other path).
#
# Content is deliberately NOT built with PS_EMPTY_CATCH's shape too: the
# body always contains `$null`/`continue`/`return`, real (non-whitespace,
# non-comment) content between the braces, so PS_EMPTY_CATCH's own
# "` \{\s*\}`-only" pattern does not also match -- confirmed by probe: the
# stderr for every BLOCKED case below carries ONLY the PS_NULL_CATCH
# wording ("whose body only nulls/continues/returns"), never the
# PS_EMPTY_CATCH wording ("empty/no-op `catch { }`"), so these tests are
# pinned to the pattern the task named, not its sibling.
# --------------------------------------------------------------------------- #

def test_ps_null_catch_dollar_null_baseline_blocked(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    $null\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "whose body only nulls/continues/returns" in r.stderr
    assert "empty/no-op `catch { }`" not in r.stderr


def test_ps_null_catch_dollar_null_non_marker_comment_still_blocked(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    # just a comment, not a swallow-ok marker at all\n"
        "    $null\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "whose body only nulls/continues/returns" in r.stderr
    assert "empty/no-op `catch { }`" not in r.stderr


def test_ps_null_catch_dollar_null_marker_on_own_line_allowed(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    # swallow-ok: deliberate no-op, error is expected here\n"
        "    $null\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 0, r.stderr


def test_ps_null_catch_dollar_null_bare_marker_on_own_line_not_cleared(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    # swallow-ok\n"
        "    $null\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "whose body only nulls/continues/returns" in r.stderr


def test_ps_null_catch_continue_baseline_blocked(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    continue\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "whose body only nulls/continues/returns" in r.stderr


def test_ps_null_catch_continue_non_marker_comment_still_blocked(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    # just a comment, not a swallow-ok marker at all\n"
        "    continue\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "whose body only nulls/continues/returns" in r.stderr


def test_ps_null_catch_continue_marker_on_own_line_allowed(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    # swallow-ok: deliberate skip, handled by the outer loop\n"
        "    continue\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 0, r.stderr


def test_ps_null_catch_continue_bare_marker_on_own_line_not_cleared(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    # swallow-ok\n"
        "    continue\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "whose body only nulls/continues/returns" in r.stderr


def test_ps_null_catch_return_baseline_blocked(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    return\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "whose body only nulls/continues/returns" in r.stderr


def test_ps_null_catch_return_non_marker_comment_still_blocked(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    # just a comment, not a swallow-ok marker at all\n"
        "    return\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "whose body only nulls/continues/returns" in r.stderr


def test_ps_null_catch_return_marker_on_own_line_allowed(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    # swallow-ok: deliberate early-return, caller retries\n"
        "    return\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 0, r.stderr


def test_ps_null_catch_return_bare_marker_on_own_line_not_cleared(tmp_path):
    content = (
        "try {\n"
        "    Do-Thing\n"
        "} catch {\n"
        "    # swallow-ok\n"
        "    return\n"
        "}\n"
    )
    r = _run_write(tmp_path, "src/foo.ps1", content)
    assert r.returncode == 2, r.stderr
    assert "whose body only nulls/continues/returns" in r.stderr
