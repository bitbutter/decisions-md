---
description: Query the project's binding DECISIONS.md (read path). Do NOT Read/Grep DECISIONS.md directly.
argument-hint: [--area AREA | --query KEYWORDS | --validate]
allowed-tools: Bash(sh:*)
---
Consult the project's binding design decisions, then review the output below.

Running the decisions read CLI (this also unlocks the edit gate for this session).
The interpreter is resolved at run time because no single Python name exists on every
platform: `python3` is absent from most Windows installs, `python` from many Linux
distributions. The `sh -c` wrapper keeps a stable leading token for `allowed-tools`.

!`sh -c '"$(command -v python3 || command -v python || command -v py)" "$0" "$@"' "${CLAUDE_PLUGIN_ROOT}/scripts/query_decisions.py" $ARGUMENTS`

Multi-word queries work without quoting: `/decisions-md:decisions --query session id` collects
"session id" as a single query. Use `--area AREA` to filter by area, or omit all
arguments to list areas and counts. `--doctor` reports whether the plugin's hooks are
running at all, and does not unlock the gate.

If any decision DIRECTLY answers the question or DIRECTLY contradicts a proposed
change, stop and present the user three options before proceeding:

1. **Abandon** — drop this line of inquiry.
2. **Adapt** — achieve the intent within the existing decision.
3. **Override** — supersede the decision (propose an updated entry, then proceed).

If the decisions are only contextually related (same area, different concern), note
them briefly and continue.
