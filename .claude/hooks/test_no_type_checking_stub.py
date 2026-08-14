#!/usr/bin/env python3
"""Regression tests for no_type_checking_stub.py -- the AST-based guard
against declaring a method ONLY inside `if TYPE_CHECKING:` with no runtime
`def` (the motivating bug's shape: two methods declared this way, living in
a MIXIN, hence this hook's deliberate no-blanket-mixin-exemption design).
Filed because this hook shipped with ZERO test coverage: no other test file
in this pack imports or subprocess-invokes it (confirmed by reading every
other shipped test file before writing this one).

Black-box: feed a PreToolUse Write event (stdin JSON) to the real hook and
assert exit code (2 = block, 0 = allow), mirroring
test_no_test_tampering_marker_count.py's / test_agent_sizing_gate.py's
`[sys.executable, HOOK]` + stdin-JSON convention. All fixtures here use Write
(whole-file `content`), so no on-disk fixture file is needed -- the hook's
`_reconstruct_post_edit` uses `tool_input.content` directly for Write.

SCOPE GOTCHA (see test_no_swallowed_errors.py's module docstring for the
full derivation -- same mechanism, repeated briefly here)
------------------------------------------------------------------------
This hook is ENGINE-SCOPED: `is_engine_path(path)` gates on `engine_dirs`
from THIS REPO'S OWN docs/audit/audit-scope.yaml (currently `["src"]`),
resolved relative to `_common.py`'s own on-disk location -- NOT
CLAUDE_PROJECT_DIR. So "in scope" always means "first path segment is
'src'" for this checkout, regardless of what CLAUDE_PROJECT_DIR a test
sets. Every in-scope fixture below uses `src/...`; every out-of-scope one
uses a different top segment (`other/...`); `test_engine_scope_gate_both_directions`
pins the pairing explicitly -- a silently-wrong `engine_dirs` would disable
this (and no_swallowed_errors.py) across a user's ENTIRE codebase without
any test here noticing.

CLAUDE_PROJECT_DIR is still set to a throwaway tmp_path per invocation so
`_common.emit_event`'s telemetry append doesn't pollute the real repo's
`.claude/hooks/state/harness_events.jsonl`.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no_type_checking_stub.py")


def _run(tmp_path, rel_path, content):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    ev = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": rel_path, "content": content},
    })
    return subprocess.run(
        [sys.executable, HOOK], input=ev, text=True, capture_output=True,
        cwd=str(tmp_path), env=env,
    )


# --------------------------------------------------------------------------- #
# Planted failure: a method def'd only inside `if TYPE_CHECKING:`, no runtime
# def, on a plain class.
# --------------------------------------------------------------------------- #

def test_type_checking_only_stub_blocked(tmp_path):
    content = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        def bar(self) -> int: ...\n"
    )
    r = _run(tmp_path, "src/foo.py", content)
    assert r.returncode == 2
    assert "TYPE_CHECKING-only stub, no runtime def" in r.stderr
    assert "`bar` (class Foo)" in r.stderr


# --------------------------------------------------------------------------- #
# The mixin case: the hook deliberately has NO blanket mixin exemption. This
# is the exact shape of the motivating bug -- pin that a *Mixin class name
# does not get a free pass.
# --------------------------------------------------------------------------- #

def test_mixin_class_gets_no_blanket_exemption_blocked(tmp_path):
    content = (
        "from typing import TYPE_CHECKING\n"
        "class ExecutionMixin:\n"
        "    if TYPE_CHECKING:\n"
        "        def _map_tif(self, *a, **k):\n"
        "            ...\n"
    )
    r = _run(tmp_path, "src/execution_mixin.py", content)
    assert r.returncode == 2
    assert "`_map_tif` (class ExecutionMixin)" in r.stderr


# --------------------------------------------------------------------------- #
# Escape markers: `# host-provides: <reason>` / `# type-stub-ok: <reason>`
# clear it. A bare marker with no reason does not.
# --------------------------------------------------------------------------- #

def test_host_provides_marker_with_reason_allowed(tmp_path):
    content = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        # host-provides: LiveStrategyEvaluator defines this at runtime\n"
        "        def bar(self) -> int: ...\n"
    )
    r = _run(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


def test_type_stub_ok_marker_with_reason_allowed(tmp_path):
    content = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        # type-stub-ok: host supplies this at composition time\n"
        "        def bar(self) -> int: ...\n"
    )
    r = _run(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


def test_bare_marker_without_reason_not_cleared(tmp_path):
    content = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        # host-provides\n"
        "        def bar(self) -> int: ...\n"
    )
    r = _run(tmp_path, "src/foo.py", content)
    assert r.returncode == 2
    assert "TYPE_CHECKING-only stub, no runtime def" in r.stderr


# --------------------------------------------------------------------------- #
# Near-misses that must be ALLOWED -- the module docstring's "deliberate
# non-triggers" list.
# --------------------------------------------------------------------------- #

def test_stub_with_matching_runtime_def_allowed(tmp_path):
    content = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        def bar(self) -> int: ...\n"
        "    def bar(self) -> int:\n"
        "        return 1\n"
    )
    r = _run(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


def test_overload_real_defs_allowed(tmp_path):
    content = (
        "from typing import overload\n"
        "class Foo:\n"
        "    @overload\n"
        "    def bar(self, x: int) -> int: ...\n"
        "    @overload\n"
        "    def bar(self, x: str) -> str: ...\n"
        "    def bar(self, x):\n"
        "        return x\n"
    )
    r = _run(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


def test_plain_attribute_annotation_under_type_checking_allowed(tmp_path):
    content = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        x: int\n"
    )
    r = _run(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


def test_import_under_type_checking_allowed(tmp_path):
    content = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from bar_module import Bar\n"
        "class Foo:\n"
        "    pass\n"
    )
    r = _run(tmp_path, "src/foo.py", content)
    assert r.returncode == 0, r.stderr


def test_non_python_file_allowed(tmp_path):
    # Same violating shape, but the hook only polices `.py` files.
    content = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        def bar(self) -> int: ...\n"
    )
    r = _run(tmp_path, "src/foo.js", content)
    assert r.returncode == 0, r.stderr


def test_test_file_exempt_even_inside_engine_dir(tmp_path):
    # is_test_file() exemption applies independent of, and is checked before,
    # the engine-path gate -- use an in-scope path that is ALSO a test file
    # to prove the exemption isn't just a byproduct of being out of scope.
    content = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        def bar(self) -> int: ...\n"
    )
    r = _run(tmp_path, "src/test_foo.py", content)
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------- #
# Engine-scope gate, both directions (see module docstring). Identical
# violating content is blocked in-scope and allowed out-of-scope.
# --------------------------------------------------------------------------- #

def test_engine_scope_gate_both_directions(tmp_path):
    content = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        def bar(self) -> int: ...\n"
    )
    in_scope = _run(tmp_path, "src/foo.py", content)
    assert in_scope.returncode == 2, in_scope.stderr

    out_of_scope = _run(tmp_path, "other/foo.py", content)
    assert out_of_scope.returncode == 0, out_of_scope.stderr
