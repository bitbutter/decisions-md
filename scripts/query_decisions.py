#!/usr/bin/env python3
"""Query DECISIONS.md for binding design decisions (plugin read CLI).

Resolves the CONSUMING project (CLAUDE_PROJECT_DIR / cwd marker walk) via the shared
decisions_common helper -- NOT this script's own location -- so it targets the project
even when installed inside a plugin dir. State lives in <project>/.decisions/cache.

Session id resolution order:
  1. DECISIONS_SESSION_ID env var (explicit override for scripted / CI use).
  2. .decisions/cache/current-session-id file (written at SessionStart by the plugin).
  3. Transcript-based lookup for claude -p autonomous workers.
"""
import re, sys, os, argparse
from pathlib import Path
from datetime import datetime

# Import the shared helper from the plugin's hooks/ dir (../hooks relative to scripts/).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks"))
from decisions_common import get_project_root, find_decisions_md, get_cache_dir


class DecisionParser:
    def __init__(self, decisions_path):
        self.decisions_path = decisions_path
        self.decisions = {}
        self.areas = set()
        self._parse()
    def _parse(self):
        if not self.decisions_path.exists():
            raise FileNotFoundError("DECISIONS.md not found")
        content = self.decisions_path.read_text(encoding="utf-8-sig")
        # Accept an optional lowercase suffix letter: DEC-INPUT-007 AND DEC-INPUT-007d
        # are both first-class IDs (a suffix marks an amend/override of the parent).
        # Without the [a-z]? group, suffix entries are silently absorbed into the
        # parent block and become invisible to --query and --validate.
        blocks = re.split(r"^(DEC-[A-Z]+-\d+[a-z]?):", content, flags=re.MULTILINE)[1:]
        for i in range(0, len(blocks), 2):
            if i + 1 >= len(blocks): break
            decision_id = blocks[i].strip()
            block_text = blocks[i + 1].strip()
            area_match = re.match(r"DEC-([A-Z]+)-\d+[a-z]?", decision_id)
            if not area_match: continue
            area = area_match.group(1).lower()
            self.areas.add(area)
            lines = block_text.split("\n")
            statement = lines[0].strip() if lines else ""
            status = "unknown"
            for line in lines:
                m = re.match(r"Status:\s*(.+)$", line)
                if m:
                    status = m.group(1).strip()
                    break
            self.decisions[decision_id] = {"area": area, "statement": statement, "status": status, "full_text": block_text}
    def validate(self):
        issues = []
        for dec_id, dec_data in self.decisions.items():
            if dec_data["status"] == "unknown":
                issues.append(f"Missing Status line for {dec_id}")
        seen_ids = {}
        content = self.decisions_path.read_text(encoding="utf-8-sig")
        for match in re.finditer(r"^(DEC-[A-Z]+-\d+[a-z]?):", content, re.MULTILINE):
            dec_id = match.group(1)
            if dec_id in seen_ids:
                issues.append(f"Duplicate decision ID: {dec_id}")
            seen_ids[dec_id] = True
        return issues
    def get_areas_with_counts(self):
        counts = {}
        for area in self.areas:
            counts[area] = len([d for d in self.decisions.values() if d["area"] == area])
        return counts
    def simple_stem(self, word):
        word = word.lower()
        for suffix in ["ies", "ing", "ed", "ly", "s"]:
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                return word[:-len(suffix)]
        return word
    def search(self, area=None, query=None):
        results = {}
        query_stems = []
        if query:
            query_stems = [self.simple_stem(w) for w in re.split(r"\W+", query.lower()) if w]
        for dec_id, dec_data in self.decisions.items():
            if area and dec_data["area"] != area.lower():
                continue
            if query_stems:
                # Include the ID itself so a query like "007d" matches the suffix entry
                # DEC-INPUT-007d, whose body text does not repeat "007d".
                text = f"{dec_id} {dec_data['statement']} {dec_data['full_text']}".lower()
                stems = [self.simple_stem(w) for w in re.split(r"\W+", text) if w]
                if sum(1 for stem in query_stems if stem in stems) == 0:
                    continue
            results[dec_id] = dec_data
        return results
    def format_results(self, results, show_status=True):
        if not results: return ""
        by_area = {}
        for dec_id, dec_data in sorted(results.items()):
            area = dec_data["area"]
            if area not in by_area: by_area[area] = []
            by_area[area].append((dec_id, dec_data))
        output = []
        for area in sorted(by_area.keys()):
            output.append(f"\n## {area.upper()}\n")
            for dec_id, dec_data in sorted(by_area[area]):
                output.append(f"**{dec_id}**: {dec_data['statement']}")
                if show_status: output.append(f"  Status: {dec_data['status']}")
                output.append("")
        return "\n".join(output)


def _configure_utf8_output():
    # query_decisions prints decision text containing non-cp1252 characters. On Windows
    # the default stdout encoding for a pipe/file is cp1252, so an unguarded print()
    # raises UnicodeEncodeError and CRASHES before create_session_marker runs -- leaving
    # the gate locked. Force utf-8 with a lossy fallback so the unlock marker is always written.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            continue


def create_session_marker(session_id, cache_dir):
    # Fail loud, fail closed: never write a marker we cannot stand behind. A marker named
    # for an unresolved/guessed session id can NEVER match the id decisions_gate.py reads
    # from its own hook payload, so it would wedge the gate. Refuse and exit non-zero.
    if not session_id:
        print(
            "ERROR: could not resolve the Claude Code session id; refusing to write a "
            "decisions-gate unlock marker that could never match the gate (no marker "
            "written). Expected .decisions/cache/current-session-id (written at "
            "SessionStart by the plugin) to exist and be non-empty. If running outside a "
            "Claude Code session, set DECISIONS_SESSION_ID to the gate's session id and retry.",
            file=sys.stderr,
        )
        sys.exit(3)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"decisions-checked-{session_id}").touch()


def write_ack_log(reason, log_dir):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "ack-log.txt"
    ts = datetime.utcnow().isoformat()
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {reason}\n")


def _find_claude_session_id_from_transcripts(project_root):
    """Locate the current Claude Code session ID from the transcripts directory.

    In claude -p mode the session-id env var is not set, so we find it by looking for
    the most recently modified .jsonl in ~/.claude/projects/<encoded-path>/. This matches
    the session_id the gate sees in its input_data.
    """
    try:
        project_path = str(Path(project_root).resolve())
        encoded = project_path.replace(":", "-").replace("\\", "-").replace("/", "-").replace("_", "-")
        if encoded:
            encoded = encoded[0].lower() + encoded[1:]
        projects_dir = Path.home() / ".claude" / "projects" / encoded
        if not projects_dir.exists():
            return None
        jsonl_files = sorted(
            projects_dir.glob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if jsonl_files:
            return jsonl_files[0].stem
    except Exception:
        return None
    return None


def get_session_id(project_root=None):
    # 1. Explicit env override (interactive sessions, scripted / CI use).
    sid = os.environ.get("DECISIONS_SESSION_ID")
    if sid:
        return sid
    # 2. Cache file written verbatim by the SessionStart hook from the gate's own payload.
    if project_root:
        try:
            cache_file = get_cache_dir(project_root)
            if cache_file:
                cache_file = Path(cache_file) / "current-session-id"
                if cache_file.exists():
                    content = cache_file.read_text(encoding="utf-8").strip()
                    if content:
                        return content
        except Exception:
            sid = None  # cache unreadable; fall through to transcript lookup
    # 3. Transcript-based lookup for claude -p autonomous workers.
    if project_root:
        found = _find_claude_session_id_from_transcripts(project_root)
        if found:
            return found
    # 4. Nothing resolved -> return None so the marker writer fails LOUD rather than
    #    minting a marker the gate can never match.
    return None


def _doctor():
    """Report whether the plugin is actually working here. Returns a process exit code.

    A hook whose interpreter cannot be found fails SILENTLY: the plugin still lists,
    the command still autocompletes, and nothing runs. This is the one command that
    says so out loud, on any OS. It is a diagnostic only -- it deliberately does NOT
    write a gate unlock marker.
    """
    failures = []

    def report(status, label, value):
        print(f"  {status:<5} {label}: {value}")
        if status == "FAIL":
            failures.append(label)

    print("decisions-md doctor\n")

    print("Interpreter")
    report("OK", "running this script", sys.executable or "(unknown)")
    report("--", "version", sys.version.split()[0])
    print()

    print("Paths")
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        report("OK" if os.path.isdir(plugin_root) else "FAIL", "CLAUDE_PLUGIN_ROOT", plugin_root)
    else:
        # Unset is normal for a direct CLI run; it is only set for plugin-spawned hooks.
        report("--", "CLAUDE_PLUGIN_ROOT", "not set (normal outside a hook)")
    project_root = get_project_root()
    report("OK", "project root", project_root)

    decisions_md = find_decisions_md(project_root)
    if decisions_md:
        report("OK", "DECISIONS.md", decisions_md)
    else:
        # Not a failure: with no DECISIONS.md the plugin is designed to no-op.
        report("--", "DECISIONS.md", "not found -- gate and nudges intentionally no-op")
    print()

    print("State directory")
    cache_dir = Path(get_cache_dir(project_root))
    if cache_dir.is_dir():
        try:
            probe = cache_dir / ".doctor-write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            report("OK", "cache dir writable", str(cache_dir))
        except OSError as exc:
            report("FAIL", "cache dir writable", f"{cache_dir} ({exc})")
    else:
        # Do NOT create it: a diagnostic must not leave state behind in a project
        # that may not even use this plugin. Check the nearest existing ancestor.
        ancestor = cache_dir
        while not ancestor.exists() and ancestor.parent != ancestor:
            ancestor = ancestor.parent
        writable = os.access(str(ancestor), os.W_OK)
        report("OK" if writable else "FAIL", "cache dir writable",
               f"{cache_dir} (not created yet; {ancestor} is "
               f"{'writable' if writable else 'NOT writable'})")

    sid_file = cache_dir / "current-session-id"
    if sid_file.exists():
        report("OK", "SessionStart hook has run", f"{sid_file.name} present")
    else:
        # THE diagnostic signal. SessionStart writes this in every project, with or
        # without a DECISIONS.md, so its absence means the hooks are not launching --
        # nearly always because the interpreter named in hooks.json is not on PATH.
        report("FAIL", "SessionStart hook has run",
               "current-session-id is MISSING -- hooks are not running in this project. "
               "Most likely the interpreter in hooks/hooks.json is not on PATH here. "
               "Start a new Claude Code session; if it is still missing, check that one "
               "of python3/python/py resolves in your shell.")

    sid = get_session_id(project_root=project_root)
    if sid:
        report("OK", "session id resolves", sid)
    else:
        report("FAIL", "session id resolves",
               "unresolved -- the gate cannot be unlocked until this works")
    print()

    if failures:
        print(f"{len(failures)} problem(s): " + ", ".join(failures))
        return 1
    print("No problems found.")
    return 0


def main():
    _configure_utf8_output()
    parser = argparse.ArgumentParser(description="Query a project's binding DECISIONS.md")
    parser.add_argument("--area", help="Filter by decision area")
    # nargs='*' lets "--query foo bar" collect ["foo", "bar"] without requiring the user
    # to quote the multi-word phrase.  The list is joined with spaces before searching.
    parser.add_argument("--query", nargs='*', help="Search for keywords (multi-word OK without quotes)")
    parser.add_argument("--validate", action="store_true", help="Validate format")
    parser.add_argument("--ack-no-design", metavar="REASON", help="Acknowledge no design")
    parser.add_argument("--doctor", action="store_true",
                        help="Report whether the plugin is actually working here")
    args = parser.parse_args()

    # Runs before the DECISIONS.md check below: a project without one is exactly the
    # case the doctor has to be able to diagnose.
    if args.doctor:
        return _doctor()

    # Normalise --query to a single string (or None).
    query_str = " ".join(args.query).strip() if args.query else None

    project_root = get_project_root()
    decisions_md = find_decisions_md(project_root)
    if not decisions_md:
        print("ERROR: DECISIONS.md not found in the current project "
              "(looked in root, docs/, support/, design/, decisions/).", file=sys.stderr)
        return 1
    decisions_path = Path(decisions_md)
    try:
        dp = DecisionParser(decisions_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    sid = get_session_id(project_root=project_root)
    cache_dir = Path(get_cache_dir(project_root))
    log_dir = Path(project_root) / "logs" / "decisions"

    if args.validate:
        issues = dp.validate()
        if issues:
            print("VALIDATION ISSUES:")
            for issue in issues:
                print(f"  - {issue}")
            return 1
        print("VALIDATION OK: No issues found")
        create_session_marker(sid, cache_dir)
        return 0

    if args.ack_no_design:
        write_ack_log(args.ack_no_design, log_dir)
        create_session_marker(sid, cache_dir)
        print(f"Acknowledged: {args.ack_no_design}")
        return 0

    if args.area and args.area.lower() not in dp.areas:
        print(f"Unknown area: {args.area}")
        print(f"\nValid areas: {', '.join(sorted(dp.areas))}")
        return 0

    if not query_str and not args.area:
        counts = dp.get_areas_with_counts()
        print("Decision Areas and Counts:\n")
        for area in sorted(counts.keys()):
            print(f"  {area}: {counts[area]}")
        create_session_marker(sid, cache_dir)
        return 0

    results = dp.search(area=args.area, query=query_str)

    if not results and query_str:
        if args.area:
            results = dp.search(area=args.area, query=None)
        else:
            results = dp.decisions

    if results:
        output = dp.format_results(results)
        print("[DECISIONS FOUND] Review below; if any DIRECTLY answer the question or DIRECTLY contradict a proposed change, present abandon/adapt/override options to the user.")
        print(output)
        create_session_marker(sid, cache_dir)
        return 0
    else:
        if args.area:
            print(f"No decisions found in area: {args.area}")
        elif query_str:
            print(f"No decisions matching query: {query_str}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
