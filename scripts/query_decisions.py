#!/usr/bin/env python3
"""Read and lint a project's binding DECISIONS.md.

The read path behind /decisions-md:decisions. Resolves the CONSUMING project (via
CLAUDE_PROJECT_DIR or a marker walk) rather than this script's own location, so it
targets your project even though it lives inside a plugin directory.

    query_decisions.py                        areas and counts
    query_decisions.py --query jump input     search
    query_decisions.py --area input           one area in full
    query_decisions.py --lint [--write]       check the format; --write fixes the
                                              mechanical part
    query_decisions.py --doctor               is the plugin actually running here
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks"))
from decisions_common import (  # noqa: E402
    get_project_root, find_decisions_md, get_state_dir, legacy_cache_dir,
    parse_decisions, areas_with_counts, lint_decisions, strip_trivial_status_lines,
    tokenize, get_session_id, claim_area_served, home_is_resolvable, MAX_QUERY_RESULTS,
)


def _configure_utf8_output():
    """Decision text can contain characters cp1252 cannot encode; on Windows an
    unguarded print() would raise UnicodeEncodeError and abort mid-answer."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            continue


def print_areas(decisions):
    counts = areas_with_counts(decisions)
    if not counts:
        print("DECISIONS.md has no entries yet.")
        return
    print("Decision areas (%d total):\n" % sum(counts.values()))
    for area in sorted(counts):
        print("  %-16s %d" % (area, counts[area]))
    print("\nSee one area in full:  --area <area>")
    print("Search across areas:   --query <keywords>")


def search(decisions, area=None, query=None):
    """Decisions matching an area and/or keywords, best match first."""
    pool = [d for d in decisions if not area or d.area == area.lower()]
    if not query:
        return pool
    stems = tokenize(query)
    if not stems:
        return pool
    scored = []
    for d in pool:
        haystack = " ".join([d.id, d.statement] + [v for _, v in d.fields])
        hits = len(stems & tokenize(haystack))
        # An ID typed verbatim is an exact request, not a fuzzy one.
        if query.strip().upper() in d.id:
            hits += 10
        if hits:
            scored.append((hits, d))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [d for _, d in scored]


def print_results(results, label):
    shown = results[:MAX_QUERY_RESULTS]
    print("[DECISIONS] %d found%s. These are binding. If one directly answers the "
          "question or contradicts a proposed change, stop and offer the user: "
          "abandon / adapt / override.\n" % (len(results), label))
    current_area = None
    for d in shown:
        if d.area != current_area:
            current_area = d.area
            print("## %s\n" % d.area.upper())
        print(d.render())
        print("")
    if len(results) > len(shown):
        print("(%d more not shown -- narrow with --area or more specific keywords)"
              % (len(results) - len(shown)))


def mark_served(project_root, areas):
    """Tell the serve hook these areas have been seen, so it does not repeat them."""
    session_id = get_session_id(project_root)
    if not session_id:
        return
    for area in areas:
        claim_area_served(project_root, session_id, area)


def run_lint(decisions_md, write):
    if write:
        removed, kept = strip_trivial_status_lines(decisions_md)
        print("Removed %d plain `Status:` line(s)." % removed)
        if kept:
            print("Left %d `Status:` line(s) that carry extra text -- fold anything worth "
                  "keeping into the statement, then delete the line by hand.\n" % kept)
        else:
            print("")

    errors, warnings = lint_decisions(decisions_md)
    if errors:
        print("ERRORS (%d) -- the file is not in the current format:" % len(errors))
        for e in errors:
            print("  - %s" % e)
        print("")
    if warnings:
        print("WARNINGS (%d) -- bloat signals, not format breaks:" % len(warnings))
        for w in warnings:
            print("  - %s" % w)
        print("")
    if not errors and not warnings:
        print("Clean: format is current and nothing looks bloated.")
    elif not errors:
        print("Format is current.")
    return 1 if errors else 0


def run_doctor(project_root):
    """Say out loud whether the plugin is working here.

    A hook whose interpreter cannot be found fails SILENTLY: the plugin still lists,
    the command still autocompletes, and nothing runs. This is what says so.
    """
    failures = []

    def report(status, label, value):
        print("  %-5s %s: %s" % (status, label, value))
        if status == "FAIL":
            failures.append(label)

    print("decisions-md doctor\n")
    print("Interpreter")
    report("OK", "running this script", sys.executable or "(unknown)")
    report("--", "version", sys.version.split()[0])
    print("\nPaths")

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        report("OK" if os.path.isdir(plugin_root) else "FAIL", "CLAUDE_PLUGIN_ROOT", plugin_root)
    else:
        report("--", "CLAUDE_PLUGIN_ROOT", "not set (normal outside a hook)")
    report("OK", "project root", project_root)

    decisions_md = find_decisions_md(project_root)
    if decisions_md:
        report("OK", "DECISIONS.md", decisions_md)
    else:
        report("--", "DECISIONS.md", "not found -- the plugin intentionally does nothing here")

    print("\nState (outside your project, by design)")
    if not home_is_resolvable():
        report("FAIL", "home directory",
               "the OS did not give one (USERPROFILE/HOME unset or blank). State has "
               "fallen back to a temp directory, so it will not survive a reboot. Set "
               "DECISIONS_STATE_DIR to a real path.")
    state_dir = Path(get_state_dir(project_root))
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".doctor-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report("OK", "state dir writable", str(state_dir))
    except OSError as exc:
        report("FAIL", "state dir writable", "%s (%s)" % (state_dir, exc))

    sid_file = state_dir / "current-session-id"
    if sid_file.exists():
        report("OK", "SessionStart hook has run", "current-session-id present")
    else:
        report("FAIL", "SessionStart hook has run",
               "current-session-id is MISSING -- hooks are not running in this project. "
               "Most likely no python3/python/py resolves on PATH here. Start a new "
               "session; if it is still missing, check your PATH.")

    sid = get_session_id(project_root)
    report("OK" if sid else "--", "session id", sid or "unresolved (hooks will stay quiet)")

    legacy = legacy_cache_dir(project_root)
    if legacy and os.path.isdir(legacy):
        report("--", "legacy state found",
               "%s is left over from an older version and is no longer read. "
               "Safe to delete, along with the .decisions/ .gitignore entry." % legacy)

    print("")
    if failures:
        print("%d problem(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("No problems found.")
    return 0


def main():
    _configure_utf8_output()
    parser = argparse.ArgumentParser(
        description="Read and lint a project's binding DECISIONS.md")
    parser.add_argument("--area", help="Show one decision area in full")
    # nargs='*' lets "--query foo bar" collect both words without the caller quoting.
    parser.add_argument("--query", nargs="*", help="Search for keywords")
    parser.add_argument("--lint", action="store_true", help="Check the file's format")
    parser.add_argument("--write", action="store_true",
                        help="With --lint: remove plain `Status:` lines in place")
    parser.add_argument("--doctor", action="store_true",
                        help="Report whether the plugin is actually running here")
    args = parser.parse_args()

    project_root = get_project_root()

    # Runs before the DECISIONS.md check: a project without one is exactly the case
    # the doctor needs to be able to diagnose.
    if args.doctor:
        return run_doctor(project_root)

    decisions_md = find_decisions_md(project_root)
    if not decisions_md:
        print("ERROR: no DECISIONS.md in this project (looked in the root and in "
              "docs/, support/, design/, decisions/).", file=sys.stderr)
        return 1

    if args.write and not args.lint:
        print("ERROR: --write only means something with --lint.", file=sys.stderr)
        return 2

    if args.lint:
        return run_lint(decisions_md, args.write)

    decisions = parse_decisions(decisions_md)
    query_str = " ".join(args.query).strip() if args.query else None

    if not query_str and not args.area:
        print_areas(decisions)
        return 0

    if args.area and args.area.lower() not in {d.area for d in decisions}:
        print("Unknown area: %s\n" % args.area)
        print_areas(decisions)
        return 0

    results = search(decisions, area=args.area, query=query_str)

    if not results:
        # Deliberately NOT a fallback dump of the whole file: a miss on a large file
        # used to cost hundreds of lines of context for nothing.
        print("No decision matches %s.\n"
              % ("area %s with keywords '%s'" % (args.area, query_str)
                 if args.area and query_str else
                 "'%s'" % query_str if query_str else "area %s" % args.area))
        print_areas(decisions)
        return 0

    label = ""
    if args.area:
        label += " in area %s" % args.area.lower()
    if query_str:
        label += " for '%s'" % query_str
    print_results(results, label)
    mark_served(project_root, sorted({d.area for d in results}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
