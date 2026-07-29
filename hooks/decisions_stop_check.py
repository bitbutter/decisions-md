#!/usr/bin/env python3
"""
Stop hook: the backstop for decisions made but never written down.

It deliberately does NOT fire after every session that touched source. If the files
you edited are already governed by decisions in an area, the odds you invented a new
binding rule are low, and asking anyway is how a decisions file fills up with entries
nobody needed. So it fires only for work in areas nothing on file covers, at most once
per session, and its default answer is "no entry needed".
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import (
    setup_utf8_stdout, get_project_root, find_decisions_md, load_config, is_enabled,
    get_area_map, parse_decisions, match_areas, get_session_id, take_pending_edits,
    decisions_were_touched, claim_stop_check,
)

setup_utf8_stdout()


def build_reason(uncovered):
    shown = ", ".join(uncovered[:5])
    if len(uncovered) > 5:
        shown += " (+%d more)" % (len(uncovered) - 5)
    return (
        "This session edited files in territory no decision currently covers: %s.\n\n"
        "Default answer: no entry is needed. Pure implementation, refactors, bug fixes "
        "and anything a user or designer would never notice do not belong in "
        "DECISIONS.md.\n\n"
        "Only if the work settled a USER- OR DESIGNER-FACING rule -- what a control "
        "does, a balance value, a UX rule, a win condition -- propose ONE entry: the "
        "binding statement in a sentence or two, plus a brief why. No file paths, no "
        "function names, no account of how a bug was found. Before proposing it, check "
        "existing decisions and name the one you checked against.\n\n"
        "If no entry is needed, reply with exactly this line and nothing else:\n"
        "No DECISIONS.md change needed."
    ) % shown


def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        input_data = {}

    if input_data.get("stop_hook_active", False):
        sys.exit(0)

    project_root = get_project_root()
    decisions_md = find_decisions_md(project_root)
    if not decisions_md:
        sys.exit(0)

    config = load_config(project_root)
    if not is_enabled(config):
        sys.exit(0)

    session_id = input_data.get("session_id") or get_session_id(project_root)
    if not session_id:
        sys.exit(0)

    if decisions_were_touched(project_root, session_id):
        take_pending_edits(project_root, session_id)
        sys.exit(0)

    # Reading the list also clears it: these edits have now been considered, whatever
    # the verdict below turns out to be.
    pending = take_pending_edits(project_root, session_id)
    if not pending:
        sys.exit(0)

    decisions = parse_decisions(decisions_md)
    area_map = get_area_map(config)
    uncovered = [p for p in pending if not match_areas(decisions, p, area_map)]
    if not uncovered:
        sys.exit(0)

    # Claim the single firing. If another Stop hook already took it, or the marker
    # cannot be written, stay quiet rather than risk asking twice.
    if not claim_stop_check(project_root, session_id):
        sys.exit(0)

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "Stop",
        "decision": "block",
        "reason": build_reason(uncovered),
    }}))
    sys.exit(0)


if __name__ == "__main__":
    main()
