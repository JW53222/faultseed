#!/usr/bin/env python3
"""Planted-failure tests for check_commit_metadata.py.

Every test here builds its own throwaway git repo under `tmp_path` (a real
`git init` + real commits with crafted metadata) -- never against this
repo's own history, per this pack's CONTRIBUTING doctrine: construct a
violating input, assert rejection, AND assert the nearest legitimate thing
is allowed. Nothing here touches the network or this repo's real `.git/`.

NO HARDCODED PERSONAL PATHS: this file's own source text must never
contain the literal contiguous substring for a home-directory prefix
either (same release-cleanliness constraint as check_commit_metadata.py
and check_doc_refs.py -- see their docstrings). Fixture content that needs
to LOOK like a hardcoded home path at runtime is assembled via
`_synthetic_home_path()` below (string concatenation), never written as
one contiguous literal.

Per this repo's own doctrine (.claude/rules/honesty-guardrails.md, "No
vacuous tests"): every test function below was deliberately broken (a
targeted mutation to check_commit_metadata.py, or an assertion flip) and
observed to fail, then restored, before being counted as done. The
mutation + observed-RED for each function is recorded in this session's
closing report, not re-derived here at import time (a self-mutating test
suite would be its own hazard).
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_commit_metadata as ccm  # noqa: E402


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def _init_repo(tmp_path, name="repo"):
    """Create a real, empty git repo under tmp_path/<name> with a default
    (noreply-shaped) identity configured, so a test only has to override
    identity for the specific commit it wants to be "leaky". Returns the
    repo root as a str."""
    root = tmp_path / name
    root.mkdir()
    _run(["git", "init", "-q", "-b", "main"], root)
    _run(["git", "config", "user.name", "clean"], root)
    _run(["git", "config", "user.email", "1+clean@users.noreply.github.com"], root)
    return str(root)


def _commit(root, name=None, email=None, message="a commit", body=None, allow_empty=True):
    """Create a commit in `root`. `name`/`email` override BOTH author and
    committer identity for this one commit (via `git -c`, not global
    config) when given, else the repo's configured default (noreply) is
    used for both. Returns the new commit's full hash."""
    full_message = message if body is None else f"{message}\n\n{body}"
    cmd = ["git"]
    if name is not None:
        cmd += ["-c", f"user.name={name}"]
    if email is not None:
        cmd += ["-c", f"user.email={email}"]
    cmd += ["commit", "-q", "-m", full_message]
    if allow_empty:
        cmd.append("--allow-empty")
    _run(cmd, root)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _synthetic_home_path(user="someuser", tail="project/secret.txt"):
    """Build a fake absolute home-directory path at RUNTIME, never as a
    contiguous source-text literal (see module docstring)."""
    return "/" + "home" + "/" + user + "/" + tail


def _hits_by_rule(result, rule):
    return [h for h in result.hits if h.rule == rule]


# ---------------------------------------------------------------------------
# Core contract: personal email caught, in author AND committer, noreply not
# ---------------------------------------------------------------------------

def test_personal_email_in_author_field_is_caught(tmp_path):
    root = _init_repo(tmp_path)
    leaky = _commit(root, name="Real Person", email="real.person@example.com")
    result = ccm.scan(root)
    assert result.exit_code == ccm.EXIT_FOUND
    author_hits = [h for h in result.hits if h.field == "author_email"]
    assert any(
        h.commit == leaky and h.matched == "real.person@example.com"
        and h.rule == "non-noreply-email"  # structured-field rule, not the embedded-text fallback
        for h in author_hits
    )


def test_personal_email_in_committer_field_is_caught(tmp_path):
    # Author is clean (default noreply identity); ONLY the committer field
    # carries a real address -- a rewrite that fixes one field and misses
    # the other is exactly the shape this pack's own incident took.
    root = _init_repo(tmp_path)
    # `-c user.name=`/`-c user.email=` (used elsewhere in this file) sets
    # BOTH author and committer identity together -- to pin author and
    # committer independently in one commit, set GIT_AUTHOR_*/
    # GIT_COMMITTER_* directly via the environment instead.
    env_commit = subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-m", "author clean, committer leaky"],
        cwd=root,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "clean", "GIT_AUTHOR_EMAIL": "1+clean@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "Real Committer", "GIT_COMMITTER_EMAIL": "real.committer@example.com",
        },
        check=True, capture_output=True,
    )
    assert env_commit.returncode == 0
    commit_hash = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()

    result = ccm.scan(root)
    assert result.exit_code == ccm.EXIT_FOUND
    author_hits = [h for h in result.hits if h.field == "author_email"]
    committer_hits = [h for h in result.hits if h.field == "committer_email"]
    assert author_hits == []  # author field genuinely clean -- not a blanket flag on the commit
    assert any(
        h.commit == commit_hash and h.matched == "real.committer@example.com"
        and h.rule == "non-noreply-email"  # structured-field rule, not the embedded-text fallback
        for h in committer_hits
    )


def test_noreply_address_is_not_caught(tmp_path):
    root = _init_repo(tmp_path)
    # Default identity configured by _init_repo is already noreply-shaped;
    # an explicit GitHub-style noreply override for both fields as well,
    # to pin the exact boundary the rule is meant to allow.
    _commit(root, name="Real Person", email="12345+realperson@users.noreply.github.com")
    result = ccm.scan(root)
    assert result.exit_code == ccm.EXIT_CLEAN
    assert result.hits == []


# ---------------------------------------------------------------------------
# The actual escape route: refs/original/... reachable only via `--all`
# ---------------------------------------------------------------------------

def test_commit_reachable_only_via_refs_original_is_caught(tmp_path):
    root = _init_repo(tmp_path)
    leaky = _commit(root, name="Real Leak", email="real.leak@example.com",
                     message="original leaky commit")
    _run(["git", "update-ref", "refs/original/refs/heads/main", leaky], root)
    # Simulate the filter-branch-style rewrite: amend HEAD to a fully clean
    # identity (author AND committer), orphaning the leaky commit so it is
    # reachable ONLY via refs/original/..., not via refs/heads/main.
    _run(
        ["git", "commit", "--amend", "--allow-empty", "--reset-author", "-q",
         "-m", "rewritten clean commit"],
        root,
    )

    # Sanity: prove the escape is real -- a HEAD-only walk sees nothing.
    head_only = subprocess.run(
        ["git", "log", "--format=%H"], cwd=root, check=True, capture_output=True, text=True,
    ).stdout.split()
    assert leaky not in head_only

    result = ccm.scan(root)
    assert result.exit_code == ccm.EXIT_FOUND
    assert any(h.commit == leaky and h.matched == "real.leak@example.com" for h in result.hits)


# ---------------------------------------------------------------------------
# Clean tree / vacuity floor
# ---------------------------------------------------------------------------

def test_clean_repo_passes(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, message="a perfectly ordinary commit")
    _commit(root, message="another one", body="nothing sensitive in this body either")
    result = ccm.scan(root)
    assert result.exit_code == ccm.EXIT_CLEAN
    assert result.hits == []
    assert result.commits_scanned == 2


def test_empty_repo_hits_vacuity_not_clean(tmp_path):
    root = _init_repo(tmp_path)  # git init'd, but zero commits made
    result = ccm.scan(root)
    assert result.commits_scanned == 0
    assert result.exit_code == ccm.EXIT_VACUOUS
    assert result.exit_code != ccm.EXIT_CLEAN


def test_non_git_directory_hits_vacuity(tmp_path):
    plain_dir = tmp_path / "not_a_repo"
    plain_dir.mkdir()
    result = ccm.scan(str(plain_dir))
    assert result.commits_scanned == 0
    assert result.exit_code == ccm.EXIT_VACUOUS


# ---------------------------------------------------------------------------
# Additional coverage: home-path leak, terms-file, CLI usage error, report
# ---------------------------------------------------------------------------

def test_home_path_in_commit_body_is_caught(tmp_path):
    # Backtick-wrapped, this repo's own citation convention -- the closing
    # backtick is in _HOME_TAIL_CHARS's exclusion set, so the match ends
    # exactly at the path (a bare trailing comma/period with no wrapping
    # gets swept into the match instead, same inherited behavior as
    # check_doc_refs.py's identical tail-char class; that's a report-
    # cosmetics nuance, not a missed detection, so it isn't pinned here).
    root = _init_repo(tmp_path)
    leaky_path = _synthetic_home_path(user="jward", tail="TradeSite-unified/secrets.env")
    commit = _commit(root, message="fix build script", body=f"broke on `{leaky_path}`, patched")
    result = ccm.scan(root)
    assert result.exit_code == ccm.EXIT_FOUND
    home_hits = _hits_by_rule(result, "home-path")
    assert any(h.commit == commit and h.matched == leaky_path and h.field == "body" for h in home_hits)


def test_home_path_placeholder_is_not_caught(tmp_path):
    # <user>-bracket placeholder in generic install text must NOT match --
    # pins the same boundary check_doc_refs.py's home-leak check pins.
    root = _init_repo(tmp_path)
    _commit(root, message="docs", body="see /home/<user>/project for an example path")
    result = ccm.scan(root)
    assert result.exit_code == ccm.EXIT_CLEAN
    assert _hits_by_rule(result, "home-path") == []


def test_terms_file_catches_supplied_term_and_absence_catches_nothing(tmp_path):
    root = _init_repo(tmp_path)
    commit = _commit(root, message="mention Project Nightingale internally")
    terms_path = tmp_path / "terms.txt"
    terms_path.write_text("# comment line, ignored\n\nProject Nightingale\n", encoding="utf-8")

    without_terms = ccm.scan(root)
    assert without_terms.exit_code == ccm.EXIT_CLEAN  # no built-in structural rule fires

    with_terms = ccm.scan(root, terms_file=str(terms_path))
    assert with_terms.exit_code == ccm.EXIT_FOUND
    terms_hits = _hits_by_rule(with_terms, "terms-file")
    assert any(h.commit == commit and h.matched == "Project Nightingale" for h in terms_hits)


def test_cli_missing_terms_file_is_usage_error_not_silent_skip(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, message="anything")
    rc = ccm.main(["--root", root, "--terms-file", str(tmp_path / "does_not_exist.txt")])
    assert rc == ccm.EXIT_USAGE_ERROR


def test_report_names_commit_field_and_match(tmp_path):
    root = _init_repo(tmp_path)
    leaky = _commit(root, name="Real Person", email="real.person@example.com")
    result = ccm.scan(root)
    report = ccm._format_report(result)
    assert leaky in report
    assert "author_email" in report
    assert "real.person@example.com" in report
