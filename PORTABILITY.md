# Interpreter portability: the plan

Working note, not user documentation. Delete once resolved.

## The defect

All eight hook commands in `hooks/hooks.json` launch `python3`:

```json
"command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/decisions_gate.py\""
```

`python3` is standard on macOS and Linux and absent from most Windows installs,
where the interpreter is `py` (the PEP 397 launcher) or `python`. `python` in turn
is missing on many Linux distributions. **No single interpreter name works
everywhere.**

Confirmed on a Windows 11 machine 2026-07-29: `python3` is not on PATH, `py -3`
is. Every hook there fails to launch.

## The worse half of the defect

A missing interpreter fails **silently**. The plugin lists in
`/plugin marketplace list`, its command autocompletes, its skill loads, and none
of the hooks run. Nothing reports this. The plugin looks installed and correct
while doing nothing at all.

Whatever we do about the interpreter, that silence is the more serious bug: it is
the reason this went unnoticed.

## Why CI missed it

`.github/workflows/ci.yml` runs on `ubuntu-latest` only. The harness passes 68/68
on Linux and has never executed on Windows.

---

## Phase 0 — make failure loud (do regardless of the outcome below)

Add `--doctor` to `scripts/query_decisions.py`, reporting:

- the interpreter actually running it (`sys.executable`, `sys.version`)
- resolved `CLAUDE_PLUGIN_ROOT` and project root
- whether a `DECISIONS.md` was found, and where
- whether `.decisions/cache/` exists and is writable
- **whether `current-session-id` exists** — its absence is a direct signal that the
  SessionStart hook never ran, which is the symptom of this bug

One command that tells a stranger on any OS whether the plugin is actually
working. This is worth doing on its own merits.

## Phase 1 — answer the Windows question in CI, not by hand

Add a `windows-latest` job to the workflow that probes the two candidate launch
strategies and reports which succeed:

1. `python3 hooks/decisions_session_start.py`   (current)
2. `py -3 hooks/decisions_session_start.py`
3. `hooks/decisions_session_start.py`           (bare, via shebang + file association)

Assert the marker file is written, and separately assert the gate still exits
**2** rather than 0 or 127. Exit code fidelity is the part that matters: a gate
that fails to block is worse than one that errors.

**Verified on Linux already:** bare invocation works and preserves exit 2, given
the shebang (present in all nine scripts) and the executable bit (currently
missing; they are all `100644` in git).

The unknown is whether Claude Code on Windows spawns hook commands through a
shell. Bare `.py` invocation depends on the `.py` file association, which applies
under `cmd.exe` but not under a direct `CreateProcess`. CI answers the shell
question; it does not fully answer the Claude-Code-spawn question, so pair it with
one manual check on a real Windows install before shipping.

## Phase 2 — implement whichever wins

**If bare invocation works on both:** drop `python3 ` from all eight commands, set
the scripts to mode `100755` in git, and drop `allowed-tools: Bash(python3:*)`
from `commands/decisions.md`. Single manifest, no platform branching, no
prerequisite beyond a working Python. Best outcome.

**If it does not:** keep `python3` and promote the Windows note from a footnote at
the bottom of the README to a required install step. Microsoft Store Python puts
`python3` on PATH and is the one-line fix; the python.org installer does not.
Phase 0's `--doctor` then carries the diagnosis.

Do **not** register both `python3` and `py -3` variants of each hook. On a machine
with both, every hook runs twice: two gate blocks, duplicated nudges.

## Phase 3 — keep it fixed

Extend the CI matrix to `ubuntu-latest`, `macos-latest`, `windows-latest` and run
the full 68-check harness on all three. This class of bug should never again be
invisible to CI.

---

## Order

Phase 0 and Phase 3 are unconditional and independent of the result. Phase 1 is
cheap and decides Phase 2. Nothing here needs to block publishing except Phase 2,
which is a one-line-per-hook change once the answer is known.
