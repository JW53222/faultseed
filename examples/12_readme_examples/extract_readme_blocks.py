#!/usr/bin/env python3
"""Parse the "### Worked examples" section of README.md into structured,
machine-checkable blocks. Companion to run.sh in this directory -- this
file is the "read the prose" half, run.sh is the "actually run it and
compare" half. Kept as a separate script (not inlined in run.sh) so the
parsing rule is one grep-able place, not buried in bash string munging.

WHY THIS EXISTS: README.md's Worked examples section asserts nine
command/output/exit-code triples were really run, e.g.:

    $ echo '...' | bash .claude/hooks/protect-files.sh
    Blocked: .env matches protected pattern '.env'
    exit 2   (same shape against config.envoy.yaml instead of .env: exit 0)

That assertion has gone stale twice, silently, each time found only by an
external reviewer reading the prose by eye: once a command's real exit code
didn't match what was printed (a missing precondition in the copy-pasted
command), once a later commit changed the scope-gate default and the
scope-gated blocks started printing a CONFIG-ERROR instead of the
documented message. Nothing re-ran the prose against the real hooks after
either was written. This parser is step one of closing that gap: extract
the claims mechanically so run.sh can execute them and diff reality against
the doc, instead of trusting the doc.

WHAT COUNTS AS A CHECKABLE BLOCK (declared subset -- see the module-level
note in run.sh for the full policy): within the Worked examples section,
every fenced ``` code block is inspected line by line. A line starting
with "$ " is a command (order preserved, "$ " stripped). A line matching
^exit \\d+ marks the block "checkable": the digits are the expected exit
code of the block's LAST command, and everything after "exit N" up to the
end of the line is captured verbatim as the near-miss claim (may be
empty). Any other non-blank line in the block is an "output line" -- a
checkable block must have EXACTLY ONE, which is the expected first line of
the last command's stderr. A block with "$ " command(s) but no "exit \\d+"
line at all is "setup": still emitted (run.sh still executes it, in
document order, so later checkable blocks see its effect) but carries no
expected_exit/expected_first_line to assert. README.md uses this shape
exactly once, for the one-time engine_dirs `sed` configure step.

A block with zero "$ " lines, or a checkable block whose output-line count
isn't exactly one, is a PARSE ERROR -- not silently skipped, not silently
guessed at. It is printed to stderr and the whole script exits 1. A parser
that quietly drops a block it can't make sense of is the same "looks
installed, checks nothing" failure this whole repo exists to catch; run.sh
additionally floors the total block count so a parser that matches zero
blocks (e.g. because the section heading text changed) fails loudly too.

NOT extracted, by declared scope, not oversight: the near-miss parenthetical
is captured verbatim in "near_miss" for a human to read in a failure
report, but nothing here (or in run.sh) executes it. "same shape against
config.envoy.yaml instead of .env" is English prose describing a
substitution, not a second command -- mechanically deriving and running a
second command from free text would itself be exactly the fragile,
overfit-to-today's-wording parser this task was warned against building.

Output: one JSON object per line to stdout, in document order:
  {
    "index": 1-based position among ALL parsed blocks (checkable + setup),
    "title": nearest preceding "**`...`**" header text, or "(untitled)",
    "line": README.md line number of the block's opening ``` fence,
    "kind": "checkable" | "setup",
    "commands": [str, ...],            # "$ " stripped, in order
    "expected_exit": int | null,
    "expected_first_line": str | null,
    "near_miss": str | null,
  }
Final line to stderr: "PARSED: <total> block(s) (<checkable> checkable, <setup> setup)"
"""
import json
import re
import sys

SECTION_START = re.compile(r"^### Worked examples\s*$")
SECTION_END = re.compile(r"^## ")  # next level-2 heading closes the section
TITLE_RE = re.compile(r"^\*\*(.+?)\*\*")
FENCE = "```"
EXIT_RE = re.compile(r"^exit\s+(\d+)\b(.*)$")


def fail(msg):
    print(f"PARSE ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        fail("usage: extract_readme_blocks.py <path-to-README.md>")
    readme_path = sys.argv[1]
    with open(readme_path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    # --- Slice out the Worked examples section ----------------------------
    start = None
    for i, line in enumerate(lines):
        if SECTION_START.match(line):
            start = i
            break
    if start is None:
        fail('no line matching "### Worked examples" found -- has the '
             "section heading text changed?")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if SECTION_END.match(lines[i]):
            end = i
            break
    section = lines[start:end]

    # --- Walk the section, pulling out fenced blocks -----------------------
    # Title comes from the line IMMEDIATELY above the fence (no blank line
    # between), not "most recently seen bold text anywhere" -- the latter
    # would leak a stale title onto the untitled `sed` setup block, whose
    # preceding paragraph happens to contain "**scope-gated**" earlier on
    # but not as the line directly touching the fence.
    blocks = []
    i = 0
    while i < len(section):
        line = section[i]
        if line.strip() == FENCE:
            fence_line_no = start + i + 1  # 1-based README.md line number
            # Title is the FIRST line of the contiguous non-blank paragraph
            # immediately above the fence (a header can wrap onto a second
            # descriptive line before the fence starts, e.g.
            # no_bash_test_mutation's and subagent_closing_report's headers
            # below), not necessarily the single line touching the fence --
            # but a blank line still ends the search, which is what keeps
            # this from leaking a stale title onto the untitled `sed` setup
            # block (see comment above the loop).
            k = i - 1
            while k >= 0 and section[k].strip() != "":
                k -= 1
            para_start = k + 1
            block_title = None
            if para_start < i:
                tm = TITLE_RE.match(section[para_start].strip())
                if tm:
                    block_title = tm.group(1).strip()
            body = []
            j = i + 1
            while j < len(section) and section[j].strip() != FENCE:
                body.append(section[j])
                j += 1
            if j >= len(section):
                fail(f"unterminated ``` fence starting at README.md:{fence_line_no}")

            commands = []
            output_lines = []
            expected_exit = None
            near_miss = None
            for bline in body:
                if bline.startswith("$ "):
                    commands.append(bline[2:])
                elif bline.strip() == "":
                    continue
                else:
                    em = EXIT_RE.match(bline)
                    if em:
                        expected_exit = int(em.group(1))
                        rest = em.group(2).strip()
                        near_miss = rest if rest else None
                    else:
                        output_lines.append(bline)

            if not commands:
                fail(f"fenced block at README.md:{fence_line_no} "
                     f"('{block_title or '(untitled)'}') has no \"$ \"-prefixed "
                     "command line -- not a recognized worked-example shape")

            if expected_exit is None:
                kind = "setup"
                if output_lines:
                    fail(f"fenced block at README.md:{fence_line_no} "
                         f"('{block_title or '(untitled)'}') has output line(s) "
                         'but no "exit N" line -- ambiguous shape, refusing to guess')
                expected_first_line = None
                block_title = block_title or "(untitled setup step)"
            else:
                kind = "checkable"
                if len(output_lines) != 1:
                    fail(f"fenced block at README.md:{fence_line_no} "
                         f"('{block_title or '(untitled)'}') is checkable (has an "
                         f"exit line) but has {len(output_lines)} output line(s), "
                         "expected exactly 1 -- ambiguous shape, refusing to guess "
                         "which one is the assertion")
                expected_first_line = output_lines[0]
                block_title = block_title or "(untitled checkable block)"

            blocks.append({
                "index": len(blocks) + 1,
                "title": block_title,
                "line": fence_line_no,
                "kind": kind,
                "commands": commands,
                "expected_exit": expected_exit,
                "expected_first_line": expected_first_line,
                "near_miss": near_miss,
            })
            i = j + 1
            continue
        i += 1

    if not blocks:
        fail("Worked examples section found but contains zero fenced code "
             "blocks -- section slicing is almost certainly wrong")

    for b in blocks:
        print(json.dumps(b))

    checkable = sum(1 for b in blocks if b["kind"] == "checkable")
    setup = sum(1 for b in blocks if b["kind"] == "setup")
    print(f"PARSED: {len(blocks)} block(s) ({checkable} checkable, {setup} setup)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
