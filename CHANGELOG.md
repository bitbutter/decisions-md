# Changelog

## [1.0.0] - 2026-06-24

First public release. Extracted from the moresque project where the engine was
developed and validated across 23 synthetic-payload checks (gate lock/unlock,
binding injection, stop block-once, per-project config, portability no-op).

### Added
- `decisions_gate.py` — PreToolUse gate: blocks edits to tracked files until
  DECISIONS.md is consulted in the current session.
- `decisions_check.py` — PostToolUse recorder: tracks edited files, validates
  DECISIONS.md format on writes.
- `decisions_nudge.py` — UserPromptSubmit nudge: reminds when prior turn edited
  tracked files without a corresponding decisions check.
- `decisions_binding_nudge.py` — UserPromptSubmit binding reminder: injects the
  "DECISIONS.md is binding" block + area overview on every prompt.
- `decisions_precompact.py` — PreCompact injection: carries the binding reminder
  forward through context compaction.
- `decisions_stop_check.py` — Stop gate: fires once per session when tracked files
  were edited but DECISIONS.md was not touched.
- `decisions_session_start.py` — SessionStart: persists the authoritative session id
  and re-arms the stop gate for each new session.
- `decisions_common.py` — Shared helpers: project-root resolution, config loading,
  binding-line builder. No chainlink / coppice dependency.
- `scripts/query_decisions.py` — Read CLI: area/keyword search, --validate,
  --ack-no-design. Writes the per-session unlock marker so the gate clears.
- `commands/decisions.md` — `/decisions` slash command.
- `skills/decisions-binding/` — The abandon/adapt/override binding protocol as an
  installable skill.
- Per-project config via `<project>/.decisions/config.json` (tracked_extensions,
  exempt_paths). Defaults to Godot file types; override for any stack.
- Portability: all hooks no-op silently when the project has no DECISIONS.md, so
  the plugin can be installed before the file is authored.

### Fixed (carry-over polish from extraction)
- `--query` argument now uses `nargs='*'` so multi-word queries work without
  quoting: `/decisions --query session id` rather than `--query "session id"`.
- `hooks.json` updated to use `python3` (standard on macOS/Linux). Windows users
  with only `python` in PATH: edit `hooks/hooks.json` and replace `python3` with
  `python`, or install Python via the Microsoft Store (adds `python3` to PATH).
- `CHAINLINK_SESSION_ID` env var retained as a convenience alias for
  `DECISIONS_SESSION_ID`; harmless to keep and aids projects migrating from a
  chainlink-based setup.
