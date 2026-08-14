# Guardrail PATTERNS registry

One entry per guarded shape shipped in this tree: the hook, the event/matcher
it fires on, what it blocks, the escape marker (if any), and the test that
proves it fires. `faultseed`'s whole pitch is the doctrine in
`.claude/rules/honesty-guardrails.md` and `CONTRIBUTING.md`:

> A gate never proven to fail is indistinguishable from a gate that cannot fail.

This file exists so that claim is checkable per hook, not just asserted once
at the top.

**Maintenance: hand-maintained.** There is no generator for this file in this
tree — `CONTRIBUTING.md` doesn't assign this step to anyone either, so treat
it as implied by its own rule 1 (a new guard's PR isn't done without a
planted-failure test) and rule 9 (classify your own test's proof bucket
honestly): whoever adds or changes a guard updates its entry here in the same
PR, including the PROVES bucket.

**Proof buckets**, same vocabulary as `CONTRIBUTING.md` §9 — do not fold
NEGATIVE-ONLY into "tested":

- **PROVEN-FAILS** — a violating input is constructed, fed to the real hook,
  and rejection (exit 2) is asserted, plus the nearest legitimate input is
  asserted allowed.
- **NEGATIVE-ONLY** — a test exists but only proves clean input is accepted,
  or that the hook is wired. Looks like coverage; proves nothing about
  detection.
- **UNTESTED** — no test references the hook.

Snapshot: `python3 -m pytest .claude/hooks/ -q` → `144 passed`. Treat that as
a snapshot rather than a fact to pin, and run the command yourself. It moved
five times while this pack was being prepared for release (67 → 113 → 120 →
130 → 144) as untested guards were found and their planted-failure tests
written, and it will move again the first time someone adds a guard.

## Role + path scope (applies across hooks)

- **ENGINE-QUALITY hooks** (`no_swallowed_errors.py`, `no_type_checking_stub.py`)
  only fire on the directories listed in `docs/audit/audit-scope.yaml`'s
  `engine_dirs`, via `_common.is_engine_path()`; inert (exit 0, no output)
  outside those dirs, role-independent. `engine_dirs` ships as the literal
  placeholder `["src"]` — a common-convention guess, not a scan of your repo.
  If your source lives elsewhere, both hooks silently cover zero code until
  you edit that file. A missing or malformed `audit-scope.yaml` fails the
  OTHER direction — loud, not silent: `is_engine_path()` raises
  `AuditScopeLoadError`, caught and turned into `block()` (exit 2).
- **GENERATED/VENDORED exemption.** `_common.is_generated_path()` exempts
  paths starting with any prefix in `docs/audit/audit-scope.yaml`'s
  `generated_paths` from both engine-quality hooks — for vendored or
  machine-generated trees you do not want an agent policed on. It ships
  **empty**, which exempts nothing; that is the safe default, since a wrong
  entry here can only cause under-policing, never a false block. Unlike
  `engine_dirs`, an absent section is not an error. Anything you add is an
  allowlist entry that silently removes code from two guards' reach, so add
  it deliberately and say why.
- **HONESTY/SAFETY hooks** (`no_test_tampering.py`, `no_bash_test_deletion.py`,
  `no_bash_test_mutation.py`, `agent_sizing_gate.py`,
  `workflow_agent_sizing_gate.py`, `subagent_closing_report.py`,
  `protect-files.sh`) are universal — no `engine_dirs` gate.
- `no_bash_test_mutation.py` additionally bypasses itself entirely under
  `GUARDRAILS_INTEGRATOR_ROLE=1` — see its entry.

---

## protect-files.sh

- **EVENT**: `PreToolUse`, matcher `Edit|Write`
- **ENFORCEMENT**: hard-block (exit 2)
- **BLOCKS**: an Edit/Write whose target basename is exactly `.env` or
  matches `.env.*`; is exactly `package-lock.json`; or whose path contains a
  `.git/` or `migrations/` directory segment (leading-slash-padded match, not
  a bare substring test — `config.envoy.yaml` and `mygit/config` do NOT
  match). A brand-new (not-yet-existing) migrations file is exempt.
- **ESCAPE**: none. Hardcoded blocklist by design — a legitimate change to
  one of these paths goes through a normal commit/PR path outside the agent.
- **SCOPE**: universal (Edit|Write matcher only); reads no config, no env vars.
- **PROVES**: PROVEN-FAILS — `test_protect_files_env_overmatch.py`, 18
  functions, both directions. E.g. `test_blocks_dotenv_exact` (target `.env`)
  → `rc == 2`; `test_allows_envoy_config_yaml` (target `config.envoy.yaml`,
  the exact over-match this hook used to have) → `rc == 0`.
- **Minimal examples** (from the shipped test):
  - BLOCKED: `Write` to `.env` → exit 2, `"protected pattern '.env'"` in stderr.
  - ALLOWED (near-miss): `Write` to `config.envoy.yaml` → exit 0.

## no_test_tampering.py

- **EVENT**: `PreToolUse`, matcher `Edit|Write|MultiEdit`
- **ENFORCEMENT**: hard-block (exit 2), only when `is_test_file(path)` is true.
- **BLOCKS**: blanket `@pytest.mark.skip`/`@pytest.mark.xfail` (`skipif` is
  excluded), `pytest.skip()`/`xfail()`, `@unittest.skip`, `self.skipTest()`,
  a no-op `assert True`, Pester `-Skip`/`Set-ItResult -Skipped`; on `.go`
  files an unconditional `t.Skip`/`t.SkipNow` not guarded by an `if`, a
  commented-out `t.Run(...)`, and `//go:build ignore`; and net assertion
  removal (`removed_asserts - added_asserts > 0`) with fewer
  `# tampering-ok:` markers than the net-removed count — one marker no longer
  waives an arbitrary number of removed assertions.
- **ESCAPE**: `# tampering-ok: <reason>` (`<# tampering-ok: <reason> #>`
  PowerShell, `// tampering-ok: <reason>` Go). Reason required — a bare
  marker does not clear the block.
- **SCOPE**: universal — fires on any file `is_test_file()` recognizes
  (basename `test_*`, `*_test.py`/`*_test.go`, path contains `/tests/` or
  `/test/`, `conftest.py`, `*.tests.ps1`), regardless of directory.
- **PROVES**: PROVEN-FAILS — `test_no_test_tampering_marker_count.py`, 17
  functions. E.g. `test_two_asserts_removed_one_marker_blocked` plants two
  removed asserts with one marker → `rc == 2`;
  `test_two_asserts_removed_two_markers_allowed` → `rc == 0`.
- **Minimal examples**:
  - BLOCKED: old `"    assert a == 1"`, new `"    pass"` → exit 2.
  - ALLOWED (near-miss): old `"    assert a == 1"`, new
    `"    foo()  # tampering-ok: justified by the corresponding code change"`
    → exit 0.

## no_swallowed_errors.py

- **EVENT**: `PreToolUse`, matcher `Edit|Write|MultiEdit`
- **ENFORCEMENT**: hard-block (exit 2) on `hard_hits`. Excuse comments
  (`# TODO: good enough`, `# known issue`) and Go's ambiguous
  `x, _ := call()` are WARN-ONLY (`emit_event(verdict="warn")` + stderr, then
  allow) unless `GUARDRAILS_STRICT=1` promotes them to hard-block.
- **BLOCKS**: Python — an AST-found `except ...:` handler (unmarked) whose
  body is exactly one `pass` or `...`, searched across a NEIGHBORHOOD window
  (the enclosing function's siblings within ±`GUARDRAILS_SWALLOW_NEIGHBORS`,
  default 2, or the whole class/module for a class-/module-level edit) — not
  just the diff, so a pre-existing swallow just outside the edit still
  blocks. A handler that does anything other than a bare `pass`/`...` (e.g.
  logs and re-raises) is never flagged. PowerShell: empty/null `catch {}`,
  `-ErrorAction SilentlyContinue/Ignore`, global `$ErrorActionPreference`. Go:
  bare `_ = err` discard, empty `if err != nil {}`,
  `if err != nil { return nil }` (hard); ignored second return `x, _ :=
  call()` is soft-only — indistinguishable from Go's `(value, ok)` idiom by
  source alone.
- **ESCAPE**: `# swallow-ok: <reason>` (also `<# ... #>` PowerShell, `//` Go).
  Reason required. Handler-aware: the marker may sit on the `except` line,
  the sole `pass`/`...` body line, or a comment line between them.
- **SCOPE**: ENGINE-QUALITY (Python/PowerShell) — see "Role + path scope"
  above. Go gets its own minimal scope check (`_bindata.go` suffix or a
  `// Code generated ... DO NOT EDIT.` marker exempt) and does NOT consult
  `engine_dirs`.
- **KNOBS**: `GUARDRAILS_STRICT` (default `"0"`); `GUARDRAILS_SWALLOW_NEIGHBORS`
  (default `2`).
- **PROVES**: PROVEN-FAILS — `test_no_swallowed_errors.py`, 10 functions.
  `test_bare_pass_swallow_blocked` → `rc == 2`, `"silently swallows an
  error"` in stderr; `test_swallow_ok_marker_on_pass_line_allowed` → `rc ==
  0`; `test_bare_swallow_ok_marker_not_cleared` (marker with no reason) →
  `rc == 2`; `test_engine_scope_gate_both_directions` (identical swallow,
  `src/foo.py` blocked, `other/foo.py` allowed in the same test);
  `test_neighborhood_scan_blocks_sibling_swallow_not_touched` (edit touches
  an untouched sibling function two positions from an existing swallow,
  still blocks, `"NEIGHBORHOOD"` in stderr).
- **Minimal examples** (from the shipped test):
  - BLOCKED: `Write` to `src/foo.py` with a bare `except Exception: pass` →
    exit 2.
  - ALLOWED (near-miss): identical, `pass  # swallow-ok: deliberate
    degrade-to-default` → exit 0.

## no_type_checking_stub.py

- **EVENT**: `PreToolUse`, matcher `Edit|Write|MultiEdit`
- **ENFORCEMENT**: hard-block (exit 2)
- **BLOCKS**: a method/function name def'd only inside `if TYPE_CHECKING:` /
  `if typing.TYPE_CHECKING:` for a given class or module scope, with no
  matching runtime `def` in that same scope and no marker. Applies per-class
  INCLUDING mixins — deliberately no blanket mixin exemption.
- **ALLOWS**: `@overload` real defs, plain attribute annotations under
  `TYPE_CHECKING`, imports under `TYPE_CHECKING`, a stub that also has a
  runtime def, non-`.py` files, test files (`is_test_file()`, independent of
  and checked before the engine-scope gate).
- **ESCAPE**: `# host-provides: <reason>` or `# type-stub-ok: <reason>` on the
  stub's def line (or the line above, for a single-line stub). Reason
  required — a bare marker does not clear the block.
- **SCOPE**: ENGINE-QUALITY — see "Role + path scope" above.
- **PROVES**: PROVEN-FAILS — `test_no_type_checking_stub.py`, 12 functions.
  `test_type_checking_only_stub_blocked` → `rc == 2`,
  `"TYPE_CHECKING-only stub, no runtime def"` and `` "`bar` (class Foo)" ``
  in stderr; `test_mixin_class_gets_no_blanket_exemption_blocked` (an
  `ExecutionMixin`-style class, no free pass) → `rc == 2`;
  `test_host_provides_marker_with_reason_allowed` → `rc == 0`;
  `test_bare_marker_without_reason_not_cleared` → `rc == 2`;
  `test_stub_with_matching_runtime_def_allowed`,
  `test_overload_real_defs_allowed`,
  `test_plain_attribute_annotation_under_type_checking_allowed`,
  `test_import_under_type_checking_allowed`, `test_non_python_file_allowed`,
  `test_test_file_exempt_even_inside_engine_dir` → all `rc == 0`;
  `test_engine_scope_gate_both_directions` (identical stub, `src/foo.py`
  blocked, `other/foo.py` allowed).
- **Minimal examples** (from the shipped test):
  - BLOCKED: `Write` to `src/foo.py`:
    ```python
    from typing import TYPE_CHECKING
    class Foo:
        if TYPE_CHECKING:
            def bar(self) -> int: ...
    ```
    → exit 2.
  - ALLOWED (near-miss): same, with
    `# host-provides: LiveStrategyEvaluator defines this at runtime` on the
    line above `def bar` → exit 0.

## no_bash_test_deletion.py

- **EVENT**: `PreToolUse`, matcher `Bash`
- **ENFORCEMENT**: hard-block (exit 2)
- **BLOCKS**: per simple command (split on `&&`, `||`, `;`, newline, `|`):
  `rm <target>` / `git rm [-r][-f] <target>` where target looks like a test
  path (contains `/tests/`/`/test/`, is a bare `tests`/`test` dir, matches
  `test_*.py`/`*_test.py`/`*.Tests.ps1`/`conftest.py`, or a glob under a
  tests path); or `git mv <test-path> <non-test-path>` (moving a test out of
  the suite).
- **ESCAPE**: `# delete-tests-ok: <reason>`, checked per-line. A bare marker
  is caught explicitly and produces a distinct "needs a reason" block
  message rather than silently clearing.
- **SCOPE**: universal (Bash matcher, no engine-dir gate, no env-var reads).
- **PROVES**: PROVEN-FAILS — `test_bash_marker_reason_required.py`,
  `test_deletion_*` functions.
  `test_deletion_bare_marker_blocked_with_reason_required_message`
  (`rm tests/test_foo.py # delete-tests-ok`) → `rc == 2`, `"needs a reason"`
  in stderr; `test_deletion_marker_with_reason_allowed` → `rc == 0`.
- **Minimal examples**:
  - BLOCKED: `rm tests/test_foo.py` (no marker) → exit 2, `"deletes or moves
    test files"` in stderr.
  - ALLOWED (near-miss): `rm scratch.txt # delete-tests-ok` (bare marker on a
    non-test target — nothing to block) → exit 0.

## no_bash_test_mutation.py

- **EVENT**: `PreToolUse`, matcher `Bash`
- **ENFORCEMENT**: hard-block (exit 2)
- **BLOCKS**: per simple command, `sed -i`/`gsed -i`, `awk -i inplace`,
  `tee`/`tee -a`, `dd of=`, and truncating/appending redirects (`>`/`>>`)
  targeting an EXISTING test-path file. Creating a brand-new test file via
  redirect is allowed.
- **ESCAPE**: `# test-mutate-ok: <reason>`, same reason-required /
  bare-marker-caught structure as `no_bash_test_deletion.py`.
- **SCOPE**: `GUARDRAILS_INTEGRATOR_ROLE=1` bypasses the whole hook unconditionally before
  the event is even read — "the integrator owns test edits at merge time."
  No other env vars.
- **PROVES**: PROVEN-FAILS — `test_bash_marker_reason_required.py`,
  `test_mutation_*` functions.
  `test_mutation_bare_marker_blocked_with_reason_required_message` → `rc ==
  2`; `test_mutation_marker_with_reason_allowed`
  (`sed -i 's/x/y/' tests/test_foo.py # test-mutate-ok: matches new evaluator
  arg`, file exists) → `rc == 0`.
- **Minimal examples**:
  - BLOCKED: `sed -i 's/x/y/' tests/test_foo.py` (file exists, no marker) →
    exit 2, `"mutates an EXISTING test file"` in stderr.
  - ALLOWED (near-miss): `sed -i 's/x/y/' notes.txt # test-mutate-ok` (bare
    marker on a non-test file — nothing to block) → exit 0.

## agent_sizing_gate.py

- **EVENT**: `PreToolUse`, matcher `Agent`
- **ENFORCEMENT**: hard-block (exit 2)
- **BLOCKS**: `model` field missing/empty, or present but not one of
  `{"haiku", "sonnet", "opus", "fable"}`; or `model` in `{"opus", "fable"}`
  (frontier models) without a leaf-escape sentinel in the prompt — the
  Opus/Fable-as-leaf anti-pattern (those tiers are meant to run as standalone
  orchestrator sessions, never a frontier leaf).
- **ESCAPE**: `opus-leaf-ok: <reason>` or `fable-leaf-ok: <reason>` anywhere
  in the spawn prompt — either sentinel clears either frontier model. Reason
  required (non-empty text after the colon).
- **SCOPE**: universal (Agent-tool matcher only); no config, no env vars;
  emits `agent_spawn` telemetry on allow.
- **PROVES**: PROVEN-FAILS — `test_agent_sizing_gate.py`, 13 functions.
  `test_fable_leaf_blocked_without_reason` → `rc == 2`, `"fable"` in
  stderr (lowercased); `test_fable_leaf_with_fable_reason_passes` → `rc ==
  0`; `test_missing_model_blocked` (no `model` key) → `rc == 2`,
  `"does not declare an explicit"` in stderr; `test_unrecognised_model_blocked`
  → `rc == 2`.
- **Minimal examples**:
  - BLOCKED: `Agent(model="opus", prompt="do the thing")` → exit 2.
  - ALLOWED (near-miss): `Agent(model="opus", prompt="opus-leaf-ok: one
    subtle oppositional review")` → exit 0.

## workflow_agent_sizing_gate.py

- **EVENT**: `PreToolUse`, matcher `Workflow`
- **ENFORCEMENT**: hard-block (exit 2)
- **BLOCKS**: static-parses the Workflow tool's inline `script` (comment/
  string blanker + paren-balanced extraction of every `agent(...)` call) and
  requires `model\s*:` to appear in each call's opts region. Any call site
  missing it blocks, naming line numbers (up to 20). A `name`-only reference
  to a builtin/named workflow can't be introspected and is allowed — "the
  agent-sizing hygiene of named workflows is their author's responsibility."
  Each call site is also checked against `VALID = {"haiku", "sonnet",
  "opus"}` when `model:` resolves to a static string literal — a recognized
  key with an unrecognized value (e.g. `model: "claude-3"`) blocks too. A
  `model:` value that isn't a static literal (a variable, a template
  interpolation, a call) is treated as unverifiable, not trusted, and
  reported as its own status rather than silently passing.
- **ESCAPE**: `// workflow-model-ok: <reason>` on the same line as the
  `agent()` call. Reason required — `ESCAPE_RE` requires non-whitespace
  after the colon; a bare `// workflow-model-ok` with no reason is
  recognized separately (`BARE_ESCAPE_RE`) specifically so it does NOT clear
  the block and the message can say what's missing rather than the generic
  block text.
- **SCOPE**: universal (Workflow-tool matcher only). No config/env-var reads.
- **PROVES**: PROVEN-FAILS — `test_workflow_agent_sizing_gate.py`, 11
  functions. `test_missing_model_blocked` → `rc == 2`;
  `test_sonnet_declared_allowed`, `test_multi_call_one_missing_reports_correct_line`,
  `test_escape_with_reason_allows_missing_model` → `rc == 0`;
  `test_unrecognised_model_value_should_be_blocked_FINDING`
  (`agent(p, {model: "claude-3"})`) → `rc == 2`;
  `test_bare_escape_without_reason_should_not_clear_block_FINDING`
  (`// workflow-model-ok` with no reason) → `rc == 2`. The `_FINDING` suffix
  on the last two names is a leftover from when this hook had the gaps those
  tests were written to catch (a bare escape cleared the block; an
  unrecognized `model:` value sailed through) — both are fixed in the
  currently-shipped hook and both tests pass; the names just haven't been
  renamed to drop the historical marker.
- **Minimal examples**:
  - BLOCKED: `agent("do a thing", {subagent_type: "general-purpose"});` (no
    `model:`) → exit 2, `"agent() call site(s) without an explicit
    \`model\`"` in stderr.
  - ALLOWED (near-miss): same with `model: "sonnet"` added → exit 0.
  - BLOCKED (near-miss on the escape): `agent(p, {subagent_type: "gp"});
    // workflow-model-ok` (bare, no reason) → exit 2, not cleared.

## subagent_closing_report.py

- **EVENT**: `SubagentStop`
- **ENFORCEMENT**: hard-block (exit 2)
- **BLOCKS**: the last 10 non-empty assistant text blocks from the
  subagent's OWN transcript (`agent_transcript_path`, preferred over the
  parent's `transcript_path`) must contain both the "Changed outside the
  literal request" and "Known problems not fixed" marker phrases
  (regex-matched with a required structural separator — `:`, `:**`, `—`,
  `-` — right after the phrase; conjunctive prose mentioning both phrases
  without that separator does not satisfy it), co-occurring within 2000
  characters of each other.
- **ESCAPE**: none in the tampering-ok sense. `SKIP_SUBAGENT_CLOSING_REPORT=1`
  disables the hook entirely (session-level, not per-invocation).
  `EXEMPT_AGENT_TYPES = {"Explore", "Plan"}` allows unconditionally,
  regardless of transcript content — their deliverable is prose, not a diff.
- **SCOPE**: universal (SubagentStop; operates on transcripts, not files).
- **PROVES**: PROVEN-FAILS — `test_subagent_closing_report_block.py`, 8
  functions, plus `test_complaint_payload_shape.py` for the allow/telemetry
  path. `test_no_markers_at_all_blocks_naming_both_missing` → `rc == 2`,
  `"BLOCKED: your closing report is missing required honesty-guardrail
  lines"` and both marker names in stderr;
  `test_changed_present_known_missing_still_blocked` → `rc == 2`, names only
  the missing one; `test_markers_present_but_beyond_cooccurrence_window_blocked`
  and `test_conjunctive_prose_mentioning_both_phrases_does_not_satisfy_gate`
  → both `rc == 2`; `test_exempt_agent_types_allowed_despite_marker_less_transcript`
  (`agent_type="Explore"`, no markers) → `rc == 0`;
  `test_skip_env_disables_hook_entirely` → `rc == 0`.
- **Minimal examples**:
  - BLOCKED: transcript whose only assistant text is "I did the thing, all
    good." (no markers), `agent_type="sonnet"` → exit 2.
  - ALLOWED (near-miss): identical text, `agent_type="Explore"` → exit 0 —
    the exemption fires before transcript text is even inspected.

---

## _dispatch.py (not a guard — the entrypoint every guard above runs through)

Not a guarded shape itself, but its fail-open/fail-closed classification
decides what happens when one of the nine guards above crashes instead of
running, so it's recorded here rather than only in `README.md`.

- A **GUARDRAIL** hook (every hook above — the default classification, not an
  explicit allowlist) that fails to import is never exec'd: `_dispatch.py`
  blocks (exit 2) itself, naming the hook and the traceback.
- The one **ADVISORY** hook this tree ships,
  `integrator_transcript_compactor.py`, fails OPEN on an import error (exit
  0) but loudly — a stderr `WARNING:` plus best-effort telemetry, never
  silent.
- A hook file that doesn't resolve on disk at all is also blocked (exit 2),
  naming the resolved path and the env vars that fix it.
- **PROVES**: PROVEN-FAILS — `test_dispatch_guardrail_vs_advisory.py`, 7
  functions, each with a positive control in the same test.
  `test_guardrail_import_failure_blocks_and_never_execs` breaks `_common.py`
  in a copied hooks dir, dispatches `no_test_tampering.py` through it → `rc
  == 2`, `rc != 1` (the `!= 1` assertion is itself part of the proof: an
  exec'd-but-broken hook would exit 1 from its own uncaught ImportError, not
  the deliberate exit 2 the in-process probe writes), then re-runs against an
  unbroken copy → `rc == 0`.
  `test_unlisted_hook_name_defaults_to_guardrail_not_advisory` plants the
  identical `raise` into two files with different names — one on the
  advisory allowlist, one not — and gets different verdicts (`rc == 2` vs.
  `rc == 0`) from identical content, isolating the name as the only variable.
  `test_advisory_import_failure_allows_but_warns_loudly` → `rc == 0`, stderr
  carries a `WARNING:` and the planted marker.
