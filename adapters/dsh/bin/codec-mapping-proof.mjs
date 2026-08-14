// codec-mapping-proof.mjs -- exercises the SAME exit-2-blocks rule dsh's real
// codec uses, against the REAL subprocess output captured from faultseed's
// _dispatch.py (not a mock). This is a literal port of the one branch that
// matters (BLOCKING_EXIT_CODE = 2 -> decision:'block', stderr -> reason),
// copied from packages/hooks/hook-protocol/src/codec.ts:11 and :63-70 of the
// deepseek-harness clone, not re-derived from memory.
//
//   const BLOCKING_EXIT_CODE = 2
//   if (exitCode === BLOCKING_EXIT_CODE) {
//     output.decision = 'block'
//     if (trimmedErr.length > 0) output.reason = trimmedErr
//   }
//
// Run with no argument at all: it defaults to its own repo root (this file
// lives at adapters/dsh/bin/, three directories below the checkout root, so
// that root is derived from import.meta.url rather than a hardcoded path --
// no machine-specific argument required to reproduce the receipt in
// README.md/NOTES.md). Pass an explicit path only to point at a DIFFERENT
// faultseed checkout than the one this script ships inside.
//
// This does NOT run dsh itself -- see adapters/dsh/README.md's PARTIAL tier
// label for exactly what that means.
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const BLOCKING_EXIT_CODE = 2 // codec.ts:11

function parseHookOutputExitBranch(exitCode, stderr) {
  // Faithful port of codec.ts:63-70's exit-2 branch only.
  const trimmedErr = stderr.trim()
  const output = { exitCode }
  if (exitCode === BLOCKING_EXIT_CODE) {
    output.decision = 'block'
    if (trimmedErr.length > 0) output.reason = trimmedErr
  }
  return output
}

function runDispatch(harnessRoot, hookName, payload) {
  let stdout = ''
  let stderr = ''
  let exitCode = 0
  try {
    stdout = execFileSync('python3', [`${harnessRoot}/.claude/hooks/_dispatch.py`, hookName], {
      input: JSON.stringify(payload),
      env: { ...process.env, CLAUDE_PROJECT_DIR: harnessRoot },
      encoding: 'utf8',
    })
  } catch (e) {
    exitCode = e.status
    stderr = e.stderr ?? ''
    stdout = e.stdout ?? ''
  }
  return { exitCode, stdout, stderr }
}

// This script's own directory is adapters/dsh/bin/; three levels up is the
// faultseed checkout root (bin -> dsh -> adapters -> root).
const scriptDir = dirname(fileURLToPath(import.meta.url))
const defaultRoot = join(scriptDir, '..', '..', '..')
const harnessRoot = process.argv[2] ?? defaultRoot

let failed = false

for (const [label, command, expectBlock] of [
  ['deny: git rm of a test file', 'git rm tests/test_foo.py', true],
  ['allow: ordinary command', 'ls -la', false],
]) {
  const { exitCode, stderr } = runDispatch(harnessRoot, 'no_bash_test_deletion.py', {
    tool_name: 'Bash',
    tool_input: { command },
  })
  const decoded = parseHookOutputExitBranch(exitCode, stderr)
  const blocked = decoded.decision === 'block'
  console.log(`--- ${label} ---`)
  console.log(`  real subprocess exit code: ${exitCode}`)
  console.log(`  codec.ts exit-2 branch decoded decision: ${decoded.decision ?? '(undefined)'}`)
  if (decoded.reason) console.log(`  reason (from real stderr): ${decoded.reason.split('\n')[0]}`)
  if (blocked === expectBlock) {
    console.log(`  PASS (expected block=${expectBlock}, got block=${blocked})`)
  } else {
    console.log(`  FAIL (expected block=${expectBlock}, got block=${blocked})`)
    failed = true
  }
}

process.exit(failed ? 1 : 0)
