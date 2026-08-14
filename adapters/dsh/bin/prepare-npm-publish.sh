#!/bin/sh
# prepare-npm-publish.sh -- STAGED, NOT applied by anything automatically.
# Nothing runs this script until an operator invokes it deliberately, once a
# real npm scope exists (as of writing, the owner has no npm account yet --
# scope decision pending). Run it from anywhere; it locates its own package
# directory from its own script location, the same pattern bin/smoke-test.sh # doc-ref-ok: usage/comment prose, path is relative to the adapter package root, not this repo root
# and bin/codec-mapping-proof.mjs already use.
#
# Usage:
#   SCOPE=your-npm-scope sh bin/prepare-npm-publish.sh   # doc-ref-ok: usage line, path is relative to the adapter package root
#
# ../package.json ships UNSCOPED today ("name": "faultseed-dsh") so that a
# GitHub-direct install (`dsh plugin add "github:JW53222/faultseed#path:adapters/dsh"`,
# see README.md's Install section) works without needing the owner's scope
# decision at all -- a scope is only required to PUBLISH to npm, not to
# install straight from git. This script is where that scope gets applied,
# and ONLY there: it does not touch the GitHub-direct path.
#
# What it does, IN ORDER, to THIS DIRECTORY's package.json only:
#   1. Rewrites the unscoped "name" ("faultseed-dsh") to the scoped form
#      ("@your-npm-scope/faultseed-dsh"). Refuses to run if "name" is not
#      exactly the unscoped literal already -- see the idempotency guard
#      below.
#   2. Flips "private": true -> "private": false (the deliberate guard that
#      currently makes `npm publish` refuse to run by accident).
#   3. Sets a "repository" field pointing at the public repo, with the
#      "directory" sub-field npm's own docs use for a package that lives in a
#      subdirectory of a monorepo (this one): adapters/dsh.
#
# Then it VERIFIES its own result rather than assuming success -- see
# adapters/dsh/NOTES.md's "why this script self-verifies" note. Critically,
# verification asserts the FINAL name equals "@<scope>/faultseed-dsh"
# EXACTLY, not merely "no placeholder token remains" -- an earlier version of
# this script substituted a "{{SCOPE}}" token and verified only that the
# token was gone, which is exactly the silent-no-op shape this pack exists to
# catch: a check that can pass while doing nothing (e.g. if a future edit
# changes what marks "unsubstituted" without updating what the check looks
# for). Checking the literal target string closes that gap.
#   - "name" is exactly "@SCOPE/faultseed-dsh" (not merely "does not contain
#     a placeholder")
#   - "private" is actually false (read back, not just "we wrote false")
#   - every path in the "files" array actually exists on disk
# If ANY check fails, package.json is restored from a backup and the script
# exits nonzero -- a failed run leaves nothing half-applied.
#
# Does NOT run `npm login` or `npm publish`. Flipping publishable and
# actually publishing are two separate, deliberately separate steps; this
# script performs only the first, and only on request.

set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PKG_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
PKG_JSON="$PKG_DIR/package.json"
REPO_URL="git+https://github.com/JW53222/faultseed.git"
UNSCOPED_NAME="faultseed-dsh"

if [ -z "${SCOPE:-}" ]; then
  echo "prepare-npm-publish.sh: SCOPE env var required, e.g.:" >&2
  echo "  SCOPE=your-npm-scope sh bin/prepare-npm-publish.sh" >&2 # doc-ref-ok: usage line, path is relative to the adapter package root
  exit 1
fi

case "$SCOPE" in
  *[!A-Za-z0-9-]* | -* | *-)
    echo "prepare-npm-publish.sh: SCOPE '$SCOPE' is not a valid npm scope segment (letters, digits, hyphens only; no leading/trailing hyphen)." >&2
    exit 1
    ;;
esac

TARGET_NAME="@${SCOPE}/${UNSCOPED_NAME}"

CURRENT_NAME=$(node -e "console.log(JSON.parse(require('fs').readFileSync(process.argv[1], 'utf8')).name)" "$PKG_JSON")
if [ "$CURRENT_NAME" != "$UNSCOPED_NAME" ]; then
  echo "prepare-npm-publish.sh: package.json's \"name\" is \"$CURRENT_NAME\", not the expected unscoped \"$UNSCOPED_NAME\" -- already applied (check for \"$TARGET_NAME\"), or the field was hand-edited. Not touching it." >&2
  exit 1
fi

BACKUP=$(mktemp)
cp "$PKG_JSON" "$BACKUP"

node -e "
const fs = require('fs')
const path = process.argv[1]
const targetName = process.argv[2]
const repoUrl = process.argv[3]
const pkg = JSON.parse(fs.readFileSync(path, 'utf8'))
pkg.name = targetName
pkg.private = false
pkg.repository = { type: 'git', url: repoUrl, directory: 'adapters/dsh' }
fs.writeFileSync(path, JSON.stringify(pkg, null, 2) + '\n')
" "$PKG_JSON" "$TARGET_NAME" "$REPO_URL"

fail=0

WRITTEN_NAME=$(node -e "console.log(JSON.parse(require('fs').readFileSync(process.argv[1], 'utf8')).name)" "$PKG_JSON")
if [ "$WRITTEN_NAME" != "$TARGET_NAME" ]; then
  echo "VERIFY FAIL: name is \"$WRITTEN_NAME\", expected exactly \"$TARGET_NAME\"" >&2
  fail=1
fi

if ! node -e "
const pkg = JSON.parse(require('fs').readFileSync(process.argv[1], 'utf8'))
process.exit(pkg.private === false ? 0 : 1)
" "$PKG_JSON"; then
  echo "VERIFY FAIL: private is not false" >&2
  fail=1
fi

MISSING=$(node -e "
const fs = require('fs')
const path = require('path')
const pkg = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'))
const dir = process.argv[2]
const missing = (pkg.files || []).filter(f => !fs.existsSync(path.join(dir, f)))
console.log(missing.join('\n'))
" "$PKG_JSON" "$PKG_DIR")
if [ -n "$MISSING" ]; then
  echo "VERIFY FAIL: files array entries missing on disk:" >&2
  echo "$MISSING" >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "Restoring package.json from backup -- publish prep NOT applied." >&2
  cp "$BACKUP" "$PKG_JSON"
  rm -f "$BACKUP"
  exit 1
fi

rm -f "$BACKUP"
echo "OK: package.json is publish-ready (name=$TARGET_NAME, private=false, repository set)."
echo "Next (NOT run by this script, and not before Sunday's scope decision): npm login, then npm publish --access public from adapters/dsh/."
