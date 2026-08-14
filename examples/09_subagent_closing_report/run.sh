#!/usr/bin/env bash
# subagent_closing_report.py -- a SubagentStop hook. Scans the last few
# assistant-text blocks of the SUBAGENT'S OWN transcript for the two
# required closing-report markers ("Changed outside the literal request:"
# and "Known problems not fixed:", see .claude/rules/honesty-guardrails.md)
# and blocks if either is missing. EXEMPT_AGENT_TYPES (read-only/research
# roles like "Explore") skip the check entirely, regardless of what the
# transcript says -- that is the near-miss below, not a text-content one.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

TRANSCRIPT="$FIXTURE/t.jsonl"
jq -nc '{message: {role: "assistant", content: [{type: "text", text: "I did the thing, all good. Everything looks fine and I verified it manually."}]}}' \
  > "$TRANSCRIPT"

section "subagent_closing_report.py -- transcript has neither required marker"
BLOCK_EVENT=$(jq -n --arg t "$TRANSCRIPT" \
  '{agent_transcript_path: $t, agent_type: "sonnet"}')
expect_block "$HOOKS_DIR/subagent_closing_report.py" "$BLOCK_EVENT" \
  "a 'looks fine, I checked' closing message with neither 'Changed outside the literal request:' nor 'Known problems not fixed:'" \
  CLAUDE_PROJECT_DIR="$FIXTURE"

section "subagent_closing_report.py -- the near-miss: an EXEMPT agent type, same transcript"
ALLOW_EVENT=$(jq -n --arg t "$TRANSCRIPT" \
  '{agent_transcript_path: $t, agent_type: "Explore"}')
expect_allow "$HOOKS_DIR/subagent_closing_report.py" "$ALLOW_EVENT" \
  "identical markerless transcript, but agent_type is \"Explore\" (read-only/research) -- the exemption fires before the transcript is even read"

finish
