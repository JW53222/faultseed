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
2. The product name is not chosen yet, but "guards-pub" (this delivery's
   working directory name, not a product name) had leaked into prose,
   comments, a cordis row `id`, and a `package.json` description across
   every shipped file. Every product-name usage across `README.md`,
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
