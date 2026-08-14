#!/usr/bin/env python3
"""Regression tests for _common.py's UNCONFIGURED_ENGINE_DIRS_SENTINEL
mechanism (independent oppositional review, finding M5).

THE BUG: an ABSENT docs/audit/audit-scope.yaml already fails LOUD (block(),
exit 2, names the file) -- see test_no_swallowed_errors.py's coverage of
that path. But the file SHIPS with `engine_dirs: ["src"]`, and a repo whose
source doesn't live under `src/` gets SILENT zero coverage from
no_swallowed_errors.py and no_type_checking_stub.py instead of that same
loud block -- is_engine_path() just returns False for everything, no
error, no warning. The shipped default was worse than no file at all.

THE FIX: `_load_engine_dirs()` now recognizes one specific, unmistakable
token -- `UNCONFIGURED_ENGINE_DIRS_SENTINEL` -- as "template not yet
edited" and raises AuditScopeLoadError (which every caller turns into a
loud block()) exactly like a missing or malformed file. A repo that ships
this sentinel as its literal engine_dirs value gets the loud first-run
failure back; a repo with any OTHER (real) value keeps working normally.

NOT "PICK A BETTER PLACEHOLDER": the bug was never that "src" is the wrong
word for a placeholder -- it's that a placeholder which merely fails to
match any real path degrades SILENTLY (is_engine_path() -> False, no
error) instead of blocking. A different string that also matches nothing
would reproduce the defect wearing a hat. The fix has to be that the
loader RECOGNIZES the sentinel and blocks on it -- not that the sentinel
looks more obviously fake than "src" did. See
test_sentinel_blocks_regardless_of_which_path_is_edited below, which is
written specifically to catch a future "tidy-up" that swaps this token for
some other unmatched string without preserving the recognition check.

NOT WIRED INTO THIS REPO'S OWN SHIPPED docs/audit/audit-scope.yaml: this
repo's own file keeps `engine_dirs: ["src"]` (not the sentinel), because
this repo's OWN test suite (test_no_swallowed_errors.py,
test_no_type_checking_stub.py) and examples (examples/03, examples/10)
read that real file directly and assert against a real `src/`-scoped
config -- test_no_type_checking_stub.py's and test_no_swallowed_errors.py's
own module docstrings say so explicitly. Flipping the shipped value to the
sentinel would block every one of those fixtures' in-scope cases for the
wrong reason (unconfigured-scope, not the planted violation) and turn
examples/10_scope_gate_wrong_directory's whole demonstration (in-scope
BLOCKS, wrong-directory ALLOWS) into two blocks. That's a genuine
coordinated change across files this task is not scoped to touch; this
test file proves the MECHANISM works correctly in isolation, via its own
synthetic audit-scope.yaml (same technique
test_generated_paths_exemption_actually_reaches_the_hook uses), without
touching the real shipped file or the tests/examples that depend on it.

`_AUDIT_SCOPE_ROOT` resolves relative to the HOOK's own on-disk location
(three parents up from _common.py), not CLAUDE_PROJECT_DIR -- so testing
against a synthetic audit-scope.yaml means running a COPY of _common.py +
no_swallowed_errors.py from inside tmp_path, with a tmp_path-local
docs/audit/audit-scope.yaml sitting where that copy's own
_AUDIT_SCOPE_ROOT resolves it to. Nothing outside tmp_path is ever
written.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REAL_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

_VIOLATION = (
    "def foo():\n"
    "    try:\n"
    "        risky()\n"
    "    except Exception:\n"
    "        pass\n"
)


def _copied_hook(tmp_path):
    hooks_dir = tmp_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    for name in ("_common.py", "no_swallowed_errors.py"):
        (hooks_dir / name).write_text(
            (Path(REAL_HOOKS_DIR) / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return hooks_dir / "no_swallowed_errors.py"


def _write_scope(tmp_path, engine_dirs_yaml_list):
    scope_dir = tmp_path / "docs" / "audit"
    scope_dir.mkdir(parents=True)
    (scope_dir / "audit-scope.yaml").write_text(engine_dirs_yaml_list, encoding="utf-8")


def _run(tmp_path, copied_hook, rel_path, content):
    ev = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": rel_path, "content": content},
    })
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(copied_hook)], input=ev, text=True, capture_output=True,
        cwd=str(tmp_path), env=env,
    )


def test_sentinel_engine_dirs_blocks_loudly_naming_the_file(tmp_path):
    copied_hook = _copied_hook(tmp_path)
    _write_scope(tmp_path, 'engine_dirs:\n  - "__SET_ME_TO_YOUR_SOURCE_DIRS__"\n')

    result = _run(tmp_path, copied_hook, "src/foo.py", _VIOLATION)

    assert result.returncode == 2, (
        f"unconfigured (sentinel) engine_dirs must BLOCK loudly, got "
        f"{result.returncode}: {result.stderr}"
    )
    assert "audit-scope.yaml" in result.stderr
    assert "__SET_ME_TO_YOUR_SOURCE_DIRS__" in result.stderr
    assert "unconfigured" in result.stderr.lower() or "placeholder" in result.stderr.lower()


def test_sentinel_blocks_regardless_of_which_path_is_edited(tmp_path):
    """The whole point of M5: an absent/unconfigured scope must block
    UNCONDITIONALLY, not just for paths that happen to look in-scope --
    unlike a real engine_dirs value, which is silent outside its list.

    This is the test that distinguishes RECOGNITION from mere NON-MATCH.
    The defect in `engine_dirs: ["src"]` was never that "src" is the wrong
    word -- it is that the value silently matches nothing on most repos,
    converting a condition the pack handles loudly (absent scope file ->
    exit 2, named) into a silent one. A different string that also matches
    nothing would reproduce the defect wearing a hat: `is_engine_path()`
    would still just return False for every real path, no error, no
    warning -- exactly the M5 bug, just spelled differently. Asserting
    BLOCK here (not "sentinel matches zero real paths") is what proves
    `_load_engine_dirs()` actually RECOGNISES the sentinel as unconfigured
    and raises before path-matching ever runs, rather than happening to
    return an empty/unmatchable dirs list. Do not weaken this assertion to
    "no path is in scope" -- that would pass for the old, buggy behavior
    too, and would stop catching a future edit that swaps this token for a
    tidier-looking one without also keeping the recognition check.
    """
    copied_hook = _copied_hook(tmp_path)
    _write_scope(tmp_path, 'engine_dirs:\n  - "__SET_ME_TO_YOUR_SOURCE_DIRS__"\n')

    result = _run(tmp_path, copied_hook, "docs/foo.py", _VIOLATION)

    assert result.returncode == 2, (
        f"sentinel must block even for a path that wouldn't match any real "
        f"engine_dirs entry, got {result.returncode}: {result.stderr}"
    )
    # Must be the RECOGNITION block (names the sentinel/config problem), not
    # a silent allow that happens to also be rc != 0 for some other reason.
    assert "audit-scope.yaml" in result.stderr
    assert "__SET_ME_TO_YOUR_SOURCE_DIRS__" in result.stderr


def test_real_configured_value_operates_normally(tmp_path):
    """Positive control / other direction: a genuine engine_dirs value (not
    the sentinel) must behave exactly as before -- in-scope violation
    blocked, out-of-scope violation allowed, no mention of the sentinel."""
    copied_hook = _copied_hook(tmp_path)
    _write_scope(tmp_path, 'engine_dirs:\n  - "backend"\n')

    in_scope = _run(tmp_path, copied_hook, "backend/foo.py", _VIOLATION)
    assert in_scope.returncode == 2, in_scope.stderr
    assert "silently swallows an error" in in_scope.stderr
    assert "__SET_ME_TO_YOUR_SOURCE_DIRS__" not in in_scope.stderr

    out_of_scope = _run(tmp_path, copied_hook, "docs/foo.py", _VIOLATION)
    assert out_of_scope.returncode == 0, out_of_scope.stderr


def test_sentinel_alongside_other_entries_is_not_treated_as_unconfigured(tmp_path):
    """The sentinel only means "unconfigured" when it is the ENTIRE list --
    matching it as a substring/membership check would make it impossible
    for a real repo to ever have a directory that happens to collide, and
    more importantly would treat a list a user genuinely edited (added a
    real dir alongside forgetting to remove the placeholder) as still
    fully unconfigured, which is the wrong diagnosis for that case."""
    copied_hook = _copied_hook(tmp_path)
    _write_scope(
        tmp_path,
        'engine_dirs:\n  - "__SET_ME_TO_YOUR_SOURCE_DIRS__"\n  - "backend"\n',
    )

    in_scope = _run(tmp_path, copied_hook, "backend/foo.py", _VIOLATION)
    assert in_scope.returncode == 2, in_scope.stderr
    assert "silently swallows an error" in in_scope.stderr


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
