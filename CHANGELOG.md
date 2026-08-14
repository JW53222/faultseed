# Changelog

Patch notes per release. A release = an annotated git tag `vX.Y.Z` on this
repo; when a release changes `adapters/dsh/`, a matching npm publish of
`faultseed-dsh` is cut FROM THAT TAG's content (see RELEASING.md for the
sync contract). Between tags, `main` moves — install from a tag or from npm
if you want a fixed version; install from `main` if you want the tip.

## Unreleased (on `main` since v0.1.0)

- `scripts/check_escape_markers.py`: diff-scoped CI gate — every escape
  marker added in a change must be acknowledged in an `Escape-Markers:`
  commit trailer; optional LLM adjudication tier behind an API key.
- `AGENTS.md`: model-agnostic agent behavioral contract (cross-tool
  convention); README pointer.
- `docs/lessons.md`: twelve enforced lessons, each cited to this repo's
  public history.
- Test-fixture hygiene: one synthetic leak fixture genericized
  (`331d348`).
- No changes to `adapters/dsh/` — npm `0.1.0` still matches `main`'s
  adapter content.

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
