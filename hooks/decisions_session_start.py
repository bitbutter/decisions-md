#!/usr/bin/env python3
"""
SessionStart hook: persist the real Claude Code session id and re-arm the Stop gate.

SessionStart is the only startup hook that receives the authoritative session_id on
stdin. Two downstream pieces need it but cannot see that payload:

  * query_decisions.py writes `.decisions/cache/decisions-checked-<id>` to unlock
    decisions_gate.py; run as a plain CLI it re-derives <id> from
    `.decisions/cache/current-session-id`. We write that file here, verbatim, so the
    CLI and the gate agree on the FIRST try -- no dependency on transcript-flush timing.
  * decisions_stop_check.py fires its capture gate once per session, guarded by
    `.decisions/cache/stop-hook-fired-this-session`. Deleting it here re-arms the gate
    for each real session.

Best-effort and silent: a SessionStart failure must never wedge startup.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decisions_common import get_project_root, get_cache_dir

STOP_HOOK_FIRED_FLAG = 'stop-hook-fired-this-session'


def _persist_session_id(cache_dir, session_id):
    """Step 1: persist session_id so query_decisions.py keys its unlock marker on the
    SAME id decisions_gate.py reads from its own SessionStart-less payloads."""
    if not session_id:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, "current-session-id"), "w", encoding="utf-8") as fh:
            fh.write(session_id)
    except OSError:
        return  # best-effort: never wedge startup on a cache-write failure


def _rearm_stop_gate(cache_dir):
    """Step 2: re-arm the Stop capture gate; a missing flag just means nothing to clear."""
    try:
        flag = os.path.join(cache_dir, STOP_HOOK_FIRED_FLAG)
        if os.path.isfile(flag):
            os.remove(flag)
    except OSError:
        return  # best-effort


def persist_session_id_and_rearm_gates(session_id):
    cache_dir = get_cache_dir(get_project_root())
    if not cache_dir:
        return
    # Two independent steps: a step-1 write failure must NOT skip the step-2 re-arm.
    _persist_session_id(cache_dir, session_id)
    _rearm_stop_gate(cache_dir)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    persist_session_id_and_rearm_gates(
        payload.get("session_id") if isinstance(payload, dict) else None
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
