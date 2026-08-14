"""Unit tests for check_interpreter_floor.py -- the install-time preflight
assertion that hook modules import cleanly under the interpreter that will
run them (see INSTALL.md's Dependencies section for the >=3.10 floor).

Uses a synthetic throwaway hooks dir per test rather than this repo's real
.claude/hooks/, so the "broken" case is a controlled fixture, not a
temporary mutation of the real _common.py.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

HOOK_PATH = Path(__file__).resolve().parent / "check_interpreter_floor.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_interpreter_floor", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_interpreter_floor"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_clean_module_imports_ok(tmp_path):
    mod = _load_module()
    (tmp_path / "_common.py").write_text(
        "from __future__ import annotations\nX: int | None = None\n"
    )
    ok, message = mod.check(tmp_path, sys.executable)
    assert ok is True
    assert "OK" in message


def test_module_level_union_without_future_import_is_reported(tmp_path):
    mod = _load_module()
    # Reproduces the exact real-world defect shape: a module-level PEP-604
    # union annotation is only a problem without the future-import.
    (tmp_path / "_common.py").write_text("X: int | None = None\n")
    ok, message = mod.check(tmp_path, sys.executable)
    if sys.version_info >= (3, 10):  # noqa: UP036 -- intentional cross-version branch, not dead code
        # Under 3.10+ this is legal even without the future-import, so the
        # synthetic fixture can't reproduce the failure on THIS interpreter
        # -- confirmed real cross-version behavior is covered by the
        # receipt doc's python3.9 run, not by this unit test.
        assert ok is True
    else:
        assert ok is False
        assert "FATAL" in message
        assert "fail OPEN" in message or "FAIL OPEN" in message


def test_python39_reproduces_real_defect_if_available(tmp_path):
    py39 = shutil.which("python3.9")
    if not py39:
        return  # environment-dependent; not a failure if python3.9 isn't installed
    mod = _load_module()
    (tmp_path / "_common.py").write_text("X: int | None = None\n")
    ok, message = mod.check(tmp_path, py39)
    assert ok is False
    assert "FATAL" in message

    (tmp_path / "_common.py").write_text(
        "from __future__ import annotations\nX: int | None = None\n"
    )
    ok, message = mod.check(tmp_path, py39)
    assert ok is True


def test_nonexistent_interpreter_reported_not_raised(tmp_path):
    mod = _load_module()
    (tmp_path / "_common.py").write_text("X = 1\n")
    ok, message = mod.check(tmp_path, "/no/such/interpreter-xyz")
    assert ok is False
    assert "could not run interpreter" in message


def test_cli_exit_codes(tmp_path, capsys):
    mod = _load_module()
    (tmp_path / "_common.py").write_text(
        "from __future__ import annotations\nX: int | None = None\n"
    )
    rc = mod.main(["--hooks-dir", str(tmp_path), "--interpreter", sys.executable])
    assert rc == 0

    (tmp_path / "_common.py").write_text("X: int | None = None\n")
    if sys.version_info < (3, 10):  # noqa: UP036 -- intentional cross-version branch, not dead code
        rc = mod.main(["--hooks-dir", str(tmp_path), "--interpreter", sys.executable])
        assert rc == 1
