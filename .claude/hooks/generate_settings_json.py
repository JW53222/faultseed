#!/usr/bin/env python3
"""generate_settings_json.py -- generate a per-target `.claude/settings.json`
from `docs/hook-manifest.yaml`'s declarative classification data, instead of
hand-authoring one per install.

INPUTS (data, not prose):
  - docs/hook-manifest.yaml: per-hook class (P/GG/TD/PP/LIB/UNWIRED),
    fixed_for_go, event/matcher bindings, wrapper/payload relationships.
  - the manifest's own `targets.<name>.profile` -- a NAMED profile string
    ("go", "python", ...), passed to `_is_eligible` for every hook.
    Profile-aware eligibility replaced an earlier hardcoded go/not-go
    boolean read: `_is_eligible` used to hardcode class GG -> eligible only
    if `fixed_for_go` (a go-specific question) and class PP -> always
    ineligible (go-specific reasoning), with the `profile` value itself
    never even read. See the manifest's own `targets:` section comment for
    the current per-class default table and the per-hook
    `profiles: {...}` override escape hatch.

INCLUSION RULE (per profile, see `_is_eligible`):
  - class P (non-wrapper) with `events`: always included, any profile
    (language-agnostic).
  - class GG with `events`: included for profile "python" by default
    (python is this pack's home grammar -- `fixed_for_go` answers a go
    question, not a python one); included for profile "go" iff
    `fixed_for_go: true`; no default for any other/unmodeled profile.
  - class PP with `events`: included for profile "python" only (the defect
    shape is real in python, cannot exist in go).
  - class TD, class LIB, class UNWIRED, class PUSH: NEVER included,
    regardless of profile. PUSH is otherwise class-P-shaped -- real,
    functional, `events` retained -- but deliberately excluded from the
    shipped default (a fuller install may carry PUSH-class hooks whose
    source isn't part of this pack; see the PUSH note in
    `_dispatch.py`'s `_ADVISORY_HOOKS` comment).
  - A hook's own `profiles: {<profile>: true|false}` dict, when it names the
    profile being resolved, WINS OUTRIGHT over all of the above for that
    profile (a sparse override, not an exhaustive allow-list -- an absent
    key still falls through to the class default). This is how two hooks
    that share a class and the same `wrapped_by` wrapper can stay mutually
    exclusive payload candidates despite sharing a class whose default
    would otherwise make both eligible at once.
  - `is_wrapper` hooks: included ONLY if at least one other hook declares
    `wrapped_by: <this wrapper>` AND is itself eligible by the rules above
    for the profile being resolved. If no eligible payload resolves, the
    wrapper is DROPPED ENTIRELY -- wiring an empty wrapper is "installed
    and not erroring" vacuity via a missing-payload mechanism, the same
    defect shape as every other silent-vacuity finding this generator
    guards against.

ANTI-VACUITY (non-negotiable): if the resolved hook set for a target is
EMPTY, this generator FAILS LOUD (raises `EmptyHookSetError`, nonzero exit
from `main`) rather than writing an empty-but-structurally-valid
settings.json. Decision, stated rather than assumed: "a target genuinely
has no applicable hooks" is NOT treated as a legitimate, silent case here --
every real target profile this manifest models has at least the
language-agnostic class-P hooks available, so an empty result set means the
manifest or the profile name is wrong, not that the target is exempt. If a
future target profile genuinely warrants zero hooks, that must be an
EXPLICIT `allow_empty: true` on the profile in the manifest, not a default.

PACK DIMENSION (orthogonal to the target profile above): every hook and
doctrine doc in the manifest also carries a `layer` (mechanical / doctrine /
both-excluded / UNRESOLVED). `--pack` selects which layers are active:
  - B (default, backward-compatible): layers [mechanical, doctrine] --
    identical hook resolution to a pack-less generator, since no shipped
    hook carries `layer: doctrine`. Byte-identical output to the prior,
    pre-pack-model behavior is a contract this file must never break.
  - C: layers [mechanical] -- same hooks dict as B (again, no hook is
    layer:doctrine); doctrine docs excluded from `resolve_doc_set`.
  - D: layers [doctrine] -- zero hooks are layer:doctrine, so the hooks
    dict resolves empty. The manifest's `packs.D.allow_empty: true` is the
    explicit, non-default opt-in this module's own anti-vacuity contract
    requires before treating that emptiness as legitimate rather than a
    generator/manifest bug.

STAGE DIMENSION: a THIRD orthogonal SELECTOR, `--stage` in {none, e1, e2},
mirroring `--pack` exactly -- both select which `layer` values are active,
from their own manifest section (`packs:` / `stages:`). `stage` gates
KNOWLEDGE-LAYER components, entirely separate from `profile` (class/language
eligibility) and `pack` (mechanical-vs-doctrine layer).

`stage` is NOT a per-item field. No hook, doc, or tool entry in the manifest
carries a `stage:` key -- an item's `layer` is the single source of truth
for which stage(s) admit it (see `_stage_layers()` below, which reads
`manifest["stages"][stage]["layers"]`, exactly mirroring `_pack_layers()`).
A per-item `stage:` field alongside `layer` would encode the same fact
twice and let the two silently disagree; this file avoids that by
construction, not by convention.

Resolution is a UNION with `pack`, not a replacement: `--pack` alone
resolves the mechanical/doctrine slice exactly as before (unchanged,
byte-identical for pack B regardless of `--stage`); `--stage` ADDITIONALLY
resolves whatever layers `manifest["stages"][stage]["layers"]` names. A
broader stage's `layers` list is typically a structural superset of a
narrower one's, so a broader stage request resolves a superset of what the
narrower one resolves -- that relationship lives in the manifest data, not
in special-cased generator logic.

Two NEW layer values, `knowledge-tools` and `knowledge-docs`, deliberately
DISTINCT from `doctrine` -- reusing `doctrine` for per-repo knowledge docs
would place them inside pack B by construction (B = C union D), manufacturing
a false null for any comparison built by differencing against B. Neither new
value is ever named in any B/C/D pack's `layers:` list in the manifest, so
`--pack` alone can NEVER resolve a knowledge-* item by construction -- the
wrong thing is UNREPRESENTABLE via the pack axis, not merely discouraged.
The only path that resolves a knowledge-* item is an explicit `--stage`
request naming a stage whose `layers:` list includes it.

No hook in the manifest declares `layer: knowledge-tools` or
`layer: knowledge-docs`, so `--stage` has zero observable effect on
`build_settings_dict`/settings.json regardless of value (this is provable by
construction: `profile` and `stage` are threaded through entirely disjoint
call paths -- `profile` only ever reaches `_is_eligible`/
`_resolve_wrapper_payload`/`generate_hook_list`, `stage` only ever reaches
`resolve_doc_set`/`resolve_tool_set`/`build_tool_manifest_dict`, and neither
function set calls into the other). `resolve_tool_set()` /
`build_tool_manifest_dict()` is the stage-side production-entry-path output
instead, parallel to `resolve_doc_set()` for docs;
`generate_tool_advertisement()` builds the mechanical, --help-derived tool
advertisement.

This file and `docs/hook-manifest.yaml` speak `pack`/`stage` selector
vocabulary ONLY -- neither encodes which named treatment mounts which
(pack, stage) combination. That binding is a decision made by whoever
operates this generator, outside this file, so revising which layers belong
to which pack never requires editing this file: selectors compose over
whatever layers a pack/stage names, regardless of what any of them are
called.

MOUNT REQUIREMENT: every session that mounts a generated pack against a
co-located target tree must set `BLESSED_REPO` explicitly in env --
`_common.blessed_root()`'s git-toplevel fallback otherwise resolves to the
foreign (target) tree, and a blessed-tree mutation guard built on top of
this pack would then block the agent's own git operations against its own
repo.

ABSOLUTE HOOK PATHS: an installer that mounts a generated pack via a
`--settings` CLI flag while `$CLAUDE_PROJECT_DIR` points at the TARGET repo,
not the install location, will find that a var-relative hook command
resolves to nowhere and the hook goes silently inert -- a real, measured
failure mode, not a hypothetical one. Portability belongs in the GENERATOR,
which knows the install location at generation time, not baked into the
artifact as an env-var reference resolved later by whatever process happens
to be running.

`--abs-root <path>` / `build_settings_dict(..., abs_root=<path>)` emits
every hook command with that literal absolute path substituted for
`$CLAUDE_PROJECT_DIR`. Default is `None` (unchanged, var-relative output) --
this is DELIBERATE, not an oversight: existing installs are authored in the
var-relative style, and this generator must keep producing byte-identical
output for pack B by default rather than silently changing style underneath
them. A production install may plausibly want absolute paths for EVERY pack
including B, which would mean any checked-in reference output needs
regenerating in the new style -- that is an operator call at adoption time,
not something this generator decides for you. Until that call is made,
`abs_root` stays a strictly additive, opt-in parameter; the unqualified
default call remains byte-identical to the pre-existing default.

INTERPRETER PIN: every generated hook command invokes bare `python3` --
whatever `python3` PATH resolves to at the moment Claude Code runs the hook,
not at install time. That's a live hazard, not just a version-drift one:
PATH can change MID-SESSION (e.g. `source venv/bin/activate` inside a
Python repo), so a hook that resolved to one interpreter at session start
can silently resolve to a different one later in the same session -- the
transcript and diff look completely normal, nothing announces the switch.
`_common.py`'s `from __future__ import annotations` fix (see
check_interpreter_floor.py and INSTALL.md's Dependencies section) makes
`_common` import cleanly across the practical Python range regardless of
which interpreter runs it, but that is a property of THIS repo's source,
not a guarantee about every target's hook tree or future edits to it --
pinning removes the PATH dependency entirely rather than relying on the
source staying interpreter-version-agnostic forever.

`--interpreter <path>` / `build_settings_dict(..., interpreter=<path>)`
substitutes that literal path for the bare `python3` token in every
generated hook command (including a wrapper's payload command). Default is
`None` (unchanged, bare `python3`) -- same "strictly additive, opt-in,
byte-identical default" discipline as `abs_root` above, for the same
reason. Install-time guidance: resolve the target's own interpreter with
`command -v python3` (or the provisioned venv's `python3`) and pass its
absolute path, so the generated settings.json is immune to a later PATH
change in the same session. Recorded in `PROVENANCE.json` as `interpreter`
when given (omitted, not `null`, when not -- matching `stage`'s convention
below, not `abs_root`'s always-present one, since this is a newer opt-in
with no pre-existing consumer expecting the key).

PROVENANCE SIDECAR: a downstream tool that mounts a generated pack can parse
an optional `PROVENANCE.json` file next to a generated pack's settings.json
to learn which generator/manifest state produced it. Without a producer,
that convention measures nothing -- if a downstream tool treats a missing
sidecar as "unrecorded", every generated pack reads "unrecorded" until
something actually writes the file. `build_provenance()` computes the
payload (generator script sha256, manifest sha256, pack, target, abs_root,
and `stage` IF AND ONLY IF the manifest declares a top-level `stages:`
section); `main()` writes it as a sibling `PROVENANCE.json` next to `--out`
(the obvious convention given how `--out` already works: one settings.json
per generation, one sidecar per generation, same directory). Provenance is
NEVER part of the settings.json dict itself -- it is a wholly separate
artifact, so pack B's byte-identical output contract is untouched.

`stage` is included in provenance as `args.stage` (default `'none'`, itself
a real, explicit selector value -- never a fabricated one) whenever the
manifest declares a `stages:` section; a manifest that genuinely predates
the stage axis (no `stages:` key at all) gets `stage` omitted from
provenance entirely, not a fabricated `None`/`'none'` value standing in for
"not applicable". The gate is structural (does the manifest have the key),
not content-based.

DETERMINISM RULING: `build_provenance()` deliberately carries NO
timestamp/generation-time field. A moment-in-time value inside a generated
artifact is a reproducibility hazard the instant anything hashes or diffs
the file, and PROVENANCE.json exists precisely to BE an identity record (the
two content shas plus pack/target/abs_root/stage) -- the last place a
nondeterministic field belongs. Generation time, where operationally
wanted, is a job for whatever wraps this generator to record in its own
layer, not this generator's job.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("FATAL: PyYAML required (pip install pyyaml)\n")
    sys.exit(1)


class EmptyHookSetError(RuntimeError):
    """Raised when a target's resolved hook set is empty -- never silently
    written as a valid-looking empty settings.json."""


class WrapperWithoutPayloadError(RuntimeError):
    """Raised (internally caught, not propagated) when a wrapper hook is
    considered but no eligible payload resolves -- the wrapper is dropped,
    not wired empty. Kept as an exception (rather than silent skip) so the
    reasoning is visible in a --verbose trace, not just absent from output."""


class EmptyToolSetError(RuntimeError):
    """Raised when a knowledge-layer `--stage` request (stage != 'none')
    resolves to ZERO tools:-section items -- the same anti-vacuity
    discipline as EmptyHookSetError on the hooks side: a non-none stage
    with nothing to install is a manifest/generator bug, never a
    silently-written empty tool set."""


DEFAULT_PACK = "B"  # backward-compatible: identical resolution to the
                     # pre-pack-model generator (no hook is layer:doctrine).

DEFAULT_STAGE = "none"  # backward-compatible function-call default -- every
                         # pre-existing 1/2-arg caller of resolve_doc_set
                         # gets the "no knowledge layer" resolution
                         # unchanged. Not a manifest default: `stages.none`
                         # is a real, explicit entry in the manifest (see
                         # `_stage_layers` below), not an implicit fallback
                         # this module invents when the key is absent.


def _pack_layers(manifest: dict, pack: str) -> list[str] | None:
    packs = manifest.get("packs")
    if not packs:
        # No `packs:` section at all (older manifest shape, or pack support
        # simply unused): no layer filter is applied at all -- see
        # `_is_eligible`'s own backward-compat carve-out below.
        return None
    if pack not in packs:
        raise KeyError(f"no pack named {pack!r} in manifest['packs']")
    return packs[pack].get("layers", [])


def _stage_layers(manifest: dict, stage: str) -> list[str]:
    """Mirrors `_pack_layers` exactly: `stage` is a SELECTOR over `layer`,
    resolved from the manifest's own `stages:` section, not a hardcoded
    table in this module and not a per-item field on any hook/doc/tool
    entry. `stages.none.layers == []` is a real, explicit manifest entry
    (see docs/hook-manifest.yaml) -- there is no manifest-shape carve-out
    here the way `_pack_layers` has for an absent `packs:` section, because
    `stages:` did not exist before this axis did; every caller of this
    generator now expects the manifest to have a `stages:` section to
    read."""
    stages = manifest.get("stages")
    if not stages:
        raise KeyError(
            "manifest has no 'stages' section -- required once the stage "
            "axis exists (docs/hook-manifest.yaml must declare stages.none "
            "explicitly, see the module docstring's STAGE DIMENSION section)"
        )
    if stage not in stages:
        raise KeyError(
            f"no stage named {stage!r} in manifest['stages'] -- must be one "
            f"of {sorted(stages)}"
        )
    return stages[stage].get("layers", [])


def _is_eligible(
    name: str, entry: dict, profile: str | None, pack_layers: list[str] | None = None
) -> bool:
    # Backward-compat: an entry that declares no `layer` at all predates the
    # pack dimension (or is a synthetic/legacy manifest fragment, e.g. this
    # module's own pre-pack-model tests) -- it is never filtered by pack,
    # only by its class/profile eligibility below, exactly as before packs
    # existed. Only entries that DO declare a `layer` are subject to the
    # pack filter.
    if pack_layers is not None and "layer" in entry and entry.get("layer") not in pack_layers:
        return False
    if not entry.get("events"):
        return False
    # Per-hook explicit override wins outright over the class-based default
    # below, for the profile keys it names -- a sparse override, not an
    # exhaustive allow-list (a profile absent from the dict still falls
    # through to the class default). This is the escape hatch a
    # profile-EXCLUSIVE hook needs when the class-level default would give
    # the wrong answer for its own scoping -- e.g. two class-GG hooks that
    # are both `wrapped_by` the same wrapper and would otherwise both be
    # default-eligible for the same profile (GG's own default only
    # self-selects for python in the grammar-extension sense, not the
    # profile-exclusive-payload sense) need this override to stay mutually
    # exclusive. This pack's own manifest does not currently ship a hook
    # that needs it, but the mechanism is general, not manifest-specific.
    override = (entry.get("profiles") or {}).get(profile)
    if override is not None:
        return bool(override)
    cls = entry.get("class")
    if cls == "P":
        return not entry.get("is_wrapper")
    if cls == "GG":
        # python is the harness's home grammar: a class-GG hook's
        # python-side already works regardless of `fixed_for_go`, which
        # answers a go-specific question (did THIS session's go-grammar
        # work close the go gap), not a python one.
        if profile == "python":
            return True
        if profile == "go":
            return bool(entry.get("fixed_for_go"))
        return False  # an unmodeled profile gets no default GG eligibility
                      # -- it must declare an explicit `profiles` override.
    if cls == "PP":
        # PYTHON-PACK-MEMBER: the defect shape cannot exist in go, but it IS
        # a real python bug class -- eligible for python only.
        return profile == "python"
    return False  # TD, LIB, UNWIRED, PUSH: never eligible, any profile.
                  # PUSH is a REAL class-P-shaped classification (real,
                  # functional, `events` retained) that is deliberately cut
                  # from the shipped default -- a fuller install may carry
                  # PUSH-class hook source that this pack doesn't ship (see
                  # the note in _dispatch.py's _ADVISORY_HOOKS comment).


def _resolve_wrapper_payload(
    hooks: dict, wrapper_name: str, profile: str | None, pack_layers: list[str] | None = None
) -> tuple[str, dict] | None:
    """Find an eligible hook declaring `wrapped_by: wrapper_name`. Returns
    (payload_hook_name, payload_entry) or None if no eligible payload exists."""
    candidates = [
        (name, entry) for name, entry in hooks.items()
        if entry.get("wrapped_by") == wrapper_name and _is_eligible(name, entry, profile, pack_layers)
    ]
    if not candidates:
        return None
    # Deterministic: if more than one eligible payload somehow exists, this
    # is itself ambiguous and must be flagged, not silently resolved by
    # picking one -- with this pack's own manifest, no wrapper currently has
    # more than one eligible payload, but this branch exists for the general
    # case the mechanism must handle, not a case this manifest exercises.
    if len(candidates) > 1:
        raise RuntimeError(
            f"ambiguous payload for wrapper {wrapper_name!r}: {[n for n, _ in candidates]} "
            "are all eligible -- manifest must disambiguate, not the generator"
        )
    return candidates[0]


def generate_hook_list(
    manifest: dict, target: str, pack: str = DEFAULT_PACK
) -> list[tuple[str, dict, str | None]]:
    """Returns [(hook_name, event_binding_dict, resolved_command_suffix)],
    resolved_command_suffix is None for a normal hook, or the payload
    command for a wrapper hook (e.g. a wrapper `verify.py` resolving to
    `python3 verify_payload.py`)."""
    hooks = manifest["hooks"]
    targets = manifest.get("targets", {})
    if target not in targets:
        raise KeyError(f"no target profile named {target!r} in manifest")
    profile = targets[target].get("profile")
    pack_layers = _pack_layers(manifest, pack)

    entries: list[tuple[str, dict, str | None]] = []
    for name, entry in hooks.items():
        if entry.get("is_wrapper"):
            payload = _resolve_wrapper_payload(hooks, name, profile, pack_layers)
            if payload is None:
                # WrapperWithoutPayloadError: constructed for the trace, not
                # raised -- the correct behavior is DROP, not crash the
                # whole generation over one absent wrapper.
                _ = WrapperWithoutPayloadError(
                    f"{name} has no eligible payload for target {target!r} pack {pack!r} "
                    "-- dropped, not wired empty"
                )
                continue
            payload_name, payload_entry = payload
            for binding in entry.get("events", []):
                entries.append((name, binding, payload_name))
            continue
        if entry.get("wrapped_by"):
            # A hook that declares `wrapped_by` is ONLY ever reachable as
            # that wrapper's payload -- it is never independently wired,
            # even if it happens to satisfy `_is_eligible` on its own (a
            # payload hook can carry its own `events` entry so callers can
            # see what event it ultimately runs under, but it must not ALSO
            # get its own direct binding -- that would wire it twice, once
            # correctly wrapped and once bypassing the wrapper's own gating
            # entirely).
            continue
        if not _is_eligible(name, entry, profile, pack_layers):
            continue
        for binding in entry.get("events", []):
            entries.append((name, binding, None))

    return entries


def resolve_doc_set(
    manifest: dict, pack: str = DEFAULT_PACK, stage: str = DEFAULT_STAGE
) -> list[str]:
    """Returns the sorted list of doc paths (manifest['docs'] keys) whose
    `layer` is active for `pack` UNION `stage`. Docs never appear in
    settings.json -- this is the parallel, doc-side half of the pack
    resolution (pack C, "mechanicals-only", should wire hooks with an empty
    doc set; pack D, "doctrine-only", should wire zero hooks with the full
    doc set -- verify this against your own manifest if you add coverage
    for it).

    `stage` is additive, not a replacement: every pre-existing caller passes
    only `pack` (or neither), so `stage` defaults to `none` (zero extra
    layers) and this function's B/C/D behavior is byte-for-byte unchanged
    from before the stage axis existed -- no doc in the manifest today
    declares `layer: knowledge-docs`, so the union is a no-op until some
    later addition to the manifest uses one."""
    docs = manifest.get("docs", {})
    pack_layers = _pack_layers(manifest, pack)
    stage_layers = _stage_layers(manifest, stage)
    if pack_layers is None:
        return sorted(docs.keys())
    active = set(pack_layers) | set(stage_layers)
    return sorted(
        path for path, entry in docs.items()
        if entry.get("layer") in active
    )


def resolve_tool_set(
    manifest: dict, stage: str = DEFAULT_STAGE
) -> list[tuple[str, dict]]:
    """Returns sorted [(tool_key, entry)] for every `manifest['tools']` item
    whose `layer` is active for `stage`. No hook in the manifest declares a
    knowledge-* layer, so this -- not `build_settings_dict` -- is the
    stage-side production-entry-path resolution for whatever a stage's
    `layers:` list admits. `stage='none'` (the default) always resolves
    empty, matching the "not a knowledge-layer mount" case -- exactly as
    `build_settings_dict` ignores `tools:` entirely regardless of stage."""
    tools = manifest.get("tools", {})
    active = set(_stage_layers(manifest, stage))
    return sorted(
        (key, entry) for key, entry in tools.items()
        if entry.get("layer") in active
    )


def generate_tool_advertisement(
    manifest: dict, stage: str = DEFAULT_STAGE, repo_root: Path | None = None
) -> str:
    """Mechanical documentation ONLY -- tool name, invocation, what it
    returns. No guidance on when/why to use it, no worked examples, no
    heuristics: that would be doctrine prose, and doctrine content is what
    the `knowledge-tools`/`knowledge-docs` layer split exists to keep out of
    this stage. Generated FROM each `status: available`
    tool's own `--help` output so the text structurally cannot drift into
    prose -- there is no free-text field here for a future edit to fill
    with heuristics. `status: stub` tools (no CLI built yet) get their
    recorded `interface:` line instead, explicitly marked STUB -- never a
    fabricated `--help` transcript for a tool that does not exist."""
    entries = resolve_tool_set(manifest, stage)
    root = repo_root or Path(__file__).resolve().parents[2]
    lines = [f"# Installed tools (knowledge-tools, stage: {stage})", ""]
    for key, entry in entries:
        if entry.get("kind") == "advertisement":
            continue  # the advertisement's own manifest row is bookkeeping
                      # for the pack-item accounting, not content to render
        status = entry.get("status")
        if status == "available":
            help_cmd = entry["help_cmd"]
            parts = help_cmd.split()
            resolved = [
                str(root / p) if p.endswith(".py") else p for p in parts
            ]
            proc = subprocess.run(
                resolved, capture_output=True, text=True, timeout=30
            )
            lines.append(f"## {key}")
            lines.append(f"Invocation: `{entry.get('entry_point', help_cmd)}`")
            lines.append("```")
            lines.append((proc.stdout or proc.stderr).strip())
            lines.append("```")
            lines.append("")
        elif status == "stub":
            lines.append(f"## {key} (STUB -- not yet installed)")
            lines.append(f"Intended interface: `{entry.get('interface', 'undocumented')}`")
            lines.append("")
        else:
            raise ValueError(f"tool {key!r} has unrecorded status {status!r}")
    return "\n".join(lines)


def build_tool_manifest_dict(
    manifest: dict, stage: str = DEFAULT_STAGE, repo_root: Path | None = None
) -> dict:
    """Third generator output, parallel to `build_settings_dict`
    (hooks) and `resolve_doc_set` (docs): the installed-tool set for a
    knowledge-layer stage plus its mechanically-generated advertisement.
    `stage='none'` (default) returns an empty, unpopulated result -- the
    "no knowledge layer mounted" case -- without raising, matching
    `resolve_tool_set`'s own no-op-at-none behavior. A non-none stage that
    resolves zero tools IS an error (EmptyToolSetError): the manifest
    always carries at least the advertisement entry for a real stage, so
    zero items means the manifest or stage name is wrong."""
    entries = resolve_tool_set(manifest, stage)
    if stage != "none" and not entries:
        raise EmptyToolSetError(
            f"stage {stage!r} resolved to ZERO tools:-section items. This is never "
            "treated as a legitimate silent case -- either the manifest or the "
            "stage name is wrong."
        )
    tools_list = [
        {"key": key, **entry} for key, entry in entries
        if entry.get("kind") != "advertisement"
    ]
    advertisement = (
        generate_tool_advertisement(manifest, stage, repo_root) if stage != "none" else ""
    )
    return {"stage": stage, "tools": tools_list, "advertisement": advertisement}


def build_settings_dict(
    manifest: dict, target: str, pack: str = DEFAULT_PACK, abs_root: str | None = None,
    interpreter: str | None = None,
) -> dict:
    """`abs_root`, when given, is an ABSOLUTE filesystem path to the install
    root (the directory containing `.claude/hooks/`) and every generated
    hook command is emitted with that literal path baked in, instead of
    `$CLAUDE_PROJECT_DIR`. Default `None` preserves the pre-existing,
    var-relative output byte-for-byte (this parameter is strictly additive,
    never the default -- see the module docstring's "ABSOLUTE HOOK PATHS"
    section for why).

    `interpreter`, when given, substitutes that literal path for the bare
    `python3` token in every generated hook command (dispatch AND any
    wrapper payload command). Default `None` preserves bare `python3` --
    see the module docstring's "INTERPRETER PIN" section for why a pin
    matters (PATH can change mid-session) and why the default must stay
    byte-identical to the pre-existing output.
    """
    hooks = manifest["hooks"]
    entries = generate_hook_list(manifest, target, pack)
    if not entries:
        packs = manifest.get("packs", {})
        allow_empty = bool(packs.get(pack, {}).get("allow_empty"))
        if not allow_empty:
            raise EmptyHookSetError(
                f"target {target!r} pack {pack!r} resolved to ZERO wireable hooks. This is "
                "never treated as a legitimate silent case -- either the manifest, the "
                "target profile, or the pack name is wrong. If a pack genuinely warrants "
                "zero hooks (e.g. a doctrine-only arm), that must be an explicit "
                "`allow_empty: true` on the pack in the manifest, not a default."
            )

    # Sort by (event's own first-appearance order, hook's declared `order`)
    # to reproduce a deterministic structure rather than whatever dict/YAML
    # iteration order happened to produce.
    def order_key(item):
        name, binding, _payload = item
        return (binding["event"], hooks[name].get("order", 1_000_000))

    # Fixed event ordering: PreToolUse, UserPromptSubmit, SubagentStop,
    # Stop, PreCompact.
    event_order = {"PreToolUse": 0, "UserPromptSubmit": 1, "SubagentStop": 2,
                   "Stop": 3, "PreCompact": 4}
    entries.sort(key=lambda item: (event_order.get(item[1]["event"], 99),
                                    hooks[item[0]].get("order", 1_000_000)))

    hooks_dir = f"{abs_root}/.claude/hooks" if abs_root else "$CLAUDE_PROJECT_DIR/.claude/hooks"
    py = interpreter if interpreter else "python3"

    settings: dict = {"hooks": {}}
    for name, binding, payload_name in entries:
        event = binding["event"]
        matcher = binding.get("matcher")
        cmd = f'{py} "{hooks_dir}/_dispatch.py" {name}'
        if payload_name:
            cmd += f' -- {py} "{hooks_dir}/{payload_name}"'
        hook_cmd_entry = {"type": "command", "command": cmd}

        event_list = settings["hooks"].setdefault(event, [])
        # Group consecutive same-matcher hooks into one block's "hooks" list
        # (e.g. no_test_tampering.py + no_swallowed_errors.py both fire on
        # Edit|Write|MultiEdit, so they group under one matcher block).
        if event_list and event_list[-1].get("matcher") == matcher:
            event_list[-1]["hooks"].append(hook_cmd_entry)
        else:
            block = {"hooks": [hook_cmd_entry]}
            if matcher is not None:
                block = {"matcher": matcher, "hooks": [hook_cmd_entry]}
            event_list.append(block)

    return settings


PROVENANCE_FILENAME = "PROVENANCE.json"  # sibling to --out, one per generation


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_provenance(
    *,
    manifest_path: Path,
    generator_path: Path,
    target: str,
    pack: str,
    abs_root: str | None,
    stage: str | None = None,
    interpreter: str | None = None,
) -> dict:
    """The PROVENANCE.json payload -- see the module docstring's
    "PROVENANCE SIDECAR" section for what a downstream tool does with it.
    Deliberately carries NO timestamp/generation-time field --
    determinism ruling (see module docstring's "DETERMINISM RULING"
    section): identical inputs must produce a byte-identical payload,
    always, not "identical except for when it happened to run". `stage` is
    included ONLY when the caller passes one -- `main()` only ever does so
    when the manifest declares a `stages:` section, so a manifest predating
    that concept never gets a fabricated field. `interpreter` follows the
    same "included only when given" convention (not `abs_root`'s
    always-present one) -- see the module docstring's "INTERPRETER PIN"
    section."""
    payload: dict = {
        "generator_sha256": _sha256_file(generator_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "pack": pack,
        "target": target,
        "abs_root": abs_root,
    }
    if stage is not None:
        payload["stage"] = stage
    if interpreter is not None:
        payload["interpreter"] = interpreter
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="path to hook-manifest.yaml")
    parser.add_argument("--target", required=True, help="target profile name, e.g. gitea")
    parser.add_argument(
        "--pack", default=DEFAULT_PACK,
        help=f"pack/arm name, e.g. B/C/D (default: {DEFAULT_PACK!r}, backward-compatible)",
    )
    parser.add_argument(
        "--stage", default=DEFAULT_STAGE,
        help=f"knowledge-layer stage selector, a key in the manifest's `stages:` "
             f"section, e.g. none/e1/e2 (default: {DEFAULT_STAGE!r}, backward-"
             "compatible -- resolves zero extra layers, so settings.json and the "
             "doc set are unaffected). Orthogonal to --pack: both select `layer` "
             "values from their own manifest section and the results union. Also "
             "recorded in PROVENANCE.json's `stage` field whenever the manifest "
             "declares a `stages:` section.",
    )
    parser.add_argument(
        "--tools-out", help="output path for the tools:-section manifest "
                             "(build_tool_manifest_dict), written only if --stage != none",
    )
    parser.add_argument(
        "--abs-root",
        help="ABSOLUTE filesystem path to the install root (dir containing .claude/hooks/). "
             "When given, hook commands are emitted with this literal path instead of "
             "$CLAUDE_PROJECT_DIR (required whenever $CLAUDE_PROJECT_DIR points at a "
             "different repo than the pack's install location, e.g. a --settings-mounted "
             "pack evaluated against a separate target repo). Default: unset, var-relative "
             "output, byte-identical to the pre-existing behavior.",
    )
    parser.add_argument(
        "--interpreter",
        help="ABSOLUTE path to the python3 interpreter every generated hook command should "
             "invoke, instead of bare `python3` (which resolves via PATH at HOOK RUN time, "
             "not install time -- see module docstring's INTERPRETER PIN section for the "
             "mid-session PATH-drift hazard this closes). Default: unset, bare `python3`, "
             "byte-identical to the pre-existing behavior. When given together with "
             "--abs-root, also preflight-checked (`<interpreter> -c \"import _common\"` from "
             "<abs-root>/.claude/hooks) before anything is written -- see "
             "check_interpreter_floor.py for the standalone form of this same check.",
    )
    parser.add_argument("--out", help="output path (default: print to stdout)")
    args = parser.parse_args()

    if args.abs_root and not Path(args.abs_root).is_absolute():
        sys.stderr.write(f"FATAL: --abs-root must be an absolute path, got {args.abs_root!r}\n")
        return 1
    if args.interpreter and not Path(args.interpreter).is_absolute():
        sys.stderr.write(
            f"FATAL: --interpreter must be an absolute path, got {args.interpreter!r} -- "
            "a bare command name (e.g. 'python3.11') is exactly the PATH-dependent value "
            "this flag exists to replace.\n"
        )
        return 1
    if args.interpreter and args.abs_root:
        target_hooks_dir = str(Path(args.abs_root) / ".claude" / "hooks")
        try:
            check = subprocess.run(
                [args.interpreter, "-c", "import _common"],
                cwd=target_hooks_dir, capture_output=True, text=True, check=False,
            )
        except OSError as e:
            sys.stderr.write(f"FATAL: could not run --interpreter {args.interpreter!r}: {e}\n")
            return 1
        if check.returncode != 0:
            sys.stderr.write(
                f"FATAL: --interpreter {args.interpreter!r} failed to import _common from "
                f"{target_hooks_dir} (exit {check.returncode}). Pinning this interpreter into "
                "settings.json would ship a hook set that fails open on every session. "
                f"stderr:\n{check.stderr}"
            )
            return 1

    manifest_path = Path(args.manifest)
    generator_path = Path(__file__).resolve()
    manifest = yaml.safe_load(manifest_path.read_text())

    try:
        settings = build_settings_dict(
            manifest, args.target, args.pack, args.abs_root, args.interpreter
        )
    except EmptyHookSetError as e:
        sys.stderr.write(f"FATAL: {e}\n")
        return 1

    provenance = build_provenance(
        manifest_path=manifest_path,
        generator_path=generator_path,
        target=args.target,
        pack=args.pack,
        abs_root=args.abs_root,
        stage=(args.stage if "stages" in manifest else None),
        interpreter=args.interpreter,
    )
    provenance_text = json.dumps(provenance, indent=2) + "\n"

    text = json.dumps(settings, indent=2) + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(text)
        provenance_path = out_path.parent / PROVENANCE_FILENAME
        provenance_path.write_text(provenance_text)
        print(f"wrote {args.out}")
        print(f"wrote {provenance_path}")
    else:
        print(text)
        print(f"--- {PROVENANCE_FILENAME} (no --out given, printed not written) ---")
        print(provenance_text)

    if args.stage != "none":
        try:
            tool_manifest = build_tool_manifest_dict(
                manifest, args.stage, manifest_path.resolve().parent.parent
            )
        except (EmptyToolSetError, KeyError) as e:
            sys.stderr.write(f"FATAL: {e}\n")
            return 1
        tools_text = json.dumps(tool_manifest, indent=2) + "\n"
        if args.tools_out:
            Path(args.tools_out).write_text(tools_text)
            print(f"wrote {args.tools_out}")
        else:
            print(tools_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
