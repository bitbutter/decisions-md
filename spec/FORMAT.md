# The DECISIONS.md format

Normative for v3. `core/parse`, `core/lint` and `core/migrate` must satisfy every rule below, and the fixtures in `tests/conformance/` pin them.

Where this document and the 2.2.0 Python implementation disagree, this document wins for v3. Deliberate differences are listed in [Changes from 2.2.0](#changes-from-220). Behaviour that 2.2.0 has and v3 keeps, even where it looks like a bug, is listed in [Behaviour carried over from 2.2.0](#behaviour-carried-over-from-220). Nothing else may differ.

## 1. What the file is

`DECISIONS.md` holds the project's binding decisions as it stands **now**. One entry, one rule. Git holds what used to be true: there is no status vocabulary, no superseded entry left in the file, no revision log inside an entry, and no override-suffix ID.

Two invariants govern everything else:

1. **Every entry that parses is binding.** There is no "inactive" state to parse.
2. **An identifier that looks like a decision but does not parse is a format error.** It is never skipped in silence. This is the failure the format exists to prevent: an unparsed ID means a rule nobody is being shown, with no diagnostic anywhere.

## 2. Discovery

The file is found by looking under the project root, in this order, and taking the **first** that exists:

1. `<root>/DECISIONS.md`
2. `<root>/docs/DECISIONS.md`
3. `<root>/support/DECISIONS.md`
4. `<root>/design/DECISIONS.md`
5. `<root>/decisions/DECISIONS.md`

Exactly one file is read. If both the root and `docs/` hold one, the root file wins and the other is not read by anything — it is neither parsed nor linted, and no warning is emitted about it.

Parent directories are not searched for the file itself; the walk-up that finds the *project root* is a separate concern (`docs/ADAPTERS.md`).

## 3. Encoding and line endings

Reading a decisions file is a single, shared step. Every path that reads one — parse, lint, query, migrate, the engine's `decide` — goes through it, so they cannot disagree about what the bytes say.

* **Encoding is UTF-8.** Invalid UTF-8 is decoded leniently with U+FFFD replacement characters and reported as an error (`not_utf8`). Reading never throws for encoding reasons, and the rest of the file still parses. A UTF-16 file is not supported and surfaces as `not_utf8`.
* **A leading byte-order mark is stripped** before anything else. A `U+FEFF` that survives at the start of line 1 stops that line being an ID line, so stripping is not cosmetic.
* **CRLF becomes LF.** This is not cosmetic either: matching a line terminator with `(.+)$` fails in front of a carriage return, so an unnormalised CRLF file yields zero entries and zero issues — a file full of binding rules that silently binds nothing.
* **A classic-Mac file (CR only, no LF anywhere) becomes LF.** Same reason.
* **A lone CR in an otherwise LF-terminated file stays a control character**, not a line break. Editors and grep treat it that way, and folding it into a newline would shift every reported line number after it.
* **Reported line numbers are 1-based over the normalised text.** A BOM strip does not shift them; a CRLF conversion does not shift them.

Everything else in this document is stated in terms of the normalised text.

## 4. Entry anatomy

An entry starts at an ID line and runs until the next ID line or end of file. Within that span, a blank line terminates the statement *and* any open field.

```
DEC-SAVE-001: A save writes the whole run state in one transaction.
Context: A half-written save is the one failure players will not forgive.

DEC-SAVE-002: A save is written once per level transition and never on a timer.
```

### 4.1 The ID line

An ID line matches, anchored at column 0:

```
^DEC-<id>\s*:\s*<statement>$
```

* The `DEC-` prefix starts **at column 0**. Leading whitespace means the line is not an entry (see [§8](#behaviour-carried-over-from-220)).
* Whitespace around the colon is not significant. `DEC-INPUT-001:rule`, `DEC-INPUT-001: rule` and `DEC-INPUT-001 : rule` are the same entry.
* The statement may be empty on the ID line only if a following line continues it; an entry whose statement is empty in the end is an error (`missing_statement`).

### 4.2 The statement

The statement is the ID line's remainder plus every following line up to the first blank line, field line, or next ID line.

* Each line is trimmed of leading and trailing whitespace.
* The parts are joined with a **single space**. Wrapping is a source-layout choice; the statement is a single line of text once parsed, and that joined form is what gets rendered and matched.
* Joining is lossless apart from the line break itself: no hyphenation, no ellipsis, no reflow.
* A statement may wrap over any number of lines. There is no line limit in the format (the linter warns about length; see [§6](#6-lint-errors-and-warnings)).

### 4.3 Fields

A field line matches, anchored at column 0:

```
^([A-Z][A-Za-z]*)\s*:\s*(.*)$
```

One capital letter, then letters. So `Context:`, `Source:`, `See:` and `OpenQuestion:` are fields. `DEC-INPUT-001:` is not (hyphens and digits), and `context:` is not (lowercase) — it continues the statement instead.

* A field line **ends the statement**.
* `Context:` is the conventional field: the reasoning behind the rule, kept short. It is not special in the grammar; it is one field among possible fields.
* A field's value continues onto following lines until a blank line, the next field line or the next ID line. Continuations are trimmed and appended with a single space, exactly as statement lines are.
* A blank line closes the open field. Without that rule, a heading or a note between entries was appended to the last field's value and printed as part of the entry.
* Fields are rendered only by `query`. The text shown at edit time is the ID and statement, with no fields (see `docs/ADAPTERS.md`).

### 4.4 The blank line between entries

The canonical layout puts one blank line between entries. The blank line is what terminates the statement, so:

* a blank line is **required** after a statement or field block before any prose;
* two entries written back to back, with no blank line, still parse as two entries — the next ID line terminates the earlier entry — but this is not canonical layout and gains nothing;
* prose written directly under a statement, with no blank line in between, is part of that statement.

### 4.5 Prose, headings and anything that is not an entry

After the blank line that ends an entry, every line until the next ID line is **prose**: markdown headings, `## Combat`, notes, dividers, paragraphs. Prose belongs to the document, not to the entry above it, and the engine ignores it completely — it is never part of a statement, never part of a field, and never matched on.

A line that matches neither an ID line, a field line nor a blank line, and appears **before** the terminating blank line, joins the statement. That is what makes wrapping work, and it is also a trap: a heading written directly under a statement becomes part of the rule ([§8](#behaviour-carried-over-from-220)).

### 4.6 Fenced code blocks

Documenting the format inside `DECISIONS.md` is expected, and an example must never become a binding rule.

* A fence opens on a line whose first non-whitespace run is three or more backticks, or three or more tildes.
* It closes on the first later line using the **same character** with a marker **at least as long** as the opening one. A four-backtick block wrapping a three-backtick example therefore does not end early.
* The lines of a **closed** fence, markers included, are treated as blank: they are never entry text, never field text, and never prose that joins a statement. Line numbering is unaffected.
* An **unclosed** fence is an error (`unclosed_fence`), and **nothing is blanked for it** — the file parses as though that marker were absent. Blanking would silently drop every following decision, which is the worst failure this format has; reporting it and keeping the decisions is the safer pair.
* Legacy-vocabulary scans ([§6](#6-lint-errors-and-warnings)) run over the normalised text **without** fence blanking. A `Status:` line inside a fenced example is still an error. See [§8](#behaviour-carried-over-from-220).

## 5. The ID grammar

### 5.1 Grammar

```
id     := "DEC-" area ( "-" area )* "-" number
area   := [A-Z]{2,}
number := [0-9]{3}
```

* Areas are **uppercase ASCII letters only**, at least two per segment.
* One or more area segments, separated by hyphens. `DEC-INPUT-001` and `DEC-ENEMY-AI-001` are both valid.
* The number is **exactly three digits** and is the **last** segment.
* A trailing letter is not part of the grammar. The old override-suffix convention (`DEC-INPUT-007d`) is retired; a leftover is reported with its own error code.

### 5.2 Area label

The area label is the ID's area segments lowercased and joined with hyphens:

| ID | Area label |
|---|---|
| `DEC-INPUT-001` | `input` |
| `DEC-ENEMY-AI-001` | `enemy-ai` |
| `DEC-SAVE-TRANSACTION-002` | `save-transaction` |

The label is what `query --area` takes, what `area_map` values must use, and what grouping, counts and rendering show. It is derived from the ID only: markdown headings carry no meaning, and an entry's area is not affected by where in the document it sits.

### 5.3 Near-miss identifiers that must fail

Each of these is a format error, not an entry:

| Form | Why it fails |
|---|---|
| `DEC-INPUT-01` | number is two digits |
| `DEC-INPUT-0001` | number is four digits |
| `DEC-C-001` | area segment is one letter |
| `DEC-INPUT-007d` | retired override suffix (own error code) |
| `DEC-combat-001` | area is lowercase |
| `Dec-INPUT-002` | prefix is not uppercase |
| `DEC-ENEMY_AI-001` | underscore in an area |
| `DEC-IMPACT_DEMO-003` | underscore in an area (a real leftover in a live project) |
| `DEC-INPUT 003` | space where the hyphen belongs |
| `DEC-INPUT-004.1` | dot inside the number |
| `DEC--005` | empty area segment |
| `DEC-COMBAT-10-01` | numeric segments; the number must be the last segment |
| `DEC-FOO-001-002` | the number is not the last segment |
| `DEC-` / `DEC-INPUT-` | no number |
| `DEC-ÅREA-001` | non-ASCII in an area |

The **detection** rule, which is wider than the grammar on purpose. A line is reported as `malformed_id` when its leading identifier-shaped text is not a valid ID, in either of these shapes:

```
^[ \t]*DEC[-_][^\s:]*\s*:                  # the leading token, at any indentation
^[ \t]*DEC[-_][^\s:]*[ \t]+[^\s:]+\s*:     # one extra token: "DEC-INPUT 003: ..."
```

case-insensitively, and either

* the identifier before the colon is neither a valid v3 ID nor a valid legacy override-suffix ID; or
* the identifier **is** valid, but the line is indented off column 0 — an indented entry is not an entry, and saying so is the point.

"Not parsed" and "reported" are the same event. Every form in the table above is rejected and reported.

Reporting does not change parsing. A swallowed line still continues the statement above it, exactly as any other non-ID, non-field line does, so the error is the only signal — which is why it exists. `  DEC-INPUT-002: rule` is therefore an error *and* a continuation of the entry above it until someone fixes the indentation.

The second pattern allows only **one** extra token, so a wrapped statement line that merely refers to another decision (`DEC-INPUT-001 is the reason we ...`) is not reported. It still catches the space-instead-of-hyphen typo, which is what it is for. The unavoidable edge is a line like `DEC-INPUT-001 is: ...`, which reads as an ID attempt and is reported as one.

## 6. Lint: errors and warnings

Lint returns two lists. The split is load-bearing: **errors block, warnings never do, and nothing is ever auto-edited on the strength of a warning.**

### 6.1 Errors

The file is not in the current format.

| Code | Condition |
|---|---|
| `unreadable` | the file cannot be read at all |
| `not_utf8` | bytes did not decode as UTF-8; replacement characters were substituted |
| `status_line` | a line beginning `Status:` at column 0 |
| `override_suffix_id` | a retired suffix ID such as `DEC-INPUT-007d` |
| `malformed_id` | an ID-shaped line that fails the grammar, is indented off column 0, or has whitespace inside the identifier ([§5.3](#53-near-miss-identifiers-that-must-fail)) |
| `unclosed_fence` | a fence opened and never closed |
| `duplicate_id` | the same ID appears twice; both stay entries, the second is the error |
| `missing_statement` | an entry whose statement is empty after joining |

An error carries `code`, a human `message`, and `line` when a line is meaningful (`not_utf8` and `unreadable` are file-level and have no line). Errors are returned ordered by line, with file-level issues first, then by code — so an adapter can report them in a stable order without sorting.

### 6.2 Warnings

Bloat signals. Never a reason to refuse anything, never repaired automatically.

| Code | Condition | Threshold |
|---|---|---|
| `entry_too_long` | non-blank lines from the ID line to the next ID line | more than 8 |
| `statement_too_long` | words in the joined statement | more than 120 |
| `code_fingerprint` | the statement names a source file, a `name()` call, or a `lower_snake_identifier` with three or more parts | first match only |
| `area_too_large` | entries sharing one area label | more than 25 |
| `near_duplicate` | two entries in the same area with Jaccard similarity of statement tokens ≥ 0.6, each with at least 4 tokens | — |
| `near_duplicate_skipped` | the comparison was skipped for an area | area larger than 250 entries, or the 60000-pair budget exhausted |

The fingerprint patterns are applied **word by word** to the statement, never across the whole string; running a character class over a long statement backtracks catastrophically. The three forms:

* a file or path ending in a source extension — `gd tscn tres gdshader py js jsx mjs cjs ts tsx rb go rs lua sh ps1 json cfg` — with optional trailing `.,;:)`;
* a call: `name()`, one to sixty word characters;
* an identifier: `lower_snake_case` with three or more underscore-separated parts, each one to thirty lowercase letters.

Constants the implementation must use: `MAX_ENTRY_LINES 8`, `MAX_STATEMENT_WORDS 120`, `MAX_AREA_ENTRIES 25`, `NEAR_DUPLICATE_RATIO 0.6`, `NEAR_DUPLICATE_MAX_AREA 250`, `NEAR_DUPLICATE_PAIR_BUDGET 60000`, `NEAR_DUPLICATE_MAX_TOKENS 60`.

Warnings are advisory because a linter that fires on most of a real file is ignored, and then it catches nothing.

## 7. Migration

Migration exists for one release's worth of leftover pre-2.0 files. It never decides anything and never asks for prose: it removes what is mechanically dead and refuses what needs a human.

### 7.1 `--write`

Removes **only** trivial status lines: a line matching, after trimming, one of

```
Status: Active
Status: Active (<YYYY-MM-DD>)
```

Nothing else is touched. A `Status:` line carrying any other text — a revision note, a date plus prose, `Superseded` — is left exactly where it is and counted as needing a human. That line is frequently where the migrated statement ended up, and deleting it destroys a rule.

Byte discipline:

* the file is written **only** when at least one line is removed; a conforming file is left byte-identical, and a second `--write` is a no-op;
* every surviving line keeps its own terminator, so a CRLF file stays CRLF;
* when the file is rewritten it is written as UTF-8 **without** a BOM, which is the one byte-level change migration may make.

### 7.2 `--archive-superseded`

Moves superseded records out of the file and into `support/decision_archive.md`, then removes them from `DECISIONS.md`. Archive first, strip second — always. Stripping a superseded record without archiving it promotes a dead rule back to binding, which is worse than leaving it.

A record is superseded when it carries a field named `Status` whose value begins with `Superseded` (case-insensitive). The successor ID is the first valid ID found in that field's value, or, failing that, the first valid ID in the statement after the phrase `Superseded by`.

The operation refuses — and writes nothing at all — when:

* `archive_refused_no_successor`: a superseded record names no successor ID;
* `archive_refused_missing_successor`: the named successor is not a parsed entry in this file.

On success, for each record in file order:

* its block is appended verbatim to the archive, ID line through its last non-blank line, including the `Status:` line, separated from the previous block by one blank line;
* the archive gets a section header carrying an ISO-8601 timestamp (`now`, supplied by the caller for determinism);
* the block and one following blank line are removed from `DECISIONS.md`; blank lines before the block are kept;
* every other byte of `DECISIONS.md` is preserved, terminators included.

Archive file shape, exactly:

```
# Decision archive

Records moved out of DECISIONS.md are not binding. Git holds the full history.

## Archived <ISO timestamp> from DECISIONS.md

<record>
```

The archive is appended to, never overwritten. It is not a decisions file, is never parsed for binding, and its name must differ from `DECISIONS.md` precisely so nothing picks it up.

### 7.3 `--check`

Reports what a run would do without touching anything: trivial status lines, status lines needing a human, superseded records with their successors, and the current format-error count. It reports "clean" only when nothing at all remains to do.

## 8. Behaviour carried over from 2.2.0

These are real behaviours of the 2.2.0 implementation. v3 keeps them, fixtures pin them, and they are listed here so that nobody "fixes" one by accident. Each is a candidate for a later release, with a fixture change to match. The two identifier shapes that 2.2.0 also absorbed without a word — an indented entry and a space where the hyphen belongs — are no longer in this list: v3 reports both ([§9](#changes-from-220)).

* **A status line inside a closed fence is still reported.** Fence blanking affects parsing, not the legacy scans.
* **A heading written directly under a statement joins it.** `DEC-X-001: rule` followed immediately by `## Combat` makes `## Combat` part of the statement. The fix is a blank line, which canonical layout already requires.
* **An indented `Status:` line is neither a field nor an error.** It joins the statement. (An indented *entry* is now an error; an indented status line is not caught by that rule, because it is not an ID.)
* **Discovery takes the first file in search order and says nothing about the others.** A stale `docs/DECISIONS.md` beside a live root file is invisible.
* **Entries with no blank line between them still parse.** Convenient, non-canonical, and not worth an error.

## 9. Changes from 2.2.0

1. **ID grammar.** v2 accepted `DEC-<letters>-<any digits>`, where "letters" was one segment of one or more. v3 requires `[A-Z]{2,}` per segment, one or more segments, and exactly three digits at the end. Consequences: `DEC-ENEMY-AI-001` becomes an entry (24 such records exist in one live project, invisible today), while `DEC-C-001`, `DEC-COMBAT-01` and `DEC-COMBAT-0001` become errors. No live project has an ID that v2 accepted and v3 rejects, so the tightening costs nothing today.
2. **Area label.** The label spans every area segment (`enemy-ai`), which is what grouping, `--area` and `area_map` use.
3. **Issue codes.** Lint issues carry a stable machine code beside their message, so an adapter can report structure without pinning prose.
4. **Swallowed identifiers are reported.** `  DEC-INPUT-002: rule` (an entry indented off column 0) and `DEC-INPUT 003: rule` (a space where the hyphen belongs) were absorbed into the statement above them with no diagnostic in 2.2.0, which is the same silent loss the grammar change exists to end. Both are now `malformed_id` ([§5.3](#53-near-miss-identifiers-that-must-fail)). No live project contains either shape, so nothing gains an error today, and parsing is unchanged: the line still continues the statement until someone fixes it.

One thing deliberately *not* changed, because it looks like an oversight and is not: a `Status:` line inside a closed fence is still reported ([§8](#behaviour-carried-over-from-220)), even though the fence's contents are never entries.

No other format rule changes.

## 10. Conformance fixtures

`tests/conformance/` holds fixture projects and expected results for these rules. The mapping:

| Rule | Case |
|---|---|
| LF file, statement, per-area serving | `lf-basic` |
| CRLF normalisation (the load-bearing case) | `crlf-basic`, `crlf-migrate` |
| BOM stripping | `bom-basic` |
| Paths containing spaces | `path-with-space` |
| ID grammar and every near miss | `near-miss-ids`, `swallowed-lines` |
| Wrapped statements, `Context:`, field continuation, no trailing newline | `wrapped-and-context` |
| Three superseded records, archive before strip | `superseded-archive`, `archive-refused` |
| Trivial versus human status lines | `legacy-status` |
| Fences, prose, unclosed fence | `fences-prose` |
| Discovery, config, out-of-project, disabled project | `scope-and-config` |
| Duplicates, empty statements, invalid encoding | `lint-errors` |
| The unmatched-edit backstop | `uncovered-backstop` |
| The traps in [§8](#behaviour-carried-over-from-220), plus the two swallowed-identifier shapes that are now reported | `swallowed-lines` |
