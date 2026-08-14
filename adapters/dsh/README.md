# faultseed for dsh (DeepSeek Harness / Cordis)

**VERIFIED THROUGH THE REAL BRIDGE — a guard was observed blocking a real
tool call through dsh's own unmodified bridge, matcher, codec, agent loop and
subprocess executor, with only the LLM scripted (dsh's own `MockAdapter`, the
same pattern its bridge tests use). NOT verified: a live `dsh` CLI process
with a real model choosing the tool call.**

Still open, listed here rather than buried further down, because the claim
above is now strong enough that the boundary matters in the same breath:

- The one real ACP e2e test that exercises this exact bridge shape end to end
  (`examples/acp-agent/tests/hooks.e2e.ts`) is gated on a real model call
  (`DEEPSEEK_API_KEY`), which is still not configured anywhere this package
  was built or verified.
- "Code Mode" tool execution (`dsh-code-runtime-worker-thread`) is
  unaccounted for — whether it changes what name reaches the matcher was not
  investigated.
- `ctx.shell`'s env-scrub behavior inside the sandboxed executor was read
  from a doc comment, not traced into its implementation or exercised.
- The bridge-level proof below (see "3.") registers a **fixture** tool under
  the literal name `'bash'` — not the real `@deepseek-ai/dsh-tool-bash`
  plugin, which additionally needs `systemPrompt`/`shellEnv` capability seams
  the proof didn't mount. The fixture answers "does the matcher key off the
  tool's registered name," which is what was in question; it does not
  confirm the real tool-bash plugin's own registration path end to end.

## What this is

A dsh **bundle** — an npm package that mounts
[faultseed](https://github.com/JW53222/faultseed)'s honesty-guardrail hooks
through `@deepseek-ai/dsh-hooks-claude-code`, dsh's own real bridge for
running unmodified Claude Code hook configs. No dsh-side guard logic lives
in this package: every decision is still made by faultseed's own Python,
run through `_dispatch.py` exactly as it runs under Claude Code today —
deterministic checks that block a coding agent from weakening a test,
swallowing an error, or deleting a test through the shell, each backed by
a planted-failure test proving it can fail. Deterministic engineering-risk
guards, not a statistical claim about defect rates — see the [main
repo](https://github.com/JW53222/faultseed) for the full doctrine and all
nine guards this pack wires.

## Install

**Once published, from npm:**

```
dsh plugin --profile <your-profile> add @jw53222/faultseed-dsh
```

**Straight from GitHub (works today, no npm account or publish needed):**

```
dsh plugin --profile <your-profile> add "github:JW53222/faultseed#path:adapters/dsh"
```

Either way, you still need to point `HOOKS_HARNESS_ROOT` at your faultseed
checkout and drop a `harness.env` file in your target project before a
hook actually fires — see "Install — full wiring detail" under the fold
below for the complete four-step sequence (`pluginRoot`, `harness.env`,
`CLAUDE_PROJECT_DIR`) a new install needs before the first guard runs.

## Verify it blocks — one command, no dsh session needed

```
$ sh bin/smoke-test.sh
```

Runs the real `_dispatch.py` against a real deny case and a real allow
case with no dsh process involved at all — the fastest way to confirm the
pack you installed is actually wired before trusting it inside an agent
loop.

## Links

- Main repo & doctrine: <https://github.com/JW53222/faultseed>
- What this pack found wrong in its own first 24 hours: [docs/lessons.md](../../docs/lessons.md)
- Model-agnostic agent behavioral contract: [AGENTS.md](../../AGENTS.md)
- Full build record for this adapter — every file:line relied on, verified vs. assumed: [NOTES.md](NOTES.md)

---

## Deep technical detail

Everything below is the full verification record for this adapter: what
was run versus merely read, the install narrative with real captured
command output, the exit-code contract this depends on, the known gaps,
and the npm-publish staging process. The sections above are the 30-second
version; this is the whole claim, with receipts.

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

## What "verified through the real bridge" means, precisely

I read the dsh source (cited below) and ran three things for real:

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

3. **The real, unmodified `@deepseek-ai/dsh-hooks-claude-code` bridge**,
   through dsh's own real agent loop and real bash-executor capability, with
   only the LLM scripted. `packages/hooks/hooks-claude-code` ships its own
   full-loop test harness (`tests/bridge.spec.ts` <!-- doc-ref-ok: path is inside the deepseek-harness clone, not this repo --> — a REAL bridge plugin, a
   REAL `@deepseek-ai/dsh-agent-loop`, a REAL bash-executor capability,
   scripting only the model via `MockAdapter`, the same "mock only what
   can't be real" rule the rest of this package follows). A scratch spec
   reusing that harness wired the REAL `adapters/dsh/hooks.json` `"bash"`
   `PreToolUse` matcher block — byte-identical command string — against the
   REAL faultseed `_dispatch.py` + `no_bash_test_deletion.py`, with
   `pluginRoot` pointed at this checkout via the same `${CLAUDE_PLUGIN_ROOT}`
   substitution `cordis.patch.yml` configures for real. Vitest runs these
   specs directly against `src/` (`vite-tsconfig-paths` in the repo's
   `vitest.config.ts`) — no `pnpm build` needed. Three cases, real output:

   ```
   $ FAULTSEED_ROOT=<this checkout> pnpm vitest run \
       packages/hooks/hooks-claude-code/tests/faultseed-e2e-proof.spec.ts --reporter=verbose

   --- case 1 (deny) --- {
     ran: false,
     isError: true,
     text: 'Error: BLOCKED: this Bash command deletes or moves test files out of the suite.\n...'
   }
   --- case 2 (allow) --- { ran: true, isError: false, text: 'tool ran' }
   --- case 3 (case-sensitivity) --- { ran: true, isError: false, text: 'tool ran' }

    ✓ 1. deny: tool name "bash" + real deny command -> real BLOCKED, tool never runs
    ✓ 2. allow: tool name "bash" + ordinary command -> tool runs, no block
    ✓ 3. case-sensitivity: tool name "Bash" (PascalCase) + same deny command -> matcher does NOT fire

    Test Files  1 passed (1)
         Tests  3 passed (3)
   ```

   Case 1 vs. case 3 is a real, executed confirmation that the matcher keys
   off the tool's registered `name` and is case-sensitive exactly as
   `matcher.ts`'s `matchesMatcher` reads — the biggest previously-unverified
   assumption this document carried (see "Known gaps" below and
   `NOTES.md`'s full record, including the reproducer). Full verbatim output
   and the complete spec source are in `NOTES.md`'s "2026-08-14 follow-up"
   section.

**What is still NOT run:** a live `dsh` CLI process, or the ACP e2e test that
exercises this exact bridge shape end to end
(`examples/acp-agent/tests/hooks.e2e.ts` in the deepseek-harness clone — it
needs a real model call gated on `DEEPSEEK_API_KEY`, which is not configured
here). The earlier toolchain wall (`pnpm` not on `PATH`; this machine's system
Node below dsh's `^22.19.0 || >=24.0.0` floor) turned out not to require a
system change: a user-local Node 22 tarball plus `corepack enable
--install-directory <scratch-dir>` (no root needed) got a working
Node 22 + pnpm 11.7.0 toolchain, and `pnpm install --frozen-lockfile` at the
deepseek-harness clone's root succeeded cleanly. The remaining gap is
`DEEPSEEK_API_KEY`, not the toolchain.

So: the exit-code contract this whole bridge depends on is demonstrated
against real processes on every side that doesn't require a live model call —
a real faultseed hook, a literal copy of dsh's real mapping code, AND now the
real bridge/matcher/agent-loop/subprocess-executor wired together, with a
guard genuinely observed blocking a genuine (scripted) tool call. What
remains unjoined is specifically the part that needs a live model: a real
`dsh` CLI process with `DEEPSEEK_API_KEY` set, choosing to call `bash` on its
own. Read the label above precisely — "verified through the real bridge,"
not "verified under a live agent."

## Install — full wiring detail and verification narrative

1. **Clone or link this package** into your dsh profile, per
   `docs/user/develop/basic/publish.md`:
   ```
   dsh plugin --profile <your-profile> add /path/to/faultseed/adapters/dsh
   ```
   (This appends the bundle to your profile's `dsh.profile.bundles` list and
   applies `cordis.patch.yml` as a layer, per that doc's "Install into a
   profile" section.)

   **Installing straight from GitHub instead**, per
   `docs/user/develop/basic/publish.md`'s "Installing from GitHub" section
   (`dsh plugin --profile <name> <args...>` forwards to pnpm, so pnpm's own
   install syntax applies): since this package lives in a subdirectory of the
   `faultseed` repo rather than at its root, the command is
   ```
   dsh plugin --profile <your-profile> add "github:JW53222/faultseed#path:adapters/dsh"
   ```
   using pnpm's `#path:<subdir>` git-subdirectory syntax. **Verified against
   the real public repo, then a real defect found and fixed, 2026-08-14** —
   this was a case where "no build step, should be clean" was the wrong
   question; the actual blocker was unrelated to building, and unrelated to
   the npm-scope decision too:
   - `pnpm add "github:JW53222/faultseed#path:adapters/dsh"` in a scratch
     project correctly fetched this repo's real tarball and resolved into
     `adapters/dsh/` — confirmed by the exact failure it hit next, against
     the package.json this repo shipped at the time:
     `[ERR_PNPM_BAD_PACKAGE_JSON] ... adapters/dsh/package.json: Invalid
     name: "@{{SCOPE}}/faultseed-dsh"`. **Fixed**: `package.json`'s `name` is
     now the plain, valid, unscoped `"faultseed-dsh"` — a real npm scope is
     only needed to *publish* to the npm registry, not to install straight
     from git, so the fix doesn't wait on the owner's scope decision at all;
     `bin/prepare-npm-publish.sh` (below) rewrites the name to its scoped
     form (`@<scope>/faultseed-dsh`) at publish time, and ONLY there. Local
     re-verification (a scratch `pnpm add` against a local copy of this
     directory with the fixed name) installs cleanly with no error.
   - **Loop closed, re-run against the real public repo after the fix was
     pushed:**
     ```
     $ pnpm add "github:JW53222/faultseed#path:adapters/dsh"
     Packages: +1
     dependencies:
     + faultseed-dsh 0.1.0
     Done in 2.1s using pnpm v9.15.9
     ```
     Exit 0. All four runtime files arrive —`cordis.patch.yml`, `hooks.json`,
     `bin/smoke-test.sh`, `bin/codec-mapping-proof.mjs` — confirmed present in
     the installed package, not merely listed in `files`. (Node v22.19.0;
     `files` is irrelevant to this path anyway, since a git install ships the
     raw tree rather than an `npm pack`-filtered tarball.)
   - The equivalent plain `npm install "github:JW53222/faultseed#path:adapters/dsh"`
     does **not** work at all, on either npm 9.2.0 or npm 10.9.3: npm parses
     the `#path:` syntax (confirmed via `npm-package-arg`, which does set
     `gitSubdir`) but its own installer (`pacote`'s git fetcher, read
     directly in the installed package — grep for `gitSubdir` finds no
     matches outside `npm-package-arg` itself) never applies it, so npm looks
     for `package.json` at the repo root and fails with `ENOENT`. Since `dsh
     plugin add` forwards to **pnpm**, not npm, this is not a problem for the
     documented install path — but it means the syntax above is pnpm-specific
     and would silently need a different shape if `dsh plugin` ever forwarded
     to npm instead.
   - Sanity-checked separately: `git ls-files adapters/dsh` and
     `package.json`'s `files` array agree — every `files` entry exists in the
     git tree, and (irrelevant to this specific gap, but worth recording) a
     GitHub-direct install fetches the **whole git tree** under
     `adapters/dsh/` regardless of `files` — `files` only filters `npm
     pack`/`npm publish` output, not a git-ref tarball fetch. So there is no
     "files says X but the repo lacks X" gap, and no runtime file this
     install path fails to deliver once the name is fixed.

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

Of the two control-flow claims above, the `PreToolUse` one is now backed by
execution, not just citation: item 3's bridge-level proof (above) shows a
denied tool call never runs (`ran: false`) and the result comes back as an
`isError` with the real hook's stderr as the reason — that IS
`merged.decision === 'deny'` returning without calling `next()`, observed,
not read. The `Stop`-event `agent.steer(...)` claim was NOT exercised by that
proof (it only drove `PreToolUse`) and remains cited from source only. The
exit-code mapping itself is separately, directly executed — see
`bin/codec-mapping-proof.mjs` above, which runs the real hook as a subprocess
and decodes its real exit code through a literal port of `codec.ts`'s own
branch.

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
  docs assert** — though the CORE mechanism behind it is now confirmed by
  execution, not just reading. `hooks.json`'s matchers were rewritten from
  Claude Code's tool names (`Edit`, `Write`, `MultiEdit`, `Bash`, `Agent`,
  `Workflow`) to dsh's own native tool names (`edit`, `write`,
  `str_replace_editor`, `bash`, `subagent`/`subagent_fork`, `workflow`)
  because dsh's matcher is a case-sensitive literal match against the query
  tool name (`packages/hooks/hook-protocol/src/matcher.ts`'s
  `matchesMatcher`, `pattern.split('|').includes(query)`), and dsh's own
  tools register under those lowercase names (`packages/shell/tool-bash/src/
  index.ts:243`, `packages/fs/tool-fs/src/edit.ts:84`, `write.ts:70`,
  `packages/fs/tool-str-replace-editor/src/index.ts:423`,
  `packages/subagent/tool-subagent/src/index.ts:83`,
  `packages/workflow/tool-workflow/src/index.ts:41`). **Resolved by
  execution for `bash`** — see item 3 above: a tool registered under the
  literal name `'bash'` was matched and blocked by this exact translated
  matcher, and the identical deny command against a tool named `'Bash'`
  (Claude Code's own PascalCase) was NOT matched, through real
  `matchesMatcher`/`tools/pre-execute` code, not a description of it. **Still
  read-only, not run**, for the other five names (`edit`, `write`,
  `str_replace_editor`, `subagent`, `subagent_fork`, `workflow`) — the proof
  only drove a `bash`-named tool call; it did not register or call fixtures
  under the other five, so their registration strings are confirmed by
  reading `packages/fs/tool-fs/src/edit.ts:84` etc. only, the same as
  before.
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
- `bin/prepare-npm-publish.sh` — **not shipped in `files`** (it is a
  repo-only operator tool, not part of the installed package). Staged,
  not-yet-applied prep for npm publish: rewrites the unscoped `name` to its
  scoped form, flips `private` to `false`, and sets `repository`, then
  verifies its own result. See "Publishing to npm" below. Does not run `npm
  publish` itself.
- `NOTES.md` — every file:line this package relies on, verified vs. assumed,
  and what a future maintainer must re-check when dsh changes.

## Publishing to npm (staged, not yet applied)

No npm account exists for this project yet, and the scope it will publish
under has not been decided — so `package.json` currently ships
`"private": true` and an unscoped `"name": "faultseed-dsh"`: a scope is only
needed to *publish* to the npm registry, not to install (this is also why
the unscoped name doesn't block the GitHub-direct install path documented
above — see that section), and `private: true` is the deliberate guard
against an accidental `npm publish` in the meantime. `bin/prepare-npm-publish.sh`
does the three mechanical edits in one step once a scope exists:

```
SCOPE=your-npm-scope sh bin/prepare-npm-publish.sh
```

It rewrites `name` from `faultseed-dsh` to `@your-npm-scope/faultseed-dsh`
(refusing to run if `name` isn't exactly the unscoped literal already — the
idempotency guard against double-applying), flips `private` to `false`, adds
a `repository` field (`type: git`, this repo's URL, `directory:
adapters/dsh`), then re-reads its own output and fails (restoring the
original file from a backup) if `name` isn't EXACTLY
`@your-npm-scope/faultseed-dsh`, `private` isn't actually `false`, or any
`files` entry is missing from disk — see the script's own header comment for
the exact checks and for why the verification checks the literal target
string rather than merely "no placeholder token remains" (an earlier
revision of this script did the latter, which is exactly the
silently-passes-while-doing-nothing shape this whole pack exists to catch).
It does not run `npm login` or `npm publish`; those remain separate,
deliberate steps for whoever holds the account. Verified 2026-08-14 against
scratch copies of this package: a normal run rewrites all three fields and
passes verification; a second run against the now-scoped copy is correctly
refused (idempotency guard); an invalid `SCOPE` (e.g. containing a space) is
rejected before any write; and a simulated `files`-array/disk mismatch (a
listed file deleted) is caught by the verification step and the original
`package.json` is restored unchanged.
