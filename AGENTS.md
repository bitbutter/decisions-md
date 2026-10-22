# Working on decisions-md

## Issue tracking

`chainlink` owns this repo's issues, in a project-local tracker at `.chainlink/` (gitignored, with `.claude/` and `.mcp.json` that `chainlink init` also drops in). `chainlink issue next` for the next item, `chainlink session work <N>` while on it, `chainlink session end --notes` at the end. **Always close with `--no-changelog`**: without it chainlink appends a line to `CHANGELOG.md` under the newest released version, which is edited by hand.

## Two products in one tree

* **v3** is the TypeScript engine: `spec/FORMAT.md` (the format, normative), `docs/ADAPTERS.md` (envelope, verbs, pi mapping), `core/`, `bin/decisions.ts`, `harnesses/pi/`, `tests/core/`, `tests/conformance/`. Node 22 runs the `.ts` sources directly. Checks: `npm install` once, then `npm test` (unit + adapter + fifth-adapter), `npm run conformance` (fixtures, in process and through the CLI), `npm run typecheck`, and `npm run live` (one real pi turn; reports pass/fail/unchecked).
* **2.2.1** is the Python plugin at the root (`hooks/`, `commands/`, `skills/`, `.claude-plugin/`). It is frozen: critical fixes only, no new features, no port. Claude Code installs point at those paths.
* The rest of this file describes the Python plugin. Where it and `spec/FORMAT.md` disagree, the spec wins for v3.

## This repo is a plugin and its own marketplace

`.claude-plugin/plugin.json` declares the plugin; `.claude-plugin/marketplace.json` lists it. Both carry a `version` and the two must agree. `commands/decisions.md` is a slash command with YAML frontmatter — quote any value that contains `[`, `|` or `:`, because a broken frontmatter block drops every field including `allowed-tools` and nothing else complains.

## Edits to this clone are not live

Neither harness loads the plugin from the clone. Claude Code loads a versioned snapshot under `~/.claude/plugins/cache/decisions-md/decisions-md/<version>/`; a Codex install, if you have one, mirrors that under `~/.Codex/plugins/cache/`. A stale version leaves the old snapshot in place.

To publish a change to your own session:

1. Bump `version` in **both** `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
2. `claude plugin update decisions-md@decisions-md` (or `Codex plugin update decisions-md@decisions-md`).
3. Restart the harness, so the hooks re-register.

## Tests

```
python tests/verify_plugin.py        # parser, linter, gate scope, pathological input
python tests/verify_hook_launch.py   # each hook actually launches through the shell
npm test                             # v3 unit, adapter and fifth-adapter tests
npm run conformance                  # fixtures, in process and through the CLI
npm run typecheck                    # tsc --noEmit
npm run live                         # one real pi turn, token checked in the transcript
```

Use whichever of `python3`, `python` or `py` exists on the machine. Both Python suites are plain standard-library Python and take a few seconds. Run the suites your change touches; run both Python suites before pushing, because the launch one catches manifest and shell-quoting breakage the first cannot see.

`verify_hook_launch.py` sets `DECISIONS_STATE_DIR` so a test run cannot touch real state.

CI runs the Python suites and `claude plugin validate` on Linux, macOS and Windows, plus the v3 checks on those three platforms. `validate` runs without `--strict` on purpose: this repo carries warnings it will not fix (no root `CLAUDE.md`, and a folder that holds both manifests), and a red job nobody reads is how the command's broken frontmatter survived from 1.0.0.

## Constraints this codebase holds itself to

**Standard library only, on the Python side.** No third-party packages, no companion tooling. The plugin has to work on a machine where the only thing installed is Python. The TypeScript side has no runtime dependencies either; typescript and `@types/node` are dev dependencies.

**One parser.** Hooks, the CLI and the linter all read decisions through `parse_decisions()` in `hooks/decisions_common.py`, so they cannot disagree about what an entry is. Do not add a second reader. v3 has its own single reader, `core/parse.ts`, and the same rule applies.

**No plugin state inside a consuming project.** State goes to `~/.claude/decisions-md-state/<project-key>/` (and `~/.decisions-md/state/<project-key>/` for v3). The `-state` suffix is load-bearing: the conventional clone path is `~/.claude/decisions-md`, so dropping the suffix would write session scratch into this repository's own working tree. A test asserts that a hook run creates nothing inside the project.

**The interpreter is resolved at run time.** `python3` is missing from most Windows installs and `python` from many Linux distributions, so every hook command and the slash command resolve it with `command -v python3 || command -v python || command -v py`. Do not hardcode an interpreter name in a manifest.

**Hooks fail loudly, never silently.** A hook that cannot do its job says so. The one exception is `SessionStart`, which is best-effort because a failure there would wedge startup.

**Adapters hold no decision knowledge.** In v3, `core/` must not learn a harness name or event, and an adapter must not parse, match, lint or keep decision state. The fifth-adapter test under `tests/adapters/` is the guard.

## Format rules the linter enforces

`DECISIONS.md` states what is true **now**. No status lines, no status vocabulary, no superseded entries, no override-suffix IDs (`DEC-INPUT-001d`). A changed decision is edited in place under its original ID; a retired one is deleted. Git holds the history.

Anything left from the pre-2.0 format is a lint error, not a supported mode.
