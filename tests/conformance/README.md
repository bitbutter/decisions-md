# Conformance fixtures

The fixture project files and the exact results the v3 engine must produce. They were written before any v3 code, from `spec/FORMAT.md` and `docs/ADAPTERS.md` alone, so the port is driven by the contract rather than by the 2.2.0 Python it replaces.

Two reasons this suite exists in this shape:

1. **Text exactness where it matters.** The block that reaches the model at edit time is product behaviour, so `decide`, `orient` and `uncovered` are compared byte for byte. Report prose (`lint`, `migrate`, `query` bodies) is not a contract, so it is pinned structurally: codes, line numbers, entry counts, and substrings.
2. **Line endings are a real failure mode.** A raw CRLF file yields zero entries and zero issues, because `(.+)$` cannot match in front of a carriage return. `crlf-basic` must produce results byte-identical to `lf-basic`, which is the only thing that keeps normalisation honest.

## Layout

```
tests/conformance/README.md
tests/conformance/cases/<case>/case.json
tests/conformance/cases/<case>/project/...        input project tree
tests/conformance/cases/<case>/expected/...       reference files compared byte for byte
```

A case may hold more than one project tree (`project/`, `disabled/`, `empty/`, `outside/`); `case.json` names them per step.

## `case.json`

```json
{
  "name": "lf-basic",
  "description": "what this case is about",
  "notes": "what it pins and why, for whoever fails it later",
  "project": "project",
  "steps": [
    {
      "id": "first-edit-in-input",
      "verb": "decide",
      "input": { "root": "$PROJECT", "file": "$PROJECT/src/input/player.gd", "session": "sess-1" },
      "expect": {
        "action": "inject",
        "code": "served",
        "text": "[DECISIONS] 2 binding decisions govern ...",
        "details": { "areas": ["input"], "ids": ["DEC-INPUT-001", "DEC-INPUT-002"] }
      }
    }
  ]
}
```

* `verb` is one of `decide`, `orient`, `record-edit`, `uncovered`, `query`, `lint`, `migrate`, `doctor`.
* `input` is the verb payload, with path templates substituted. Steps run in file order against one project tree and one session-visible state root, so a sequence can pin serving, claims, pending edits and migration in order.
* `session` is an opaque string, passed through unchanged.

## Runner procedure

A runner (Phase 1 ships the TypeScript one) does exactly this:

1. Copy the whole case directory into a fresh temporary directory **whose own name contains a space**. Project trees, expected files and absolute paths then all carry a space at once, which is one of the cases.
2. Substitute path templates: `$CASE` → the copied case directory, `$PROJECT` → `$CASE/project`, `$STATE` → a fresh empty temporary directory that is exported as `DECISIONS_STATE_DIR` for the whole case.
3. Snapshot the case copy before each step. After it, every file the step changed must be named in `expect.files`; anything else changing fails the step. This is how "the engine writes no state into the consuming project" is asserted on every case, not just once.
4. Call the verb twice — once in process, once through `bin/decisions.ts` — and compare both against the fixture. Each run gets its own copy and its own state root, because the first run mutates claims and pending edits. Through the envelope, every step must exit 0, including steps that answer `block` or `fail`: the CLI never exits 2, and a non-zero exit means it produced no envelope at all.
5. Compare the two envelope sequences field for field, after replacing each run's temporary paths (and the state directory's project hash) with their tokens. Any difference is a failure: the same input must produce the same action, code, text and details whichever way the adapter reaches the engine.

`node tests/conformance/run.ts` runs both passes, which takes about 20 seconds. `--in-process` runs the fixture checks only, for a fast loop while editing the engine.

Comparison rules:

| Field | Rule |
|---|---|
| `expect.action`, `expect.code` | exact |
| `expect.text` | exact string equality; an empty string means "nothing to say". No trailing newline in either side. |
| `expect.textIncludes` | every listed substring appears in `text` |
| `expect.textExcludes` | no listed substring appears in `text` |
| `expect.details` | deep partial: only keys present in the fixture are compared; objects recursively; arrays must match in length and compare element-wise under the same rule. `message` prose is never pinned. |
| `expect.files` | map of case-relative path → reference file, compared byte for byte |
| `expect.filesAbsent` | paths that must not exist after the step |

A step with no `text` and no `textIncludes` asserts only the action, the code and whatever `details` says. That is deliberate: a code plus a line number is enough to drive an implementation, and pinning prose would make every wording improvement a fixture change.

## Cases

| Case | Pins |
|---|---|
| `lf-basic` | the reference case: exact inject and orientation text, served-once per area per session, query claims the areas it shows, silent for a path no area touches, clean lint, doctor |
| `crlf-basic` | a CRLF file produces byte-identical results to `lf-basic`; the load-bearing normalisation case |
| `bom-basic` | a leading BOM is stripped before parsing; byte-identical results again |
| `path-with-space` | spaces and capitals in directory and file names, in the text the model sees and in every path comparison |
| `near-miss-ids` | `DEC-ENEMY-AI-001` parses; twelve near misses are reported as errors, never skipped; area labels span segments (`enemy-ai`) |
| `wrapped-and-context` | wrapped statements join with single spaces; `Context:` and `Source:` render only in query; a file with no trailing newline parses |
| `superseded-archive` | three superseded records archived before being stripped, refusal-free; archived records stop binding; `now` makes the archive header reproducible |
| `archive-refused` | missing and absent successors refuse the whole run and write nothing |
| `legacy-status` | `--write` removes only trivial `Status:` lines and keeps the one that swallowed a statement; second run is a byte-identical no-op |
| `crlf-migrate` | migration preserves each surviving line's CRLF terminator |
| `fences-prose` | closed fences are never entries (and still lint for `Status:`); an unclosed fence is an error and blanks nothing; prose between entries is ignored |
| `scope-and-config` | config replaces defaults, `area_map`, exempt prefixes, out-of-project paths, a disabled project, a project with no `DECISIONS.md`, the root file winning discovery over `docs/`, and the precedence order that picks each code |
| `uncovered-backstop` | the single question about uncovered work, and every case where it stays quiet (`no_pending_edits`, `all_covered`, `decisions_touched`, `already_asked`) |
| `lint-errors` | duplicate ID, empty statement (not served to the model), and a codepage file that still parses while reporting `not_utf8` |
| `swallowed-lines` | four non-entry lines that continue the statement above them: an indented entry and a space-instead-of-hyphen ID (both `malformed_id`), plus a heading under a statement and an indented `Status:` line (both still silent). Two entries written back to back still parse as two. |

## Deliberately not covered

* **Fallback match scoring.** Fixtures exercise the confident tiers (an area label in the path, `area_map`) only. The ownership and lift scoring is pinned by `tests/core` unit tests in Phase 1, because a fixture whose result depends on a tuned heuristic is a fixture that fails for the wrong reason.
* **`doctor` details.** Environment-dependent: version, writable state directory, resolved state root. Only its action and code are pinned.
* **Claim races.** Two writers claiming one area at the same moment is a state-API concern, tested directly in `tests/core`.
* **The pi adapter itself.** These fixtures are harness-free. The adapter's own tests live under `harnesses/pi/`, and the live transcript check under `tests/live`.
