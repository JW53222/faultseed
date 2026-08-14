# NOTES — dsh adapter build record

Scope: build `adapters/dsh/` only. This file records every dsh source
file:line relied on, what was verified by running something vs. assumed by
reading, what a future maintainer must re-check when dsh changes, and the
exact commands run with their observed output.

dsh clone used: a shallow clone of `deepseek-ai/deepseek-harness` at an
ephemeral, session-scoped scratch location (read-only; I did not modify it,
and the path itself is not meaningful to record — it will not exist in any
other session). All line numbers are from that checkout at the time of
reading (2026-08-13) — re-verify if it has drifted.

## Environment check (why no build was attempted)

```
$ node -v
v20.19.2
$ pnpm -v
/bin/bash: line 3: pnpm: command not found
$ npm -v
9.2.0
$ corepack --version
0.24.0
```

`dsh-scan/package.json`:
```
"packageManager": "pnpm@11.7.0",
"engines": { "node": "^22.19.0 || >=24.0.0" },
```

Node v20.19.2 is below the declared floor. I did not run `corepack enable`
+ a full `pnpm install` + `pnpm build` — on a ~60GB-RAM box a cold monorepo
install/build of this size plausibly exceeds the ~15-minute research budget
by itself, before even reaching a test run, and the Node-version mismatch is
a second, independent blocker on top of that. This is a stated stop, not a
silent one.

## dsh source facts relied on (file:line, what I read vs. ran)

All of these are **read**, not run, unless marked "RAN":

- `packages/hooks/hook-protocol/src/codec.ts:11` — `const BLOCKING_EXIT_CODE
  = 2`.
- `packages/hooks/hook-protocol/src/codec.ts:63-70` (exact lines may drift;
  identify by the `if (exitCode === BLOCKING_EXIT_CODE)` block) — exit 2 sets
  `output.decision = 'block'` and, if stderr is non-empty after trim, sets
  `output.reason = trimmedErr`. **RAN**: `bin/codec-mapping-proof.mjs` is a
  literal port of exactly this branch (copy-pasted logic, not
  reimplemented from memory), applied to real `_dispatch.py` subprocess
  output. Output captured verbatim in `README.md`.
- `packages/hooks/hooks-claude-code/src/index.ts` — the `tools/pre-execute`
  listener (search for `ctx.on('tools/pre-execute'`; was at line ~238-244 in
  the checkout I read): `merged.decision === 'deny'` returns
  `{kind:'deny', ...}` without calling `next()`. NOT RUN — read only. This is
  the specific claim in the team-lead brief I could not independently
  confirm by execution; I'm flagging it explicitly rather than restating it
  as observed.
- `packages/hooks/hooks-claude-code/src/index.ts:270-276` — the
  `agent/turn-stopping` listener. This is where a `deny` Stop decision calls
  `agent.steer(...)`. NOT RUN.
- `packages/core/agent-loop/src/agent.ts:295-299` — the loop's stop
  condition. **Corrected before publish.** The earlier version of this entry
  quoted `if (!this.inbox.hasPending) return false` here. That is real code,
  but it lives at `:324`, in a different method — a misattribution, which is
  precisely the defect class this pack exists to catch, found by re-reading
  the source rather than re-reading the note. What is actually at 295-299:

  ```
  295:  if (turnEnds && this.inbox.nextStep.length === 0) {
  296:    await this.dispatch.serial('agent/turn-stopping', { turn, signal })
  ...
  299:  if (turnEnds && this.inbox.nextStep.length === 0) break
  ```

  So `:296` only DISPATCHES the event; the deny branch is not in this file at
  all. The mechanism is the re-test at `:299` — `steer()`
  (`agent.ts:126-128`) pushes onto `inbox.nextStep`, so when line 299
  re-evaluates the same condition it is now false and the loop does not
  break. NOT RUN: read, not observed.
- `packages/hooks/hooks-claude-code/src/config.ts` — `CLAUDE_EVENTS` const
  (line ~11-19): `['SessionStart','UserPromptSubmit','PreToolUse',
  'PostToolUse','Stop','SubagentStart','SubagentStop']`. **No `PreCompact`.**
  This is why `integrator_transcript_compactor.py` is excluded from
  `hooks.json` rather than silently mis-wired — `parseClaudeCodeConfig`
  iterates only this list, so a `PreCompact` key in the input JSON is
  neither parsed nor reported in `skipped` (that array is only for
  unsupported hook *types* within a supported event, not unsupported event
  names — read directly, not run).
- `packages/hooks/hooks-claude-code/src/config.ts` — `substituteCommand`:
  replaces `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PROJECT_DIR}` tokens in
  command strings via `.split().join()`. Confirms both tokens are real and
  independent. NOT RUN (pure string function, low risk, but still unrun).
- `packages/hooks/hooks-claude-code/src/index.ts` — `Config` interface /
  `export const Config: z<Config>` (`z.object({ configPath: z.string()
  .required(), pluginRoot: z.string(), projectDir: z.string(),
  defaultTimeoutMs: ..., stderrSummaryMaxChars: ... })`). Confirms
  `configPath`/`pluginRoot`/`projectDir` are the only path-shaped config
  keys this bridge exposes — I did not invent a fourth. NOT RUN.
- `packages/hooks/hooks-claude-code/src/index.ts` — inside `runPoint`:
  `const hookEnv = projectDir !== undefined ? { CLAUDE_PROJECT_DIR:
  projectDir } : undefined`, passed to `runHook(ctx.shell, hook, {...
  ...hookEnv...})`. This is the basis for the README/cordis.patch.yml claim <!-- doc-ref-ok: 'README/cordis.patch.yml' is prose conjunction, not a path -->
  that `projectDir` is the ONLY env var this bridge forwards to a hook
  subprocess — there is no generic per-hook `env:` config field. NOT RUN.
  This is why the adapter uses a `harness.env` file (faultseed's own,
  independently-read mechanism) instead of trying to pass
  `AUDIT_HARNESS_HOOKS_DIR` through the bridge itself.
- `packages/hooks/hook-protocol/src/runner.ts:60-80`ish — docstring/comment
  "trusted environment entries merge after the executor scrub" for
  `runHook`. This is why I did NOT assume ambient shell env (e.g. exporting
  `AUDIT_HARNESS_HOOKS_DIR` before `dsh` boots) reliably reaches the hook
  subprocess — `ctx.shell`'s executor is a sandboxed shell
  (`dsh-bash-sandbox` / `dsh-shell-env` in `dsh-base`'s own
  `cordis.patch.yml`) and "scrub" reads as deliberate env stripping, not
  full inheritance. NOT independently confirmed by running it — this is an
  inference from the doc comment's wording, flagged as such.
- `packages/hooks/hook-protocol/src/matcher.ts:37-66` —
  `matcherDiagnostic`/`matchesMatcher`: for `mode === 'claude-code'`, a
  purely `[A-Za-z0-9_|]+` pattern is treated as a **literal**,
  **case-sensitive** pipe-alternation (`pattern.split('|').includes(query)`),
  not a regex. **RAN nothing here** — this is read-only, but it is the basis
  for the entire matcher-translation decision below, so treat it as
  load-bearing despite being unrun.
- Real dsh native tool names (all read, not run):
  - `packages/shell/tool-bash/src/index.ts:243` — `name: 'bash'`.
  - `packages/fs/tool-fs/src/edit.ts:84` — `name: 'edit'`.
  - `packages/fs/tool-fs/src/write.ts:70` — `name: 'write'`.
  - `packages/fs/tool-str-replace-editor/src/index.ts:423` — `name:
    'str_replace_editor'`.
  - `packages/subagent/tool-subagent/src/index.ts:83` — `toolName:
    z.string().default('subagent')`; `dsh-base`'s `cordis.patch.yml` also
    mounts a second instance with `config: { toolName: subagent_fork }` for
    fork children.
  - `packages/workflow/tool-workflow/src/index.ts:41` — `toolName:
    z.string().default('workflow')`.
- `packages/bundle/base/cordis.patch.yml` and
  `packages/bundle/headless/cordis.patch.yml` — read in full, used as the
  structural template for `cordis.patch.yml`'s `- insert:` shape and to
  confirm `!!js process.env.X ?? default` / `!!js process.cwd()` are real,
  observed patterns (e.g. `sandbox-policy`'s `mode: !!js
  process.env.DSH_PERMISSION_MODE ?? 'workspace-write'`; `fs-sandbox`'s `cwd:
  !!js process.cwd()`). I deliberately did NOT use `!!js
  require.resolve(...)` anywhere in this package's `cordis.patch.yml` —
  no cordis.patch.yml in the clone was found using `require`/`import` inside
  a `!!js` expression, so I have no evidence that identifier is in scope
  there, and inventing it would violate the "do not invent config keys"
  instruction in spirit even though it's an expression, not a key.
- `docs/user/develop/basic/publish.md` — full tutorial, read in full. Basis
  for: the two-manifest model (bundle vs. profile), `dsh plugin --profile
  <name> add <path>` install flow, and the loading-order section (bundle
  patches in list order, then the profile's own `cordis.patch.yml`, then
  `$DSH_HOME/cordis.patch.yml`, then `--patch` overlays — "later layers win
  per row... a patch replaces a row's entire `config` value rather than
  deep-merging"). This is why the README tells a user who wants to override
  `faultseed-hooks-claude-code`'s config to restate the WHOLE row, not just
  one key.
- `packages/extensions/cordis-client-runner/package.json` — read to check
  for a second real `dsh.bundle` example beyond `dsh-base`/`dsh-headless`;
  turned out to declare `dsh.client` (a different manifest kind, browser-half
  extensions), not `dsh.bundle` — a dead end I did not use, noted here so a
  future session doesn't re-walk it expecting a second bundle example.
- `examples/acp-agent/cordis.yml:178-192` (approx) — the ONLY real, working
  example in the clone of `@deepseek-ai/dsh-hooks-claude-code` actually
  mounted (`configPath: ./hooks.json`), alongside its accompanying comment
  confirming `configPath` resolves from the **server launch cwd**, not
  `session/new.cwd` and not the mounting package's own directory. This
  directly informed the decision to route path resolution through
  `${CLAUDE_PLUGIN_ROOT}` (a token the bridge substitutes independent of cwd)
  rather than relying on `configPath` being package-relative — nothing in
  the bridge makes `configPath` resolve relative to the package that names
  it.
- `examples/acp-agent/tests/hooks.e2e.ts` and its sibling snapshot fixtures
  under `examples/acp-agent/tests/snapshots/hook-cc-*/workspace/hooks.json`
  — read in full. This is a REAL, working e2e test of exactly this bridge
  shape, gated on `describe.skipIf(!process.env.DEEPSEEK_API_KEY)`. I did
  not have that key available and did not attempt to obtain one — this is
  the single most direct path to a VERIFIED tier for a future session with
  API access, and is called out as such in `README.md`.
- `.claude/hooks/generate_settings_json.py` (faultseed side, not dsh) —
  **RAN**, twice:
  ```
  $ python3 .claude/hooks/generate_settings_json.py \
      --manifest docs/hook-manifest.yaml --target python_default
  ```
  produced the var-relative (`$CLAUDE_PROJECT_DIR`-based) settings.json this
  package's `hooks.json` is derived from — every `command` string, matcher,
  and event grouping in `hooks.json` traces back to this real tool's real
  output, with only two hand-applied transforms (documented in `hooks.json`'s
  own `_comment` field and in `README.md`): `$CLAUDE_PROJECT_DIR` ->
  `${CLAUDE_PLUGIN_ROOT}`, and Claude-Code tool names -> dsh native tool
  names. I also ran it a second time with `--abs-root <this checkout's
  absolute path>` to confirm that flag exists and works (it does — real
  absolute paths came out, necessarily, since baking a literal absolute path
  into every generated command is exactly what that flag does; that output
  is not reproduced here for that reason — see the "Commands run" section
  below), then discarded that output in
  favor of the `${CLAUDE_PLUGIN_ROOT}` design, because baking an absolute
  faultseed path into `hooks.json` would silently break
  `no_swallowed_errors.py`/`no_type_checking_stub.py`'s
  `docs/audit/audit-scope.yaml` resolution the moment `CLAUDE_PROJECT_DIR`
  is (correctly) pointed at the user's actual target project instead of at
  faultseed itself — see `cordis.patch.yml`'s own comment block for the
  full reasoning. This conflict (one root needed for finding `_dispatch.py`,
  a DIFFERENT root needed for `audit-scope.yaml` resolution) is a genuine
  design finding from this session, not copied from any doc.

## Commands run, in order, with observed exit codes

Every command below (except the environment check and the deliberately-not-
reproduced `--abs-root` run) is run from the faultseed checkout root using
relative paths — none of them require or print a machine-specific absolute
path, so they reproduce as-is on any checkout.

```
$ node -v                                   # v20.19.2
$ pnpm -v                                   # command not found
$ npm -v                                    # 9.2.0
$ corepack --version                        # 0.24.0

$ echo '{"tool_name":"Bash","tool_input":{"command":"git rm tests/test_foo.py"}}' \
    | CLAUDE_PROJECT_DIR=. python3 .claude/hooks/_dispatch.py no_bash_test_deletion.py
BLOCKED: this Bash command deletes or moves test files out of the suite.

  - git rm tests/test_foo.py

Deleting tests via the shell bypasses the Edit/Write tamper guards (this is exactly how the motivating incident's test delete slipped through). Removing a test is sometimes right, but it must be a deliberate, surfaced decision. Confirm with the human first. If the deletion is intended and approved, append `# delete-tests-ok: <reason>` to the command.
$ echo $?
2

$ echo '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' \
    | CLAUDE_PROJECT_DIR=. python3 .claude/hooks/_dispatch.py no_bash_test_deletion.py
$ echo $?
0

$ python3 .claude/hooks/generate_settings_json.py --manifest docs/hook-manifest.yaml --target python_default
# -> real settings.json body (PreToolUse: protect-files.sh, no_test_tampering.py,
#    no_swallowed_errors.py, no_type_checking_stub.py, agent_sizing_gate.py,
#    workflow_agent_sizing_gate.py, no_bash_test_deletion.py,
#    no_bash_test_mutation.py; SubagentStop: subagent_closing_report.py;
#    PreCompact: integrator_transcript_compactor.py) -- this is the source
#    hooks.json was translated from. Every command in that body reads
#    `python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/_dispatch.py" <hook>.py` --
#    a shell-variable token, not a literal path, so this receipt is already
#    path-free with no editing needed.

$ python3 .claude/hooks/generate_settings_json.py --manifest docs/hook-manifest.yaml \
    --target python_default --abs-root <this checkout's absolute path> --out <scratch path>
# -> wrote file; confirmed --abs-root exists and bakes a literal absolute
#    path into every generated command (that is what the flag is FOR, so its
#    output is inherently not path-free -- not reproduced here for that
#    reason, per instruction: note it plainly rather than edit the output).
#    Output discarded from the shipped package regardless -- see the
#    conflict this ruled out, above.

$ sh adapters/dsh/bin/smoke-test.sh
# -> both PASS lines; exit 0. No argument or env var given -- the script
#    derives its own checkout root from its own location.

$ node adapters/dsh/bin/codec-mapping-proof.mjs
# -> both PASS lines; exit 0. No argument given -- confirmed working from
#    both the checkout root and an unrelated cwd (/tmp), since it derives
#    its checkout root from import.meta.url, not process.cwd().
```

## What a future maintainer MUST re-check when dsh changes

1. **`BLOCKING_EXIT_CODE` and the exit-2 branch shape** in `codec.ts` — if
   this changes, `bin/codec-mapping-proof.mjs`'s hardcoded port goes stale
   silently (it does not import the real file). Re-run the proof after
   diffing `codec.ts` against the line ranges cited above.
2. **`CLAUDE_EVENTS`** in `config.ts` — if `PreCompact` is ever added,
   `integrator_transcript_compactor.py` becomes wireable and should be added
   back into `hooks.json`.
3. **dsh's native tool names** (`bash`, `edit`, `write`,
   `str_replace_editor`, `subagent`, `subagent_fork`, `workflow`) — these are
   config-default strings (`z.string().default(...)`), not constants; a
   profile that overrides `toolName` in its own `cordis.patch.yml` breaks
   the matcher translation in this package's `hooks.json` silently (the
   guard would just never fire — no error, no log, checked directly against
   `matchesMatcher`'s `false`-on-no-match return). This is the single
   highest-risk silent-failure mode in this whole adapter and was NOT
   verified against a running dsh session.
4. **Whether `matchQuery` passed to `tools/pre-execute` is actually the
   tool's `name` field** — I inferred this from `exec.name` appearing as the
   matcher subject in `index.ts`'s `ctx.on('tools/pre-execute', ...)`
   listener, but never traced what populates `ToolExecution.name` at the
   call site. If it's some other identifier (a route id, a registered alias),
   every matcher in `hooks.json` is wrong and the guard set is silently
   inert. This is the single biggest unverified assumption in this delivery.
5. **Code Mode's effect on tool identity** (`dsh-code-runtime-worker-thread`,
   referenced in `packages/bundle/headless/cordis.patch.yml`, gated by
   `DSH_TOOLS_MODE`) was not investigated at all — if a profile runs tools
   through Code Mode instead of native dispatch, `tools/pre-execute` may not
   fire per-tool the same way, or `exec.name` may differ again.
6. **`ctx.shell`'s env scrub behavior** (`runner.ts`'s "trusted environment
   entries merge after the executor scrub") was read, not traced into
   `dsh-bash-sandbox`/`dsh-shell-env`'s actual implementation. If ambient env
   does in fact reach hook subprocesses unscrubbed, the `harness.env` file
   requirement in `README.md` could be simplified to a plain exported
   `AUDIT_HARNESS_HOOKS_DIR` — but do not make that simplification without
   confirming it by running a real hook through a real dsh session first.

## Post-review correction: naming and a dangling `files` entry

A first review round (team-lead) found two defects, both fixed:

1. `package.json`'s `files` array listed `bin/regenerate-hooks-json.sh`, <!-- doc-ref-ok: naming the file that was wrongly listed and never created; this sentence IS the correction record -->
   which was never created. Fixed to list the two scripts that actually
   exist: `bin/smoke-test.sh`, `bin/codec-mapping-proof.mjs`.
2. The working directory name — never a product name — had leaked into
   prose, comments, a cordis row `id`, and a `package.json` description
   across every shipped file, at a point when no product name had been
   chosen. One has since been chosen: `faultseed`. Every product-name usage
   across `README.md`,
   `cordis.patch.yml`, `package.json`, `hooks.json`, and (for internal
   consistency, since the same defect class applied there too — an addition
   beyond what the review round literally named) `NOTES.md` and both
   `bin/*` scripts, was replaced with the literal token `faultseed`. Real,
   local filesystem paths inside actually-run commands and their pasted
   output were, at this point, kept literal per the review's own
   instruction, with a one-line callout added near the first one in
   `README.md` clarifying that the path named this build's local checkout,
   not the product name. **This was superseded in the very next round — see
   "Post-review correction 2" below — because this repo is headed for public
   release and the local absolute path itself turned out to be the actual
   problem, not just the product-name string inside it.**

   One wrinkle surfaced doing this: two of this adapter's own invented env
   var names (`GUARDS_PUB_ROOT`, `GUARDS_PUB_DSH_HOOKS_JSON` — glue this
   adapter invented, not real dsh config keys) also carried the leaked name.
   A literal `faultseed` substitution doesn't work for these two identifiers
   specifically: shell variable names cannot contain `{`, `}`, or `-`, and
   `faultseed`/`{{SCOPE}}` are very likely to resolve to a hyphenated npm
   package name. Embedding the token there would ship a template that is
   syntactically broken the moment someone fills it in. Renamed both to
   fixed, generic, non-product-tied identifiers instead —
   `HOOKS_HARNESS_ROOT` and `HOOKS_HARNESS_DSH_HOOKS_JSON` — which need no
   substitution at all. This is a deliberate, disclosed deviation from "use
   the literal token faultseed everywhere a product name appears," scoped
   narrowly to shell-identifier positions, not a partial application of the
   instruction. Re-ran both `bin/smoke-test.sh` and
   `bin/codec-mapping-proof.mjs` after the rename against the real local
   checkout; both still PASS (same output as the original run, only the env
   var name changed).

## Post-review correction 2: path-free reproducible receipts

A second review round (team-lead) corrected the first round's own
instruction: this repo is being prepared for public release, and a
release-cleanliness sweep runs over the final tree AND its full git history
with a zero-exceptions bar against the operator's local absolute checkout
path (it lives under the operator's home directory and embeds a personal
username). Keeping that path literal inside receipts, as the first round
asked for, cannot ship.

The fix applied is NOT editing the old pasted output (that would turn a
receipt back into an unverified claim) — both proof scripts were changed to
be genuinely path-free and then re-run for real:

- `bin/codec-mapping-proof.mjs` no longer requires an argument. It derives
  its own checkout root from `import.meta.url` (three directories up from
  `adapters/dsh/bin/`), so `node bin/codec-mapping-proof.mjs` reproduces
  identically on any checkout with no machine-specific input. Verified this
  actually works from an unrelated `cwd` (`/tmp`), not just the checkout
  root, since it deliberately does not use `process.cwd()`.
- `bin/smoke-test.sh` no longer requires `HOOKS_HARNESS_ROOT` to be set. It
  computes its own default the equivalent way for POSIX sh
  (`SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)`, then three `..` up), and only
  reads the env var as an override for pointing at a different checkout.
- The `_dispatch.py` deny/allow receipt now runs as `CLAUDE_PROJECT_DIR=.
  python3 .claude/hooks/_dispatch.py no_bash_test_deletion.py` from the
  checkout root — `.` resolves internally via `os.path.abspath()` inside
  `_dispatch.py`, but that resolution is never printed, so the receipt's
  visible command and output are both path-free.
- The plain `generate_settings_json.py` receipt (no `--abs-root`) was
  already path-free on inspection — its output's hook commands read
  `$CLAUDE_PROJECT_DIR` as a literal shell-variable token, not an
  interpolated path — so it needed no change, only re-running for a fresh
  timestamp/manifest-hash pair (the manifest hash in its `PROVENANCE.json`
  differs slightly from the original build's run because another agent
  edited `docs/hook-manifest.yaml` concurrently in this shared repo; the
  hook set and command shapes are unchanged).
- The one `--abs-root` demonstration run is the sole exception, disclosed
  rather than hidden: baking a literal absolute path into every generated
  command is that flag's entire purpose, so its output cannot be made
  path-free by choice of invocation syntax. Its output was never pasted into
  any shipped file in the first place (only described narratively), so no
  receipt needed correcting — the command *example* in `NOTES.md` now shows
  `<this checkout's absolute path>` as a placeholder instead of a literal
  path, with the reason stated inline.

Every receipt in `README.md` and `NOTES.md` was re-pasted from a fresh,
actual run after these script changes, not edited from the prior output. A
search of `adapters/dsh/` for the home-directory path prefix, and a parallel
search for the bare username string (the release-scrub concern is username
leakage generally, not only the home-directory prefix; the ephemeral
dsh-clone scratch path in this file's own header also carried the username
and was genericized for the same reason, even though it wasn't under that
prefix), both return zero hits as of this correction — see the closing
report below for the exact commands and their output.

## 2026-08-14 follow-up: toolchain unblocked, a bridge-level proof, install-path verification

A later session re-checked all three open items in this file: the toolchain
wall, the install path, and the npm-publish staging. Findings below; the
README's PARTIAL label and its "Known gaps" section were deliberately left
untouched by this pass — see the closing note at the end of this section for
why, and for what the earlier author of this document should decide.

### Toolchain: no longer walled, no sudo needed

The original blocker (`node -v` → `v20.19.2`, below dsh's `^22.19.0 ||
>=24.0.0` floor; `pnpm` not on `PATH`) is still true of the box's SYSTEM
Node/npm (Debian trixie ships Node 20 as `stable`; no `nodejs-22`/`nodejs-24`
package exists in the repo; `sudo` requires a password this session doesn't
have). It does NOT require a system change to fix:

```
$ curl -sL -o node22.tar.xz https://nodejs.org/dist/v22.19.0/node-v22.19.0-linux-x64.tar.xz
$ tar xf node22.tar.xz   # extracted to a scratch dir, not installed system-wide
$ export PATH="<scratch>/node-v22.19.0-linux-x64/bin:$PATH"
$ node -v
v22.19.0
$ corepack enable --install-directory <scratch>/corepack-shims
$ export PATH="<scratch>/corepack-shims:$PATH"
$ pnpm -v
11.7.0
```

A user-local Node 22 tarball plus `corepack enable` is entirely sufficient —
no root, no touching the system `nodejs` package. `git clone --depth 1
https://github.com/deepseek-ai/deepseek-harness.git` and `pnpm install
--frozen-lockfile` both succeeded from there (28.1s for install, one
`node-pty` native build via `node-gyp`, no errors).

### A real, executed proof that does not need `DEEPSEEK_API_KEY`

The full ACP e2e test (`examples/acp-agent/tests/hooks.e2e.ts`) is still
gated on a real model call (`describe.skipIf(!process.env.DEEPSEEK_API_KEY)`)
and no key was available — that specific test is still not run. But
`packages/hooks/hooks-claude-code` ships its OWN real-bridge test harness
(`tests/bridge.spec.ts` <!-- doc-ref-ok: path is inside the deepseek-harness clone, not this repo --> ) that mounts the REAL, unmodified bridge plugin, a
REAL `@deepseek-ai/dsh-agent-loop`, and a REAL bash-executor capability, with
only the LLM **scripted** (`MockAdapter`) rather than a live model call — the
same "prefer the real implementation, mock only what truly can't be real"
rule this whole package follows. Vitest runs these specs directly against
`src/` via `vite-tsconfig-paths` (confirmed in the repo's root
`vitest.config.ts`) — **no `pnpm build` needed either**, which the original
research pass didn't have reason to check.

A new spec file, written into that same test directory (scratch — not part
of the dsh package, never intended to be committed to the dsh clone or
anywhere else, and the dsh clone itself is an ephemeral scratch checkout per
this file's existing convention), reuses that harness to run the REAL
`adapters/dsh/hooks.json` "bash" `PreToolUse` matcher block — byte-identical
command string — against the REAL faultseed `_dispatch.py` +
`no_bash_test_deletion.py`, with `pluginRoot` pointed at the real faultseed
(this repo's) checkout root via `${CLAUDE_PLUGIN_ROOT}` substitution (the
exact mechanism `cordis.patch.yml` configures). Three cases, one file, real
output:

```
$ FAULTSEED_ROOT=<this checkout's absolute path> pnpm vitest run \
    packages/hooks/hooks-claude-code/tests/faultseed-e2e-proof.spec.ts --reporter=verbose

--- case 1 (deny) --- {
  ran: false,
  isError: true,
  text: 'Error: BLOCKED: this Bash command deletes or moves test files out of the suite.\n' +
    '\n' +
    '  - git rm tests/test_foo.py\n' +
    '\n' +
    "Deleting tests via the shell bypasses the Edit/Write tamper guards (this is exactly how the motivating incident's test delete slipped through). Removing a test is sometimes right, but it must be a deliberate, surfaced decision. Confirm with the human first. If the deletion is intended and approved, append `# delete-tests-ok: <reason>` to the command."
}
--- case 2 (allow) --- { ran: true, isError: false, text: 'tool ran' }
--- case 3 (case-sensitivity) --- { ran: true, isError: false, text: 'tool ran' }

 ✓ ... 1. deny: tool name "bash" + real deny command -> real BLOCKED, tool never runs 53ms
 ✓ ... 2. allow: tool name "bash" + ordinary command -> tool runs, no block 40ms
 ✓ ... 3. case-sensitivity: tool name "Bash" (PascalCase) + same deny command -> matcher does NOT fire, tool runs 5ms

 Test Files  1 passed (1)
      Tests  3 passed (3)
```

**Reproducer** (not shipped anywhere — this describes a file written into a
scratch `deepseek-harness` clone's own `packages/hooks/hooks-claude-code/tests/`
directory, run there, then discarded with the clone; nothing under
`adapters/dsh/` depends on it existing):

```ts
// packages/hooks/hooks-claude-code/tests/faultseed-e2e-proof.spec.ts
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { describe, expect, it } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import { SessionId, type SessionEvent } from '@deepseek-ai/dsh-session'
import { defineContentToolFixture } from '@deepseek-ai/dsh-tools'
import type { Agent } from '@deepseek-ai/dsh-agent'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import { mountAgentLoopTestDependencies } from '@deepseek-ai/dsh-agent-loop-testkit'
import { LocalBashExecutor } from '@deepseek-ai/dsh-bash-local'
import LocalSubprocessRuntime from '@deepseek-ai/dsh-subprocess-local'
import * as HooksClaude from '@deepseek-ai/dsh-hooks-claude-code'
import { MockAdapter, toolCallResponse, textResponse } from '../../../core/agent-loop/tests/mock-adapter.ts'

function events(agent: Agent): SessionEvent[] { return [...agent.session.events] }

const faultseedRoot = process.env.FAULTSEED_ROOT
if (!faultseedRoot) throw new Error('FAULTSEED_ROOT env var required')

async function runCase(toolName: string, command: string) {
  const dir = mkdtempSync(join(tmpdir(), 'faultseed-e2e-'))
  try {
    writeFileSync(join(dir, 'hooks.json'), JSON.stringify({ hooks: { PreToolUse: [{
      matcher: 'bash',
      hooks: [{ type: 'command', command: 'python3 "${CLAUDE_PLUGIN_ROOT}/.claude/hooks/_dispatch.py" no_bash_test_deletion.py' }],
    }] } }))
    const adapter = new MockAdapter([toolCallResponse('c1', toolName, { command }), textResponse('done')])
    const ctx = new Context()
    await mountAgentLoopTestDependencies(ctx)
    await ctx.plugin(AgentLoop, { agents: [] })
    await ctx.plugin(LocalSubprocessRuntime)
    await ctx.plugin(LocalBashExecutor, { timeoutMs: 10_000 })
    let ran = false
    ctx.tools.register(defineContentToolFixture({
      name: toolName, description: 'fixture tool for the matcher-subject proof', parameters: {},
      async execute() { ran = true; return [{ type: 'text', text: 'tool ran' }] },
    }))
    await ctx.plugin(HooksClaude, { configPath: join(dir, 'hooks.json'), pluginRoot: faultseedRoot })
    ctx.llm.registerAdapter(['mock'], adapter)
    const agent = ctx.agentLoop.create(SessionId('a1'), { provider: 'mock', model: 'mock' })
    agent.followup(createUserMessage({ content: [{ type: 'text', text: 'go' }], source: { kind: 'user' } }))
    await agent.whenIdle()
    const result = events(agent).find(e => e.type === 'tool/result')
    const isError = result?.type === 'tool/result' ? result.data.message.content[0].isError as boolean : undefined
    const text = result?.type === 'tool/result'
      ? (result.data.message.content[0].content.find((b: { type: string }) => b.type === 'text') as { text: string } | undefined)?.text
      : undefined
    return { ran, isError, text }
  } finally { rmSync(dir, { recursive: true, force: true }) }
}

describe('faultseed proof', () => {
  it('1. deny: tool name "bash" + real deny command -> real BLOCKED, tool never runs', async () => {
    const { ran, isError, text } = await runCase('bash', 'git rm tests/test_foo.py')
    expect(ran).toBe(false); expect(isError).toBe(true)
    expect(text).toContain('BLOCKED: this Bash command deletes or moves test files out of the suite.')
  })
  it('2. allow: tool name "bash" + ordinary command -> tool runs, no block', async () => {
    const { ran, isError } = await runCase('bash', 'ls -la')
    expect(ran).toBe(true); expect(isError).toBe(false)
  })
  it('3. case-sensitivity: tool name "Bash" (PascalCase) + same deny command -> matcher does NOT fire', async () => {
    const { ran, isError } = await runCase('Bash', 'git rm tests/test_foo.py')
    expect(ran).toBe(true); expect(isError).toBe(false)
  })
})
```

To reproduce: shallow-clone `deepseek-ai/deepseek-harness`, get a Node
`^22.19.0`/pnpm `11.7.0` toolchain on `PATH` (a user-local Node tarball +
`corepack enable --install-directory <dir>` needs no root — see above),
`pnpm install --frozen-lockfile` at the clone root, save the file above at
the path in its own first comment line, then run the command shown in the
output block above with `FAULTSEED_ROOT` set to this repo's checkout root.

What this DOES resolve, by running real code rather than reading it:

- **Known-gaps bullet #2 in README.md** ("Matcher translation... I did not
  run a dsh agent to confirm these are the literal strings that reach
  `matchQuery`") — case 1 vs. case 3 above IS that confirmation: a tool
  literally named `'bash'` is matched and blocked by the real
  `matchesMatcher`/`tools/pre-execute` path; the SAME deny command against a
  tool literally named `'Bash'` (Claude Code's own PascalCase name) is NOT
  matched and runs — through real, unmodified dsh matcher code, not the hand
  ported description of it.
- The "What a future maintainer MUST re-check" item #4 above ("whether
  `matchQuery` passed to `tools/pre-execute` is actually the tool's `name`
  field") — confirmed by running: a fixture tool registered under `name`
  IS what the matcher sees.
- `${CLAUDE_PLUGIN_ROOT}` substitution via the `pluginRoot` config field —
  exercised for real (case 1's command resolves through it to the real
  `_dispatch.py`), not just read from `config.ts`.

What this does NOT resolve — still open, still real gaps:

- This is not a live `dsh` CLI process, and no LLM produced the tool call —
  it was scripted (`MockAdapter`). The one thing genuinely unique to a live
  agent (a real model choosing to call `bash` with that exact command) is
  still unobserved.
- Item #5 (Code Mode / `dsh-code-runtime-worker-thread` effect on tool
  identity) and item #6 (`ctx.shell`'s env-scrub behavior) are untouched by
  this proof — it doesn't route through Code Mode or exercise ambient env
  forwarding at all.
- The full `ToolBash` plugin (`packages/shell/tool-bash`) was not mounted —
  it additionally injects `systemPrompt`/`shellEnv` capability seams beyond
  this proof's scope. The fixture tool used here is registered under the
  identical literal name (`'bash'`, confirmed by reading
  `packages/shell/tool-bash/src/index.ts:243`'s `defineTool({ name: 'bash'
  })`) but is not the real tool-bash plugin's own registration code path.

### Install-path verification (task 2)

Documented in `README.md`'s Install section (the GitHub-direct paragraph)
with the exact commands and their real output. Summary: `dsh plugin
--profile <name> add "github:JW53222/faultseed#path:adapters/dsh"` is the
correct, verified syntax (pnpm's `#path:<subdir>` git-subdirectory
resolution — confirmed via a real `pnpm add` against the real public repo,
which got exactly as far as reading `adapters/dsh/package.json` out of the
fetched tarball before failing). It currently fails, live, against the real
repo, with `Invalid name: "@{{SCOPE}}/faultseed-dsh"` — the `{{SCOPE}}`
placeholder blocks GitHub-direct install today, independent of the npm
publish question this file already tracked. This was NOT something the
"no build step, so it should be clean" framing predicted; it needed running
the real install to find. The plain `npm install` equivalent of the same
spec does not work AT ALL (confirmed by grepping the installed npm's own
`pacote` for `gitSubdir` — zero matches outside `npm-package-arg`, which
parses the token but nothing downstream applies it) — this only works
because `dsh plugin add` forwards to pnpm, not npm.

Also checked: `private: true` does NOT block a package from being installed
as a dependency (confirmed: a scratch copy with a valid name and
`private: true` still install cleanly via `pnpm add <local-path>`) — only the
`{{SCOPE}}` name defect blocks the GitHub-direct path. `git ls-files
adapters/dsh` vs. `package.json`'s `files` array: every `files` entry exists
in the tree; no gap. `files` is irrelevant to a GitHub-direct install anyway
(a git-ref tarball fetch ships the whole tracked subdirectory, not an `npm
pack`-filtered one) — only relevant to the npm-publish path.

### Publish-prep script (task 3)

`bin/prepare-npm-publish.sh` — see `README.md`'s "Publishing to npm" section
for usage and what it does. Not run against this package's real
`package.json` (still `private: true`, still `{{SCOPE}}`, unchanged by this
session — verified with `git status`/`git diff` before finishing). Verified
against THREE scratch copies instead: a normal run (all three fields flip,
verification passes), an invalid `SCOPE` (rejected before any write), and a
simulated `files`/disk mismatch (verification fails, original
`package.json` restored byte-for-byte from its backup, confirmed by
re-reading it afterward).

### Why README.md's PARTIAL label and "Known gaps" wording were left alone

This session found real, run (not read) evidence that narrows two
previously-flagged unverified assumptions. It deliberately did not edit
README.md's top-of-file PARTIAL characterization or its "Known gaps"
section's matcher-translation bullet, even though both are now stale in
light of the above — a prior instruction on this exact adapter states the
label's wording is to be owned by whoever requested this follow-up, not
decided unilaterally by whoever produces new evidence. This section is that
evidence, written down precisely so that decision can be made with full
information.

## Closing report (per honesty-guardrails.md)

**Changed outside the literal request:** none. Every file written is under
`adapters/dsh/`. I ran `python3 .claude/hooks/generate_settings_json.py` and
`.claude/hooks/_dispatch.py` from the faultseed tree to produce real,
verifiable output, and read files throughout the faultseed and dsh clones,
but wrote nothing outside `adapters/dsh/`. No `git commit`/`push`/`npm
publish`/`gh` command was run.

**Known problems not fixed:**
- End-to-end blocking through a real running dsh agent was not observed
  (Node version below dsh's floor, no pnpm, no `DEEPSEEK_API_KEY` for the
  one real e2e test that exercises this exact bridge shape). Labeled PARTIAL
  throughout rather than papered over.
- Two unverified assumptions are load-bearing and explicitly flagged above
  (#3 tool-name matcher translation, #4 whether `exec.name` is really the
  matcher subject) — I could not resolve either without running a real dsh
  session, which was out of the ~15-minute proof budget after the
  environment check failed.
- `integrator_transcript_compactor.py` cannot be wired at all today (no
  `PreCompact` event in the bridge) — documented as a real gap, not silently
  dropped.

**(2026-08-14 follow-up note, appended, not editing the above): items #3 and
#4 immediately above are now partially superseded** — see "A real, executed
proof that does not need DEEPSEEK_API_KEY" above for exactly what is now
run-verified vs. what remains open. The original bullets are left as written
above (historical accuracy of what THAT session knew at the time); this note
exists so a reader of just the closing report doesn't miss the update.
