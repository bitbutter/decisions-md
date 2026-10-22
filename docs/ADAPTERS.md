# Adapters

How a harness gets a project's binding decisions in front of its agent, and what each side is allowed to know.

## 1. The shape

```
core/            plain functions: parse, match, query, lint, migrate, state
bin/decisions    thin CLI over core, for adapters that need a subprocess
harnesses/pi/    the only adapter today; imports core in process
spec/FORMAT.md   the file format
```

Three rules hold this together:

1. **`core/` holds no harness knowledge.** No harness name, no harness path, no harness event name, no harness exit code, no harness vocabulary ("hook", "tool_call", "PreToolUse"). Core knows about files, decisions, and actions.
2. **An adapter holds no decision knowledge.** It does not parse a decision, match an area, lint a file, or keep decision state. It resolves a target path, supplies a session identity, calls one core function, and maps the returned action onto its own mechanism.
3. **The envelope is a wire format, not the engine.** Adapters that can import core call functions. Only an adapter that must spawn a process speaks the JSON envelope, and even then the envelope is a translation of the same four actions.

A new harness should cost one adapter file and nothing under `core/`. The check for that is the synthetic fifth adapter: built from this document alone, against fixtures, with no reference to pi.

## 2. Actions

Core answers every request with exactly one action. This is the whole coupling between engine and harness.

| Action | Meaning | Adapter obligation |
|---|---|---|
| `none` | Nothing needs to reach the model. | Do nothing. Log the code if you like. |
| `inject` | This text belongs in front of the model, and the work may proceed. | Deliver `text` by your own mechanism. |
| `block` | Work must not continue until the model has read `text`. | Refuse, delay or annotate the action under way; the retry proceeds. |
| `fail` | The engine could not complete the request — malformed input, unreadable file, internal error. | Surface `text` as a diagnostic if you have somewhere to put it. Never treat it as a decision, and never block on it. |

`fail` is not a strong `block`. It means "no answer", and an adapter that blocks on it converts an engine bug into a stuck editor.

`block` does not mean "revert". Where an adapter can gate a tool call it gates it; where the action has already happened (a post-write lint) it attaches the text to the result. The engine cannot tell those cases apart and does not try.

## 3. The envelope

A subprocess adapter writes one JSON object to stdin and reads one JSON object from stdout.

```json
{
  "action": "inject",
  "text": "[DECISIONS] 1 binding decision governs src/input/player.gd (area: input).\n...",
  "code": "served",
  "details": { "decisionsFile": "DECISIONS.md", "areas": ["input"], "ids": ["DEC-INPUT-001"], "withheld": 0 }
}
```

* Every envelope has exactly these four keys. `action`, `code` and `text` are strings; `details` is an object.
* `text` is empty exactly when there is nothing to say, and never ends with a newline.
* `code` is a stable, lowercase, `snake_case` reason drawn from the vocabulary in [§5](#5-verbs). Adapters may branch on it. Nothing else in the envelope is stable enough to branch on.
* `details` is verb-specific ([§5](#5-verbs)). An adapter may read it; the model-facing text never depends on it.
* **Exit status is 0 for any handled request**, including `block` and `fail`. The CLI never exits 2. A non-zero exit means the CLI could not emit an envelope at all, and it carries no information about decisions.
* Input is JSON on stdin: `{"verb": "...", ...fields}`. Unknown fields are ignored; a missing required field is `invalid_input`.

Adapters that import core skip all of this and call the function directly. One behaviour is shared either way: the action and the text are the same, so an in-process adapter and a subprocess adapter produce the same result for the same input.

## 4. Exported core functions

Signatures are TypeScript. Types are structural; nothing here is a class and nothing throws for a condition the caller can handle.

### 4.1 `parse`

| Function | Contract |
|---|---|
| `normalizeText(raw: string): string` | Strips a leading BOM, CRLF → LF, and a whole-file CR-only file → LF. Leaves a lone CR in an LF file alone. Every reader goes through this. |
| `decodeFile(bytes: Uint8Array): { text: string; validUtf8: boolean }` | UTF-8 decode, lenient on failure. Never throws for encoding. |
| `readDecisionsFile(path: string): { text: string; validUtf8: boolean } \| null` | Read + decode + normalise. The only sanctioned way to get decision text. |
| `parseDecisions(text: string): Entry[]` | Entries in file order, per `spec/FORMAT.md` §4. No linting, no state. |
| `parseId(id: string): { areas: string[]; number: number } \| null` | Grammar check; `null` when it fails §5.1. |
| `areaLabel(id: string): string \| null` | `DEC-ENEMY-AI-001` → `enemy-ai`. |
| `findDecisionsFile(root: string): string \| null` | Discovery, `spec/FORMAT.md` §2. |

`Entry` carries `id`, `area` (the label), `statement` (joined), `fields` (ordered key/value pairs), `line` (1-based) and `lineCount` (non-blank lines in the block).

### 4.2 `match`

| Function | Contract |
|---|---|
| `matchAreas(entries, relPath, areaMap): string[]` | Area labels plausibly governing a project-relative, forward-slashed path, best first. |
| `entriesForAreas(entries, areas, limit): { shown: Entry[]; withheld: number }` | File order, capped. |

Matching is a heuristic and is documented as one, because surfacing the wrong area costs tokens while failing to surface the right one defeats the product. Three tiers, all of them computed and unioned:

1. **`area_map` glob.** `{ "src/systems/**": "economy" }`. `*` does not cross `/`; `**` does.
2. **Area name in the path.** A path token equals the area label or one of its segments (`enemy-ai` matches a path containing `enemy`), or their stems. Confident, and never suppressed by tier 3.
3. **Word overlap, weighted by ownership.** Tokens come from path segments minus generic directory names (`src`, `lib`, `test`, `game`, `util`, …) and from each entry's statement plus field values. A word scores 1.0 for an area when most of its occurrences sit in that area (≥ 0.5) or it is concentrated there (lift ≥ 2.0) and it occurs at least twice in the file; 0.6 when it occurs exactly once; 0.4 otherwise. An area needs a total of 1.0 to be returned.

Path and decision tokens are lowercased, split on `_`, `-`, camelCase and non-word characters, singularised by a small rule set (`ies → y`, `ses/sxz + es`, trailing `s` except `ss/us/is`, trailing `ing/ed/ly`), and words shorter than three characters are dropped unless non-ASCII. The stemming rules are spelled out rather than folded into one trailing-`s` strip, because a blanket strip made `enemies` and `enemy` different words and turned `class`, `status` and `process` into not-themselves.

### 4.3 `query`

| Function | Contract |
|---|---|
| `queryDecisions(entries, opts): { results: Entry[]; total: number }` | Filter by area label and/or keywords, score by token overlap, exact ID match scores 10. Results best first, then by ID. |
| `renderEntry(entry, opts): string` | `ID: statement`, then each field on its own line indented two spaces. `opts.withFields` defaults to true. |
| `areaCounts(entries): { area: string; count: number }[]` | Sorted by label. |
| `overview(entries): string` | `4 decisions (economy:2, input:2)`, or `""` when empty. |

### 4.4 `lint`

| Function | Contract |
|---|---|
| `lintFile(file: string): { errors: Issue[]; warnings: Issue[]; entries: number }` | Per `spec/FORMAT.md` §6. |
| `Issue` | `{ code, message, line? }`. Message prose is not part of the contract; code and line are. Issues are ordered by line, with file-level issues (no line, such as `not_utf8`) first, then by code. |

### 4.5 `migrate`

| Function | Contract |
|---|---|
| `checkMigration(file): MigrationReport` | What a run would do: trivial status lines, status lines needing a human, superseded records with successors, current error count. |
| `writeMigration(file): { removed: number; kept: number; changed: boolean }` | Removes trivial `Status:` lines only. Byte-preserving, idempotent, no BOM in the output. |
| `archiveSuperseded(file, archiveFile, nowIso): { archived: Entry[]; refused?: string }` | Archive first, strip second; refuses the whole run on a missing successor. |

### 4.6 `state`

Core owns decision state. Adapters pass an opaque session identity and never keep their own.

| Function | Contract |
|---|---|
| `resolveStateDir(root): string` | `$DECISIONS_STATE_DIR` if set, else the state root below. Never inside the project. |
| `projectKey(root): string` | Readable slug plus a short hash of the normalised absolute root. |
| `claimServed(root, session, area): boolean` | Atomic create-exclusive claim. `true` for exactly one caller, once. |
| `areaServed(root, session, area): boolean` | Has this area been shown this session. |
| `claimBackstop(root, session): boolean` | Atomic claim for the single unmatched-work question per session. |
| `recordEdit(root, session, relPath): boolean` | Record an edited path, one file per path so concurrent writers cannot lose each other's writes. |
| `takeEdits(root, session): string[]` | Return recorded paths and forget them. |
| `markDecisionsTouched(root, session)` / `decisionsTouched(root, session)` | Whether this session already wrote `DECISIONS.md`. |
| `resetSession(root, session)` | Forget one session, so a new or resumed one starts clean. |
| `pruneState(root)` | Drop session directories older than 7 days and orphaned `.tmp` files older than 1 hour. |

Claims are a discipline, not a lock: **claim before emitting text, and stay silent if the claim fails.** A failed claim means either another caller won or the state directory is unwritable. Blocking on either produces a block that repeats forever, which is worse than a missed serve.

## 5. Verbs

`bin/decisions` exposes these verbs. Each is a thin wrapper: read stdin, call core, emit the envelope, exit 0.

Any verb may answer `engine_error` (`fail`) when core throws; the tables below list only the reasons that carry meaning for that verb.

| Verb | Purpose |
|---|---|
| `decide` | Which decisions govern this file, and should it be shown now. |
| `orient` | The one-time orientation block and the file's overview. |
| `record-edit` | Post-write bookkeeping for a path. |
| `uncovered` | Did this session edit territory no decision covers. |
| `query` | Read the file: areas, one area in full, or a keyword search. |
| `lint` | Format check of one file. |
| `migrate` | Check, write, or archive. |
| `doctor` | Is this install working at all. |

`query`, `lint`, `migrate` and `doctor` are deliberate human/agent invocations: `"enabled": false` in project config suppresses automatic delivery, not them.

### 5.1 `decide`

Input: `{ root, file, session? }`.

Checks run in this order and the first hit wins, so a code tells you why nothing was shown:

| Code | Action | Condition |
|---|---|---|
| `invalid_input` | `fail` | bad payload, missing `root` or `file` |
| `no_decisions_file` | `none` | discovery found nothing |
| `disabled_by_config` | `none` | `"enabled": false` |
| `outside_project` | `none` | `file` is not inside `root` |
| `untracked_extension` | `none` | extension is not tracked |
| `exempt_path` | `none` | the file is `DECISIONS.md` itself or under an exempt prefix |
| `no_session` | `none` | no session identity, so serving could not be remembered |
| `no_entries` | `none` | the file parses to zero entries |
| `no_matching_area` | `none` | nothing on file bears on this path |
| `already_served` | `none` | every matched area was already served this session |
| `served` | `inject` | at least one area is fresh; the text is the decisions themselves |

`details`: `{ decisionsFile, areas, ids, withheld }`. `ids` are the entries actually rendered; `withheld` counts entries in the served areas beyond the cap (15).

Every entry in a served area is in the text; the engine does not summarise, and a file that is not in format still serves whatever parses. Silence is the losing move, not a possibly-stale rule. The one entry that is never served is one whose statement is empty: there is no rule in it, `lint` already reports it, and a bare ID in a binding block reads as a rule that says nothing. Those entries are dropped before area matching, so an area containing only them cannot match and no claim is made.

Exact text, `{N}` entries, one area:

```
[DECISIONS] 1 binding decision governs src/input/player.gd (area: input).
Read them, then re-run your edit. Nothing else is required to proceed.

DEC-INPUT-001: Jumping is bound to the A button.

If one of these contradicts the change you are about to make, stop and offer the user: abandon / adapt / override. Otherwise just carry on.
```

Plural forms are `N binding decisions govern`, `(areas: input, economy)` when more than one area is served, and a withheld line of its own when `withheld > 0`:

```
(3 more in this area are not shown.)
```

### 5.2 `orient`

Input: `{ root }`. Codes: `oriented` (`inject`), `no_decisions_file` / `disabled_by_config` / `no_entries` (`none`).

Exact text:

```
[DECISIONS] This project has binding design decisions. Code and tests must follow them.
  Relevant decisions are shown to you automatically before your first edit in each area.
  If one contradicts what is being asked, stop and offer: abandon / adapt / override.
  On file: 4 decisions (economy:2, input:2)
```

The last line is the parsed overview. When the file parses to zero entries, `no_entries` suppresses the whole block (action `none`, empty text): an orientation that says "binding decisions" and lists none is noise.

`orient` keeps no state and may be called as often as an adapter likes. Core's text names no command; an adapter may append one line naming its own lookup command, and that line is the adapter's, not the engine's.

### 5.3 `record-edit`

Input: `{ root, file, session? }`. Codes: `recorded`, `recorded_decisions_file`, `untracked_extension`, `exempt_path`, `outside_project`, `no_decisions_file`, `disabled_by_config`, `no_session`, `invalid_input`, `engine_error`. Action is always `none`.

Called after a write succeeds. Recording before the write would count edits that failed. When `file` is the project's own `DECISIONS.md`, this marks the session as having touched it and records nothing else — that flag is what stops the backstop asking about work the agent already wrote down.

### 5.4 `uncovered`

Input: `{ root, session }`. The backstop for decisions made and never written down.

| Code | Action | Condition |
|---|---|---|
| `no_decisions_file`, `disabled_by_config`, `no_session`, `invalid_input` | `none`/`fail` | as above |
| `decisions_touched` | `none` | this session already wrote `DECISIONS.md` |
| `no_pending_edits` | `none` | nothing was edited since the last call |
| `all_covered` | `none` | every edited path matched an area |
| `already_asked` | `none` | the one question this session was already asked |
| `uncovered_edits` | `inject` | at least one edited path matched nothing |

Text (paths joined by `, `, first five then ` (+N more)`):

```
This session edited files in territory no decision currently covers: src/audio/mixer.gd.

Default answer: no entry is needed. Pure implementation, refactors, bug fixes and anything a user or designer would never notice do not belong in DECISIONS.md.

Only if the work settled a USER- OR DESIGNER-FACING rule -- what a control does, a balance value, a UX rule, a win condition -- propose ONE entry: the binding statement in a sentence or two, plus a brief why. No file paths, no function names, no account of how a bug was found. Before proposing it, check existing decisions and name the one you checked against.

If no entry is needed, reply with exactly this line and nothing else:
No DECISIONS.md change needed.
```

It asks once per session, and only about uncovered territory. A session that already wrote `DECISIONS.md`, or that edited only areas that have decisions, is not asked. Asking anyway is how a decisions file fills with entries nobody needed.

`details`: `{ paths }` — every edited path that matched no area, in the order the edits were recorded.

### 5.5 `query`

Input: `{ root, area?, terms?, session? }`. Codes: `found` (`none`), `no_match` (`none`), `areas_listed` (`none`), `unknown_area` (`none`), `no_decisions_file` (`none`), `invalid_input` (`fail`). Action is always `none`: reading is not a gate.

`details`: `{ areas, ids, total, shown }`. Results are capped at 12; the text says how many were not shown.

`query` claims the areas it shows, so a later edit in one of them is not re-served. That is the point of asking: the agent has the text.

### 5.6 `lint`

Input: `{ root, file? }`. Default target is the discovered `DECISIONS.md`.

| Code | Action | Condition |
|---|---|---|
| `clean` | `none` | no errors |
| `format_errors` | `block` | at least one error |
| `no_decisions_file` | `none` | nothing to lint |
| `unreadable` | `fail` | the file vanished or cannot be read |

`details`: `{ entries, errors: Issue[], warnings: Issue[], counts: { errors, warnings } }`. Warnings never change the action, and nothing is auto-edited.

### 5.7 `migrate`

Input: `{ root, file?, mode: "check" | "write" | "archive-superseded", now? }`. `now` is an ISO-8601 timestamp used for the archive header, so runs are reproducible; it defaults to the wall clock.

| Code | Action | Condition |
|---|---|---|
| `clean` | `none` | nothing to do |
| `needs_migration` | `block` | something remains: trivial status lines, superseded records, or format errors |
| `migrated` | `none` | `write` removed lines |
| `nothing_to_migrate` | `none` | `write` removed nothing; file byte-identical |
| `archived` | `none` | `archive-superseded` moved records |
| `archive_refused_no_successor` | `block` | a superseded record names no successor |
| `archive_refused_missing_successor` | `block` | the named successor is not an entry |
| `no_decisions_file`, `unreadable` | `none`/`fail` | as above |

A refusal writes nothing: no archive file, no edit.

`details`, by mode — `check`: `{ trivialStatus, nontrivialStatus, superseded: [{ line, id, successor }], formatErrors }`, where `superseded[].line` is the record's ID line and `nontrivialStatus` excludes records that archiving handles; `write`: `{ removed, kept }`; `archive-superseded`: `{ archived, archiveFile }`.

### 5.8 `doctor`

Input: `{ root }`. Codes: `ok` (`none`), `problems` (`none`). `details.checks` is `[{ name, status: ok|warn|fail, detail }]`: engine version, project root, decisions file, state directory writable, state root resolved (not a temp fallback), session identity seen. It reports rather than repairs, and it is the only place that says "installed and doing nothing" out loud.

## 6. Project inputs

Read from `<root>/.decisions/config.json`. Missing or malformed is `{}`, never an error: a project that cannot configure the engine is a project that gets defaults.

| Key | Type | Default | Effect |
|---|---|---|---|
| `enabled` | boolean | `true` | `false` suppresses automatic delivery only |
| `tracked_extensions` | string[] | `.gd .tscn .tres .gdshader .gdextension .py .js .jsx .mjs .cjs .ts .tsx .rb .go .rs .lua .sh .ps1` | extensions that trigger `decide`. A configured list **replaces** the defaults; `[]` means nothing is tracked; unusable entries fall back to defaults rather than silently disabling |
| `exempt_paths` | string[] | `DECISIONS.md .decisions/ tools/ addons/ vendor/ third_party/ node_modules/ .godot/ build/ dist/` | project-relative prefixes that never trigger a serve |
| `area_map` | object | `{}` | `{ "glob": "area-label" }`, highest-confidence match tier |

Comparison paths are project-relative and forward-slashed. Case folding follows the filesystem: case-insensitive on Windows, exact elsewhere. `exempt_paths` is a prefix match on the project-relative path, never a substring match on an absolute one, so `tools/` exempts `tools/build.py` and not `src/tools/thing.py`.

2.2.0 listed `.claude/` among the default exempt paths. A harness path cannot live inside core, so it is gone from the defaults; a project that vendors a harness's directory tree can list it itself.

## 7. State location

```
<state-root>/<project-key>/s-<session>/served/<area-label>
<state-root>/<project-key>/s-<session>/pending/<hash-of-relpath>
<state-root>/<project-key>/s-<session>/decisions-touched
<state-root>/<project-key>/s-<session>/backstop-asked
```

* **State root**: `$DECISIONS_STATE_DIR`, else `~/.decisions-md/state/`. Not under any harness's directory: the location is a product decision, and a harness-named path inside the engine is exactly the leak this architecture forbids.
* **Project key**: a readable slug of the project directory name (40 characters, `[A-Za-z0-9._-]`), then a hyphen and the first ten hex characters of the SHA-1 of the normalised absolute root. Readable enough to delete by hand, unique enough not to collide.
* **Session directory**: `s-` plus the sanitised session identity, truncated. Core never interprets the identity; the adapter supplies it, and may supply a new one per session.
* **Never inside the consuming project.** Not a temp file, not a cache, not a lock. The only things core reads from a project are `DECISIONS.md` and `.decisions/config.json`; the only things it writes are the files `migrate` was told to rewrite. Fixtures assert the project tree is otherwise unchanged.
* **Nothing here is precious.** Deleting the state root costs one re-served decision list. The root is a sibling of the conventional clone path (`~/.claude/decisions-md`), never a parent of it, so nothing writes into this repository's own working tree.
* **Fallback**: if the OS gives no home directory, the root falls back to a temp path and `doctor` reports it as a failure. Writing state into whatever directory happened to be current — i.e. into a project — is the one outcome the fallback exists to prevent.

## 8. pi mapping

pi is the only verified harness. The adapter is an extension, imports core in process, and maps five events.

| pi event | Core call | Adapter behaviour |
|---|---|---|
| `session_start` | `orient({ root })` | `inject` → `pi.sendMessage({ customType: "decisions-md", content: text, display: false }, { deliverAs: "nextTurn" })`. Queued for the next prompt, so orientation costs no turn and survives a resumed session. Then `state.pruneState(root)`. |
| `tool_call` where `toolName` is `edit` or `write` | `decide({ root, file: event.input.path, session })` | `inject` → `return { block: true, reason: text }`. pi feeds `reason` to the model and the agent retries the edit; the area is already claimed, so the retry passes. `none` → return nothing. `fail` → return nothing and `ctx.ui.notify` once per distinct code. |
| `tool_result` for `edit`/`write` | `record-edit(...)`; then `lint(...)` if the path is the project's `DECISIONS.md` | `block` from `lint` → append `text` to the tool result content, because the write already happened and cannot be reverted. |
| `turn_end` | `uncovered({ root, session })` | `inject` → `pi.sendMessage({…}, { deliverAs: "followUp" })`, so the question lands after the turn's remaining tool calls instead of mid-turn. |
| `session_compact` | `orient({ root })` | Same delivery as `session_start`: compaction is the one place the orientation can be lost. |

Session identity: a stable string per pi session, derived from `ctx.sessionManager.getSessionFile()` (or an in-memory id for an ephemeral session). It is opaque to core and may be any length; core sanitises it.

Path handling: `event.input.path` for both tools. Resolve it against the session cwd, then hand core the absolute path plus the project root; core computes the project-relative path. The adapter does not compare paths, test extensions or read config — those answers come back as codes.

Commands: `/decisions` maps to `query`, `/decisions-lint` to `lint`, `/decisions-migrate` to `migrate`, printing `text` through `ctx.ui.notify` or a plain message. These command names are the adapter's, and no core text may mention them.

## 9. Deliberately absent

Deferred by the v3 plan until a second adapter is real, and not to be built speculatively:

* `_hookpayload` profiles — recorded payload fixtures per harness. Conformance fixtures plus a live pi session cover the single adapter today.
* `session-init --capabilities` — capability negotiation. One adapter needs no negotiation; the action vocabulary already expresses everything the engine can require.
* Generated `dist/` packages. The pi package ships source.
* Claude Code, Codex and OpenCode adapters. Those harnesses are frozen at the 2.2.0 Python plugin in this repository's root, which stays untouched and working.
* Exit code 2. That is a Claude/Codex convention, so it belongs to those adapters. The CLI never uses it.

## 10. Adding a harness

The checklist a fifth adapter has to satisfy, and the reason each item exists:

1. **Resolve a target path** for each action that writes code, and say what kind of write it is. Nothing else about the harness reaches core.
2. **Supply a session identity**, stable within a session and different across sessions.
3. **Deliver `inject` and `block`** by the harness's own mechanism, honouring the difference in [§2](#2-actions).
4. **Never parse, match, lint or keep decision state.** If the adapter is computing what a decision means, the answer belongs in core.
5. **Pass conformance.** Run `tests/conformance/` through the subprocess envelope, unmodified. If a case needs a change to pass, the adapter is wrong or the contract is; either way it is a finding, not a local patch.

If item 4 or 5 forces a change under `core/`, the architecture has failed its own test, and the plan's rule applies: fix the contract, not the adapter.
