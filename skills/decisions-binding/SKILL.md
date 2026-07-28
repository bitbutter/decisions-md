---
name: decisions-binding
description: The binding protocol for a project's DECISIONS.md design-memory. Use BEFORE design-touching work, and whenever a decisions query result may directly answer a question or contradict a proposed change. Explains how to consult decisions and how to present abandon/adapt/override options.
---

# DECISIONS.md binding protocol

`DECISIONS.md` records binding design decisions. Code and tests must follow them.
Each entry has the form:

```
DEC-AREA-NNN: Statement.
Status: Active (YYYY-MM-DD)
```

Status values: `Active`, `Superseded by DEC-AREA-NNN`, `Deprecated`.

## What belongs in an entry

DECISIONS.md records **user- or designer-facing** decisions: rules, UX, balance,
what a control does, win/scoring conditions. It is not implementation
documentation and not a changelog. Before drafting an entry, check:

- **Would a user or designer care, not just a programmer?** If a fact only makes
  sense to someone reading the code, it's implementation detail — it belongs in a
  code comment (citing the decision ID), not here.
- **State the rule, not the fix.** Never narrate how a bug was found or corrected
  ("corrected after discovering X was wrong", "PROBLEM: … RULE: …"). Write only the
  current binding rule and, briefly, why.
- **No implementation fingerprints in the statement.** No file paths, line numbers,
  function or variable names in the binding statement itself. A `Source:` /
  `Context:` line may name the implementing file in one short clause for
  traceability — not a walkthrough of the code.
- **Pure refactors, internal fixes, and behavior-preserving changes need no entry.**
  Only behavior a user or designer would notice is in scope.
- **Don't narrate history inline.** Record an override as a suffix entry (below),
  not as a "REVISION: X redefined as Y, replacing Z" paragraph stacked inside one
  entry's prose. Folding a settled parent+suffix chain back into one current-state
  entry is a separate, periodic prune pass — not something to do at decision time.

## Always consult via the read path — never read the file directly

Before any design-touching work, query the decisions instead of opening the file:

```
/decisions --area <area>
/decisions --query <keywords>
```

Querying through the CLI also unlocks the consult-before-edit gate for the session.
Do **not** Read or Grep `DECISIONS.md` directly — the query tool exists so the gate
can confirm a real consultation happened, and so you see only the relevant entries.

## When a decision is directly relevant

If a decision **directly answers** the question or **directly contradicts** a
proposed change, stop and present the user three options:

1. **Abandon** — drop this line of inquiry; wait for direction.
2. **Adapt** — achieve the intent within the existing decision.
3. **Override** — supersede the decision and proceed (propose an updated entry:
   set the old one's Status to `Superseded by DEC-AREA-NNN` and draft the new entry).

## Amending or superseding an existing decision

When the user chooses **Override** (or **Adapt**) for a decision that already
exists, do NOT rewrite the parent clause in place — that erases the prior intent
and makes the history unreadable. Add a **suffix entry** instead, which the query
tool recognizes as its own first-class decision:

- **ID:** append a lowercase letter to the parent number — `DEC-AREA-NNNb`, then
  `c`, `d`, … in order. One letter only (`[a-z]`); never `007b1` or `007_bb`.
- **Header line:** `DEC-AREA-NNNn: OVERRIDES the <clause> of DEC-AREA-NNN` (or
  `REFINES`, `SUPERSEDES`) followed by the statement.
- Give it its own `Status: Active (overrides DEC-AREA-NNN <clause>)` line.
- Leave the parent clause in place, but add a one-line superseded-note on its
  `Refined` / `Context` line pointing at the suffix entry, so the file is not
  internally contradictory.

Suffix entries are queryable: `--query "NNNd"` returns the suffix decision, not
just the parent. If a query for a suffix you know exists returns only the parent,
the entry is malformed — check the ID has exactly one trailing lowercase letter
and a trailing `:`.

If decisions are only **contextually related** (same area, different concern), note
them briefly and proceed normally.

## When the work has no design implications

If a question or change has no bearing on design decisions, acknowledge it so the
gate doesn't keep nudging:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/query_decisions.py" --ack-no-design "reason"
```

## Proposing a new decision

When you implement novel behavior or the user expresses a clear design choice:

1. Validate format first: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/query_decisions.py" --validate`.
2. Search for near-duplicates with `/decisions --query <keywords>`.
3. If a near-duplicate exists, offer to overwrite, merge, or keep both.
4. If none exists, draft the entry and ask the user to confirm before writing it to
   `DECISIONS.md`. Decisions document **intent**, not implementation detail — see
   "What belongs in an entry" above before drafting.
