#!/usr/bin/env python3
"""Self-scan: runs faultseed's own engine-quality guards
(no_swallowed_errors.py, no_type_checking_stub.py) over the pack's OWN
source tree.

Filed because an independent oppositional review found two unmarked
swallows inside this pack's own .claude/hooks/ and scripts/ that the
pack's own no_swallowed_errors guard would flag if it ever looked at
them -- invisible only because the shipped
docs/audit/audit-scope.yaml ships `engine_dirs: ["src"]` and this pack
has no `src/`, so the guard never scanned its own files. "faultseed
does not pass faultseed" was the exact finding: the first probe a
skeptical engineer runs on a guard pack, and nothing caught it before
publication. This test is that CI step, wired permanently into
run_tests.sh's normal suite discovery so it runs on every push and PR
the same way every other suite here does -- no separate ci.yml step
needed, and none added, because a guard pack whose CI entry point is
"run the one command" (run_tests.sh) should not grow a second,
parallel way to invoke coverage.

This test does NOT depend on the shipped docs/audit/audit-scope.yaml.
That file is user-facing config -- a fresh clone's own copy may be
edited, including to a sentinel that deliberately BLOCKS until
configured (see that file's own header comment) -- and this self-scan
must keep working regardless of what a user (or a sibling change in
this same pack) does to it. Instead it builds its OWN synthetic scope:
a throwaway copy of _common.py plus the two engine-quality guards
under tmp_path/.claude/hooks/, with a tmp_path-local
docs/audit/audit-scope.yaml declaring `engine_dirs: ["src"]`. Because
_common.py's `_AUDIT_SCOPE_ROOT` resolves relative to the HOOK's own
on-disk `__file__` (not CLAUDE_PROJECT_DIR -- see
test_no_swallowed_errors.py's module docstring for the full
derivation), running the COPY from under tmp_path makes it read the
COPY's synthetic audit-scope.yaml, not this repo's real one.

Every real, non-test .py file under .claude/hooks/ and scripts/ (this
pack's actual source, discovered by glob so a file added later is
picked up automatically -- not hardcoded, which is exactly the M2
lesson: an untested axis silently drifts out of coverage) is fed to
both guards as a synthetic Write event whose file_path is rewritten to
`src/<basename>` (so it lands inside the synthetic engine_dirs) but
whose CONTENT is the real file's current on-disk content -- so a
violation introduced in the real file is what trips the guard here,
not the file_path string.

test_positive_control_bare_except_is_caught proves the rig is actually
live: an unmarked bare `except: pass` MUST be blocked by this same
harness. A self-scan that can't catch a bare violation isn't a
self-scan, it's decoration -- see the mutation-testing traps recorded
in the review this test was filed from (a mutation that never applies
makes a test pass for the wrong reason).
"""
import glob
import json
import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_SRC_DIR = os.path.join(REPO_ROOT, ".claude", "hooks")
SCRIPTS_SRC_DIR = os.path.dirname(os.path.abspath(__file__))

GUARDS = ["no_swallowed_errors.py", "no_type_checking_stub.py"]

# Floor for the discovery vacuity check below. 14 files exist at time of
# writing (12 under .claude/hooks/, 2 under scripts/); the floor is set
# comfortably under that so ordinary growth/removal of a file or two never
# trips it, while a mass disappearance (wrong glob, moved directory) does.
_MIN_EXPECTED_PACK_SOURCE_FILES = 10


def _discover_pack_source_files():
    """Every non-test .py file the pack ships as its own source, under
    .claude/hooks/ and scripts/ -- excluding test_*.py (that's the SUITE,
    not the pack under test) and anything under __pycache__."""
    files = []
    for src_dir in (HOOKS_SRC_DIR, SCRIPTS_SRC_DIR):
        for path in glob.glob(os.path.join(src_dir, "*.py")):
            if os.path.basename(path).startswith("test_"):
                continue
            files.append(path)
    return sorted(files)


PACK_SOURCE_FILES = _discover_pack_source_files()


def test_pack_source_discovery_is_not_vacuous():
    """Same doctrine run_tests.sh applies to whole suites, applied here to
    this test's own file list: a self-scan silently discovering zero (or
    near-zero) files to scan is indistinguishable from a self-scan that was
    never wired up at all."""
    assert len(PACK_SOURCE_FILES) >= _MIN_EXPECTED_PACK_SOURCE_FILES, (
        f"only discovered {len(PACK_SOURCE_FILES)} pack source file(s) under "
        f"{HOOKS_SRC_DIR} and {SCRIPTS_SRC_DIR} (expected >= "
        f"{_MIN_EXPECTED_PACK_SOURCE_FILES}). If this repo's source layout "
        "legitimately moved, update the discovery dirs in this file "
        "deliberately; if it silently dropped, the self-scan below is "
        "running against nothing."
    )


@pytest.fixture(scope="module")
def synthetic_scope(tmp_path_factory):
    """Build the throwaway .claude/hooks/ + docs/audit/audit-scope.yaml rig
    described in the module docstring, once per test session, and return its
    root."""
    root = tmp_path_factory.mktemp("guards_self_scan")
    hooks_dst = root / ".claude" / "hooks"
    hooks_dst.mkdir(parents=True)
    shutil.copy2(os.path.join(HOOKS_SRC_DIR, "_common.py"), hooks_dst / "_common.py")
    for guard in GUARDS:
        shutil.copy2(os.path.join(HOOKS_SRC_DIR, guard), hooks_dst / guard)
    scope_dir = root / "docs" / "audit"
    scope_dir.mkdir(parents=True)
    (scope_dir / "audit-scope.yaml").write_text('engine_dirs:\n  - "src"\n', encoding="utf-8")
    return root


def _run_guard(synthetic_scope, guard, content, in_scope_basename):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(synthetic_scope)
    ev = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": f"src/{in_scope_basename}", "content": content},
    })
    hook_path = synthetic_scope / ".claude" / "hooks" / guard
    return subprocess.run(
        [sys.executable, str(hook_path)], input=ev, text=True, capture_output=True,
        cwd=str(synthetic_scope), env=env,
    )


@pytest.mark.parametrize("guard", GUARDS)
@pytest.mark.parametrize(
    "real_path", PACK_SOURCE_FILES,
    ids=[os.path.relpath(p, REPO_ROOT) for p in PACK_SOURCE_FILES],
)
def test_pack_source_clears_own_engine_quality_guards(synthetic_scope, real_path, guard):
    content = open(real_path, encoding="utf-8").read()
    result = _run_guard(synthetic_scope, guard, content, os.path.basename(real_path))
    rel = os.path.relpath(real_path, REPO_ROOT)
    assert result.returncode != 2, (
        f"{guard} flags this pack's OWN source file {rel}:\n{result.stderr}\n"
        "faultseed's own guards must pass over faultseed's own tree -- fix "
        "the flagged code, or mark it with the documented "
        "'# swallow-ok: <reason>' / TYPE_CHECKING-stub escape (see "
        "honesty-guardrails / this hook's own module docstring)."
    )


def test_positive_control_bare_except_is_caught(synthetic_scope):
    """Proves the rig above is actually live: an unmarked bare `except:
    pass` MUST be blocked. If this goes green with rc != 2, the self-scan
    above is vacuous and nothing can be trusted from it."""
    content = (
        "def f():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    result = _run_guard(synthetic_scope, "no_swallowed_errors.py", content, "positive_control.py")
    assert result.returncode == 2, (
        f"positive control did not block (rc={result.returncode}); the "
        "self-scan rig above is not exercising the guard -- see stderr:\n"
        f"{result.stderr}"
    )
