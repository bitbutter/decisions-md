#!/usr/bin/env python3
"""
PostToolUse (Write|Edit) hook: records edits to tracked files for decision nudging,
and validates DECISIONS.md format on writes to it.

- Appends the edited tracked-file path to .decisions/cache/decisions-pending-edits.json
- If the file IS DECISIONS.md, validates format and returns issues as additionalContext.

Inert when the project has no DECISIONS.md (no stray .decisions/cache is created).
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import (
    setup_utf8_stdout, get_project_root, get_cache_dir, find_decisions_md,
    load_config, get_tracked_extensions, is_within_project_root, DECISION_ID_RE,
)

setup_utf8_stdout()

PENDING_EDITS_FILENAME = 'decisions-pending-edits.json'


def get_pending_edits_path(project_root):
    cache_dir = get_cache_dir(project_root)
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, PENDING_EDITS_FILENAME)


def append_pending_edit(project_root, file_path):
    path = get_pending_edits_path(project_root)
    try:
        existing = []
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        normalized = file_path.replace('\\', '/')
        if normalized not in existing:
            existing.append(normalized)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(existing, f)
    except (OSError, json.JSONDecodeError):
        return


def validate_decisions(file_path):
    """Returns list of format issue strings, or [] if clean."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().replace('\r\n', '\n').replace('\r', '\n').lstrip('﻿').strip()
    except OSError:
        return []

    issues = []
    lines = content.split('\n')
    seen_ids = {}

    for i, line in enumerate(lines):
        m = re.match(rf'^({DECISION_ID_RE}):\s*(.+)$', line)
        if not m:
            continue
        dec_id = m.group(1)

        if dec_id in seen_ids:
            issues.append(f'{dec_id}: duplicate ID (also at line {seen_ids[dec_id] + 1})')
        seen_ids[dec_id] = i

        if i + 1 >= len(lines) or not re.match(r'^Status:\s*.+', lines[i + 1]):
            issues.append(f'{dec_id} (line {i + 1}): missing or malformed Status line')

    return issues


def is_decisions_file(file_path, project_root):
    normalized = file_path.replace('\\', '/').lower()
    # Mirror all search subdirs from decisions_common._DECISIONS_SEARCH_SUBDIRS
    subdirs = ('', 'docs', 'support', 'design', 'decisions')
    candidates = [
        os.path.join(project_root, d, 'DECISIONS.md').replace('\\', '/').lower()
        if d else os.path.join(project_root, 'DECISIONS.md').replace('\\', '/').lower()
        for d in subdirs
    ]
    return any(normalized == c for c in candidates)


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, Exception):
        sys.exit(0)

    tool_name = input_data.get('tool_name', '')
    if tool_name not in ('Write', 'Edit'):
        sys.exit(0)

    tool_input = input_data.get('tool_input', {})
    file_path = tool_input.get('file_path', '')
    if not file_path:
        sys.exit(0)

    project_root = get_project_root() or ''

    # Decisions system is inert when the project has no DECISIONS.md.
    if not find_decisions_md(project_root):
        sys.exit(0)

    if is_decisions_file(file_path, project_root):
        issues = validate_decisions(file_path)
        if issues:
            msg = '[DECISIONS.md format issues]\n' + '\n'.join(f'  - {i}' for i in issues)
            msg += '\nFix these before continuing.'
            output = {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': msg}}
            print(json.dumps(output))
        sys.exit(0)

    ext = os.path.splitext(file_path)[1].lower()
    if (ext in get_tracked_extensions(load_config(project_root))
            and is_within_project_root(file_path, project_root)):
        append_pending_edit(project_root, file_path)

    sys.exit(0)


if __name__ == '__main__':
    main()
