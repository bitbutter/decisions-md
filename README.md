# decisions-md

A rule you settled last week is easy for an agent to contradict today, because nothing in the code states it. `DECISIONS.md` is a plain file with one binding decision per entry. This package reads it, works out which decisions govern the file the agent is about to edit, and puts them in front of the agent at that moment: once per area per session, just before the edit, not in every prompt.

Version 3 is a pi package written in TypeScript, with no dependencies at runtime. It keeps its state outside your repository.

## Harness status

| Harness | Version | Stands |
|---|---|---|
| pi | 3.0.0-rc.1 | Last verified against pi 0.84.2 on 2026-10-22: a real session had the decisions served at edit time, the edit blocked, and the retry pass. |
| Claude Code | 2.2.1 | Its Python test suites pass on this machine as of 2026-10-22 (122 and 12 checks), and `claude plugin validate` passes on both manifests. No live Claude Code session has run it since the fork. Frozen. |

There is no Codex or OpenCode adapter. `docs/ADAPTERS.md` says what one would have to do; `tests/adapters/` builds a fifth adapter from that document alone, to check that `core/` holds no harness knowledge.

## Install

```
pi install git:github.com/bitbutter/decisions-md@v3-rc
```

To run a clone instead:

```
pi install /absolute/path/to/decisions-md
```

Until a project has a `DECISIONS.md`, the extension does nothing. Install now and write the file later. There is no per-project setup: no gitignore entry, nothing to copy in. `.decisions/config.json` is optional.

In a session:

| Command | What it does |
|---|---|
| `/decisions` | Lists the areas, shows one area in full, or searches by keyword |
| `/decisions-lint` | Checks the file's format |
| `/decisions-migrate` | Checks, writes or archives a 2.x file |
| `/decisions-doctor` | Reports what the engine resolved, when something looks inert |

## The file

`DECISIONS.md` goes at your project root, or in `docs/`, `support/`, `design/` or `decisions/`. Exactly one file is read, and the root wins if there are several.

A decision is one line:

```
DEC-ECONOMY-001: Gold is earned in combat only, never from exploring.
```

An ID, a colon, and the rule. The statement can wrap across lines; the parts join with single spaces. Add a `Context:` line underneath when the reasoning is worth keeping:

```
DEC-ECONOMY-001: Gold is earned in combat only, never from exploring.
Context: Encounter rewards are the only source of gold.
```

`DEC-<AREA>-<NNN>`, where an area is two or more capital letters and the number is three digits. Areas can take more than one segment: `DEC-ENEMY-AI-001` is an entry in area `enemy-ai`. Areas are yours to name — INPUT, RENDER, ECONOMY, whatever parts your project has. The engine only uses them for grouping.

The `## Combat` headings are ordinary markdown for your own reading. The area comes from the ID, so headings are optional.

There is no status line and no status vocabulary. Every entry in the file is binding.

A whole file looks like this:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/decisions-example-dark.svg">
  <img alt="A DECISIONS.md file holding five decisions grouped into combat, economy and save areas. Each entry is an ID, a colon and a rule, most with a Context line underneath." src="docs/decisions-example-light.svg" width="860">
</picture>

## What belongs in the file

**1. Could someone violate this without anything failing?**

Do the opposite in your head: does it compile, pass the tests and run? A type, an assert or a test that catches the violation is already holding the rule.

**2. Does it bind work that has not been written yet?**

Name everything that has to obey it. If the list is "anything that ever grants gold", it belongs in the file; if you can finish it, it is a refactor.

A rule against a second source of gold has no list you could finish. Rebind jump to B and you can: the input map, the button prompt art.

### Early decisions

What the player is promised, what a save has to guarantee and what may never happen during a fight all get decided before the code that depends on them exists.

The decisions made in week one are the ones most often lost. One gets made in conversation, acted on once, and then it lives in whoever remembers it. Nothing in the code states it, so an agent can write something reasonable that quietly violates it.

### Changing a decision

Edit it in place and keep its ID. Put the reason in the commit message.

Do not append a second entry that overrides the first, and do not keep a revision log inside the entry. The file states what is true now; `git log -p DECISIONS.md` states what used to be true, with a date, an author and a message.

Keep the ID the same. Code comments refer to these IDs, and a comment pointing at `DEC-INPUT-001` should take you to the rule that applies now.

### Retiring a decision

Delete it. If "we considered X and rejected it" still matters, that is a live rule rather than a retired one, so write it down; otherwise the question is open again.

## How it behaves

**Before an edit.** When pi is about to write to a source file, the extension works out which areas govern that path and blocks the edit with those decisions:

```
[DECISIONS] 2 binding decisions govern src/input/player.gd (area: input).
Read them, then re-run your edit. Nothing else is required to proceed.

DEC-INPUT-001: Jumping is bound to the A button.
DEC-INPUT-002: Holding the jump button does not increase jump height.

If one of these contradicts the change you are about to make, stop and offer the user: abandon / adapt / override. Otherwise just carry on.
```

The model reads that, runs the edit again, and the retry goes through. This happens once per area per session: move from input code to render code and you get the render decisions. A file no decision covers is not interrupted.

**At session start, and after compaction.** A short orientation block queued for the next prompt: how many decisions are on file, per area. The queued message costs no turn.

**When the model stops.** If the session edited files no decision covers, one question goes to the model: should any of this be written down? Nothing is asked when decisions already cover the edited files, when the session wrote `DECISIONS.md` itself, or after it has asked once.

**When `DECISIONS.md` is written.** The lint report is attached to the write's result. The write already happened, so nothing is blocked; the model gets the errors in the same breath.

**Reading them yourself.**

```
/decisions                     # areas and how many decisions each holds
/decisions jump input          # keyword search
/decisions --area input        # one area in full, with the reasoning
```

## Keeping the file small

`/decisions-lint` checks the format, and an error means the file will not be read correctly, so errors block. An ID that looks like a decision but does not parse is reported, never skipped.

Warnings are suggestions and never block anything:

- an entry stating its rule in more than about 120 words — at that length it usually holds more than one rule
- two entries that say nearly the same thing
- an area with more decisions than one person can hold at once

## Migrating from 2.x

The file format is nearly the same. These are the differences:

- **`Status:` lines are errors now.** Every entry in the file is binding; history lives in git.
- **Superseded entries are errors.** They must be archived out of the file, or someone will follow a dead rule.
- **Multi-segment IDs parse.** `DEC-ENEMY-AI-001` was reported as "not binding" before and invisible to the agent; now it is an entry in area `enemy-ai`. A file can gain entries without being edited.
- **Override suffixes are gone.** `DEC-INPUT-001d` is not an entry. Work the rule into the entry it overrides, then delete it.

```
/decisions-migrate                       # check: what can be fixed, what needs a person
/decisions-migrate --archive-superseded  # move superseded records to support/decision_archive.md, then strip them
/decisions-migrate --write               # remove plain Status: lines
/decisions-lint                          # what is left
```

Run the archive before the strip. Stripping a superseded record without archiving promotes a dead rule back to binding. An archive run refuses and writes nothing when a superseded record names no successor, or names one that is not an entry.

`--write` only removes `Status:` lines that carry nothing but a state and a date. Lines with extra text are left, with their line numbers, for you to fold into the statement above and delete. Running either mode twice is a no-op, and a file that is already conforming comes back byte-identical.

## Configuration

Optional. Drop `<project>/.decisions/config.json` — this file belongs to your project and should be committed.

```json
{
  "tracked_extensions": [".py", ".ts", ".rs"],
  "exempt_paths": ["DECISIONS.md", ".decisions/", "tools/"],
  "area_map": { "src/rendering/**": "render", "shaders/**": "render" },
  "enabled": true
}
```

`tracked_extensions` — which file types trigger serving. The default covers Godot (`.gd`, `.tscn`, `.tres`, `.gdshader`, `.gdextension`) and common script types (`.py`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.rb`, `.go`, `.rs`, `.lua`, `.sh`, `.ps1`). A list replaces the defaults; `[]` stops serving before edits and leaves the backstop question running.

`exempt_paths` — project-relative prefixes that never trigger a serve. `tools/` covers `tools/build.py` but not `src/tools/thing.py`. Setting this replaces the default list: `DECISIONS.md`, `.decisions/`, `tools/`, `addons/`, `vendor/`, `third_party/`, `node_modules/`, `.godot/`, `build/`, `dist/`.

`area_map` — file patterns to an area, for files whose names give no clue. A single `*` does not cross a `/`; `**` does.

`enabled: false` — turns automatic serving off for this project. The four commands still answer.

## Limitations

**It guesses which decisions apply to a file.** Three things, in order: your `area_map`, an area name appearing in the file's path, and word overlap between the path and the decision. It can guess wrong in both directions. If a decision governs files whose names give no clue, pin them with `area_map`.

**Showing the model a decision does not make it obey one.** Nothing makes a model follow a rule it has just read, though a block can stop a tool call.

**It only sees the `edit` and `write` tools.** An agent that changes a file with `sed`, a heredoc or a script is not noticed. Nor are edits you make in your own editor, which is harmless: nothing depends on seeing those.

**The backstop question is asked once per session**, and only about files no decision covers. A second uncovered rule in the same session is not asked about.

**It uses some context.** An orientation line for the next prompt, the decisions for each area you touch — the statements, not the reasoning — and that one question at most.

## State

Kept in `~/.decisions-md/state/<project-key>/`, never in your project. It holds which areas this session has already been shown, which files were edited, and which session is which. Deleting it is safe: the only effect is that the model is shown decisions it has already seen.

`DECISIONS_STATE_DIR` moves that folder somewhere else.

## Troubleshooting

Run `/decisions-doctor`.

It reports the engine version, the project root it resolved, the `DECISIONS.md` it found, whether it can write its state folder, and whether a session identity arrived. It reports rather than repairs.

A file that is not in format is not silent: lint reports it, and whatever still parses is still served.

## Tests

`npm install` once for the typecheck, since TypeScript is a dev dependency. The other three use only Node.

```
npm test            # unit tests, pi adapter tests, fifth-adapter test
npm run conformance # every fixture in process and through the CLI, envelopes compared
npm run typecheck   # tsc --noEmit
npm run live        # one real pi session, token checked in the transcript
```

The live check reports `pass`, `fail` or `unchecked`. A check it could not run is never reported as a pass. It needs a model with credentials; `DECISIONS_LIVE_MODEL` picks it.

## Claude Code, frozen at 2.2.1

The Python plugin at the repo root (`hooks/`, `commands/`, `skills/`, `.claude-plugin/`) is the 2.2.1 product, kept for Claude Code. It is frozen, with these terms.

Critical correctness fixes only, with no new features and no port to v3. Its two Python suites pass on this machine as of 2026-10-22: 122 checks of the parser, linter and gate scope, and 12 checks that each hook launches through the shell. No live Claude Code session has run it since the fork, and that is the limit of what is known. Nothing flows from `core/` into it either: the two products share a format and a repository, not a runtime.

A harness that becomes a daily driver for a week is the trigger to port it. Until then, an adapter is written against `docs/ADAPTERS.md` and not before.

```
/plugin marketplace add github.com/bitbutter/decisions-md
/plugin install decisions-md
```

It needs a Python 3 reachable as `python3`, `python` or `py`, and it keeps its state in `~/.claude/decisions-md-state/`.

## License

MIT. See [LICENSE](LICENSE).
