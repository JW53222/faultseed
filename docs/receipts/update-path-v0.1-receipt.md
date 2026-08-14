# Update-path receipt — v0.1.0 → current `main`

Closes RELEASING.md step 2, the "Update-path gate (required before any
second release)": a real drifted install of v0.1.0, updated to current
`main`'s content, with a receipt. This is that receipt, and it found two
real bugs in the update procedure it was written to validate — neither
excused, both fixed before this file was written up.

## Setup

Scratch dir (outside this repo): a fresh git repo (`target-repo`), a
`git archive v0.1.0` extraction (`v010-src`), and a `git archive HEAD`
extraction of this repo's `main` at `0b0044af8eba` (`main-src`). All
commands below were actually run against these three directories.

**Pack content is byte-identical between v0.1.0 and this `main`**
(`diff -rq v010-src/.claude main-src/.claude` and `diff -q .../docs/hook-manifest.yaml` <!-- doc-ref-ok: scratch-dir paths inside the ephemeral update-proof harness, not paths in this repo -->
— both empty). This release doesn't change the nine guards; it adds this
receipt and an `adapters/dsh/` storefront pass. That makes a plain
before/after diff of the copied files vacuous by itself, so a **positive
control** (item 4 below) was added specifically to prove the update step
performs a real overwrite rather than a no-op that happens to look clean
because nothing changed.

## Install v0.1.0, then drift it

1. Fresh repo, one file (`src/app.py`), committed. <!-- doc-ref-ok: the scratch target-repo's own placeholder file, not a path in this repo -->
2. Installed v0.1.0 per `INSTALL.md`'s Quickstart: copied `.claude/hooks`,
   `.claude/rules`, `docs/hook-manifest.yaml`, `docs/audit/audit-scope.yaml`;
   set `engine_dirs: ["src"]`; ran `generate_settings_json.py`. Baseline
   PROVE-IT pair confirmed working (`.env` → exit 2, `config.envoy.yaml` →
   exit 0). Committed.
3. Drifted, three separate commits:
   - `engine_dirs` grown to `["src", "lib"]` — a real config value a user
     would actually reach, not the shipped sentinel.
   - `.claude/hooks/LOCAL_NOTES.md` added <!-- doc-ref-ok: a file created inside the scratch target-repo for this receipt, not a path in this repo --> — the user's own file, living
     next to the pack's files, never part of the pack.
   - `protect-files.sh` line 86 hand-edited (`.env` → `.env-DISABLED`) —
     **the positive control**: simulated accidental local drift to a PACK
     file itself. Verified it actually broke the guard before touching
     the update path at all: `.env` write → exit 0 (should be 2).
4. Uncommitted, gitignored `.claude/settings.local.json` added (a local
   permission override) — this is real repo behavior, not a plant that
   needed inventing: `generate_settings_json.py` has no
   `settings.local.json`-aware `--target` or flag at all, so nothing about
   an update could reach it either way.

## `INSTALL.md` had no update path — that's the finding

`grep -i updat INSTALL.md` before this change matched one unrelated line
(inside the tampering-marker doc, "test needed updating"). The Quickstart
is a single-shot "copy files into an empty slot" procedure; nothing in the
file told a v0.1.0 installer how to move to a newer version, and re-running
Quickstart step 1 verbatim onto an *existing* install is not safe (next
section). A methods pack that can only be installed once has made a
one-time delivery, per RELEASING.md's own words for this gate. Fixed:
`INSTALL.md` gained an "Updating" section (six steps: get a newer
extraction, re-copy pack files, deliberately skip re-copying
`audit-scope.yaml`, regenerate `settings.json`, note `settings.local.json`
is untouched by construction, re-run the PROVE-IT pair) plus a
survives/does-not-survive table.

## Two real bugs the drafting process caught

**Bug 1 — nesting.** The first draft of the Updating section's step 2 reused
Quickstart step 1's exact command form: `cp -r <src>/.claude/hooks
<dst>/.claude/hooks`. Run for real against the drifted repo (where
`.claude/hooks` already existed), this did not overwrite — `cp -r` onto an
existing directory copies the source *inside* it. Result: a stray
`.claude/hooks/hooks/`, the corrupted `protect-files.sh` untouched at the
top level, `generate_settings_json.py` exit 0 but wiring nothing that
mattered. Caught by checking the actual file content post-"update", not by
trusting the copy's exit code.

**Bug 2 — the naive fix deleted the user's file.** `rm -rf .claude/hooks`
before the copy avoids the nesting, but a directory-replace also removes
anything the user added inside that same directory — it deleted
`LOCAL_NOTES.md` on the next run <!-- doc-ref-ok: the scratch target-repo's planted file, not a path in this repo -->. Caught the same way: checked the file
existed, not just that the command exited 0.

**Fix applied, in both `INSTALL.md` and this receipt's own re-run:** copy
the source's *contents*, trailing `/.`, not the source directory itself —
`cp -r <src>/.claude/hooks/. <dst>/.claude/hooks/`. Overwrites every
filename the pack ships, adds new ones, deletes nothing that isn't the
pack's own. Re-ran with this form; see the after-column below.

## Before / after

| Check | Before update | After update | Verdict |
|---|---|---|---|
| `engine_dirs` (`docs/audit/audit-scope.yaml`) | `["src", "lib"]` (drifted) | `["src", "lib"]` | **survived**, as documented |
| `.claude/hooks/LOCAL_NOTES.md`<!-- doc-ref-ok: scratch target-repo path, not a path in this repo --> (user's own file) | present | present | **survived**, as documented |
| `.claude/settings.local.json` | `{"permissions": {"allow": ["Bash(pytest:*)"]}}` | byte-identical | **survived**, untouched (never in either copy list) |
| `protect-files.sh` line 86 (positive control) | `.env-DISABLED` (corrupted, guard broken) | `.env` (restored) | **overwritten**, as documented |
| `.env` write via `protect-files.sh` | exit `0` (broken — should block) | exit `2` (`Blocked: .env matches protected pattern '.env'`) | **functional pin restored** |
| `config.envoy.yaml` write (near-miss) | exit `0` | exit `0` | unchanged, correct throughout |
| `.claude/hooks/hooks/`, `.claude/rules/rules/` (nesting check) | n/a | absent | **no nesting**, confirmed with the corrected command form |
| `git log` (local commit history) | 5 commits | same 5 commits, same shas | **untouched** |
| `src/app.py`<!-- doc-ref-ok: scratch target-repo path, not a path in this repo --> (pre-existing project file) | `def add(a, b): return a + b` | byte-identical | **untouched** |
| `generate_settings_json.py` exit code | — | `0` (`wrote .claude/settings.json`, `wrote .claude/PROVENANCE.json`) | clean regen |

## What this receipt does not claim

The pack's *content* didn't change between v0.1.0 and this `main` (see
"Setup" above) — this receipt validates the update *mechanism* and the
survives/does-not-survive contract, not a real feature propagating through
an update. The positive control (protect-files.sh corruption/restore) is
what makes that validation non-vacuous: it proves the copy step performs a
genuine overwrite of pack files, not a no-op that looks clean only because
nothing changed. The first real *content* change to `.claude/hooks/` will
be the first time this exact procedure is exercised against a non-identical
diff — re-run it then rather than assuming this receipt covers that case.
