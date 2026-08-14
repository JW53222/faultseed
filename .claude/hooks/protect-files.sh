#!/bin/bash
# protect-files.sh -- PreToolUse hook, matcher: Edit|Write
#
# WHAT IT BLOCKS: an Edit/Write whose target file_path shape matches one of
# four protected shapes -- guards against an agent hand-editing a secrets
# file, a lockfile npm/pip should own, raw git internals, or an EXISTING
# migration (migrations are append-only; editing a past one after it may
# have run is a schema-drift hazard):
#   - a dotenv file: basename is exactly ".env" or starts with ".env."
#     (".env.local", ".env.production") -- basename match, not "contains
#     the substring .env" (see 2026-08-08 fix: the old bare substring test
#     also blocked "config.envoy.yaml" and "dev.environment.md", and only
#     let "environment.py" through by coincidence -- no dot before "env").
#   - the lockfile "package-lock.json" -- exact basename.
#   - anything under a ".git/" directory segment.
#   - anything under a "migrations/" directory segment.
# WHAT IT ALLOWS: a brand-new migration file (path doesn't exist yet -- see
# the `-e "$FILE_PATH"` check) still needs to be created via Write.
# ESCAPE: none -- pre-existing, hardcoded blocklist, no in-command bypass
# marker. A legitimate change to one of these paths goes through a normal
# git commit/PR path outside the agent, not an escape hatch here.
#
# DEPENDENCY: this guard parses its stdin event with `jq`, an external
# binary not otherwise required anywhere in this repo (see INSTALL.md
# "Dependencies" / docs/guards/protect-files.md "Scope"). Three distinct
# outcomes below, told apart deliberately -- collapsing them either blocks
# legitimate traffic or (the bug this comment documents) fails open:
#   1. jq is missing (`command -v jq` fails)   -> BLOCK loudly, name jq.
#   2. jq is present but errors on this input  -> BLOCK loudly, name jq.
#      (`$FILE_PATH` non-zero exit from the pipeline below -- malformed
#      JSON, bad filter, etc.)
#   3. jq succeeds and finds no .tool_input.file_path -> ALLOW. This is a
#      legitimate event shape (not every tool call has a file path), not a
#      parse failure, so it must not be treated as case 2.
# Before this fix, a missing `jq` hit case 1 the same way as case 3 -- bash
# reports "jq: command not found" on stderr, the `$(...)` substitution
# still exits 0 mid-pipeline in the old ungated form, FILE_PATH ends up
# empty, and the existing `-z "$FILE_PATH"` check below silently ALLOWED
# the write. On a machine without jq this guard ran, reported nothing
# wrong, and protected nothing.
#
# Prevent edits to sensitive files

INPUT=$(cat)

if ! command -v jq >/dev/null 2>&1; then
  echo "BLOCKED: protect-files.sh cannot run -- 'jq' is not installed (or not" >&2
  echo "on PATH). This guard depends on jq to parse the tool-call event and" >&2
  echo "check the target file_path against protected patterns (.env," >&2
  echo "package-lock.json, .git/, migrations/). A guardrail that cannot parse" >&2
  echo "its input cannot enforce anything, and the Claude Code hook protocol" >&2
  echo "only treats exit 2 as blocking -- so silently exiting 0 here would" >&2
  echo "look installed while protecting nothing. Refusing to silently wave" >&2
  echo "this tool call through. Install jq (e.g. 'apt install jq' / 'brew" >&2
  echo "install jq' / 'yum install jq') and retry." >&2
  exit 2
fi

if ! FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>&1); then
  echo "BLOCKED: protect-files.sh cannot run -- jq failed to parse the" >&2
  echo "tool-call event on stdin. A guardrail that cannot parse its input" >&2
  echo "cannot enforce anything, and the Claude Code hook protocol only" >&2
  echo "treats exit 2 as blocking -- so silently exiting 0 here would look" >&2
  echo "installed while protecting nothing. Refusing to silently wave this" >&2
  echo "tool call through. jq said:" >&2
  echo "$FILE_PATH" >&2
  exit 2
fi

# jq ran cleanly; an empty result here means the event legitimately has no
# file_path (e.g. a non-Edit/Write tool call), not a parse failure -- allow.
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

BASENAME=$(basename -- "$FILE_PATH")

block() {
  echo "Blocked: $FILE_PATH matches protected pattern '$1'" >&2
  exit 2
}

# Dotenv files: exact ".env", or ".env.<suffix>" -- matched on the basename,
# not anywhere in the path, so "config.envoy.yaml" / "dev.environment.md" /
# "src/environment.py" are not dotenv files and must pass.
if [[ "$BASENAME" == ".env" || "$BASENAME" == .env.* ]]; then
  block ".env"
fi

# Lockfile: exact basename only.
if [[ "$BASENAME" == "package-lock.json" ]]; then
  block "package-lock.json"
fi

# Directory-segment patterns: anything under a ".git/" or "migrations/"
# directory, matched as a path segment (leading-slash-padded so a path that
# merely starts with the segment still matches, without false-matching a
# name like "notmigrations/" or "mygit/" that only shares the substring).
for dirpat in ".git/" "migrations/"; do
  case "/$FILE_PATH" in
    */"$dirpat"*)
      # Allow a brand-new migration file; block only edits to an existing one.
      if [[ "$dirpat" == "migrations/" && ! -e "$FILE_PATH" ]]; then
        continue
      fi
      block "$dirpat"
      ;;
  esac
done

exit 0
