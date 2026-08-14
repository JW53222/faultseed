# no_type_checking_stub

## What it blocks

An `Edit`/`Write`/`MultiEdit` that declares a method or function ONLY inside
an `if TYPE_CHECKING:` block, with no matching runtime `def` in the same
class or module scope.

## Why this shape is worth a gate

Code under `if TYPE_CHECKING:` never executes — `TYPE_CHECKING` is `False` at
runtime, it's `True` only to a static type checker. A method defined solely
in that block type-checks clean (mypy/pyright see the signature and are
satisfied) but does not exist when the program actually runs: calling it
raises `AttributeError`, or worse, an `if hasattr(...)`-style guard silently
takes the wrong branch instead of erroring at all. This hook exists because
that exact shape shipped in production once — a method (`_map_tif`) declared
only under `TYPE_CHECKING` inside a mixin class, passing every static check
while being entirely absent at runtime.

## BLOCKED

```
$ cat ev.json   # Write to src/foo.py:
  # from typing import TYPE_CHECKING
  # class Foo:
  #     if TYPE_CHECKING:
  #         def bar(self) -> int: ...
$ CLAUDE_PROJECT_DIR=$PWD python3 .claude/hooks/no_type_checking_stub.py < ev.json
BLOCKED: this edit declares a method/function ONLY inside an
`if TYPE_CHECKING:` block with no runtime implementation.
  - `bar` (class Foo): TYPE_CHECKING-only stub, no runtime def
...
$ echo $?
2
```

## ALLOWED

The nearest legitimate thing: the identical stub, marked as a documented
host/mixin contract rather than an accidental gap:

```
$ cat ev.json   # same file, adds inside the TYPE_CHECKING block:
  #         # host-provides: Host defines this at runtime
$ CLAUDE_PROJECT_DIR=$PWD python3 .claude/hooks/no_type_checking_stub.py < ev.json
$ echo $?
0
```

Both commands above were run against this tree this session, from the repo
root. A genuinely
unrelated near-miss the hook's own test suite pins: the identical stub with a
matching runtime `def bar(self) -> int: return 1` outside the `TYPE_CHECKING`
guard is never flagged — that's the ordinary, correct pattern this hook
exists to distinguish from the broken one.

## The escape marker

`# host-provides: <reason>` or `# type-stub-ok: <reason>`, on the def's own
source line or the line immediately above it (for a single-line stub). The
regex requires a non-whitespace character after the colon — a bare marker
with no reason does not clear the block.

## Scope

ENGINE-QUALITY — gated on `is_engine_path(path)`, same `engine_dirs` config
(`docs/audit/audit-scope.yaml`) as `no_swallowed_errors.py`. In this tree
that's the placeholder `["src"]`, which is why every probe above uses
`src/...`. Test files are exempted independently via `is_test_file()`, ahead
of and regardless of the engine-scope check. Non-`.py` files are never
policed at all. No env vars are read.

**The same silent-inertness risk as its `engine_dirs` sibling applies here**:
an edit outside the configured directories is `allow()`ed before any AST
walk happens, indistinguishable from "no violation found." See
`no_swallowed_errors.md`'s Scope section for the full mechanism — both hooks
share the exact same config and the exact same failure mode.

Deliberately, this hook applies **per-class including mixins** — there is no
blanket exemption for a class whose name suggests it's a mixin. That's not
an oversight; it's the point. The bug this hook exists to catch (`_map_tif`)
lived in a mixin, and a mixin-name carve-out would have re-opened exactly
that hole.

## How we know it fires

`test_no_type_checking_stub.py`, filed specifically because this hook shipped
in an earlier delivery of this tree with **zero** test coverage. Run this
session:

```
$ python3 -m pytest .claude/hooks/test_no_type_checking_stub.py -q
............                                                            [100%]
12 passed in 0.15s
```

`test_type_checking_only_stub_blocked` plants the bare stub and asserts
`rc == 2`; `test_mixin_class_gets_no_blanket_exemption_blocked` plants the
same shape inside a class literally named `ExecutionMixin` and confirms it
is *still* blocked — pinning that there's no mixin carve-out;
`test_host_provides_marker_with_reason_allowed` /
`test_type_stub_ok_marker_with_reason_allowed` assert `rc == 0`;
`test_bare_marker_without_reason_not_cleared` plants `# host-provides` with
nothing after it and confirms the block still fires;
`test_engine_scope_gate_both_directions` pins the scope boundary in one test
function (`src/...` blocked, `other/...` allowed), the same pattern as its
sibling hook.

## Known limits

The detector is structural (an AST shape: def in `TYPE_CHECKING`, absent at
runtime in the same scope) rather than a name/keyword list — this is the
*good* example the pack's own contributing guide points to, precisely
because it generalizes across codebases regardless of what the method or
class is named.

What it does not catch: it only polices `.py` files — a TypeScript
`declare`-only stub, or the equivalent pattern in another language, is
invisible to this hook. It also only checks that *some* runtime `def` with
the matching name exists in the same class/module scope — it does not verify
the runtime def's signature actually matches the stub's declared signature,
so a runtime def with a different arity or return type still satisfies the
check and is not flagged as a separate kind of drift.

Like `no_swallowed_errors.py`, it inherits the `engine_dirs` topology-coupling
risk in full: the shipped placeholder (`["src"]`) is a guess, not a scan, and
a wrong value means this hook silently covers zero code on your repo until
you fix `docs/audit/audit-scope.yaml`.
