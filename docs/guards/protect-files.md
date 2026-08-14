# protect-files

## What it blocks

An `Edit` or `Write` whose target path matches one of four protected shapes:
a dotenv file, the `package-lock.json` lockfile, anything under a `.git/`
directory segment, or anything under an existing `migrations/` directory
segment.

## Why this shape is worth a gate

An agent that hand-edits `.env` can leak or corrupt a live secret, and an
agent that hand-edits `package-lock.json` produces a lockfile that no longer
matches what `npm install` would generate — the next install silently
resolves different transitive versions than what was tested. Editing
`.git/` internals directly bypasses every git safety check. Editing an
already-applied migration is a schema-drift hazard: the file no longer
describes what actually ran against the database, so a fresh environment
built from migrations diverges from one built by upgrading in place. None of
these are things you want an agent's shell one-liner deciding on its own.

## BLOCKED

```
$ echo '{"tool_input":{"file_path":".env"}}' | bash protect-files.sh
Blocked: .env matches protected pattern '.env'
$ echo $?
2
```

## ALLOWED

The nearest legitimate thing is a filename that merely *contains* the
substring `.env` without being a dotenv file — this is the exact
over-match the hook's own history documents (see Known limits):

```
$ echo '{"tool_input":{"file_path":"config.envoy.yaml"}}' | bash protect-files.sh
$ echo $?
0
```

Both commands above were run against this tree this session.

## The escape marker

None. `protect-files.sh` says so in its own header comment: this is a
hardcoded blocklist with no in-command bypass. A legitimate change to one of
these paths goes through a normal git commit/PR path outside the agent, not
an escape hatch inside the hook.

## Scope

Fires on every `Edit`/`Write` — no `engine_dirs` gate, no config file, no
env vars. It cannot go silently inert the way the two `engine_dirs`-scoped
guards can, because it reads no external configuration; the only way to
weaken it is to edit the hardcoded pattern list in the script itself.

The dotenv and lockfile checks match on the file's **basename** (`.env`,
`.env.local`, `.env.production`, exact `package-lock.json`) — not a
substring of the full path. The `.git/`/`migrations/` checks match a
leading-slash-padded directory *segment*, so `notmigrations/foo.sql` and
`mygit/config` do not false-match. A brand-new (not-yet-existing)
`migrations/...` file is exempted, since creating a fresh migration via
`Write` is normal.

**Dependency:** this is the one guard in the pack that shells out to an
external binary, `jq`, to parse its stdin event (see INSTALL.md
"Dependencies"). Before 2026-08-13, a missing or broken `jq` fell through
to the guard's own legitimate empty-file_path allow path — the guard ran,
reported nothing wrong, and PERMITTED every Edit/Write, including to
`.env`. It now checks `jq` explicitly (both "is it on PATH" and "did the
parse itself succeed") and fails **closed**: exit 2, naming jq, if either
check fails. See `.claude/hooks/test_protect_files_missing_jq.py` for the
planted-failure test.

Those two checks are **deliberately redundant** for the absent-`jq` case, and
that is worth knowing before you tidy one away. An independent reviewer
disabled the `command -v jq` branch alone and the tests still passed —
because execution then falls through to the parse-failure branch, which
catches it and exits 2 anyway. Removing either branch alone leaves the hole
closed; removing both opens it, and the two fail-closed tests go red
together. Defense in depth on the one guard in this pack with an external
dependency, stated here so it survives the next simplification pass.

## How we know it fires

`test_protect_files_env_overmatch.py`, 16 test functions covering both
directions. Run this session, from the repo root:

```
$ python3 -m pytest .claude/hooks/test_protect_files_env_overmatch.py -q
................                                                        [100%]
16 passed in 0.09s
```

`test_blocks_dotenv_exact` (`r.returncode == 2`, `"protected pattern '.env'"
in r.stderr`) and `test_allows_envoy_config_yaml` (`r.returncode == 0` for
`config.envoy.yaml`) are the pair this doc's BLOCKED/ALLOWED examples above
mirror directly.

## Known limits

The blocklist is fixed and small — four shapes, no config surface to extend
it. If your repo keeps secrets in a differently-named file (`secrets.yaml`,
`credentials.json`), or has its own equivalent of a generated lockfile this
hook doesn't know about (`poetry.lock`, `Gemfile.lock`, `Cargo.lock`), this
hook does not protect it; you would need to add a pattern to the script
yourself.

The docstring records a real past bug worth knowing before you trust this
file blindly: before the 2026-08-08 fix, the `.env` check was a bare bash
substring test (`[[ "$FILE_PATH" == *".env"* ]]`), so it also blocked
`config.envoy.yaml` and `dev.environment.md` — files that are not dotenv
files at all — while `src/environment.py` happened to pass only because
there is no `.` immediately before `env` in that filename. That was
coincidence, not correct logic. The current basename-exact match fixes it,
but it is the kind of regression a future edit to this script could
reintroduce without a matching test catching it — which is exactly why
`test_allows_envoy_config_yaml` exists and should not be deleted.
