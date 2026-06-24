# Deploy instructions

This file documents the exact steps to publish the decisions-md plugin to GitHub
and make it installable from the Claude Code marketplace.

**Human action required** for steps 1–5. Steps 6–7 can be done from any Claude Code
session once the repo is public.

---

## Step 1 — Create the GitHub repo

Go to https://github.com/new and create a **public** repo:

- **Owner**: bitbutter
- **Repository name**: `decisions-md`
- **Description**: `Claude Code plugin — binding DECISIONS.md enforcement`
- **Visibility**: Public
- **Do NOT initialise** with README, .gitignore, or licence (this repo ships its own).

---

## Step 2 — Push this directory to the new repo

Run the following from wherever you've placed this `decisions-md-repo/` directory
(or from inside a clone of it):

```bash
cd /path/to/decisions-md-repo

git init
git add .
git commit -m "Initial release: decisions-md plugin v1.0.0"
git branch -M main
git remote add origin https://github.com/bitbutter/decisions-md.git
git push -u origin main
```

---

## Step 3 — Tag the release

```bash
git tag v1.0.0
git push origin v1.0.0
```

Then create a GitHub release at:
https://github.com/bitbutter/decisions-md/releases/new?tag=v1.0.0

Use the CHANGELOG.md content as the release notes.

---

## Step 4 — Verify CI passes

Check that the Actions tab shows the CI workflow green on the initial push.
The synthetic-payload harness (56 checks) runs on every push.

---

## Step 5 — Optional: publish to the Claude Code plugin registry

If there is an official Anthropic registry, submit the plugin there following
their submission process. The plugin.json already has all required fields.

---

## Step 6 — Add the marketplace and install (from any Claude Code session)

Once the repo is public, in any Claude Code session:

```
/plugin marketplace add github.com/bitbutter/decisions-md
/plugin install decisions-md
```

Reload Claude Code so the hooks register.

---

## Step 7 — Smoke-test in a real project

In a project that has a `DECISIONS.md`:

1. Edit a tracked file (e.g. a `.gd` file) — the gate should block:
   ```
   DECISIONS GATE: edits to design-relevant files require consulting DECISIONS.md first.
   ```
2. Run `/decisions --query <something>` — the gate unlocks.
3. Edit the tracked file again — succeeds.
4. Let the session end with an unsaved design change — the Stop hook fires once and
   prompts decision capture.

---

## Step 8 — Repoint existing installs (if any were done from local path)

If moresque or ancap_if were already installed from a local path marketplace
(Phase 4 done before Phase 5), switch them to the published source:

```
/plugin marketplace remove /path/to/local/decisions-md
/plugin marketplace add github.com/bitbutter/decisions-md
/plugin install decisions-md
```

---

## Repository structure (for reference)

```
decisions-md/
├── .claude-plugin/
│   └── plugin.json          ← plugin manifest (name, version, description, license)
├── hooks/
│   ├── hooks.json            ← event → script mappings (uses ${CLAUDE_PLUGIN_ROOT})
│   ├── decisions_common.py   ← shared helpers; no external deps
│   ├── decisions_gate.py     ← PreToolUse gate
│   ├── decisions_check.py    ← PostToolUse recorder + format validator
│   ├── decisions_nudge.py    ← UserPromptSubmit edit-reminder
│   ├── decisions_binding_nudge.py  ← UserPromptSubmit binding block
│   ├── decisions_precompact.py     ← PreCompact injection
│   ├── decisions_session_start.py  ← SessionStart (persist session id, re-arm stop)
│   └── decisions_stop_check.py     ← Stop gate (once-per-session)
├── scripts/
│   └── query_decisions.py    ← read CLI; also writes the gate-unlock marker
├── commands/
│   └── decisions.md          ← /decisions slash command
├── skills/
│   └── decisions-binding/
│       └── SKILL.md          ← abandon/adapt/override protocol
├── tests/
│   └── verify_plugin.py      ← 56-check synthetic-payload harness (no live session needed)
├── .github/
│   └── workflows/
│       └── ci.yml            ← runs validate + harness on every push
├── .gitignore
├── CHANGELOG.md
├── LICENSE                   ← MIT
└── README.md
```
