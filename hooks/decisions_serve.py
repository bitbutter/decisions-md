#!/usr/bin/env python3
"""
PreToolUse (Write|Edit) hook: serves the binding decisions that govern the file
about to be edited.

This is a delivery mechanism, not a lock. It does not ask Claude to go and look
something up -- it works out which decision areas cover the target path and prints
those decisions itself, once per area per session. A file no decision covers passes
through in silence.

It blocks the first edit in each newly-served area (exit 2) purely because that is how
text reaches the model: for an exit-2 PreToolUse block Claude Code feeds stderr back
and discards stdout. The retry then succeeds with no further action needed.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import (
    setup_utf8_stdout, get_project_root, find_decisions_md, load_config, is_enabled,
    get_tracked_extensions, get_exempt_paths, get_area_map, is_exempt_path,
    is_within_project_root, relative_path, parse_decisions, match_areas,
    statements_for_areas, get_session_id, area_is_served, claim_area_served,
)

setup_utf8_stdout()


def build_message(rel_path, areas, shown, withheld):
    area_label = ", ".join(areas)
    plural = "" if len(shown) == 1 else "s"
    body = [
        "[DECISIONS] %d binding decision%s govern %s (area: %s)."
        % (len(shown), plural, rel_path, area_label),
        "Read them, then re-run your edit. Nothing else is required to proceed.",
        "",
    ]
    body.extend(d.render(with_fields=False) for d in shown)
    if withheld > 0:
        body.append("")
        body.append(
            "(%d more in this area, and the reasoning behind each: "
            "/decisions-md:decisions --area %s)" % (withheld, areas[0])
        )
    body.append("")
    body.append(
        "If one of these contradicts the change you are about to make, stop and offer "
        "the user: abandon / adapt / override. Otherwise just carry on."
    )
    return "\n".join(body)


def main():
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # hook failure must never stand between a user and their edit

    if input_data.get("tool_name", "") not in ("Write", "Edit"):
        sys.exit(0)

    tool_input = input_data.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    # Anything but a string is a malformed payload. Bailing out beats a traceback from
    # deep inside a path call, in a hook whose whole contract is to stay out of the way.
    if not isinstance(file_path, str) or not file_path:
        sys.exit(0)

    project_root = get_project_root()
    decisions_md = find_decisions_md(project_root)
    if not decisions_md:
        sys.exit(0)

    config = load_config(project_root)
    if not is_enabled(config):
        sys.exit(0)

    if not is_within_project_root(file_path, project_root):
        sys.exit(0)

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in get_tracked_extensions(config):
        sys.exit(0)

    if is_exempt_path(file_path, project_root, get_exempt_paths(config), decisions_md):
        sys.exit(0)

    # Without a session id there is no way to remember what has been served, and
    # re-serving on every single edit would be worse than staying quiet.
    session_id = input_data.get("session_id") or get_session_id(project_root)
    if not session_id:
        sys.exit(0)

    decisions = parse_decisions(decisions_md)
    if not decisions:
        sys.exit(0)

    rel_path = relative_path(file_path, project_root)
    areas = match_areas(decisions, rel_path, get_area_map(config))
    if not areas:
        sys.exit(0)  # nothing on file bears on this path; say nothing

    if all(area_is_served(project_root, session_id, a) for a in areas):
        sys.exit(0)

    # Claim each area BEFORE printing anything. The claim is what stops this block
    # repeating, so a block must never outlive a claim that failed: if the marker
    # cannot be written -- a locked state file, a full disk -- the right answer is to
    # stay quiet and let the edit through, not to block on every retry forever.
    fresh = [a for a in areas if claim_area_served(project_root, session_id, a)]
    if not fresh:
        sys.exit(0)

    shown, withheld = statements_for_areas(decisions, fresh)
    if not shown:
        sys.exit(0)

    print(build_message(rel_path, fresh, shown, withheld), file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
