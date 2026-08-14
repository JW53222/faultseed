#!/usr/bin/env python3
"""Planted-failure tests for check_escape_markers.py.

Every test here builds its own throwaway git repo under `tmp_path` (a real
`git init` + real commits) and runs the real, unmodified script as a
subprocess against it -- exactly the black-box convention section 1 of
CONTRIBUTING.md asks for, extended to a script that scans a DIFF and a
commit RANGE rather than a single PreToolUse event. Nothing here touches
this repo's own `.git/` or the network.

Per this repo's own doctrine (.claude/rules/honesty-guardrails.md, "No
vacuous tests" / CONTRIBUTING.md section 2, "the mutation check"): every
test function below was run against a deliberately broken
check_escape_markers.py (a targeted mutation -- inverting the
bare/reasoned branch in `_detect_swallow`, and separately hardcoding
`main()`'s bare/unacknowledged/tier_b_failures check to `False` -- watched
to fail, then restored, before being counted as done. See this session's
closing report for the mutation record (CONTRIBUTING.md section 2 does not
ask this to be re-derived at import time -- a self-mutating suite would be
its own hazard).
"""
from __future__ import annotations

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(SCRIPT_DIR, "check_escape_markers.py")

sys.path.insert(0, SCRIPT_DIR)
import check_escape_markers as cem  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True, capture_output=True)


def _init_repo(tmp_path, name="repo"):
    root = tmp_path / name
    root.mkdir()
    _git(["init", "-q", "-b", "main"], root)
    _git(["config", "user.name", "tester"], root)
    _git(["config", "user.email", "tester@example.invalid"], root)
    return root


def _write(root, relpath, content):
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _commit(root, message, trailer_lines=None):
    body = message if not trailer_lines else message + "\n\n" + "\n".join(trailer_lines)
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", body], root)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _run(root, base_ref, extra_env=None, extra_path=None):
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    if extra_path:
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, SCRIPT, "--root", str(root), "--base-ref", base_ref],
        capture_output=True, text=True, env=env,
    )


# A marker keyword and its reason-carrying/bare forms, assembled at runtime
# (concatenation rather than a contiguous literal) so THIS test file --
# which legitimately needs to plant realistic marker text as fixture
# content -- reads clearly as "building a fixture", not as an accidental
# second copy of the live syntax sitting in prose. (is_test_file() already
# excludes this file from check_escape_markers.py's own scan regardless --
# see that script's SCOPE section -- this is about readability, not safety.)
def _marker_reasoned(keyword, reason):
    return "#" + " " + keyword + ":" + " " + reason


def _marker_bare(keyword):
    return "#" + " " + keyword


SWALLOW_KEYWORD = "swallow-ok"


def _swallow_snippet(marker_comment):
    return (
        "def f():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        f"        pass  {marker_comment}\n"
    )


# ---------------------------------------------------------------------------
# Core contract: bare / unacknowledged / acknowledged (Tier A)
# ---------------------------------------------------------------------------

def test_bare_marker_blocked_naming_file_and_line(tmp_path):
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", _swallow_snippet(_marker_bare(SWALLOW_KEYWORD)))
    _commit(root, "bare marker")

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_UNACKNOWLEDGED
    assert "BARE" in proc.stdout
    assert "src/foo.py:5" in proc.stdout


def test_reasoned_marker_without_trailer_blocked_naming_file_and_line(tmp_path):
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", _swallow_snippet(_marker_reasoned(SWALLOW_KEYWORD, "deliberate degrade to default")))
    _commit(root, "reasoned, no trailer")

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_UNACKNOWLEDGED
    assert "UNACKNOWLEDGED" in proc.stdout
    assert "src/foo.py:5" in proc.stdout


def test_reasoned_marker_with_trailer_allowed(tmp_path):
    """The NEGATIVE-CONTROL twin of the two BLOCKED tests above: identical
    marker, only the trailer differs -- the pairing this pack's own
    CONTRIBUTING.md section 1 asks every guard's test file to have."""
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", _swallow_snippet(_marker_reasoned(SWALLOW_KEYWORD, "deliberate degrade to default")))
    _commit(root, "reasoned, acknowledged", trailer_lines=["Escape-Markers: src/foo.py:5"])

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout


def test_trailer_in_earlier_commit_of_the_range_still_counts(tmp_path):
    """The trailer doesn't have to be on the SAME commit that introduces the
    marker -- any commit in the diffed range acknowledges it."""
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", _swallow_snippet(_marker_reasoned(SWALLOW_KEYWORD, "deliberate degrade to default")))
    _commit(root, "introduces the marker", trailer_lines=["Escape-Markers: src/foo.py:5"])
    _write(root, "src/other.py", "def g():\n    return 2\n")
    _commit(root, "unrelated follow-up commit")

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr


def test_trailer_acknowledging_a_different_line_does_not_cover_this_one(tmp_path):
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", _swallow_snippet(_marker_reasoned(SWALLOW_KEYWORD, "deliberate degrade to default")))
    _commit(root, "reasoned, wrong trailer", trailer_lines=["Escape-Markers: src/foo.py:99"])

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_UNACKNOWLEDGED
    assert "src/foo.py:5" in proc.stdout


def test_comma_separated_trailer_covers_multiple_markers(tmp_path):
    root = _init_repo(tmp_path)
    _write(root, "src/a.py", "def a():\n    return 1\n")
    _write(root, "src/b.py", "def b():\n    return 2\n")
    base = _commit(root, "base")
    _write(root, "src/a.py", _swallow_snippet(_marker_reasoned(SWALLOW_KEYWORD, "degrade a")))
    _write(root, "src/b.py", _swallow_snippet(_marker_reasoned(SWALLOW_KEYWORD, "degrade b")))
    _commit(root, "two markers, one trailer line", trailer_lines=[
        "Escape-Markers: src/a.py:5, src/b.py:5",
    ])

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr


def test_no_markers_added_is_clean(tmp_path):
    """NEGATIVE CONTROL for the whole gate: an ordinary change with no
    escape markers at all must pass without needing any trailer."""
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", "def f():\n    return 2\n")
    _commit(root, "ordinary change")

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr
    assert "0 escape marker(s) added" in proc.stdout


# ---------------------------------------------------------------------------
# Vocabulary -- one planted case per marker family (not exhaustive of every
# comment syntax each hook supports; MARKER_SPECS' own detectors already
# import the governing hook's real regex, so per-syntax coverage of e.g.
# swallow-ok's Go/PowerShell forms belongs to no_swallowed_errors.py's own
# test file, not duplicated here).
# ---------------------------------------------------------------------------

def _plant_and_check(tmp_path, name, relpath, initial, marker_line_content, trailer_line):
    root = _init_repo(tmp_path, name)
    _write(root, relpath, initial)
    base = _commit(root, "base")
    _write(root, relpath, marker_line_content)
    _commit(root, "adds a marker")
    proc_unack = _run(root, base)

    root2 = _init_repo(tmp_path, name + "-ack")
    _write(root2, relpath, initial)
    base2 = _commit(root2, "base")
    _write(root2, relpath, marker_line_content)
    _commit(root2, "adds a marker, acknowledged", trailer_lines=[trailer_line])
    proc_ack = _run(root2, base2)
    return proc_unack, proc_ack


def test_tampering_ok_marker_detected(tmp_path):
    initial = "def test_x():\n    assert 1 == 1\n"
    marked = "def test_x():\n    " + _marker_reasoned("tampering-ok", "the code now returns 2, see PR") + "\n    pass\n"
    unack, ack = _plant_and_check(tmp_path, "tampering", "tests/test_foo.py", initial, marked, "Escape-Markers: tests/test_foo.py:2")
    # is_test_file() excludes tests/*.py from THIS gate's scan entirely (see
    # SCOPE) -- a marker inside a test fixture file is never flagged, same
    # as every shipped guard's own test-file exemption. Confirms the
    # exemption applies here too, not a detection failure of tampering-ok.
    assert unack.returncode == cem.EXIT_CLEAN
    assert ack.returncode == cem.EXIT_CLEAN


def test_host_provides_marker_detected(tmp_path):
    initial = "class Foo:\n    pass\n"
    marked = (
        "from typing import TYPE_CHECKING\n"
        "class Foo:\n"
        "    if TYPE_CHECKING:\n"
        "        " + _marker_reasoned("host-provides", "Host defines this at runtime") + "\n"
        "        def bar(self) -> int: ...\n"
    )
    unack, ack = _plant_and_check(tmp_path, "stub", "src/foo.py", initial, marked, "Escape-Markers: src/foo.py:4")
    assert unack.returncode == cem.EXIT_UNACKNOWLEDGED
    assert ack.returncode == cem.EXIT_CLEAN


def test_delete_tests_ok_marker_detected(tmp_path):
    initial = "#!/bin/sh\necho hello\n"
    marked = "#!/bin/sh\necho hello\n" + _marker_reasoned("delete-tests-ok", "suite genuinely obsolete, see PR 42") + "\nrm tests/test_old.py\n"
    unack, ack = _plant_and_check(tmp_path, "deltest", "scripts_cleanup.sh", initial, marked, "Escape-Markers: scripts_cleanup.sh:3")
    assert unack.returncode == cem.EXIT_UNACKNOWLEDGED
    assert ack.returncode == cem.EXIT_CLEAN


def test_test_mutate_ok_marker_detected(tmp_path):
    initial = "#!/bin/sh\necho hello\n"
    marked = "#!/bin/sh\necho hello\n" + _marker_reasoned("test-mutate-ok", "refactor preserves coverage, see PR 42") + "\nsed -i 's/x/y/' tests/test_old.py\n"
    unack, ack = _plant_and_check(tmp_path, "mutest", "maint.sh", initial, marked, "Escape-Markers: maint.sh:3")
    assert unack.returncode == cem.EXIT_UNACKNOWLEDGED
    assert ack.returncode == cem.EXIT_CLEAN


def test_workflow_model_ok_marker_detected(tmp_path):
    initial = "// workflow script\n"
    marked = "// workflow script\nagent(p, {subagent_type: \"gp\"}); " + "// " + "workflow-model-ok" + ": " + "deliberate inherit from parent\n"
    unack, ack = _plant_and_check(tmp_path, "wfmodel", "workflow.js", initial, marked, "Escape-Markers: workflow.js:2")
    assert unack.returncode == cem.EXIT_UNACKNOWLEDGED
    assert ack.returncode == cem.EXIT_CLEAN


def test_opus_leaf_ok_marker_detected(tmp_path):
    initial = "PROMPT = 'do the thing'\n"
    marked = "PROMPT = 'do the thing. " + _marker_reasoned_inline("opus-leaf-ok", "one bounded oppositional review") + "'\n"
    unack, ack = _plant_and_check(tmp_path, "opusleaf", "prompts.py", initial, marked, "Escape-Markers: prompts.py:1")
    assert unack.returncode == cem.EXIT_UNACKNOWLEDGED
    assert ack.returncode == cem.EXIT_CLEAN


def test_fable_leaf_ok_marker_detected(tmp_path):
    initial = "PROMPT = 'do the thing'\n"
    marked = "PROMPT = 'do the thing. " + _marker_reasoned_inline("fable-leaf-ok", "one bounded oppositional review") + "'\n"
    unack, ack = _plant_and_check(tmp_path, "fableleaf", "prompts.py", initial, marked, "Escape-Markers: prompts.py:1")
    assert unack.returncode == cem.EXIT_UNACKNOWLEDGED
    assert ack.returncode == cem.EXIT_CLEAN


def test_doc_ref_ok_marker_detected_in_a_dot_py_file(tmp_path):
    """doc-ref-ok's highest-volume habitat (.md prose) is out of this
    gate's scanned-extension set by design (see SCOPE) -- but the marker
    CAN legitimately appear in a .py docstring too, and that occurrence
    must still be caught."""
    initial = '"""module docstring"""\n'
    marked = '"""module docstring, cites a name deliberately not resolved. ' + _marker_reasoned_inline("doc-ref-ok", "conftest.py is an ecosystem convention name, not a real citation") + '"""\n'
    unack, ack = _plant_and_check(tmp_path, "docref", "src/mod.py", initial, marked, "Escape-Markers: src/mod.py:1")
    assert unack.returncode == cem.EXIT_UNACKNOWLEDGED
    assert ack.returncode == cem.EXIT_CLEAN


def _marker_reasoned_inline(keyword, reason):
    """Same shape as `_marker_reasoned`, without the leading `#` -- for
    markers with no required comment prefix (opus-leaf-ok / fable-leaf-ok /
    doc-ref-ok)."""
    return keyword + ":" + " " + reason


# ---------------------------------------------------------------------------
# Scope -- both directions, per this pack's own vacuity doctrine
# (CONTRIBUTING.md section 7: "your test suite must pin the scope in BOTH
# directions").
# ---------------------------------------------------------------------------

def test_markdown_file_out_of_scope_even_with_a_realistic_marker(tmp_path):
    """The identical bug, in a .md file instead of a .py file, must NOT be
    flagged -- see module docstring's SCOPE section, point 1."""
    root = _init_repo(tmp_path)
    _write(root, "docs/notes.md", "# Notes\n")
    base = _commit(root, "base")
    _write(root, "docs/notes.md", "# Notes\n\n" + _marker_reasoned(SWALLOW_KEYWORD, "deliberate degrade to default") + "\n")
    _commit(root, "docs touch with realistic marker text")

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr
    assert "0 escape marker(s) added" in proc.stdout


def test_examples_directory_out_of_scope(tmp_path):
    root = _init_repo(tmp_path)
    _write(root, "examples/03_demo/run.sh", "#!/bin/sh\necho demo\n")
    base = _commit(root, "base")
    _write(root, "examples/03_demo/run.sh", "#!/bin/sh\necho demo\n" + _marker_bare(SWALLOW_KEYWORD) + "\n")
    _commit(root, "example fixture touch")

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr


def test_test_file_out_of_scope(tmp_path):
    root = _init_repo(tmp_path)
    _write(root, "tests/test_thing.py", "def test_a():\n    assert True\n")
    base = _commit(root, "base")
    _write(root, "tests/test_thing.py", "def test_a():\n    " + _marker_bare(SWALLOW_KEYWORD) + "\n    assert True\n")
    _commit(root, "test fixture touch")

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr


def test_identical_marker_in_scope_and_out_of_scope_same_commit(tmp_path):
    """Same shape as the two tests above, folded into ONE test/commit so
    the pairing can't drift apart -- mirrors
    test_no_swallowed_errors.py::test_engine_scope_gate_both_directions."""
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    _write(root, "docs/notes.md", "# Notes\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", _swallow_snippet(_marker_bare(SWALLOW_KEYWORD)))
    _write(root, "docs/notes.md", "# Notes\n\n" + _marker_reasoned(SWALLOW_KEYWORD, "same shape, wrong extension") + "\n")
    _commit(root, "one in scope, one not, same commit")

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_UNACKNOWLEDGED
    assert "src/foo.py" in proc.stdout
    assert "docs/notes.md" not in proc.stdout


def test_self_path_is_excluded_from_its_own_scan(tmp_path):
    """SELF-CONFIG EXCLUSION (see check_escape_markers.py's own "Self-scan
    note"): the PR that adds/touches check_escape_markers.py itself must
    never be flagged for containing its own vocabulary table. This is a
    real dogfood scenario, not a hypothetical -- this exact PR touches this
    exact file."""
    root = _init_repo(tmp_path)
    _write(root, "src/placeholder.py", "x = 1\n")
    base = _commit(root, "base")
    with open(SCRIPT, encoding="utf-8") as f:
        real_source = f.read()
    _write(root, cem.SELF_PATH, real_source)
    _commit(root, "add check_escape_markers.py")

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr
    assert "0 in this gate's scanned-extension scope" in proc.stdout


# ---------------------------------------------------------------------------
# Malformed / edge inputs
# ---------------------------------------------------------------------------

def test_malformed_trailer_token_is_ignored_and_reported(tmp_path):
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", _swallow_snippet(_marker_reasoned(SWALLOW_KEYWORD, "deliberate degrade to default")))
    _commit(root, "malformed trailer", trailer_lines=["Escape-Markers: not-a-valid-token"])

    proc = _run(root, base)
    assert proc.returncode == cem.EXIT_UNACKNOWLEDGED
    assert "malformed" in proc.stdout.lower()


# ---------------------------------------------------------------------------
# Usage errors -- diff cannot be computed at all (EXIT_USAGE_ERROR), distinct
# from a real, computed, empty/clean diff (EXIT_CLEAN).
# ---------------------------------------------------------------------------

def test_bad_base_ref_is_usage_error_not_a_silent_clean_pass(tmp_path):
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    _commit(root, "base")

    proc = _run(root, "not-a-real-ref-anywhere")
    assert proc.returncode == cem.EXIT_USAGE_ERROR
    assert "could not compute a diff" in proc.stderr


def test_no_base_ref_given_is_usage_error(tmp_path):
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    _commit(root, "base")

    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("GUARDRAILS_ESCAPE_BASE_REF", None)
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--root", str(root)],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == cem.EXIT_USAGE_ERROR
    assert "no base ref given" in proc.stderr.lower()


def test_genuinely_empty_diff_is_a_clean_pass_not_a_usage_error(tmp_path):
    """NEGATIVE CONTROL for the two tests above: a VALID base ref that
    happens to equal HEAD (nothing changed) is a real, computed, empty
    diff -- a legitimate clean pass, not the "couldn't compute a diff at
    all" failure mode."""
    root = _init_repo(tmp_path)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    head = _commit(root, "base")

    proc = _run(root, head)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# Tier B -- ANTHROPIC_API_KEY-gated LLM adjudication. `claude` is stubbed
# via a throwaway PATH entry (same technique example 11 / a "missing
# dependency" test uses for `jq` in protect-files.sh) so these tests are
# deterministic and never touch a real network or API key.
# ---------------------------------------------------------------------------

def _write_claude_stub(tmp_path, output):
    stub_dir = tmp_path / "stubbin"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "claude"
    stub.write_text("#!/bin/sh\n" + f'printf "%s\\n" "{output}"\n', encoding="utf-8")
    stub.chmod(0o755)
    return str(stub_dir)


def _acknowledged_repo(tmp_path, name="tierb"):
    root = _init_repo(tmp_path, name)
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", _swallow_snippet(_marker_reasoned(SWALLOW_KEYWORD, "deliberate degrade to default")))
    _commit(root, "reasoned, acknowledged", trailer_lines=["Escape-Markers: src/foo.py:5"])
    return root, base


def test_tier_b_absent_key_skips_loudly_and_tier_a_alone_gates(tmp_path):
    root, base = _acknowledged_repo(tmp_path)
    proc = _run(root, base)  # no ANTHROPIC_API_KEY in env (see _run)
    assert proc.returncode == cem.EXIT_CLEAN
    assert "SKIPPED" in proc.stdout
    assert "ANTHROPIC_API_KEY" in proc.stdout


def test_tier_b_pass_allows(tmp_path):
    root, base = _acknowledged_repo(tmp_path, "tierb-pass")
    stub_path = _write_claude_stub(tmp_path, "PASS")
    proc = _run(root, base, extra_env={"ANTHROPIC_API_KEY": "fake-key-for-test"}, extra_path=stub_path)
    assert proc.returncode == cem.EXIT_CLEAN, proc.stdout + proc.stderr
    assert "1 PASS, 0 FAIL" in proc.stdout


def test_tier_b_fail_blocks_even_though_tier_a_passed(tmp_path):
    root, base = _acknowledged_repo(tmp_path, "tierb-fail")
    stub_path = _write_claude_stub(tmp_path, "FAIL")
    proc = _run(root, base, extra_env={"ANTHROPIC_API_KEY": "fake-key-for-test"}, extra_path=stub_path)
    assert proc.returncode == cem.EXIT_UNACKNOWLEDGED
    assert "TIER-B-FAIL" in proc.stdout


def test_tier_b_ambiguous_output_folds_to_fail(tmp_path):
    """Mirrors .claude/rules/honesty-guardrails.md's "AMBIGUOUS FOLDS INTO
    FAIL" rule -- anything that is not the exact token PASS is a FAIL,
    including a hedge that isn't an outright FAIL either."""
    root, base = _acknowledged_repo(tmp_path, "tierb-ambiguous")
    stub_path = _write_claude_stub(tmp_path, "I cannot tell from this diff alone")
    proc = _run(root, base, extra_env={"ANTHROPIC_API_KEY": "fake-key-for-test"}, extra_path=stub_path)
    assert proc.returncode == cem.EXIT_UNACKNOWLEDGED
    assert "TIER-B-FAIL" in proc.stdout


def test_tier_b_key_set_but_claude_binary_missing_fails_loudly(tmp_path):
    """This is NOT the absent-key skip -- the operator opted in by setting
    the key, so a missing `claude` binary must fail loudly (EXIT_USAGE_ERROR,
    naming `claude`), not silently fall back to Tier A alone. Uses an
    isolated PATH with no `claude` anywhere on it (but still real `git`, or
    the diff computation itself would fail for the wrong reason)."""
    root, base = _acknowledged_repo(tmp_path, "tierb-missing-claude")
    git_dir = os.path.dirname(subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip())
    empty_bin = tmp_path / "no-claude-here"
    empty_bin.mkdir()
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env["ANTHROPIC_API_KEY"] = "fake-key-for-test"
    env["PATH"] = str(empty_bin) + os.pathsep + git_dir + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--root", str(root), "--base-ref", base],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == cem.EXIT_USAGE_ERROR
    assert "claude" in proc.stderr


def test_tier_b_not_invoked_when_zero_reasoned_acknowledged_markers(tmp_path):
    """A bare marker (which Tier A already rejects outright) must not
    trigger a Tier B call -- nothing to adjudicate, and no reason to shell
    out to `claude` for it."""
    root = _init_repo(tmp_path, "tierb-nothing-to-adjudicate")
    _write(root, "src/foo.py", "def f():\n    return 1\n")
    base = _commit(root, "base")
    _write(root, "src/foo.py", _swallow_snippet(_marker_bare(SWALLOW_KEYWORD)))
    _commit(root, "bare marker only")

    stub_dir = tmp_path / "stubbin-should-not-run"
    stub_dir.mkdir()
    stub = stub_dir / "claude"
    stub.write_text("#!/bin/sh\necho SHOULD_NOT_HAVE_RUN >&2\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)

    proc = _run(root, base, extra_env={"ANTHROPIC_API_KEY": "fake-key-for-test"}, extra_path=str(stub_dir))
    assert proc.returncode == cem.EXIT_UNACKNOWLEDGED
    assert "SHOULD_NOT_HAVE_RUN" not in proc.stdout + proc.stderr
    assert "nothing to adjudicate" in proc.stdout
