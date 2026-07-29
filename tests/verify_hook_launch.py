#!/usr/bin/env python3
"""Launch regression test: do the commands in hooks.json actually start on this OS?

The synthetic-payload harness (verify_plugin.py) runs the hook scripts through
`sys.executable`, so it proves the LOGIC is right while saying nothing about whether
Claude Code can launch them. That gap hid a total Windows failure: `python3` is absent
on most Windows installs, every hook failed to start, and nothing reported it -- the
plugin listed, its command autocompleted, and none of it ran.

So this test reads the command strings out of hooks/hooks.json (never a copy of them,
which would drift) and runs each one the way Claude Code does: through a POSIX shell.
Claude Code uses bash on Windows too -- Git Bash, not cmd.exe -- so bash is the correct
harness on all three platforms.

Usage:
    python tests/verify_hook_launch.py            # run all checks
    python tests/verify_hook_launch.py -v         # verbose

Exit 0 = all checks passed (or skipped for lack of a shell).
Exit 1 = one or more checks failed.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent.resolve()
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"

SESSION_ID = "launch-test-session"
DECISIONS_MD = """\
DEC-ARCH-001: Use a layered architecture with clear separation of concerns.
Status: Active (2026-01-01)
"""

_passes = 0
_failures = 0
_verbose = "-v" in sys.argv


def find_shell():
    """Locate the shell Claude Code launches hooks with, or None.

    On Windows this must be Git Bash, NOT `C:\\Windows\\System32\\bash.exe`, which is
    the WSL launcher. WSL is a different machine with a different PATH: Windows Python
    is invisible inside it, so probing there reports a catastrophic failure that does
    not exist. Derive Git Bash from the git installation, which Claude Code requires
    on Windows anyway.
    """
    if os.name != "nt":
        return shutil.which("bash") or shutil.which("sh")

    try:
        exec_path = subprocess.run(["git", "--exec-path"], capture_output=True,
                                   text=True, timeout=10)
        if exec_path.returncode == 0 and exec_path.stdout.strip():
            # .../Git/mingw64/libexec/git-core -> .../Git/bin/bash.exe
            git_core = Path(exec_path.stdout.strip().replace("/", os.sep))
            for parent in git_core.parents:
                candidate = parent / "bin" / "bash.exe"
                if candidate.is_file():
                    return str(candidate)
    except (OSError, subprocess.SubprocessError):
        pass

    for candidate in (r"C:\Program Files\Git\bin\bash.exe",
                      r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.isfile(candidate):
            return candidate

    found = shutil.which("bash")
    if found and "system32" in found.lower():
        return None  # WSL only; probing it would report a failure that isn't real
    return found


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


def iter_hook_commands():
    """Yield (script_basename, command_string) for every command in hooks.json."""
    manifest = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    for event, matchers in manifest.get("hooks", {}).items():
        for matcher in matchers:
            for hook in matcher.get("hooks", []):
                command = hook.get("command", "")
                found = re.search(r"([A-Za-z0-9_]+\.py)", command)
                yield event, (found.group(1) if found else "?"), command


def run_via_shell(bash, command, payload, project):
    """Run a hook command through bash exactly as Claude Code would."""
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    result = subprocess.run(
        [bash, "-c", command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    if _verbose:
        print(f"    rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}")
    return result


def launch_failed(result):
    """True when the shell could not start the interpreter at all.

    127 is the shell's 'command not found'. The message check catches the subtler
    variant where a bare script path is handed to bash, which then tries to run
    Python source as shell script -- the failure mode that makes a bare-invocation
    manifest worse than a broken one.
    """
    if result.returncode == 127:
        return True
    markers = ("command not found", "No such file or directory", "syntax error near")
    return any(m in result.stderr for m in markers)


def main():
    print("decisions-md hook launch harness")
    print(f"Plugin root: {PLUGIN_ROOT}")

    bash = find_shell()
    if not bash:
        print("\nSKIP: could not find the shell Claude Code launches hooks with. "
              "On Windows, install Git for Windows (Claude Code requires it).")
        return 0
    print(f"Shell: {bash}")

    print("\n[0] Interpreters visible to the shell")
    for name in ("python3", "python", "py"):
        probe = subprocess.run([bash, "-c", f"command -v {name}"],
                               capture_output=True, text=True)
        found = probe.returncode == 0 and probe.stdout.strip()
        print(f"    {'found  ' if found else 'absent '} {name}"
              f"{': ' + probe.stdout.strip() if found else ''}")
    resolver = subprocess.run(
        [bash, "-c", "command -v python3 || command -v python || command -v py"],
        capture_output=True, text=True)
    if not (resolver.returncode == 0 and resolver.stdout.strip()):
        # Nothing below can mean anything if no interpreter resolves, and this is
        # itself the exact defect the test exists to catch. Report it and stop.
        check("some Python 3 resolves for the manifest's resolver", False,
              "none of python3/python/py are on PATH in this shell; every hook "
              "would fail to launch")
        print(f"\n{'='*50}")
        print(f"Results: {_passes} passed, {_failures} failed")
        return 1
    check("some Python 3 resolves for the manifest's resolver", True)
    print(f"    resolver picks: {resolver.stdout.strip().splitlines()[0]}")

    with tempfile.TemporaryDirectory(prefix="decisions_md_launch_") as tmp:
        project = Path(tmp) / "project"
        project.mkdir()
        (project / "DECISIONS.md").write_text(DECISIONS_MD, encoding="utf-8")
        (project / "main.gd").write_text("# godot source", encoding="utf-8")

        gate_payload = {
            "session_id": SESSION_ID,
            "tool_name": "Write",
            "tool_input": {"file_path": str(project / "main.gd")},
        }
        payloads = {
            "decisions_session_start.py": {"session_id": SESSION_ID},
            "decisions_gate.py": gate_payload,
            "decisions_check.py": gate_payload,
        }

        # Every command in the manifest must at minimum START.
        print("\n[1] Every hook command in hooks.json launches")
        for event, script, command in iter_hook_commands():
            result = run_via_shell(bash, command, payloads.get(script, {}), project)
            check(f"{event}: {script} launches",
                  not launch_failed(result),
                  f"rc={result.returncode} stderr={result.stderr.strip()[:400]}")

        # The two behaviours that matter most, driven through the shell.
        print("\n[2] SessionStart writes the session marker through the shell")
        session_cmd = next(c for _, s, c in iter_hook_commands()
                           if s == "decisions_session_start.py")
        run_via_shell(bash, session_cmd, {"session_id": SESSION_ID}, project)
        sid_file = project / ".decisions" / "cache" / "current-session-id"
        check("session_start: wrote current-session-id", sid_file.exists())
        if sid_file.exists():
            check("session_start: id matches the payload",
                  sid_file.read_text(encoding="utf-8").strip() == SESSION_ID)

        print("\n[3] Gate still blocks with exit 2 through the shell")
        # Exit-code fidelity is the point: a gate that fails to block is worse than one
        # that errors, and a shell wrapper is exactly the kind of thing that eats a 2.
        gate_cmd = next(c for _, s, c in iter_hook_commands() if s == "decisions_gate.py")
        marker = project / ".decisions" / "cache" / f"decisions-checked-{SESSION_ID}"
        if marker.exists():
            marker.unlink()
        result = run_via_shell(bash, gate_cmd, gate_payload, project)
        check("gate: exits 2 (blocks)", result.returncode == 2,
              f"rc={result.returncode} stderr={result.stderr.strip()[:400]}")
        check("gate: block message survives on stderr",
              "DECISIONS GATE" in result.stderr)

        print("\n[4] Gate allows once unlocked, through the shell")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        result = run_via_shell(bash, gate_cmd, gate_payload, project)
        check("gate: exits 0 after unlock", result.returncode == 0,
              f"rc={result.returncode} stderr={result.stderr.strip()[:400]}")

    print(f"\n{'='*50}")
    print(f"Results: {_passes} passed, {_failures} failed")
    return 0 if _failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
