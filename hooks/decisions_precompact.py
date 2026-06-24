#!/usr/bin/env python3
"""PreCompact hook: injects DECISIONS binding rules as custom compaction instructions."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import setup_utf8_stdout, get_project_root, build_binding_lines

setup_utf8_stdout()


def main():
    lines = build_binding_lines(get_project_root())
    if not lines:
        sys.exit(0)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "customInstructions": "\n".join(lines)
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
