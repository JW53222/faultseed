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
`engine_dirs`. That list is loaded from THIS REPO'S OWN
docs/audit/audit-scope.yaml (currently the placeholder `["src"]`) --
resolved relative to `_common.py`'s own on-disk location
(`_AUDIT_SCOPE_ROOT`), NOT `CLAUDE_PROJECT_DIR`. So no matter what
CLAUDE_PROJECT_DIR a test sets, "in scope" always means "first path segment
is 'src'" for this checkout. Every fixture below uses `src/...` for
in-scope cases and a different top segment (`other/...`) for out-of-scope
cases -- and `test_engine_scope_gate_both_directions` pins the pairing
explicitly, because a silently-wrong `engine_dirs` would disable this (and
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

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no_swallowed_errors.py")


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

    `hook_path` defaults to this repo's real HOOK (every existing caller's
    behavior, unchanged); a caller may pass a different on-disk copy of the
    hook instead -- see test_generated_paths_exemption_actually_reaches_the_hook,
    which needs to run a COPY of the hook from inside tmp_path so its
    _AUDIT_SCOPE_ROOT-relative audit-scope.yaml lookup resolves to a
    synthetic, tmp_path-local config instead of this repo's real one."""
    ev = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": rel_path, "content": content},
    })
    return subprocess.run(
        [sys.executable, hook_path or HOOK], input=ev, text=True, capture_output=True,
        cwd=str(tmp_path), env=_env(tmp_path, **env_extra),
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
        [sys.executable, HOOK], input=ev, text=True, capture_output=True,
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
