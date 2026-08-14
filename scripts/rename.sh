#!/usr/bin/env bash
# rename.sh -- replace the {{NAME}} / {{SCOPE}} placeholders with the real
# project name and npm scope, once, at the moment the name is chosen.
#
# WHY THIS EXISTS: the repo is written with placeholder tokens so that the
# name can be decided last without a hand-edit sweep across every doc. That
# only works if the sweep is mechanical and VERIFIED -- a rename that misses
# three files leaves a repo that reads as unfinished, and nobody notices
# until a stranger does.
#
# USAGE
#   scripts/rename.sh --check                 report placeholder counts, change nothing
#   scripts/rename.sh <name>                  set {{NAME}}; leave {{SCOPE}} alone
#   scripts/rename.sh <name> <scope>          set both
#   scripts/rename.sh --dry-run <name> [scope]  show what would change
#
# EXIT CODES
#   0  success (or --check found placeholders and reported them)
#   1  bad usage / not a git repo
#   2  placeholders survived the sweep -- the rename did NOT fully apply
#   3  VACUITY: there was nothing to rename. Either it has already been run,
#      or you are not where you think you are. A sweep that swept nothing is
#      not a success, and this script will not report it as one.
set -euo pipefail

NAME_TOKEN='{{NAME}}'
SCOPE_TOKEN='{{SCOPE}}'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "FATAL: $REPO_ROOT is not a git repository." >&2
  exit 1
}

# Files this repo ships: tracked, PLUS untracked-but-not-ignored (a file
# added and not yet committed still ships). `git ls-files` alone was the
# first version of this line and it was wrong in the dangerous direction --
# on a tree mid-work it found 1 placeholder instead of dozens and would have
# reported a clean, complete rename. Ignored paths and .git stay out of
# scope: a rename must not reach into anything the repo does not ship.
#
# This script excludes ITSELF. It necessarily contains the placeholder tokens
# in its own source, so a sweep that included it would rewrite its own
# literals -- silently breaking the second run (the one that sets the scope
# after the name) and polluting its own before/after counts. Found by
# running the vacuity test against a fixture and getting 7 hits from a tree
# that was supposed to have none.
SELF_REL="scripts/$(basename "${BASH_SOURCE[0]}")"
mapfile -t FILES < <(git ls-files --cached --others --exclude-standard | grep -vFx "$SELF_REL")

count_token() {
  local token="$1" total=0 n
  for f in "${FILES[@]}"; do
    [ -f "$f" ] || continue
    n=$(grep -Fo "$token" "$f" 2>/dev/null | wc -l)
    total=$((total + n))
  done
  echo "$total"
}

files_with() {
  local token="$1"
  grep -Fl "$token" "${FILES[@]}" 2>/dev/null || true
}

DRY_RUN=0
case "${1:-}" in
  --check)
    echo "{{NAME}}  occurrences: $(count_token "$NAME_TOKEN")"
    echo "{{SCOPE}} occurrences: $(count_token "$SCOPE_TOKEN")"
    echo
    echo "Files containing a placeholder:"
    { files_with "$NAME_TOKEN"; files_with "$SCOPE_TOKEN"; } | sort -u | sed 's/^/  /'
    exit 0
    ;;
  --dry-run)
    DRY_RUN=1; shift
    ;;
  ""|-h|--help)
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac

NEW_NAME="${1:-}"
NEW_SCOPE="${2:-}"

if [ -z "$NEW_NAME" ]; then
  echo "FATAL: no name given. See --help." >&2
  exit 1
fi

BEFORE_NAME=$(count_token "$NAME_TOKEN")
BEFORE_SCOPE=$(count_token "$SCOPE_TOKEN")

# VACUITY GUARD. A sweep that finds nothing to sweep is the same shape as a
# detector pointed at the wrong directory: zero hits and a broken invocation
# produce identical output. Fail loudly instead of printing a reassuring
# "done".
if [ "$BEFORE_NAME" -eq 0 ] && { [ -z "$NEW_SCOPE" ] || [ "$BEFORE_SCOPE" -eq 0 ]; }; then
  echo "FATAL (vacuity): no placeholders found in $REPO_ROOT." >&2
  echo "Nothing was renamed. Either this has already been run, or this is not" >&2
  echo "the tree you meant. Refusing to exit 0 on a sweep that swept nothing." >&2
  exit 3
fi

echo "Renaming in $REPO_ROOT"
echo "  {{NAME}}  -> $NEW_NAME        ($BEFORE_NAME occurrences)"
if [ -n "$NEW_SCOPE" ]; then
  echo "  {{SCOPE}} -> $NEW_SCOPE       ($BEFORE_SCOPE occurrences)"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo
  echo "--dry-run: no files written. Affected files:"
  { files_with "$NAME_TOKEN"; [ -n "$NEW_SCOPE" ] && files_with "$SCOPE_TOKEN"; } \
    | sort -u | sed 's/^/  /'
  exit 0
fi

for f in "${FILES[@]}"; do
  [ -f "$f" ] || continue
  sed -i "s/{{NAME}}/${NEW_NAME}/g" "$f"
  [ -n "$NEW_SCOPE" ] && sed -i "s/{{SCOPE}}/${NEW_SCOPE}/g" "$f"
done

# VERIFY. The sweep is not trusted; it is checked. This is the whole reason
# the script exists rather than a one-line sed in a README.
AFTER_NAME=$(count_token "$NAME_TOKEN")
AFTER_SCOPE=$(count_token "$SCOPE_TOKEN")

FAILED=0
if [ "$AFTER_NAME" -ne 0 ]; then
  echo "FAILED: $AFTER_NAME occurrence(s) of {{NAME}} survived:" >&2
  files_with "$NAME_TOKEN" | sed 's/^/  /' >&2
  FAILED=1
fi
if [ -n "$NEW_SCOPE" ] && [ "$AFTER_SCOPE" -ne 0 ]; then
  echo "FAILED: $AFTER_SCOPE occurrence(s) of {{SCOPE}} survived:" >&2
  files_with "$SCOPE_TOKEN" | sed 's/^/  /' >&2
  FAILED=1
fi
[ "$FAILED" -eq 1 ] && exit 2

echo
echo "Done. Verified: 0 placeholders remain in tracked files."
if [ -z "$NEW_SCOPE" ]; then
  echo "Note: {{SCOPE}} was not given and still has $AFTER_SCOPE occurrence(s)."
  echo "Re-run with a scope once the npm scope is decided."
fi
echo "Review with: git diff"
