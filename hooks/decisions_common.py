#!/usr/bin/env python3
"""Shared helpers for the DECISIONS.md enforcement plugin hooks.

Self-contained: standard library only, and no dependency on any external decision
tracker. State lives in a plugin-owned, project-relative `.decisions/cache/`
directory next to DECISIONS.md.

Project-root resolution (in order): the `CLAUDE_PROJECT_DIR` env var that Claude
Code sets for plugin hooks (authoritative consuming-project root), then a walk up
from CWD for a DECISIONS.md / .git marker, then a walk up from this module, then
CWD. This makes the engine work whether it runs from the plugin install dir, a
project subdir, or a plain CLI invocation.

What the gate guards (tracked file extensions) and what it skips (exempt paths)
are read from an optional `<project>/.decisions/config.json`, with sensible
defaults, so the plugin is reusable across projects without code edits.
"""

import io
import json
import os
import re
import subprocess
import sys

# Project-relative, plugin-owned state directory (sibling of DECISIONS.md).
CACHE_DIRNAME = os.path.join(".decisions", "cache")
CONFIG_RELPATH = os.path.join(".decisions", "config.json")

# DECISIONS.md may live at the project root or a small set of conventional doc dirs.
_DECISIONS_SEARCH_SUBDIRS = ("", "docs", "support", "design", "decisions")

# Defaults (overridable per-project via .decisions/config.json).
# Godot types plus the common scripting/source types, so the gate is useful out of
# the box outside Godot projects. A project that wants a narrower (or wider) set
# overrides `tracked_extensions` in .decisions/config.json.
DEFAULT_TRACKED_EXTENSIONS = [
    # Godot
    ".gd", ".tscn", ".tres", ".gdshader", ".gdextension",
    # Common scripting / source languages
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".rb", ".go", ".rs", ".lua", ".sh", ".ps1",
]
DEFAULT_EXEMPT_PATHS = ["DECISIONS.md", ".decisions/", ".claude/", "tools/"]

# A decision ID may carry ONE optional trailing lowercase letter (DEC-AREA-007d),
# which marks an amend/override of the parent entry. Every place that parses or
# validates an ID must accept the suffix, or suffix entries get silently absorbed
# into the parent block and become invisible to --query and --validate.
DECISION_ID_RE = r"DEC-([A-Z]+)-\d+[a-z]?"


def setup_utf8_stdout():
    """Force UTF-8 stdout so non-cp1252 decision text doesn't crash print() on Windows."""
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def find_decisions_md(root):
    """Return the path to DECISIONS.md under `root` (root or a known doc subdir), else None."""
    if not root:
        return None
    for d in _DECISIONS_SEARCH_SUBDIRS:
        p = os.path.join(root, d, "DECISIONS.md") if d else os.path.join(root, "DECISIONS.md")
        if os.path.isfile(p):
            return p
    return None


def _walk_up_for_marker(start):
    """Return the nearest ancestor of `start` (inclusive) holding DECISIONS.md or .git, else None."""
    if not start:
        return None
    cur = os.path.abspath(start)
    for _ in range(40):
        if find_decisions_md(cur) or os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def get_project_root():
    """Resolve the consuming project's root (NOT the plugin install dir)."""
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root and os.path.isdir(env_root):
        return env_root
    for start in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        root = _walk_up_for_marker(start)
        if root:
            return root
    return os.getcwd()


def get_cache_dir(project_root):
    """Project-relative, plugin-owned state dir (`<root>/.decisions/cache`). Not created here."""
    if not project_root:
        return None
    return os.path.join(project_root, CACHE_DIRNAME)


def load_config(project_root):
    """Read `<root>/.decisions/config.json` -> dict; {} when absent or malformed."""
    if not project_root:
        return {}
    path = os.path.join(project_root, CONFIG_RELPATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def get_tracked_extensions(config):
    """Lowercased set of file extensions the gate guards / the check records.

    Falls back to defaults only when the key is absent or not a list (a string typo
    like "tracked_extensions": ".gd" must NOT be iterated char-by-char). An explicit
    empty list is honored (tracks nothing) so a project can opt out.
    """
    exts = config.get("tracked_extensions")
    if not isinstance(exts, list):
        exts = DEFAULT_TRACKED_EXTENSIONS
    return {str(e).lower() for e in exts}


def get_exempt_paths(config):
    """Project-relative path prefixes that never trip the gate.

    Falls back to defaults only when the key is absent or not a list; an explicit
    empty list is honored (exempt nothing -- DECISIONS.md itself stays exempt via the
    gate's own check).
    """
    paths = config.get("exempt_paths")
    if not isinstance(paths, list):
        paths = DEFAULT_EXEMPT_PATHS
    return [str(p) for p in paths]


def is_within_project_root(file_path, project_root):
    """True only if `file_path` resolves to a location inside `project_root`.

    A project's gate governs that project's own files only. Editing a file OUTSIDE
    the root (another repo, or this plugin's own source while you work elsewhere)
    must never be gated and must never be recorded as this project's pending
    decision-capture -- otherwise it corrupts the wrong project's .decisions/cache
    and false-blocks that project's Stop gate.
    """
    if not file_path or not project_root:
        return False
    try:
        root = os.path.normcase(os.path.abspath(project_root))
        target = os.path.normcase(os.path.abspath(file_path))
    except (OSError, ValueError):
        return False
    return target == root or target.startswith(root + os.sep)


def get_overview(decisions_path):
    """One-line summary of DECISIONS.md: total count + per-area breakdown, or "" on error."""
    try:
        content = open(decisions_path, encoding="utf-8-sig").read()
    except OSError:
        return ""
    areas = {}
    for m in re.finditer(rf"^{DECISION_ID_RE}:", content, re.MULTILINE):
        a = m.group(1).lower()
        areas[a] = areas.get(a, 0) + 1
    if not areas:
        return ""
    total = sum(areas.values())
    parts = ", ".join(f"{a}:{n}" for a, n in sorted(areas.items()))
    return f"{total} decisions ({parts})"


def build_binding_lines(project_root):
    """Return the shared DECISIONS-binding reminder lines, or None if no DECISIONS.md.

    One source of truth for the block emitted by both the UserPromptSubmit binding
    nudge and the PreCompact injection, so the two can't drift.
    """
    path = find_decisions_md(project_root)
    if not path:
        return None
    lines = [
        "[DECISIONS-BINDING] DECISIONS.md rules are binding.",
        "  Read path: /decisions-md:decisions [--area A] [--query K]  (or query_decisions.py).",
        "  Call BEFORE design-touching work. Do NOT Read/Grep DECISIONS.md directly.",
        "  On direct answer or contradiction: present abandon/adapt/override options.",
    ]
    overview = get_overview(path)
    if overview:
        lines.append(f"  Overview: {overview}")
    return lines


def run_command(cmd, timeout=5):
    """Run a shell command; return stripped stdout on success, else None."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, shell=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError, Exception):
        return None
    return None
