---
name: decisions-binding
description: The binding protocol for a project's DECISIONS.md design memory. Use before design-touching work, when a decision may answer a question or contradict a proposed change, and when deciding whether something new belongs in the file. Covers the entry format, changing and retiring decisions, and the abandon/adapt/override protocol.
---

# DECISIONS.md binding protocol

`DECISIONS.md` records binding design decisions. Code and tests must follow them.

## The format

```
DEC-INPUT-001: Jumping is bound to the A button.
Context: The face buttons are reserved for actions the player uses under pressure.
```

An ID, a colon, and the rule. The statement may wrap across lines. `Context:` is
optional and holds the reasoning, briefly.

There is no status line and no status vocabulary. **Everything in the file is
binding** — that is the whole point of the file. A `Status:` line would say the same
thing on every entry, so it says nothing.

There are no override-suffix IDs (`DEC-INPUT-001d`). They are a lint error.

## Changing a decision

Edit the entry in place and keep its ID.

Do not append a second entry that overrides the first, and do not stack a revision
log inside the entry. The file states what is true now; `git log -p DECISIONS.md`
states what used to be true, with a date, an author and a message. Put the reason for
the change in the commit message.

Keeping the ID stable matters: code comments cite these IDs, and a comment pointing at
`DEC-INPUT-001` should lead to the rule that is in force, not to a superseded one with
a pointer to its own replacement.

If a change genuinely splits one decision into two, keep the original ID for the part
that inherits the original intent and mint a new ID for the rest.

## Retiring a decision

Delete it.

The obvious worry — that someone will now re-open a settled question — is worth
thinking through once. If "we considered X and rejected it" still binds future work,
that is not a retired decision, it is a live one: write it as a rule in its own right.
Otherwise the question really is open again, and re-opening it is correct.

## What belongs in an entry

DECISIONS.md records **user- or designer-facing** decisions: rules, UX, balance, what
a control does, win and scoring conditions. It is not implementation documentation and
not a changelog.

- **Would a user or designer care, not just a programmer?** If a fact only makes sense
  to someone reading the code, it belongs in a code comment citing the decision ID.
- **State the rule, not the fix.** Never narrate how a bug was found or corrected.
- **No implementation fingerprints.** No file paths, line numbers, function or variable
  names in the statement.
- **Pure refactors, internal fixes and behavior-preserving changes need no entry.**
- **One or two sentences.** An entry that runs past about eight lines has stopped being
  a rule and become a design document; the linter will say so.

## Consulting decisions

The decisions that govern a file are shown to you automatically, once per area per
session, immediately before your first edit there. You do not need to ask for them.

To look things up yourself:

```
/decisions-md:decisions --query <keywords>
/decisions-md:decisions --area <area>
/decisions-md:decisions                     # areas and counts
```

## When a decision is directly relevant

If a decision **directly answers** the question or **directly contradicts** a proposed
change, stop and give the user three options:

1. **Abandon** — drop this line of inquiry; wait for direction.
2. **Adapt** — achieve the intent within the existing decision.
3. **Override** — supersede it. Edit that entry in place under its existing ID, then
   proceed.

If decisions are only contextually related (same area, different concern), note them
briefly and carry on.

## Proposing a new decision

The bar is high, and the default answer is that no entry is needed. A decisions file
that accumulates an entry per session stops being memory and becomes noise — every
future read costs more and the rules that matter get harder to see.

Propose one only when the work settled a user- or designer-facing rule that nothing on
file already covers. Then:

1. Search for near-duplicates: `/decisions-md:decisions --query <keywords>`.
2. Name the existing decision you checked against when you propose.
3. Draft the statement — a sentence or two, plus a brief `Context:` — and ask the user
   to confirm before writing it.
4. Check the format afterwards: `/decisions-md:decisions --lint`.
