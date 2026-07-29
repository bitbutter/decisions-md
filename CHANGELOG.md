# Changelog

## [1.1.0] - 2026-07-28

Folds in the fixes made on the `decisions-md-marketplace` copy (0.1.1–0.1.4),
which had diverged from this repo, onto this repo's packaging (config-driven
extensions, shared helper module, test harness, CI). This repo is now the single
canonical source.

### Added
- Repo is now its own marketplace: ships `.claude-plugin/marketplace.json`, so
  `/plugin marketplace add github.com/bitbutter/decisions-md` works directly.
- `is_within_project_root()` — the gate and the PostToolUse recorder now ignore
  edits to files outside the project root. Previously, editing another repo's file
  (or the plugin's own source) from within a gated project could be blocked, and
  was recorded as that project's pending decision-capture, false-blocking its Stop
  gate.
- Suffix decision IDs (`DEC-AREA-NNNb/c/d`) are first-class throughout: parsing,
  validation, the area overview, and `--query`. Previously a suffix entry was
  absorbed into its parent block and was invisible to both `--query` and
  `--validate` (a query for `007d` returned only `007`). `--query` now also
  searches the ID itself, so `--query 007d` matches an entry whose body never
  repeats the ID.
- Skill: a "What belongs in an entry" section (scope test + anti-patterns) and an
  "Amending or superseding" section documenting the suffix convention.

### Changed
- **Default `tracked_extensions` broadened beyond Godot** to common script/source
  types (`.py`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.rb`, `.go`, `.rs`,
  `.lua`, `.sh`, `.ps1`). Still fully overridable per project via
  `.decisions/config.json`.
- Stop-gate and capture-nudge messages state the scope test inline
  (user/designer-facing behavior, not implementation/refactor/bugfix) and the
  concrete anti-patterns. The no-decision-needed path now asks for exactly one
  line, `No DECISIONS.md change needed.`, instead of a verbose paragraph.
- `validate_decisions` now requires an uppercase area (`DEC-[A-Z]+-NNN`), matching
  the read CLI's parser. Lowercase-area entries were never visible to `--query`,
  so validating them was misleading.
- README, docstrings, and the plugin description no longer refer to unpublished
  sibling tooling. The plugin stands alone: standard library only, no external
  tracker, no assumed companion tool.

### Fixed
- **The gate's block message now goes to stderr.** For an exit-2 PreToolUse block
  Claude Code feeds only stderr back to the model; the message was being written to
  stdout and discarded, so the block surfaced as the opaque
  `hook error: [...]: No stderr output` instead of the actionable instructions.

### Removed
- `CHAINLINK_SESSION_ID` env-var support. `DECISIONS_SESSION_ID` is the only
  explicit session-id override.
- `DEPLOY.md` — a one-time internal publishing runbook.

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
  binding-line builder. Standard library only.
- `scripts/query_decisions.py` — Read CLI: area/keyword search, --validate,
  --ack-no-design. Writes the per-session unlock marker so the gate clears.
- `commands/decisions.md` — `/decisions-md:decisions` slash command.
- `skills/decisions-binding/` — The abandon/adapt/override binding protocol as an
  installable skill.
- Per-project config via `<project>/.decisions/config.json` (tracked_extensions,
  exempt_paths). Defaults to Godot file types; override for any stack.
- Portability: all hooks no-op silently when the project has no DECISIONS.md, so
  the plugin can be installed before the file is authored.

### Fixed (carry-over polish from extraction)
- `--query` argument now uses `nargs='*'` so multi-word queries work without
  quoting: `/decisions-md:decisions --query session id` rather than `--query "session id"`.
- `hooks.json` updated to use `python3` (standard on macOS/Linux). Windows users
  with only `python` in PATH: edit `hooks/hooks.json` and replace `python3` with
  `python`, or install Python via the Microsoft Store (adds `python3` to PATH).
