# Changelog

Patch notes per release. A release = an annotated git tag `vX.Y.Z` on this
repo; when a release changes `adapters/dsh/`, a matching npm publish of
`faultseed-dsh` is cut FROM THAT TAG's content (see RELEASING.md for the
sync contract). Between tags, `main` moves — install from a tag or from npm
if you want a fixed version; install from `main` if you want the tip.

## v0.1.1 — 2026-08-14

- **Update-path gate closed** (RELEASING.md step 2, previously unreceipted):
  a fresh v0.1.0 install, deliberately drifted (customized `engine_dirs`,
  a local file added next to the hooks pack, a `settings.local.json`
  override, and — as a positive control — a hand-corrupted pack file),
  updated cleanly to current `main`'s content. `INSTALL.md` gained an
  "Updating" section (previously absent — a pack that can only be
  installed once, not updated, was the actual gap this gate exists to
  catch); receipt at
  `docs/receipts/update-path-v0.1-receipt.md`.
- `adapters/dsh/`: npm storefront pass. `README.md` restructured so the
  npm package page reads as a standalone page in 30 seconds — what this
  is, both install paths, a one-command verify-it-blocks check, and links
  to the main repo / `docs/lessons.md` / `AGENTS.md` — with the full
  verification record (unchanged, including the "VERIFIED THROUGH THE
  REAL BRIDGE" boundary statement) moved below the fold. `package.json`
  gained `keywords`, `homepage`, and `bugs`; version bumped to `0.1.1`
  (the adapter's own content — `cordis.patch.yml`, `hooks.json`, the two
  `bin/` proof scripts — is unchanged; this is a metadata/packaging-only
  bump).
- `scripts/check_escape_markers.py`: diff-scoped CI gate — every escape
  marker added in a change must be acknowledged in an `Escape-Markers:`
  commit trailer; optional LLM adjudication tier behind an API key.
- `AGENTS.md`: model-agnostic agent behavioral contract (cross-tool
  convention); README pointer.
- `docs/lessons.md`: twelve enforced lessons, each cited to this repo's
  public history.
- Test-fixture hygiene: one synthetic leak fixture genericized
  (`331d348`).

## v0.1.0 — 2026-08-14

Initial publication.

- Nine guards, each with a planted-failure test proving it can fail;
  mutation-verified.
- Comment-defeat evasion class in Go/PowerShell detection found by the
  pack's own mutation pass and fixed pre-tag (`d55be18`); escape-marker
  contract holds in both directions in all tiers.
- Fail-closed on missing dependencies (`jq`, `bash`), unparseable stdin,
  invalid UTF-8, Python < 3.10, and unusual git states.
- dsh (DeepSeek Harness) adapter, verified through the real bridge
  (agent-loop, matcher, codec, subprocess; only the LLM scripted).
- `scripts/check_commit_metadata.py` and `scripts/check_doc_refs.py`
  gates; examples runner including README worked-example execution.
- npm: `@jw53222/faultseed-dsh@0.1.0`, packed from this tag's
  `adapters/dsh`, registry shasum `3598a7cf...` verified against the staged
  tarball.
