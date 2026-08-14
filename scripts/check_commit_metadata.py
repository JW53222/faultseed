#!/usr/bin/env python3
"""check_commit_metadata.py -- scan COMMIT METADATA (author name/email,
committer name/email, subject, body) across every commit reachable from
ANY ref, for forbidden identifiers.

WHY THIS EXISTS -- a real incident, not a hypothetical:
This pack ships a release scrub that checks every FILE for forbidden
identifiers (personal names, emails, home paths, origin-project vocabulary)
by running against `git archive` extractions. It passed clean, four times,
with an empty exceptions list. It never saw commit metadata -- a `git
archive` extraction is files-and-nothing-else, no `.git/` at all -- so the
owner's personal email sat in the author AND committer fields of every
commit through four green scrub runs, a full independent oppositional
review, and a delta review. Nothing built for this pack could see it.
GitHub's push protection is what actually caught it, which is the only
reason it never went public. This script closes exactly that hole: it is
the first thing in this pack that looks at `git log` instead of `git
show HEAD:path` / a working-tree walk.

SHAPE: a release-time repo CHECK (sibling to check_doc_refs.py), NOT a
Claude Code hook. The nine guards in .claude/hooks/ block in-session TOOL
CALLS (an Edit, a Bash command) as they happen; there is no tool call to
intercept here; this operates over already-committed git history at
release-scrub time, same as check_doc_refs.py. Wired into run_tests.sh the
same way check_doc_refs.py is: that script auto-discovers every
`scripts/test_*.py`, so no wiring edit was needed for the test file, and
this script itself is meant to be invoked directly (`python3
scripts/check_commit_metadata.py`) as part of the same pre-publish
checklist as check_doc_refs.py, not through pytest.

============================================================================
DESIGN DECISIONS
============================================================================

1. WHICH COMMITS ARE SCANNED -- `git log --all`, not HEAD, not
   `git push --all`'s ref set.
   This is the part that bit us. `git filter-branch` (and equivalents)
   rewrite history and leave the ORIGINAL, unrewritten commits reachable
   from `refs/original/refs/heads/<branch>` -- a ref that sits outside
   `refs/heads/` and `refs/tags/`. `git push --all` only pushes
   `refs/heads/*`; `git push --tags` only pushes `refs/tags/*`; a plain
   `git push` pushes whatever the configured refspec names. All three can
   leave `refs/original/...` behind, unpushed, looking "gone" from the
   outside. But it is NOT gone from the repo, and a later `git push
   refs/*:refs/*` (an explicit mirror-style refspec, or `git push
   --mirror`) publishes it -- pre-rewrite commits, personal metadata and
   all. `git log --all` (equivalently `git rev-list --all`) walks every ref
   under `refs/` including `refs/original/...`, `refs/stash`, and anything
   else -- verified empirically before writing this: a throwaway repo with
   a commit orphaned under `refs/original/refs/heads/main` after a second
   commit was made on `refs/heads/master` shows up in `git log --all
   --oneline` even though it is invisible to `git push --all`/`--tags`. A
   check that only looked at HEAD (or only at `refs/heads/*`) would have
   reported this repo's real incident clean while the pre-rewrite,
   personal-email-carrying commits were still sitting in the object store.

2. THE FORBIDDEN-TERMS LIST IS NOT SHIPPED HERE -- ON PURPOSE.
   The real forbidden-terms list (the owner's actual name, email local-part,
   home username, origin-project internal vocabulary) lives OUTSIDE this
   repo and must never be copied in: it is, by definition, an inventory of
   the exact identifiers this pack exists to keep out of a public repo, so
   shipping that inventory INSIDE the public repo defeats its own purpose
   the moment someone opens this file. That rules out "ship the list and
   grep for it" as this script's design, which leaves one real question:
   what can a check ship that benefits a COMPLETE STRANGER installing this
   pack, who has no list at all and never will?

   The answer this script takes: a small set of STRUCTURAL patterns that
   need no secret list to be useful, because they don't look for a
   particular name or email -- they look for a SHAPE that is a personal
   leak by construction, for any user, on any machine:
     - any email address in a commit-metadata field that is NOT a
       `noreply`-style address (`_is_noreply_email` below) -- author/
       committer email fields are checked directly; subject/body are
       regex-scanned for embedded addresses (a manually-added
       `Signed-off-by: Real Name <real@email>` trailer, or a personal
       email pasted into a commit message, both land here).
     - any absolute home-directory path (`/home/<user>/...`,
       `/Users/<user>/...`, or a single-user Linux root-home path -- see
       `_ROOT_PREFIX` below) appearing in a commit's subject or body text.
   Neither pattern requires knowing WHOSE name, email, or home directory to
   look for -- they fire for the shape alone. That is exactly the incident
   this file exists to prevent: the real author/committer email that leaked
   was, structurally, "an email address that is not noreply" the whole
   time; this script would have caught it on the first run, with zero
   configuration, before a single push attempt.

   On top of that structural floor, `--terms-file PATH` accepts an
   OPTIONAL, user-supplied, never-committed file of additional literal
   terms (one per line, `#`-comments and blank lines ignored), matched
   case-insensitively as a substring against all six fields. This is where
   a maintainer's actual name, employer, or origin-project vocabulary
   belongs -- supplied locally at scrub time (a file outside the repo, or a
   gitignored path inside it), never checked into the pack itself. Omitting
   `--terms-file` does not weaken the vacuity floor (see §3): the
   structural checks alone still have to scan >0 commits to pass.

   FALSE-POSITIVE COST, weighed explicitly: this script does NOT carry
   check_doc_refs.py's long exemption ladder (glob/quote/suffix/generated-
   artifact/placeholder/external-repo/creating-command -- see that script's
   docstring §3a-j), and that is a deliberate asymmetry, not an oversight.
   check_doc_refs.py's citation extraction collides constantly with
   legitimate content -- ordinary prose, test fixtures, ecosystem filenames
   like `conftest.py` -- because "a path-shaped string appears in a file" is
   a common, mostly-innocent event, so it needed a long ladder to stay
   usable. A commit's structured author/committer EMAIL FIELD containing a
   real (non-noreply) address, or a commit MESSAGE containing a literal
   `/home/<user>/...` path, is not that: there is no ordinary, legitimate
   reason for either to appear in a public release's git history at all,
   so the true-positive rate for both patterns is high and the false-
   positive rate is low by construction. This is also a REPORT, not a
   blocking hook -- a human reads the output before a release push (same
   consumption model as check_doc_refs.py); the cost of an occasional
   false positive is one line in a report a maintainer glances at and
   dismisses, not a build broken for a legitimate case. That asymmetry
   (report, not gate; rare true collision) is why a short, un-exempted
   check is the right level of complexity here, where check_doc_refs.py's
   was not.

3. VACUITY FLOOR -- mirrors check_doc_refs.py's `EXIT_VACUOUS` concept.
   `commits_scanned` counts only WELL-FORMED, fully-parsed commit records
   (see `_git_log_all`'s 7-field split). Scanning zero commits (not a git
   repo, a git repo with no commits yet, or -- defensively -- a git repo
   where every commit record failed to parse into the expected 6 metadata
   fields, e.g. because a future `git` changed `-z`/`--format` behavior
   incompatibly) collapses to the SAME `commits_scanned == 0` gate and the
   SAME `EXIT_VACUOUS` code, deliberately: "0 real commits" and "commits
   existed but 0 of them were checkable" are the same observable failure
   from a caller's point of view -- either way, 0 field-checks actually
   ran -- and reporting them as the one gate (with a distinguishing count
   of malformed records in the message) is simpler and no less honest than
   inventing a second exit code for a distinction the caller cannot act on
   differently. This must FAIL distinctly, not silently report clean --
   a checker that reports "0 found" after checking nothing is indistinguishable,
   from the outside, from one that would have caught something.

4. WHY `-z` / unit-separator (`\x1f`) FIELD PARSING, NOT ONE COMMIT PER
   `git log -1` CALL.
   A single `git log --all -z --format=...` call retrieves every commit's
   six fields in one subprocess, `\x00`-delimited per commit (git's own
   `-z` option, the standard idiom for NUL-safe multi-record `git log`
   output) and `\x1f`-delimited (ASCII Unit Separator, a control character
   that does not occur in ordinary text) between fields within a record.
   The body field is captured with `str.split(sep, maxsplit=6)` so that if
   a commit body ever legitimately contains a literal `\x1f` byte (not
   observed, exceedingly unlikely), it is absorbed into the body field
   rather than corrupting the split -- the parse only breaks (falls into
   the malformed-record path in §3) if `\x00` itself is corrupted, which
   would mean `git log -z` itself misbehaved.

5. COMMITTER FIELDS, NOT ONLY AUTHOR FIELDS.
   Author and committer identity are set independently (`git commit
   --author=... `, `git rebase`/`filter-branch`/`cherry-pick`, or a bot
   re-signing a commit, can each touch one without the other). A rewrite
   that fixes the author but not the committer (or vice versa) is exactly
   the shape this script exists to catch, so `author_email` and
   `committer_email` are both checked directly, and `author_name` /
   `committer_name` both participate in the optional terms-file scan (§2).

6. KNOWN LIMIT, home-path matching: `_HOME_TAIL_CHARS` (reused verbatim
   from check_doc_refs.py's identical exclusion set) does not exclude a
   bare trailing comma or period, so an UNWRAPPED path immediately
   followed by prose punctuation (`.../secrets.env, then patched`) sweeps
   that punctuation into the reported match. A backtick/quote/paren-
   wrapped citation (this repo's own convention) is unaffected -- the
   closing character IS excluded, so the match ends exactly at the path.
   This is report-text cosmetics, not a missed detection: the path is
   still found and still drives EXIT_FOUND either way.

NO HARDCODED PERSONAL PATHS IN THIS FILE (release-cleanliness constraint,
same as check_doc_refs.py): this script's own source text must never
contain the literal contiguous home-directory-prefix substrings it
searches for. `_HOME_PREFIX` / `_USERS_PREFIX` / `_ROOT_PREFIX` below are
therefore assembled via string concatenation, never spelled out as one
contiguous literal anywhere in this file (including this docstring) --
otherwise check_doc_refs.py's own home-path-leak check, which also scans
every `.py` file in this repo including this one, would flag this file.

EXIT CODES:
  0 (EXIT_CLEAN)        commits scanned, nothing forbidden found.
  1 (EXIT_FOUND)        at least one forbidden metadata match found.
  2 (EXIT_VACUOUS)      0 commits scanned (see §3) -- distinct FAILURE.
  3 (EXIT_USAGE_ERROR)  `--terms-file PATH` was given but PATH does not
                         exist / is not a readable file -- an explicitly
                         requested check that silently did not run is the
                         same defect class as a vacuous scan, so it is
                         loud, not a silent "no terms" fallback.

Usage: python3 check_commit_metadata.py [--root PATH] [--terms-file PATH]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

EXIT_CLEAN = 0
EXIT_FOUND = 1
EXIT_VACUOUS = 2
EXIT_USAGE_ERROR = 3

FIELD_NAMES = (
    "author_name", "author_email",
    "committer_name", "committer_email",
    "subject", "body",
)
_EMAIL_FIELDS = ("author_email", "committer_email")

# ASCII Unit Separator between fields within one commit's record; `-z`
# NUL-delimits records themselves. See docstring §4.
_FIELD_SEP = "\x1f"
_LOG_FORMAT = _FIELD_SEP.join(["%H", "%an", "%ae", "%cn", "%ce", "%s", "%b"])

# A conventional email-shaped token, good enough for a release-scrub
# free-text sweep (subject/body) -- not RFC 5322 exhaustive, deliberately:
# this is looking for a leaked address a human wrote, not validating input.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# --- home-directory path prefixes -- see "NO HARDCODED PERSONAL PATHS" ---
# Built from separately-quoted fragments, exactly like check_doc_refs.py's
# own `_HOME_PREFIX`/`_USERS_PREFIX`/`_ROOT_PREFIX`, so this file's source
# text never contains the contiguous substring being searched for (and so
# check_doc_refs.py's own leak check, which also scans this file, stays
# clean).
_SLASH = "/"
_HOME_PREFIX = _SLASH + "home" + _SLASH        # multi-user Linux
_USERS_PREFIX = _SLASH + "Users" + _SLASH      # macOS
_ROOT_PREFIX = _SLASH + "root"                 # single-user Linux root home

# Same tail-character exclusion set as check_doc_refs.py's home-path check:
# a bracketed/`$VAR`-style placeholder in generic instructions never even
# starts a match.
_HOME_TAIL_CHARS = r"[^\s\"'`)\]<>${}]"
_HOME_PATH_RE = re.compile(
    r"(?<![\w./-])("
    + re.escape(_HOME_PREFIX) + _HOME_TAIL_CHARS + r"+"
    + r"|" + re.escape(_USERS_PREFIX) + _HOME_TAIL_CHARS + r"+"
    + r"|" + re.escape(_ROOT_PREFIX) + r"(?:" + re.escape(_SLASH) + _HOME_TAIL_CHARS + r"*)?"
    + r")"
)


@dataclass
class CommitRecord:
    commit: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    subject: str
    body: str


@dataclass
class Hit:
    commit: str    # full 40-char SHA -- see docstring, "so a human can act on it"
    field: str      # one of FIELD_NAMES
    rule: str       # "non-noreply-email" / "embedded-email" / "home-path" / "terms-file"
    matched: str    # the exact substring that triggered the rule


@dataclass
class ScanResult:
    commits_scanned: int = 0    # well-formed, fully-parsed records only
    commits_malformed: int = 0  # raw records that failed to parse -- see §3/§4
    hits: list = field(default_factory=list)

    @property
    def exit_code(self):
        if self.commits_scanned == 0:
            return EXIT_VACUOUS
        if self.hits:
            return EXIT_FOUND
        return EXIT_CLEAN


def _is_noreply_email(addr):
    """True if `addr` looks like a provider-generated no-reply address
    (GitHub's `<id>+<user>@users.noreply.github.com`, GitLab's equivalent,
    and similar). Deliberately liberal ("noreply" as a substring of either
    the local-part or the domain, not an exact-domain allowlist) rather
    than hardcoding one host: a stranger installing this pack may publish
    to GitLab, Bitbucket, or a self-hosted forge with its own no-reply
    convention, and this script ships with no list of hosts to hardcode
    anyway (see docstring §2). The false-positive risk of this leniency is
    negligible -- a real, non-generated address that happens to contain the
    substring "noreply" without BEING a no-reply address is not a shape
    that occurs in practice."""
    local, sep, domain = addr.strip().rpartition("@")
    if not sep:
        return False
    return "noreply" in local.lower() or "noreply" in domain.lower()


def _load_terms(path):
    """Load an optional, never-committed forbidden-terms file: one literal
    term per line, blank lines and `#`-prefixed comment lines ignored.
    Matched case-insensitively as a substring later. Raises OSError if
    `path` cannot be read -- the caller in `main` checks existence first
    and turns that into EXIT_USAGE_ERROR rather than a traceback."""
    terms = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            terms.append(line)
    return terms


def _git_log_all(root):
    """Return (records, malformed_count) for every commit reachable from
    ANY ref under refs/ -- `git log --all`, not HEAD, not `refs/heads/*`
    only. See docstring §1 for why: this is what still sees a
    `refs/original/refs/heads/<branch>` left behind by a history rewrite,
    which `git push --all`/`--tags` would silently skip.

    Degrades to ([], 0) -- same shape as "zero commits" -- on any git
    failure (not a repo, git missing, timeout): the caller's vacuity gate
    (ScanResult.commits_scanned == 0) already handles that case correctly
    without a separate code path, mirroring check_doc_refs.py's
    `_git_ls_files` returning [] for the same reason."""
    try:
        proc = subprocess.run(
            ["git", "-C", root, "log", "--all", "-z", "--format=" + _LOG_FORMAT],
            capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], 0
    if proc.returncode != 0:
        return [], 0

    records = []
    malformed = 0
    for chunk in proc.stdout.split(b"\x00"):
        if not chunk.strip():
            continue
        text = chunk.decode("utf-8", errors="replace")
        parts = text.split(_FIELD_SEP, 6)
        if len(parts) != 7:
            malformed += 1
            continue
        commit, an, ae, cn, ce, subj, body = parts
        records.append(CommitRecord(commit, an, ae, cn, ce, subj, body))
    return records, malformed


def scan(root, terms_file=None):
    root = os.path.abspath(root)
    records, malformed = _git_log_all(root)
    result = ScanResult(commits_scanned=len(records), commits_malformed=malformed)
    if not records:
        return result

    terms = _load_terms(terms_file) if terms_file else ()

    for rec in records:
        for field_name in FIELD_NAMES:
            value = getattr(rec, field_name)
            if not value:
                continue

            if field_name in _EMAIL_FIELDS:
                # The whole field IS the email (`%ae`/`%ce` never carry
                # surrounding text) -- check it directly rather than
                # regex-scanning it. See docstring §5.
                if not _is_noreply_email(value):
                    result.hits.append(Hit(rec.commit, field_name, "non-noreply-email", value))
            else:
                # author_name / committer_name / subject / body: free text
                # that may have an address embedded in it (a manually
                # pasted `Signed-off-by:` trailer, a name field abused as
                # free text, ...). See docstring §2.
                for m in _EMAIL_RE.finditer(value):
                    addr = m.group(0)
                    if not _is_noreply_email(addr):
                        result.hits.append(Hit(rec.commit, field_name, "embedded-email", addr))

            for m in _HOME_PATH_RE.finditer(value):
                result.hits.append(Hit(rec.commit, field_name, "home-path", m.group(1)))

            if terms:
                lowered = value.lower()
                for term in terms:
                    idx = lowered.find(term.lower())
                    if idx != -1:
                        result.hits.append(
                            Hit(rec.commit, field_name, "terms-file", value[idx:idx + len(term)])
                        )

    result.hits.sort(key=lambda h: (h.commit, h.field, h.rule, h.matched))
    return result


def _format_report(result):
    lines = []
    lines.append(
        f"scanned {result.commits_scanned} commit(s) reachable from any ref "
        f"under refs/ (git log --all)"
    )
    if result.commits_malformed:
        lines.append(
            f"WARNING: {result.commits_malformed} commit record(s) failed to "
            "parse into the expected 6 metadata fields and were excluded -- "
            "see this script's docstring §3/§4"
        )

    lines.append("")
    lines.append("== forbidden commit metadata (drives exit code) ==")
    if not result.hits:
        lines.append("0 found")
    else:
        lines.append(f"{len(result.hits)} found:")
        by_commit: dict = {}
        for h in result.hits:
            by_commit.setdefault(h.commit, []).append(h)
        for commit in sorted(by_commit):
            lines.append(f"\n{commit}")
            for h in by_commit[commit]:
                lines.append(f"  field {h.field}: [{h.rule}] {h.matched!r}")

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--root", default=".",
        help="repo root to scan (default: current directory)",
    )
    parser.add_argument(
        "--terms-file", default=None,
        help="optional file of additional forbidden terms, one per line, "
             "'#' comments allowed, matched case-insensitively as a "
             "substring against all six metadata fields. Never commit "
             "this file to the pack -- see this script's docstring §2.",
    )
    args = parser.parse_args(argv)

    if args.terms_file is not None and not os.path.isfile(args.terms_file):
        sys.stderr.write(
            f"ERROR: --terms-file {args.terms_file!r} does not exist or is "
            "not a file. An explicitly requested check that silently did "
            "not run is a vacuity failure, not a warning -- see EXIT CODES "
            "in this script's docstring.\n"
        )
        return EXIT_USAGE_ERROR

    result = scan(args.root, terms_file=args.terms_file)

    if result.commits_scanned == 0:
        sys.stderr.write(
            f"VACUOUS SCAN: 0 commit(s) reachable from any ref under refs/ "
            f"in {os.path.abspath(args.root)!r} yielded a checkable record "
            f"({result.commits_malformed} malformed record(s) discarded). "
            "Either this is not a git repository, it has zero commits, or "
            "every commit record failed to parse -- reported as a distinct "
            "failure, not a clean pass -- see this script's own docstring, "
            "'EXIT CODES'.\n"
        )
        return EXIT_VACUOUS

    print(_format_report(result))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
