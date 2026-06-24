#!/usr/bin/env python3
"""
Stop hook: enforces decision capture after tracked-file edits.

If decisions-pending-edits.json is non-empty AND DECISIONS.md was not edited this
session AND no skip-flag is set, blocks the stop once and asks Claude to evaluate
whether any edits encode new design decisions. Guarded against loops by the
once-per-session flag and the stop_hook_active check.
"""

import json
import os
import sys

import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import (
    setup_utf8_stdout, get_project_root, get_cache_dir, find_decisions_md,
)

setup_utf8_stdout()

PENDING_EDITS_FILENAME = 'decisions-pending-edits.json'
STOP_HOOK_FIRED_FLAG = 'stop-hook-fired-this-session'


def get_pending_edits_path(cache_dir):
    return os.path.join(cache_dir, PENDING_EDITS_FILENAME)


def get_stop_hook_flag_path(cache_dir):
    return os.path.join(cache_dir, STOP_HOOK_FIRED_FLAG)


def load_pending_edits(cache_dir):
    path = get_pending_edits_path(cache_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def was_decisions_edited(project_root):
    """Check if DECISIONS.md appears in the current branch's uncommitted changes.

    Uses the resolved project root as the git working directory and derives the
    actual DECISIONS.md path (which may be in a subdir like docs/) so the check
    works for all five advertised search locations.
    """
    decisions_path = find_decisions_md(project_root)
    if not decisions_path or not project_root:
        return False
    try:
        rel = os.path.relpath(decisions_path, project_root).replace("\\", "/")
    except ValueError:
        rel = "DECISIONS.md"
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", rel],
            capture_output=True, text=True, timeout=5,
            cwd=project_root,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def clear_pending_edits(cache_dir):
    path = get_pending_edits_path(cache_dir)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        return  # best-effort: a cache-write failure must never wedge the Stop hook


def has_stop_hook_fired(cache_dir):
    return os.path.exists(get_stop_hook_flag_path(cache_dir))


def mark_stop_hook_fired(cache_dir):
    path = get_stop_hook_flag_path(cache_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('')
    except OSError:
        return  # best-effort: a cache-write failure must never wedge the Stop hook


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, Exception):
        input_data = {}

    if input_data.get('stop_hook_active', False):
        sys.exit(0)

    project_root = get_project_root()
    cache_dir = get_cache_dir(project_root)
    if not cache_dir:
        sys.exit(0)

    if has_stop_hook_fired(cache_dir):
        sys.exit(0)

    pending = load_pending_edits(cache_dir)
    if not pending:
        sys.exit(0)

    if was_decisions_edited(project_root):
        # Claude already is/was evaluating decisions, don't block
        clear_pending_edits(cache_dir)
        sys.exit(0)

    # All conditions met: block the stop and ask Claude to evaluate
    mark_stop_hook_fired(cache_dir)

    names = [os.path.basename(p) for p in pending]
    file_list = ', '.join(names[:5])
    if len(names) > 5:
        file_list += f' (+{len(names) - 5} more)'

    reason = (
        f'Tracked files were edited: {file_list}. '
        'Evaluate whether any edit encodes a new design decision; '
        'if yes check for near-duplicates via the decisions read CLI and propose an entry to the user; '
        'if none do, state that explicitly.'
    )

    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'Stop',
            'decision': 'block',
            'reason': reason
        }
    }))

    # Clear pending edits after the block fires to prevent repeated blocks in future sessions.
    clear_pending_edits(cache_dir)
    sys.exit(0)


if __name__ == '__main__':
    main()
