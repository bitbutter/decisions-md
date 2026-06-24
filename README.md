# decisions-md

A Claude Code plugin that turns a project's `DECISIONS.md` into enforced, binding
design memory. No chainlink or coppice dependency — it owns its own `.decisions/`
state and works in any project that has a `DECISIONS.md`.

## What it does

| Component | Event | Behaviour |
|-----------|-------|-----------|
| `decisions_session_start.py` | SessionStart | Persists the real session id; re-arms the Stop gate. |
| `decisions_gate.py` | PreToolUse `Write\|Edit` | Blocks edits to tracked files until DECISIONS.md is consulted this session. |
| `decisions_check.py` | PostToolUse `Write\|Edit` | Records edited tracked files; validates DECISIONS.md format on writes. |
| `decisions_nudge.py` | UserPromptSubmit | Reminds when the prior turn edited tracked files; clears the list. |
| `decisions_binding_nudge.py` | UserPromptSubmit | Injects the "DECISIONS.md is binding" reminder + overview on every prompt. |
| `decisions_precompact.py` | PreCompact | Carries the binding reminder through context compaction. |
| `decisions_stop_check.py` | Stop | Blocks stop once per session when tracked files were edited but DECISIONS.md was not. |
| `commands/decisions.md` | `/decisions` | Read CLI: `/decisions [--area A] [--query K] [--validate]`. Unlocks the gate. |
| `skills/decisions-binding/` | skill | The abandon/adapt/override binding protocol. |
| `scripts/query_decisions.py` | — | The read CLI the command and gate-unlock use. |

All hooks are silent no-ops when the project has no `DECISIONS.md`, so the plugin
can be installed before the file is authored. `DECISIONS.md` may live at the project
root or in `docs/`, `support/`, `design/`, or `decisions/`.

## Install from the marketplace

```
/plugin marketplace add github.com/bitbutter/decisions-md
/plugin install decisions-md
```

Restart or reload Claude Code so the hooks register. Then drop a `DECISIONS.md` into
your project (or an existing subdirectory). On the next session start, the gate
activates: editing a tracked file is blocked until you run `/decisions`.

## Verify the install

In a project with a `DECISIONS.md`:

1. Edit any tracked file (`.gd`, `.tscn`, etc.) — the gate should block.
2. Run `/decisions --query <something>` — the gate unlocks.
3. Edit the file again — succeeds.
4. At session end with unsaved design work — the Stop hook prompts you to capture decisions.

## Per-project configuration (optional)

Drop `<project>/.decisions/config.json` to override defaults:

```json
{
  "tracked_extensions": [".py", ".ts", ".rs"],
  "exempt_paths": ["DECISIONS.md", ".decisions/", ".claude/", "vendor/"]
}
```

- `tracked_extensions` — file types the gate guards (default: Godot set: `.gd`, `.tscn`, `.tres`, `.gdshader`, `.gdextension`).
- `exempt_paths` — project-relative prefixes that never trip the gate.

An explicit empty list is honoured: `"tracked_extensions": []` disables the gate
entirely while keeping the nudges and stop hook.

## DECISIONS.md format

```
DEC-AREA-NNN: Statement of the decision.
Status: Active (YYYY-MM-DD)
```

Valid status values: `Active`, `Superseded by DEC-AREA-NNN`, `Deprecated`.

Check format at any time: `/decisions --validate`.

## State (`.decisions/cache/`, gitignore it)

Files written into the consuming project (not the plugin install dir):

| File | Purpose |
|------|---------|
| `current-session-id` | Session id persisted at SessionStart; keyed by gate and CLI. |
| `decisions-checked-<id>` | Per-session unlock marker written by `query_decisions.py`. |
| `decisions-pending-edits.json` | Tracked files edited this session, cleared on nudge fire. |
| `stop-hook-fired-this-session` | Once-per-session guard for the Stop gate; deleted at next SessionStart. |

Ack reasons are appended to `<project>/logs/decisions/ack-log.txt`.

Add `.decisions/` to your project's `.gitignore`.

## Session id resolution

The plugin derives the session id (needed for the per-session gate unlock marker)
in this order:

1. `DECISIONS_SESSION_ID` env var (explicit override for scripted / CI use).
2. `CHAINLINK_SESSION_ID` env var (convenience alias for projects migrating from chainlink).
3. `.decisions/cache/current-session-id` (written at SessionStart — the normal path).
4. Transcript-based lookup (`~/.claude/projects/`) for `claude -p` autonomous workers.

## Python requirement

Hooks call `python3`. On macOS and Linux `python3` is standard. On Windows:

- **Microsoft Store Python** (recommended): installs `python3` into PATH automatically.
- **Legacy installer**: only `python` is added. Either create a `python3` alias, or
  edit `hooks/hooks.json` and replace every `python3` with `python`.

No third-party packages are required — only the Python standard library.

## Local install (development / pre-marketplace)

```bash
# Register the cloned repo as a local marketplace
/plugin marketplace add /absolute/path/to/decisions-md
/plugin install decisions-md
```

## License

MIT — see [LICENSE](LICENSE).
