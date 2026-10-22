/**
 * Migration. Normative rules: spec/FORMAT.md §7.
 *
 * `--write` removes mechanically dead status lines and nothing else.
 * `--archive-superseded` archives first, strips second, and refuses the whole
 * run when a successor is missing: stripping without archiving promotes a dead
 * rule back to binding.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { decodeBytes, normalizeText, parseDecisions, parseId } from "./parse.ts";
import { lintFile } from "./lint.ts";
import type { Entry, MigrationReport } from "./types.ts";

const TRIVIAL_STATUS_RE = /^Status:[ \t]*Active[ \t]*(\([ \t]*\d{4}-\d{2}-\d{2}[ \t]*\))?[ \t]*$/;
const SUPERSEDED_STATUS_RE = /^Status:[ \t]*superseded\b/i;
const STATUS_FIELD = "Status";

const ARCHIVE_PREAMBLE =
	"# Decision archive\n\nRecords moved out of DECISIONS.md are not binding. Git holds the full history.\n";

interface RawFile {
	/** Lines including their own terminators, so survivors are written back byte for byte. */
	chunks: string[];
	bodies: string[];
	validUtf8: boolean;
}

function readRaw(file: string): RawFile | null {
	let bytes: Buffer;
	try {
		bytes = fs.readFileSync(file);
	} catch {
		return null;
	}
	const { text, validUtf8 } = decodeBytes(bytes);
	let raw = text;
	if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1);
	const chunks = raw.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g) ?? [];
	// The final match of that pattern is always an empty string; drop it so the
	// line indexes line up with split("\n") on the normalised text.
	if (chunks.length > 0 && chunks[chunks.length - 1] === "") chunks.pop();
	return { chunks, bodies: chunks.map((c) => c.replace(/[\r\n]+$/, "")), validUtf8 };
}

function writeAtomic(file: string, text: string): boolean {
	const dir = path.dirname(file);
	const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${Date.now()}.tmp`);
	try {
		fs.mkdirSync(dir, { recursive: true });
		fs.writeFileSync(tmp, text, "utf8");
		fs.renameSync(tmp, file);
		return true;
	} catch {
		try {
			fs.unlinkSync(tmp);
		} catch {
			// nothing to clean
		}
		return false;
	}
}

export interface WriteResult {
	removed: number;
	/** Status lines that carry text and are not superseded: a human's job. */
	kept: number;
	/** Superseded records, which `archive-superseded` handles. */
	superseded: number;
	changed: boolean;
}

/**
 * Remove trivial `Status:` lines. Only lines that carry no information beyond
 * "this entry exists" are touched: a Status line with prose in it is frequently
 * where the migrated statement ended up, and deleting it destroys a rule.
 */
export function writeMigration(file: string): WriteResult {
	const raw = readRaw(file);
	if (!raw || !raw.validUtf8) return { removed: 0, kept: 0, superseded: 0, changed: false };

	const keptChunks: string[] = [];
	let removed = 0;
	let kept = 0;
	let superseded = 0;
	for (let i = 0; i < raw.chunks.length; i += 1) {
		const body = (raw.bodies[i] ?? "").trim();
		if (/^Status:/.test(body)) {
			if (TRIVIAL_STATUS_RE.test(body)) {
				removed += 1;
				continue;
			}
			if (SUPERSEDED_STATUS_RE.test(body)) superseded += 1;
			else kept += 1;
		}
		keptChunks.push(raw.chunks[i] as string);
	}
	if (removed === 0) return { removed: 0, kept, superseded, changed: false };
	const wrote = writeAtomic(file, keptChunks.join(""));
	return { removed: wrote ? removed : 0, kept, superseded, changed: wrote };
}

interface SupersededRecord {
	entry: Entry;
	successorId: string | null;
	/** Index range into the raw lines: [start, end], both inclusive, non-blank. */
	start: number;
	end: number;
}

/** Entries carrying `Status: Superseded ...`, with the successor they name. */
export function supersededRecords(text: string): { entry: Entry; successorId: string | null }[] {
	const out: { entry: Entry; successorId: string | null }[] = [];
	for (const entry of parseDecisions(text)) {
		const field = entry.fields.find((f) => f.key === STATUS_FIELD && /^superseded\b/i.test(f.value.trim()));
		if (!field) continue;
		out.push({ entry, successorId: findSuccessor(entry, field.value) });
	}
	return out;
}

function findSuccessor(entry: Entry, statusValue: string): string | null {
	for (const candidate of statusValue.match(/DEC-[A-Z0-9_-]+/g) ?? []) {
		if (parseId(candidate)) return candidate;
	}
	const byPhrase = /Superseded by\s+(DEC-[A-Z0-9_-]+)/i.exec(entry.statement);
	if (byPhrase?.[1] && parseId(byPhrase[1])) return byPhrase[1];
	return null;
}

function normalizedTextOf(raw: RawFile): string {
	return normalizeText(raw.bodies.length > 0 ? `${raw.bodies.join("\n")}\n` : "");
}

/** What a migration run would do, without touching anything. */
export function checkMigration(file: string): MigrationReport {
	const raw = readRaw(file);
	const report: MigrationReport = {
		trivialStatus: 0,
		nontrivialStatus: 0,
		superseded: [],
		formatErrors: lintFile(file).errors.length,
	};
	if (!raw) return report;

	for (const body of raw.bodies) {
		const line = body.trim();
		if (!/^Status:/.test(line)) continue;
		if (TRIVIAL_STATUS_RE.test(line)) report.trivialStatus += 1;
		else if (!SUPERSEDED_STATUS_RE.test(line)) report.nontrivialStatus += 1;
	}
	report.superseded = supersededRecords(normalizedTextOf(raw)).map((record) => ({
		line: record.entry.line,
		id: record.entry.id,
		successor: record.successorId,
	}));
	return report;
}

export interface ArchiveResult {
	archived: string[];
	refused?: "archive_refused_no_successor" | "archive_refused_missing_successor";
	offendingId?: string;
	archiveFile?: string;
	/** The archive was written but DECISIONS.md could not be rewritten. */
	writeFailed?: boolean;
}

/** Move superseded records into the archive, then remove them. */
export function archiveSuperseded(file: string, archiveFile: string, nowIso: string): ArchiveResult {
	const raw = readRaw(file);
	if (!raw || !raw.validUtf8) return { archived: [] };
	const text = normalizedTextOf(raw);
	const entries = parseDecisions(text);
	const byId = new Set(entries.map((e) => e.id));

	const records: SupersededRecord[] = [];
	for (const { entry, successorId } of supersededRecords(text)) {
		if (successorId === null) {
			return { archived: [], refused: "archive_refused_no_successor", offendingId: entry.id };
		}
		if (!byId.has(successorId)) {
			return { archived: [], refused: "archive_refused_missing_successor", offendingId: successorId };
		}
		records.push({ entry, successorId, start: entry.line - 1, end: entry.line - 1 });
	}
	if (records.length === 0) return { archived: [] };

	// The block runs from the ID line to the last non-blank line before the next
	// entry (or end of file). Blank lines inside the block are kept verbatim.
	const starts = new Set(entries.map((e) => e.line - 1));
	for (const record of records) {
		let end = record.start;
		for (let i = record.start; i < raw.bodies.length; i += 1) {
			if (i > record.start && starts.has(i)) break;
			if ((raw.bodies[i] ?? "").trim() !== "") end = i;
		}
		record.end = end;
	}
	records.sort((a, b) => a.start - b.start);

	let existing = "";
	try {
		existing = fs.readFileSync(archiveFile, "utf8");
	} catch {
		existing = ARCHIVE_PREAMBLE;
	}

	// A block already in the archive is not appended twice. That makes a rerun
	// after a failed rewrite safe instead of duplicating history.
	const blocks = records
		.map((r) => raw.bodies.slice(r.start, r.end + 1).join("\n"))
		.filter((block) => !existing.includes(block));
	if (blocks.length > 0) {
		const section = `## Archived ${nowIso} from DECISIONS.md\n\n${blocks.join("\n\n")}\n`;
		const nextArchive = existing.endsWith("\n") ? `${existing}\n${section}` : `${existing}\n\n${section}`;
		if (!writeAtomic(archiveFile, nextArchive)) return { archived: [] };
	}

	// Verify the archive before removing anything: archive first, strip second.
	let written = "";
	try {
		written = fs.readFileSync(archiveFile, "utf8");
	} catch {
		written = "";
	}
	for (const record of records) {
		const block = raw.bodies.slice(record.start, record.end + 1).join("\n");
		if (!written.includes(block)) return { archived: [], archiveFile };
	}

	// Remove [start .. end] plus one following blank line, per record.
	const doomed = new Set<number>();
	for (const record of records) {
		for (let i = record.start; i <= record.end; i += 1) doomed.add(i);
		const after = record.end + 1;
		if (after < raw.chunks.length && (raw.bodies[after] ?? "").trim() === "") doomed.add(after);
	}
	const remaining = raw.chunks.filter((_, i) => !doomed.has(i)).join("");
	const archivedIds = records.map((r) => r.entry.id);
	if (!writeAtomic(file, remaining)) {
		return { archived: archivedIds, archiveFile, writeFailed: true };
	}
	return { archived: archivedIds, archiveFile };
}
