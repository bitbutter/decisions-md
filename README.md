# decisions-md

Agents forget design decisions. They re-open settled questions and contradict
choices the project already made.

`DECISIONS.md` is a plain file you write yourself, one entry per binding decision.
This plugin makes Claude Code read it before it edits source, keeps the rules in
context when the conversation compacts, and asks you to record new decisions
before the session ends.

It needs no third-party packages and no companion tooling. Drop it into any
project that has a `DECISIONS.md`.

## Install

```
/plugin marketplace add github.com/bitbutter/decisions-md
/plugin install decisions-md
```

This repo is its own marketplace, so those two commands are all you need. Restart
or reload Claude Code afterwards so the hooks register.

Nothing happens yet. The gate, the nudges and the Stop check all no-op silently
until the project has a `DECISIONS.md`, so you can install first and write the file
later. The one exception is the SessionStart hook, which records the session id to
`.decisions/cache/` in every project regardless, so that adding a `DECISIONS.md`
mid-session still works.

## Write the file

Put a `DECISIONS.md` at your project root, or in `docs/`, `support/`, `design/`,
or `decisions/`. One entry looks like this:

```
DEC-INPUT-001: Jumping is bound to the A button.
Status: Active (2026-01-15)
```

`DEC-<AREA>-<NNN>`, then a `Status:` line. Areas are yours to name; the plugin
just groups by them. Valid statuses are `Active`, `Superseded by DEC-AREA-NNN`,
and `Deprecated`.

Run `/decisions --validate` to check the format at any time.

## Use it

From the next session start, editing a tracked file is blocked until you consult
the decisions:

```
/decisions --query jump input      # search
/decisions --area input            # everything in one area
/decisions                         # list areas and counts
```

Any of those unlocks editing for the rest of the session. If the work genuinely
has no design bearing, say so and carry on:

```
/decisions --ack-no-design "fixing a typo in a comment"
```

When you stop, the Stop hook checks whether you edited source without touching
`DECISIONS.md`. If you did, it blocks once and asks whether anything you changed
belongs in the file.

### Amending a decision

To override or refine an existing entry, add a suffix letter rather than editing
the parent:

```
DEC-INPUT-001d: OVERRIDES the binding clause of DEC-INPUT-001. Jumping is bound to B.
Status: Active (overrides DEC-INPUT-001 binding clause)
```

Suffix entries are first-class. They parse, validate, and answer `--query 001d` on
their own. The bundled skill covers when to use one.

## Limitations

Worth knowing before you rely on it.

**The gate is coarse.** One query unlocks the whole session, whatever you queried.
It never checks that what you read bears on what you then edit. It stops you
editing blind; it does not prove the right decision was consulted.

**`--ack-no-design` unlocks unconditionally.** Any agent can declare the work
design-free and proceed. The reason lands in `logs/decisions/ack-log.txt` for you
to read later, and that is the entire check.

**It gates on file extension.** A typo fix in a `.py` file trips the gate. A design
change to a `.json` config does not. You can tune `tracked_extensions`, but the
gate cannot tell a refactor from a rule change.

**Edits outside Claude Code are invisible.** `sed`, `git checkout`, another editor:
none of it registers. The Stop hook can decide you never touched `DECISIONS.md`
when you did.

**The binding reminder is a prompt, not enforcement.** Hooks can block a tool call.
They cannot make a model honour a decision it has read. This shapes behaviour
rather than guaranteeing it.

**The Stop gate fires once per session**, then stays quiet however much more you
edit.

**It costs tokens every turn.** The binding reminder and the area overview are
injected on each prompt.

## Configuration

Optional. Drop `<project>/.decisions/config.json`:

```json
{
  "tracked_extensions": [".py", ".ts", ".rs"],
  "exempt_paths": ["DECISIONS.md", ".decisions/", ".claude/", "vendor/"]
}
```

`tracked_extensions` sets the file types the gate guards. The default covers Godot
(`.gd`, `.tscn`, `.tres`, `.gdshader`, `.gdextension`) and common script types
(`.py`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.rb`, `.go`, `.rs`, `.lua`,
`.sh`, `.ps1`).

`exempt_paths` lists project-relative prefixes that never trip the gate.

An empty list is honoured: `"tracked_extensions": []` turns the gate off and leaves
the nudges and Stop hook running.

## What runs when

| Component | Event | Behaviour |
|-----------|-------|-----------|
| `decisions_session_start.py` | SessionStart | Persists the real session id; re-arms the Stop gate. |
| `decisions_gate.py` | PreToolUse `Write\|Edit` | Blocks edits to tracked files until DECISIONS.md is consulted this session. |
| `decisions_check.py` | PostToolUse `Write\|Edit` | Records edited tracked files; validates DECISIONS.md format on writes. |
| `decisions_nudge.py` | UserPromptSubmit | Reminds when the prior turn edited tracked files; clears the list. |
| `decisions_binding_nudge.py` | UserPromptSubmit | Injects the binding reminder and area overview on every prompt. |
| `decisions_precompact.py` | PreCompact | Carries the binding reminder through context compaction. |
| `decisions_stop_check.py` | Stop | Blocks stop once per session when tracked files were edited but DECISIONS.md was not. |
| `commands/decisions.md` | `/decisions` | The read command. Unlocks the gate. |
| `skills/decisions-binding/` | skill | The abandon/adapt/override protocol. |
| `scripts/query_decisions.py` | | The read CLI behind the command. |

## State

Written into your project, not the plugin install directory. Add `.decisions/` to
your `.gitignore`.

| File | Purpose |
|------|---------|
| `.decisions/cache/current-session-id` | Session id persisted at SessionStart; keyed by gate and CLI. |
| `.decisions/cache/decisions-checked-<id>` | Per-session unlock marker. |
| `.decisions/cache/decisions-pending-edits.json` | Tracked files edited this session; cleared when the nudge fires. |
| `.decisions/cache/stop-hook-fired-this-session` | Once-per-session guard, deleted at the next SessionStart. |
| `logs/decisions/ack-log.txt` | Appended `--ack-no-design` reasons. |

The session id, needed for the per-session unlock marker, resolves in this order:
the `DECISIONS_SESSION_ID` env var, then `.decisions/cache/current-session-id`
written at SessionStart, then a transcript lookup in `~/.claude/projects/` for
`claude -p` workers. If none resolve it refuses to write a marker and exits
non-zero, rather than minting one the gate could never match.

## Python

The hooks call `python3`, standard on macOS and Linux. On Windows, Microsoft Store
Python puts `python3` on PATH; the legacy installer only adds `python`, so either
alias it or replace `python3` with `python` throughout `hooks/hooks.json`.

Standard library only.

## Local install

To run a clone directly:

```
/plugin marketplace add /absolute/path/to/decisions-md
/plugin install decisions-md
```

## License

MIT. See [LICENSE](LICENSE).
