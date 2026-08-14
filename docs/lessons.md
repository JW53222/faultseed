# Lessons this pack enforces, and where each came from

None of the twelve items below were designed in ahead of time. Every one was
found in this pack's own first 24 hours — sometimes by the pack's own
methods (a mutation pass, a doc-ref gate, a release scrub), sometimes by an
external reviewer reading the tree cold — and every fix landed in a public
commit on this repo's `main`. Citations below are commit SHAs, file paths,
and test names in *this* repository; each was checked against `git show`/
`git log`/the file on disk before being written down, the same discipline
[CONTRIBUTING.md](../CONTRIBUTING.md) asks of a contributor: "Where I quote
a command, I ran it. Where I quote a test, it exists at that path." Run
`git log --oneline` yourself rather than take the SHAs on faith.

## 1. A gate never proven to fail is indistinguishable from one that cannot fail

**Trap:** a guard can sit in the tree, be wired in `settings.json`, and be
invoked by real edits, while nothing has ever confirmed it actually blocks
anything.

**Instance:** the initial commit's own message (`71f3135`) states the claim
was false when the pack was assembled: "Four of the nine guards had no test
of any kind, the wiring layer's cited receipt named a file that did not
exist." That commit is what made the claim true before day one — writing
the missing tests surfaced six further bugs on the way (a model-tier set
defined and never consulted, an escape marker requiring no reason unlike
every sibling, two sizing gates that disagreed about their own recognized
vocabulary, `protect-files.sh` permitting a write when `jq` was absent, the
dispatcher itself permitting a tool call when `bash` was absent, and
generated-path exemptions hardcoded to a layout this repo doesn't have).

**Rule:** a PR adding a guard is not accepted without a test that
constructs a violating input and asserts rejection, plus the nearest
legitimate input allowed — [CONTRIBUTING.md §1](../CONTRIBUTING.md#1-the-planted-failure-requirement).

**What enforces it now:** every shipped guard has a `test_*.py` doing
exactly that (see the README's own [Receipts](../README.md#receipts)
section for the current count); `scripts/check_doc_refs.py` makes the
second half of the `71f3135` defect — a receipt citing a path that doesn't
exist — a released-time failure instead of a silent claim, over both
tracked and untracked files.

## 2. Green-for-the-wrong-reason

**Trap:** an "allow" test for an escape marker can pass for a reason that
has nothing to do with the marker — because the detection code never
reached the marker check at all.

**Instance:** commit `d55be18` found that five hard-block patterns across
two language tiers (`GO_DISCARD_ERR`, `GO_EMPTY_ERR_CHECK`,
`GO_SWALLOWED_RETURN_NIL`, `PS_EMPTY_CATCH`, `PS_NULL_CATCH`, all listed by
name in `docs/guards/no_swallowed_errors.md`) were anchored so that *any*
trailing or interior comment stopped the pattern from matching at all — not
just a reasoned `# swallow-ok:` marker. An "allow" test that added the
marker passed, but it would have passed identically with an unrelated `//
whatever`, because the marker-vocabulary check was never reached in either
case. Only a negative control — a *non-marker* comment, asserted to still
block — exposes the difference; none existed before `d55be18`.
`docs/guards/no_swallowed_errors.md` was corrected the same day (`97170e5`)
to say so plainly: "A comment that is not a marker clears nothing, in any
tier. That is worth saying plainly because it was not true until
2026-08-14."

**Rule:** every allow-marker test ships its must-block twin — a non-marker
comment on the identical shape, asserted to still block — or the "allow"
test proves nothing about the marker specifically.

**What enforces it now:** the widened Go/PowerShell detectors themselves
(`d55be18`) plus `.claude/hooks/test_no_swallowed_errors.py`'s paired
tests, and `docs/guards/no_swallowed_errors.md`'s explicit statement of the
five affected pattern names so a reader on an older checkout knows exactly
what to re-verify.

## 3. Opt-out-by-comment, and the question that found the rest of it

**Trap:** finding and fixing two instances of a bug feels like closing it.
It doesn't tell you whether the bug is a pair or a pattern.

**Instance:** the same mutation pass in `d55be18` found two real bugs first
— an over-anchored regex that any trailing comment defeated, and an
empty-`catch` pattern requiring adjacent braces. Asking
[CONTRIBUTING.md §12](../CONTRIBUTING.md#12-when-you-fix-a-bug-ask-where-else-that-shape-lives)'s
question — "if this mistake happened twice, where else does the same shape
live?" — turned up three more: every remaining hard-block pattern in both
non-Python tiers had the identical flaw. Five of five. The rationale-required
contract did not hold in either tier at all.

**Rule:** a repeated mistake is evidence about the author's model, not
about the line — check the siblings, not just the neighbors of the line you
changed. Codified as a standing question in CONTRIBUTING.md §12.

**What enforces it now:** nothing machine-checks that a contributor asked
the question — CONTRIBUTING.md §8 says so plainly (this is one of the bar
items that "can't be enforced," a checkbox would be exactly the
control-shaped object this pack exists to catch). What the `d55be18` fix
did instead: two shared per-language fragments replaced five separately
synced patches, so the five patterns can no longer drift apart from each
other one fix at a time.

## 4. A control's dependencies ship with it, or are checked loudly

**Trap:** correct code with a missing input degrades into whatever its
fallback happens to be — chosen by nobody, tested by nobody.

**Instance:** `protect-files.sh` shelled out to `jq` with no check that
`jq` was present. Per `71f3135`'s commit message, before the fix "the
secret-file guard exit[ed] 0 and permit[ted] the write when `jq` was
absent" and, separately, "the dispatcher itself exit[ed] 1 — which the
protocol reads as permit — when `bash` was absent." Both are undocumented
dependencies whose absence silently defeated the guard while it kept
looking installed.

**Rule:** name every file, env var, and binary a guard depends on; each one
either ships with the guard or the guard fails loudly (exit 2, naming what's
missing) when it's absent — [CONTRIBUTING.md
§10](../CONTRIBUTING.md#10-ship-your-dependencies-or-fail-loudly-without-them)
and [§11](../CONTRIBUTING.md#11-test-the-guards-environment-not-only-its-input)
(test the *environment*, not only the input).

**What enforces it now:** `protect-files.sh`'s fail-closed `jq` check
(named in its own header comment), `_dispatch.py`'s `bash`-probe fail path,
and `examples/11_missing_dependency`, which reproduces the historical `jq`
fail-open against the pre-fix commit side by side with the fixed behavior.

## 5. Vacuity catches empty, never partial

**Trap:** a scan that covers a third of the tree and finds nothing looks
identical, from the outside, to a scan that covers everything and finds
nothing. Only one of those is a clean result.

**Instance:** `scripts/check_doc_refs.py`'s own docstring (shipped in
`71f3135`) records the incident that shaped it: "this exact repo, mid-session,
had a small tracked core plus roughly fifty more files sitting
untracked-but-real... the bare call reported a clean-looking result over
only the tracked third." A parallel finding in the oppositional review
(`8a57cd2`, item M3): "`run_tests.sh` could not detect a suite that ceased
to exist — globbed discovery meant a vanished suite simply was not a suite,
and the headline verifier printed 'all stages passed'."

**Rule:** a scan must cover its full stated surface (tracked *and*
untracked-not-gitignored files, not `git ls-files` alone), and a test
runner must know how many suites it *expects* to run, not just whether the
ones it found exited 0.

**What enforces it now:** `check_doc_refs.py`'s untracked-inclusive file
walk plus its own `EXIT_VACUOUS` code for a zero-file scan;
`run_tests.sh`'s per-stage vacuity guard (`fail_stage` on a pytest exit 5 —
zero tests collected — or an all-skipped/xfailed run that exits 0 with
nothing actually passed) and, after `8a57cd2`, an explicit floor on the
expected suite set so a vanished suite is reported by name instead of
folded into "all stages passed."

## 6. Content scans cannot see commit metadata

**Trap:** every gate built to catch a leaked identifier in this pack ran
against file *content* — a `git archive` extraction, a working-tree walk.
None of them could see the commit graph itself, because a `git archive`
extraction is files and nothing else.

**Instance:** per `d55be18`'s commit message, a personal email sat in the
author and committer fields of every one of this repo's first five commits,
through four green release-scrub runs, an independent oppositional review,
and a delta review — "None could see it: every scan ran against `git
archive` extractions... GitHub's push protection caught what we had not
built."

**Rule:** scan `git log --all`, not `HEAD` and not `refs/heads/*` alone — a
history rewrite (`filter-branch` or equivalent) leaves the original commits
reachable from a `refs/original/...` backup ref that sits outside
`refs/heads`, invisible to `git push --all`/`--tags` but fully reachable
from an explicit mirror-style push.

**What enforces it now:** `scripts/check_commit_metadata.py`, added in
`d55be18` alongside its own test file
(`scripts/test_check_commit_metadata.py`) — its docstring §1 pins the
history-rewrite backup-ref case explicitly, verified against a throwaway
repo before being written: a commit orphaned under
`refs/original/refs/heads/main` shows up under `git log --all --oneline`
even though it is invisible to `git push --all`/`--tags`.

## 7. Two verification routes over the same subset are the same net held twice

**Trap:** a pytest suite and a black-box example runner look like two
independent layers of coverage. They aren't, if both of them only ever
drive the same subset of the guard's actual behavior.

**Instance:** before `d55be18`, both `.claude/hooks/test_no_swallowed_errors.py`
and `examples/03_no_swallowed_errors/run.sh` exercised only the Python/AST
shape of `no_swallowed_errors.py` — `examples/03`'s fixture is a bare
`except Exception: pass` in a `.py` file, nothing in either the pytest
suite or the example runner drove the Go or PowerShell branches. Both
"passed." Neither told you the escape-marker contract didn't hold in
either non-Python tier at all (Lesson 2, above) — the gap that `d55be18`'s
mutation pass actually found.

**Rule:** independence of *mechanism* (a different test runner, a
different invocation style) is not independence of *coverage*. Ask what
inputs each route actually drives, not how many routes exist.

**What enforces it now:** post-`d55be18` coverage spans all three language
tiers in both the pytest suite and the example fixtures;
[CONTRIBUTING.md §9](../CONTRIBUTING.md#9-provenance-ledger--classify-your-own-test-honestly)'s
PROVEN-FAILS / NEGATIVE-ONLY / UNTESTED ledger exists specifically so a
contributor can name, per guard and per shape, which of these three states
actually holds instead of rounding "a test file exists" up to "tested."

## 8. An executed proof outranks a read citation

**Trap:** a source-code citation that is real text, copied correctly,
still fails if it's filed at the wrong line number — and that kind of error
survives a grep for the quoted string, because the string really is in the
file. It only fails a *read* of the specific line cited.

**Instance:** `adapters/dsh/NOTES.md`'s "Post-review correction" records
exactly this against its own earlier draft. An entry originally cited
`packages/core/agent-loop/src/agent.ts:295-299` <!-- doc-ref-ok: path is inside the deepseek-harness clone, not this repo --> for the agent loop's
stop-condition re-test, quoting `if (!this.inbox.hasPending) return false`.
That line of code is real — it just lives at `:324`, in a different method.
The correction was found by re-reading the source, not by re-reading the
note, and the file says so rather than silently swapping the line number.
By contrast, `adapters/dsh/bin/codec-mapping-proof.mjs` is a literal,
copy-pasted port of the real exit-2 branch in dsh's `codec.ts` <!-- doc-ref-ok: path is inside the deepseek-harness clone, not this repo -->, run against
real `_dispatch.py` output — its claim is backed by an execution, not a
citation.

**Rule:** an executed proof against real output outranks a read-and-cited
line number. `NOTES.md`'s own convention makes the difference explicit by
marking every claim RAN or NOT RUN rather than leaving read-only citations
looking equivalent to executed ones.

**What enforces it now:** the RAN/NOT RUN convention throughout
`adapters/dsh/NOTES.md`, and `adapters/dsh/bin/codec-mapping-proof.mjs` /
`adapters/dsh/bin/smoke-test.sh` as the two claims in that adapter actually
backed by execution rather than by a citation.

## 9. Mutation testing's own self-deception

**Trap:** a mutation-tested suite still lies to you in two specific ways —
by reporting a mutation as applied when it silently wasn't, or by turning
red for a reason unrelated to the planted failure.

**Instance:** [CONTRIBUTING.md §2](../CONTRIBUTING.md#2-the-mutation-check--a-test-must-be-seen-red-once)
names the risk directly: "A test that has never been observed failing has
not been shown to test anything. It could be checking the wrong field,
catching the wrong exception, or passing because of a typo that makes the
assertion vacuous." The independent oppositional review (`8a57cd2`) treated
this as load-bearing rather than assumed: it "rebuilt the guard→test
mapping from the test sources rather than any doc table, and hash-verified
four mutations as actually applied" before accepting any test's pass/fail
as meaningful.

**Rule:** confirm the planted mutation actually landed (don't trust that a
patch step succeeded), and confirm a test's failure names the planted
defect specifically — not any red, from any cause.

**What enforces it now:** CONTRIBUTING.md §2's five-step mutation check
(write the test, break the guard on purpose, watch it fail, restore,
confirm green) — explicitly named in §8 as one of the bar items CI cannot
enforce ("it cannot confirm that you broke your guard on purpose, watched
the test go red, and restored it"), which is why the reviewer's own
hash-verification step exists as a check on the check.

## 10. A printed example that doesn't reproduce is the worst defect a receipts product can ship

**Trap:** verifying a worked example once does not keep it true — the next
unrelated commit can silently invalidate it, and nothing notices unless
something re-executes the example against the current tree.

**Instance:** the oppositional review (`8a57cd2`, finding H1) found a
README worked example that printed `exit 2` and actually returned `0` — the
guard only blocks mutating a test file that already exists on disk, and the
copy-pasteable command omitted that precondition, so the first thing a
skeptic pasted returned the opposite of the documented answer. It was
fixed the same day. The very next commit that touched the shipped
`engine_dirs` default (`c278ace`) silently re-broke two *different* worked
examples that the H1 fix had just repaired — both now printed a
config-error message instead of the documented one. `8c41602` names the
root cause: "two sequential changes, each verified alone, never jointly
re-verified. `examples/` is machine-checked by `run_tests.sh`; README prose
was not. That asymmetry let the same class of defect land twice, both
times found by an external reviewer rather than by this repo's own gates."

**Rule:** verified prose is not verified once it's been true — it needs a
mechanism that re-executes it against the current tree on every run, not a
human re-reading it after every change.

**What enforces it now:** `examples/12_readme_examples`, added in
`8c41602`. Its `extract_readme_blocks.py` parses README.md's own fenced
worked-example blocks at run time and executes them, asserting the real
exit code and the real first line of stderr against what the README
prints, wired into `run_tests.sh` — so a stale claim fails the suite
instead of waiting for the next external reviewer to notice by eye.

## 11. Escape hatches need adjudication, not just a reason on file

**Trap:** requiring a reason after an escape marker's colon (Lesson 2)
stops a bare, unexplained override. It does nothing about a *false* reason
— nothing downstream ever reads whether the stated reason is true.

**Instance:** `5cfa8f5`'s commit message states the gap plainly: "Every
guard's escape marker requires a reason after the colon, but nothing
downstream in this pack reviews whether the reason is TRUE."

**Rule:** an override with a reason attached is not the same claim as an
override with a *reviewed* reason — the first is a comment, the second is
an actual check on the diff it excuses.

**What enforces it now:** `scripts/check_escape_markers.py`, a diff-scoped
CI gate wired as a blocking `escape-markers` job in `.github/workflows/ci.yml`
on every pull request. Tier A extracts every marker added in the diff
(across all nine markers this pack ships, read live from each governing
hook's own regex) and fails outright on a bare marker, or requires a
reasoned one to be named in an `Escape-Markers:` commit trailer. An
optional Tier B, gated on `ANTHROPIC_API_KEY`, runs a cold `claude -p`
adjudication of whether the stated reason actually matches its diff hunk —
ambiguous folds to fail, mirroring this pack's own tampering-vouch rule for
test edits.

## 12. Show the correction history

**Trap:** the easiest way to make a claim look clean is to quietly fix it
and move on. That produces a document that reads as though the mistake
never happened — which is a worse receipt than one that shows the mistake
and the fix.

**Instance:** `adapters/dsh/NOTES.md` keeps both its misattributed
`agent.ts:295-299` <!-- doc-ref-ok: path is inside the deepseek-harness clone, not this repo --> citation (Lesson 8) and the paragraph correcting it, in
place, rather than silently editing the line number and moving on. The same
instinct runs through this repo's commit history at the doc level: `8a57cd2`
(finding H2) replaced five stale, unhedged test counts with "run it
yourself" rather than quietly refreshing the numbers to look current, and
recorded the finding — "one moved 41→71 between two runs minutes apart" —
instead of omitting it.

**Rule:** a correction left visible, with what was wrong and why, is a
stronger receipt than a claim that merely reads clean — a reader can check
that the *process* catches its own mistakes, not just that the current
text has none.

**What enforces it now:** nothing machine-checks that a correction stays
visible rather than getting silently edited away — this is a convention,
not a gate, the same honest limit CONTRIBUTING.md §8 states for the
mutation check (Lesson 9). What's structural instead:
[CONTRIBUTING.md §9](../CONTRIBUTING.md#9-provenance-ledger--classify-your-own-test-honestly)'s
provenance ledger and `adapters/dsh/NOTES.md`'s own append-only convention
(each correction is a new dated section, not an edit to the old one) both
make "here is what I got wrong" a first-class, retained artifact rather
than a diff that vanishes into the next revision.
