# Releasing — the GitHub↔npm sync contract

Two channels, one source of truth:

- **GitHub (`main`)** is the living tree and a ref-tracking install channel
  — `github:` installs follow whatever ref the user names. Tags are the
  fixed points.
- **npm (`faultseed-dsh`)** is an immutable versioned snapshot of
  `adapters/dsh/` only. npm never receives content that is not in a public
  tagged commit.

The invariant, checkable by anyone: **for every npm version X.Y.Z there is a
git tag `vX.Y.Z` whose `adapters/dsh/` packs to the registry's shasum.**

## Procedure (in order; each step gates the next)

1. All repo gates green on the release commit: `./run_tests.sh`,
   `scripts/check_doc_refs.py`, `scripts/check_commit_metadata.py`,
   `scripts/check_escape_markers.py` (vs previous tag), and the
   licensor-side release sweep against a `git archive` extraction.
2. **Update-path gate (required before any second release):** v(N) must
   install cleanly OVER v(N-1) in a deliberately drifted scratch repo —
   modified config, moved files, local commits — with a receipt. A methods
   pack that cannot ship an update has made a one-time delivery. This gate
   has NO receipt yet (no second release exists); it must gain one before
   v0.2 ships. Do not delete this paragraph to make a release easier.
3. CHANGELOG.md entry written (patch-notes style), version bumped in
   `adapters/dsh/package.json` ONLY if the adapter changed.
4. Annotated tag `vX.Y.Z`; tag message names the npm version it backs (or
   states the adapter is unchanged and no npm publish accompanies it).
5. If the adapter changed: publish from a `git archive <tag>` extraction —
   never the working tree — via `adapters/dsh/bin/prepare-npm-publish.sh`
   (applies the scope + flips `private`), then `npm publish --access public`.
6. **Verify the sync from the outside**: download the registry tarball,
   `sha1sum` it, and confirm it equals `npm pack --dry-run`'s shasum from
   the tag's extraction. Record both in the GitHub Release notes.
7. GitHub Release created from the tag; body = the CHANGELOG entry.

## Why publish from an extraction, not the tree

The working tree accumulates local state (telemetry logs, scratch files)
that the tagged content does not contain; a tree-packed tarball can differ
from what the tag proves. `git archive <tag>` makes the published bytes a
pure function of the public commit — which is what lets a stranger verify
the invariant above without trusting us.
