#!/usr/bin/env python3
"""Synthetic-payload harness for the decisions-md plugin.

Creates throwaway projects, drives each hook with crafted JSON payloads, and asserts
the behaviour -- no live Claude Code session needed. State is redirected to a temp
directory via DECISIONS_STATE_DIR, so a run cannot touch your real state.

    python3 tests/verify_plugin.py         run all checks
    python3 tests/verify_plugin.py -v      show every subprocess result

Exit 0 = all checks passed. Exit 1 = at least one failed.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent.resolve()
HOOKS_DIR = PLUGIN_ROOT / "hooks"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"

sys.path.insert(0, str(HOOKS_DIR))
from decisions_common import get_state_dir  # noqa: E402  (path set above)


def _configure_utf8_output():
    """Windows defaults a redirected stream to cp1252, which cannot encode the section
    headers below -- the harness used to die mid-run rather than report a result."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            continue


_configure_utf8_output()

DECISIONS_MD = """\
DEC-INPUT-001: Jumping is bound to the A button.
Context: Face buttons are reserved for actions used under pressure.

DEC-INPUT-002: Holding the jump button does not increase jump height.

DEC-RENDER-001: The game renders at a fixed internal resolution and scales up.
"""

SESSION_ID = "test-session-abc123"
STATE_ROOT = None  # set in main()

_passes = 0
_failures = 0
_verbose = "-v" in sys.argv


def _log(msg):
    if _verbose:
        print("    %s" % msg, flush=True)


def check(name, condition, detail=""):
    global _passes, _failures
    if condition:
        print("  PASS  %s" % name, flush=True)
        _passes += 1
    else:
        print("  FAIL  %s" % name, flush=True)
        if detail:
            print("        %s" % str(detail)[:800], flush=True)
        _failures += 1


def _env(project, session_id=None, extra=None):
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        "CLAUDE_PROJECT_DIR": str(project),
        "DECISIONS_STATE_DIR": str(STATE_ROOT),
    }
    if session_id:
        env["DECISIONS_SESSION_ID"] = session_id
    if extra:
        env.update(extra)
    return env


def run_hook(hook_file, payload, env):
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / hook_file)],
        input=json.dumps(payload), capture_output=True, text=True, env=env,
    )
    _log("%s rc=%s out=%r err=%r" % (hook_file, result.returncode, result.stdout, result.stderr))
    return result.returncode, result.stdout, result.stderr


def run_cli(args, env):
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "query_decisions.py")] + args,
        capture_output=True, text=True, env=env,
    )
    _log("cli %s rc=%s out=%r" % (args, result.returncode, result.stdout))
    return result.returncode, result.stdout, result.stderr


def setup_project(tmp, decisions=DECISIONS_MD, config=None, tree=("main.gd",)):
    project = Path(tempfile.mkdtemp(dir=tmp))
    if decisions is not None:
        (project / "DECISIONS.md").write_text(decisions, encoding="utf-8")
    if config is not None:
        (project / ".decisions").mkdir()
        (project / ".decisions" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    for rel in tree:
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# source", encoding="utf-8")
    return project


def write_payload(project, rel, session_id=SESSION_ID, tool="Write"):
    return {"tool_name": tool, "tool_input": {"file_path": str(project / rel)},
            "session_id": session_id}


def start_session(project, session_id=SESSION_ID):
    """Drive SessionStart the way Claude Code would, so state exists."""
    return run_hook("decisions_session_start.py", {"session_id": session_id},
                    _env(project, session_id))


def _session_dir(project, session_id=SESSION_ID):
    """This project's session state dir -- resolved the way the plugin resolves it.

    Globbing the state root instead would pick up whichever earlier test project
    happened to sort first and quietly assert against the wrong one.
    """
    os.environ["DECISIONS_STATE_DIR"] = str(STATE_ROOT)
    return Path(get_state_dir(str(project))) / ("s-" + session_id)


def pending_edits(project, session_id=SESSION_ID):
    d = _session_dir(project, session_id) / "pending"
    if not d.is_dir():
        return []
    return sorted(p.read_text(encoding="utf-8").strip() for p in d.iterdir())


def served_areas(project, session_id=SESSION_ID):
    d = _session_dir(project, session_id) / "served"
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


def project_polluted(project):
    """Anything the plugin should never create inside a consuming project."""
    stray = []
    if (project / ".decisions" / "cache").exists():
        stray.append(".decisions/cache")
    if (project / "logs").exists():
        stray.append("logs/")
    return stray


# ── 1. Manifest ───────────────────────────────────────────────────────────────

def test_manifest(tmp):
    print("\n[1] Manifest")
    pj = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
    mj = json.loads((PLUGIN_ROOT / ".claude-plugin" / "marketplace.json").read_text())
    check("plugin.json: name", pj.get("name") == "decisions-md")
    check("plugin.json: license MIT", pj.get("license") == "MIT")
    check("versions agree", pj.get("version") == mj["plugins"][0].get("version"),
          "%s vs %s" % (pj.get("version"), mj["plugins"][0].get("version")))

    hooks = json.loads((HOOKS_DIR / "hooks.json").read_text()).get("hooks", {})
    for event in ("SessionStart", "PreToolUse", "PostToolUse", "PreCompact", "Stop"):
        check("hooks.json declares %s" % event, event in hooks)
    check("hooks.json no longer runs on every prompt", "UserPromptSubmit" not in hooks)

    referenced = []
    for entries in hooks.values():
        for entry in entries:
            for h in entry.get("hooks", []):
                referenced.append(h["command"].split("hooks/")[-1].rstrip('"'))
    missing = [r for r in referenced if not (HOOKS_DIR / r).exists()]
    check("every hook script referenced exists", not missing, missing)

    on_disk = {p.name for p in HOOKS_DIR.glob("decisions_*.py")} - {"decisions_common.py"}
    check("no orphan hook scripts on disk", on_disk == set(referenced),
          "on disk=%s referenced=%s" % (sorted(on_disk), sorted(referenced)))


# ── 2. No DECISIONS.md → the plugin does nothing, anywhere ────────────────────

def test_portability(tmp):
    print("\n[2] Portability — project without DECISIONS.md")
    project = setup_project(tmp, decisions=None)
    env = _env(project, SESSION_ID)

    rc, out, err = run_hook("decisions_serve.py", write_payload(project, "main.gd"), env)
    check("serve: exits 0", rc == 0)
    check("serve: says nothing", not out.strip() and not err.strip())

    rc, out, _ = run_hook("decisions_session_start.py", {"session_id": SESSION_ID}, env)
    check("session_start: exits 0", rc == 0)
    check("session_start: injects nothing", not out.strip())

    rc, out, _ = run_hook("decisions_check.py", write_payload(project, "main.gd"), env)
    check("check: exits 0", rc == 0)
    rc, out, _ = run_hook("decisions_stop_check.py", {"session_id": SESSION_ID}, env)
    check("stop: exits 0 and says nothing", rc == 0 and not out.strip())

    check("nothing created inside the project", not project_polluted(project),
          project_polluted(project))


# ── 3. State never lands in the project ───────────────────────────────────────

def test_state_location(tmp):
    print("\n[3] State location")
    project = setup_project(tmp)
    env = _env(project, SESSION_ID)

    start_session(project)
    run_hook("decisions_serve.py", write_payload(project, "main.gd"), env)
    run_hook("decisions_check.py", write_payload(project, "main.gd"), env)
    run_cli(["--query", "jump"], env)

    check("no .decisions/cache in the project", not (project / ".decisions" / "cache").exists())
    check("no logs/ in the project", not (project / "logs").exists())
    check("nothing written into the plugin dir",
          not (PLUGIN_ROOT / ".decisions").exists())

    keys = list(Path(STATE_ROOT).glob("*/current-session-id"))
    check("session id persisted outside the project", len(keys) >= 1)


# ── 4. SessionStart ───────────────────────────────────────────────────────────

def test_session_start(tmp):
    print("\n[4] SessionStart")
    project = setup_project(tmp)
    rc, out, _ = start_session(project)
    check("exits 0", rc == 0)
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    check("injects the orientation block", "[DECISIONS]" in ctx)
    check("orientation states the count", "3 decisions" in ctx, ctx)
    check("orientation names the areas", "input:2" in ctx and "render:1" in ctx, ctx)

    # A second start resets what the previous session had served.
    env = _env(project, SESSION_ID)
    run_hook("decisions_serve.py", write_payload(project, "main.gd"), env)
    start_session(project)
    rc, _, err = run_hook("decisions_serve.py", write_payload(project, "input_handler.gd"), env)
    check("resets served areas on a new session", rc == 2, err)


# ── 5. Serving decisions ──────────────────────────────────────────────────────

def test_serve(tmp):
    print("\n[5] Serve — relevant decisions, once per area")
    project = setup_project(tmp, tree=("input_handler.gd", "render_pass.gd", "audio_bus.gd"))
    env = _env(project, SESSION_ID)
    start_session(project)

    rc, out, err = run_hook("decisions_serve.py", write_payload(project, "input_handler.gd"), env)
    check("blocks once to deliver (exit 2)", rc == 2, err)
    check("delivers on stderr, not stdout", "[DECISIONS]" in err and "[DECISIONS]" not in out)
    check("serves the matching area", "DEC-INPUT-001" in err and "DEC-INPUT-002" in err, err)
    check("does not serve unrelated areas", "DEC-RENDER-001" not in err, err)
    check("tells the model what to do next", "re-run your edit" in err.lower(), err)
    check("statement only, no Context noise", "Face buttons are reserved" not in err, err)

    rc, out, err = run_hook("decisions_serve.py", write_payload(project, "input_handler.gd"), env)
    check("silent on the second edit in the same area", rc == 0 and not err.strip(), err)

    rc, out, err = run_hook("decisions_serve.py", write_payload(project, "render_pass.gd"), env)
    check("serves a different area when you move to it", rc == 2 and "DEC-RENDER-001" in err, err)

    rc, out, err = run_hook("decisions_serve.py", write_payload(project, "audio_bus.gd"), env)
    check("silent for a path no decision covers", rc == 0 and not err.strip(), err)


def test_serve_scope(tmp):
    print("\n[6] Serve — what it leaves alone")
    project = setup_project(tmp, tree=("input_handler.gd", "notes.txt", "tools/input_build.py",
                                       "src/tools/input_thing.py", ".claude/input_hook.py"))
    env = _env(project, SESSION_ID)
    start_session(project)

    rc, _, _ = run_hook("decisions_serve.py", write_payload(project, "DECISIONS.md"), env)
    check("DECISIONS.md itself", rc == 0)
    rc, _, _ = run_hook("decisions_serve.py", write_payload(project, "notes.txt"), env)
    check("untracked extension", rc == 0)
    rc, _, _ = run_hook("decisions_serve.py", write_payload(project, "tools/input_build.py"), env)
    check("exempt prefix tools/", rc == 0)
    # A dot-prefixed default exemption: a naive lstrip("./") would turn ".claude/"
    # into "claude/" and stop exempting this at all.
    rc, _, _ = run_hook("decisions_serve.py", write_payload(project, ".claude/input_hook.py"), env)
    check("exempt prefix .claude/ keeps its leading dot", rc == 0)

    # The old substring match exempted anything with "tools/" ANYWHERE in the path.
    rc, _, err = run_hook("decisions_serve.py", write_payload(project, "src/tools/input_thing.py"), env)
    check("src/tools/ is NOT exempt (prefix match, not substring)", rc == 2, err)

    outside = Path(tempfile.mkdtemp(dir=tmp)) / "input_other.gd"
    outside.write_text("# another repo", encoding="utf-8")
    rc, _, _ = run_hook("decisions_serve.py",
                        {"tool_name": "Write", "tool_input": {"file_path": str(outside)},
                         "session_id": SESSION_ID}, env)
    check("a file outside the project root", rc == 0)


def test_serve_config(tmp):
    print("\n[7] Serve — config")
    project = setup_project(tmp, config={"tracked_extensions": [".xyz"]},
                            tree=("input_handler.gd", "input_data.xyz"))
    env = _env(project, SESSION_ID)
    start_session(project)
    rc, _, _ = run_hook("decisions_serve.py", write_payload(project, "input_handler.gd"), env)
    check("custom tracked_extensions drops .gd", rc == 0)
    rc, _, err = run_hook("decisions_serve.py", write_payload(project, "input_data.xyz"), env)
    check("custom tracked_extensions adds .xyz", rc == 2, err)

    # area_map pins a path whose name says nothing about its area.
    project = setup_project(tmp, config={"area_map": {"gfx/**": "render"}},
                            tree=("gfx/pipeline.gd",))
    env = _env(project, SESSION_ID + "-map")
    start_session(project, SESSION_ID + "-map")
    rc, _, err = run_hook("decisions_serve.py",
                          write_payload(project, "gfx/pipeline.gd", SESSION_ID + "-map"), env)
    check("area_map routes an unguessable path", rc == 2 and "DEC-RENDER-001" in err, err)

    project = setup_project(tmp, config={"enabled": False}, tree=("input_handler.gd",))
    env = _env(project, SESSION_ID + "-off")
    rc, out, _ = run_hook("decisions_session_start.py",
                          {"session_id": SESSION_ID + "-off"}, env)
    check("enabled:false silences SessionStart", rc == 0 and not out.strip())
    rc, _, err = run_hook("decisions_serve.py",
                          write_payload(project, "input_handler.gd", SESSION_ID + "-off"), env)
    check("enabled:false silences the serve hook", rc == 0 and not err.strip(), err)
    rc, out, _ = run_hook("decisions_stop_check.py", {"session_id": SESSION_ID + "-off"}, env)
    check("enabled:false silences the Stop check", rc == 0 and not out.strip())


# ── 8. PostToolUse ────────────────────────────────────────────────────────────

def test_check(tmp):
    print("\n[8] PostToolUse check")
    project = setup_project(tmp, tree=("input_handler.gd",))
    env = _env(project, SESSION_ID)
    start_session(project)

    rc, _, _ = run_hook("decisions_check.py", write_payload(project, "input_handler.gd"), env)
    check("exits 0", rc == 0)
    check("records the edit", pending_edits(project) == ["input_handler.gd"],
          pending_edits(project))

    rc, _, _ = run_hook("decisions_check.py", write_payload(project, "notes.txt"), env)
    check("ignores untracked files", pending_edits(project) == ["input_handler.gd"],
          pending_edits(project))

    bad = project / "DECISIONS.md"
    bad.write_text("DEC-INPUT-001: A rule.\nStatus: Active (2026-01-01)\n", encoding="utf-8")
    rc, out, _ = run_hook("decisions_check.py", write_payload(project, "DECISIONS.md"), env)
    check("lints DECISIONS.md when it is written", "format errors" in out, out)
    check("names the Status line as the problem", "Status" in out, out)


# ── 9. Stop check ─────────────────────────────────────────────────────────────

def test_stop(tmp):
    print("\n[9] Stop check")
    project = setup_project(tmp, tree=("input_handler.gd", "audio_bus.gd"))
    env = _env(project, SESSION_ID)
    start_session(project)

    # Edits inside a covered area: the rules already exist, so stay quiet.
    run_hook("decisions_check.py", write_payload(project, "input_handler.gd"), env)
    rc, out, _ = run_hook("decisions_stop_check.py", {"session_id": SESSION_ID}, env)
    check("silent when the edited area already has decisions", rc == 0 and not out.strip(), out)

    # Edits where nothing is on file: worth asking about, once.
    run_hook("decisions_check.py", write_payload(project, "audio_bus.gd"), env)
    rc, out, _ = run_hook("decisions_stop_check.py", {"session_id": SESSION_ID}, env)
    data = json.loads(out) if out.strip() else {}
    reason = data.get("hookSpecificOutput", {}).get("reason", "")
    check("blocks once for uncovered work",
          data.get("hookSpecificOutput", {}).get("decision") == "block", out)
    check("default answer is 'no entry needed'", "no entry is needed" in reason.lower(), reason)
    check("names the uncovered file", "audio_bus.gd" in reason, reason)

    run_hook("decisions_check.py", write_payload(project, "audio_bus.gd"), env)
    rc, out, _ = run_hook("decisions_stop_check.py", {"session_id": SESSION_ID}, env)
    check("fires at most once per session", not out.strip(), out)

    rc, out, _ = run_hook("decisions_stop_check.py",
                          {"session_id": SESSION_ID, "stop_hook_active": True}, env)
    check("no-op when stop_hook_active", not out.strip(), out)


# ── 10. Lint ──────────────────────────────────────────────────────────────────

LEGACY_MD = """\
DEC-INPUT-007: Jumping is bound to the A button.
Status: Active (2026-01-01)

DEC-INPUT-007d: OVERRIDES the binding clause of DEC-INPUT-007. Jumping is bound to B.
Status: Active (overrides DEC-INPUT-007 binding clause)

DEC-INPUT-007: A duplicate ID.
Status: Retired (2026-02-02)
"""

BLOATED_MD = """\
DEC-UI-001: The pause menu opens with Start and closes with Start or B.

DEC-UI-002: The pause menu opens with the Start button and closes with Start or B.

DEC-UI-003: The inventory grid is eight columns wide and the player_inventory_grid()
call refreshes it whenever an item is added, removed, moved, dropped, equipped,
unequipped, split, merged, sorted, filtered, favourited, marked, unmarked, compared,
previewed, repaired, upgraded, dismantled, or otherwise touched by any subsystem at
all in any circumstance whatsoever including during a save or load operation.
Context: One.
Context: Two.
Context: Three.
Context: Four.
Context: Five.
"""


def test_lint(tmp):
    print("\n[10] Lint")
    project = setup_project(tmp, decisions=LEGACY_MD)
    env = _env(project, SESSION_ID)

    rc, out, _ = run_cli(["--lint"], env)
    check("legacy file fails (exit 1)", rc == 1, out)
    check("flags Status lines", "Status:" in out and "no longer part of the format" in out, out)
    check("flags the override-suffix ID", "DEC-INPUT-007d" in out and "retired" in out, out)
    check("flags the duplicate ID", "duplicate ID" in out, out)

    rc, out, _ = run_cli(["--lint", "--write"], env)
    check("--write removes the plain Status lines", "Removed 1 plain" in out, out)
    check("--write leaves the ones carrying prose", "Left 2" in out, out)
    remaining = (project / "DECISIONS.md").read_text(encoding="utf-8")
    id_lines = [l for l in remaining.split("\n") if l.startswith("DEC-INPUT-007")]
    check("--write kept every decision", len(id_lines) == 3, remaining)

    project = setup_project(tmp, decisions=BLOATED_MD)
    env = _env(project, SESSION_ID)
    rc, out, _ = run_cli(["--lint"], env)
    check("bloat is a warning, not an error (exit 0)", rc == 0, out)
    check("warns about a near-duplicate", "nearly the same thing" in out, out)
    check("warns about an oversized entry", "design document" in out, out)
    check("warns about code names in a statement", "code identifier" in out or
          "function call" in out, out)

    project = setup_project(tmp)
    rc, out, _ = run_cli(["--lint"], _env(project, SESSION_ID))
    check("a clean file passes", rc == 0 and "Clean" in out, out)


# ── 11. CLI read paths ────────────────────────────────────────────────────────

def test_cli(tmp):
    print("\n[11] CLI")
    project = setup_project(tmp)
    env = _env(project, SESSION_ID)
    start_session(project)

    rc, out, _ = run_cli([], env)
    check("no args lists areas and counts", rc == 0 and "input" in out and "2" in out, out)

    rc, out, _ = run_cli(["--query", "jump", "button"], env)
    check("multi-word query works", rc == 0 and "DEC-INPUT-001" in out, out)
    check("query shows the reasoning", "Face buttons are reserved" in out, out)

    rc, out, _ = run_cli(["--query", "quixotic", "flibbertigibbet"], env)
    check("a miss does NOT dump the whole file", "DEC-INPUT-001" not in out, out)
    check("a miss offers the area list instead", "Decision areas" in out, out)

    rc, out, _ = run_cli(["--area", "render"], env)
    check("--area filters", "DEC-RENDER-001" in out and "DEC-INPUT-001" not in out, out)

    rc, out, _ = run_cli(["--area", "nosucharea"], env)
    check("unknown area is explained, not dumped", "Unknown area" in out
          and "DEC-INPUT-001" not in out, out)

    # A manual read should stop the serve hook repeating that area.
    rc, _, err = run_hook("decisions_serve.py", write_payload(project, "render_pass.gd"), env)
    check("CLI read marks the area as seen", rc == 0 and not err.strip(), err)

    rc, out, _ = run_cli(["--doctor"], env)
    check("doctor exits 0 when healthy", rc == 0, out)
    check("doctor reports the state dir", "state dir writable" in out, out)
    check("doctor confirms hooks have run", "SessionStart hook has run" in out
          and "FAIL  SessionStart" not in out, out)

    rc, out, _ = run_cli(["--write"], env)
    check("--write without --lint is refused", rc == 2, out)


# ── 12. A big file stays bounded ──────────────────────────────────────────────

def test_bounded_output(tmp):
    print("\n[12] Bounded output")
    big = "\n\n".join("DEC-INPUT-%03d: Input rule number %d." % (i, i) for i in range(1, 41))
    project = setup_project(tmp, decisions=big, tree=("input_handler.gd",))
    env = _env(project, SESSION_ID)
    start_session(project)

    rc, _, err = run_hook("decisions_serve.py", write_payload(project, "input_handler.gd"), env)
    served = [l for l in err.split("\n") if l.startswith("DEC-")]
    check("serve caps how much it prints", len(served) <= 15, len(served))
    check("serve says how much it withheld", "more in this area" in err, err)

    rc, out, _ = run_cli(["--area", "input"], env)
    shown = [l for l in out.split("\n") if l.startswith("DEC-")]
    check("CLI caps a large area", len(shown) <= 12, len(shown))
    check("CLI says how much it withheld", "not shown" in out, out)


# ── 13. Concurrency ───────────────────────────────────────────────────────────

def _run_parallel(hook, payloads, env, workers=20):
    """Fire N hook processes at once, the way parallel tool calls do."""
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_hook, hook, p, env) for p in payloads]
        for f in futures:
            results.append(f.result())
    return results


def test_concurrency(tmp):
    print("\n[13] Concurrency — parallel tool calls")
    names = ["input_file_%02d.gd" % i for i in range(20)]
    project = setup_project(tmp, tree=tuple(names))
    env = _env(project, SESSION_ID)
    start_session(project)

    # Every parallel edit must be recorded. A shared read-modify-write JSON kept 8/20.
    _run_parallel("decisions_check.py", [write_payload(project, n) for n in names], env)
    recorded = pending_edits(project)
    check("all 20 parallel edits recorded", len(recorded) == 20,
          "%d of 20: %s" % (len(recorded), recorded[:5]))

    # Exactly one of N racing serve hooks may block; the rest must let the edit past,
    # or the same decisions get printed several times over for one area.
    project2 = setup_project(tmp, tree=tuple(names))
    env2 = _env(project2, SESSION_ID)
    start_session(project2)
    results = _run_parallel(
        "decisions_serve.py", [write_payload(project2, n) for n in names], env2)
    blocked = [r for r in results if r[0] == 2]
    check("exactly one of 20 racing serves blocks", len(blocked) == 1,
          "%d blocked" % len(blocked))
    check("the one block still carries the decisions",
          bool(blocked) and "DEC-INPUT-001" in blocked[0][2], blocked[:1])
    check("area recorded as served exactly once", served_areas(project2) == ["input"],
          served_areas(project2))


# ── 14. Damaged and hostile files ─────────────────────────────────────────────

def test_damaged_files(tmp):
    print("\n[14] Damaged DECISIONS.md")

    # A file saved in the Windows system codepage is not valid UTF-8. Every hook used
    # to die with a traceback on every edit.
    project = setup_project(tmp, decisions=None, tree=("input_handler.gd",))
    (project / "DECISIONS.md").write_bytes(
        "DEC-INPUT-001: Café curtains are red.\n".encode("cp1252"))
    env = _env(project, SESSION_ID)
    start_session(project)
    for hook, payload in (("decisions_serve.py", write_payload(project, "input_handler.gd")),
                          ("decisions_check.py", write_payload(project, "input_handler.gd")),
                          ("decisions_stop_check.py", {"session_id": SESSION_ID}),
                          ("decisions_precompact.py", {})):
        rc, _, err = run_hook(hook, payload, env)
        check("%s survives a non-UTF-8 file" % hook, "Traceback" not in err, err[:200])
    rc, out, _ = run_cli(["--lint"], env)
    check("lint names the encoding problem", "not valid UTF-8" in out, out)
    rc, out, _ = run_cli(["--lint", "--write"], env)
    check("--write refuses to rewrite a file it could not decode",
          "Removed 0 plain" in out, out)

    # A stray carriage return mid-line is not a line break; reported line numbers must
    # still match what the user's editor shows.
    project = setup_project(tmp, decisions=None)
    (project / "DECISIONS.md").write_bytes(
        b"DEC-A-001: One.\nDEC-A-002: Two \r with a stray CR.\nStatus: Active\n")
    rc, out, _ = run_cli(["--lint"], _env(project, SESSION_ID))
    check("line number ignores a stray CR", "line 3:" in out, out)


def test_stop_check_signal(tmp):
    print("\n[15] Stop check uses this session's own edit, not git state")
    project = setup_project(tmp, tree=("audio_bus.gd",))
    env = _env(project, SESSION_ID)
    start_session(project)

    run_hook("decisions_check.py", write_payload(project, "audio_bus.gd"), env)
    # Writing DECISIONS.md this session is what cancels the check.
    run_hook("decisions_check.py", write_payload(project, "DECISIONS.md"), env)
    rc, out, _ = run_hook("decisions_stop_check.py", {"session_id": SESSION_ID}, env)
    check("silent once DECISIONS.md was written this session", not out.strip(), out)

    # An unrelated file merely named decisions.md is governed like anything else.
    # (Not under vendor/ — that is exempt by default, which would mask the point.)
    project = setup_project(tmp, tree=("game/dep/input_thing.gd",))
    env = _env(project, SESSION_ID + "-v")
    start_session(project, SESSION_ID + "-v")
    (project / "game" / "dep" / "decisions.md").write_text("not the real one", encoding="utf-8")
    rc, _, err = run_hook("decisions_serve.py",
                          write_payload(project, "game/dep/input_thing.gd",
                                        SESSION_ID + "-v"), env)
    check("a stray decisions.md does not exempt its neighbours", rc == 2, err[:200])

    # Vendored trees are exempt by default -- they are not your design surface.
    project = setup_project(tmp, tree=("addons/thing/input_helper.gd",))
    env = _env(project, SESSION_ID + "-a")
    start_session(project, SESSION_ID + "-a")
    rc, _, err = run_hook("decisions_serve.py",
                          write_payload(project, "addons/thing/input_helper.gd",
                                        SESSION_ID + "-a"), env)
    check("addons/ is exempt by default", rc == 0, err[:200])


# ── 16. Inputs that used to hang or vanish ────────────────────────────────────

def test_pathological(tmp):
    print("\n[16] Pathological input — must stay fast and visible")

    # The lint runs on every write to DECISIONS.md, inside a 5s hook timeout.
    big = "\n\n".join("DEC-AREA%d-%03d: Rule number %d about thing %d."
                      % (i % 7, i, i, i) for i in range(3000))
    project = setup_project(tmp, decisions=big)
    env = _env(project, SESSION_ID)
    started = time.time()
    rc, out, _ = run_cli(["--lint"], env)
    elapsed = time.time() - started
    check("3000 decisions lint in under 5s", elapsed < 5.0, "took %.1fs" % elapsed)

    # The shape that survived the first fix: many areas, each just under the per-area
    # cap, with statements as long as real ones get.
    many = "\n\n".join(
        "DEC-AREA%02d-%03d: %s" % (a, i, " ".join("word%d" % (i * 7 + w) for w in range(100)))
        for a in range(40) for i in range(250))
    project = setup_project(tmp, decisions=many)
    started = time.time()
    rc, out, _ = run_cli(["--lint"], _env(project, SESSION_ID))
    elapsed = time.time() - started
    check("40 verbose areas lint in under 5s", elapsed < 5.0, "took %.1fs" % elapsed)

    # One entry, ~20KB of "a.a.a...", used to backtrack for minutes.
    project = setup_project(tmp, decisions="DEC-BAIT-001: " + ("a." * 10000) + "zzz\n")
    started = time.time()
    rc, out, _ = run_cli(["--lint"], _env(project, SESSION_ID))
    elapsed = time.time() - started
    check("a 20KB dotted statement lints in under 5s", elapsed < 5.0, "took %.1fs" % elapsed)

    # An ID that does not parse must be reported, never silently dropped.
    for bad in ("dec-input-001", "DEC--001", "DEC-999-001"):
        project = setup_project(tmp, decisions="%s: Something binding.\n" % bad)
        rc, out, _ = run_cli(["--lint"], _env(project, SESSION_ID))
        check("`%s` is reported, not silently ignored" % bad,
              rc == 1 and "does not parse" in out, out[:200])

    # An example inside a code fence is documentation, not a binding decision.
    project = setup_project(tmp, decisions=(
        "# How to write one\n\n```\nDEC-CODE-001: An example, not a rule.\n```\n\n"
        "DEC-INPUT-001: A real rule.\n"))
    rc, out, _ = run_cli([], _env(project, SESSION_ID))
    check("a fenced example is not counted as a decision",
          "code" not in out and "input" in out, out)

    # A tilde fence is a fence too.
    project = setup_project(tmp, decisions=(
        "~~~\nDEC-CODE-001: An example.\n~~~\n\nDEC-INPUT-001: A real rule.\n"))
    rc, out, _ = run_cli([], _env(project, SESSION_ID))
    check("a tilde fence hides its example too", "code" not in out and "input" in out, out)

    # A longer fence wrapping a shorter one must not end at the inner marker.
    project = setup_project(tmp, decisions=(
        "````\n```\nDEC-CODE-999: Doubly fenced, still an example.\n```\n````\n\n"
        "DEC-INPUT-001: A real rule.\n"))
    rc, out, _ = run_cli([], _env(project, SESSION_ID))
    check("a nested fence does not leak its example",
          "code" not in out and "input" in out, out)

    # A blank line closes an open field. Prose that follows -- a markdown heading
    # grouping the next entries, a note between them -- belongs to the file, not to the
    # decision above it. It used to be appended to the last field's value, so it printed
    # as part of the entry and fed the area matcher words nobody wrote into the rule.
    project = setup_project(tmp, decisions=(
        "DEC-COMBAT-001: Damage is a whole number.\n"
        "Context: Cards multiply these values.\n\n"
        "## Netcode\n\n"
        "DEC-NETCODE-001: The host resolves ties.\n"))
    rc, out, _ = run_cli(["--area", "combat"], _env(project, SESSION_ID))
    check("a heading after a Context line does not join the field",
          "Netcode" not in out and "Cards multiply" in out, out)
    rc, out, _ = run_cli(["--query", "netcode"], _env(project, SESSION_ID))
    check("that heading does not make the combat entry match on its words",
          "DEC-COMBAT-001" not in out, out)

    # A wrapped field, unbroken by a blank line, is still one value.
    project = setup_project(tmp, decisions=(
        "DEC-COMBAT-001: Damage is a whole number.\n"
        "Context: Cards multiply these values,\n"
        "so a fraction drifts from the shown total.\n"))
    rc, out, _ = run_cli(["--area", "combat"], _env(project, SESSION_ID))
    check("a field still wraps onto the next line",
          "drifts from the shown total" in out, out)

    # An unclosed fence must never silently swallow the decisions after it.
    project = setup_project(tmp, decisions=(
        "```\nDEC-CODE-001: Example.\n\nDEC-INPUT-001: A real rule that must survive.\n"))
    env = _env(project, SESSION_ID)
    rc, out, _ = run_cli(["--lint"], env)
    check("an unclosed fence is an error, not silence",
          rc == 1 and "never closed" in out, out)
    rc, out, _ = run_cli([], env)
    check("decisions after an unclosed fence still parse", "input" in out, out)

    # A mistyped tracked_extensions must not silently disable the plugin.
    project = setup_project(tmp, config={"tracked_extensions": [[".gd"], 7]},
                            tree=("input_handler.gd",))
    env = _env(project, SESSION_ID + "-cfg2")
    start_session(project, SESSION_ID + "-cfg2")
    rc, _, err = run_hook("decisions_serve.py",
                          write_payload(project, "input_handler.gd", SESSION_ID + "-cfg2"), env)
    check("a mistyped tracked_extensions falls back to defaults", rc == 2, err[:200])

    # A malformed payload must not produce a traceback.
    project = setup_project(tmp, tree=("input_handler.gd",))
    env = _env(project, SESSION_ID)
    for bad_input in ({"file_path": ["a", "b"]}, {"file_path": None}, "notadict"):
        for hook in ("decisions_serve.py", "decisions_check.py"):
            rc, _, err = run_hook(hook, {"tool_name": "Write", "tool_input": bad_input,
                                         "session_id": SESSION_ID}, env)
            check("%s survives file_path=%r" % (hook, bad_input),
                  "Traceback" not in err, err[:200])


def main():
    global STATE_ROOT
    print("decisions-md plugin harness")
    print("Plugin root: %s" % PLUGIN_ROOT)
    with tempfile.TemporaryDirectory(prefix="decisions_md_test_") as tmp:
        STATE_ROOT = Path(tmp) / "_state"
        STATE_ROOT.mkdir()
        for fn in (test_manifest, test_portability, test_state_location, test_session_start,
                   test_serve, test_serve_scope, test_serve_config, test_check, test_stop,
                   test_lint, test_cli, test_bounded_output, test_concurrency,
                   test_damaged_files, test_stop_check_signal, test_pathological):
            fn(tmp)
    print("\n" + "=" * 50)
    print("Results: %d passed, %d failed" % (_passes, _failures))
    return 0 if _failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
