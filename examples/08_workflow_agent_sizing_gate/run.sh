#!/usr/bin/env bash
# workflow_agent_sizing_gate.py -- the Workflow-tool sibling of
# agent_sizing_gate.py. It statically parses a Workflow's inline script for
# every agent(...) call site and requires each one to declare a `model:`.
# No frontier-leaf concept here (opus is a normal tier); the escape is
# `// workflow-model-ok: <reason>` on the call's own line, and -- as of
# this run -- that marker requires a real reason, same as every other
# escape hatch in this pack.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../lib/common.sh"

section "workflow_agent_sizing_gate.py -- agent() call with no model: at all"
BLOCK_EVENT=$(jq -n \
  '{tool_name: "Workflow", tool_input: {script: "agent(\"do the thing\", {subagent_type: \"general-purpose\"});"}, cwd: "/tmp"}')
expect_block "$HOOKS_DIR/workflow_agent_sizing_gate.py" "$BLOCK_EVENT" \
  "un-sized agent() call site -- would silently inherit the parent's model (Opus during an ultracode session)"

section "workflow_agent_sizing_gate.py -- near-miss: model: \"sonnet\" declared"
ALLOW_EVENT=$(jq -n \
  '{tool_name: "Workflow", tool_input: {script: "agent(\"do the thing\", {model: \"sonnet\"});"}, cwd: "/tmp"}')
expect_allow "$HOOKS_DIR/workflow_agent_sizing_gate.py" "$ALLOW_EVENT" \
  "same call, model: \"sonnet\" present -- a normal, explicitly sized dispatch"

section "workflow_agent_sizing_gate.py -- a bare escape marker with no reason"
BLOCK_EVENT2=$(jq -n \
  '{tool_name: "Workflow", tool_input: {script: "agent(\"do the thing\", {subagent_type: \"general-purpose\"}); // workflow-model-ok"}, cwd: "/tmp"}')
expect_block "$HOOKS_DIR/workflow_agent_sizing_gate.py" "$BLOCK_EVENT2" \
  "'// workflow-model-ok' with no ':' and no reason text -- still blocked (verified live: this used to silently clear the block with zero justification; that gap is closed as of this run, see examples/README.md)"

section "workflow_agent_sizing_gate.py -- the real near-miss: escape marker WITH a reason"
ALLOW_EVENT2=$(jq -n \
  '{tool_name: "Workflow", tool_input: {script: "agent(\"do the thing\", {subagent_type: \"general-purpose\"}); // workflow-model-ok: deliberate parent-inherit for a tiny one-off"}, cwd: "/tmp"}')
expect_allow "$HOOKS_DIR/workflow_agent_sizing_gate.py" "$ALLOW_EVENT2" \
  "same call, marker now carries a real reason after the colon"

finish
