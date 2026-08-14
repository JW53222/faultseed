#!/usr/bin/env python3
"""check_doc_refs.py -- two independent gates over this repo's tracked text
files:

  (1) DANGLING DOC REFERENCES -- path-like citations that do not resolve to
      a real file in the tree.
  (2) HOME-DIRECTORY PATH LEAKS -- a hardcoded absolute path under a user's
      home directory, which is both a personal-identifier leak in a public
      repo and a portability bug (a path that cannot exist on the reader's
      machine).

These are deliberately reported as two SEPARATE checks with two separate
exit-code tiers (see EXIT CODES below), not folded together: they are
different defects with different fixes, and a reader of the output should
not have to disentangle them.

WHY (1) EXISTS: this repo was extracted from a much larger internal
codebase. Its docs, comments, and config carry citations to files that
never made the cut ("services/live_evaluator_execution.py",
"docs/harness-install/INSTALL-RUNBOOK.md", ...). A reader who follows one of
those goes nowhere. This is a write-time gate against that decaying
silently: every citation is a receipt, and a citation to a file that does
not exist is a receipt that does not exist.

WHY (2) EXISTS: while (1) already walks every text file looking for
path-shaped strings, that same walk cheaply answers a second question --
does any tracked file contain a hardcoded path under a user's home
directory. Same walk, same file set, unrelated defect class, so it lives in
this script rather than a second standalone one, but it is scored and
reported independently.

============================================================================
DESIGN DECISIONS (each one is deliberate -- read before "fixing" a FP/FN)
============================================================================

1. WHICH FILES ARE SCANNED
   `git ls-files --cached --others --exclude-standard` under `--root`
   (default: `.`, the current working directory when this script is
   invoked -- never a hardcoded path; see "NO HARDCODED PERSONAL PATHS"
   below), filtered to SCANNED_EXTS. That is tracked files PLUS untracked
   files that are NOT gitignored -- "everything this repo ships", not
   "everything git has committed". Gitignored paths (`.git/`,
   `__pycache__/`, build output, ...) are excluded either way.
   CORRECTNESS NOTE, found the hard way: an earlier revision used bare
   `git ls-files` (tracked-only) and a positive control caught it silently
   under-scanning -- this exact repo, mid-session, had a small tracked
   core plus roughly fifty more files sitting untracked-but-real
   (README.md, INSTALL.md, docs/guards/, this script's own directory, ...),
   and the bare call reported a clean-looking result over only the tracked
   third of the tree. An in-progress repo -- several agents committing at
   different times, this one included -- has real, working, about-to-be-
   committed content sitting untracked far more often than a finished one;
   scoping either check to tracked-only quietly narrows it to whatever
   fraction of the repo happens to be committed at the moment the script
   runs. DO NOT "simplify" this back to bare `git ls-files` -- that is a
   silent under-sweep, not a simplification, and it was hit twice in one
   session (this exact instance and a `scripts/rename.sh` elsewhere in the
   same tree that found 1 placeholder instead of 59 the same way).
   `result.files_scanned` is printed in every report specifically so a
   human can sanity-check "does that count look like the whole tree" --
   see EXIT CODES below for why zero-files vacuity is a distinct code but
   a merely-INCOMPLETE (nonzero but undercounted) scan is not: that
   failure mode is caught by fixing the file-selection call correctly, not
   by a second exit code trying to detect it after the fact.

   Content is read from the WORKING TREE (current disk state), not `git
   show HEAD` -- an uncommitted in-progress fix should be able to silence a
   finding immediately, without a commit round-trip. A citation MAY now
   resolve against an untracked-but-shipped file too (see §4) -- being
   untracked no longer disqualifies a file from counting, only being
   gitignored does.

   SCANNED_EXTS = .py .md .yaml .yml .sh -- the exact extension set this
   repo actually contains (see `git ls-files | grep -oE '\\.[A-Za-z0-9]+$'
   | sort -u` at design time). Not a generic "looks like text" guess:
   listing extensions explicitly means a new file type is silently NOT
   scanned until someone deliberately adds it here, rather than the
   scanner guessing wrong about binary/generated content. Both checks (1)
   and (2) share this file set -- they differ in what they do with each
   file's text, not in which files they open.

2. DANGLING-REFERENCE EXTRACTION -- REGION SCOPING PER FILE TYPE
   The single biggest false-positive lever on citation EXTRACTION, found
   empirically by reading the corpus before writing the regex:
   - `.py` files: ONLY `#` comments (via `tokenize`) and REAL docstrings
     (via `ast` -- the first statement of a module/class/function body,
     when it is a bare string constant). Plain string literals elsewhere
     in the code are NOT scanned -- this repo's own tests are full of
     string literals that look like citations but are test-fixture data
     (`_run_write(tmp_path, "src/foo.py", content)`) or operational data
     (a `frozenset({"transcript_context_scan.py", ...})` of real-but-
     unshipped hook names). Comments and docstrings are where this repo's
     authors write "see X for the mechanism"; everywhere else is program
     data.
   - `.md` / `.yaml` / `.yml` / `.sh` files: the entire file (no code-vs-
     data split to make there).
   - `.md` fenced code blocks tagged as SAMPLE_OUTPUT_LANGS (text,
     console, output, log, bash-output) are skipped -- those blocks show
     what a command PRINTS, not files to cite. An untagged fence or a
     real-language one is still scanned (this repo's one real fenced
     block, README.md's file listing, is untagged and genuine).

3. DANGLING-REFERENCE EXTRACTION -- PER-TOKEN EXEMPTIONS (applied in this
   order, after a token is extracted)
   a. GLOB/WILDCARD: a match immediately preceded by `*`, `?`, `[`, or `]`
      is a shell/regex PATTERN, not a citation (`test_*.py`, `*_test.go`).
   b. QUOTED LITERAL: a match immediately wrapped in a matching pair of
      `"`/`'` is an example STRING under discussion, not a citation --
      found empirically in test_protect_files_env_overmatch.py's own
      docstring narrating a bug with quoted examples ("src/environment.py",
      "package-lock.json", none real, none meant to be). Backtick-wrapped
      citations are NOT exempted (backticks are this repo's own citation
      convention).
   c. ESCAPE MARKER: a line containing `doc-ref-ok: <reason>` (reason
      required, mirrors `# swallow-ok:` / `# tampering-ok:` in
      .claude/rules/honesty-guardrails.md) suppresses every citation on
      that line. Not currently used anywhere in this repo; a deliberate,
      auditable override for a case the heuristics below get wrong.
   d. GENERATED ARTIFACT: a citation whose BASENAME matches a name this
      repo's own `.gitignore` marks as generated-and-never-committed is
      dropped entirely, from either the loud or quiet bucket (see §5).
      Derived DYNAMICALLY from `.gitignore`'s literal (non-glob) lines --
      not a hand-maintained list, so it cannot drift from the
      authoritative source. Today that resolves to exactly
      `{"settings.json", "settings.local.json"}` (from
      `.claude/settings.json` / `.claude/settings.local.json`), which
      `generate_settings_json.py`'s own docstring names as its output --
      citing that filename is correct and useful, not dangling, because
      the file legitimately does not exist until a user runs the
      generator. A glob/negation `.gitignore` line (contains `* ? [ ] !`)
      is skipped as a source for this set -- it says nothing about one
      SPECIFIC filename citation being legitimate.
   e. SUFFIX CONVENTION: a BARE (no `/`) token that starts with `_` or `-`
      (e.g. `_test.go`, `_bindata.go`) is a filename-SUFFIX rule being
      described, not a file -- same family as the glob exemption in (a),
      extended to the un-globbed suffix shape this corpus actually uses
      (`no_test_tampering.py`: "gated on... recognizing the suffix --
      see... `_test.go`"). Only applies when there is no `/`: a
      slash-qualified path ending in a `_`/`-`-prefixed basename (rare,
      not observed in this corpus) is still a real citation candidate.
   f. PLACEHOLDER BASENAME (`PLACEHOLDER_BASENAMES`): a citation whose
      BASENAME is a canonical synthetic-fixture name is dropped entirely
      (loud or quiet), matched by basename so `src/foo.py`, `other/foo.py`,
      and bare `foo.py` are one entry. Found empirically, not guessed:
      `examples/05_no_bash_test_deletion/run.sh` and
      `examples/06_no_bash_test_mutation/run.sh` each spawn a `mktemp -d`
      fixture, `touch`/`echo >` these exact names into it, then feed a
      synthetic `{"tool_input": {"command": "rm tests/test_foo.py"}}`-shaped
      JSON payload to the real hook to prove it fires -- "does
      `tests/test_foo.py` exist in THIS repo" is the wrong question for a
      path that only ever exists inside that example's own throwaway
      `mktemp -d` directory. `.claude/hooks/PATTERNS.md`'s worked-example
      bullets (`src/foo.py` blocked, `other/foo.py` allowed) and
      `docs/guards/no_bash_test_mutation.md`'s matching prose use the exact
      same small vocabulary. This is a NAMED, SMALL, STABLE set (not a
      per-citation escape hatch) -- adding a future worked example that
      reuses `foo.py`/`bar.py`/`test_foo.py` costs nothing here; a genuinely
      new placeholder name would need a deliberate addition to this set,
      which is exactly the auditability a silent heuristic would not have.
   g. SHELL/ENV VARIABLE PREFIX: a token immediately preceded by a literal
      `$` whose leading path segment looks like a conventional shell
      constant (`^[A-Z][A-Z0-9_]*$` -- `$FIXTURE/tests/test_foo.py`,
      `$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py`,
      `$HOOKS_DIR/no_bash_test_deletion.py`, all found verbatim in
      `examples/05_no_bash_test_deletion/run.sh` and
      `adapters/dsh/bin/smoke-test.sh`) is a RUNTIME expansion, not a
      static repo path, and is dropped entirely. Deliberately NOT resolved
      by stripping the variable and re-checking the remainder: this script
      cannot know statically whether a given shell constant points at this
      repo's own root (`$CLAUDE_PROJECT_DIR`, where the remainder plausibly
      SHOULD resolve) or an ephemeral `mktemp -d` fixture root (`$FIXTURE`,
      where it structurally never will) -- guessing which is which per
      variable name would be exactly the kind of unaudited heuristic this
      script avoids elsewhere. Treating every `$VAR/...` token as equally
      unknowable is the conservative, honest answer: it never produces a
      false PASS by mis-resolving a remainder, only an intentional
      "not statically checkable, not reported".
   h. EXTERNAL-REPO DECLARATION (`EXTERNAL_REPOS`): a citation found in a
      file under a declared `under` directory, whose path starts with one
      of that declaration's `prefixes`, is a deliberate citation into
      ANOTHER project's own source tree -- not a broken local link but the
      opposite, a maintainer's re-verification receipt (`adapters/dsh/NOTES.md`:
      "records every dsh source file:line relied on... what a future
      maintainer must re-check when dsh changes"). `adapters/dsh/` alone
      carries roughly 55 of these into `deepseek-ai/deepseek-harness`
      ("packages/hooks/hook-protocol/src/codec.ts:11" and friends) --
      marking each individually would be both unmaintainable and would hide
      the pattern from a reader of this file; ONE declaration (directory +
      repo name + prefix list) covers all of them and is itself the
      documentation of why they're exempt. Kept as an in-script constant
      rather than a separate config file or per-file markers because this
      script's own edit authority is scoped to exactly two files
      (scripts/check_doc_refs.py, scripts/test_check_doc_refs.py) -- a
      follow-up could externalize `EXTERNAL_REPOS` into a small config file
      without changing the mechanism, if a team wants declarations added
      without touching this script.
   i. TEMPLATE-BRACKET PREFIX: `_PATH_TOKEN_RE`'s lookbehind excludes `>`
      and `}` (the closing halves of a `<placeholder>` or
      `${VAR}`/`{{VAR}}` template token) alongside its pre-existing `/`
      exclusion, so a match can never start immediately after either --
      `<this-pack>/docs/x.yaml` and `${CLAUDE_PLUGIN_ROOT}/rest.py` are
      refused the same way `/`-preceded starts always were (there's
      already a `/` right after the closing bracket in every real
      occurrence in this corpus, so the pre-existing `/` exclusion alone
      would already catch those two specific examples -- adding `>`/`}`
      to the SAME set is what additionally covers a bracket immediately
      followed by NO separating `/` (`${VAR}rest.py`), which the
      `/`-exclusion alone cannot reach). An earlier revision of this
      mechanism was a separate, parallel post-hoc check (walk backward
      from the match, strip trailing `/`, check for a trailing `>`/`}`)
      -- removed after mutation-testing it and discovering the check
      never actually fired on any real or planted fixture: the
      pre-existing `/` exclusion silently did all the work first, every
      time, for every shape this corpus actually contains. Keeping dead
      code that merely resembled a working exemption would have been
      exactly the "looks installed, enforces nothing" shape this repo's
      own guards exist to catch elsewhere. Folding the two closing-bracket
      characters into the SAME lookbehind the `/` exclusion already lives
      in is the version that is both correct (covers the no-slash case
      too) and honest (one exclusion set, doing visibly one job).
   j. CREATING-COMMAND TARGET (`_CREATING_COMMAND_TAIL_RE`): a citation is
      the TARGET of a file-creating shell command -- a redirect (`>`/`>>`,
      excluding fd-redirects like `2>`/`&>` and `->`/`→`-style arrows via
      an explicit lookbehind), `cat >`/`cat >>`, or the destination
      argument of `cp SRC DEST` -- when the text between the start of the
      line and this citation, with only whitespace/quotes in between, ends
      in one of those shapes. Found empirically:
      `examples/05_no_bash_test_deletion/run.sh` /
      `examples/06_no_bash_test_mutation/run.sh` (`> $FIXTURE/...`,
      `cat > tests/test_foo.py <<'EOF'`) and INSTALL.md's PROVE-IT
      walkthrough (`printf ... > src/foo.py`,
      `cp src/foo.py docs/notes/foo.py`). This generalizes past
      `PLACEHOLDER_BASENAMES` (§3f) on purpose: a NEW worked example that
      creates-then-cites a filename not yet in that curated set is still
      caught structurally, without needing the set edited. The two
      mechanisms are complementary, not redundant --
      `PLACEHOLDER_BASENAMES` also catches a bare MENTION of a known
      fixture name with no creating command nearby in the same file
      (e.g. a table row referencing `tests/test_foo.py` in prose).

   KNOWN RESIDUAL FALSE-POSITIVE CATEGORY (not suppressed, by design): a
   well-known ecosystem convention name (real occurrences in this corpus
   are backtick-wrapped, e.g. `conftest.py`, `package-lock.json`,
   `requirements.txt` -- quoted here instead, purely so this docstring's
   own illustrative use of them doesn't itself become a false positive,
   per §3b) mentioned bare with no quotes/glob/suffix marker still
   surfaces -- but see §5: as of
   this revision it lands in the QUIET bucket, not the exit-code-triggering
   one, specifically because it is bare. Distinguishing "generic tool name"
   from "real citation" by content alone would require guessing; the quiet
   bucket is the answer instead of a guess.

4. RESOLUTION RULE
   Resolution targets are every SHIPPED path per §1 (tracked + untracked-
   not-gitignored) -- a citation to a real, about-to-be-committed file
   resolves exactly like a citation to a tracked one; a citation to a
   gitignored path, or to nothing at all, does not.
   - A citation containing `/` must resolve to an EXACT shipped path,
     either repo-root-relative, or (fallback, `../`-style relative doc
     links) relative to the CITING file's own directory. No suffix/
     basename fallback: "backend/scripts/depq.py" when the real file is at
     "scripts/depq.py" is exactly the "stale directory prefix" bug class
     this script exists to catch, and suffix-matching would paper over it.
   - A citation with NO `/` (a bare basename) resolves if ANY shipped file
     in the whole tree has that exact basename -- this corpus overwhelmingly
     cites hooks/docs by bare name (PATTERNS.md headers every hook `##
     <bare-filename>.py`).

5. LOUD VS. QUIET -- WHAT ACTUALLY DRIVES THE DANGLING EXIT CODE
   Tuned after a first pass on the real tree came back with 152 hits, most
   of which turned out not to be citations at all but MENTIONS -- a
   filename named as the SUBJECT of a sentence, e.g. a doc saying it
   "blocks edits to .env, package-lock.json" -- rather than a pointer
   telling the reader to go open it (see "docs/x.md"). The signal used to
   tell them apart:
   whether the citation contains a `/`. A real "go read this" citation in
   this corpus is overwhelmingly either directory-qualified
   ("docs/harness-install/INSTALL-RUNBOOK.md",
   "services/live_evaluator_execution.py") or a bare hook/doc name that is
   this repo's own well-established convention (PATTERNS.md's `##
   <name>.py` headers); a bare MENTION of a well-known external filename
   never carries a directory. So:
     - `hits` (LOUD, drives EXIT_DANGLING): unresolved citations containing
       `/`. This is what the exit code and "N dangling reference(s) found"
       count are about.
     - `bare_mentions` (QUIET, informational only): unresolved citations
       with no `/`. Still fully listed in the report and the worklist --
       nothing is silently dropped -- but does not change the exit code.
       This is where `conftest.py`/`package-lock.json`-shaped residual FPs
       land, without losing the ability to catch a genuinely dangling bare
       citation (a human still sees it, just not gated on it).
   A simpler alternative considered (require citation-shaped CONTEXT: inside
   backticks AND has a `/`, or preceded by "see"/"at"/"in") was rejected in
   favor of the `/`-only rule for its determinism -- a proximity-to-keyword
   heuristic is exactly the kind of fragile, context-sensitive judgment this
   whole tool exists to avoid needing elsewhere. The `/`-only rule is
   auditable from the token alone, with no adjacent-word lookup.
   REGRESSION GUARANTEE: both "services/live_evaluator_execution.py" and
   "docs/harness-install/INSTALL-RUNBOOK.md" (real dangling citations to the
   origin codebase, both `/`-qualified) still land in `hits`, not
   `bare_mentions` -- see the fixture tests
   `test_regression_slash_qualified_origin_citation_still_flagged_loud`.

6. HOME-DIRECTORY PATH LEAK CHECK -- separate mechanism, separate exit code
   Scans the RAW text of every file in the same SCANNED_EXTS set (no
   region-scoping, no quote exemption) for an absolute path starting with
   one of three home-directory prefixes (built via string concatenation in
   this file -- see "NO HARDCODED PERSONAL PATHS" below): the multi-user
   Linux prefix, the macOS prefix, and the single-user Linux root-home
   path. Full raw text, unlike the dangling-reference check's region
   scoping, because the hazard here is a hardcoded path used AS CODE (a
   shell command, a Python constant) just as much as one merely mentioned
   in prose -- quoting does not make a hardcoded personal path fine the way
   it makes an illustrative example fine, so the quoted-literal exemption
   from §3b does NOT apply here.
   MATCH SHAPE: the prefix followed by one or more characters that are not
   whitespace, a quote/backtick, a closing paren/bracket, `<`/`>`, `$`, or
   `{`/`}`. The exclusions matter: `<user>`/`{username}`-style bracket
   placeholders and `$USER`-style shell-variable placeholders in generic
   installation instructions are portable by construction (they contain no
   actual personal path), so they never even start a match -- the very
   first character after the prefix already fails the character class.
   `$HOME` itself never matches anything: it does not begin with one of the
   three literal prefixes at all.
   KNOWN LIMITS: the macOS prefix could in principle collide with a REST
   API path segment that happens to use the same word (e.g. an endpoint
   documented as a path under that word) -- not observed anywhere in this
   corpus, called out here rather than silently risked. `https://`/`ssh://`
   URLs are stripped before matching (the same `_strip_urls_and_remotes`
   preprocessing (1) uses) so a remote path segment that happens to look
   like a home directory is not mistaken for a local one.

NO HARDCODED PERSONAL PATHS IN THIS FILE (release-cleanliness constraint):
this script's own source text must never contain the literal contiguous
substring it searches for in (2) -- a script whose job is finding
hardcoded personal paths must not itself get flagged by the same sweep for
containing one. `_HOME_PREFIX` / `_USERS_PREFIX` / `_ROOT_PREFIX` below are
therefore assembled via string concatenation from separately-quoted
fragments, never spelled out as one contiguous literal, anywhere in this
file (including this docstring). Verify with `grep -rn` for the three
prefixes over this file returning nothing.

Usage: python3 check_doc_refs.py [--root PATH]
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import re
import subprocess
import sys
import tokenize
from dataclasses import dataclass, field

EXIT_CLEAN = 0
EXIT_DANGLING = 1
EXIT_HOME_PATH_LEAK = 2
EXIT_VACUOUS = 3

SCANNED_EXTS = {".py", ".md", ".yaml", ".yml", ".sh"}

# Extensions that make a bare token "path-like" enough to be a citation
# candidate at all. Deliberately broader than SCANNED_EXTS -- a .md file in
# THIS repo can legitimately cite a .go or .json file even though this repo
# doesn't itself carry any tracked .go/.json files to scan.
_CITED_EXT_ALT = (
    r"(?:py|md|ya?ml|sh|json|txt|rst|cfg|toml|ini|ps1|go|js|ts|tsx)"
)

# A path-like token: one or more '/'-joined segments (letters, digits, '_',
# '.', '-'), the last segment ending in a recognized extension, optionally
# followed by a ':LINE' or ':LINE-LINE' locator (stripped before
# resolution). The lookbehind refuses to start a match right after a glob
# wildcard character, a word character, '.', '/', or '-' -- the first three
# stop `*_test.go`/`test_*.py` fragments (see docstring §3a), the last two
# stop the regex from starting mid-token.
_PATH_TOKEN_RE = re.compile(
    # ">" and "}" (the closing halves of a "<placeholder>" or
    # "${VAR}"/"{{VAR}}" template token, see docstring §3i) are excluded
    # here too, alongside the pre-existing glob/word/./'/'-' exclusions --
    # a match can never start immediately after one.
    r"(?<![\w./*?\[\]>}-])"
    # Trailing basename must END in an alnum/underscore right before the
    # extension dot (not '-' or '.') -- rules out prose like "non-.py files"
    # matching a bogus "non-.py" token.
    r"((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]*[A-Za-z0-9_]\." + _CITED_EXT_ALT + r")"
    r"(?::\d+(?:-\d+)?)?"
    r"(?![\w/-])"
)

_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")
_SCP_REMOTE_RE = re.compile(r"\b[\w.-]+@[\w.-]+:\S+")

_ESCAPE_MARKER_RE = re.compile(r"doc-ref-ok:\s*\S")

# A path-token immediately preceded by a literal '$' whose leading segment
# looks like a conventional shell/env variable name ($FIXTURE/tests/...,
# $CLAUDE_PROJECT_DIR/.claude/..., $HOOKS_DIR/no_bash_test_deletion.py) is a
# runtime expansion, not a static repo path -- see docstring §3g.
_SHELL_VAR_LEADING_SEGMENT_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Canonical placeholder basenames -- see docstring §3f.
PLACEHOLDER_BASENAMES = frozenset({
    "foo.py", "bar.py", "baz.py",
    "test_foo.py", "test_example.py", "bar_test.go",
    "notes.txt", "scratch.txt",
    "payload.py",
    "environment.py", "config.envoy.yaml", "dev.environment.md",
})

# External-repo declarations -- see docstring §3h.
EXTERNAL_REPOS = (
    {
        "under": "adapters/dsh/",
        "repo": "deepseek-ai/deepseek-harness",
        "prefixes": ("packages/", "dsh-scan/", "docs/user/", "examples/acp-agent/", "apps/"),
    },
)

# A line matching one of these, with only whitespace/quotes between the end
# of the match and the citation, means the citation is the TARGET of a
# file-creating command (redirect, `cat >`, or `cp SRC <dest>`) -- a
# runtime fixture the reader's own command brings into existence, not a
# citation to something that should already be in the tree. See docstring
# §3j. The `(?<![0-9&-])` lookbehind on the redirect operator excludes
# fd-redirects (`2>`, `&>`) and `->`/`→`-style arrows (common in this
# corpus's rename/transform notation) from being mistaken for a shell
# redirect.
_CREATING_COMMAND_TAIL_RE = re.compile(
    r"(?:"
    r"(?<![0-9&-])>>?\s*['\"]?"       # '>' / '>>' redirect
    r"|cat\s+>>?\s*['\"]?"              # `cat >` / `cat >>`
    r"|cp\s+\S+\s+"                      # `cp SRC ` -- next token is the dest
    r")$"
)

_FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)(\S*)\s*$")

# Fenced-code languages that conventionally show command OUTPUT / sample
# data, not real repo paths worth citation-checking. See docstring §2.
_SAMPLE_OUTPUT_LANGS = {"text", "console", "output", "log", "bash-output"}

# --- home-directory path prefixes -- see "NO HARDCODED PERSONAL PATHS" ---
# Each is built from separately-quoted fragments so this file's own source
# text never contains the contiguous substring being searched for.
_SLASH = "/"
_HOME_PREFIX = _SLASH + "home" + _SLASH        # multi-user Linux
_USERS_PREFIX = _SLASH + "Users" + _SLASH      # macOS
_ROOT_PREFIX = _SLASH + "root"                 # single-user Linux root home

# Characters that may NOT immediately follow a home-prefix for the match to
# continue: whitespace, quote/backtick, closing paren/bracket, angle
# brackets, '$', and curly braces -- this is what makes a placeholder like
# a bracketed username or a shell variable fail to match at all (the first
# required character after the prefix already isn't in the allowed set).
# See docstring §6.
_HOME_TAIL_CHARS = r"[^\s\"'`)\]<>${}]"
_HOME_PATH_RE = re.compile(
    r"(?<![\w./-])("
    + re.escape(_HOME_PREFIX) + _HOME_TAIL_CHARS + r"+"
    + r"|" + re.escape(_USERS_PREFIX) + _HOME_TAIL_CHARS + r"+"
    + r"|" + re.escape(_ROOT_PREFIX) + r"(?:" + re.escape(_SLASH) + _HOME_TAIL_CHARS + r"*)?"
    + r")"
)


@dataclass
class Hit:
    path: str  # citing file, root-relative, posix
    line: int
    cited: str  # the resolved (locator-stripped) citation token
    text: str  # the full source line, stripped


@dataclass
class HomeLeak:
    path: str
    line: int
    matched: str
    text: str


@dataclass
class ScanResult:
    files_scanned: int = 0
    hits: list = field(default_factory=list)           # LOUD: '/'-qualified, unresolved
    bare_mentions: list = field(default_factory=list)   # QUIET: bare, unresolved
    home_leaks: list = field(default_factory=list)      # separate defect class

    @property
    def exit_code(self):
        if self.files_scanned == 0:
            return EXIT_VACUOUS
        if self.hits:
            return EXIT_DANGLING
        if self.home_leaks:
            return EXIT_HOME_PATH_LEAK
        return EXIT_CLEAN


def _posix(p):
    return p.replace(os.sep, "/")


def _git_ls_files(root):
    """Repo-relative, posix-separated paths of every file this repo SHIPS:
    tracked files PLUS untracked files that are not gitignored (`--cached
    --others --exclude-standard`). Empty list (never raises) if `root`
    isn't a git work tree at all -- that degrades cleanly into the vacuity
    exit code rather than a crash.

    DO NOT use bare `git ls-files` here (tracked-only) -- found the hard
    way: a repo with uncommitted-but-real work in progress (this exact repo,
    mid-session, had ~28 tracked files and roughly fifty more sitting
    untracked-but-not-ignored: README.md, INSTALL.md, docs/guards/,
    examples/, this very script's own directory) silently scanned only the
    tracked third and reported a clean/complete-looking result over what
    was actually a partial tree. Bare `git ls-files` undercounting an
    uncommitted-but-real tree is not a one-off either -- the same call
    undercounted a rename sweep elsewhere in this same session (found 1
    placeholder instead of 59). `--exclude-standard` is what keeps this
    from also picking up `.git/`, `__pycache__/`, and anything else
    `.gitignore` legitimately excludes -- the semantic wanted is "files
    this repo ships", not "every byte on disk under root"."""
    try:
        proc = subprocess.run(
            ["git", "-C", root, "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [_posix(line) for line in proc.stdout.splitlines() if line.strip()]


def _strip_urls_and_remotes(line):
    line = _URL_RE.sub(" ", line)
    line = _SCP_REMOTE_RE.sub(" ", line)
    return line


def _load_generated_artifact_basenames(root):
    """Basenames this repo's own `.gitignore` marks as generated-and-never-
    committed (see docstring §3d). Only LITERAL (non-glob, non-negation)
    `.gitignore` lines are used -- a glob line says nothing about one
    specific filename citation being legitimate. Derived dynamically so
    this can never drift out of sync with the authoritative source."""
    names = set()
    try:
        with open(os.path.join(root, ".gitignore"), "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except OSError:
        return names
    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if any(ch in line for ch in "*?[]!"):
            continue  # glob/negation pattern, not a literal path
        names.add(line.rstrip("/").rsplit("/", 1)[-1])
    return names


def _py_scan_regions(text):
    """Return {lineno: [snippet, ...]} restricted to `#` comment text
    (via tokenize) and real AST-verified docstring bodies. See docstring
    §2 for why plain string literals are excluded."""
    regions: dict = {}
    lines = text.splitlines()

    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                regions.setdefault(tok.start[0], []).append(tok.string)
    except (tokenize.TokenizeError, IndentationError, SyntaxError, ValueError):
        pass

    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None
    if tree is not None:
        nodes = [tree] + [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        for node in nodes:
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                start = first.value.lineno
                end = getattr(first.value, "end_lineno", start)
                for ln in range(start, end + 1):
                    if 1 <= ln <= len(lines):
                        regions.setdefault(ln, []).append(lines[ln - 1])

    return regions


def _md_fenced_skip_lines(text):
    """Return the set of 1-based line numbers inside a markdown fenced code
    block whose info-string is a SAMPLE_OUTPUT_LANGS tag."""
    skip = set()
    in_fence = False
    fence_marker = None
    is_sample = False
    for i, line in enumerate(text.splitlines(), start=1):
        m = _FENCE_RE.match(line)
        if m and not in_fence:
            in_fence = True
            fence_marker = m.group(2)[0]
            lang = m.group(3).strip().lower()
            is_sample = lang in _SAMPLE_OUTPUT_LANGS
            if is_sample:
                skip.add(i)
            continue
        if m and in_fence and m.group(2)[0] == fence_marker:
            in_fence = False
            if is_sample:
                skip.add(i)
            is_sample = False
            continue
        if in_fence and is_sample:
            skip.add(i)
    return skip


def _extract_hits_from_line(line, lineno, citing_path):
    """Yield (lineno, cited_token, line_text) for every non-exempt citation
    candidate found in `line`."""
    if _ESCAPE_MARKER_RE.search(line):
        return
    clean = _strip_urls_and_remotes(line)
    for m in _PATH_TOKEN_RE.finditer(clean):
        # `end` uses the OVERALL match end (m.end(0)), not just the
        # captured path group (m.end(1)) -- a quoted citation carrying a
        # ':LINE' locator ("packages/.../codec.ts:11") has the locator
        # BETWEEN the path and the closing quote; checking only right after
        # the path group would look at ':' instead of the quote and miss
        # the exemption entirely. The reported token itself still comes
        # from group(1), locator-free.
        start, end = m.start(1), m.end(0)
        before = clean[start - 1] if start > 0 else ""
        after = clean[end] if end < len(clean) else ""
        if before in ("'", '"') and before == after:
            continue  # quoted literal -- see docstring §3b
        if before == "$":
            leading = m.group(1).split("/", 1)[0]
            if _SHELL_VAR_LEADING_SEGMENT_RE.match(leading):
                continue  # shell/env variable expansion -- see docstring §3g
        prefix_text = clean[:start]
        if _CREATING_COMMAND_TAIL_RE.search(prefix_text):
            continue  # target of a file-creating command -- see docstring §3j
        yield lineno, m.group(1), line.strip()


def _external_repo_declaration(citing_path, cited):
    """Return the matching EXTERNAL_REPOS declaration if `cited` (found in
    `citing_path`) is a citation into a declared external repo, else None.
    See docstring §3h."""
    for decl in EXTERNAL_REPOS:
        if citing_path.startswith(decl["under"]) and cited.startswith(decl["prefixes"]):
            return decl
    return None


def _iter_citations(path, root):
    """Yield (lineno, cited_token, line_text) for every citation candidate
    in the tracked file `path` (root-relative posix), scoped per §2."""
    text = _read_text(path, root)
    if text is None:
        return

    ext = os.path.splitext(path)[1].lower()

    if ext == ".py":
        regions = _py_scan_regions(text)
        for lineno, snippets in regions.items():
            for snippet in snippets:
                yield from _extract_hits_from_line(snippet, lineno, path)
        return

    lines = text.splitlines()
    skip_lines = _md_fenced_skip_lines(text) if ext == ".md" else set()
    for i, line in enumerate(lines, start=1):
        if i in skip_lines:
            continue
        yield from _extract_hits_from_line(line, i, path)


def _read_text(path, root):
    abs_path = os.path.join(root, path)
    if not os.path.isfile(abs_path):
        return None
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _scan_home_path_leaks(scannable, root):
    """Full raw-text scan (no region scoping, no quote exemption -- see
    docstring §6) of every scannable file for a hardcoded home-directory
    path."""
    hits = []
    for path in scannable:
        text = _read_text(path, root)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            clean = _strip_urls_and_remotes(line)
            for m in _HOME_PATH_RE.finditer(clean):
                hits.append(HomeLeak(path=path, line=i, matched=m.group(1), text=line.strip()))
    hits.sort(key=lambda h: (h.path, h.line, h.matched))
    return hits


def scan(root):
    root = os.path.abspath(root)
    shipped = _git_ls_files(root)  # tracked + untracked-not-ignored -- see _git_ls_files
    scannable = [p for p in shipped if os.path.splitext(p)[1].lower() in SCANNED_EXTS]

    result = ScanResult(files_scanned=len(scannable))
    if not scannable:
        return result

    all_shipped = set(shipped)
    basenames: dict = {}
    for p in shipped:
        basenames.setdefault(p.rsplit("/", 1)[-1], []).append(p)
    generated = _load_generated_artifact_basenames(root)

    for path in scannable:
        for lineno, cited_raw, text in _iter_citations(path, root):
            cited = cited_raw.split(":", 1)[0] if re.search(r":\d+", cited_raw) else cited_raw
            if cited.startswith("./"):
                cited = cited[2:]
            base = cited.rsplit("/", 1)[-1]
            if base in generated:
                continue  # generated artifact, never checked in -- §3d
            if "/" not in cited and (base.startswith("_") or base.startswith("-")):
                continue  # bare suffix-convention mention -- §3e
            if base in PLACEHOLDER_BASENAMES:
                continue  # canonical worked-example fixture name -- §3f
            if _external_repo_declaration(path, cited) is not None:
                continue  # citation into a declared external repo -- §3h
            if _resolve(cited, path, all_shipped, basenames):
                continue
            hit = Hit(path=path, line=lineno, cited=cited, text=text)
            if "/" in cited:
                result.hits.append(hit)
            else:
                result.bare_mentions.append(hit)

    result.hits.sort(key=lambda h: (h.path, h.line, h.cited))
    result.bare_mentions.sort(key=lambda h: (h.path, h.line, h.cited))
    result.home_leaks = _scan_home_path_leaks(scannable, root)
    return result


def _resolve(cited, citing_path, all_shipped, basenames):
    """`all_shipped` is tracked + untracked-not-ignored (see _git_ls_files) --
    a citation to an untracked-but-real, not-yet-committed file resolves
    just as a tracked one does; a citation to a gitignored path (or one
    that plain doesn't exist anywhere) does not."""
    if "/" not in cited:
        return cited in basenames
    if cited in all_shipped:
        return True
    citer_dir = citing_path.rsplit("/", 1)[0] if "/" in citing_path else ""
    if citer_dir:
        rel = _normalize_posix(citer_dir + "/" + cited)
        if rel in all_shipped:
            return True
    return False


def _normalize_posix(p):
    parts = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def _append_hits_by_file(lines, hits):
    by_file: dict = {}
    for h in hits:
        by_file.setdefault(h.path, []).append(h)
    for path in sorted(by_file):
        lines.append(f"\n{path}")
        for h in by_file[path]:
            lines.append(f"  line {h.line}: cites {h.cited!r} -- {h.text}")


def _format_report(result):
    lines = []
    lines.append(f"scanned {result.files_scanned} file(s) (git-tracked + untracked-not-gitignored)")

    lines.append("")
    lines.append("== dangling references (loud -- drives exit code) ==")
    if not result.hits:
        lines.append("0 found")
    else:
        lines.append(f"{len(result.hits)} found:")
        _append_hits_by_file(lines, result.hits)

    lines.append("")
    lines.append("== bare-name mentions (quiet -- informational only) ==")
    if not result.bare_mentions:
        lines.append("0 found")
    else:
        lines.append(f"{len(result.bare_mentions)} found:")
        _append_hits_by_file(lines, result.bare_mentions)

    lines.append("")
    lines.append("== home-directory path leaks (separate defect class) ==")
    if not result.home_leaks:
        lines.append("0 found")
    else:
        lines.append(f"{len(result.home_leaks)} found:")
        by_file: dict = {}
        for h in result.home_leaks:
            by_file.setdefault(h.path, []).append(h)
        for path in sorted(by_file):
            lines.append(f"\n{path}")
            for h in by_file[path]:
                lines.append(f"  line {h.line}: {h.matched!r} -- {h.text}")

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=".",
        help="repo root to scan (default: current directory)",
    )
    args = parser.parse_args(argv)

    result = scan(args.root)

    if result.files_scanned == 0:
        sys.stderr.write(
            f"VACUOUS SCAN: 0 file(s) (tracked or untracked-not-ignored) matched "
            f"{sorted(SCANNED_EXTS)} under {os.path.abspath(args.root)!r}. Either "
            "this is not a git repository, the tree is empty, or every shipped "
            "file was filtered out by extension. This is reported as a distinct "
            "failure, not a clean pass -- see this script's own docstring, "
            "'EXIT CODES'.\n"
        )
        return EXIT_VACUOUS

    print(_format_report(result))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
