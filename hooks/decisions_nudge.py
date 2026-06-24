#!/usr/bin/env python3
"""
UserPromptSubmit hook: nudges about new design decisions after tracked-file edits.

Exits silently if no pending edits were recorded since the last prompt. Otherwise
emits a one-line reminder and clears the cache.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import setup_utf8_stdout, get_project_root, get_cache_dir

setup_utf8_stdout()

PENDING_EDITS_FILENAME = 'decisions-pending-edits.json'


def main():
    cache_dir = get_cache_dir(get_project_root())
    if not cache_dir:
        sys.exit(0)

    cache_path = os.path.join(cache_dir, PENDING_EDITS_FILENAME)
    if not os.path.exists(cache_path):
        sys.exit(0)

    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            pending = json.load(f)
    except (OSError, json.JSONDecodeError):
        sys.exit(0)

    if not pending:
        sys.exit(0)

    names = [os.path.basename(p) for p in pending]
    summary = ', '.join(names[:5])
    if len(names) > 5:
        summary += f' (+{len(names) - 5} more)'

    # Clear cache before outputting so a crash doesn't re-fire indefinitely
    try:
        os.remove(cache_path)
    except OSError:
        return

    print(
        f'<decisions-nudge>Previous turn edited tracked files: {summary}. '
        f'If any edit encodes a new design decision, check DECISIONS.md for near-duplicates '
        f'and propose an entry if none exists.</decisions-nudge>'
    )
    sys.exit(0)


if __name__ == '__main__':
    main()
