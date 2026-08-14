# Auditing your own escape markers

`scripts/check_escape_markers.py` closes a gap the nine guards themselves
don't: they require an escape marker to carry a *reason*, but nothing in
this pack reviews whether that reason is *true*. This is a **diff-scoped
CI / pre-push gate**, not a `.claude/hooks/` PreToolUse guard — it runs
once per pull request (or push, via a pre-push hook), not once per tool
call, and it looks at git history rather than a single Edit/Write/Bash
event.

## The doctrine, restated for this one

Every guard's escape marker (`# swallow-ok: <reason>`, `# tampering-ok:
<reason>`, and the rest — see the vocabulary table below) stops a **bare**
bypass: no marker with an empty reason clears a block. It does not stop a
**well-written, false** reason. An agent can write `# swallow-ok: this is
the documented degrade-to-default path` on a swallow that is neither
documented nor a degrade-to-default, and every guard in this tree waves it
through — the marker only checks that a reason exists, not that it's
correct. In the origin system this pack was extracted from, an independent
reviewer adjudicates every marker's reason against the diff at merge time
(`.claude/rules/honesty-guardrails.md`, "Tampering-vouch review"). This
pack shipped the markers themselves but nothing to wire that review into
an installer's own CI/CD. `check_escape_markers.py` is that.

## Two tiers

**Tier A (deterministic, always on, no dependency beyond `git`).** Diffs
the branch against a base ref, extracts every escape marker *added* (a `+`
line) in the diffed, in-scope files, and requires two things:

1. No **bare** marker — the keyword with nothing after the colon. This
   fails outright; no commit-message trailer excuses it.
2. Every **reasoned** marker is named, `<path>:<line>`, in an
   `Escape-Markers:` trailer somewhere in the commits being merged (see
   [Trailer format](#trailer-format)). This is what forces a new escape
   marker to be *visible at review time* — in the commit message a human
   actually reads — instead of buried three files deep in a diff nobody
   opened.

**Tier B (optional, gated on `ANTHROPIC_API_KEY`).** For every marker that
passed Tier A, invokes a **cold** `claude -p` subprocess — no session
reuse, no context beyond the marker, its stated reason, and the diff hunk
around it — and asks it to judge whether the reason describes a change
actually visible in that hunk. The verdict is binary: anything that isn't
the exact token `PASS` (empty output, a timeout, `FAIL`, a hedge, garbage)
folds to `FAIL`, mirroring the origin's tampering-vouch rule ("ambiguous
folds into fail"). A Tier B `FAIL` fails the whole gate exactly like a
Tier A miss.

`ANTHROPIC_API_KEY` absent → Tier B is **skipped, loudly** (named in the
report), and Tier A alone gates the run. `ANTHROPIC_API_KEY` present but
the `claude` binary missing on `PATH` is a *different* case — the operator
opted in by setting the key, so this fails loudly (naming `claude`)
instead of silently degrading to Tier A only, the same "ship your
dependency or fail loudly" rule `CONTRIBUTING.md` §10 states for `jq` in
`protect-files.sh`.

## Trailer format

One `Escape-Markers:` line per commit, naming every marker that commit (or
an earlier commit in the same range) is acknowledging:

```
git commit -m "$(cat <<'EOF'
Add a deliberate degrade-to-default swallow

Escape-Markers: src/foo.py:42, src/foo.py:58
EOF
)"
```

Repeated `Escape-Markers:` lines across separate commits in the same PR
all count — the gate searches every commit in `base..HEAD`, not just the
tip, so a marker introduced early and acknowledged in a later commit on
the same branch is still covered. A malformed token (missing the `:line`
suffix) is ignored and reported by name, not silently dropped.

## Vocabulary

Every marker below is detected by importing the **real, live** compiled
regex (or matching function) from the hook that actually enforces it —
see `check_escape_markers.py`'s own `_load_hook()` — never a re-typed
second copy that could drift from what the guard itself accepts.

| Marker | Governing hook | Forms | Worked example |
|---|---|---|---|
| `# swallow-ok: <reason>` | `no_swallowed_errors.py` | `#`, `<# #>` (PowerShell), `//` (Go) | `pass  # swallow-ok: intentional degrade-to-default, see issue #42` |
| `# tampering-ok: <reason>` | `no_test_tampering.py` | `#`, `<# #>`, `//` | `# tampering-ok: assertion pinned a code path removed in this PR, see diff below` |
| `# host-provides: <reason>` / `# type-stub-ok: <reason>` | `no_type_checking_stub.py` | `#` | `# host-provides: LiveEvaluator supplies this at composition time` |
| `# delete-tests-ok: <reason>` | `no_bash_test_deletion.py` | `#` (inside a Bash command string) | `rm tests/test_foo.py  # delete-tests-ok: the feature it covered was removed in this PR` |
| `# test-mutate-ok: <reason>` | `no_bash_test_mutation.py` | `#` (inside a Bash command string) | `sed -i 's/old/new/' tests/test_foo.py  # test-mutate-ok: renames fixture to match new endpoint` |
| `// workflow-model-ok: <reason>` | `workflow_agent_sizing_gate.py` | `//` (JS) | `agent(p, {model: undefined}); // workflow-model-ok: deliberate inherit for a one-off maintenance run` |
| `opus-leaf-ok: <reason>` | `agent_sizing_gate.py` | plain text sentinel, no comment syntax | `Agent(model="opus", prompt="... opus-leaf-ok: one bounded oppositional review, no delegation")` |
| `fable-leaf-ok: <reason>` | `agent_sizing_gate.py` | plain text sentinel, no comment syntax | same shape as `opus-leaf-ok`, for the Fable tier |
| `doc-ref-ok: <reason>` | `scripts/check_doc_refs.py` | plain text, any scanned line | `See conftest.py doc-ref-ok: ecosystem convention name, not a real citation` |

**Deliberately excluded: `falsy-zero-ok`.** `no_falsy_zero.py` is not a
hook this pack ships — `CONTRIBUTING.md` §6 names it as the documented
cautionary case for vocabulary coupling and states plainly why it isn't
shipped ("the hazard is portable, the detector is not"). There is no
guard in `.claude/hooks/` for this script to audit that marker against.

## Scope — what gets scanned, and the known gap

Only files whose extension is one a shipped guard's marker actually lives
in as source-comment syntax: `.py .sh .go .ps1 .psm1 .psd1 .js`.
Deliberately **out of scope**:

- **Markdown/YAML (`.md`, `.yaml`, `.yml`).** This repo's own
  `CONTRIBUTING.md`, `PATTERNS.md`, `docs/guards/*.md` and `README.md`
  quote realistic, fully-formed marker examples dozens of times over as
  *documentation*, not live escapes guarding real code — scanning `.md`
  would make touching this pack's own docs impossible without constant
  trailer friction over prose that clears nothing. The real cost: `doc-ref-ok`
  (which legitimately lives mostly in `.md`/`.yaml` prose) is
  under-covered by this choice. Stated here, not hidden — if you install
  this gate somewhere that leans on `doc-ref-ok` heavily, widen
  `SCANNED_EXTS` in your own copy and expect the doc-PR friction that
  comes with it.
- **`examples/` and `adapters/`** — mirrors `run_tests.sh`'s own
  suite-discovery exclusions; both directories deliberately construct
  marker-shaped fixture text as worked demonstrations.
- **Test files** (`is_test_file()`, the same predicate every shipped
  guard already uses) — a planted-failure test has to construct violating
  marker text as a literal fixture to prove detection works at all.
- **`scripts/check_escape_markers.py` itself** (`SELF_PATH`) — its own
  vocabulary table and regex definitions are, by construction, a literal
  enumeration of the markers it audits. This is the same SELF-CONFIG
  EXCLUSION `scripts/check_release_clean.py` applies to its own
  forbidden-terms/exceptions files, for the identical reason: a gate must
  never read its own configuration back to itself and count it as
  contamination.

## Exit codes

| Code | Name | Meaning |
|---|---|---|
| `0` | `EXIT_CLEAN` | Every added marker (if any) is reasoned, acknowledged, and (if Tier B ran) adjudicated `PASS`. |
| `1` | `EXIT_UNACKNOWLEDGED` | At least one bare marker, one reasoned-but-unacknowledged marker, or one Tier B `FAIL`. |
| `2` | `EXIT_USAGE_ERROR` | The diff itself could not be computed (no base ref given, bad ref, not a git repo) — distinct from a real, computed, empty diff, which is `EXIT_CLEAN`. Also used when `ANTHROPIC_API_KEY` is set but `claude` isn't on `PATH`. |

## Running it yourself

```
python3 scripts/check_escape_markers.py --base-ref <ref-or-sha> [--root PATH]
```

`--base-ref` also reads from `GUARDRAILS_ESCAPE_BASE_REF` if omitted from
the command line. In this repo's own `.github/workflows/ci.yml`, the
`escape-markers` job passes `github.event.pull_request.base.sha` on
`pull_request` events and no-ops loudly (a named step explaining why) on
`push` — a push has no PR base ref to diff against, and fabricating one
would produce a result that doesn't mean what a PR diff means.

For a local pre-push hook, the natural base ref is wherever your branch
diverged from its remote tracking branch, e.g.:

```
BASE=$(git merge-base origin/main HEAD)
python3 scripts/check_escape_markers.py --base-ref "$BASE"
```

## What this doesn't do

- It does not adjudicate a marker whose reason it cannot see in the diff
  hunk it's given (Tier B's context window is the hunk containing the
  marker, not the whole file or the whole PR) — a reason that depends on
  context outside that hunk will read as unconfirmable and fold to `FAIL`.
  State the reason near the marker, not three functions away.
- It does not catch a marker that was never diffed at all — a marker
  already sitting in the tree before the base ref is out of scope by
  construction (this is a gate on *new* markers, not a full-tree audit;
  `scripts/check_release_clean.py` and friends are the full-tree release
  checks, a different tool for a different question).
- `agent_sizing_gate.py`'s `opus-leaf-ok`/`fable-leaf-ok` sentinel is
  matched per diff LINE here, mirroring the real hook's own whole-prompt
  `_has_leaf_escape` by hand (there's no importable regex object for it) —
  a sentinel split across two lines in a multi-line committed prompt
  string will not be recognized as reasoned. See
  `check_escape_markers.py`'s `_detect_leaf_sentinel` docstring.
