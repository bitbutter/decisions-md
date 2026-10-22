/**
 * The verb layer: one plain function per verb, shared by the CLI and by any
 * adapter that imports core in process. Contracts: docs/ADAPTERS.md §5.
 *
 * Each returns an Envelope: an action, the text a harness may deliver, a stable
 * code, and verb-specific details. No harness vocabulary appears here.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { findDecisionsFile, parseDecisions, readDecisionsFile } from "./parse.ts";
import { entriesForAreas, matchAreas } from "./match.ts";
import { areaCounts, areaListText, overview, queryDecisions, queryText } from "./query.ts";
import { lintFile } from "./lint.ts";
import { archiveSuperseded, checkMigration, writeMigration } from "./migrate.ts";
import {
	isExemptPath,
	isTrackedExtension,
	loadConfig,
} from "./config.ts";
import { isSamePath, isWithinProject, relativePath } from "./paths.ts";
import { homeIsResolvable, projectStateDir } from "./state.ts";
import { ENGINE_VERSION } from "./version.ts";
import { InvalidInput, type Envelope, type Entry, type Issue, type MigrationReport } from "./types.ts";
import {
	areaServed,
	claimBackstop,
	claimServed,
	decisionsTouched,
	markDecisionsTouched,
	recordEdit as recordEditState,
	takeEdits,
} from "./state.ts";

export interface VerbInput {
	root?: string;
	file?: string;
	session?: string;
	area?: string;
	terms?: string;
	mode?: string;
	now?: string;
	/** `doctor` only: the adapter's own name and the harness version it was built against. */
	adapter?: string;
	builtAgainst?: string;
}

function required(value: unknown, name: string): string {
	if (typeof value !== "string" || value.trim() === "") throw new InvalidInput(`${name} is required`);
	return value;
}

function none(code: string, details: Record<string, unknown> = {}, text = ""): Envelope {
	return { action: "none", text, code, details };
}

function fail(code: string, text: string, details: Record<string, unknown> = {}): Envelope {
	return { action: "fail", text, code, details };
}

function decisionsFileFor(root: string): string | null {
	return findDecisionsFile(root);
}

function projectRelative(file: string, root: string): string {
	return relativePath(file, root);
}

// ── text templates ──────────────────────────────────────────────────────────

export function decideText(
	shown: Entry[],
	relPath: string,
	areas: string[],
	withheld: number,
): string {
	const label = areas.length === 1 ? "area" : "areas";
	const lines = [
		`[DECISIONS] ${shown.length} binding decision${shown.length === 1 ? "" : "s"} ${
			shown.length === 1 ? "governs" : "govern"
		} ${relPath} (${label}: ${areas.join(", ")}).`,
		"Read them, then re-run your edit. Nothing else is required to proceed.",
		"",
		...shown.map((entry) => `${entry.id}: ${entry.statement}`),
	];
	if (withheld > 0) {
		lines.push("", `(${withheld} more in ${areas.length === 1 ? "this area" : "these areas"} are not shown.)`);
	}
	lines.push(
		"",
		"If one of these contradicts the change you are about to make, stop and offer the user: abandon / adapt / override. Otherwise just carry on.",
	);
	return lines.join("\n");
}

export function orientText(summary: string): string {
	return [
		"[DECISIONS] This project has binding design decisions. Code and tests must follow them.",
		"  Relevant decisions are shown to you automatically before your first edit in each area.",
		"  If one contradicts what is being asked, stop and offer: abandon / adapt / override.",
		`  On file: ${summary}`,
	].join("\n");
}

export function uncoveredText(paths: string[]): string {
	const shown = paths.slice(0, 5).join(", ") + (paths.length > 5 ? ` (+${paths.length - 5} more)` : "");
	return [
		`This session edited files in territory no decision currently covers: ${shown}.`,
		"",
		"Default answer: no entry is needed. Pure implementation, refactors, bug fixes and anything a user or designer would never notice do not belong in DECISIONS.md.",
		"",
		"Only if the work settled a USER- OR DESIGNER-FACING rule -- what a control does, a balance value, a UX rule, a win condition -- propose ONE entry: the binding statement in a sentence or two, plus a brief why. No file paths, no function names, no account of how a bug was found. Before proposing it, check existing decisions and name the one you checked against.",
		"",
		"If no entry is needed, reply with exactly this line and nothing else:",
		"No DECISIONS.md change needed.",
	].join("\n");
}

function issueLine(issue: Issue): string {
	return `  - ${issue.message}`;
}

export function lintText(errors: Issue[], warnings: Issue[]): string {
	if (errors.length === 0 && warnings.length === 0) {
		return "Clean: format is current and nothing looks bloated.";
	}
	const lines: string[] = [];
	if (errors.length > 0) {
		lines.push(`ERRORS (${errors.length}) -- the file is not in the current format:`);
		lines.push(...errors.map(issueLine));
	}
	if (warnings.length > 0) {
		if (lines.length > 0) lines.push("");
		lines.push(`WARNINGS (${warnings.length}) -- bloat signals, not format breaks:`);
		lines.push(...warnings.map(issueLine));
	}
	if (errors.length === 0) lines.push("", "Format is current.");
	return lines.join("\n");
}

function migrationText(report: MigrationReport): string {
	const lines: string[] = [];
	if (report.trivialStatus > 0) lines.push(`${report.trivialStatus} plain \`Status:\` line(s) can be removed automatically.`);
	if (report.superseded.length > 0) {
		lines.push(`${report.superseded.length} superseded record(s) can be archived:`);
		for (const record of report.superseded) {
			lines.push(`  ${record.id} -> ${record.successor ?? "(no successor named)"}`);
		}
	}
	if (report.nontrivialStatus > 0) {
		lines.push(
			`${report.nontrivialStatus} \`Status:\` line(s) carry extra text -- move anything still true into the statement above, then delete the line by hand.`,
		);
	}
	if (report.formatErrors > 0) lines.push(`${report.formatErrors} format error(s) remain. See lint.`);
	if (lines.length === 0) return "Clean: nothing to migrate.";
	return lines.join("\n");
}

// ── verbs ───────────────────────────────────────────────────────────────────

export function decide(input: VerbInput): Envelope {
	const root = required(input.root, "root");
	const file = required(input.file, "file");

	const decisionsFile = decisionsFileFor(root);
	if (!decisionsFile) return none("no_decisions_file");
	const config = loadConfig(root);
	if (!config.enabled) return none("disabled_by_config");
	if (!isWithinProject(file, root)) return none("outside_project");
	if (!isTrackedExtension(file, config.trackedExtensions)) return none("untracked_extension");

	const rel = projectRelative(file, root);
	if (isExemptPath(file, rel, config.exemptPaths, decisionsFile)) return none("exempt_path");

	const session = input.session?.trim();
	if (!session) return none("no_session");

	const read = readDecisionsFile(decisionsFile);
	if (!read) return none("no_decisions_file");
	const entries = parseDecisions(read.text);
	if (entries.length === 0) return none("no_entries");

	const matched = matchAreas(entries, rel, config.areaMap);
	if (matched.length === 0) return none("no_matching_area");

	// An area whose entries all have empty statements has nothing to serve. Drop it
	// before claiming, so a wasted claim cannot silence the area for the session.
	const servable = matched.filter((area) =>
		entries.some((entry) => entry.area === area && entry.statement !== ""),
	);
	if (servable.length === 0) return none("no_matching_area");

	if (servable.every((area) => areaServed(root, session, area))) return none("already_served");

	// Claim before emitting: a block must never outlive a claim that failed, or it
	// repeats forever. Losing the claim means someone else serves it.
	const fresh = servable.filter((area) => claimServed(root, session, area));
	if (fresh.length === 0) return none("already_served");

	const { shown, withheld } = entriesForAreas(entries, fresh);
	if (shown.length === 0) return none("no_matching_area");

	return {
		action: "inject",
		text: decideText(shown, rel, fresh, withheld),
		code: "served",
		details: {
			decisionsFile: projectRelative(decisionsFile, root),
			areas: fresh,
			ids: shown.map((entry) => entry.id),
			withheld,
		},
	};
}

export function orient(input: VerbInput): Envelope {
	const root = required(input.root, "root");
	const decisionsFile = decisionsFileFor(root);
	if (!decisionsFile) return none("no_decisions_file");
	const config = loadConfig(root);
	if (!config.enabled) return none("disabled_by_config");
	const read = readDecisionsFile(decisionsFile);
	if (!read) return none("no_decisions_file");
	const entries = parseDecisions(read.text);
	if (entries.length === 0) return none("no_entries");
	return {
		action: "inject",
		text: orientText(overview(entries)),
		code: "oriented",
		details: { decisionsFile: projectRelative(decisionsFile, root), entries: entries.length },
	};
}

export function recordEdit(input: VerbInput): Envelope {
	const root = required(input.root, "root");
	const file = required(input.file, "file");
	const decisionsFile = decisionsFileFor(root);
	if (!decisionsFile) return none("no_decisions_file");
	const config = loadConfig(root);
	if (!config.enabled) return none("disabled_by_config");
	if (!isWithinProject(file, root)) return none("outside_project");
	const session = input.session?.trim();
	if (!session) return none("no_session");

	const rel = projectRelative(file, root);
	// The decisions file itself is exempt as a serve target, but it is exactly what
	// the backstop needs to know about, so it is recognised before the extension
	// test (its .md extension is usually not tracked).
	if (isSamePath(file, decisionsFile)) {
		markDecisionsTouched(root, session);
		return none("recorded_decisions_file", { path: rel });
	}
	if (!isTrackedExtension(file, config.trackedExtensions)) return none("untracked_extension", { path: rel });
	if (isExemptPath(file, rel, config.exemptPaths, decisionsFile)) return none("exempt_path", { path: rel });

	recordEditState(root, session, rel);
	return none("recorded", { path: rel });
}

export function uncovered(input: VerbInput): Envelope {
	const root = required(input.root, "root");
	const decisionsFile = decisionsFileFor(root);
	if (!decisionsFile) return none("no_decisions_file");
	const config = loadConfig(root);
	if (!config.enabled) return none("disabled_by_config");
	const session = input.session?.trim();
	if (!session) return none("no_session");
	if (decisionsTouched(root, session)) return none("decisions_touched");

	const pending = takeEdits(root, session);
	if (pending.length === 0) return none("no_pending_edits");

	const read = readDecisionsFile(decisionsFile);
	const entries = read ? parseDecisions(read.text) : [];
	const uncoveredPaths = pending.filter((rel) => matchAreas(entries, rel, config.areaMap).length === 0);
	if (uncoveredPaths.length === 0) return none("all_covered");

	if (!claimBackstop(root, session)) return none("already_asked");

	return {
		action: "inject",
		text: uncoveredText(uncoveredPaths),
		code: "uncovered_edits",
		details: { paths: uncoveredPaths },
	};
}

export function query(input: VerbInput): Envelope {
	const root = required(input.root, "root");
	const decisionsFile = decisionsFileFor(root);
	if (!decisionsFile) return none("no_decisions_file");
	const read = readDecisionsFile(decisionsFile);
	if (!read) return none("no_decisions_file");
	const entries = parseDecisions(read.text);
	const area = input.area?.trim();
	const terms = input.terms?.trim();

	if (!area && !terms) {
		return none("areas_listed", { areas: areaCounts(entries) }, areaListText(entries));
	}
	if (area && !entries.some((entry) => entry.area === area.toLowerCase())) {
		return none("unknown_area", {}, `Unknown area: ${area}\n\n${areaListText(entries)}`);
	}

	const { results, total } = queryDecisions(entries, { area, terms });
	if (total === 0) {
		const what = area && terms ? `area ${area} with keywords '${terms}'` : area ? `area ${area}` : `'${terms ?? ""}'`;
		return none("no_match", {}, `No decision matches ${what}.\n\n${areaListText(entries)}`);
	}

	const session = input.session?.trim();
	if (session) {
		for (const served of new Set(results.map((entry) => entry.area))) claimServed(root, session, served);
	}

	return none(
		"found",
		{
			areas: [...new Set(results.map((entry) => entry.area))],
			ids: results.map((entry) => entry.id),
			total,
			shown: results.length,
		},
		queryText(entries, { area, terms }),
	);
}

export function lint(input: VerbInput): Envelope {
	const root = required(input.root, "root");
	const target = input.file?.trim() || decisionsFileFor(root);
	if (!target) return none("no_decisions_file");

	const result = lintFile(target);
	if (result.errors.length === 1 && result.errors[0]?.code === "unreadable") {
		return fail("unreadable", result.errors[0].message, { entries: 0 });
	}
	const details = {
		entries: result.entries,
		errors: result.errors,
		warnings: result.warnings,
		counts: { errors: result.errors.length, warnings: result.warnings.length },
	};
	const text = lintText(result.errors, result.warnings);
	return result.errors.length > 0
		? { action: "block", text, code: "format_errors", details }
		: none("clean", details, text);
}

export function migrate(input: VerbInput): Envelope {
	const root = required(input.root, "root");
	const target = input.file?.trim() || decisionsFileFor(root);
	if (!target) return none("no_decisions_file");
	const mode = input.mode ?? "check";

	if (mode === "check") {
		const report = checkMigration(target);
		const pending =
			report.trivialStatus > 0 || report.superseded.length > 0 || report.formatErrors > 0 || report.nontrivialStatus > 0;
		const text = migrationText(report);
		return pending
			? { action: "block", text, code: "needs_migration", details: { ...report } }
			: none("clean", { ...report }, "Clean: nothing to migrate.");
	}

	if (mode === "write") {
		const result = writeMigration(target);
		const parts: string[] = [];
		if (result.removed > 0) parts.push(`Removed ${result.removed} plain \`Status:\` line(s).`);
		if (result.kept > 0) {
			parts.push(
				`Left ${result.kept} \`Status:\` line(s) that carry extra text -- fold anything worth keeping into the statement, then delete by hand.`,
			);
		}
		if (result.superseded > 0) {
			parts.push(
				`${result.superseded} superseded record(s) are archived by --archive-superseded, not by this command.`,
			);
		}
		const text = parts.length > 0 ? parts.join(" ") : "Nothing to migrate: no \`Status:\` lines.";
		const details = { removed: result.removed, kept: result.kept, superseded: result.superseded };
		return result.changed
			? none("migrated", details, text)
			: none("nothing_to_migrate", details, text);
	}

	if (mode === "archive-superseded") {
		const archiveFile = path.join(root, "support", "decision_archive.md");
		const nowIso = input.now?.trim() || new Date().toISOString();
		const result = archiveSuperseded(target, archiveFile, nowIso);
		if (result.refused) {
			const text =
				result.refused === "archive_refused_no_successor"
					? `Cannot archive: ${result.offendingId ?? "a record"} is marked superseded but names no successor ID. Name the entry that replaced it, then retry.`
					: `Cannot archive: the successor named in the Status line (${result.offendingId ?? "unknown"}) is not an entry in this file. Write the successor first, then retry.`;
			return { action: "block", text, code: result.refused, details: {} };
		}
		if (result.writeFailed) {
			return fail(
				"engine_error",
				`Archived ${result.archived.join(", ")} but could not rewrite ${path.basename(target)}. The archive is written; fix the file's permissions and retry.`,
				{ archived: result.archived.length },
			);
		}
		if (result.archived.length === 0) return none("clean", {}, "No superseded records to archive.");
		return none(
			"archived",
			{ archived: result.archived.length, archiveFile: path.relative(root, archiveFile).split(path.sep).join("/") },
			`Archived ${result.archived.length} record(s) to ${path.relative(root, archiveFile).split(path.sep).join("/")}: ${result.archived.join(", ")}.`,
		);
	}

	throw new InvalidInput(`unknown migrate mode: ${mode}`);
}

export function doctor(input: VerbInput): Envelope {
	const root = required(input.root, "root");
	const decisionsFile = decisionsFileFor(root);
	const checks: { name: string; status: "ok" | "warn" | "fail"; detail: string }[] = [];
	const add = (name: string, status: "ok" | "warn" | "fail", detail: string): void => {
		checks.push({ name, status, detail });
	};

	add("engine", "ok", ENGINE_VERSION);
	add("projectRoot", "ok", root);
	add("decisionsFile", decisionsFile ? "ok" : "warn", decisionsFile ?? "not found -- the engine does nothing here");

	const stateDir = projectStateDir(root);
	let writable = true;
	try {
		fs.mkdirSync(stateDir, { recursive: true });
		const probe = path.join(stateDir, ".doctor-write-probe");
		fs.writeFileSync(probe, "ok");
		fs.unlinkSync(probe);
	} catch {
		writable = false;
	}
	add("stateDir", writable ? "ok" : "fail", writable ? stateDir : `${stateDir} (not writable)`);
	add(
		"stateRoot",
		homeIsResolvable() ? "ok" : "fail",
		homeIsResolvable()
			? "resolved"
			: "the OS gave no home directory, so state fell back to a temp path; set DECISIONS_STATE_DIR",
	);
	add("sessionIdentity", input.session?.trim() ? "ok" : "warn", input.session?.trim() ? "supplied" : "not supplied by this call");
	// Reported, never assumed: an adapter that cannot say who it is may not be the
	// one running, and a missing harness version is a stale badge nobody re-dated.
	add(
		"adapter",
		input.adapter?.trim() ? "ok" : "warn",
		input.adapter?.trim() || "not reported by this call",
	);
	add(
		"harness",
		input.builtAgainst?.trim() ? "ok" : "warn",
		input.builtAgainst?.trim() || "not reported by this call -- the adapter was built against no stated version",
	);

	const failures = checks.filter((check) => check.status === "fail");
	const text = [
		"decisions doctor",
		"",
		...checks.map((check) => `  ${check.status.padEnd(4)} ${check.name}: ${check.detail}`),
		"",
		failures.length === 0 ? "No problems found." : `${failures.length} problem(s): ${failures.map((f) => f.name).join(", ")}`,
	].join("\n");
	return none(failures.length === 0 ? "ok" : "problems", { checks }, text);
}

export const VERBS = {
	decide,
	orient,
	"record-edit": recordEdit,
	uncovered,
	query,
	lint,
	migrate,
	doctor,
} as const;

export type VerbName = keyof typeof VERBS;

/**
 * The envelope boundary: run a verb and turn a throw into a `fail` envelope.
 *
 * Verbs themselves throw InvalidInput on a malformed payload; this is what makes
 * an in-process adapter and a subprocess adapter answer identically, including
 * when the payload is wrong.
 */
export function handle(name: string, input: VerbInput): Envelope {
	if (!Object.prototype.hasOwnProperty.call(VERBS, name)) {
		return { action: "fail", text: `unknown or missing verb: ${name}`, code: "invalid_input", details: {} };
	}
	try {
		return VERBS[name as VerbName](input);
	} catch (error) {
		if (error instanceof InvalidInput) {
			return { action: "fail", text: error.message, code: "invalid_input", details: {} };
		}
		return {
			action: "fail",
			text: error instanceof Error ? error.message : String(error),
			code: "engine_error",
			details: {},
		};
	}
}
