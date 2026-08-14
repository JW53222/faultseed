#!/usr/bin/env python3
"""_dispatch.py -- hook ENTRYPOINT boundary. Resolves and execs the real hook
script from the HARNESS's own location, not the audited target tree.

THE BUG THIS FIXES: every hook command in .claude/settings.json used to be
a literal

    python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/<name>.py"

$CLAUDE_PROJECT_DIR is set by Claude Code to the AUDITED (target) tree's
root. When the harness is installed SEPARATELY from the tree it audits (its
.claude/hooks/ scripts live somewhere else on disk), that path resolves into
a tree that does not contain the hooks. Empirically this fails in TWO ways,
neither of which is a loud, attributable block:
  - plain `python3 <missing-file>` exits 2 (coincidentally the hook
    protocol's blocking code) but with a useless, non-actionable message
    ("python3: can't open file ...") that never names the fix.
  - a hook invoked through a wrapper script that does its OWN internal path
    resolution (rather than trusting $CLAUDE_PROJECT_DIR the way this file
    does) can exit 127 -- shell "command not found" -- which the Claude Code
    hook protocol treats as NON-BLOCKING. Verified empirically: hook fires,
    fails, tool call PERMITTED. This is the true "silently absent" shape:
    any hook-locating logic that assumes co-location with the audited tree
    needs the same fix this file applies, wherever that logic lives.

THE FIX: settings.json now invokes ONLY this file directly (still found via
$CLAUDE_PROJECT_DIR, since Claude Code must locate .claude/settings.json --
and this dispatcher -- inside the audited tree; that part of the coupling is
unavoidable, Claude Code has no other way to discover hook wiring). This
file's ONE job is to resolve where the harness's OWN .claude/hooks/ assets
actually live and re-exec the real hook from there.

RESOLUTION (mirrors blessed_root()'s precedence style in _common.py). The env
var is named AUDIT_HARNESS_HOOKS_DIR, not something more generic like
AUDIT_HARNESS_DIR: an env var holds one value per process, and a name generic
enough to ALSO mean some other harness asset directory (docs/audit tooling,
say, in a larger install that ships some) would let setting it for ONE
purpose silently break the other -- a single shared var whose "correct" value
depends on which consumer happens to be asking. Pick a name specific enough
that it can never be reused for something else by accident; a fresh,
narrowly-scoped name costs nothing and closes off a whole class of
future collision.
  1. env AUDIT_HARNESS_HOOKS_DIR, if set and non-empty -- the .claude/hooks dir
     itself.
  2. harness.env's AUDIT_HARNESS_HOOKS_DIR entry, at $CLAUDE_PROJECT_DIR/harness.env
     (repo root, gitignored -- not shipped as a template in this pack, so
     create it yourself with one `KEY=VALUE` line if you need this level).
     Read directly by this file via a minimal KEY=VALUE parser (duplicated
     from, not imported from, _common.py -- see _parse_env_file's docstring
     for why).
  3. co-located default: $CLAUDE_PROJECT_DIR/.claude/hooks -- an
     unconfigured / co-located install (the historical, still-supported
     case) behaves exactly as before this fix.

ESCAPE HATCH: SKIP_HOOK_DISPATCH (any value other than "", "0", "false",
"False") skips resolution ENTIRELY and exits 0 immediately -- checked as the
VERY FIRST thing, before any resolution/import that could itself raise or
exit. A documented hatch that sits AFTER an eager failure path is not a
hatch, it is unreachable (a sibling defect in this family had its escape
hatch 377 lines after an eager failure at import -- on the tree the hatch
exists to cover, execution never got there).

FAIL LOUD, NEVER SILENT: if the resolved hooks directory does not contain
the requested hook, this exits 2 (the Claude Code hook protocol's ONLY
blocking code) with a message naming AUDIT_HARNESS_HOOKS_DIR, harness.env, and
SKIP_HOOK_DISPATCH.

THIS FILE IS AN ENTRYPOINT, NOT A LIBRARY: it is never imported by another
module (only ever invoked as `python3 _dispatch.py ...` from
.claude/settings.json), so sys.exit() here is the correct, safe idiom -- the
"raise inside library code, exit at the hook entrypoint boundary" split does
not require anything fancier here, unlike _common.py's lazy __getattr__
(which exists because _common IS imported by every other hook module in this
pack, where a module-scope sys.exit() would have taken all of them down at
import time -- see _common.py's LAZY RESOLUTION comment). Nothing in this
file is importable that could reproduce that hazard.

GUARDRAIL-VS-ADVISORY: A HOOK THAT CANNOT LOAD MUST SAY SO, NEVER PASS
SILENTLY (added after a measured incident: on Python 3.9, a module-level
PEP-604 union in _common.py raised TypeError at import for nearly every hook
that imported it. Python exits 1 on an uncaught exception at import time,
and the Claude Code hook protocol only treats exit 2 as blocking -- so every
one of those guardrails waved every tool call through while `settings.json`
still listed them as installed. Nothing in any log distinguished that from
"ran, found nothing wrong." _common.py's own PEP-604 line has since been
fixed (`from __future__ import annotations`), but that fixes ONE instance,
not the CLASS: any future hook, guardrail or advisory, can break the same
way.

Before `execv`/`execvp` below, this file now tries to load the resolved
target IN-PROCESS (`_check_importable` for `.py`, `_check_sh_syntax` for
`.sh`) and reacts according to a two-way classification:

  - GUARDRAIL (a hook whose job is to DENY a tool call or Stop event) --
    import failure means the control cannot do its job. FAIL CLOSED: block
    (exit 2) naming the hook and the captured error, and never attempt the
    real exec at all (there is no point running something already proven
    broken).
  - ADVISORY (a hook whose job is context injection or telemetry, never a
    denial) -- import failure means an agent gets less context, not that a
    bad action is silently permitted. Allowed to FAIL OPEN, but LOUD: a
    stderr warning plus a best-effort telemetry event, never bare silence.

Classification lives in `_ADVISORY_HOOKS` below -- an EXPLICIT, ENUMERATED
allowlist of the advisory hook_rel names actually dispatched from this
repo's `.claude/settings.json` (cross-check: `docs/hook-manifest.yaml`,
which records the same source-of-truth intent for each hook's role, though
that file's `class`/`layer` axes answer a different question --
wireability/mechanical-vs-doctrine -- not this one). Anything NOT on that
list defaults to GUARDRAIL -- "when in doubt, guard": a hook this file
doesn't recognize is far more likely to be a control someone forgot to
enumerate than a genuinely inert one, and the cost of over-blocking an
unrecognized advisory hook (a loud, fixable block) is far cheaper than the
cost of silently failing open on a real guardrail.

Deliberately IN-PROCESS, not a second subprocess: `_dispatch.py` sits on the
single hottest path in this whole system (every PreToolUse hook, every tool
call), so spawning a whole extra python interpreter just to test-import
before the real exec would roughly double process-spawn overhead on every
invocation. `importlib.util.module_from_spec` + `exec_module` inside THIS
already-running process exercises every module-level statement (the exact
shape that killed those hooks -- module-level code, never `main()`, which
every hook here guards behind `if __name__ == "__main__":`) at effectively
zero marginal cost, and is provably safe here specifically because
`os.execv`/`os.execvp` immediately below REPLACES this process's entire
image on the success path -- any state the trial import leaves behind
(`sys.modules` entries, whatever) is discarded before the real hook ever
runs, so there is no cross-contamination risk. `.sh` targets have no
in-process equivalent, so `_check_sh_syntax` does spawn `bash -n` -- but
only for the small `.sh` subset of the guardrail set (`protect-files.sh` in
this pack), not the hot per-call majority.
"""
import os
import sys


def _skip_requested():
    v = os.environ.get("SKIP_HOOK_DISPATCH", "")
    return v not in ("", "0", "false", "False")


def _project_dir():
    pd = os.environ.get("CLAUDE_PROJECT_DIR")
    if pd:
        return os.path.abspath(pd)
    # Self-relative fallback if Claude Code somehow didn't set it: this file
    # is .claude/hooks/_dispatch.py, so the project root is two dirs up.
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_env_file(path):
    """Minimal KEY=VALUE parser for harness.env -- mirrors _common.py's own
    _parse_env_file (comments, blank lines, 'export ' prefix, quoted values).
    Duplicated rather than imported: _common.py is one of the harness assets
    that may live in the SEPARATE install location this file's whole job is
    to locate -- it may not be sitting next to this file at all, so this
    file cannot assume it can import it."""
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except OSError:
        return out
    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key] = val
    return out


def resolve_hooks_dir(project_dir):
    """Precedence: env AUDIT_HARNESS_HOOKS_DIR -> harness.env's AUDIT_HARNESS_HOOKS_DIR ->
    co-located default. Never raises and never checks existence -- the
    caller (main()) is responsible for turning "resolved but empty/missing"
    into a loud block(), since a syntactically-valid but nonexistent
    override is exactly the case that must fail loud, not silently
    fall through to some other guess."""
    v = os.environ.get("AUDIT_HARNESS_HOOKS_DIR", "").strip()
    if v:
        return os.path.abspath(v)

    env_path = os.path.join(project_dir, "harness.env")
    if os.path.isfile(env_path):
        parsed = _parse_env_file(env_path)
        v = (parsed.get("AUDIT_HARNESS_HOOKS_DIR") or "").strip()
        if v:
            return os.path.abspath(v)

    return os.path.join(project_dir, ".claude", "hooks")


def _interpreter_for(path):
    if path.endswith(".py"):
        return sys.executable
    if path.endswith(".sh"):
        return "bash"
    return None  # exec the file directly via its own shebang + exec bit


# See the module docstring's GUARDRAIL-VS-ADVISORY section for the full
# rationale. EXPLICIT enumeration of the advisory (never-denies) hook_rel
# names this dispatcher recognizes.
#
# Of these, only integrator_transcript_compactor.py (PreCompact transcript
# housekeeping) ships as source in THIS pack and is actually wired by its
# generated settings.json. The other four -- transcript_context_scan.py /
# file_context_hint.py / prompt_context_hint.py (context injection),
# covmap_diffcheck.py (coverage telemetry) -- are pre-declared for a fuller
# install that carries those hooks too (see generate_settings_json.py's
# PUSH-class handling); this pack's own hook-manifest.yaml never wires them,
# so listing them here is forward-compatible, not misleading -- a hook_rel
# this file has never heard of still defaults to GUARDRAIL below, so an
# unrecognized hook is never accidentally treated as advisory.
#
# Verified by direct inspection (grep for `block(`/`exit(2)`/a `deny`
# permissionDecision in each file that ships here): none of the shipped
# advisory hook can deny a tool call or a Stop event. EVERY hook_rel this
# pack ships that CAN deny -- no_test_tampering.py, no_swallowed_errors.py,
# no_type_checking_stub.py, no_bash_test_deletion.py, no_bash_test_mutation.py,
# agent_sizing_gate.py, workflow_agent_sizing_gate.py, protect-files.sh,
# subagent_closing_report.py -- is deliberately NOT on this list, so none of
# them may be added here by accident. A hook_rel this file has never seen
# before also falls through to GUARDRAIL by the same default, not just the
# ones named above.
_ADVISORY_HOOKS = frozenset({
    "transcript_context_scan.py",
    "file_context_hint.py",
    "prompt_context_hint.py",
    "covmap_diffcheck.py",
    "integrator_transcript_compactor.py",
})


def _is_guardrail(hook_rel):
    return hook_rel not in _ADVISORY_HOOKS


def _check_importable(target):
    """In-process import probe for a `.py` hook target. Returns None if it
    imports cleanly, else the captured exception text (traceback, tail-
    truncated). See the module docstring for why this is safe to do
    in-process and never executes the hook's own __main__ block."""
    import importlib.util
    import traceback

    try:
        spec = importlib.util.spec_from_file_location("_dispatch_import_probe", target)
        if spec is None or spec.loader is None:
            return "could not build an import spec for this file"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 -- every ORDINARY import-time exception
        # (ImportError, TypeError -- the measured PEP-604-union shape,
        # SyntaxError, AttributeError, ...) must be caught and surfaced
        # (blocked or warned), never let one kind slip through unclassified.
        # Deliberately `Exception`, not `BaseException`: a module-level
        # `sys.exit(N)` raises SystemExit, which must propagate normally
        # rather than being reinterpreted as an "import failure" -- no real
        # hook in this tree does this (every one guards its exit behind
        # `if __name__ == "__main__":`), but treating it as a probe failure
        # would be wrong if one ever legitimately did, and `BaseException`
        # would also swallow KeyboardInterrupt, which must never be caught
        # silently either.
        return traceback.format_exc()[-4000:]
    return None


def _check_sh_syntax(target):
    """`bash -n` syntax-only probe for a `.sh` hook target -- the shell
    analogue of _check_importable() above. Spawns a subprocess (bash has no
    in-process equivalent), but only for the small `.sh` subset of the
    dispatched hooks.

    Never raises: if `bash` itself is missing or unrunnable, that is
    reported as a probe failure (same try/except OSError shape
    check_interpreter_floor.py uses for its own interpreter probe), not
    left to escape as an uncaught exception. An uncaught FileNotFoundError
    here would propagate out of main(), Python would exit 1 on the
    uncaught exception, and exit 1 is NON-BLOCKING in the Claude Code hook
    protocol -- so this dispatcher, whose entire job is to make a broken
    hook fail LOUD instead of silently permitting the tool call, would
    itself fail OPEN on exactly the guardrail it was supposed to protect.
    """
    import subprocess

    try:
        proc = subprocess.run(["bash", "-n", target], capture_output=True, text=True)
    except OSError as e:
        return f"could not run bash to syntax-check this hook: {e}"
    if proc.returncode == 0:
        return None
    return (proc.stdout + proc.stderr).strip()[-4000:]


def _emit_dispatch_event(verdict, hook_rel, target, error):
    """Best-effort, fire-and-forget telemetry line for an advisory hook's
    import failure -- deliberately self-contained (does NOT import
    _common.emit_event) for the same reason resolve_hooks_dir's env-file
    parser is duplicated rather than imported: _common.py is one of the
    assets that may itself be broken (it is literally the file that caused
    the incident this whole mechanism exists to catch), and telemetry must
    never depend on the thing it might need to report as broken. Mirrors
    _common.emit_event's line shape closely enough to land in the same
    harness_events.jsonl and be read by the same tooling, without requiring
    _common to be importable."""
    try:
        import json
        from datetime import datetime, timezone

        # `target` is always <hooks_dir>/<hook_rel>, so its dirname IS the
        # resolved hooks dir -- same layout _common._events_path() assumes
        # (<project_dir>/.claude/hooks/state/harness_events.jsonl).
        events_path = os.path.join(os.path.dirname(target), "state", "harness_events.jsonl")
        os.makedirs(os.path.dirname(events_path), exist_ok=True)
        line = json.dumps({
            "schema_v": 1,
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": "dispatch_import_failure",
            "source": "_dispatch",
            "verdict": verdict,
            "subject": hook_rel,
            "payload": {"target": target, "error": error[:1000]},
        }, default=str, separators=(",", ":")) + "\n"
        fd = os.open(events_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:  # swallow-ok: telemetry must never block dispatch, and the
        # stderr warning printed alongside every call site of this function is
        # the primary, non-optional loud signal -- this is a best-effort second
        # channel, not the only one.
        pass


def _block_guardrail_import_failure(hook_rel, target, error):
    sys.stderr.write(
        "BLOCKED: guardrail hook '%s' failed to load (%s) -- a guardrail that "
        "cannot import cannot enforce anything, and the Claude Code hook "
        "protocol only treats exit 2 as blocking (a plain uncaught-exception "
        "exit 1 from the real hook would have been silently read as PERMIT). "
        "Refusing to run it, and refusing to silently wave this tool call "
        "through.\n"
        "Import error:\n%s\n"
        "Fix the hook (or whatever it imports) before this control can run "
        "again. If this hook is genuinely meant to fail open, that is a "
        "deliberate classification change -- add it to _ADVISORY_HOOKS in "
        "this file, with a reason, rather than leaving it silently broken.\n"
        % (hook_rel, target, error)
    )
    sys.exit(2)


def _warn_advisory_import_failure(hook_rel, target, error):
    sys.stderr.write(
        "WARNING: advisory hook '%s' failed to load (%s) and will not run this "
        "invocation. Classified advisory (context-injection/telemetry, never a "
        "denial), so this fails OPEN by design -- but never silently: this "
        "warning plus a dispatch_import_failure telemetry event are the loud "
        "signal that replaces it. See _dispatch.py's GUARDRAIL-VS-ADVISORY "
        "docstring section.\n"
        "Import error:\n%s\n"
        % (hook_rel, target, error)
    )
    _emit_dispatch_event("fail_open_advisory", hook_rel, target, error)


def _block(hook_rel, target, project_dir):
    sys.stderr.write(
        "BLOCKED: cannot resolve harness hook '%s' -- looked for it at\n"
        "  %s\n"
        "(the resolved HARNESS location), which does not exist. This tree's "
        ".claude/settings.json expects the harness's own .claude/hooks/ to "
        "be located via AUDIT_HARNESS_HOOKS_DIR, not assumed co-located with the "
        "audited tree.\n"
        "Fix: set the AUDIT_HARNESS_HOOKS_DIR environment variable to the "
        "directory containing this harness's .claude/hooks/, or add "
        "AUDIT_HARNESS_HOOKS_DIR=<path> to %s/harness.env.\n"
        "To bypass hook dispatch entirely, set SKIP_HOOK_DISPATCH=1.\n"
        % (hook_rel, target, project_dir)
    )
    sys.exit(2)


def main(argv):
    if _skip_requested():
        sys.exit(0)

    if len(argv) < 2:
        sys.stderr.write(
            "BLOCKED: _dispatch.py requires a hook filename argument "
            "(.claude/settings.json wiring is malformed)\n"
        )
        sys.exit(2)

    hook_rel = argv[1]
    extra_args = argv[2:]
    project_dir = _project_dir()
    hooks_dir = resolve_hooks_dir(project_dir)
    target = os.path.join(hooks_dir, hook_rel)

    if not os.path.isfile(target):
        _block(hook_rel, target, project_dir)

    error = None
    if target.endswith(".py"):
        error = _check_importable(target)
    elif target.endswith(".sh"):
        error = _check_sh_syntax(target)
    # Any other extension (an executable with a shebang, exec'd directly
    # below via os.execv) has no cheap "does this load" probe available --
    # unchanged from before this fix, not a regression.

    if error is not None:
        if _is_guardrail(hook_rel):
            _block_guardrail_import_failure(hook_rel, target, error)
        else:
            _warn_advisory_import_failure(hook_rel, target, error)
            # Already proven broken above -- exec'ing it again would only
            # reproduce the same failure. Fail open directly (exit 0), having
            # already emitted the loud warning + telemetry that replaces the
            # silence this whole mechanism exists to close.
            sys.exit(0)

    interp = _interpreter_for(target)
    if interp is None:
        os.execv(target, [target] + extra_args)
    else:
        os.execvp(interp, [interp, target] + extra_args)


if __name__ == "__main__":
    main(sys.argv)
