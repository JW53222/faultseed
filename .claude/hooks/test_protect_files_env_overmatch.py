#!/usr/bin/env python3
"""Regression tests: protect-files.sh's PROTECTED_PATTERNS matcher used bare
bash substring tests (`[[ "$FILE_PATH" == *"$pattern"* ]]`), so the ".env"
pattern blocked ANY path containing the literal 4-byte sequence ".env" --
not just an actual dotenv file. Confirmed over-matches (pre-fix): a Write to
"config.envoy.yaml" or "dev.environment.md" was blocked (exit 2), even
though neither is a secrets file. "src/environment.py" happened to pass
(exit 0) only because there is no "." immediately before "env" in
"environment.py" -- coincidence, not correct logic; a shallow sanity check
on that one file alone would wrongly conclude the matcher was sound.

Fixed 2026-08-08: ".env" is now matched on the file's BASENAME (exactly
".env", or ".env.<suffix>" like ".env.local"/".env.production"), and
"package-lock.json" on an exact basename. ".git/" and "migrations/" remain
directory-segment matches (now leading-slash-padded so a name that merely
shares the substring, e.g. "notmigrations/foo" or "mygit/config", is not
mistaken for the real directory segment).

Black-box: feed a PreToolUse Edit/Write event (stdin JSON) to the real
protect-files.sh and assert exit code (2 = block, 0 = allow) plus the
distinguishing "Blocked: ... matches protected pattern '<pattern>'" phrase
for the block cases. Migration-path cases run against real files created in
a temp cwd, since the hook's new-migration exemption is an `-e "$FILE_PATH"`
filesystem check, not just a string match.
"""
import json
import os
import subprocess
import tempfile

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HOOKS_DIR, "protect-files.sh")


def _run(file_path, cwd):
    ev = json.dumps({"tool_input": {"file_path": file_path}})
    return subprocess.run(
        ["bash", HOOK], input=ev, text=True, capture_output=True, cwd=cwd
    )


def _touch(cwd, rel_path):
    full = os.path.join(cwd, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "w").close()


# --- MUST-BLOCK: real secrets/lockfile/git/migration paths ---

def test_blocks_dotenv_exact():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, ".env")
        r = _run(".env", d)
        assert r.returncode == 2
        assert "protected pattern '.env'" in r.stderr


def test_blocks_dotenv_local_suffix():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, ".env.local")
        r = _run(".env.local", d)
        assert r.returncode == 2
        assert "protected pattern '.env'" in r.stderr


def test_blocks_dotenv_production_suffix():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, ".env.production")
        r = _run(".env.production", d)
        assert r.returncode == 2


def test_blocks_dotenv_nested():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "backend/.env")
        r = _run("backend/.env", d)
        assert r.returncode == 2


def test_blocks_lockfile_root():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "package-lock.json")
        r = _run("package-lock.json", d)
        assert r.returncode == 2
        assert "protected pattern 'package-lock.json'" in r.stderr


def test_blocks_lockfile_nested():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "frontend/package-lock.json")
        r = _run("frontend/package-lock.json", d)
        assert r.returncode == 2


def test_blocks_under_git_dir():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "some/dir/.git/HEAD")
        r = _run("some/dir/.git/HEAD", d)
        assert r.returncode == 2
        assert "protected pattern '.git/'" in r.stderr


def test_blocks_existing_migration():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "backend/migrations/0002_x.py")
        r = _run("backend/migrations/0002_x.py", d)
        assert r.returncode == 2
        assert "protected pattern 'migrations/'" in r.stderr


def test_allows_brand_new_migration_file():
    # Path doesn't exist yet -- the hook's documented "still needs to be
    # created via Write" exemption.
    with tempfile.TemporaryDirectory() as d:
        r = _run("migrations/9999_new_not_yet_created.sql", d)
        assert r.returncode == 0


# --- MUST-PASS: ordinary paths that merely contain look-alike substrings ---

def test_allows_envoy_config_yaml():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "config.envoy.yaml")
        r = _run("config.envoy.yaml", d)
        assert r.returncode == 0, r.stderr


def test_allows_dev_environment_md():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "dev.environment.md")
        r = _run("dev.environment.md", d)
        assert r.returncode == 0, r.stderr


def test_allows_environment_py():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "src/environment.py")
        r = _run("src/environment.py", d)
        assert r.returncode == 0, r.stderr


def test_allows_environment_setup_md():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "docs/environment-setup.md")
        r = _run("docs/environment-setup.md", d)
        assert r.returncode == 0, r.stderr


def test_allows_dir_that_only_shares_git_substring():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "mygit/config")
        r = _run("mygit/config", d)
        assert r.returncode == 0, r.stderr


def test_allows_dir_that_only_shares_migrations_substring():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "notmigrations/foo.sql")
        r = _run("notmigrations/foo.sql", d)
        assert r.returncode == 0, r.stderr


# --- Positive control: the fixed matcher can still block at all ---

def test_positive_control_still_blocks_plain_dotenv():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, ".env")
        r = _run(".env", d)
        assert r.returncode == 2
