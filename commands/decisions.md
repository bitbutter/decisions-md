---
description: Query the project's binding DECISIONS.md (read path). Do NOT Read/Grep DECISIONS.md directly.
argument-hint: [--area AREA | --query KEYWORDS | --validate]
allowed-tools: Bash(python3:*)
---
Consult the project's binding design decisions, then review the output below.

Running the decisions read CLI (this also unlocks the edit gate for this session):

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/query_decisions.py" $ARGUMENTS`

Multi-word queries work without quoting: `/decisions --query session id` collects
"session id" as a single query. Use `--area AREA` to filter by area, or omit all
arguments to list areas and counts.

If any decision DIRECTLY answers the question or DIRECTLY contradicts a proposed
change, stop and present the user three options before proceeding:

1. **Abandon** — drop this line of inquiry.
2. **Adapt** — achieve the intent within the existing decision.
3. **Override** — supersede the decision (propose an updated entry, then proceed).

If the decisions are only contextually related (same area, different concern), note
them briefly and continue.
