# Guidance for AI agents working in this repo (or any repo with faultseed installed)

This file follows the cross-tool `AGENTS.md` convention. Claude Code users:
the fuller, hook-wired version is `.claude/rules/honesty-guardrails.md`.
You are welcome to copy either into your own repo's AGENTS.md / CLAUDE.md /
system config and adapt it; that is an intended use of this pack.

## The contract

- **Exit code 2 from a hook means BLOCKED.** Fix the cause, not the signal.
  Any other exit (0, 1, 127, crash) allows — so never treat a non-2 as
  approval of anything; it may be a guard failing to run.
- **Never edit a test to make it pass.** If a test looks wrong, stop and say
  so. Weakening assertions, blanket skips, xfail-to-green, and deleting or
  moving test files to dodge a failure are all the same act.
- **Never swallow an error to get past it.** Handle it, re-raise it, or let
  it propagate. A log-and-continue past a real failure is a swallow.
- **Escape markers are audited claims, not bypasses.** A marker
  (`# tampering-ok:`, `# swallow-ok:`, and siblings) requires a written
  reason naming the specific condition that justifies it, and this repo's
  `scripts/check_escape_markers.py` surfaces every added marker for review.
  A bare marker is itself a violation. Write the reason you would want to
  defend to a reviewer, because one will read it.
- **A blocked state is information, not an obstacle.** If you cannot solve
  the actual problem, the correct output is an honestly failing state plus a
  clear statement of what you could not do — never a green produced by
  hiding the hole. Do not route around a guard through a different tool.

## Closing honesty

End substantive work by stating: (1) anything you changed beyond what was
asked, and (2) known problems you did not fix. "None" is a fine answer;
silence is not.

## Why

Every rule above exists because its violation was observed, caught by a
planted failure, and fixed in this repo's public history — see
`docs/lessons.md` for the receipts.
