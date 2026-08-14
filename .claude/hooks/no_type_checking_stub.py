#!/usr/bin/env python3
"""no_type_checking_stub.py  --  PreToolUse hook, matcher: Edit|Write|MultiEdit

Blocks a specific dishonest shape: declaring a method ONLY inside an
`if TYPE_CHECKING:` block, with no runtime `def` for it on the same class. At
type-check time the method "exists" (mypy/pyright are happy); at runtime it
does not, so any call AttributeErrors — or, worse, silently falls through to
a different code path. The motivating bug had exactly this shape: two methods
declared as TYPE_CHECKING-only stubs with no runtime implementation.
CRUCIALLY, that bug lived inside a MIXIN class, so this hook MUST be able to
catch the shape inside a mixin — a blanket "skip all mixins" rule would
neuter the guard against the exact bug it exists for.

How it works
------------
We parse the FULL post-edit file (Write gives us the whole body; for Edit we
can only see the fragment, so we read the on-disk file and apply the edit in
memory to get an accurate AST — falling back to the fragment if that fails).
Then, per class (and at module level):

  1. Collect every method name `def`'d / `async def`'d directly in the class
     body at RUNTIME (i.e. NOT nested inside an `if TYPE_CHECKING:` guard).
  2. Collect every method name declared ONLY inside an `if TYPE_CHECKING:` (or
     `if typing.TYPE_CHECKING:`) block in the class body.
  3. Any name in set (2) but NOT in set (1) is a TYPE_CHECKING-only stub. It is
     BLOCKED BY DEFAULT — regardless of whether the class is a mixin.

Module-level functions get the same treatment (a top-level def that exists
only under TYPE_CHECKING is the same lie).

The legitimate mixin-contract escape (bypass-with-justification)
----------------------------------------------------------------
A mixin legitimately declares the methods it expects its HOST class to provide
as TYPE_CHECKING stubs (the host supplies them at composition time). That is a
real pattern — but it must be DECLARED, not inferred from the class name. We do
NOT blanket-skip `*Mixin` classes (that is what let the motivating bug's
shape through). The dev must put an explicit inline marker on the
TYPE_CHECKING `def` line:

    if TYPE_CHECKING:
        # host-provides: HostClass defines this at runtime
        def some_method(self, *a, **k) -> Any: ...

Accepted markers (each REQUIRES a non-empty rationale after the colon):
    # host-provides: <reason>
    # type-stub-ok: <reason>

The marker forces the dev to articulate WHY it's legitimate (which host
implements it), and a future audit can grep `host-provides`/`type-stub-ok` to
find every such contract. A bare marker with no rationale does NOT count — it
is treated as unmarked, exactly like the falsy-zero gate's `# falsy-zero-ok:`
philosophy.

Result:
  - A NEW unmarked TYPE_CHECKING stub in ANY class (including a mixin) -> BLOCK
    (this catches a recurrence of the motivating bug's shape inside a mixin).
  - A marked mixin-contract stub -> ALLOW.

Deliberate non-triggers (these are legitimate and must NOT block):
  - `@overload` signatures (real runtime defs, just multiple).
  - Attribute *annotations* inside TYPE_CHECKING (`x: int` with no value) —
    those are type hints, not method stubs; we only police def/async def.
  - A method declared under TYPE_CHECKING that ALSO has a runtime def
    (the stub-plus-impl pattern people use for typing precision).
  - Imports under TYPE_CHECKING (the documented circular-dep workaround).
  - A TYPE_CHECKING stub carrying an explicit `# host-provides:` /
    `# type-stub-ok:` marker with a rationale (the host-contract escape).
  - Non-Python files.

This is the AST-shaped guard the regex hooks can't express.

BLOCKS: a method/function `def`'d ONLY inside `if TYPE_CHECKING:` with no
runtime def sibling, in any class (including mixins) or at module level.
ESCAPE: `# host-provides: <reason>` or `# type-stub-ok: <reason>` on the
TYPE_CHECKING-only def line. Rationale is REQUIRED — a bare marker with no
text after the colon does not count (see MARKER regex).
"""

import ast
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import (
    load_event, extract, block, allow, is_test_file, is_engine_path,
    is_generated_path,
)

# Explicit "this stub is a host-provided contract" markers. A rationale after
# the colon is REQUIRED — a bare marker is treated as unmarked (same as the
# falsy-zero gate's `# falsy-zero-ok:` requires a reason).
MARKER = re.compile(r"#\s*(?:host-provides|type-stub-ok)\s*:\s*\S")


def _is_type_checking_test(test):
    """True if an `if` test is `TYPE_CHECKING` or `typing.TYPE_CHECKING`."""
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return False


def _defs_in_body(body):
    """Names of functions def'd directly in a statement list (not recursing
    into nested classes/functions, but DOES descend into plain if/else)."""
    names = set()
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.If) and not _is_type_checking_test(stmt.test):
            # a normal runtime `if` (e.g. version guard) still defines at runtime
            names |= _defs_in_body(stmt.body)
            names |= _defs_in_body(stmt.orelse)
    return names


def _type_checking_only_defs(body, src_lines):
    """Map of {name: marked} for functions def'd inside an `if TYPE_CHECKING:`
    block in this statement list. `marked` is True iff the def carries an
    explicit `# host-provides:`/`# type-stub-ok:` rationale marker on the same
    source line (or, for a multi-line signature, on any of its lines)."""
    found = {}
    for stmt in body:
        if isinstance(stmt, ast.If) and _is_type_checking_test(stmt.test):
            for inner in stmt.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found[inner.name] = _has_marker(inner, src_lines)
    return found


def _has_marker(node, src_lines):
    """True if the def node's source span carries a host-contract marker."""
    if not src_lines:
        return False
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", start)
    if start is None:
        return False
    # Scan the def's own source lines for the marker. (Single-line `def f(): ...`
    # stubs put the marker on the line above; ast doesn't span comments, so also
    # check the immediately preceding line.)
    lo = max(1, start - 1)
    hi = end or start
    for ln in range(lo, hi + 1):
        if 1 <= ln <= len(src_lines) and MARKER.search(src_lines[ln - 1]):
            return True
    return False


def _find_stubs(tree, src_lines):
    """Return list of (scope_label, name) for UNMARKED TYPE_CHECKING-only def
    stubs. Marked (host-provides/type-stub-ok) stubs are allowed and omitted."""
    stubs = []

    # module-level
    runtime = _defs_in_body(tree.body)
    tc_only = _type_checking_only_defs(tree.body, src_lines)
    for name in sorted(tc_only):
        if name in runtime:
            continue
        if tc_only[name]:  # marked -> allowed
            continue
        stubs.append(("module", name))

    # per class — NO blanket mixin/protocol skip. The motivating bug lived in
    # a mixin, so a mixin stub is blocked-by-default and only excused by an
    # explicit inline marker (handled in _type_checking_only_defs).
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            runtime = _defs_in_body(node.body)
            tc_only = _type_checking_only_defs(node.body, src_lines)
            for name in sorted(tc_only):
                if name in runtime:
                    continue
                if tc_only[name]:  # marked -> allowed
                    continue
                stubs.append((node.name, name))
    return stubs


def _reconstruct_post_edit(event, path, added):
    """Best-effort full post-edit source.

    Write: the added text IS the whole file.
    Edit/MultiEdit: read the current on-disk file and apply the string
    substitution(s) so we parse the real resulting file, not a fragment.
    Falls back to the added fragment if the file can't be read/applied.
    """
    tool = event.get("tool_name", "")
    ti = event.get("tool_input", {}) or {}

    if tool == "Write" or ti.get("content") is not None:
        return ti.get("content") or added

    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError:
        return added  # new file via Edit shouldn't happen; fall back

    edits = []
    if ti.get("old_string") is not None:
        edits.append((ti["old_string"], ti.get("new_string") or ""))
    for e in ti.get("edits", []) or []:
        if e.get("old_string") is not None:
            edits.append((e["old_string"], e.get("new_string") or ""))

    for old, new in edits:
        if old and old in src:
            src = src.replace(old, new, 1)
    return src


def main():
    event = load_event()
    path, added, _removed = extract(event)

    if not path or not path.endswith(".py"):
        allow()
    # Test files declaring typing stubs are not the failure mode we care about;
    # the motivating bug was production source. Skip tests to avoid noise.
    if is_test_file(path):
        allow()
    # Engine-quality hook: only police the engine source dirs configured in
    # audit-scope.yaml's engine_dirs. The motivating bug lived in an
    # engine-quality source dir; this hook is inert for docs/frontend/strategy
    # edits (role-independent path scope).
    if not is_engine_path(path):
        allow()
    # Generated/vendored trees under engine dirs (backend/mutants/, ...)
    # are build artifacts, not hand-authored source — never police them.
    if is_generated_path(path):
        allow()

    src = _reconstruct_post_edit(event, path, added)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # If the post-edit file doesn't parse, don't block on this hook —
        # other tooling will surface the syntax error.
        allow()

    src_lines = src.splitlines()
    stubs = _find_stubs(tree, src_lines)
    if stubs:
        lines = [
            "BLOCKED: this edit declares a method/function ONLY inside an "
            "`if TYPE_CHECKING:` block with no runtime implementation.\n"
        ]
        for scope, name in stubs:
            where = f"class {scope}" if scope != "module" else "module level"
            lines.append(f"  - `{name}` ({where}): TYPE_CHECKING-only stub, no runtime def")
        lines.append(
            "\nThis type-checks clean but does not exist at runtime — any call "
            "raises AttributeError or silently takes a wrong branch (this is the "
            "exact shape of the motivating bug: a TYPE_CHECKING-only stub with no "
            "runtime def, living inside a mixin class). Add a real `def` for it outside the "
            "TYPE_CHECKING guard, or remove the stub. If you genuinely only need "
            "the type and never call it, annotate it as an attribute "
            "(`name: Callable[...]`), not a def.\n"
            "If this is a legitimate mixin/host contract (the host class supplies "
            "the method at runtime), put an explicit marker with a rationale on "
            "the stub: `# host-provides: <which host implements it>` (or "
            "`# type-stub-ok: <reason>`). A bare marker with no reason does not "
            "count."
        )
        block("\n".join(lines))

    allow()


if __name__ == "__main__":
    main()
