# What each guard blocks

Nine hooks, one page each. Every page follows the same structure — what it
blocks, why the shape matters, a BLOCKED example and the nearest legitimate
ALLOWED example (both actually run against this tree, not invented), the
escape marker if one exists, the scope it fires in, the test that proves it
fires (not just that it's wired), and what it doesn't catch.

Read the "Known limits" section on every page before you trust a guard.
Every guard here has real gaps — a fixed vocabulary list, a scope config
that ships as a placeholder, a shape it deliberately doesn't try to detect —
and the doctrine this whole pack follows (see `CONTRIBUTING.md`) is that an
undisclosed gap is worse than a disclosed one. If a page's limits section
ever reads "none," that's a bug in the page, not a guard with no gaps.

**The exit-code contract, stated once because every page below relies on
it:** exit code 2 blocks the tool call; every other exit code (0, 1, an
uncaught crash landing on 1, 127) silently allows it through. This is Claude
Code's hook protocol, not this pack's choice, and it means a hook that
crashes enforces nothing while still looking installed — see
`faultseed`'s `_dispatch.py` for the fail-closed wrapper this pack runs every
guard through specifically to convert a silent crash into a loud outcome.

## The nine guards

| Guard | Blocks | Event / matcher | Escape marker | Scope-gated |
|---|---|---|---|---|
| [`protect-files`](protect-files.md) | Edit/Write to `.env*`, `package-lock.json`, `.git/…`, an existing `migrations/…` file | `PreToolUse` / `Edit\|Write` | none (hardcoded, no bypass) | no |
| [`no_test_tampering`](no_test_tampering.md) | A test file weakened: blanket skip/xfail, `assert True`, assertions removed without replacement | `PreToolUse` / `Edit\|Write\|MultiEdit` | `# tampering-ok: <reason>` | no (fires on any `is_test_file()` path) |
| [`no_swallowed_errors`](no_swallowed_errors.md) | An exception handler whose body is a bare `pass`/`...` (plus PowerShell/Go equivalents) | `PreToolUse` / `Edit\|Write\|MultiEdit` | `# swallow-ok: <reason>` | yes — `engine_dirs` (Python/PS); narrower Go-only check |
| [`no_type_checking_stub`](no_type_checking_stub.md) | A method defined only inside `if TYPE_CHECKING:`, no runtime `def` | `PreToolUse` / `Edit\|Write\|MultiEdit` | `# host-provides:` / `# type-stub-ok: <reason>` | yes — `engine_dirs` |
| [`no_bash_test_deletion`](no_bash_test_deletion.md) | `rm`/`git rm`/`git mv` of a test file or tests directory via Bash | `PreToolUse` / `Bash` | `# delete-tests-ok: <reason>` | no |
| [`no_bash_test_mutation`](no_bash_test_mutation.md) | `sed -i`/`awk -i`/`tee`/`dd`/redirect mutating an EXISTING test file via Bash | `PreToolUse` / `Bash` | `# test-mutate-ok: <reason>` | no (but `GUARDRAILS_INTEGRATOR_ROLE=1` bypasses entirely) |
| [`agent_sizing_gate`](agent_sizing_gate.md) | An `Agent` spawn with no `model`, or `model: opus/fable` without acknowledging the frontier-leaf exception | `PreToolUse` / `Agent` | `opus-leaf-ok:` / `fable-leaf-ok: <reason>` in the prompt | no |
| [`workflow_agent_sizing_gate`](workflow_agent_sizing_gate.md) | A `Workflow` script's `agent()` call site with no/invalid `model:` | `PreToolUse` / `Workflow` | `// workflow-model-ok: <reason>` | no |
| [`subagent_closing_report`](subagent_closing_report.md) | A subagent finishing without both "Changed outside the literal request" and "Known problems not fixed" markers in its recent transcript | `SubagentStop` | none (structural exemptions: `Explore`/`Plan` agent types, `SKIP_SUBAGENT_CLOSING_REPORT=1`) | no |

## The one config file worth knowing about before you install anything

Two guards — `no_swallowed_errors` and `no_type_checking_stub` — only fire
inside directories listed in `docs/audit/audit-scope.yaml`'s `engine_dirs`
key. That file ships with the literal placeholder `["src"]`. If your
repo's hand-written source lives somewhere else (`backend/`, `app/`,
`lib/`), those two guards cover **zero code** until you fix that list — and
nothing will tell you, because a directory outside `engine_dirs` and a
directory with no violations produce the identical observable output: exit
0, no stderr. Each of those two guards' own pages has a "Known limits"
section that says this again in the specific context of that guard; this is
the one fact in the whole pack worth reading twice.
