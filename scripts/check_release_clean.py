#!/usr/bin/env python3
"""check_release_clean.py -- release-vocabulary sweep for a repo about to
ship: catches personal-identifier and credential SHAPES in file content,
plus (optionally) a user-supplied list of the user's own literal terms.

Ported from a private release pipeline's check_release_clean.sh, which is
proven there: a planted-failure test asserts it rejects a real violation
and names both the offending term and the file it was found in. A user
installing this pack had no way to check whether THEIR OWN tree is clean
without a private copy of that check -- this file is that check, vendored.

============================================================================
THE HARD PART -- WHAT SHIPS HERE VS. WHAT NEVER CAN
============================================================================
The origin gate's terms list was ~100 literal strings: a real inventory of
one organisation's own identifiers (product name, personal workstation
name, the author's git handle, a secrets vendor tied to their infra, a
regulator acronym tied to their specific product, their own consumer email
domains). Shipping that list here would publish the very thing it exists
to keep unpublished -- the same self-defeating move the origin script
itself refuses for its own config (its SELF_CONFIG_RELPATHS comment: a
gate must never read its own configuration back to itself and count it as
contamination). So this port ships something structurally different, in
two tiers:

TIER 1 -- SHAPES (SHAPE_CHECKS below; built in, generic, ship as-is).
A pattern for "this looks like a personal leak" that needs no secret list
at all, because it does not look for a particular name -- it looks for a
FORM that is a leak for any user, on any repo: an absolute home-directory
path, a real (non-placeholder, non-noreply) email address, a PEM
private-key header, an AWS-shaped access key ID, a bearer token. A run
with no other configuration at all still exercises every one of these.

TIER 2 -- YOUR OWN TERMS (--extra-terms-file, optional, never shipped).
Your employer's name, your internal project codenames, the vendors tied to
YOUR infra -- the terms that matter most to any given release are,
definitionally, the ones only that release's owner can supply. This flag
points at a file in the exact format the origin forbidden-terms.txt used:
one literal term per line, '#'-comments and blank lines ignored, matched
case-insensitively as a substring anywhere in a scanned file (there is no
inline-comment syntax, so a term itself may never contain '#'). The file
is never part of this repo -- there is no shipped default filename, and
nothing here for this repo's own .gitignore to exclude. Follow this pack's
own precedent instead: scripts/check_commit_metadata.py's --terms-file
takes the identical never-committed, optional, pass-your-own-path
approach for the same reason (see that script's docstring, "THE FORBIDDEN-
TERMS LIST IS NOT SHIPPED HERE -- ON PURPOSE"). Keep your terms file
outside the tree entirely, or inside it under a name your own .gitignore
excludes -- never commit it, since committing it re-creates the exact
problem this design avoids.

Tier 2 is additive, not required. Its absence is stated in the report,
never silently assumed -- see "== extra terms ==" in the output.

============================================================================
SCOPE DECISION -- NO GIT-HISTORY SCAN (unlike the origin script)
============================================================================
The origin check_release_clean.sh had a third mode: when the build
directory carried a `.git/` whose entire history was a single orphan
commit (an invariant specific to that origin's own seal pipeline), it
additionally blob-scanned everything reachable from that one commit. That
mode is deliberately NOT ported:

  1. The recommended way to run this check (see "OPERATIONAL NOTE (a)"
     below) is against a `git archive` extraction, which by construction
     has no `.git/` directory at all -- the origin's history-scan branch
     would never fire there anyway.
  2. "History is exactly one orphan commit" is an invariant of one
     specific origin pipeline, not a property any repo installing this
     pack can be assumed to have. Porting that branch would mean either
     silently never firing (dead code) or asserting a shape this pack has
     no business asserting about someone else's repo.

This is a known, STATED gap, not a silent one: full commit-HISTORY file
CONTENT (as opposed to the tip of a tree) is not scanned by this script.
Neither is it scanned by scripts/check_commit_metadata.py, which is a
different surface entirely -- see OPERATIONAL NOTE (b) below.

============================================================================
TWO OPERATIONAL FACTS FROM USING THE ORIGIN OF THIS GATE ON A REAL REPO
============================================================================
(a) Run this against a `git archive` extraction, not your live working
    tree. A working tree accumulates generated, run-time-only state that
    the published artifact never contains -- this repo's own example:
    `.claude/hooks/state/harness_events.jsonl` (see docs/telemetry.md) is
    local telemetry the hooks in this pack write as they fire, gitignored,
    and never part of a real release. Scanning the live working tree risks
    both false positives (flagging generated state nobody is going to
    ship) and a false sense of security (a clean working-tree scan proves
    nothing about whether a stray absolute path or credential made it into
    a PREVIOUS commit still reachable in `.git/`, which this script -- see
    the scope decision above -- does not look at either). The archive
    extraction is exactly what a recipient of the release actually
    receives, so it is the only tree whose scan result means what it
    claims to mean:
        git archive --format=tar HEAD | (mkdir -p /tmp/relcheck && tar -x -C /tmp/relcheck)
        python3 scripts/check_release_clean.py /tmp/relcheck

(b) This script scans FILE CONTENT only -- the bytes inside each shipped
    file. Commit METADATA (author/committer name and email, commit
    subject and body) is a separate surface it cannot see at all: a `git
    archive` extraction has no `.git/`, and even a full-history scan of
    file content (which this script does not do -- see the scope decision
    above) would never touch a commit's author/committer fields, because
    those aren't file content. scripts/check_commit_metadata.py is the
    sibling script that closes exactly that gap (it scans
    `git log --all` across every ref, not `git show HEAD:path`), and its
    own docstring records the real incident that motivated it: a personal
    email sat in every commit's author/committer fields through four green
    runs of the origin file-content scrub, because nothing that scrub did
    could ever have seen it. Run both checks; neither substitutes for the
    other.

============================================================================
OTHER DESIGN NOTES
============================================================================
- VACUITY GUARD (same property as the origin, and as this pack's
  scripts/check_doc_refs.py / scripts/check_commit_metadata.py siblings):
  scanning zero files under <build-dir> is a FATAL failure (EXIT_VACUOUS),
  never a green "0 hits" pass. A scan that touches nothing proves nothing.

- EXCEPTION SEMANTICS (--exceptions-file, optional, format
  "<path><TAB><reason>" per line): an exception excuses ONE PATH -- a file,
  or everything under it if the path names a directory -- from ALL rules
  (every shape AND every extra term) found within that path. It does NOT
  extend to any other path. Every live exception is re-printed in full on
  every run; a STALE exception (path no longer exists under <build-dir>)
  fails the check rather than silently vanishing -- same anti-rot property
  the origin's clean-exceptions.txt documents.

- SELF-CONFIG EXCLUSION: the origin script had to hardcode an exclusion
  list (SELF_CONFIG_RELPATHS) for its own forbidden-terms.txt and
  clean-exceptions.txt, because those files are, by construction, a
  literal enumeration of every term they define -- scanning them means the
  gate can never report clean. This script needs NO equivalent hardcoded
  list for Tier 1 (the shapes are regex, defined via code, not a file that
  enumerates its own targets as literal substrings -- verified by running
  this script against its own source, see "NO HARDCODED..." below). It
  DOES still need the same protection for Tier 2 if a user's own
  --extra-terms-file (or --exceptions-file) happens to sit inside the
  directory being scanned: both are excluded from the scan automatically,
  by resolved path, whenever that happens -- see `_self_config_relpaths()`.

- NO HARDCODED PERSONAL PATHS / KEY SHAPES IN THIS FILE: like
  scripts/check_doc_refs.py and scripts/check_commit_metadata.py, the
  home-directory prefixes below are assembled via string concatenation so
  this file's own source text never contains one of them as one
  contiguous literal. The credential-shape patterns do not need the same
  treatment -- each one is interrupted by regex syntax (an optional group,
  an alternation, a `\\s+`) at the exact point that would otherwise make it
  a literal match for itself, so the raw pattern SOURCE never satisfies
  its own regex. Verified empirically: running this script against its own
  source file is part of scripts/test_check_release_clean.py.

EXIT CODES:
  0 (EXIT_CLEAN)         files scanned, nothing forbidden found.
  1 (EXIT_FOUND)         at least one non-excepted hit, OR a stale
                         exception -- either way, the build is not
                         verified clean.
  2 (EXIT_VACUOUS)       0 files scanned under <build-dir> -- distinct
                         FAILURE, never a silent pass.
  3 (EXIT_USAGE_ERROR)   <build-dir> does not exist, --extra-terms-file /
                         --exceptions-file was given but is not a readable
                         file, or --exceptions-file has a malformed entry
                         (missing TAB, empty path, or empty reason).

Usage: python3 check_release_clean.py <build-dir>
           [--extra-terms-file PATH] [--exceptions-file PATH]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

EXIT_CLEAN = 0
EXIT_FOUND = 1
EXIT_VACUOUS = 2
EXIT_USAGE_ERROR = 3

# Mirrors the origin's own skip threshold for pathologically large files --
# a release build's own generated blobs (bundled binaries, lockfile-scale
# JSON) are not worth reading in full for a vocabulary sweep.
MAX_FILE_BYTES = 20_000_000

# --- home-directory path prefixes -- see "NO HARDCODED..." in the module
# docstring. Built from separately-quoted fragments so this file's source
# text never contains one of these as one contiguous literal (and so this
# very script's own home-path check, run over this repo, stays clean).
_SLASH = "/"
_HOME_PREFIX = _SLASH + "home" + _SLASH        # multi-user Linux
_USERS_PREFIX = _SLASH + "Users" + _SLASH      # macOS
_ROOT_PREFIX = _SLASH + "root"                 # single-user Linux root home

# A placeholder (`<user>`, `{username}`, `$HOME`, ...) never even starts a
# match -- the first character after the prefix already fails this class.
_HOME_TAIL_CHARS = r"[^\s\"'`)\]<>${}]"
_HOME_PATH_RE = re.compile(
    r"(?<![\w./-])("
    + re.escape(_HOME_PREFIX) + _HOME_TAIL_CHARS + r"+"
    + r"|" + re.escape(_USERS_PREFIX) + _HOME_TAIL_CHARS + r"+"
    + r"|" + re.escape(_ROOT_PREFIX) + r"(?:" + re.escape(_SLASH) + _HOME_TAIL_CHARS + r"*)?"
    + r")"
)

# A conventional email-shaped token -- good enough for a release-scrub
# free-text sweep, not RFC 5322 exhaustive (this is looking for a leaked
# address a human wrote, not validating input).
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# RFC 2606 reserved domains plus the ".local"/".localhost" convention --
# these are SAFE, conventional placeholders that legitimately appear in
# docs and examples, unlike a real provider domain. A file-content scanner
# collides with these constantly (see scripts/check_doc_refs.py's own
# "docs need usable example addresses" note); a commit-metadata scanner
# (scripts/check_commit_metadata.py) does not need this exemption because
# there is no legitimate reason for ANY email, placeholder or not, to sit
# in a commit's author/committer field.
_PLACEHOLDER_EMAIL_DOMAIN_SUFFIXES = (
    ".example", ".invalid", ".test", ".local", ".localhost",
    "example.com", "example.org", "example.net",
)


def _is_noreply_email(addr):
    """True for a provider-generated no-reply address (GitHub's
    `<id>+<user>@users.noreply.github.com`, GitLab's equivalent, and
    similar). Deliberately liberal (substring "noreply" in either half)
    rather than an exact-domain allowlist -- this script has no list of
    forges to hardcode, and a real non-generated address that happens to
    contain "noreply" without being one is not a shape seen in practice."""
    local, sep, domain = addr.rpartition("@")
    if not sep:
        return False
    return "noreply" in local.lower() or "noreply" in domain.lower()


def _is_placeholder_email_domain(addr):
    domain = addr.rpartition("@")[2].lower()
    return any(domain == s or domain.endswith("." + s) or domain == s.lstrip(".")
               for s in _PLACEHOLDER_EMAIL_DOMAIN_SUFFIXES)


# PEM private-key header. The optional middle group (an alternation, a
# regex metacharacter) is what keeps this pattern's own SOURCE TEXT from
# ever being a contiguous match for itself -- see "NO HARDCODED..." above.
_PRIVATE_KEY_HEADER_RE = re.compile(
    r"-----BEGIN(?: RSA| EC| DSA| OPENSSH| ENCRYPTED)? PRIVATE KEY-----"
)

# AWS-shaped access key ID (long-term "AKIA..." or STS temporary
# "ASIA..."): 4-letter prefix + 16 uppercase alphanumerics, not itself
# preceded/followed by another alnum (so it doesn't fire mid-token inside a
# longer opaque string).
_AWS_KEY_RE = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])")

# A generic "Bearer <token>" HTTP-auth header value, 20+ chars of
# token-shaped content after the scheme word.
_BEARER_TOKEN_RE = re.compile(r"\b[Bb]earer\s+[A-Za-z0-9\-_.=]{20,}")


def _home_path_matches(line):
    return [(m.group(1), "home-path") for m in _HOME_PATH_RE.finditer(line)]


def _email_matches(line):
    out = []
    for m in _EMAIL_RE.finditer(line):
        addr = m.group(0)
        if _is_noreply_email(addr) or _is_placeholder_email_domain(addr):
            continue
        out.append((addr, "email-address"))
    return out


def _private_key_matches(line):
    return [(m.group(0), "private-key-header") for m in _PRIVATE_KEY_HEADER_RE.finditer(line)]


def _aws_key_matches(line):
    return [(m.group(0), "aws-access-key") for m in _AWS_KEY_RE.finditer(line)]


def _bearer_token_matches(line):
    return [(m.group(0), "bearer-token") for m in _BEARER_TOKEN_RE.finditer(line)]


# The shipped, generic starter list -- see "TIER 1" in the module
# docstring. Each entry is a function taking one text line and returning a
# list of (matched_substring, rule_name) pairs.
SHAPE_CHECKS = (
    _home_path_matches,
    _email_matches,
    _private_key_matches,
    _aws_key_matches,
    _bearer_token_matches,
)


@dataclass
class Hit:
    path: str       # relpath under build dir, posix separators
    line: int
    rule: str        # shape name, or the extra term itself
    matched: str      # the exact substring that triggered the rule
    text: str         # the full source line, stripped, for context


@dataclass
class ExceptionEntry:
    path: str
    reason: str
    live: bool = True


@dataclass
class ScanResult:
    files_scanned: int = 0
    hits: list = field(default_factory=list)            # non-excepted
    excepted_hits: list = field(default_factory=list)
    exceptions: list = field(default_factory=list)        # ExceptionEntry, all of them
    extra_terms_file: str = None
    extra_terms_count: int = 0

    @property
    def stale_exceptions(self):
        return [e for e in self.exceptions if not e.live]

    @property
    def exit_code(self):
        if self.files_scanned == 0:
            return EXIT_VACUOUS
        if self.hits or self.stale_exceptions:
            return EXIT_FOUND
        return EXIT_CLEAN


def _load_extra_terms(path):
    """One literal term per line; '#'-comments and blank lines ignored.
    Same format the origin forbidden-terms.txt used -- see module
    docstring, TIER 2."""
    terms = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n").rstrip("\r").strip()
            if not line or line.startswith("#"):
                continue
            terms.append(line)
    return terms


class MalformedExceptions(Exception):
    pass


def _load_exceptions(path):
    """"<path><TAB><reason>" per line; '#'-comments and blank lines
    ignored. Raises MalformedExceptions (caller turns this into
    EXIT_USAGE_ERROR) on a line with no TAB, or an empty path/reason --
    a malformed entry fails loud, never silently skips."""
    entries = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\n").rstrip("\r")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "\t" not in line:
                raise MalformedExceptions(f"{path}:{lineno}: no TAB separator: {line!r}")
            p, _, reason = line.partition("\t")
            p = p.strip()
            reason = reason.strip()
            if not p or not reason:
                raise MalformedExceptions(f"{path}:{lineno}: empty path or reason: {line!r}")
            entries.append((p.rstrip("/"), reason))
    return entries


def _self_config_relpaths(build, extra_terms_file, exceptions_file):
    """Resolved relpaths (under `build`) of the user's own
    --extra-terms-file / --exceptions-file, IF either happens to sit
    inside the tree being scanned. Both files are, by construction, a
    literal enumeration of the very terms/paths this scan is looking for
    -- scanning them would be the exact "gate reads its own configuration
    back to itself" bug the origin script's SELF_CONFIG_RELPATHS comment
    documents. Dynamic (computed from whatever paths were actually passed
    on the command line), not a hardcoded list, because there is no fixed
    shipped filename for either -- see module docstring, TIER 2."""
    out = set()
    build_real = os.path.realpath(build)
    for p in (extra_terms_file, exceptions_file):
        if not p:
            continue
        p_real = os.path.realpath(p)
        try:
            rel = os.path.relpath(p_real, build_real)
        except ValueError:
            continue  # different drive (Windows) -- cannot be "inside" build
        if rel == os.curdir or rel.startswith(".." + os.sep) or rel == os.pardir:
            continue  # outside build, the common/recommended case
        out.add(rel.replace(os.sep, "/"))
    return out


def _is_excepted(relpath, exceptions):
    for e in exceptions:
        if relpath == e.path or relpath.startswith(e.path + "/"):
            return e
    return None


def scan(build, extra_terms=None, extra_terms_file=None, exceptions=None):
    """extra_terms: list[str], already loaded. exceptions: list[(path,
    reason)], already loaded. Both optional/empty by default -- Tier 1
    alone still runs."""
    extra_terms = extra_terms or []
    exceptions = exceptions or []
    build = os.path.abspath(build)

    entries = [ExceptionEntry(path=p, reason=r, live=os.path.exists(os.path.join(build, p)))
               for p, r in exceptions]

    skip_relpaths = _self_config_relpaths(build, extra_terms_file, None)

    result = ScanResult(exceptions=entries, extra_terms_file=extra_terms_file,
                         extra_terms_count=len(extra_terms))

    extra_terms_lower = [t.lower() for t in extra_terms]

    for root, dirs, files in os.walk(build):
        if ".git" in dirs:
            dirs.remove(".git")
        for fn in files:
            abspath = os.path.join(root, fn)
            relpath = os.path.relpath(abspath, build).replace(os.sep, "/")
            if relpath in skip_relpaths:
                continue
            try:
                size = os.path.getsize(abspath)
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                continue
            try:
                with open(abspath, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            result.files_scanned += 1
            if b"\x00" in data[:8192]:
                continue  # binary file, mirrors grep -I
            text = data.decode("utf-8", "replace")
            exc = _is_excepted(relpath, entries)
            for lineno, line in enumerate(text.splitlines(), start=1):
                for check in SHAPE_CHECKS:
                    for matched, rule in check(line):
                        hit = Hit(path=relpath, line=lineno, rule=rule, matched=matched,
                                   text=line.strip())
                        (result.excepted_hits if exc else result.hits).append(hit)
                if extra_terms:
                    line_lower = line.lower()
                    for term, term_lower in zip(extra_terms, extra_terms_lower):
                        if term_lower in line_lower:
                            hit = Hit(path=relpath, line=lineno, rule=term, matched=term,
                                       text=line.strip())
                            (result.excepted_hits if exc else result.hits).append(hit)

    result.hits.sort(key=lambda h: (h.path, h.line, h.rule))
    result.excepted_hits.sort(key=lambda h: (h.path, h.line, h.rule))
    return result


def _append_hits_by_file(lines, hits):
    by_file = {}
    for h in hits:
        by_file.setdefault(h.path, []).append(h)
    for path in sorted(by_file):
        lines.append(f"\n{path}")
        for h in by_file[path]:
            lines.append(f"  line {h.line}: [{h.rule}] {h.matched!r} -- {h.text}")


def _format_report(result, build):
    lines = [f"scanned {result.files_scanned} file(s) under {build}"]

    lines.append("")
    lines.append("== forbidden-content hits (shapes + extra terms; drives exit code) ==")
    if not result.hits:
        lines.append("0 found")
    else:
        lines.append(f"{len(result.hits)} found:")
        _append_hits_by_file(lines, result.hits)

    lines.append("")
    if result.extra_terms_file:
        lines.append(f"== extra terms (--extra-terms-file {result.extra_terms_file}: "
                      f"{result.extra_terms_count} term(s) loaded) ==")
    else:
        lines.append("== extra terms: none supplied (--extra-terms-file not given; "
                      "Tier 1 shapes only) ==")

    lines.append("")
    if result.exceptions:
        lines.append(f"adjudicated exceptions ({len(result.exceptions)}), re-stated every run:")
        for e in result.exceptions:
            lines.append(f"  [{'live' if e.live else 'STALE'}] {e.path}")
            lines.append(f"         reason: {e.reason[:200]}")
    else:
        lines.append("adjudicated exceptions (0)")

    if result.excepted_hits:
        lines.append("")
        lines.append(f"(excused by exceptions: {len(result.excepted_hits)} hit(s) -- not counted above)")

    if result.stale_exceptions:
        lines.append("")
        lines.append(f"RED: {len(result.stale_exceptions)} adjudicated exception(s) "
                      "no longer exist in the build -- the list has rotted:")
        for e in result.stale_exceptions:
            lines.append(f"  stale entry: {e.path}")

    lines.append("")
    lines.append(f"TOTAL non-excepted hits: {len(result.hits)} (want 0)")

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("build_dir", help="the directory to sweep (a git archive extraction, recommended -- see module docstring)")
    parser.add_argument("--extra-terms-file", default=None,
                         help="optional, never-shipped file of your own literal terms (Tier 2)")
    parser.add_argument("--exceptions-file", default=None,
                         help="optional file of adjudicated path exceptions")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.build_dir):
        print(f"FATAL: build dir does not exist: {args.build_dir}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    build = os.path.abspath(args.build_dir)

    extra_terms = []
    if args.extra_terms_file:
        if not os.path.isfile(args.extra_terms_file):
            print(f"FATAL: --extra-terms-file given but not a readable file: {args.extra_terms_file}",
                  file=sys.stderr)
            return EXIT_USAGE_ERROR
        extra_terms = _load_extra_terms(args.extra_terms_file)

    exceptions = []
    if args.exceptions_file:
        if not os.path.isfile(args.exceptions_file):
            print(f"FATAL: --exceptions-file given but not a readable file: {args.exceptions_file}",
                  file=sys.stderr)
            return EXIT_USAGE_ERROR
        try:
            exceptions = _load_exceptions(args.exceptions_file)
        except MalformedExceptions as e:
            print(f"FATAL: malformed exception entry -- {e}", file=sys.stderr)
            return EXIT_USAGE_ERROR

    result = scan(build, extra_terms=extra_terms, extra_terms_file=args.extra_terms_file,
                  exceptions=exceptions)

    if result.files_scanned == 0:
        sys.stderr.write(
            f"VACUOUS SCAN: 0 file(s) matched under {build!r}. Either the path is "
            "wrong, the tree is empty, or every entry was filtered out. This is a "
            "distinct failure, not a clean pass -- see this script's own vacuity "
            "guard.\n"
        )
        return EXIT_VACUOUS

    print(_format_report(result, build))
    if result.exit_code == EXIT_CLEAN:
        print("\n=== check_release_clean.py :: PASS -- no forbidden terms found ===")
    else:
        print("\n=== check_release_clean.py :: FAIL -- forbidden terms present (or a stale exception) ===")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
