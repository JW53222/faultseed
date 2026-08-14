# subagent_closing_report

## What it blocks

A `SubagentStop` event where the subagent's own transcript does not contain
both required closing-report markers — "Changed outside the literal
request:" and "Known problems not fixed:" — co-occurring near each other in
its most recent output.

## Why this shape is worth a gate

The other eight guards in this pack watch a specific tool call; this one
watches whether a subagent, at the end of its work, actually told you the
two things that matter most: what it touched beyond what was asked, and
what it knows is still broken. Both are the kind of admission a subagent
under pressure to look done has every incentive to skip. The hook's own
history names the concrete failure it closes: a worker silently shipped
three out-of-scope file deletions while its final report said "none outside
scope" — an orchestrator caught it that time by manually diffing the
branch, but nothing in the harness would have caught it if they hadn't. A
prose rule in a docs file is only as reliable as every future reader's
diligence; this hook makes the two-line report a mechanically-checked
condition of the subagent actually finishing, not a convention that quietly
lapses under load.

## BLOCKED

```
$ mkdir -p .scratch && printf '%s\n' '{"message":{"role":"assistant","content":[{"type":"text","text":"I did the thing, all good."}]}}' > .scratch/t.jsonl
$ echo '{"agent_transcript_path":".scratch/t.jsonl","agent_type":"sonnet"}' \
  | CLAUDE_PROJECT_DIR=$PWD python3 .claude/hooks/subagent_closing_report.py
BLOCKED: your closing report is missing required honesty-guardrail lines.
  - missing: 'Changed outside the literal request: ...' ...
  - missing: 'Known problems not fixed: ...' ...
$ echo $?
2
```
Run from the repo root; `agent_transcript_path` is a relative path.

## ALLOWED

The nearest legitimate thing is not a well-formed closing report on a
different subagent — it's the *identical* marker-less transcript, but from
an agent type this hook treats as out of scope for the rule entirely:

```
$ echo '{"agent_transcript_path":".scratch/t.jsonl","agent_type":"Explore"}' \
  | CLAUDE_PROJECT_DIR=$PWD python3 .claude/hooks/subagent_closing_report.py
$ echo $?
0
```

Both commands above were run against this tree this session, using the same
`t.jsonl` fixture for both — proving the allow is the `Explore` exemption
firing, not a difference in transcript content. A separate, content-based
near-miss: a transcript that actually writes
`**Changed outside the literal request:** none` and
`**Known problems not fixed:** none` together at the end also allows —
that's the well-formed report this hook exists to require.

## The escape marker

None in the tampering-ok sense — there's no per-invocation sentinel a
subagent can write into its own transcript to waive the requirement (that
would defeat the point: the thing being checked is exactly "did you write
the honest report," so a self-granted bypass phrase would be the same hole
reopened). Two structural exemptions exist instead:

- Env `SKIP_SUBAGENT_CLOSING_REPORT=1` disables the hook entirely — a
  session-level bypass for debugging, not a per-task escape.
- `agent_type` in `{"Explore", "Plan"}` is allowed unconditionally,
  regardless of transcript content, before any transcript text is even
  read — these types are read-only by definition (no Edit/Write tool
  available to them), so there is no code-scope for the rule to police.

## Scope

Universal — `SubagentStop`, no path or `engine_dirs` gating, since it
operates on a transcript rather than a file edit. It reads
`agent_transcript_path` in preference to the older `transcript_path` — a
deliberate fix, documented in the hook's own BUG-FIX HISTORY, for a past
incident where the hook read the *parent* session's transcript (which never
contains the subagent's own closing text) and blocked every honest worker
regardless of what they wrote.

## How we know it fires

`test_complaint_payload_shape.py` (3 tests) covers the ALLOW path (a
well-formed report emits a correctly-shaped `complaint` telemetry event).
`test_subagent_closing_report_block.py` (8 tests) covers the BLOCK path
specifically — filed because the ALLOW-only sibling is exactly the "only
ever shown to accept" shape this whole pack's doctrine warns against. Run
this session, from the repo root:

```
$ python3 -m pytest .claude/hooks/test_complaint_payload_shape.py .claude/hooks/test_subagent_closing_report_block.py -q
...........                                                            [100%]
11 passed in 0.29s
```

`test_no_markers_at_all_blocks_naming_both_missing` plants a marker-less
transcript and asserts `rc == 2` naming both missing markers.
`test_exempt_agent_types_allowed_despite_marker_less_transcript` plants the
same marker-less transcript for `Explore`/`Plan` (allowed) and then, in the
same test function, for `sonnet` (blocked) — proving the allow is the
exemption firing, not the transcript coincidentally passing.
`test_prefers_own_transcript_over_parent` plants a valid report in the
subagent's own transcript with an invalid parent transcript (allowed), and
the reverse (blocked) — pinning that the parent transcript is never
consulted when `agent_transcript_path` is present, the exact shape of the
past incident named above.

## Known limits

This hook checks for the *presence and pairing* of two marker phrases in
recent transcript text — it has no way to verify that what follows either
marker is true. A subagent that writes `**Changed outside the literal
request:** none` while having, in fact, changed something outside its
scope satisfies this hook completely; the check is structural (did you say
the words, in the right shape, near each other), not semantic (is what you
said accurate). Catching that class of dishonesty is what the orchestrator
diff-review step and the diffstat annotation (when a subagent references an
`incoming/<branch>` push) are for — this hook forces the claim to exist in
writing, it does not verify the claim.

The marker regexes require a structural separator (a colon, em-dash, or
similar) immediately after the phrase, specifically to reject conjunctive
prose that merely *mentions* both phrases without writing an actual report
(e.g. "...I need to include the Changed outside the literal request and
Known problems not fixed sections..." does not satisfy the gate) — this is
a real, tested distinction, but it also means a legitimate report using
unusual punctuation the regex doesn't anticipate could, in principle, be
misjudged as absent. The co-occurrence window (2000 characters) and the
10-most-recent-blocks scan window are both tunable constants in the source,
not configurable via env var — a subagent whose closing report legitimately
spans more than 2000 characters between the two markers, or whose final
text arrives more than 10 assistant-text blocks after other tool-call
noise, would need the source edited to accommodate it.
