#!/usr/bin/env python3
"""Shared engine for the decisions-md plugin.

Standard library only, no companion tooling.

Design rules this module encodes:

  * DECISIONS.md states what is true NOW. Git holds what used to be true. There is
    no status vocabulary, no superseded entries and no suffix/override IDs -- a
    changed decision is edited in place under its original ID, and a retired one is
    deleted. Anything left over from the old format is a lint error, not a mode.
  * Plugin state NEVER lands in the consuming project. It lives under
    ~/.claude/decisions-md-state/<project-key>/. The only thing the plugin reads out of a
    project is DECISIONS.md and the optional .decisions/config.json, which the
    project owns and commits.
  * One parser. The hooks, the CLI and the linter all read decisions through
    parse_decisions() so they cannot disagree about what an entry is.

Project-root resolution (in order): the CLAUDE_PROJECT_DIR env var that Claude Code
sets for plugin hooks, then a walk up from CWD for a DECISIONS.md / .git marker, then
a walk up from this module, then CWD.
"""

import bisect
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time

CONFIG_RELPATH = os.path.join(".decisions", "config.json")

# DECISIONS.md may live at the project root or a small set of conventional doc dirs.
DECISIONS_SEARCH_SUBDIRS = ("", "docs", "support", "design", "decisions")

# Defaults (overridable per-project via .decisions/config.json).
DEFAULT_TRACKED_EXTENSIONS = [
    # Godot
    ".gd", ".tscn", ".tres", ".gdshader", ".gdextension",
    # Common scripting / source languages
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".rb", ".go", ".rs", ".lua", ".sh", ".ps1",
]
# Vendored and generated trees are not your design surface, and matching them produced
# real noise: a test framework and an art-import addon both matched narrative decisions.
DEFAULT_EXEMPT_PATHS = [
    "DECISIONS.md", ".decisions/", ".claude/", "tools/",
    "addons/", "vendor/", "third_party/", "node_modules/", ".godot/", "build/", "dist/",
]

# One ID grammar: DEC-<AREA>-<NNN>. No trailing letter. A trailing letter used to mean
# "override of the parent entry"; that convention is gone and its leftovers are linted.
DECISION_ID_RE = r"DEC-([A-Z]+)-\d+"
ID_LINE_RE = re.compile(r"^(DEC-[A-Z]+-\d+)\s*:\s*(.*)$")
LEGACY_SUFFIX_ID_RE = re.compile(r"^(DEC-[A-Z]+-\d+[a-z])\s*:", re.MULTILINE)
LEGACY_STATUS_RE = re.compile(r"^Status:\s*(.*)$", re.MULTILINE)

# A "Key: value" line ends the wrapped statement and starts a metadata field.
FIELD_LINE_RE = re.compile(r"^([A-Z][A-Za-z]*)\s*:\s*(.*)$")
# A markdown code fence: three or more backticks or tildes.
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

# How many decisions the serve hook will print for one edit before pointing at the CLI.
MAX_SERVED_STATEMENTS = 15
# How many entries a single CLI result set prints before doing the same.
MAX_QUERY_RESULTS = 12
# Session state older than this is swept at SessionStart; orphaned temp files sooner.
STATE_TTL_SECONDS = 7 * 24 * 60 * 60
TMP_TTL_SECONDS = 60 * 60
# In the fallback matcher, a word counts as belonging to an area when at least this
# share of its occurrences across the whole file sit in that one area.
AREA_OWNERSHIP_RATIO = 0.5
# ...or when it appears in an area this many times more often than across the file.
AREA_LIFT_THRESHOLD = 2.0


def setup_utf8_stdout():
    """Force UTF-8 stdout so non-cp1252 decision text doesn't crash print() on Windows."""
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        return


# ── Project resolution ────────────────────────────────────────────────────────

def find_decisions_md(root):
    """Return the path to DECISIONS.md under `root` (root or a known doc subdir), else None."""
    if not root:
        return None
    for d in DECISIONS_SEARCH_SUBDIRS:
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


def is_within_project_root(file_path, project_root):
    """True only if `file_path` resolves to a location inside `project_root`.

    A project's decisions govern that project's own files. An edit to another repo --
    or to this plugin's own source while you work elsewhere -- is not its business.
    """
    if not file_path or not project_root:
        return False
    try:
        root = os.path.normcase(os.path.abspath(project_root))
        target = os.path.normcase(os.path.abspath(file_path))
    except (OSError, ValueError):
        return False
    return target == root or target.startswith(root + os.sep)


def relative_path(file_path, project_root):
    """Project-relative, forward-slashed path; falls back to the basename off-root."""
    try:
        rel = os.path.relpath(os.path.abspath(file_path), os.path.abspath(project_root))
    except (OSError, ValueError):
        return os.path.basename(file_path).replace("\\", "/")
    return rel.replace("\\", "/")


# ── State (outside the consuming project, always) ─────────────────────────────

def _project_key(project_root):
    """Stable, readable directory name for one project's state."""
    norm = os.path.normcase(os.path.abspath(project_root or os.getcwd()))
    digest = hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:10]
    base = os.path.basename(norm.rstrip(os.sep)) or "project"
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", base)[:40].strip("-") or "project"
    return f"{slug}-{digest}"


def get_state_dir(project_root):
    """~/.claude/decisions-md-state/<project-key>/ -- never inside the consuming project.

    The "-state" suffix is load-bearing. The conventional place to clone this plugin is
    ~/.claude/decisions-md, so a state root of that same path would write per-project
    state directly into the plugin's own working tree -- the exact pollution this
    module exists to avoid, aimed at the one repository most likely to notice.

    Nothing here is precious: deleting it costs you one re-served decision list.
    DECISIONS_STATE_DIR relocates the root (the test harness sets it so a test run
    cannot touch your real state).
    """
    root = os.environ.get("DECISIONS_STATE_DIR")
    if not root:
        root = os.path.join(state_home(), ".claude", "decisions-md-state")
    return os.path.join(root, _project_key(project_root))


def home_is_resolvable():
    """True when the OS gave us a real absolute home directory."""
    home = os.path.expanduser("~")
    return bool(home) and home != "~" and os.path.isabs(home)


def state_home():
    """The home directory, or a labelled temp fallback when there isn't one.

    os.path.expanduser does not raise when it cannot resolve a home -- on Windows it
    hands back the literal string "~", and an unset or blank USERPROFILE yields "".
    Joining either onto a relative path produced state inside whatever directory the
    hook happened to be launched from, i.e. the user's project: the one outcome this
    module exists to prevent. Falling back to the temp directory keeps that guarantee;
    --doctor reports the fallback as a failure so it is never silent.
    """
    if home_is_resolvable():
        return os.path.expanduser("~")
    return os.path.join(tempfile.gettempdir(), "decisions-md-nohome")


def _write_atomic(path, text):
    """Write via a temp file + os.replace so a concurrent reader never sees a half file.

    newline="" is not optional. Without it, Windows text mode translates every "\\n" to
    "\\r\\n" on the way out -- so text that already carries "\\r\\n" is written as
    "\\r\\r\\n" and the file is quietly corrupted.
    """
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        try:
            os.replace(tmp, path)
        except OSError:
            # A failed replace must not leave its temp file lying next to the original
            # (Windows raises here whenever a sync client or scanner holds the target).
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        return True
    except OSError:
        return False


def get_session_id(project_root):
    """Explicit env override, else the id persisted by the SessionStart hook, else None.

    None is a normal, non-fatal answer: every caller treats "no session identity" as
    "do nothing", because the plugin's per-session bookkeeping is an optimisation, not
    a lock.
    """
    sid = os.environ.get("DECISIONS_SESSION_ID")
    if sid:
        return sid.strip()
    try:
        path = os.path.join(get_state_dir(project_root), "current-session-id")
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
        return content or None
    except OSError:
        return None


def persist_session_id(project_root, session_id):
    """Record the authoritative session id so the CLI and hooks agree on one identity."""
    if not session_id:
        return False
    return _write_atomic(os.path.join(get_state_dir(project_root), "current-session-id"),
                         str(session_id))


# ── Per-session bookkeeping ───────────────────────────────────────────────────
#
# Every fact is its own small file, and no file is ever read-modify-written.
#
# The obvious design -- one JSON blob per session, loaded, edited, saved -- does not
# survive contact with Claude Code, which dispatches tool calls in parallel: each call
# spawns its own hook process, and two processes rewriting one blob silently discard
# each other's changes. Measured, 20 parallel edit-recording hooks kept 8 of 20 facts.
# Worse on Windows, where concurrently os.replace-ing the same destination raises
# PermissionError most of the time.
#
# Disjoint files remove the race rather than guarding it, and creating a marker with
# mode "x" is an atomic claim: exactly one process can win, which is precisely the
# question "has this area been served yet?" is asking.

def _safe_component(name):
    """A single path component that cannot escape its directory, or None."""
    s = re.sub(r"[^A-Za-z0-9._-]", "-", str(name or "")).strip("-. ")
    if not s or s.strip(".") == "":
        return None
    return s[:80]


def session_dir(project_root, session_id):
    sid = _safe_component(session_id)
    if not sid:
        return None
    return os.path.join(get_state_dir(project_root), "s-" + sid)


def _claim(path):
    """Create `path` exactly once. True only for the process that created it.

    False means either someone else got there first or the write failed -- callers
    treat both the same way, by doing nothing, because acting on a claim you did not
    win (or could not record) is what produces a block that repeats forever.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except OSError:
        return False


def _write_marker(path, text):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return True
    except OSError:
        return False


def claim_area_served(project_root, session_id, area):
    """Claim the right to show `area`'s decisions. True for one caller, once."""
    sdir = session_dir(project_root, session_id)
    name = _safe_component(area)
    if not sdir or not name:
        return False
    return _claim(os.path.join(sdir, "served", name))


def area_is_served(project_root, session_id, area):
    sdir = session_dir(project_root, session_id)
    name = _safe_component(area)
    if not sdir or not name:
        return False
    return os.path.isfile(os.path.join(sdir, "served", name))


def record_pending_edit(project_root, session_id, rel_path):
    """Note that a tracked file was edited. Keyed by path hash, so writers never collide."""
    sdir = session_dir(project_root, session_id)
    if not sdir or not rel_path:
        return False
    key = hashlib.sha1(rel_path.encode("utf-8", "replace")).hexdigest()[:16]
    return _write_marker(os.path.join(sdir, "pending", key), rel_path)


def take_pending_edits(project_root, session_id):
    """Return the edits recorded this session and forget them."""
    sdir = session_dir(project_root, session_id)
    if not sdir:
        return []
    pending_dir = os.path.join(sdir, "pending")
    found = []
    try:
        names = sorted(os.listdir(pending_dir))
    except OSError:
        return []
    for name in names:
        path = os.path.join(pending_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                value = fh.read().strip()
        except OSError:
            continue
        try:
            os.remove(path)
        except OSError:
            # Removing it is what makes this a "take". If the file survives -- another
            # process holding it open, most likely -- reporting the edit anyway would
            # hand the same one back on the next call. Leave it for the sweep instead.
            continue
        if value:
            found.append(value)
    return found


def mark_decisions_touched(project_root, session_id):
    """Record that DECISIONS.md itself was written this session."""
    sdir = session_dir(project_root, session_id)
    return _write_marker(os.path.join(sdir, "decisions-touched"), "1") if sdir else False


def decisions_were_touched(project_root, session_id):
    sdir = session_dir(project_root, session_id)
    return bool(sdir) and os.path.isfile(os.path.join(sdir, "decisions-touched"))


def claim_stop_check(project_root, session_id):
    """Claim the one Stop-check firing this session. True for one caller, once."""
    sdir = session_dir(project_root, session_id)
    return _claim(os.path.join(sdir, "stop-fired")) if sdir else False


def reset_session(project_root, session_id):
    """Forget everything about one session, so a new or resumed one starts clean."""
    sdir = session_dir(project_root, session_id)
    if not sdir:
        return
    shutil.rmtree(sdir, ignore_errors=True)


def prune_old_state(project_root):
    """Drop stale session directories and orphaned temp files.

    Temp files need sweeping explicitly: a failed os.replace leaves `<name>.<pid>.tmp`
    behind, and a sweep that only matched session directories would keep them forever.
    """
    state_dir = get_state_dir(project_root)
    try:
        names = os.listdir(state_dir)
    except OSError:
        return
    now = time.time()
    for name in names:
        path = os.path.join(state_dir, name)
        try:
            if name.startswith("s-") and os.path.isdir(path):
                if now - _last_touched(path) > STATE_TTL_SECONDS:
                    shutil.rmtree(path, ignore_errors=True)
            elif name.endswith(".tmp") and now - os.path.getmtime(path) > TMP_TTL_SECONDS:
                os.remove(path)
        except OSError:
            continue


def _last_touched(session_path):
    """Newest mtime of a session directory or its immediate subdirectories.

    A directory's own mtime only moves when a DIRECT child appears, so a long-running
    session that keeps adding files inside an existing served/ or pending/ folder looks
    untouched to the sweep and could be deleted while still in use.
    """
    newest = os.path.getmtime(session_path)
    try:
        for entry in os.listdir(session_path):
            child = os.path.join(session_path, entry)
            try:
                newest = max(newest, os.path.getmtime(child))
            except OSError:
                continue
    except OSError:
        pass
    return newest


def legacy_cache_dir(project_root):
    """Pre-2.0 in-project state dir, so the doctor can tell you it is safe to delete."""
    if not project_root:
        return None
    return os.path.join(project_root, ".decisions", "cache")


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(project_root):
    """Read `<root>/.decisions/config.json` -> dict; {} when absent or malformed."""
    if not project_root:
        return {}
    try:
        with open(os.path.join(project_root, CONFIG_RELPATH), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def is_enabled(config):
    """`"enabled": false` turns the whole plugin off for one project."""
    return config.get("enabled", True) is not False


def get_tracked_extensions(config):
    """Lowercased set of file extensions that trigger a decision serve.

    Falls back to defaults only when the key is absent or not a list (a string typo
    like "tracked_extensions": ".gd" must NOT be iterated char-by-char). An explicit
    empty list is honored.
    """
    exts = config.get("tracked_extensions")
    if not isinstance(exts, list):
        return {e.lower() for e in DEFAULT_TRACKED_EXTENSIONS}
    # An explicit [] means "track nothing" and is honoured. But a list whose entries
    # are not extension strings -- [[".py"]], [1, 2], [null] -- is a typo, and coercing
    # it with str() produced values like "['.py']" that can never match a real file,
    # silently switching the plugin off with no diagnostic anywhere.
    usable = {e.lower() for e in exts if isinstance(e, str) and e.startswith(".") and len(e) > 1}
    if exts and not usable:
        return {e.lower() for e in DEFAULT_TRACKED_EXTENSIONS}
    return usable


def get_exempt_paths(config):
    """Project-relative path prefixes that never trigger a serve."""
    paths = config.get("exempt_paths")
    if not isinstance(paths, list):
        paths = DEFAULT_EXEMPT_PATHS
    cleaned = []
    for p in paths:
        s = str(p).replace("\\", "/").strip()
        # Strip a leading "./" only. A blanket lstrip("./") would eat the leading dot
        # of ".decisions/" and ".claude/" and exempt the wrong directories entirely.
        if s.startswith("./"):
            s = s[2:]
        s = s.rstrip("/")
        if s:
            cleaned.append(s)
    return cleaned


def get_area_map(config):
    """Optional {glob: area} map pinning paths to decision areas."""
    raw = config.get("area_map")
    if not isinstance(raw, dict):
        return {}
    return {str(k).replace("\\", "/"): str(v).lower() for k, v in raw.items()}


def _compare_path(p):
    """Forward-slashed, and case-folded only where the filesystem is.

    os.path.normcase cannot be used on its own here: on Windows it rewrites "/" to
    "\\", which silently breaks any comparison written against a forward-slashed
    prefix.
    """
    s = (p or "").replace("\\", "/")
    return s.lower() if os.name == "nt" else s


def is_exempt_path(file_path, project_root, exempt_paths, decisions_md=None):
    """True if the file IS this project's DECISIONS.md, or sits under an exempt prefix.

    Prefix match on the PROJECT-RELATIVE path, not a substring match on the absolute
    one: an exempt entry of "tools/" must exempt "tools/build.py" and must NOT exempt
    "src/tools/thing.py", nor anything that merely happens to contain those characters
    somewhere in an absolute path.

    The DECISIONS.md test compares resolved paths rather than basenames, so an unrelated
    `vendor/some_dep/decisions.md` is governed like any other file.
    """
    if not file_path:
        return True
    if decisions_md:
        try:
            if (os.path.normcase(os.path.abspath(file_path))
                    == os.path.normcase(os.path.abspath(decisions_md))):
                return True
        except (OSError, ValueError):
            pass
    rel = _compare_path(relative_path(file_path, project_root))
    for exempt in exempt_paths:
        e = _compare_path(exempt).rstrip("/")
        if e and (rel == e or rel.startswith(e + "/")):
            return True
    return False


# ── Parsing ───────────────────────────────────────────────────────────────────

class Decision(object):
    """One entry: an ID line whose statement may wrap, plus optional `Key: value` fields."""

    __slots__ = ("id", "area", "statement", "fields", "line_no", "line_count")

    def __init__(self, dec_id, area, statement, fields, line_no, line_count):
        self.id = dec_id
        self.area = area
        self.statement = statement
        self.fields = fields
        self.line_no = line_no
        self.line_count = line_count

    def render(self, with_fields=True):
        out = ["%s: %s" % (self.id, self.statement)]
        if with_fields:
            for key, value in self.fields:
                out.append("  %s: %s" % (key, value))
        return "\n".join(out)


def _normalise_newlines(text):
    """CRLF -> LF, and CR -> LF only for a file that really is CR-terminated.

    A lone \\r in the middle of an otherwise LF-terminated file is a stray control
    character, not a line break -- every editor and grep treats it that way. Folding it
    into a newline anyway shifted every reported line number after it, so the linter
    would tell you to go and delete a line that was not the offending one.
    """
    text = text.replace("\r\n", "\n")
    if "\r" in text and "\n" not in text:
        text = text.replace("\r", "\n")   # genuine classic-Mac line endings
    return text


def read_decisions_text(path):
    """Read DECISIONS.md with BOM and line endings normalised, or None if unreadable.

    Decoding is lenient on purpose. UnicodeDecodeError is a ValueError, not an OSError,
    so a DECISIONS.md saved as cp1252 -- what Windows editors still do by default -- used
    to escape this handler and take down every hook with a traceback on every edit. A
    replacement character in one word is a far better outcome than that; the linter
    reports the encoding separately so it still gets fixed.
    """
    # newline="" disables Python's universal-newline translation. Without it the reader
    # silently turns every lone \r into \n before this code can tell the difference
    # between a line terminator and a stray control byte -- which is exactly the
    # distinction the reported line numbers depend on.
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            return _normalise_newlines(fh.read())
    except OSError:
        return None
    except (UnicodeDecodeError, ValueError):
        pass
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            return _normalise_newlines(fh.read())
    except (OSError, ValueError):
        return None


def is_valid_utf8(path):
    try:
        with open(path, "rb") as fh:
            fh.read().decode("utf-8-sig")
        return True
    except (OSError, UnicodeDecodeError):
        return False


def _blank_fenced_blocks(lines):
    """Blank out CLOSED fenced code blocks. Returns (lines, unclosed_fence_line_no).

    Documenting the entry format inside DECISIONS.md is a natural thing to do, and an
    example used to become a real, binding decision. Blanking rather than deleting keeps
    every reported line number pointing at the right line.

    Three details matter, each of which was wrong when this was a simple toggle:
      * Only a fence that is actually CLOSED blanks anything. An unclosed fence used to
        swallow every decision after it in total silence -- the worst failure this file
        has, since the entries simply stop being binding and nothing says so.
      * A fence closes on the same character, at least as long as the one that opened it
        (CommonMark). A ```` ```` ```` block wrapping a ``` ``` ``` example used to end
        early and leak its contents back out as live decisions.
      * ~~~ is a fence too.
    """
    out = list(lines)
    total = len(lines)
    i = 0
    while i < total:
        opening = _FENCE_RE.match(lines[i])
        if not opening:
            i += 1
            continue
        marker = opening.group(1)
        close_at = None
        for j in range(i + 1, total):
            closing = _FENCE_RE.match(lines[j])
            if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
                close_at = j
                break
        if close_at is None:
            return out, i + 1
        for k in range(i, close_at + 1):
            out[k] = ""
        i = close_at + 1
    return out, None


def parse_decisions(path):
    """Parse DECISIONS.md into a list of Decision, in file order.

    A decision runs from its ID line to the next ID line (or EOF). The statement is the
    ID line's text plus any following lines up to the first blank line or `Key: value`
    field. Legacy `Status:` lines parse as ordinary fields so the linter can report
    them; nothing else in the plugin looks at them.
    """
    text = read_decisions_text(path)
    if text is None:
        return []
    lines, _unclosed = _blank_fenced_blocks(text.split("\n"))

    starts = []
    for i, line in enumerate(lines):
        if ID_LINE_RE.match(line):
            starts.append(i)

    decisions = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        m = ID_LINE_RE.match(lines[start])
        dec_id, first = m.group(1), m.group(2).strip()
        area_match = re.match(DECISION_ID_RE, dec_id)
        area = area_match.group(1).lower() if area_match else ""

        statement_parts = [first] if first else []
        fields = []
        in_statement = True
        in_field = False
        for raw in lines[start + 1:end]:
            line = raw.rstrip()
            if not line.strip():
                # A blank line closes the statement AND any open field. Without closing
                # the field, every later line up to the next ID -- a markdown heading, a
                # note between entries -- was appended to the last field's value, which
                # both printed as part of the entry and fed the area matcher words the
                # author never put in the decision.
                in_statement = False
                in_field = False
                continue
            field = FIELD_LINE_RE.match(line)
            if field:
                in_statement = False
                in_field = True
                fields.append((field.group(1), field.group(2).strip()))
                continue
            if in_statement:
                statement_parts.append(line.strip())
            elif in_field:
                # Continuation of the previous field's value, unbroken by a blank line.
                key, value = fields[-1]
                fields[-1] = (key, (value + " " + line.strip()).strip())
            # Anything else is prose between entries -- headings, notes. Not ours.

        block = [l for l in lines[start:end] if l.strip()]
        decisions.append(Decision(
            dec_id=dec_id,
            area=area,
            statement=" ".join(statement_parts).strip(),
            fields=fields,
            line_no=start + 1,
            line_count=len(block),
        ))
    return decisions


def areas_with_counts(decisions):
    counts = {}
    for d in decisions:
        counts[d.area] = counts.get(d.area, 0) + 1
    return counts


def get_overview(decisions):
    """One-line summary: total count + per-area breakdown, or "" when empty."""
    counts = areas_with_counts(decisions)
    if not counts:
        return ""
    total = sum(counts.values())
    parts = ", ".join("%s:%d" % (a, n) for a, n in sorted(counts.items()))
    return "%d decisions (%s)" % (total, parts)


# ── Matching a file path to decision areas ────────────────────────────────────

_PATH_STOPWORDS = {
    "src", "source", "scripts", "script", "lib", "libs", "app", "apps", "core",
    "common", "util", "utils", "addons", "assets", "res", "code", "game", "pkg",
    "internal", "new", "old", "tmp", "temp", "node", "modules", "dist", "build",
    "test", "tests", "spec", "specs", "the", "and", "for",
}


def simple_stem(word):
    """Crude singular/base form, so "cards" and "card" compare equal.

    The plural rules are spelled out rather than folded into one trailing-"s" strip.
    A blanket strip made "enemies" -> "enem" while "enemy" stayed "enemy", so the two
    forms of the same word stopped matching each other; and it turned "class",
    "status" and "process" into different words than themselves.
    """
    w = (word or "").lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"                      # enemies -> enemy
    if len(w) > 4 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]                            # boxes -> box, buses -> bus
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]                            # cards -> card; class/status untouched
    for suffix in ("ing", "ed", "ly"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w


def tokenize(text):
    """Lowercase word stems, splitting snake_case, kebab-case and camelCase.

    \\W is unicode-aware, so a non-ASCII file name yields tokens rather than nothing at
    all -- returning an empty set would make the matcher give up before it started.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text or "")
    words = re.split(r"[\W_]+", spaced, flags=re.UNICODE)
    out = set()
    for w in words:
        if len(w) >= 3 or (len(w) >= 2 and not w.isascii()):
            out.add(simple_stem(w))
    return out


def path_tokens(rel_path, protected=()):
    """Meaningful tokens from a project-relative path, minus generic directory noise.

    `protected` holds the project's actual area names, which are never treated as
    noise. Without it a project with a BUILD or TEST area could never match its own
    files: those words sit in the generic-directory list and were stripped before the
    area-name check ever ran.
    """
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", rel_path or "")
    keep = {p for p in protected} | {simple_stem(p) for p in protected}
    return {t for t in tokenize(stem) if t in keep or t not in _PATH_STOPWORDS}


def _glob_match(rel_path, pattern):
    """fnmatch, but "*" does not cross a directory separator.

    Plain fnmatch treats "/" as an ordinary character, so a pattern of "src/*" also
    matches "src/deep/nested/thing.gd" -- far wider than whoever wrote it intended.
    A pattern that opts into "**" keeps the greedy behaviour.
    """
    if not fnmatch.fnmatch(rel_path, pattern):
        return False
    if "**" in pattern:
        return True
    return pattern.count("/") == rel_path.count("/")


def decision_tokens(decision):
    """Every word of a decision worth matching on -- statement AND its fields.

    The fields matter: a Context or Source line is where an entry names the file or
    function it governs, and that is frequently the only textual link between a rule
    and the code it binds.
    """
    text = " ".join([decision.statement] + [v for _, v in decision.fields])
    return tokenize(text) - _PATH_STOPWORDS


def match_areas(decisions, rel_path, area_map):
    """Decision areas that plausibly govern `rel_path`, best first.

    A heuristic, and it does not pretend otherwise -- but it is anchored on the file
    actually being edited, which is more than a keyword an agent guessed at. The two
    kinds of error are not symmetric: failing to surface a decision that governs this
    file is the failure the whole plugin exists to prevent, while surfacing one extra
    only costs tokens. Everything below is tuned in that direction.
    """
    if not decisions:
        return []
    known = {d.area for d in decisions}

    # Confident signals: an explicit area_map glob, or the area's own name in the path.
    # These are unioned rather than short-circuited -- one broad glob in config should
    # not be able to hide the area a file is literally named after.
    confident = []
    for pattern, area in area_map.items():
        if area in known and _glob_match(rel_path, pattern) and area not in confident:
            confident.append(area)

    tokens = path_tokens(rel_path, protected=known)
    for area in sorted(known):
        if (area in tokens or simple_stem(area) in tokens) and area not in confident:
            confident.append(area)
    if not tokens:
        return confident

    # Fallback: word overlap, weighted by which area a word BELONGS to rather than by
    # how rare it is. Two failures pushed it here. Counting raw overlap let everyday
    # vocabulary carry a match -- "weapon" plus "element" tagged a fifth of one real
    # project's files with an area about cursor cosmetics. But filtering out frequent
    # words instead lost `cards.gd`, the one file a whole area of card-cursor decisions
    # is about, because "card" was too common to survive the filter.
    #
    # What actually distinguishes the two: a word whose occurrences sit almost entirely
    # in ONE area is strong evidence for that area however often it appears, while a
    # word spread evenly across areas is evidence for none of them.
    per_decision = [(d, decision_tokens(d)) for d in decisions]
    per_area, totals, area_size = {}, {}, {}
    for d, toks in per_decision:
        bucket = per_area.setdefault(d.area, {})
        area_size[d.area] = area_size.get(d.area, 0) + 1
        for t in toks:
            bucket[t] = bucket.get(t, 0) + 1
            totals[t] = totals.get(t, 0) + 1

    total_decisions = float(len(decisions))
    scores = {}
    for area, bucket in per_area.items():
        if area in confident:
            continue
        score = 0.0
        for t in tokens & set(bucket):
            # Two ways a word can speak for an area: most of its uses are in this area,
            # or it is far more concentrated here than across the file as a whole. The
            # second test is what lets a small area be heard at all -- when one area
            # holds most of the decisions it owns nearly every word by default, and a
            # single-entry area could otherwise never win a word it plainly owns.
            owned = bucket[t] / float(totals[t]) >= AREA_OWNERSHIP_RATIO
            lift = ((bucket[t] / float(area_size[area]))
                    / (totals[t] / total_decisions))
            if not (owned or lift >= AREA_LIFT_THRESHOLD):
                score += 0.4
            elif totals[t] >= 2:
                score += 1.0
            else:
                # A word used exactly once in the whole file "belongs" to its area by
                # arithmetic alone. That is how vendored code matched real areas -- one
                # stray "bool" in one decision was enough. Half a match: two such words
                # still count, one no longer does.
                score += 0.6
        if score >= 1.0:
            scores[area] = score
    ranked = [a for a, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]
    return confident + ranked


def statements_for_areas(decisions, areas, limit=MAX_SERVED_STATEMENTS):
    """Statement lines for the given areas, plus how many were withheld."""
    wanted = [d for d in decisions if d.area in areas]
    shown = wanted[:limit]
    return shown, len(wanted) - len(shown)


# ── Shared context block ──────────────────────────────────────────────────────

# ── Lint ──────────────────────────────────────────────────────────────────────

# An entry is a rule, not a design document. Past these, it is being used as one.
# These are deliberately looser than the guidance in the skill: style advice aims at
# one or two sentences, the linter only flags what is egregious. A linter that fires
# on most of a real file gets ignored, and then it catches nothing at all.
MAX_ENTRY_LINES = 8
MAX_STATEMENT_WORDS = 120
MAX_AREA_ENTRIES = 25
NEAR_DUPLICATE_RATIO = 0.6

TRIVIAL_STATUS_RE = re.compile(r"^Status:\s*Active\s*(\(\s*\d{4}-\d{2}-\d{2}\s*\))?\s*$")
# Anything that looks like it was MEANT to be a decision ID. Deliberately loose: an ID
# that does not fit the grammar used to vanish in silence -- not parsed, not counted,
# not reported -- so a lowercase "dec" typo could lose a binding decision permanently.
_ID_ISH_RE = re.compile(r"^[ \t]*(dec[-_][^\s:]*)\s*:", re.MULTILINE | re.IGNORECASE)
_SOURCE_EXTENSIONS = (
    "gd", "tscn", "tres", "gdshader", "py", "js", "jsx", "mjs", "cjs", "ts", "tsx",
    "rb", "go", "rs", "lua", "sh", "ps1", "json", "cfg",
)
# Applied to ONE whitespace-separated word at a time, not to a whole statement. Run
# across a long statement, a greedy class that also matches the dot it is anchored on
# ([\w./\\-]+\.) backtracks exponentially: a single 20 KB entry of "a.a.a..." hung the
# post-edit hook past its timeout.
_FILENAME_WORD_RE = re.compile(
    r"^[\w/\\-]{1,60}(?:\.[\w/\\-]{1,20}){0,4}\.(?:%s)[.,;:)]?$" % "|".join(_SOURCE_EXTENSIONS),
    re.IGNORECASE)
_CALL_WORD_RE = re.compile(r"^\w{1,60}\(\)[.,;:]?$")
_IDENTIFIER_WORD_RE = re.compile(r"^[a-z]{1,30}(?:_[a-z]{1,30}){2,}$")
_FINGERPRINT_WORD_TESTS = (
    (_FILENAME_WORD_RE, "a file name"),
    (_CALL_WORD_RE, "a function call"),
    (_IDENTIFIER_WORD_RE, "a code identifier"),
)
# Comparing every statement against every other is quadratic. On a real-sized file that
# is fine; on a large one it blew straight past the hook's timeout, so the comparison is
# confined to one area at a time and skipped for any area too big to afford it.
NEAR_DUPLICATE_MAX_AREA = 250
NEAR_DUPLICATE_PAIR_BUDGET = 60000
NEAR_DUPLICATE_MAX_TOKENS = 60


def _fingerprint(statement):
    """(matched text, label) for the first code fingerprint in a statement, or None."""
    for word in statement.split():
        for pattern, label in _FINGERPRINT_WORD_TESTS:
            if pattern.match(word):
                shown = word.rstrip(".,;:")
                # Only strip a closing paren that is punctuation. A function call ends
                # in one, and reporting `spawn_boss(` helps nobody.
                if shown.endswith(")") and "(" not in shown:
                    shown = shown[:-1]
                return shown, label
    return None


def _line_lookup(text):
    """Return offset -> 1-based line number, in log time.

    The obvious `text[:pos].count("\\n") + 1` re-scans the file from the top for every
    single match, which is quadratic in the file size. On a large decisions file that,
    not the duplicate scan, was where the seconds actually went.
    """
    starts = [0]
    pos = text.find("\n")
    while pos != -1:
        starts.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return lambda offset: bisect.bisect_right(starts, offset)


def lint_decisions(path):
    """Check DECISIONS.md. Returns (errors, warnings) as lists of message strings.

    Errors are format violations, including every leftover of the pre-2.0 format:
    a `Status:` line, or an override-suffix ID. Warnings are bloat signals -- entries
    growing into design documents, near-duplicates, oversized areas.
    """
    text = read_decisions_text(path)
    if text is None:
        return (["cannot read %s" % path], [])

    errors, warnings = [], []
    if not is_valid_utf8(path):
        errors.append(
            "the file is not valid UTF-8 -- some characters were read as replacements. "
            "Re-save it as UTF-8 (a Windows editor defaulting to the system codepage is "
            "the usual cause)."
        )

    line_of = _line_lookup(text)

    for m in LEGACY_STATUS_RE.finditer(text):
        line_no = line_of(m.start())
        errors.append(
            "line %d: `Status:` lines are no longer part of the format -- delete this line. "
            "Every entry in the file is binding; git holds the history. "
            "Run --lint --write to remove the plain ones automatically." % line_no
        )

    for m in LEGACY_SUFFIX_ID_RE.finditer(text):
        line_no = line_of(m.start())
        parent = re.sub(r"[a-z]$", "", m.group(1))
        errors.append(
            "line %d: %s uses the retired override-suffix form. Fold its rule into %s, "
            "edit that entry in place, and delete this one." % (line_no, m.group(1), parent)
        )

    _, unclosed_fence = _blank_fenced_blocks(text.split("\n"))
    if unclosed_fence:
        errors.append(
            "line %d: a code fence is opened here and never closed. Everything after it "
            "would be read as part of the fence, so close it (or delete it) -- an "
            "unclosed fence is how a decision stops being binding without anyone "
            "noticing." % unclosed_fence)

    for m in _ID_ISH_RE.finditer(text):
        dec_id = m.group(1)
        if re.match(r"^DEC-[A-Z]+-\d+$", dec_id) or re.match(r"^DEC-[A-Z]+-\d+[a-z]$", dec_id):
            continue
        line_no = line_of(m.start())
        errors.append(
            "line %d: `%s` looks like a decision but does not parse as one, so it is "
            "not binding and nothing else will mention it again. Expected "
            "DEC-<AREA>-<NNN>, with an uppercase area and a number."
            % (line_no, dec_id))

    decisions = parse_decisions(path)
    seen = {}
    for d in decisions:
        if d.id in seen:
            errors.append("line %d: duplicate ID %s (first seen at line %d)"
                          % (d.line_no, d.id, seen[d.id]))
        seen[d.id] = d.line_no
        if not d.statement:
            errors.append("line %d: %s has no statement" % (d.line_no, d.id))

    for d in decisions:
        if d.line_count > MAX_ENTRY_LINES:
            warnings.append(
                "line %d: %s is %d lines. A decision is a rule, not a design document -- "
                "state the rule and cut the rest." % (d.line_no, d.id, d.line_count)
            )
        words = len(d.statement.split())
        if words > MAX_STATEMENT_WORDS:
            warnings.append(
                "line %d: %s states its rule in %d words. Past ~%d an entry is usually "
                "several rules wearing one ID -- split it, or cut it back to the rule."
                % (d.line_no, d.id, words, MAX_STATEMENT_WORDS)
            )
        hit = _fingerprint(d.statement)
        if hit:
            warnings.append(
                "line %d: %s names %s (`%s`) in its statement. Decisions record intent; "
                "implementation belongs in a code comment citing %s."
                % (d.line_no, d.id, hit[1], hit[0], d.id)
            )

    for area, count in sorted(areas_with_counts(decisions).items()):
        if count > MAX_AREA_ENTRIES:
            warnings.append(
                "area %s holds %d decisions. Past ~%d an area stops being memory and starts "
                "being noise -- consider whether some are dead and can be deleted."
                % (area.upper(), count, MAX_AREA_ENTRIES)
            )

    by_area = {}
    for d in decisions:
        by_area.setdefault(d.area, []).append(d)
    # A per-area cap bounds each area but not their number, and long statements make
    # every comparison dearer -- 12 areas of 250 entries at a realistic 80 words each
    # still ran to 6.7s, past the hook's timeout. So the whole scan works to one budget
    # and stops when it is spent, rather than trusting any single limit.
    budget = NEAR_DUPLICATE_PAIR_BUDGET
    skipped = []
    for area, group in sorted(by_area.items()):
        pairs = len(group) * (len(group) - 1) // 2
        if len(group) > NEAR_DUPLICATE_MAX_AREA or pairs > budget:
            skipped.append("%s (%d)" % (area.upper(), len(group)))
            continue
        budget -= pairs
        tokens = [(d, set(list(tokenize(d.statement))[:NEAR_DUPLICATE_MAX_TOKENS]))
                  for d in group]
        for i in range(len(tokens)):
            d_a, t_a = tokens[i]
            if len(t_a) < 4:
                continue
            for j in range(i + 1, len(tokens)):
                d_b, t_b = tokens[j]
                if len(t_b) < 4:
                    continue
                union = t_a | t_b
                if union and len(t_a & t_b) / float(len(union)) >= NEAR_DUPLICATE_RATIO:
                    warnings.append(
                        "line %d: %s says nearly the same thing as %s (line %d). Keep one."
                        % (d_b.line_no, d_b.id, d_a.id, d_a.line_no)
                    )
    if skipped:
        warnings.append(
            "near-duplicate checking was skipped for %s -- too many entries to compare "
            "without stalling the editor." % ", ".join(skipped))

    return errors, warnings


def strip_trivial_status_lines(path):
    """Remove `Status: Active` / `Status: Active (date)` lines. Returns (removed, kept).

    Only the lines that carry no information beyond "this entry exists" are touched.
    A Status line with prose in it -- a revision log, a Retired marker -- is left
    alone, because deciding what survives that text is a judgement call.
    """
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            raw = fh.read()
    except OSError:
        return (0, 0)
    except (UnicodeDecodeError, ValueError):
        # Rewriting a file we could not fully decode would replace the bytes we could
        # not read with question marks. Refuse; --lint already reports the encoding.
        return (0, 0)

    # Split into lines that KEEP their own terminator, so every surviving line is
    # written back byte for byte. Rebuilding the file from stripped lines would
    # rewrite its line endings and turn a 15-line deletion into a whole-file diff.
    kept, removed, kept_status = [], 0, 0
    for chunk in re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", raw):
        body = chunk.rstrip("\r\n")
        if LEGACY_STATUS_RE.match(body):
            if TRIVIAL_STATUS_RE.match(body.strip()):
                removed += 1
                continue
            kept_status += 1
        kept.append(chunk)
    if removed:
        _write_atomic(path, "".join(kept))
    return (removed, kept_status)


def build_binding_lines(project_root):
    """The orientation block, or None when the project has no DECISIONS.md.

    Emitted ONCE at SessionStart and again through compaction -- not on every prompt.
    The per-edit serve hook carries the actual decision content.
    """
    path = find_decisions_md(project_root)
    if not path:
        return None
    overview = get_overview(parse_decisions(path))
    lines = [
        "[DECISIONS] This project has binding design decisions. Code and tests must follow them.",
        "  Relevant decisions are shown to you automatically before your first edit in each area.",
        "  To look them up yourself: /decisions-md:decisions --area <area> | --query <keywords>",
        "  If one contradicts what is being asked, stop and offer: abandon / adapt / override.",
    ]
    if overview:
        lines.append("  On file: %s" % overview)
    return lines
