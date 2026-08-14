# There is no done-gate here, and that is deliberate

**Nothing in faultseed checks that your tests are green before an agent finishes.**

The guards block specific *actions* — weakening a test, swallowing an error,
deleting a test through the shell. None of them runs your suite. If you install
this pack and then assume something is watching your test results, you have
assumed wrong, and this page exists so you cannot make that assumption by
accident.

That verification is yours to run.

## Why not, given that it is the obvious thing to want

A done-gate for this pack exists. It was built, it runs daily, and it detects
correctly. It is not shipped, and it was withdrawn rather than patched. Two
findings put it here, both measured rather than reasoned:

### 1. It detects but does not block

The Claude Code hook protocol treats **exit code 2, and only exit code 2**, as
blocking. The done-gate's verdict paths returned other codes:

| Return | Meaning | What the protocol did |
|---|---|---|
| `1` | a real new failure introduced by this diff | **permitted** |
| `3` | hard failure, including the gate's own vacuity assertion | **permitted** |
| `2` | syntax error | blocked |

So a genuine regression was reported and allowed through, a diff that dodged
test coverage entirely was reported and allowed through, and the only thing
that actually blocked was a syntax error. Confirmed three ways: source read,
end-to-end drive against generated settings, and live reproduction in a sealed
build.

This is the fail-open trap described in the README, in its purest form. The
gate looked installed. It logged that it had found something. It enforced
nothing.

### 2. The obvious repair makes it worse

The tempting fix is to point the Stop hook at a different, stricter component.
That was tried, on a real foreign repository, and deliberately reversed.

The stricter component classified failures as *new* (caused by this agent) or
*inherited* (already broken before it started). That classifier reads a state
file. The only thing anywhere that WRITES that state file is a shell script
that does not ship. So the state was always absent, the classifier never
engaged, and the component silently fell back to blocking on any non-zero
result at all.

Installed on a repository carrying **1,427 pre-existing failures**, it blocked
three consecutive full-suite runs — roughly 90 seconds each — before a loop
guard forced it through. Every one of those blocks was for failures the agent
did not cause.

Note how the two failure modes differ, because it matters more than either one
individually. The exit-code defect made the gate **silent** — it had nothing to
say and said nothing. The classifier defect made it **plausibly wrong** — it
read as a working strict gate, right up until somebody counted what it was
blocking on. Silence is at least honest about having nothing to say.

## The general rule this produced

> **A control's data dependencies must ship with it, or its degraded path
> becomes its only path.**

The classifier was not broken. It was correct code with a missing input, and
correct code with a missing input degrades into whatever its fallback happens
to be — which nobody chose, nobody tested, and nobody would have shipped on
purpose.

This applies to anything you add to this pack, and it is now part of the bar in
[CONTRIBUTING.md](../CONTRIBUTING.md): if your guard reads a file, a sidecar,
an environment variable, or a service, ship it or fail loudly without it. Never
degrade quietly.

## What lands here when it lands

A fixed done-gate is expected to arrive as a separate component. The acceptance
criteria are recorded now, so they are not re-litigated from memory later:

1. **The inherited-failures path must still return "allow."** Break that and a
   new user's first task hard-blocks on debt they did not create — the
   1,427-failure pathology by another route.
2. **A planted-failure test per verdict path**, not one aggregate test. This
   gate's behavior is knowable only by driving it; that lesson was paid for
   more than once.
3. **Proven against a repository that already has failing tests.** A green run
   on a clean fixture cannot falsify a dirty-repo failure — the failure mode
   requires pre-existing red to exist at all. Several independent clean
   fixtures agreed with each other while all of them were blind to it.
4. **Two known blind spots must each get their own branch**, because neither is
   covered by the obvious fix: untracked new files are invisible to `git diff`,
   and a repository with zero commits has no `HEAD` to diff against, so it
   currently reads as "skipped" rather than as an error.

## The related caveat you should read even without a done-gate

`subagent_closing_report.py` enforces the two-list closing report at a *natural
termination*. Under a turn budget, a truncated run, or an interrupted session,
there is no natural termination, so it never fires at all.

That means "no report" and "nothing to report" produce identical output
downstream. One of those means the run was clean; the other means unknown,
possibly a mess. If you run agents non-interactively under any cap, treat
**"terminated without a closing report" as a distinct failing outcome** in
whatever consumes the run. That requires no cooperation from the agent and
cannot be defeated by truncation.

This was measured, not theorized: in a counted two-arm comparison on a real
repository, neither arm re-ran its suite after its final edit and neither
produced a closing report — because both runs hit their turn budget first. The
harnessed arm did the honest thing and stated what it could not fix; the
structured report that would have made that legible to a reviewer never
arrived. You get the restraint without the report that justifies it, which is
the worse half of the trade.
