#!/usr/bin/env python3
"""
PostToolUse (Write|Edit) hook.

Two jobs:
  * Record which tracked files were edited this session, so the Stop check knows
    whether anything happened that might not be written down yet.
  * Lint DECISIONS.md the moment it is written, so a format mistake surfaces while
    the entry is still in front of you.

Inert when the project has no DECISIONS.md.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import (
    setup_utf8_stdout, get_project_root, find_decisions_md, load_config, is_enabled,
    get_tracked_extensions, is_within_project_root, relative_path, lint_decisions,
    get_session_id, record_pending_edit, mark_decisions_touched,
)

setup_utf8_stdout()

# A pre-existing file can carry dozens of warnings. Dumping all of them into context on
# every single write to DECISIONS.md would cost more than the advice is worth, so the
# hook shows a sample and points at the full report.
MAX_INJECTED_ERRORS = 10
MAX_INJECTED_WARNINGS = 5


def build_lint_report(errors, warnings):
    parts = []
    if errors:
        parts.append("[DECISIONS.md format errors -- fix these]")
        parts.extend("  - %s" % e for e in errors[:MAX_INJECTED_ERRORS])
        if len(errors) > MAX_INJECTED_ERRORS:
            parts.append("  - (+%d more errors)" % (len(errors) - MAX_INJECTED_ERRORS))
    if warnings:
        parts.append("[DECISIONS.md warnings -- not blocking]")
        parts.extend("  - %s" % w for w in warnings[:MAX_INJECTED_WARNINGS])
        if len(warnings) > MAX_INJECTED_WARNINGS:
            parts.append("  - (+%d more warnings)" % (len(warnings) - MAX_INJECTED_WARNINGS))
    parts.append("Full report: /decisions-md:decisions --lint")
    return "\n".join(parts)


def is_decisions_file(file_path, decisions_md):
    try:
        return (os.path.normcase(os.path.abspath(file_path))
                == os.path.normcase(os.path.abspath(decisions_md)))
    except (OSError, ValueError):
        return False


def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if input_data.get("tool_name", "") not in ("Write", "Edit"):
        sys.exit(0)

    tool_input = input_data.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(file_path, str) or not file_path:
        sys.exit(0)

    project_root = get_project_root() or ""
    decisions_md = find_decisions_md(project_root)
    if not decisions_md:
        sys.exit(0)

    config = load_config(project_root)
    if not is_enabled(config):
        sys.exit(0)

    session_id = input_data.get("session_id") or get_session_id(project_root)

    if is_decisions_file(file_path, decisions_md):
        # Tell the Stop check this session already went and updated the file, so it
        # does not ask again. This is session-scoped and exact; asking git whether
        # DECISIONS.md is dirty answered a different question -- any stray uncommitted
        # edit from last week counted, and silently cancelled the check.
        if session_id:
            mark_decisions_touched(project_root, session_id)
        errors, warnings = lint_decisions(decisions_md)
        if errors or warnings:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": build_lint_report(errors, warnings),
            }}))
        sys.exit(0)

    if os.path.splitext(file_path)[1].lower() not in get_tracked_extensions(config):
        sys.exit(0)
    if not is_within_project_root(file_path, project_root):
        sys.exit(0)

    if session_id:
        record_pending_edit(project_root, session_id,
                            relative_path(file_path, project_root))

    sys.exit(0)


if __name__ == "__main__":
    main()
