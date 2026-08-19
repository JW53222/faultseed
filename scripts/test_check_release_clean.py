#!/usr/bin/env python3
"""Planted-failure tests for check_release_clean.py.

Every test here builds its own throwaway directory tree under `tmp_path`
and calls `check_release_clean.scan(...)` / `.main(...)` directly -- no
subprocess, matching this repo's own scripts/test_check_doc_refs.py and
scripts/test_check_commit_metadata.py convention. Nothing here touches the
network or this repo's real tree.

NO HARDCODED PERSONAL PATHS / KEY SHAPES: this file's own source text must
never contain, as one contiguous literal, anything that check_release_clean's
own SHAPE_CHECKS would flag (a home-directory path, a real email address, a
private-key header, an AWS-shaped key, a bearer token) -- same
release-cleanliness constraint check_release_clean.py documents for
itself, extended here because a fixture that plants one of these shapes
has to spell it out SOMEWHERE, and "somewhere" must not be this file's own
committed source. Every fixture value below that needs to LOOK like one of
these shapes at runtime is assembled via the `_synthetic_*` helpers (string
concatenation), never written as one contiguous literal. Verified directly
by test_this_file_is_clean_under_its_own_scan below -- not just asserted in
prose.

Per this repo's own doctrine (.claude/rules/honesty-guardrails.md, "No
vacuous tests" / CONTRIBUTING.md section 2, "the mutation check"): every
test function below was run against a deliberately broken
check_release_clean.py (a targeted mutation, or an assertion flip) and
observed to fail, then restored, before being counted as done. Per-function
mutation results are recorded in this session's closing report.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_release_clean as crc  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic fixture builders -- see module docstring, "NO HARDCODED...".
# ---------------------------------------------------------------------------

def _synthetic_home_path(user="someuser", tail="project/secret.txt"):
    return "/" + "home" + "/" + user + "/" + tail


def _synthetic_email(local="realperson", domain_head="gmail", domain_tail="com"):
    return local + "@" + domain_head + "." + domain_tail


def _synthetic_aws_key(suffix="IOSFODNN7EXAMPLE"):
    assert len(suffix) == 16
    return "AKIA" + suffix


def _synthetic_private_key_header(keytype="RSA"):
    return "-----BEGIN " + keytype + " PRIVATE" + " KEY-----"


def _synthetic_bearer_token(token="ZXhhbXBsZXRva2VuMTIzNDU2Nzg5MA"):
    return "Bearer" + " " + token


def _write(tmp_path, relpath, content):
    p = tmp_path / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Core contract: planted failure / clean / vacuity (mirrors the origin
# bash test's own case list, ported to this repo's pytest convention).
# ---------------------------------------------------------------------------

def test_planted_extra_term_at_top_level_is_detected_and_names_term_and_file(tmp_path):
    root = tmp_path / "pos1"
    _write(root, "top.txt", "some text with PlantedTermOne inside it\n")
    result = crc.scan(str(root), extra_terms=["PlantedTermOne"])
    assert result.exit_code == crc.EXIT_FOUND
    assert any(h.rule == "PlantedTermOne" and h.path == "top.txt" for h in result.hits)


def test_planted_extra_term_nested_in_subdirectory_is_detected(tmp_path):
    root = tmp_path / "pos2"
    _write(root, "a/b/c/other.txt", "unrelated content\n")
    _write(root, "a/b/c/nested.txt", "buried deep: SecondPlantedTerm right here\n")
    result = crc.scan(str(root), extra_terms=["SecondPlantedTerm"])
    assert result.exit_code == crc.EXIT_FOUND
    hit = next(h for h in result.hits if h.path == "a/b/c/nested.txt")
    assert hit.rule == "SecondPlantedTerm"


def test_planted_extra_term_matches_case_insensitively(tmp_path):
    root = tmp_path / "pos3"
    _write(root, "lower.txt", "oops i typed mixedcaseterm in lowercase\n")
    result = crc.scan(str(root), extra_terms=["MixedCaseTerm"])
    assert result.exit_code == crc.EXIT_FOUND
    hit = next(h for h in result.hits if h.path == "lower.txt")
    # reported as spelled in the terms list, not as it appeared in the file
    assert hit.rule == "MixedCaseTerm"


def test_empty_tree_hits_vacuity_not_a_clean_pass(tmp_path):
    root = tmp_path / "vacuous-empty"
    root.mkdir()
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_VACUOUS
    # main() is what actually prints the "vacuity" wording (scan() itself
    # is silent) -- assert that end-to-end via main(), which is what a
    # real caller sees.
    rc = crc.main([str(root)])
    assert rc == crc.EXIT_VACUOUS


def test_nonexistent_path_is_a_usage_error_not_a_pass(tmp_path):
    missing = tmp_path / "does-not-exist"
    rc = crc.main([str(missing)])
    assert rc == crc.EXIT_USAGE_ERROR


def test_clean_tree_passes(tmp_path):
    root = tmp_path / "clean"
    _write(root, "a.txt", "nothing forbidden in here at all\n")
    _write(root, "sub/b.py", "just ordinary source code\n")
    result = crc.scan(str(root), extra_terms=["PlantedTermOne"])
    assert result.exit_code == crc.EXIT_CLEAN


# ---------------------------------------------------------------------------
# Exception mechanism: scoped, not a blanket; stale entries fail loud;
# malformed entries fail loud.
# ---------------------------------------------------------------------------

def test_hit_on_excepted_only_path_passes_and_reason_is_reported(tmp_path):
    root = tmp_path / "excepted"
    _write(root, "legal/notice.txt", "this file legitimately contains PlantedTermOne by design\n")
    result = crc.scan(str(root), extra_terms=["PlantedTermOne"],
                       exceptions=[("legal/notice.txt",
                                    "Synthetic test fixture: adjudicated as legitimate.")])
    assert result.exit_code == crc.EXIT_CLEAN
    assert result.exceptions[0].live is True
    assert "adjudicated as legitimate" in result.exceptions[0].reason


def test_exception_for_path_a_does_not_excuse_a_hit_at_path_b(tmp_path):
    root = tmp_path / "not-blanket"
    _write(root, "legal/notice.txt", "this file legitimately contains PlantedTermOne by design\n")
    _write(root, "other/leak.txt", "this UNRELATED file also has PlantedTermOne, not excepted\n")
    result = crc.scan(str(root), extra_terms=["PlantedTermOne"],
                       exceptions=[("legal/notice.txt", "adjudicated as legitimate.")])
    assert result.exit_code == crc.EXIT_FOUND
    assert any(h.path == "other/leak.txt" for h in result.hits)
    assert not any(h.path == "legal/notice.txt" for h in result.hits)


def test_stale_exception_fails_the_check(tmp_path):
    root = tmp_path / "stale-check"
    _write(root, "clean.txt", "perfectly clean file\n")
    result = crc.scan(str(root), exceptions=[("this/path/does/not/exist.txt", "never created")])
    assert result.exit_code == crc.EXIT_FOUND
    assert result.stale_exceptions[0].path == "this/path/does/not/exist.txt"


def test_malformed_exception_line_is_a_usage_error(tmp_path):
    root = tmp_path / "malformed-exc"
    _write(root, "clean.txt", "clean file\n")
    exc_file = tmp_path / "exc-bad.txt"
    exc_file.write_text("this-line-has-no-tab-separator\n", encoding="utf-8")
    rc = crc.main([str(root), "--exceptions-file", str(exc_file)])
    assert rc == crc.EXIT_USAGE_ERROR


def test_missing_extra_terms_file_is_usage_error_not_silent_skip(tmp_path):
    root = tmp_path / "missing-terms"
    _write(root, "clean.txt", "clean file\n")
    rc = crc.main([str(root), "--extra-terms-file", str(tmp_path / "does_not_exist.txt")])
    assert rc == crc.EXIT_USAGE_ERROR


# ---------------------------------------------------------------------------
# Tier 1 shape checks -- each planted, each names file + line + rule.
# ---------------------------------------------------------------------------

def test_home_path_shape_is_caught(tmp_path):
    root = tmp_path / "home"
    leaked = _synthetic_home_path()
    _write(root, "notes.txt", f"see {leaked} for the fixture\n")
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_FOUND
    hit = next(h for h in result.hits if h.rule == "home-path")
    assert hit.path == "notes.txt"
    assert leaked in hit.matched


def test_home_path_bracket_placeholder_is_not_caught(tmp_path):
    root = tmp_path / "home-placeholder"
    _write(root, "install.md", "install under /home/<user>/project\n")
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_CLEAN


def test_real_email_shape_is_caught(tmp_path):
    root = tmp_path / "email"
    leaked = _synthetic_email()
    _write(root, "contact.txt", f"reach out at {leaked}\n")
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_FOUND
    hit = next(h for h in result.hits if h.rule == "email-address")
    assert hit.matched == leaked


def test_placeholder_and_noreply_emails_are_not_caught(tmp_path):
    root = tmp_path / "email-placeholder"
    noreply = "1234+someone" + "@users.noreply.github.com"
    _write(root, "docs.md",
           "contact us at team@example.com or file an issue -- bot is "
           f"{noreply}\n")
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_CLEAN


def test_every_placeholder_domain_suffix_is_actually_exempt(tmp_path):
    """Each entry in _PLACEHOLDER_EMAIL_DOMAIN_SUFFIXES must really exempt an
    address under it -- both as a bare domain and with a subdomain.

    The previous test only exercised example.com. That let a suffix-building
    bug ("." + ".invalid" -> "..invalid") leave the five dot-prefixed RFC 2606
    entries permanently dead while the check still reported clean, so
    `tester@example.invalid` in a fixture was flagged as a real leaked
    address. Driving the constant itself means a new entry cannot be added
    without being proven to work.
    """
    for suffix in crc._PLACEHOLDER_EMAIL_DOMAIN_SUFFIXES:
        bare = suffix.lstrip(".")
        for domain in (bare, "example." + bare if "." not in bare else "sub." + bare):
            addr = "someone@" + domain
            assert crc._is_placeholder_email_domain(addr), (
                f"{addr} should be exempt via suffix {suffix!r}"
            )
            assert crc._email_matches(addr) == [], (
                f"{addr} must not be reported as a leaked address"
            )


def test_reserved_tld_address_in_a_fixture_does_not_fail_the_sweep(tmp_path):
    """End-to-end guard for the same defect at the exit-code level.

    A git-config fixture using an RFC 2606 `.invalid` address is the exact
    shape that reddened this repo's own release sweep at v0.1.1 while the
    published surface was clean.
    """
    root = tmp_path / "reserved-tld"
    _write(root, "test_fixture.py",
           '_git(["config", "user.email", "tester@example.invalid"], root)\n')
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_CLEAN, (
        f"reserved-TLD address wrongly flagged: {result.hits}"
    )


def test_a_real_address_is_still_caught_alongside_reserved_tlds(tmp_path):
    """The exemption must not have widened into 'no email is ever a leak'."""
    root = tmp_path / "real-addr"
    # Built by concatenation so this file stays clean under its own scan --
    # same reason the noreply fixture above is spelled that way.
    real = "real.person" + "@" + "gmail.com"
    _write(root, "notes.md", f"ok: tester@example.invalid\nleak: {real}\n")
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_FOUND
    matched = [h.matched for h in result.hits if h.rule == "email-address"]
    assert matched == [real], matched


def test_private_key_header_shape_is_caught(tmp_path):
    root = tmp_path / "pk"
    leaked = _synthetic_private_key_header()
    _write(root, "id_rsa.txt", leaked + "\nMIIEow...\n")
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_FOUND
    hit = next(h for h in result.hits if h.rule == "private-key-header")
    assert hit.path == "id_rsa.txt"


def test_aws_key_shape_is_caught(tmp_path):
    root = tmp_path / "aws"
    leaked = _synthetic_aws_key()
    _write(root, "config.env", f"AWS_ACCESS_KEY_ID={leaked}\n")
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_FOUND
    hit = next(h for h in result.hits if h.rule == "aws-access-key")
    assert hit.matched == leaked


def test_bearer_token_shape_is_caught(tmp_path):
    root = tmp_path / "bearer"
    leaked = _synthetic_bearer_token()
    _write(root, "curl-example.sh", f'curl -H "Authorization: {leaked}"\n')
    result = crc.scan(str(root))
    assert result.exit_code == crc.EXIT_FOUND
    hit = next(h for h in result.hits if h.rule == "bearer-token")
    assert hit.path == "curl-example.sh"


# ---------------------------------------------------------------------------
# Self-config exclusion: a user's own --extra-terms-file / --exceptions-file
# must not flag itself when it happens to sit inside the scanned tree.
# ---------------------------------------------------------------------------

def test_extra_terms_file_inside_build_dir_does_not_flag_itself(tmp_path):
    root = tmp_path / "self-config"
    _write(root, "clean.txt", "nothing here\n")
    terms_file = root / "my-terms.txt"
    terms_file.write_text("MyEmployerName\n", encoding="utf-8")
    result = crc.scan(str(root), extra_terms=["MyEmployerName"],
                       extra_terms_file=str(terms_file))
    # The terms file itself contains "MyEmployerName" by construction --
    # it must be excluded from the scan, not reported as a hit.
    assert not any(h.path == "my-terms.txt" for h in result.hits)
    assert result.exit_code == crc.EXIT_CLEAN


# ---------------------------------------------------------------------------
# Release-cleanliness of this pack's own vendored files.
# ---------------------------------------------------------------------------

def test_this_file_is_clean_under_its_own_scan(tmp_path):
    """check_release_clean.py and this test file must each pass a scan of
    themselves -- proves the "NO HARDCODED..." discipline in both module
    docstrings actually holds, rather than just asserting it in prose."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = tmp_path / "self-scan"
    root.mkdir()
    for name in ("check_release_clean.py", "test_check_release_clean.py"):
        src = os.path.join(here, name)
        with open(src, "r", encoding="utf-8") as f:
            content = f.read()
        (root / name).write_text(content, encoding="utf-8")
    result = crc.scan(str(root))
    assert result.files_scanned == 2
    assert result.hits == [], f"self-scan found hits: {result.hits}"
