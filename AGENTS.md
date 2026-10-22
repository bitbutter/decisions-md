# Working on decisions-md

## Two products in one tree

* **v3** is the TypeScript engine: `spec/FORMAT.md` (the format, normative), `docs/ADAPTERS.md` (envelope, verbs, pi mapping), `core/`, `bin/decisions.ts`, `harnesses/pi/`, `tests/core/`, `tests/conformance/`. Node 22 runs the `.ts` sources directly. Checks: `node tests/conformance/run.ts` and `node --test tests/core/*.test.ts`.
* **2.2.0** is the Python plugin at the root (`hooks/`, `commands/`, `skills/`, `.claude-plugin/`). It is frozen: critical fixes only, no new features, no port. Claude Code and Codex installs point at those paths.
* The rest of this file describes 2.2.0. Where it and `spec/FORMAT.md` disagree, the spec wins for v3.

This repository is the plugin **and** its own marketplace. `.Codex-plugin/plugin.json`
declares the plugin; `.Codex-plugin/marketplace.json` lists it. Both carry a `version`
and the two must agree.

## Edits to this clone are not live

Codex does not load the plugin from the clone. It loads a versioned snapshot under
`~/.Codex/plugins/cache/decisions-md/decisions-md/<version>/`, so a file you just edited
here is still the old file as far as a running session is concerned.

To publish a change to your own session:

1. Bump `version` in **both** `.Codex-plugin/plugin.json` and
   `.Codex-plugin/marketplace.json`. A stale version leaves the old snapshot in place.
2. `Codex plugin update decisions-md@decisions-md`
3. Restart Codex, so the hooks re-register.

Skipping the version bump is the usual reason a change appears to have no effect.

## Tests

```
python3 tests/verify_plugin.py        # parser, linter, gate scope, pathological input
python3 tests/verify_hook_launch.py   # each hook actually launches through the shell
```

Use whichever of `python3`, `python` or `py` exists on the machine. Both suites are plain
standard-library Python and take a few seconds. Run both before pushing — the second one
catches manifest and shell-quoting breakage that the first cannot see.

`verify_hook_launch.py` sets `DECISIONS_STATE_DIR` so a test run cannot touch real state.

## Constraints this codebase holds itself to

**Standard library only.** No third-party packages, no companion tooling. The plugin has
to work on a machine where the only thing installed is Python.

**One parser.** Hooks, the CLI and the linter all read decisions through
`parse_decisions()` in `hooks/decisions_common.py`, so they cannot disagree about what an
entry is. Do not add a second reader.

**No plugin state inside a consuming project.** State goes to
`~/.Codex/decisions-md-state/<project-key>/`. The `-state` suffix is load-bearing: the
conventional clone path is `~/.Codex/decisions-md`, so dropping the suffix would write
session scratch into this repository's own working tree. A test asserts that a hook run
creates nothing inside the project.

**The interpreter is resolved at run time.** `python3` is missing from most Windows
installs and `python` from many Linux distributions, so every hook command and the slash
command resolve it with `command -v python3 || command -v python || command -v py`. Do not
hardcode an interpreter name in a manifest.

**Hooks fail loudly, never silently.** A hook that cannot do its job says so. The one
exception is `SessionStart`, which is best-effort because a failure there would wedge
startup.

## Format rules the linter enforces

`DECISIONS.md` states what is true **now**. No status lines, no status vocabulary, no
superseded entries, no override-suffix IDs (`DEC-INPUT-001d`). A changed decision is
edited in place under its original ID; a retired one is deleted. Git holds the history.

Anything left from the pre-2.0 format is a lint error, not a supported mode.
