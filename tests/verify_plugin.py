#!/usr/bin/env python3
"""Synthetic-payload harness for the decisions-md plugin.

Creates a temporary consuming project, drives each hook with crafted JSON payloads,
and asserts the expected behaviour without requiring a live Claude Code session.

Usage:
    python3 tests/verify_plugin.py            # run all checks
    python3 tests/verify_plugin.py -v         # verbose

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent.resolve()
HOOKS_DIR = PLUGIN_ROOT / "hooks"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"

DECISIONS_MD = """\
DEC-ARCH-001: Use a layered architecture with clear separation of concerns.
Status: Active (2026-01-01)

DEC-ARCH-002: All public APIs must be versioned from the start.
Status: Active (2026-01-01)

DEC-UI-001: The UI layer must not contain business logic.
Status: Active (2026-01-01)
"""

SESSION_ID = "test-session-abc123"

_passes = 0
_failures = 0
_verbose = "-v" in sys.argv


def _log(msg):
    if _verbose:
        print(f"    {msg}", flush=True)


def check(name, condition, detail=""):
    global _passes, _failures
    if condition:
        print(f"  PASS  {name}", flush=True)
        _passes += 1
    else:
        print(f"  FAIL  {name}", flush=True)
        if detail:
            print(f"        {detail}", flush=True)
        _failures += 1


def run_hook(hook_file, payload, env=None):
    """Run a hook script with a JSON payload on stdin. Returns (returncode, stdout, stderr)."""
    merged_env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
    if env:
        merged_env.update(env)
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / hook_file)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )
    _log(f"{hook_file} rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}")
    return result.returncode, result.stdout, result.stderr


def run_cli(args, env=None):
    """Run query_decisions.py with given args list. Returns (returncode, stdout, stderr)."""
    merged_env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
    if env:
        merged_env.update(env)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "query_decisions.py")] + args,
        capture_output=True,
        text=True,
        env=merged_env,
    )
    _log(f"cli {args} rc={result.returncode} stdout={result.stdout!r}")
    return result.returncode, result.stdout, result.stderr


def setup_project(tmp_dir, write_decisions=True, config=None):
    """Create a minimal consuming project in a unique subdir of tmp_dir and return its path."""
    project = Path(tempfile.mkdtemp(dir=tmp_dir))
    if write_decisions:
        (project / "DECISIONS.md").write_text(DECISIONS_MD, encoding="utf-8")
    if config is not None:
        decisions_dir = project / ".decisions"
        decisions_dir.mkdir()
        (decisions_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    # Tracked test file
    src = project / "main.gd"
    src.write_text("# godot source", encoding="utf-8")
    return project


# ── Section 1: manifest ────────────────────────────────────────────────────────

def test_manifest(tmp):
    print("\n[1] Manifest")
    pj = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
    check("plugin.json: name is 'decisions-md'", pj.get("name") == "decisions-md")
    check("plugin.json: version present", bool(pj.get("version")))
    check("plugin.json: description present", bool(pj.get("description")))
    check("plugin.json: license is MIT", pj.get("license") == "MIT")

    hj = json.loads((HOOKS_DIR / "hooks.json").read_text())
    hooks = hj.get("hooks", {})
    for event in ("SessionStart", "PreToolUse", "PostToolUse", "UserPromptSubmit", "PreCompact", "Stop"):
        check(f"hooks.json: declares {event}", event in hooks)


# ── Section 2: portability (no DECISIONS.md → all hooks no-op) ────────────────

def test_portability(tmp):
    print("\n[2] Portability — no DECISIONS.md")
    project = setup_project(tmp, write_decisions=False)
    env = {"CLAUDE_PROJECT_DIR": str(project), "DECISIONS_SESSION_ID": SESSION_ID}

    payload = {"tool_name": "Write", "tool_input": {"file_path": str(project / "main.gd")}, "session_id": SESSION_ID}
    rc, out, _ = run_hook("decisions_gate.py", payload, env)
    check("gate: no-op when no DECISIONS.md (exit 0)", rc == 0)
    check("gate: no block output when no DECISIONS.md", "DECISIONS GATE" not in out)

    rc, out, _ = run_hook("decisions_binding_nudge.py", {}, env)
    check("binding_nudge: no-op when no DECISIONS.md (exit 0)", rc == 0)
    check("binding_nudge: empty output when no DECISIONS.md", out.strip() == "")


# ── Section 3: SessionStart persists session id ───────────────────────────────

def test_session_start(tmp):
    print("\n[3] SessionStart")
    project = setup_project(tmp)
    env = {"CLAUDE_PROJECT_DIR": str(project)}
    cache_dir = project / ".decisions" / "cache"

    payload = {"session_id": SESSION_ID}
    rc, _, _ = run_hook("decisions_session_start.py", payload, env)
    check("session_start: exits 0", rc == 0)

    sid_file = cache_dir / "current-session-id"
    check("session_start: wrote current-session-id", sid_file.exists())
    check("session_start: correct session id", sid_file.read_text().strip() == SESSION_ID)

    # Re-arm: place a stop-hook-fired flag and verify it is removed
    flag = cache_dir / "stop-hook-fired-this-session"
    flag.touch()
    run_hook("decisions_session_start.py", payload, env)
    check("session_start: re-arms stop gate (removes flag)", not flag.exists())

    # Session id must land in PROJECT, not plugin dir
    plugin_cache = PLUGIN_ROOT / ".decisions" / "cache"
    check("session_start: writes to project cache, not plugin dir",
          not plugin_cache.exists() or not (plugin_cache / "current-session-id").exists())


# ── Section 4: gate — locked before consult ───────────────────────────────────

def test_gate_locked(tmp):
    print("\n[4] Gate — locked (no prior consult)")
    project = setup_project(tmp)
    env = {"CLAUDE_PROJECT_DIR": str(project), "DECISIONS_SESSION_ID": SESSION_ID}

    payload = {"tool_name": "Write", "tool_input": {"file_path": str(project / "main.gd")}, "session_id": SESSION_ID}
    rc, out, _ = run_hook("decisions_gate.py", payload, env)
    check("gate: blocks (exit 2)", rc == 2)
    check("gate: block message present", "DECISIONS GATE" in out)


# ── Section 5: gate — unlock via CLI ──────────────────────────────────────────

def test_gate_unlock(tmp):
    print("\n[5] Gate — unlock via query CLI")
    project = setup_project(tmp)
    env = {"CLAUDE_PROJECT_DIR": str(project), "DECISIONS_SESSION_ID": SESSION_ID}

    # Run CLI to write unlock marker
    rc, out, _ = run_cli(["--query", "architecture"], env)
    check("cli: exit 0 after query", rc == 0)
    check("cli: found decisions", "DECISIONS FOUND" in out or "ARCH" in out)

    marker = project / ".decisions" / "cache" / f"decisions-checked-{SESSION_ID}"
    check("cli: wrote unlock marker in project (not plugin dir)", marker.exists())
    plugin_marker = PLUGIN_ROOT / ".decisions" / "cache" / f"decisions-checked-{SESSION_ID}"
    check("cli: did NOT write unlock marker in plugin dir", not plugin_marker.exists())

    # Gate should now pass
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(project / "main.gd")}, "session_id": SESSION_ID}
    rc, out, _ = run_hook("decisions_gate.py", payload, env)
    check("gate: allows after unlock (exit 0)", rc == 0)
    check("gate: no block message after unlock", "DECISIONS GATE" not in out)


# ── Section 6: gate — exempt paths never blocked ─────────────────────────────

def test_gate_exempt(tmp):
    print("\n[6] Gate — exempt paths")
    project = setup_project(tmp)
    env = {"CLAUDE_PROJECT_DIR": str(project), "DECISIONS_SESSION_ID": SESSION_ID + "-exempt"}

    # DECISIONS.md itself is always exempt
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(project / "DECISIONS.md")}, "session_id": SESSION_ID + "-exempt"}
    rc, out, _ = run_hook("decisions_gate.py", payload, env)
    check("gate: DECISIONS.md itself is exempt (exit 0)", rc == 0)

    # .claude/ prefix is exempt by default
    claude_dir = project / ".claude"
    claude_dir.mkdir()
    payload["tool_input"]["file_path"] = str(claude_dir / "settings.json")
    rc, out, _ = run_hook("decisions_gate.py", payload, env)
    check("gate: .claude/ path is exempt (exit 0)", rc == 0)

    # Untracked extension (.txt) is not blocked
    payload["tool_input"]["file_path"] = str(project / "notes.txt")
    rc, out, _ = run_hook("decisions_gate.py", payload, env)
    check("gate: untracked extension not blocked (exit 0)", rc == 0)


# ── Section 7: check → nudge pipeline ────────────────────────────────────────

def test_check_nudge(tmp):
    print("\n[7] PostToolUse check → UserPromptSubmit nudge")
    project = setup_project(tmp)
    env = {"CLAUDE_PROJECT_DIR": str(project)}

    # PostToolUse records the edit
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(project / "main.gd")}, "session_id": SESSION_ID}
    rc, _, _ = run_hook("decisions_check.py", payload, env)
    check("check: exits 0", rc == 0)

    pending_file = project / ".decisions" / "cache" / "decisions-pending-edits.json"
    check("check: recorded edit in pending-edits.json", pending_file.exists())
    pending = json.loads(pending_file.read_text())
    check("check: correct file recorded", any("main.gd" in p for p in pending))

    # Nudge fires and clears the list
    rc, out, _ = run_hook("decisions_nudge.py", {}, env)
    check("nudge: exits 0", rc == 0)
    check("nudge: emits reminder", "decisions-nudge" in out or "tracked files" in out)
    check("nudge: clears pending-edits.json", not pending_file.exists())

    # Second nudge is silent (list is clear)
    rc, out, _ = run_hook("decisions_nudge.py", {}, env)
    check("nudge: silent on second call (no pending)", out.strip() == "")


# ── Section 8: DECISIONS.md format validation ─────────────────────────────────

def test_decisions_validation(tmp):
    print("\n[8] DECISIONS.md format validation")
    project = setup_project(tmp)
    env = {"CLAUDE_PROJECT_DIR": str(project), "DECISIONS_SESSION_ID": SESSION_ID}

    # Valid DECISIONS.md → --validate passes
    rc, out, _ = run_cli(["--validate"], env)
    check("cli --validate: passes on valid DECISIONS.md (exit 0)", rc == 0)
    check("cli --validate: reports OK", "VALIDATION OK" in out)

    # Corrupt DECISIONS.md → --validate fails
    bad = project / "DECISIONS.md"
    bad.write_text("DEC-ARCH-003: Missing status line.\n\nSome other text.\n", encoding="utf-8")
    rc, out, _ = run_cli(["--validate"], env)
    check("cli --validate: fails on malformed DECISIONS.md (exit 1)", rc == 1)
    check("cli --validate: reports issue", "VALIDATION ISSUES" in out or "missing" in out.lower())


# ── Section 9: binding nudge and precompact injection ────────────────────────

def test_binding_injection(tmp):
    print("\n[9] Binding nudge + PreCompact injection")
    project = setup_project(tmp)
    env = {"CLAUDE_PROJECT_DIR": str(project)}

    rc, out, _ = run_hook("decisions_binding_nudge.py", {}, env)
    check("binding_nudge: exits 0", rc == 0)
    data = json.loads(out)
    ctx = data.get("hookSpecificOutput", {}).get("additionalContext", "")
    check("binding_nudge: DECISIONS-BINDING in output", "DECISIONS-BINDING" in ctx)
    check("binding_nudge: overview in output", "decisions" in ctx.lower())

    rc, out, _ = run_hook("decisions_precompact.py", {}, env)
    check("precompact: exits 0", rc == 0)
    data = json.loads(out)
    instr = data.get("hookSpecificOutput", {}).get("customInstructions", "")
    check("precompact: DECISIONS-BINDING in customInstructions", "DECISIONS-BINDING" in instr)


# ── Section 10: stop hook — block-once ───────────────────────────────────────

def test_stop_hook(tmp):
    print("\n[10] Stop hook — block-once")
    project = setup_project(tmp)
    env = {"CLAUDE_PROJECT_DIR": str(project)}
    cache_dir = project / ".decisions" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Seed a pending edit
    (cache_dir / "decisions-pending-edits.json").write_text(
        json.dumps([str(project / "main.gd")]), encoding="utf-8"
    )

    payload = {"stop_hook_active": False}
    rc, out, _ = run_hook("decisions_stop_check.py", payload, env)
    check("stop: exits 0", rc == 0)
    if out.strip():
        data = json.loads(out)
        decision = data.get("hookSpecificOutput", {}).get("decision", "")
        check("stop: blocks on first fire", decision == "block")
    else:
        check("stop: blocks on first fire", False, "no output from stop hook")

    flag = cache_dir / "stop-hook-fired-this-session"
    check("stop: wrote once-per-session flag", flag.exists())
    check("stop: cleared pending-edits", not (cache_dir / "decisions-pending-edits.json").exists())

    # Second fire is silent
    rc, out, _ = run_hook("decisions_stop_check.py", payload, env)
    check("stop: silent on second fire (flag present)", out.strip() == "")

    # stop_hook_active guard
    flag.unlink(missing_ok=True)
    (cache_dir / "decisions-pending-edits.json").write_text(json.dumps(["x.gd"]), encoding="utf-8")
    rc, out, _ = run_hook("decisions_stop_check.py", {"stop_hook_active": True}, env)
    check("stop: no-op when stop_hook_active=True", out.strip() == "")


# ── Section 11: per-project config override ───────────────────────────────────

def test_config_override(tmp):
    print("\n[11] Per-project config override")

    # .gd becomes untracked; .xyz becomes tracked
    config = {"tracked_extensions": [".xyz"], "exempt_paths": ["DECISIONS.md", ".decisions/"]}
    project = setup_project(tmp, config=config)
    env = {"CLAUDE_PROJECT_DIR": str(project), "DECISIONS_SESSION_ID": SESSION_ID + "-cfg"}
    sid = SESSION_ID + "-cfg"

    # .gd is NOT tracked → gate passes without unlock
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(project / "main.gd")}, "session_id": sid}
    rc, out, _ = run_hook("decisions_gate.py", payload, env)
    check("config: untracked extension (.gd) not blocked", rc == 0, out)

    # .xyz IS tracked → gate blocks
    payload["tool_input"]["file_path"] = str(project / "data.xyz")
    rc, out, _ = run_hook("decisions_gate.py", payload, env)
    check("config: custom tracked extension (.xyz) blocked (exit 2)", rc == 2, out)


# ── Section 12: multi-word --query via nargs ──────────────────────────────────

def test_multiword_query(tmp):
    print("\n[12] Multi-word --query (nargs fix)")
    project = setup_project(tmp)
    env = {"CLAUDE_PROJECT_DIR": str(project), "DECISIONS_SESSION_ID": SESSION_ID + "-mq"}

    # Two separate words — would have failed with old nargs=None
    rc, out, _ = run_cli(["--query", "layered", "architecture"], env)
    check("cli: --query multi-word exits 0", rc == 0)
    check("cli: --query multi-word finds results", "ARCH" in out or "DECISIONS FOUND" in out)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"decisions-md plugin synthetic-payload harness")
    print(f"Plugin root: {PLUGIN_ROOT}")

    with tempfile.TemporaryDirectory(prefix="decisions_md_test_") as tmp:
        test_manifest(tmp)
        test_portability(tmp)
        test_session_start(tmp)
        test_gate_locked(tmp)
        test_gate_unlock(tmp)
        test_gate_exempt(tmp)
        test_check_nudge(tmp)
        test_decisions_validation(tmp)
        test_binding_injection(tmp)
        test_stop_hook(tmp)
        test_config_override(tmp)
        test_multiword_query(tmp)

    print(f"\n{'='*50}")
    print(f"Results: {_passes} passed, {_failures} failed")
    return 0 if _failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
