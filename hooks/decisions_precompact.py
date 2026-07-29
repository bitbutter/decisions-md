#!/usr/bin/env python3
"""PreCompact hook: carries the orientation block through context compaction.

The same block SessionStart emits. Compaction is the one place it can be lost, which
is the only reason it is repeated at all.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import (
    setup_utf8_stdout, get_project_root, build_binding_lines, load_config, is_enabled,
)

setup_utf8_stdout()


def main():
    project_root = get_project_root()
    if not is_enabled(load_config(project_root)):
        sys.exit(0)
    lines = build_binding_lines(project_root)
    if not lines:
        sys.exit(0)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "customInstructions": "\n".join(lines),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
