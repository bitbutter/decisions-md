#!/usr/bin/env python3
"""
PreToolUse (Write|Edit) hook: blocks edits to design-relevant files until
DECISIONS.md has been consulted via the read CLI in the current session.

The set of guarded extensions and exempt path prefixes come from
`<project>/.decisions/config.json` (with defaults), so the plugin is reusable
across projects. The per-session unlock marker (`.decisions/cache/
decisions-checked-<session_id>`) is written by query_decisions.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import (
    setup_utf8_stdout, get_project_root, get_cache_dir, find_decisions_md,
    load_config, get_tracked_extensions, get_exempt_paths, is_within_project_root,
)

setup_utf8_stdout()


def is_tracked_file(file_path, tracked_extensions):
    _, ext = os.path.splitext(file_path)
    return ext.lower() in tracked_extensions


def is_exempt_path(file_path, project_root, exempt_paths):
    """True if file is DECISIONS.md itself or under an exempt path prefix."""
    if not file_path:
        return True

    norm_path = os.path.normcase(os.path.abspath(file_path))
    norm_root = os.path.normcase(os.path.abspath(project_root)) if project_root else ""

    decisions_path = os.path.join(project_root, "DECISIONS.md") if project_root else ""
    if decisions_path and os.path.normcase(os.path.abspath(decisions_path)) == norm_path:
        return True

    for exempt in exempt_paths:
        if norm_root:
            exempt_full = os.path.normcase(os.path.join(norm_root, exempt))
            if norm_path.startswith(exempt_full):
                return True
        if exempt in norm_path.replace("\\", "/"):
            return True
    return False


def get_gate_marker_path(session_id, project_root):
    if not session_id or not project_root:
        return None
    cache_dir = get_cache_dir(project_root)
    if not cache_dir:
        return None
    return os.path.join(cache_dir, f"decisions-checked-{session_id}")


def gate_marker_exists(session_id, project_root):
    marker_file = get_gate_marker_path(session_id, project_root)
    return bool(marker_file) and os.path.isfile(marker_file)


def _cli_path():
    """Best-effort absolute path to the plugin's read CLI, for the block message."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        return os.path.join(plugin_root, "scripts", "query_decisions.py")
    return None


def main():
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get("tool_name", "")
    except (json.JSONDecodeError, Exception):
        # Hook failure: fail-open (allow edits)
        sys.exit(0)

    if tool_name not in ("Write", "Edit"):
        sys.exit(0)

    project_root = get_project_root()

    # No DECISIONS.md? Gate is disabled (portability).
    if not find_decisions_md(project_root):
        sys.exit(0)

    file_path = input_data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)

    # This project's gate governs this project's files only. An edit somewhere else
    # (another repo, or the plugin's own source) must never be blocked here.
    if not is_within_project_root(file_path, project_root):
        sys.exit(0)

    config = load_config(project_root)

    if not is_tracked_file(file_path, get_tracked_extensions(config)):
        sys.exit(0)

    if is_exempt_path(file_path, project_root, get_exempt_paths(config)):
        sys.exit(0)

    session_id = input_data.get("session_id")
    if not session_id:
        # Can't track gate state without a session id: fail-open.
        sys.exit(0)

    if gate_marker_exists(session_id, project_root):
        sys.exit(0)

    # Gate is closed. Block with an actionable, plugin-aware message.
    # For an exit-2 PreToolUse block, Claude Code feeds ONLY stderr back to the
    # model; anything on stdout is discarded and the block renders as the opaque
    # "hook error: [...]: No stderr output".
    cli = _cli_path()
    cli_query = f'python3 "{cli}" --query <keywords>' if cli else "query_decisions.py --query <keywords>"
    cli_ack = f'python3 "{cli}" --ack-no-design "reason"' if cli else 'query_decisions.py --ack-no-design "reason"'
    print(
        "DECISIONS GATE: edits to design-relevant files require consulting DECISIONS.md first.\n\n"
        "You cannot edit tracked files until you have consulted the project's design decisions.\n\n"
        "Choose ONE path to unlock further edits this session:\n\n"
        "PREFERRED: consult by keywords from your task:\n"
        "  /decisions-md:decisions <keywords>\n"
        f"  (or directly: {cli_query})\n\n"
        "ALTERNATIVE: acknowledge this is not design-relevant work (logged for review):\n"
        f"  {cli_ack}\n\n"
        "Either path unlocks edits for the rest of this session. Then retry your edit.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
