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
   `DECISIONS.md`. Decisions document **intent**, not implementation detail.
