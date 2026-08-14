#!/usr/bin/env bash
# protect-files.sh -- blocks Edit/Write to a hardcoded set of sensitive
# paths: dotenv files, package-lock.json, anything under .git/ or
# migrations/. No escape marker exists for this one (see the header
# comment in .claude/hooks/protect-files.sh) -- there is no "I meant it"
# override, on purpose.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "$DIR/../lib/common.sh"

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

section "protect-files.sh -- an agent tries to Edit a .env file"
BLOCK_EVENT=$(jq -n --arg path "$FIXTURE/.env" \
  '{tool_name: "Edit", tool_input: {file_path: $path, old_string: "OLD=1", new_string: "NEW=2"}}')
expect_block "$HOOKS_DIR/protect-files.sh" "$BLOCK_EVENT" \
  "Edit targeting .env (a real secrets file shape)"

section "protect-files.sh -- the near-miss: a filename that merely CONTAINS 'env'"
ALLOW_EVENT=$(jq -n --arg path "$FIXTURE/config.envoy.yaml" \
  '{tool_name: "Write", tool_input: {file_path: $path, content: "envoy: {}\n"}}')
expect_allow "$HOOKS_DIR/protect-files.sh" "$ALLOW_EVENT" \
  "config.envoy.yaml -- '.env' as a mid-string substring, not the dotenv basename shape. This is the 2026-08-08 fix: an older cut of this hook blocked this file too."

finish
