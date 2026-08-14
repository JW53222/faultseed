#!/usr/bin/env python3
"""check_interpreter_floor.py -- install-time/preflight assertion that the
harness's hook modules IMPORT CLEANLY under the interpreter that will
actually execute them.

WHY THIS EXISTS: `_dispatch.py` execs each hook with `sys.executable` --
i.e. whatever `python3` the calling process resolves to, which is the
AUDITED target's environment, not this repo's own. That interpreter is not
guaranteed to meet this repo's own >=3.10 floor (see INSTALL.md's
Dependencies section). A module-level PEP-604 union annotation without
`from __future__ import annotations` (the defect this check exists to catch)
raises TypeError at import on Python < 3.10. The crash exits 1, which the
Claude Code hook protocol treats as NON-BLOCKING (only exit 2 blocks) --
so every hook that imports `_common` silently fails OPEN: it appears
installed (present in settings.json, fires, produces a process) while
every guardrail it carries waves everything through.

This script does not try to fix that fail-open behavior in `_dispatch.py`
itself (fixing the hook protocol's own non-blocking-exit-1 convention is a
bigger design question than a single preflight check should try to solve,
so it was deliberately left alone). It gives installers a LOUD, attributable
signal *before* that silent failure mode can happen at all: run this once
per target interpreter as part of install preflight and again any time the
audited target's Python version changes.

USAGE:
    python3 check_interpreter_floor.py [--hooks-dir DIR] [--interpreter PATH]

    --hooks-dir DIR     Directory containing _common.py and friends.
                         Default: this script's own directory.
    --interpreter PATH  Interpreter to check against. Default: sys.executable
                         (the interpreter running THIS script). Pass the
                         target environment's `python3` explicitly when
                         preflighting an install for a different machine/venv.

Exits 0 and prints "OK" if `<interpreter> -c "import _common"` succeeds from
inside --hooks-dir. Exits 1 with a FATAL message (naming the interpreter,
its version, and the runbook section) if it does not.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def check(hooks_dir: Path, interpreter: str) -> tuple[bool, str]:
    """Run `<interpreter> -c "import _common"` with cwd=hooks_dir.

    Returns (ok, message). Never raises: a missing/non-executable
    interpreter is reported as a failure, not an unhandled exception --
    this is a preflight check, and a check that can crash the install
    script it's guarding is worse than no check.
    """
    try:
        proc = subprocess.run(
            [interpreter, "-c", "import _common"],
            cwd=str(hooks_dir),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        return False, f"could not run interpreter {interpreter!r}: {e}"

    if proc.returncode == 0:
        version = subprocess.run(
            [interpreter, "-c", "import sys; print(sys.version.split()[0])"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        return True, f"OK: {interpreter} ({version}) imports {hooks_dir}/_common.py cleanly"

    return False, (
        f"FATAL: {interpreter!r} failed to import {hooks_dir}/_common.py "
        f"(exit {proc.returncode}).\n"
        "This means the harness hooks will FAIL OPEN under this interpreter: "
        "an ImportError exits 1, which the Claude Code hook protocol treats "
        "as non-blocking, so every guardrail hook that imports _common "
        "silently permits everything instead of enforcing.\n"
        f"stderr:\n{proc.stderr}"
        "\nThis interpreter does not meet the >=3.10 floor _common.py "
        "requires. See INSTALL.md's Dependencies section for why, and pin a "
        "newer interpreter (or pass --interpreter to point this check at the "
        "one you plan to use)."
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hooks-dir", default=None,
        help="directory containing _common.py (default: this script's own directory)",
    )
    parser.add_argument(
        "--interpreter", default=sys.executable,
        help="interpreter to check (default: sys.executable, i.e. the interpreter "
             "running this script)",
    )
    args = parser.parse_args(argv)

    hooks_dir = Path(args.hooks_dir) if args.hooks_dir else Path(__file__).resolve().parent

    ok, message = check(hooks_dir, args.interpreter)
    if ok:
        print(message)
        return 0
    sys.stderr.write(message + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
