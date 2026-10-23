# decisions-md

decisions-md is a system for writing down the rules of your project while you work on it. A rule is a constraint the project's own content doesn't implicitly establish, and it governs work not yet done. It is built for workflows where you direct an agent to do everything, including the editing of `DECISIONS.md`, and the rules reach the agent before it edits a covered file.

`DECISIONS.md` is a plain file with one binding decision per entry. This package reads it, works out which decisions govern the file the agent is about to edit, and puts them in front of the agent at that moment: once per area per session, just before the edit, not in every prompt.

Version 3 is a pi package in TypeScript, with no dependencies at runtime, and it keeps its state outside your repository. It was verified in a live session against pi 0.84.2. Claude Code runs the older Python plugin, frozen at 2.2.1.

## Install

```
pi install git:github.com/bitbutter/decisions-md@v3-rc
```

To run a clone instead: `pi install /absolute/path/to/decisions-md`.

Until a project has a `DECISIONS.md`, the extension does nothing. There is no per-project setup and nothing to gitignore.

| Command | What it does |
|---|---|
| `/decisions` | Lists the areas, shows one area in full, or searches by keyword |
| `/decisions-lint` | Checks the file's format |
| `/decisions-migrate` | Checks, writes or archives a file in the older 2.x format |
| `/decisions-doctor` | Reports what the engine resolved, when something looks inert |

## The file

`DECISIONS.md` goes at your project root, or in `docs/`, `support/`, `design/` or `decisions/`. Exactly one file is read, and the root wins if there are several.

An entry is an ID, a colon and the rule:

```
DEC-ECONOMY-001: Gold is earned in combat only, never from exploring.
Context: Encounter rewards are the only source of gold.
```

The statement can wrap across lines and the parts join with single spaces. The `Context:` line is optional and holds the reasoning. An ID is `DEC-<AREA>-<NNN>`, where an area is two or more capital letters and the number is three digits; `DEC-ENEMY-AI-001` belongs to area `enemy-ai`. Areas are yours to name, and the engine uses them only for grouping. Headings like `## Combat` are ordinary markdown, for your own reading.

Every entry in the file is binding. There is no status line and no status vocabulary.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/decisions-example-dark.svg">
  <img alt="A DECISIONS.md file holding five decisions grouped into combat, economy and save areas. Each entry is an ID, a colon and a rule, most with a Context line underneath." src="docs/decisions-example-light.svg" width="860">
</picture>

## When to add a rule

Ask what happens if someone violates the constraint. If the project still compiles and the tests still pass, and future rules are likely to depend on this one, it belongs in the file. If a type, an assert or a test would already catch the violation, or no other important rule is likely to depend on it, leave it out.

**Changing one.** Have the agent edit the entry in place and keep its ID, with the reason in the commit message. Do not stack a second entry on top of the first, and do not keep a revision log inside the entry: the file states what is true now, and `git log -p DECISIONS.md` states what used to be true.

**Retiring one.** Have the agent delete it. If "we considered X and rejected it" still matters, that is a live rule rather than a retired one: write the rejection as an entry that names the option and the reason it stays out.

## What happens

**Before an edit.** When pi is about to write to a source file, it is shown the decisions that govern that path, and the edit is blocked once:

```
[DECISIONS] 2 binding decisions govern src/input/player.gd (area: input).
Read them, then re-run your edit. Nothing else is required to proceed.

DEC-INPUT-001: Jumping is bound to the A button.
DEC-INPUT-002: Holding the jump button does not increase jump height.

If one of these contradicts the change you are about to make, stop and offer the user: abandon / adapt / override. Otherwise just carry on.
```

The model runs the edit again and it goes through. This happens once per area per session, so moving from input code to render code brings the render decisions. A file no decision covers is not interrupted.

**At session start, and after compaction.** An orientation line rides on the next prompt: how many decisions are on file, per area. No turn is spent on it.

**When the model stops.** If the session edited files that no decision covers, the extension sends the agent one prompt about a rule the work may have settled. Nothing is sent when decisions already cover the edited files, when the session wrote `DECISIONS.md` itself, or a second time in the same session.

**When `DECISIONS.md` is written.** The lint report is attached to the write's result. The write already happened, so nothing is blocked, and the agent sees the errors immediately.

You can read them yourself:

```
/decisions                     # areas and how many decisions each holds
/decisions jump input          # keyword search
/decisions --area input        # one area in full, with the reasoning
```

## Housekeeping

A `/decisions-lint` error means the file will not be read correctly, so errors block; an ID that looks like a decision but does not parse is reported, never skipped. Warnings are suggestions and never block: an entry stating its rule in more than about 120 words (at that length it usually holds more than one rule), two entries that say nearly the same thing, and an area with more decisions than one person can hold at once.

## Configuration

Optional. Have the agent write `<project>/.decisions/config.json`, or write it yourself. This file belongs to your project and should be committed.

```json
{
  "tracked_extensions": [".py", ".ts", ".rs"],
  "exempt_paths": ["DECISIONS.md", ".decisions/", "tools/"],
  "area_map": { "src/rendering/**": "render", "shaders/**": "render" },
  "enabled": true
}
```

`tracked_extensions` — which file types trigger serving. The default covers Godot (`.gd`, `.tscn`, `.tres`, `.gdshader`, `.gdextension`) and common script types (`.py`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.rb`, `.go`, `.rs`, `.lua`, `.sh`, `.ps1`). A list replaces the defaults; `[]` stops serving before edits and leaves the backstop question running.

`exempt_paths` — project-relative prefixes that never trigger a serve. `tools/` covers `tools/build.py` but not `src/tools/thing.py`. The default is `DECISIONS.md`, `.decisions/`, `tools/`, `addons/`, `vendor/`, `third_party/`, `node_modules/`, `.godot/`, `build/`, `dist/`; setting this replaces it.

`area_map` — file patterns to an area, for files whose names give no clue. A single `*` does not cross a `/`; `**` does.

`enabled: false` — turns automatic serving off for this project. The four commands still answer.

## Limitations

**It guesses which decisions apply to a file.** Three things, in order: your `area_map`, an area name appearing in the file's path, and word overlap between the path and the decision. It can guess wrong in both directions. If a decision governs files whose names give no clue, pin them with `area_map`.

**Showing the model a decision does not make it obey one.** Nothing makes a model follow a rule it has just read, though a block can stop a tool call.

**It only sees the `edit` and `write` tools.** An agent that changes a file with `sed`, a heredoc or a script is not noticed. Nor are edits you make in your own editor, which is harmless: nothing depends on seeing those.

**The backstop question is asked once per session**, and only about files no decision covers.

**It uses some context.** An orientation line for the next prompt, the decisions for each area you touch (the statements, not the reasoning), and that one question at most.

## State, and when it looks inert

State lives in `~/.decisions-md/state/<project-key>/`, never in your project: which areas the session has been shown, which files were edited, which session is which. Deleting it is safe; the only effect is that the model is shown decisions it has already seen. `DECISIONS_STATE_DIR` moves it elsewhere.

`/decisions-doctor` reports the engine version, the project root it resolved, the `DECISIONS.md` it found, whether it can write its state folder, and whether a session identity arrived. It reports rather than repairs. A file that is not in format is never silent: lint names it, and whatever still parses is still served.

## Tests

`npm install` once for the typecheck, since TypeScript is a dev dependency. The other three use only Node.

```
npm test            # unit tests, pi adapter tests, fifth-adapter test
npm run conformance # every fixture in process and through the CLI, envelopes compared
npm run typecheck   # tsc --noEmit
npm run live        # one real pi session, token checked in the transcript
```

The live check reports `pass`, `fail` or `unchecked`; a check it could not run is never reported as a pass. It needs a model with credentials, and `DECISIONS_LIVE_MODEL` picks it. `tests/adapters/` builds a fifth adapter from `docs/ADAPTERS.md` alone, which is how `core/` is kept from growing harness knowledge. There is no Codex or OpenCode adapter.

## Claude Code, frozen at 2.2.1

The Python plugin at the repo root (`hooks/`, `commands/`, `skills/`, `.claude-plugin/`) is the 2.2.1 product, kept for Claude Code and frozen: critical correctness fixes only, no new features, no port to v3. Both Python suites pass on this machine; no live Claude Code session has run it since the fork, and that is the limit of what is known. Nothing flows from `core/` into it either: the two products share a format and a repository, not a runtime. A harness that becomes a daily driver for a week is the trigger to port it; until then an adapter is written against `docs/ADAPTERS.md`.

```
/plugin install decisions-md --marketplace bitbutter/decisions-md
```

On Claude Code older than 2.1.275, add the marketplace first: `/plugin marketplace add github.com/bitbutter/decisions-md`. It needs a Python 3 reachable as `python3`, `python` or `py`, and it keeps its state in `~/.claude/decisions-md-state/`.

## License

MIT. See [LICENSE](LICENSE).
