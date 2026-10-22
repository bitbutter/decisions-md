# Changelog

## [3.0.0-rc.1] - 2026-10-22

### Added — the v3 engine, as a pi package

The engine is rewritten in TypeScript, under `core/`, and exported as plain functions. It
answers every request with one of four actions: `none`, `inject`, `block`, `fail`. The
package ships source, needs Node 22.18 or newer, and has no dependencies at runtime.

`harnesses/pi/` is the only adapter. It blocks the first edit in each new area with the
decisions that govern that path, queues the orientation block for the next prompt at
session start and again after compaction, asks the uncovered question once per session,
and attaches the lint report to any write of `DECISIONS.md`.

`bin/decisions.ts` is the subprocess envelope — one JSON object in on stdin, one out on
stdout, exit 0 for every handled request including `block` and `fail`. It exists for
harnesses that cannot import core.

`spec/FORMAT.md` is the normative format and `docs/ADAPTERS.md` is the adapter contract.
Where either disagrees with 2.2.0, v3 follows the document.

### Changed — the format

- **Multi-segment area IDs parse.** `DEC-ENEMY-AI-001` was reported as not binding and was
  invisible to the agent; it is now an entry in area `enemy-ai`. A 2.x file can gain
  entries without being edited.
- **`Status:` lines are format errors.** Every entry in the file is binding, and git holds
  the history. Lint blocks on them.
- **Superseded records are format errors** until they are archived out of the file.
- **Override-suffix IDs are gone.** `DEC-INPUT-001d` is not an entry.
- An ID that looks like a decision but does not parse is always reported, never skipped.

### Added — migrate

`/decisions-migrate` checks, writes or archives. `--archive-superseded` moves superseded
records into `support/decision_archive.md` with a dated header and then strips them, and
refuses the whole run — writing nothing — when a record names no successor or names one
that is not an entry. `--write` removes only `Status:` lines that carry nothing but a state
and a date, and leaves the rest with line numbers. Either mode is a no-op on a second run.

### Fixed

- **The length warning counts the entry, not its neighbourhood.** 2.2.0 counted every
  non-blank line from an entry's ID line to the next ID line, so a heading and a paragraph
  after the closing blank line could make a one-line rule look nine lines long. The
  warning now counts only the lines the entry occupies.
- **`--write` does not treat superseded records as hand work.** Their `Status:` lines are
  counted separately and reported as `--archive-superseded`'s job, instead of asking you to
  fold a dead record into the statement above it.
- **A serve is never spent on nothing.** An area whose entries all have empty statements is
  dropped before any area is marked served, so one bad entry cannot silence that area for
  the rest of the session.

### Verified

- **pi**: last verified against pi 0.84.2 on 2026-10-22, in a real session. The decisions
  were served at edit time, the edit was blocked, the retry passed, and the served token
  was found in the session transcript.
- **Claude Code 2.2.0**: unchanged since the fork. Its Python suites pass on this machine
  as of 2026-10-22 (122 and 12 checks); no live Claude Code session has run it since the
  fork. Frozen at 2.2.0, and the Python plugin at the repo root still installs from this
  repository's marketplace.

The test surface: 75 unit and adapter tests, 15 conformance fixtures that run twice —
in process and through the CLI — with the two envelope sequences compared field by field,
and a fifth adapter written from `docs/ADAPTERS.md` alone.

## [2.2.0] - 2026-08-01

### Changed — what qualifies as a decision

The bar was "would a user or designer care?", which asks for a judgement and gets a yes
almost every time. It is now two questions with checkable answers, and both must be yes:

1. **Could someone violate this without anything failing?** If a type, an assert or a test
   would catch it, that mechanism already holds the rule, and a second copy in the file
   goes stale unnoticed.
2. **Does it bind work that has not been written yet?** If you can finish naming what has
   to obey it, that is a refactor. If the honest answer is "anything that ever grants
   gold", it is a decision.

The second question is what separates a decision from a setting. A button binding has a
short, knowable list. A rule against a second source of gold has every reward that will
ever be written on it.

- The README gains a section on what belongs in the file, and why the bar sits there:
  these choices are usually settled before the code that depends on them exists, which is
  what makes them constrain so much of the later work — and what makes them easy to lose,
  since nothing in the code states them.
- The skill asks for the same two answers when proposing an entry, and says to propose the
  change rather than the entry when the affected places can be listed.
- **One rule per entry.** "Autosaves on room exit, never mid-combat" is two rules: the
  trigger site owns the first, nothing owns the second.
- The README example is rebuilt from entries that pass both questions. Whole-number damage
  was dropped — in most projects a type already holds it.

## [2.1.1] - 2026-08-01

### Fixed

- **A blank line now closes an open field.** Prose following a decision — a markdown
  heading grouping the next entries, a note between them — was appended to the last
  field's value. It printed as part of the entry, and its words joined the entry's search
  tokens, so a heading could pull an unrelated decision into the set surfaced for a file.
  A field still wraps onto the next line when no blank line separates them.

### Changed

- The README example is built from decisions other work has to honour, rather than
  settings nothing depends on.

## [2.1.0] - 2026-08-01

The plugin now carries everything it needs to explain itself. Nothing about it has to
live in a user's `CLAUDE.md`.

### Added

- **The `decisions-binding` skill documents the headless invocation.** In a `claude -p`
  run the slash command does not reliably dispatch, so the skill now gives the direct
  script call alongside it. This was the one piece of operating knowledge the plugin
  expected you to have written down somewhere else.
- **`CLAUDE.md` for this repository**, holding the development loop: edits to a clone are
  not live until the version is bumped in both manifests and the plugin is updated. A
  contributor cloning this repo had no way to learn that.
- **An example file in the README**, as a light and dark image so it reads in either
  GitHub theme.

## [2.0.0] - 2026-07-29

A rewrite around one rule: **DECISIONS.md states what is true now, and git holds what
used to be true.** Everything that existed to preserve history inside the file is gone,
and the gate stopped being a gate.

### Changed — the file format (breaking)

- **No `Status:` line.** Every entry in the file is binding; a line that said so on
  every entry said nothing. `Active`, `Superseded by …` and `Deprecated` are gone with
  it. A leftover `Status:` line is now a lint error.
- **No override-suffix IDs.** `DEC-INPUT-007d` used to mean "overrides part of
  DEC-INPUT-007", which meant reading two entries and reconciling them to learn one
  rule. To change a decision, edit it in place and keep its ID — code comments cite
  those IDs, and a citation should lead to the rule in force. Put the reason in the
  commit message.
- **Retiring a decision means deleting it.** If "we rejected X" still binds future
  work, that is a live rule and should be written as one.
- A decision is now one line: `DEC-AREA-NNN: The rule.`, plus an optional `Context:`.
- `/decisions-md:decisions --lint --write` removes the plain `Status:` lines for you
  and reports the ones carrying text that needs a human decision.

### Changed — the gate became a delivery mechanism

- **The PreToolUse hook now serves the decisions that govern the file being edited**
  instead of blocking until someone runs a query. It matches the target path to
  decision areas, prints those decisions, and lets the retry through. A file no
  decision covers passes in silence.
- One block per area per session, rather than one per session regardless of relevance.
  Moving from input code to render code shows you the render decisions.
- `--ack-no-design` is gone, along with `logs/decisions/ack-log.txt`. It existed to
  escape a block that no longer happens for work with no design bearing.
- `decisions_gate.py` is now `decisions_serve.py`.

### Changed — state left your repositories

- Plugin state moved to `~/.claude/decisions-md-state/<project>/`. It used to be written
  into every project you opened, including projects with no `DECISIONS.md`, where an
  agent running `git add -A` could commit it. Adding `.decisions/` to `.gitignore` is
  no longer part of adopting the plugin. A project's `.decisions/config.json` stays in
  the project, where it belongs.
- `--doctor` reports a leftover `.decisions/cache/` and tells you it is safe to delete.

### Removed

- The **UserPromptSubmit hooks**, both of them. The binding reminder was static text
  re-sent on every prompt; it is now emitted once at SessionStart and again through
  compaction. The post-edit nudge duplicated the Stop check with worse timing.
- Seven hooks are now five.

### Changed — less pressure to write things down

- **The Stop check only fires for work in areas no decision covers.** If a rule
  already governs the files you touched, you probably did not just invent one, and
  asking anyway is how a decisions file fills with entries nobody needed.
- Its default answer is now explicitly "no entry is needed", and proposing one
  requires naming the existing decision it was checked against.
- `--lint` gained bloat warnings: oversized entries, near-duplicate statements,
  file and function names in a statement, and areas past ~25 entries.

### Fixed

- **Parallel tool calls lost each other's state.** Every hook process read one shared
  session JSON, changed a field and wrote it back, so two hooks running at once
  silently discarded each other — measured, 20 parallel edit-recordings kept 8. Each
  fact is now its own small file and nothing is read-modify-written; "has this area
  been served" is settled by an atomic create, which exactly one process can win.
- **An edit could be blocked forever.** The serve hook printed its decisions and
  blocked, trusting a state write it never checked. If that write failed — on Windows,
  any sync client or scanner holding the file is enough — the block repeated on every
  retry with no way through. It now blocks only after successfully claiming the area.
- **Any non-UTF-8 byte in DECISIONS.md crashed every hook**, with a traceback, on
  every edit. `UnicodeDecodeError` is a `ValueError`, not an `OSError`, so it slipped
  past the handler. A file saved in the Windows system codepage was enough. Decoding
  is now lenient and `--lint` reports the encoding instead.
- **The Stop check could be silently cancelled by an unrelated edit.** It asked git
  whether DECISIONS.md was dirty and took yes to mean "already reconciled" — so one
  stray uncommitted line from last week disabled it. It now uses whether *this session*
  wrote the file, which is the question it was actually asking. No git call at all.
- **State could still land inside your project.** `expanduser("~")` does not raise when
  there is no home directory; on Windows it returns the literal string `~`, which was
  then joined onto a relative path and created inside whatever directory the hook was
  launched from. There is now a labelled temp fallback, and `--doctor` fails loudly.
- **Reported line numbers were wrong for files containing a stray carriage return.**
  Both this code and Python's own universal-newline translation folded a lone `\r`
  into a line break, so the linter told you to go and delete the wrong line.
- A failed atomic write left its temp file behind permanently — the state sweep only
  matched session files, so nothing ever collected them.
- Taking the list of edited files reported an edit it had failed to delete, so a locked
  marker file could be handed back on the next call as well. Removing the marker is what
  makes it a "take"; an edit that cannot be removed is now left for the sweep instead.
- The state sweep aged a session by its directory's own mtime, which stops moving once
  the subdirectories exist. A session running continuously for over a week could have
  had its state deleted while still in use.
- An unrelated file named `decisions.md` anywhere in the tree (a vendored dependency,
  say) was treated as the project's own decisions file and exempted from everything.
- **An unclosed code fence silently swallowed every decision after it** — they stopped
  being binding and nothing said so. Only a closed fence is treated as one now, and an
  unclosed fence is a lint error. A fence also has to close on the same character and at
  least the same length, so a ```` ```` ```` block wrapping a ``` ``` ``` example no
  longer ends early and leaks its contents back out as live decisions. `~~~` counts as
  a fence too; it used to be ignored entirely.
- **`--lint` could still stall the editor** on a file with many verbose areas: 10,000
  decisions took 34 seconds against a 5-second hook timeout. Almost all of it was line
  numbers — `text[:pos].count("\n")` re-scans the file from the top for every match,
  which is quadratic in file size. Now 0.4s for the same file.
- An `area_map` entry in config suppressed the rest of the matching entirely, so pinning
  a directory to one area silently hid every other area that governed those files.
- A word used exactly once in the whole file counted as "belonging" to its area by
  arithmetic alone, which is how a vendored test framework matched a narrative decision
  area. One such word is no longer enough on its own.
- Vendored and generated trees — `addons/`, `vendor/`, `third_party/`, `node_modules/`,
  `.godot/`, `build/`, `dist/` — are exempt by default. They are not your design surface.
- The function-call warning printed `` `spawn_boss(` ``, having stripped the closing
  paren that made it a call.

### Fixed — which decisions get shown

Measured against two real projects (119 decisions, 385 source files):

- **The plural of a word no longer stems differently from the singular.** `enemies`
  became `enem` while `enemy` stayed `enemy`, so the two forms stopped matching each
  other — two files about the same subject got different decisions depending on which
  folder name someone happened to type. It also turned `class`, `status`, `process`
  and `address` into words that were not themselves.
- **An area named after a common directory word was invisible.** `build`, `test`,
  `core` and `util` are stripped from paths as generic noise, so a project with a
  BUILD area could never match its own build files. A project's own area names are
  never treated as noise now.
- **The fallback matcher weighs which area a word belongs to**, rather than counting
  raw overlap. Everyday vocabulary used to carry a match — "weapon" plus "element"
  tagged a fifth of one project's files with an area about cursor cosmetics.
- **A decision's `Context:` and `Source:` lines are searched too, not just its
  statement.** That is where an entry names the file or function it governs, and it
  was frequently the only textual link between a rule and the code it binds. One real
  decision, written *because* of a bug in `game_grid.gd`, was never shown when editing
  that file.
- Non-ASCII file names yielded no tokens at all, which guaranteed a miss.
- A config `area_map` glob no longer swallows the rest of the matching: an explicit
  mapping is unioned with the area a file is literally named after, rather than
  replacing it. `*` in those globs also stops crossing directory separators, which is
  what anyone writing `src/*` means.
- `_write_atomic` wrote in text mode, so on Windows every `\n` became `\r\n` — text
  that already carried `\r\n` was written as `\r\r\n`, quietly corrupting the file.
- Exempt paths were matched as a substring of the absolute path, so `tools/` also
  exempted `src/tools/` and any directory whose full path happened to contain those
  characters. They are now project-relative prefixes.
- The default exempt list was mangled before use: a blanket `lstrip("./")` turned
  `.decisions/` into `decisions/` and `.claude/` into `claude/`, so neither was
  actually exempt.
- A query that matched nothing printed **every** decision in the file. On a large file
  one bad keyword cost hundreds of lines of context. It now shows the area list.
- Query results and served decisions are both capped, and say how much they withheld.
- `--lint --write` preserves the file's existing line endings instead of rewriting
  them, so deleting a few lines does not produce a whole-file diff.

### Added

- `"enabled": false` in `.decisions/config.json` turns the plugin off for one project.
- `area_map` in config pins path globs to decision areas, for paths whose names say
  nothing about what they contain: `{"gfx/**": "render"}`.
- `DECISIONS_STATE_DIR` relocates the state root (the test harness uses it so a test
  run cannot touch your real state). The default deliberately ends in `-state`: the
  conventional clone location for this plugin is `~/.claude/decisions-md`, and a state
  root at that path would write project state into the plugin's own working tree.
- `--lint` reports a `DECISIONS.md` that is not valid UTF-8.
- The test harness now covers concurrency (20 hooks at once), files damaged by
  encoding and stray control characters, and the Stop check's cancel signal. None of
  those were exercised before, which is how the state races survived a green run.

### Migrating an existing DECISIONS.md

```
/decisions-md:decisions --lint --write   # strips the plain Status lines
/decisions-md:decisions --lint           # lists what still needs a human
```

Anything left is a judgement call: fold each override-suffix entry back into its
parent, and delete retired entries.

## [1.2.0] - 2026-07-29

### Fixed
- **The plugin did nothing at all on most Windows installs.** Every hook command
  launched `python3`, which is standard on macOS and Linux but absent from Windows
  unless Python came from the Microsoft Store. Each hook failed to start, and the
  failure was silent: the plugin listed, its command autocompleted, its skill loaded,
  and no gate, nudge or Stop check ever ran. Hooks now resolve the interpreter at
  launch — `$(command -v python3 || command -v python || command -v py)` — so one
  manifest works on all three platforms with no editing and no per-platform variants.
  (Registering both a `python3` and a `py -3` variant was rejected: on a machine with
  both, every hook would run twice.)

  Bare invocation of the `.py` files, relying on the shebang, was also measured and
  rejected. Claude Code runs hooks through a POSIX shell on Windows (Git Bash), not
  `cmd.exe`, so the `.py` file association never applies; bash instead reads the
  Python source as a shell script and the resulting nonzero exit *blocks the prompt*.

### Added
- `--doctor`: reports the interpreter actually running, the resolved plugin and
  project roots, whether a `DECISIONS.md` was found, whether the state directory is
  writable, and whether the hooks have run at all. A missing `current-session-id` is
  the direct signal that no hook is launching. Exits non-zero when it finds a problem.
- `tests/verify_hook_launch.py`: runs the command strings out of `hooks/hooks.json`
  through a real shell and asserts each one starts, that SessionStart writes its
  marker, and that the gate still exits 2. The existing harness ran the hook scripts
  through `sys.executable`, so it proved the logic correct while saying nothing about
  whether Claude Code could launch them — which is how a total Windows failure passed
  68/68 checks.

### Changed
- CI runs both harnesses on `ubuntu-latest`, `macos-latest` and `windows-latest`,
  under `bash` on all three. It previously ran on Linux only, which is why this was
  invisible. Running it on Windows immediately exposed a second latent bug: the test
  harness printed a `→` in a section header, which Windows' default cp1252 output
  encoding cannot represent, so the harness died mid-run instead of reporting a
  result. Both harnesses now force UTF-8 on their own output, as the plugin's entry
  points already did.
- The gate's block message names the interpreter actually running the hook instead of
  a hardcoded `python3`, so the command it prints can be pasted and run.

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

First public release. The engine was built inside a game project, where design
decisions kept being lost between sessions, and validated across 23
synthetic-payload checks (gate lock/unlock, binding injection, stop block-once,
per-project config, portability no-op).

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
