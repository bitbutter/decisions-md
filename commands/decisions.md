---
description: Read the project's binding DECISIONS.md (search, browse, lint).
argument-hint: [--query KEYWORDS | --area AREA | --lint [--write] | --doctor]
allowed-tools: Bash(sh:*)
---
Reading the project's binding design decisions.

The interpreter is resolved at run time because no single Python name exists on every
platform: `python3` is absent from most Windows installs, `python` from many Linux
distributions. The `sh -c` wrapper keeps a stable leading token for `allowed-tools`.

!`sh -c '"$(command -v python3 || command -v python || command -v py)" "$0" "$@"' "${CLAUDE_PLUGIN_ROOT}/scripts/query_decisions.py" $ARGUMENTS`

Usage:

- no arguments — list the areas and how many decisions each holds
- `--query jump input` — search; multi-word works without quoting
- `--area input` — one area in full, including the reasoning behind each entry
- `--lint` — check the file's format; `--lint --write` removes leftover `Status:` lines
- `--doctor` — report whether the plugin's hooks are running here at all

Decisions in the output are binding. If one directly answers the question or directly
contradicts a proposed change, stop and offer the user three options:

1. **Abandon** — drop this line of inquiry.
2. **Adapt** — achieve the intent within the existing decision.
3. **Override** — supersede it: edit that entry in place, keeping its ID, then proceed.

If the decisions are only contextually related (same area, different concern), note
them briefly and continue.
