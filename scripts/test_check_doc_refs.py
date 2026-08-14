#!/usr/bin/env python3
"""Planted-failure tests for check_doc_refs.py.

Every test here builds its own throwaway git repo under `tmp_path` (a real
`git init` + `git add`, since the checker's whole design is "ask git which
files are tracked" -- faking that any other way would test a different
program). Nothing is written outside `tmp_path`; nothing touches the
network. `git` is a hard dependency of the script under test, not an extra
dependency introduced by the tests.

NO HARDCODED PERSONAL PATHS: this file's own source text must never contain
the literal contiguous substring for a home-directory prefix either (same
release-cleanliness constraint as check_doc_refs.py itself -- see its
docstring). Fixture content that needs to LOOK like a hardcoded home path at
runtime is assembled via `_synthetic_home_path()` below (string
concatenation), never written as one contiguous literal.

Per this repo's own doctrine (.claude/rules/honesty-guardrails.md, "No
vacuous tests"): every test function below was deliberately broken (a
targeted mutation to check_doc_refs.py, or an assertion flip) and observed
to fail, then restored, before being counted as done. The mutation +
observed-RED for each function is recorded in this session's closing
report, not re-derived here at import time (a self-mutating test suite
would be its own hazard) -- see the report for the per-function table.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_doc_refs as cdr  # noqa: E402


def _init_repo(tmp_path, files, name="repo"):
    """Create a real git repo under tmp_path/<name>, write `files`
    ({relpath: content}), `git add -A` (no commit unless the test needs
    one). Returns the repo root as a str."""
    root = tmp_path / name
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=root, check=True)
    for relpath, content in files.items():
        p = root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return str(root)


def _cited(result):
    """Every citation the checker extracted and failed to resolve,
    regardless of loud/quiet tier -- the right thing to check for
    extraction/exemption tests, which care about "was this reported at
    all", not which bucket it landed in."""
    return {h.cited for h in result.hits} | {h.cited for h in result.bare_mentions}


def _synthetic_home_path(user="someuser", tail="project/secret.txt"):
    """Build a fake absolute home-directory path at RUNTIME, never as a
    contiguous source-text literal (see module docstring)."""
    return "/" + "home" + "/" + user + "/" + tail


# ---------------------------------------------------------------------------
# Core contract: planted failure / clean / vacuity
# ---------------------------------------------------------------------------

def test_planted_dangling_reference_is_detected(tmp_path):
    root = _init_repo(tmp_path, {
        "doc.md": "See `sub/does_not_exist_anywhere.py` for the mechanism.\n",
    })
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_DANGLING
    assert "sub/does_not_exist_anywhere.py" in {h.cited for h in result.hits}
    hit = next(h for h in result.hits if h.cited == "sub/does_not_exist_anywhere.py")
    assert hit.path == "doc.md"
    assert hit.line == 1


def test_clean_tree_all_citations_resolve(tmp_path):
    root = _init_repo(tmp_path, {
        "doc.md": "See `real_target.py` for the mechanism.\n",
        "real_target.py": "# a real file\n",
    })
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_CLEAN
    assert result.hits == []
    assert result.bare_mentions == []
    assert result.files_scanned == 2


def test_vacuous_non_git_directory(tmp_path):
    # No git init at all -- `git ls-files` fails, must degrade to vacuity,
    # not a crash and not a silent "0 problems" pass.
    plain_dir = tmp_path / "not_a_repo"
    plain_dir.mkdir()
    (plain_dir / "doc.md").write_text("some text\n", encoding="utf-8")
    result = cdr.scan(str(plain_dir))
    assert result.files_scanned == 0
    assert result.exit_code == cdr.EXIT_VACUOUS
    assert result.exit_code != cdr.EXIT_CLEAN


def test_vacuous_git_repo_with_no_scannable_extensions(tmp_path):
    root = _init_repo(tmp_path, {
        "image.png": "not really an image but wrong extension\n",
        "data.bin": "binary-ish\n",
    })
    result = cdr.scan(root)
    assert result.files_scanned == 0
    assert result.exit_code == cdr.EXIT_VACUOUS


# ---------------------------------------------------------------------------
# False-positive exemption mechanisms (docstring §2/§3)
# ---------------------------------------------------------------------------

def test_glob_pattern_citations_not_flagged(tmp_path):
    root = _init_repo(tmp_path, {
        "doc.md": "Matches `test_*.py`, `*_test.go`, and `*_bindata.go`.\n",
    })
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_CLEAN
    assert result.hits == []
    assert result.bare_mentions == []


def test_quoted_example_in_py_docstring_not_flagged(tmp_path):
    # Mirrors the real corpus shape found in this repo's own
    # test_protect_files_env_overmatch.py: a docstring narrating a bug with
    # QUOTED example strings must not be flagged, but a BARE (unquoted)
    # citation in the same docstring must still be caught -- proves the
    # exemption is scoped to the quoted token, not a blanket "ignore this
    # docstring". The genuine citation is slash-qualified so this also
    # doubles as a LOUD-tier check (drives EXIT_DANGLING).
    root = _init_repo(tmp_path, {
        "buggy_matcher.py": (
            '"""Regression test: the matcher used to wrongly pass '
            '"illustrative_example.py" (quoted, a discussion example, not '
            'a real citation). See docs/genuinely_missing_doc.md for the fix.\n'
            '"""\n'
            "x = 1\n"
        ),
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "illustrative_example.py" not in cited
    assert "docs/genuinely_missing_doc.md" in cited
    assert result.exit_code == cdr.EXIT_DANGLING


def test_ordinary_py_string_literal_not_scanned(tmp_path):
    # A plain code string (test-fixture argument, not a comment/docstring)
    # must never be scanned -- mirrors this repo's own
    # test_no_swallowed_errors.py calling _run_write(tmp_path, "src/foo.py", ...).
    # The bare (unquoted) attribute-access expression on the following line
    # isolates region-scoping specifically from the quoted-literal exemption
    # (§3b): it is ordinary CODE, not wrapped in quotes, so only region
    # scoping (comments/docstrings only) keeps it out. The genuine citation
    # is slash-qualified so this also doubles as a LOUD-tier check.
    root = _init_repo(tmp_path, {
        "test_fixture_shape.py": (
            "# see docs/real_comment_target.md for context\n"
            "def test_thing():\n"
            '    path = "totally_fake_fixture_name.py"\n'
            "    totally_fake_bare_code_token.py\n"
            "    assert path\n"
        ),
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "totally_fake_fixture_name.py" not in cited
    assert "totally_fake_bare_code_token.py" not in cited
    assert "docs/real_comment_target.md" in cited
    assert result.exit_code == cdr.EXIT_DANGLING


def test_escape_marker_suppresses_citation(tmp_path):
    # Deliberately BARE citations here (no '/'): proves the escape marker
    # applies BEFORE the loud/quiet split, not just to the loud tier.
    root = _init_repo(tmp_path, {
        "marked.md": "See `phantom_marked.py` for details. doc-ref-ok: acknowledged placeholder\n",
        "unmarked.md": "See `phantom_unmarked.py` for details.\n",
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "phantom_marked.py" not in cited
    assert "phantom_unmarked.py" in cited


def test_markdown_sample_output_fence_not_scanned(tmp_path):
    root = _init_repo(tmp_path, {
        "doc.md": (
            "Example output:\n"
            "```text\n"
            "wrote fake_output_artifact.py\n"
            "```\n"
            "But `docs/real_prose_target.md` is a genuine citation.\n"
        ),
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "fake_output_artifact.py" not in cited
    assert "docs/real_prose_target.md" in cited


def test_generated_artifact_basename_exempted_via_gitignore(tmp_path):
    # settings.json / .claude/settings.json are the real-corpus motivating
    # case: generated by generate_settings_json.py, correctly gitignored,
    # cited constantly and correctly by docs describing the generator. Both
    # the bare form and the slash-qualified form must be fully exempt --
    # not loud, not quiet, not reported at all.
    root = _init_repo(tmp_path, {
        ".gitignore": ".claude/settings.json\n.claude/settings.local.json\n*.pyc\n",
        "doc.md": (
            "Running the generator writes `settings.json`. See also "
            "`.claude/settings.json` and `.claude/settings.local.json`.\n"
        ),
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "settings.json" not in cited
    assert ".claude/settings.json" not in cited
    assert ".claude/settings.local.json" not in cited
    assert result.exit_code == cdr.EXIT_CLEAN


def test_bare_suffix_convention_not_flagged(tmp_path):
    # A bare token starting with '_' or '-' describes a filename SUFFIX
    # rule, not a file -- same family as the glob exemption, for the
    # un-globbed suffix shape this corpus actually uses
    # (no_test_tampering.py: "...recognizing the suffix -- see `_test.go`").
    root = _init_repo(tmp_path, {
        "doc.md": "Go tests are matched by the `_test.go` suffix.\n",
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "_test.go" not in cited
    assert result.exit_code == cdr.EXIT_CLEAN


def test_quoted_citation_with_line_locator_exempted(tmp_path):
    # Regression for a real bug found while tuning: the quote-exemption
    # used to check the character right after the CAPTURED PATH GROUP, not
    # the overall match -- so a quoted citation carrying a ':LINE' locator
    # ("packages/some/file.ts:11") had ':' sitting between the path and the
    # closing quote, and the exemption silently never fired. Found via this
    # checker flagging its own docstring's `"...codec.ts:11"` example.
    root = _init_repo(tmp_path, {
        "doc.py": (
            '"""Discussion of "packages/some/discussed_example.ts:11" as an example.\n'
            '"""\n'
            "x = 1\n"
        ),
    })
    result = cdr.scan(root)
    assert "packages/some/discussed_example.ts" not in _cited(result)


# ---------------------------------------------------------------------------
# Placeholder basenames (docstring §3f) -- worked-example fixture paths
# ---------------------------------------------------------------------------

def test_placeholder_basename_exempted(tmp_path):
    # src/foo.py, other/foo.py, tests/test_foo.py: the exact synthetic
    # fixture names examples/05_no_bash_test_deletion/run.sh and
    # .claude/hooks/PATTERNS.md's own worked examples use -- these are
    # created inside a throwaway mktemp -d, never meant to exist in this
    # repo, so citing them must not be flagged, loud or quiet.
    root = _init_repo(tmp_path, {
        "doc.md": "See `src/foo.py`, `other/foo.py`, and `tests/test_foo.py` for the pattern.\n",
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "src/foo.py" not in cited
    assert "other/foo.py" not in cited
    assert "tests/test_foo.py" not in cited
    assert result.exit_code == cdr.EXIT_CLEAN


def test_non_placeholder_similarly_shaped_citation_still_flagged(tmp_path):
    # A DIFFERENT basename in the same directory shape must NOT be
    # exempted -- the placeholder set matches by exact basename, not "any
    # file under src/" or "anything that looks like a fixture".
    root = _init_repo(tmp_path, {
        "doc.md": "See `src/genuinely_missing_module.py` for the pattern.\n",
    })
    result = cdr.scan(root)
    assert "src/genuinely_missing_module.py" in {h.cited for h in result.hits}
    assert result.exit_code == cdr.EXIT_DANGLING


# ---------------------------------------------------------------------------
# Shell/env variable prefix (docstring §3g)
# ---------------------------------------------------------------------------

def test_shell_variable_prefix_exempted(tmp_path):
    # $HOOKS_HARNESS_ROOT/.claude/hooks/_dispatch.py, verbatim shape from
    # adapters/dsh/bin/smoke-test.sh -- a runtime shell-variable expansion,
    # not a static repo path.
    root = _init_repo(tmp_path, {
        "deploy.sh": 'DISPATCH="$HOOKS_HARNESS_ROOT/.claude/hooks/_dispatch.py"\n',
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert not any("HOOKS_HARNESS_ROOT" in c for c in cited)
    assert result.exit_code == cdr.EXIT_CLEAN


def test_dollar_prefix_lowercase_leading_segment_not_exempted(tmp_path):
    # "$path_var" doesn't look like a conventional shell CONSTANT
    # (lowercase leading segment) -- only genuine ALL-CAPS shell-variable-
    # shaped prefixes are exempted, so this must still be flagged.
    root = _init_repo(tmp_path, {
        "deploy.sh": "echo $path_var/sub/genuinely_broken.py\n",
    })
    result = cdr.scan(root)
    assert "path_var/sub/genuinely_broken.py" in {h.cited for h in result.hits}


# ---------------------------------------------------------------------------
# External-repo declarations (docstring §3h)
# ---------------------------------------------------------------------------

def test_external_repo_declaration_exempts_dsh_citations(tmp_path):
    root = _init_repo(tmp_path, {
        "adapters/dsh/NOTES.md": (
            "See `packages/hooks/hook-protocol/src/fake_example.ts:11` "
            "for the mechanism.\n"
        ),
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "packages/hooks/hook-protocol/src/fake_example.ts" not in cited
    assert result.exit_code == cdr.EXIT_CLEAN


def test_external_repo_declaration_is_scoped_not_global(tmp_path):
    # The SAME declared prefix shape, cited from OUTSIDE adapters/dsh/,
    # must NOT be exempted -- proves the declaration is scoped to `under`,
    # not a global "anything starting with packages/ is fine" rule.
    root = _init_repo(tmp_path, {
        "doc.md": "See `packages/hooks/hook-protocol/src/fake_example.ts` for the mechanism.\n",
    })
    result = cdr.scan(root)
    assert "packages/hooks/hook-protocol/src/fake_example.ts" in {h.cited for h in result.hits}
    assert result.exit_code == cdr.EXIT_DANGLING


def test_external_repo_declaration_does_not_exempt_unlisted_prefixes(tmp_path):
    # A citation INSIDE adapters/dsh/ that does NOT match any declared
    # prefix must still be flagged -- proves the declaration exempts
    # specific prefixes, not "everything in this directory".
    root = _init_repo(tmp_path, {
        "adapters/dsh/NOTES.md": "See `sub/genuinely_broken_local_ref.py` for details.\n",
    })
    result = cdr.scan(root)
    assert "sub/genuinely_broken_local_ref.py" in {h.cited for h in result.hits}
    assert result.exit_code == cdr.EXIT_DANGLING


# ---------------------------------------------------------------------------
# Template placeholders: $VAR, ${VAR}, <bracket> (docstring §3i)
# ---------------------------------------------------------------------------

def test_angle_bracket_template_prefix_exempted(tmp_path):
    # <this-pack>/docs/x.yaml -- the '<...>' prefix is a reader-substituted
    # placeholder, not a literal path. Handled by the SAME '/'-exclusion in
    # _PATH_TOKEN_RE's lookbehind that already stops a match from starting
    # mid-path (a match can never start right after '/', and there is
    # always a '/' between the closing '>' and the real sub-path in this
    # corpus's actual usage) -- no separate bracket-specific mechanism was
    # needed for THIS shape. See test_no_slash_template_prefix_exempted
    # below for the shape that actually needs the '>'/'}' lookbehind
    # exclusion to fire.
    root = _init_repo(tmp_path, {
        "doc.md": "cp <this-pack>/docs/nonexistent_target.yaml <your-repo>/docs/nonexistent_target.yaml\n",
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "docs/nonexistent_target.yaml" not in cited
    assert result.exit_code == cdr.EXIT_CLEAN


def test_curly_brace_template_prefix_exempted(tmp_path):
    # ${CLAUDE_PLUGIN_ROOT}/sub/nonexistent.py -- verbatim shape from
    # adapters/dsh/README.md's substituteCommand discussion. Same as the
    # angle-bracket case above: the '/'-exclusion in the lookbehind already
    # covers this, since there's a '/' between '}' and the real sub-path.
    root = _init_repo(tmp_path, {
        "doc.md": "This substitutes `${CLAUDE_PLUGIN_ROOT}/sub/nonexistent.py` in every command.\n",
    })
    result = cdr.scan(root)
    assert "sub/nonexistent.py" not in _cited(result)
    assert result.exit_code == cdr.EXIT_CLEAN


def test_no_slash_template_prefix_exempted(tmp_path):
    # "${VAR}rest.py" -- NO separating '/' between the closing brace and
    # the rest of the token. This is the shape that actually requires the
    # dedicated '>'/'}' exclusion in _PATH_TOKEN_RE's lookbehind (the
    # pre-existing '/'-exclusion alone does NOT cover it, since there is no
    # '/' immediately before "rest.py" here) -- not observed verbatim in
    # this corpus, but the mechanism must not depend on every template
    # reference happening to include a trailing slash.
    root = _init_repo(tmp_path, {
        "doc.md": "Reads `${SOME_VAR}nonexistent_no_slash.py` directly.\n",
    })
    result = cdr.scan(root)
    assert "nonexistent_no_slash.py" not in _cited(result)
    assert result.exit_code == cdr.EXIT_CLEAN


def test_arrow_notation_with_intervening_prose_not_exempted(tmp_path):
    # "->" followed by prose text (not directly adjacent to the citation)
    # must not exempt an adjacent real citation either -- the citation is
    # preceded by a plain space, not '>'/'}'/'/', so the lookbehind exclusion
    # doesn't apply, and the creating-command check is end-anchored (any
    # non-whitespace text between '->' and the citation defeats it) so it
    # doesn't fire here either. See test_arrow_notation_not_mistaken_for_redirect
    # below for the directly-adjacent '->' case.
    root = _init_repo(tmp_path, {
        "doc.md": "Renamed old/thing.py -> now see sub/genuinely_missing.py in this pass.\n",
    })
    result = cdr.scan(root)
    assert "sub/genuinely_missing.py" in {h.cited for h in result.hits}


# ---------------------------------------------------------------------------
# Creating-command target detection (docstring §3j)
# ---------------------------------------------------------------------------

def test_redirect_target_exempted(tmp_path):
    root = _init_repo(tmp_path, {
        "doc.md": "$ printf 'def x(): pass' > sub/newly_created_by_reader.py\n",
    })
    result = cdr.scan(root)
    assert "sub/newly_created_by_reader.py" not in _cited(result)
    assert result.exit_code == cdr.EXIT_CLEAN


def test_cat_redirect_target_exempted(tmp_path):
    root = _init_repo(tmp_path, {
        "doc.md": "$ mkdir -p tests && cat > tests/newly_created_fixture.py <<'EOF'\n",
    })
    result = cdr.scan(root)
    assert "tests/newly_created_fixture.py" not in _cited(result)


def test_cp_destination_exempted_but_source_still_checked(tmp_path):
    # `cp SRC DEST` -- only DEST is a creating-command target. SRC is an
    # ordinary citation and must still be checked normally (it happens to
    # resolve here because it's declared as a real shipped file, proving
    # the source path is evaluated on its own merits, not blanket-exempted
    # just for sitting on a `cp` line).
    root = _init_repo(tmp_path, {
        "doc.md": "$ mkdir -p docs/notes && cp sub/real_source.py docs/notes/newly_created_dest.py\n",
        "sub/real_source.py": "# real\n",
    })
    result = cdr.scan(root)
    cited = _cited(result)
    assert "docs/notes/newly_created_dest.py" not in cited
    assert "sub/real_source.py" not in cited  # resolves normally, not via the exemption
    assert result.exit_code == cdr.EXIT_CLEAN


def test_bare_greater_than_comparison_not_mistaken_for_redirect(tmp_path):
    # A prose/markdown '>' that is NOT a shell redirect (e.g. a value
    # comparison) must not exempt an adjacent real citation. Text between
    # the '>' and the citation defeats the end-anchored redirect check.
    root = _init_repo(tmp_path, {
        "doc.md": "if latency > 5, see sub/genuinely_missing_doc.md for the runbook.\n",
    })
    result = cdr.scan(root)
    assert "sub/genuinely_missing_doc.md" in {h.cited for h in result.hits}


def test_arrow_notation_not_mistaken_for_redirect(tmp_path):
    # '->' must not be mistaken for a shell '>' redirect -- the '-'
    # immediately before '>' is excluded by the creating-command lookbehind.
    root = _init_repo(tmp_path, {
        "doc.md": "old/thing.py -> sub/genuinely_missing_after_arrow.py\n",
    })
    result = cdr.scan(root)
    assert "sub/genuinely_missing_after_arrow.py" in {h.cited for h in result.hits}


# ---------------------------------------------------------------------------
# Loud vs. quiet split (docstring §5) -- the tuning pass itself
# ---------------------------------------------------------------------------

def test_bare_mention_is_quiet_and_does_not_drive_exit_code(tmp_path):
    # A bare (no '/') unresolved citation -- the MENTION shape
    # (`package-lock.json`-like) -- must still be fully visible in
    # bare_mentions, but must NOT flip the exit code to EXIT_DANGLING.
    root = _init_repo(tmp_path, {
        "doc.md": "Blocks edits to `.env`, `some_bare_mentioned_thing.json`.\n",
    })
    result = cdr.scan(root)
    assert result.hits == []
    assert result.exit_code == cdr.EXIT_CLEAN
    bare_cited = {h.cited for h in result.bare_mentions}
    assert "some_bare_mentioned_thing.json" in bare_cited


def test_regression_slash_qualified_origin_citations_still_flagged_loud(tmp_path):
    # The two exact regression cases named when this tuning pass was
    # requested: both are real dangling citations into the origin codebase
    # this pack was extracted from, and both MUST survive the loud/quiet
    # tuning as LOUD hits (drive EXIT_DANGLING), not get demoted.
    root = _init_repo(tmp_path, {
        "no_type_checking_stub.py": (
            "# MIXIN (`ExecutionMixin` in services/live_evaluator_execution.py),\n"
            "# so this hook must also walk mixin bases.\n"
        ),
        "test_check_interpreter_floor.py": (
            "# run them (docs/harness-install/INSTALL-RUNBOOK.md paragraph 18.14).\n"
        ),
    })
    result = cdr.scan(root)
    loud = {h.cited for h in result.hits}
    assert "services/live_evaluator_execution.py" in loud
    assert "docs/harness-install/INSTALL-RUNBOOK.md" in loud
    assert result.exit_code == cdr.EXIT_DANGLING


# ---------------------------------------------------------------------------
# Resolution rule (docstring §4)
# ---------------------------------------------------------------------------

def test_bare_basename_resolves_anywhere_in_tree(tmp_path):
    root = _init_repo(tmp_path, {
        "doc.md": "See `helper.py` for the shared logic.\n",
        "src/nested/deep/helper.py": "# lives somewhere else entirely\n",
    })
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_CLEAN
    assert result.hits == []
    assert result.bare_mentions == []


def test_slash_path_must_match_exact_directory(tmp_path):
    # Same basename exists, but under the WRONG directory -- a stale
    # directory-prefix citation must be reported, not silently resolved by
    # suffix-matching (this is the "backend/scripts/depq.py" vs
    # "scripts/depq.py" bug class the script exists to catch).
    root = _init_repo(tmp_path, {
        "doc.md": "See `wrong/dir/real.py` for the shared logic.\n",
        "right/dir/real.py": "# the actual location\n",
    })
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_DANGLING
    assert "wrong/dir/real.py" in {h.cited for h in result.hits}


def test_citer_relative_dotdot_path_resolves(tmp_path):
    root = _init_repo(tmp_path, {
        "sub/dir/notes.md": "See `../sibling.py` for the shared helper.\n",
        "sub/sibling.py": "# resolved relative to notes.md's own directory\n",
    })
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_CLEAN
    assert result.hits == []


def test_untracked_not_ignored_file_is_a_valid_resolution_target(tmp_path):
    # "sub/shadow.py" exists on disk and was never `git add`ed -- but it is
    # NOT gitignored, so per docstring §1/§4 ("everything this repo ships",
    # not "everything git has committed") it MUST still count as a real
    # resolution target. This is the exact shape a positive control caught
    # this checker getting wrong with a bare `git ls-files` call: an
    # in-progress, not-yet-committed file is real content, not scratch.
    root = _init_repo(tmp_path, {
        "doc.md": "See `sub/shadow.py` for the shared helper.\n",
    })
    shadow_dir = os.path.join(root, "sub")
    os.makedirs(shadow_dir, exist_ok=True)
    with open(os.path.join(shadow_dir, "shadow.py"), "w", encoding="utf-8") as f:
        f.write("# untracked but real, not yet committed\n")
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_CLEAN
    assert result.hits == []


def test_gitignored_file_is_not_a_valid_resolution_target(tmp_path):
    # A GITIGNORED path is the one kind of "exists on disk" that must NOT
    # resolve a citation -- it is deliberately excluded from what this repo
    # ships (build output, caches, ...), unlike a merely-uncommitted file.
    root = _init_repo(tmp_path, {
        ".gitignore": "ignored/\n",
        "doc.md": "See `ignored/shadow.py` for the shared helper.\n",
    })
    ignored_dir = os.path.join(root, "ignored")
    os.makedirs(ignored_dir, exist_ok=True)
    with open(os.path.join(ignored_dir, "shadow.py"), "w", encoding="utf-8") as f:
        f.write("# deliberately gitignored, must not resolve anything\n")
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_DANGLING
    assert "ignored/shadow.py" in {h.cited for h in result.hits}


def test_untracked_not_ignored_file_is_scanned_for_both_checks(tmp_path):
    # The exact planted-failure case requested: an untracked-but-not-
    # ignored file with a dangling citation, AND one with a home-path leak,
    # must both be caught -- proves the coverage fix (docstring §1) reaches
    # both independent checks, not just the resolution side.
    root = _init_repo(tmp_path, {
        "doc.md": "See `sub/tracked_anchor.py` for context.\n",
        "sub/tracked_anchor.py": "# real, tracked, keeps the repo non-vacuous\n",
    })
    with open(os.path.join(root, "untracked_doc.md"), "w", encoding="utf-8") as f:
        f.write("See `sub/never_added_target.py` for details.\n")
    leaked = _synthetic_home_path(user="ci_regression_user", tail="notes.md")
    with open(os.path.join(root, "untracked_deploy.sh"), "w", encoding="utf-8") as f:
        f.write(f"cp {leaked} /tmp/out\n")
    result = cdr.scan(root)
    assert "sub/never_added_target.py" in {h.cited for h in result.hits}
    assert any(h.path == "untracked_deploy.sh" and h.matched == leaked for h in result.home_leaks)


def test_working_tree_content_used_not_git_head(tmp_path):
    root = _init_repo(tmp_path, {
        "doc.md": "See `pkg/real_target.py` for the shared helper.\n",
        "pkg/real_target.py": "# real\n",
    })
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)
    # Uncommitted edit: doc.md now cites something that doesn't exist.
    # git ls-files still lists doc.md as tracked; the scan must read the
    # CURRENT disk content, not the committed HEAD version.
    with open(os.path.join(root, "doc.md"), "w", encoding="utf-8") as f:
        f.write("See `pkg/newly_broken_reference.py` for the shared helper.\n")
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_DANGLING
    assert "pkg/newly_broken_reference.py" in {h.cited for h in result.hits}
    assert "pkg/real_target.py" not in {h.cited for h in result.hits}


# ---------------------------------------------------------------------------
# Home-directory path leak check (docstring §6) -- separate exit code
# ---------------------------------------------------------------------------

def test_home_path_leak_detected_with_own_exit_code(tmp_path):
    leaked = _synthetic_home_path(user="someuser", tail="project/secret.txt")
    root = _init_repo(tmp_path, {
        "deploy.sh": f"cp {leaked} /tmp/out\n",
    })
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_HOME_PATH_LEAK
    assert result.hits == []  # not folded into the dangling-reference count
    assert len(result.home_leaks) == 1
    leak = result.home_leaks[0]
    assert leak.path == "deploy.sh"
    assert leak.matched == leaked


def test_relative_and_home_variable_paths_not_flagged_as_leaks(tmp_path):
    bracket_placeholder = "/" + "home" + "/<username>/project"
    root = _init_repo(tmp_path, {
        # $HOME, a bracket placeholder, and a plain relative path are all
        # portable -- none of them is a hardcoded personal path.
        "deploy.sh": (
            "cp $HOME/project/secret.txt /tmp/out\n"
            "cp ./relative/secret.txt /tmp/out\n"
        ),
        "README.md": f"Install under {bracket_placeholder}.\n",
    })
    result = cdr.scan(root)
    assert result.home_leaks == []
    assert result.exit_code != cdr.EXIT_HOME_PATH_LEAK


def test_dangling_reference_takes_priority_over_home_leak_in_exit_code(tmp_path):
    # Both defect classes present at once: the combined exit code favors
    # EXIT_DANGLING (preserves the pre-existing meaning of exit 1 for
    # anything already gating on it), but the home leak must still be
    # fully present in the report data, not swallowed by the priority rule.
    leaked = _synthetic_home_path(user="anotheruser", tail="notes.md")
    root = _init_repo(tmp_path, {
        "doc.md": "See `sub/does_not_exist.py` for details.\n",
        "deploy.sh": f"cp {leaked} /tmp/out\n",
    })
    result = cdr.scan(root)
    assert result.exit_code == cdr.EXIT_DANGLING
    assert len(result.hits) == 1
    assert len(result.home_leaks) == 1


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_cli_main_exit_codes_and_output(tmp_path, capsys):
    dangling_root = _init_repo(tmp_path, {
        "doc.md": "See `sub/cli_phantom_target.py` for details.\n",
    })
    rc = cdr.main(["--root", dangling_root])
    out = capsys.readouterr().out
    assert rc == cdr.EXIT_DANGLING
    assert "cli_phantom_target.py" in out

    clean_root = _init_repo(tmp_path, {
        "doc2.md": "See `cli_real_target.py` for details.\n",
        "cli_real_target.py": "# real\n",
    }, name="repo_clean")
    rc = cdr.main(["--root", clean_root])
    out = capsys.readouterr().out
    assert rc == cdr.EXIT_CLEAN
    assert "dangling references" in out
    assert "0 found" in out

    leak_root = _init_repo(tmp_path, {
        "deploy.sh": f"cp {_synthetic_home_path()} /tmp/out\n",
    }, name="repo_leak")
    rc = cdr.main(["--root", leak_root])
    out = capsys.readouterr().out
    assert rc == cdr.EXIT_HOME_PATH_LEAK
    assert "home-directory path leaks" in out

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    rc = cdr.main(["--root", str(empty_dir)])
    err = capsys.readouterr().err
    assert rc == cdr.EXIT_VACUOUS
    assert "VACUOUS" in err
