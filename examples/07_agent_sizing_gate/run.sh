#!/usr/bin/env bash
# agent_sizing_gate.py -- blocks an Agent-tool call that launches a
# frontier model (opus/fable) as a LEAF (no delegation, full frontier
# rate) unless the prompt carries an explicit `opus-leaf-ok:`/
# `fable-leaf-ok:` sentinel with a real reason. Also blocks a missing or
# unrecognised `model` field outright.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

section "agent_sizing_gate.py -- Agent(model=\"opus\", ...) with no escape sentinel"
BLOCK_EVENT=$(jq -n \
  '{tool_name: "Agent", tool_input: {model: "opus", prompt: "do the thing", subagent_type: "general-purpose"}}')
expect_block "$HOOKS_DIR/agent_sizing_gate.py" "$BLOCK_EVENT" \
  "a frontier model spawned as a leaf -- full frontier cost, no fan-out, serializes work a team would parallelize"

section "agent_sizing_gate.py -- the near-miss: a bounded, justified frontier leaf"
ALLOW_EVENT=$(jq -n \
  '{tool_name: "Agent", tool_input: {model: "opus", prompt: "opus-leaf-ok: one subtle oppositional review", subagent_type: "general-purpose"}}')
expect_allow "$HOOKS_DIR/agent_sizing_gate.py" "$ALLOW_EVENT" \
  "same model, but the prompt carries 'opus-leaf-ok: <reason>' -- a deliberate, narrow exception, not silence"

section "agent_sizing_gate.py -- also blocked: no model declared at all"
BLOCK_EVENT2=$(jq -n \
  '{tool_name: "Agent", tool_input: {prompt: "do the thing", subagent_type: "general-purpose"}}')
expect_block "$HOOKS_DIR/agent_sizing_gate.py" "$BLOCK_EVENT2" \
  "'model' field missing entirely -- every dispatch must declare an explicit tier"

finish
