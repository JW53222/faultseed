# faultseed for dsh (DeepSeek Harness / Cordis)

**PARTIAL — the exit-code mapping was exercised directly; end-to-end blocking
through a running dsh agent was NOT observed.**

This package is a dsh **bundle** (per `docs/user/develop/basic/publish.md` in
the deepseek-harness tree: an npm package whose `package.json` declares a
`dsh.bundle` key). It mounts `@deepseek-ai/dsh-hooks-claude-code` — dsh's own,
real bridge for running unmodified Claude Code hook configs — over
[faultseed](../../.claude/hooks/), a pack of deterministic Python hooks that
block a coding agent from weakening tests, swallowing errors, deleting tests
via the shell, etc. No dsh-side guard logic exists in this package: every
actual decision is still made by faultseed's own Python, unmodified, run
through `_dispatch.py` exactly as it runs under Claude Code today.

Every command below is shown exactly as run: from the faultseed checkout
root, using paths relative to that root (or, for `bin/codec-mapping-proof.mjs`,
no path at all — it locates its own checkout root from its own file
location). Run them the same way from your own checkout and they reproduce
as-is; nothing below is specific to the machine these proofs were captured
on.

## What "PARTIAL" means here, precisely

I read the dsh source (cited below) and ran two things for real:

1. **`_dispatch.py` itself, unmodified**, against a real deny case and a real
   allow case, run from the checkout root with a relative `CLAUDE_PROJECT_DIR`:

   ```
   $ echo '{"tool_name":"Bash","tool_input":{"command":"git rm tests/test_foo.py"}}' \
       | CLAUDE_PROJECT_DIR=. python3 .claude/hooks/_dispatch.py no_bash_test_deletion.py
   BLOCKED: this Bash command deletes or moves test files out of the suite.

     - git rm tests/test_foo.py

   Deleting tests via the shell bypasses the Edit/Write tamper guards (this is exactly how the motivating incident's test delete slipped through). Removing a test is sometimes right, but it must be a deliberate, surfaced decision. Confirm with the human first. If the deletion is intended and approved, append `# delete-tests-ok: <reason>` to the command.
   $ echo $?
   2
   ```

   (and exit `0`, no output, for `ls -la` in place of the `git rm`). Reproduce
   with `bin/smoke-test.sh` (below) — it needs no argument either; it locates
   its own checkout root the same way `bin/codec-mapping-proof.mjs` does.

2. **dsh's real codec's exit-2-blocks rule**, applied to that real subprocess
   output. `packages/hooks/hook-protocol/src/codec.ts:11` defines
   `BLOCKING_EXIT_CODE = 2`; `:63-70` maps exit 2 to `decision:'block'` with
   trimmed stderr as `reason`. `bin/codec-mapping-proof.mjs` is a literal port
   of that one branch (not a reimplementation of the whole codec, not a
   guess), run against the real `_dispatch.py` subprocess above, with **no
   argument** — it derives its own checkout root from `import.meta.url`
   (three directories up from `adapters/dsh/bin/`), not a hardcoded or
   machine-specific path:

   ```
   $ node bin/codec-mapping-proof.mjs
   --- deny: git rm of a test file ---
     real subprocess exit code: 2
     codec.ts exit-2 branch decoded decision: block
     reason (from real stderr): BLOCKED: this Bash command deletes or moves test files out of the suite.
     PASS (expected block=true, got block=true)
   --- allow: ordinary command ---
     real subprocess exit code: 0
     codec.ts exit-2 branch decoded decision: (undefined)
     PASS (expected block=false, got block=false)
   ```

**What I did NOT run:** a real `dsh` agent process, the
`@deepseek-ai/dsh-hooks-claude-code` bridge itself, or the ACP e2e test that
exercises this exact bridge shape
(`examples/acp-agent/tests/hooks.e2e.ts` in the deepseek-harness clone — it
needs a real model call gated on `DEEPSEEK_API_KEY`, which is not configured
here). I also could not install the monorepo: `pnpm` is not on `PATH`,
`corepack` reports `pnpm@11.7.0` pinned by `package.json`'s
`packageManager` field, and the repo's `engines.node` requires
`^22.19.0 || >=24.0.0` while this machine runs Node `v20.19.2` — below floor.
I did not attempt to work around the Node version or install a matching
toolchain; that was a deliberate stop at the ~15-minute research budget, not
a discovered blocker I pushed through.

So: the exit-code contract this whole bridge depends on is demonstrated
against real processes on both sides (a real faultseed hook, and a literal
copy of dsh's real mapping code) but never joined by an actual running dsh
process in between. Do not read this as "verified working" — read it as "the
one load-bearing rule was checked directly; the glue holding it together was
read, not run."

## Install

1. **Clone or link this package** into your dsh profile, per
   `docs/user/develop/basic/publish.md`:
   ```
   dsh plugin --profile <your-profile> add /path/to/faultseed/adapters/dsh
   ```
   (This appends the bundle to your profile's `dsh.profile.bundles` list and
   applies `cordis.patch.yml` as a layer, per that doc's "Install into a
   profile" section.)

2. **Point `pluginRoot` at your faultseed checkout**, not at this adapter
   package. `cordis.patch.yml` reads it from `HOOKS_HARNESS_ROOT` — a
   deliberately generic env var name, not a `faultseed` substitution (shell
   identifiers can't contain the hyphens a product name commonly has; see
   `cordis.patch.yml`'s own comment):
   ```
   export HOOKS_HARNESS_ROOT=/absolute/path/to/faultseed
   ```
   This substitutes `${CLAUDE_PLUGIN_ROOT}` in every command in `hooks.json`
   — the same substitution token a real Claude Code plugin install uses
   (`packages/hooks/hooks-claude-code/src/config.ts`'s `substituteCommand`).

3. **Drop a `harness.env` file in your actual dsh target project's root**
   (the project dsh will run against, NOT faultseed itself):
   ```
   AUDIT_HARNESS_HOOKS_DIR=/absolute/path/to/faultseed/.claude/hooks
   ```
   `_dispatch.py` reads this itself (`.claude/hooks/_dispatch.py`'s own
   `resolve_hooks_dir()`) to find the real guard scripts once it starts
   running — this is faultseed's own documented mechanism for "harness
   installed separately from the tree it audits," not something this
   adapter invented. See `NOTES.md` for why this file has to live in the
   target project rather than being expressed as another dsh config field.

4. Boot `dsh --profile <your-profile>` from inside your target project. The
   `projectDir` config (defaults to `process.cwd()`) becomes
   `CLAUDE_PROJECT_DIR` for every hook subprocess — this is what
   `no_swallowed_errors.py` / `no_type_checking_stub.py` use to resolve
   `docs/audit/audit-scope.yaml`'s `engine_dirs` in YOUR project, so it must
   be your project's root, not faultseed's.

5. Sanity-check the wiring without booting dsh at all. Run with no env var
   from inside this checkout (it self-locates); set `HOOKS_HARNESS_ROOT`
   explicitly only if you're pointing it at a *different* faultseed checkout
   than the one `bin/smoke-test.sh` ships inside:
   ```
   sh bin/smoke-test.sh
   ```

## The exit-code contract (why this works at all)

Every faultseed hook is a subprocess that reads one JSON event on stdin and
signals its verdict entirely through its **exit code**: `exit 2` = block,
anything else = allow. `_dispatch.py` (`.claude/hooks/_dispatch.py` in the
faultseed tree) is the one entrypoint every wired hook is invoked through —
it resolves where the real hook script lives, then `execv`s it, so the exit
code you see IS the real hook's exit code, unmodified.

On the dsh side, `packages/hooks/hook-protocol/src/codec.ts:11` defines
`const BLOCKING_EXIT_CODE = 2`, and lines 63-70 map that exit code to
`decision:'block'` with trimmed stderr as `reason`. That decision then flows
into `packages/hooks/hooks-claude-code/src/index.ts`'s `PreToolUse` listener
(`tools/pre-execute`, lines 238-243 in the clone I read — re-check against
your checkout, these numbers drift): a `merged.decision === 'deny'` returns
`{kind:'deny', reason: ...}` **without calling `next()`**, so the underlying
dsh tool call is never dispatched.

For `Stop`, the deny branch lives in the **same file**, lines 267-276: the
`agent/turn-stopping` listener calls `agent.steer(...)` on a deny, which
re-queues a message so the loop observes pending input and runs another step
instead of stopping. Two neighbouring citations are easy to get wrong here
and worth stating precisely, because they are in different packages:
`packages/core/agent-loop/src/agent.ts:296` only **dispatches** the
`agent/turn-stopping` event, and `:126-128` defines `steer()` itself —
neither contains the deny logic.

Neither control-flow claim was exercised in this delivery; both are cited
from source, not observed running. The one claim in this document that WAS
executed is the exit-code mapping — see `bin/codec-mapping-proof.mjs` above,
which runs the real hook as a subprocess and decodes its real exit code
through a literal port of `codec.ts`'s own branch. Prefer that receipt over
any of the citations in this paragraph: it was run, they were read.

**Nothing this package ships changes that contract.** It contributes zero
new logic — only a `cordis.patch.yml` row and a translated `hooks.json`.

## Known gaps (read before relying on this)

- **`integrator_transcript_compactor.py` (a `PreCompact` hook) cannot be
  wired through this bridge at all.** `packages/hooks/hooks-claude-code/src/
  config.ts`'s `CLAUDE_EVENTS` list is `SessionStart, UserPromptSubmit,
  PreToolUse, PostToolUse, Stop, SubagentStart, SubagentStop` — no
  `PreCompact`. It is intentionally omitted from `hooks.json`, not silently
  dropped by the parser.
- **Matcher translation is this adapter's own inference, not something dsh's
  docs assert.** `hooks.json`'s matchers were rewritten from Claude Code's
  tool names (`Edit`, `Write`, `MultiEdit`, `Bash`, `Agent`, `Workflow`) to
  dsh's own native tool names (`edit`, `write`, `str_replace_editor`, `bash`,
  `subagent`/`subagent_fork`, `workflow`) because dsh's matcher is a
  case-sensitive literal match against the query tool name
  (`packages/hooks/hook-protocol/src/matcher.ts`'s `matchesMatcher`,
  `pattern.split('|').includes(query)`), and dsh's own tools register under
  those lowercase names (`packages/shell/tool-bash/src/index.ts:243`,
  `packages/fs/tool-fs/src/edit.ts:84`, `write.ts:70`,
  `packages/fs/tool-str-replace-editor/src/index.ts:423`,
  `packages/subagent/tool-subagent/src/index.ts:83`,
  `packages/workflow/tool-workflow/src/index.ts:41`). I did not run a dsh
  agent to confirm these are the literal strings that reach
  `matchQuery` at the `tools/pre-execute` event — see `NOTES.md`.
- **"Code Mode" tool execution is unaccounted for.** dsh has an alternate
  tool-execution path (`dsh-code-runtime-worker-thread`, referenced in
  `packages/bundle/headless/cordis.patch.yml`) whose effect on what name
  reaches the matcher I did not investigate.
- The done-gate (`verify_before_done.py` / `gate_model.py`) is **not** part
  of this pack at all — see
  [../../docs/no-done-gate.md](../../docs/no-done-gate.md) for why it was
  withdrawn rather than patched. This adapter carries that same withdrawal
  forward: there is no `Stop`-event payload to wire even if the bridge's
  `Stop` handling were verified.

## Files

- `package.json` — the bundle manifest (`dsh.bundle.patch`).
- `cordis.patch.yml` — the one new plugin row.
- `hooks.json` — the faultseed hook wiring, translated for dsh (see above).
- `bin/smoke-test.sh` — exercises real `_dispatch.py` deny/allow without dsh.
- `bin/codec-mapping-proof.mjs` — applies dsh's real exit-2 codec branch to
  that same real subprocess output.
- `NOTES.md` — every file:line this package relies on, verified vs. assumed,
  and what a future maintainer must re-check when dsh changes.
