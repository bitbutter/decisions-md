#!/usr/bin/env python3
"""
SessionStart hook: persist the session id, reset this session's bookkeeping, and
inject the one-time orientation block.

SessionStart is the only startup hook that receives the authoritative session_id on
stdin, and the CLI cannot see that payload -- so it is written to the state dir here
and read back from there.

The orientation block used to be re-injected on every single prompt. It is static
text, so it is emitted once here and once more through compaction instead. The
per-edit serve hook is what carries actual decision content.

Best-effort and silent: a SessionStart failure must never wedge startup.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import (
    setup_utf8_stdout, get_project_root, persist_session_id, reset_session,
    prune_old_state, build_binding_lines, load_config, is_enabled,
)

setup_utf8_stdout()


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    session_id = payload.get("session_id") if isinstance(payload, dict) else None

    project_root = get_project_root()
    if not is_enabled(load_config(project_root)):
        sys.exit(0)

    persist_session_id(project_root, session_id)
    # A new (or resumed) session starts with nothing served and nothing pending.
    reset_session(project_root, session_id)
    prune_old_state(project_root)

    lines = build_binding_lines(project_root)
    if not lines:
        sys.exit(0)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
