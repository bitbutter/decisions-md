/**
 * Reading and parsing DECISIONS.md. Normative rules: spec/FORMAT.md §2-§4.
 *
 * Every reader goes through readDecisionsFile(), so parsing, linting, querying
 * and migration cannot disagree about what the bytes say.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { Entry, Field, ReadResult } from "./types.ts";

/** Conventional locations, in discovery order. First existing file wins. */
export const DECISIONS_SEARCH_SUBDIRS = ["", "docs", "support", "design", "decisions"] as const;

const FIELD_LINE_RE = /^([A-Z][A-Za-z]*)\s*:\s*(.*)$/;
const FENCE_RE = /^\s*(`{3,}|~{3,})/;
const ID_LINE_RE = /^([^\s:]+)\s*:(.*)$/;

/**
 * Strip a leading BOM, CRLF -> LF, and a whole-file CR-only file -> LF.
 *
 * A lone CR in an otherwise LF file is NOT a line break. Folding it in would
 * shift every reported line number after it, and every editor and grep treats
 * it as a stray control character.
 */
export function normalizeText(raw: string): string {
	let text = raw;
	if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
	text = text.replace(/\r\n/g, "\n");
	if (text.includes("\r") && !text.includes("\n")) text = text.replace(/\r/g, "\n");
	return text;
}

/** UTF-8 decode, lenient: invalid bytes become U+FFFD and the caller is told. */
export function decodeBytes(bytes: Uint8Array): ReadResult {
	let validUtf8 = true;
	try {
		new TextDecoder("utf-8", { fatal: true }).decode(bytes);
	} catch {
		validUtf8 = false;
	}
	// Buffer decoding replaces invalid sequences; it does not strip a BOM, which
	// normalizeText does.
	const text = Buffer.from(bytes).toString("utf8");
	return { text, validUtf8 };
}

/** Read, decode and normalise. The only sanctioned way to get decision text. */
export function readDecisionsFile(file: string): ReadResult | null {
	let bytes: Buffer;
	try {
		bytes = fs.readFileSync(file);
	} catch {
		return null;
	}
	const { text, validUtf8 } = decodeBytes(bytes);
	return { text: normalizeText(text), validUtf8 };
}

export interface ParsedId {
	areas: string[];
	number: number;
}

/**
 * The ID grammar: `DEC-<AREA>(-<AREA>)*-<NNN>`, AREA `[A-Z]{2,}`, NNN 3 digits.
 * Returns null for anything else, including every near miss in FORMAT.md §5.3.
 */
export function parseId(id: string): ParsedId | null {
	const m = /^DEC-((?:[A-Z]{2,})(?:-[A-Z]{2,})*)-([0-9]{3})$/.exec(id);
	if (!m || m[1] === undefined || m[2] === undefined) return null;
	return { areas: m[1].split("-"), number: Number(m[2]) };
}

/** The area label: segments lowercased and hyphen-joined. */
export function areaLabel(id: string): string | null {
	const parsed = parseId(id);
	return parsed ? parsed.areas.join("-").toLowerCase() : null;
}

/** Retired override-suffix form, kept only so it can be reported. */
export function isLegacySuffixId(id: string): boolean {
	return /^DEC-[A-Z]+-[0-9]+[a-z]$/.test(id);
}

/**
 * Blank out closed fenced code blocks. Returns the lines and the 1-based line of
 * an unclosed fence marker, if any.
 *
 * An unclosed fence blanks nothing: reporting it and keeping the decisions is
 * safer than silently dropping every rule after it.
 */
export function blankFencedBlocks(lines: string[]): { lines: string[]; unclosedFenceLine?: number } {
	const out = lines.slice();
	let i = 0;
	while (i < out.length) {
		const opening = FENCE_RE.exec(out[i] ?? "");
		if (!opening || opening[1] === undefined) {
			i += 1;
			continue;
		}
		const marker = opening[1];
		let closeAt = -1;
		for (let j = i + 1; j < out.length; j += 1) {
			const closing = FENCE_RE.exec(out[j] ?? "");
			const candidate = closing?.[1];
			if (candidate && candidate[0] === marker[0] && candidate.length >= marker.length) {
				closeAt = j;
				break;
			}
		}
		if (closeAt < 0) return { lines: out, unclosedFenceLine: i + 1 };
		for (let k = i; k <= closeAt; k += 1) out[k] = "";
		i = closeAt + 1;
	}
	return { lines: out };
}

interface IdLine {
	id: string;
	rest: string;
}

/** Recognise an ID line: the prefix sits at column 0 and must be a valid ID. */
export function readIdLine(line: string): IdLine | null {
	const m = ID_LINE_RE.exec(line);
	if (!m || m[1] === undefined) return null;
	if (parseId(m[1]) === null) return null;
	return { id: m[1], rest: m[2] ?? "" };
}

/** Parse the normalised text into entries, in file order. */
export function parseDecisions(text: string): Entry[] {
	const { lines } = blankFencedBlocks(text.split("\n"));

	const starts: number[] = [];
	const ids: string[] = [];
	const rests: string[] = [];
	for (let i = 0; i < lines.length; i += 1) {
		const idLine = readIdLine(lines[i] ?? "");
		if (idLine) {
			starts.push(i);
			ids.push(idLine.id);
			rests.push(idLine.rest);
		}
	}

	const entries: Entry[] = [];
	for (let n = 0; n < starts.length; n += 1) {
		const start = starts[n] as number;
		const end = n + 1 < starts.length ? (starts[n + 1] as number) : lines.length;
		const id = ids[n] as string;
		const first = (rests[n] as string).trim();

		const statementParts: string[] = first ? [first] : [];
		const fields: Field[] = [];
		let inStatement = true;
		let inField = false;
		// Lines this entry actually occupies: its ID line, statement continuations
		// and fields. Prose after the closing blank line is the document's, not the
		// entry's, so it must not make the entry look long.
		let usedLines = 1;

		for (let i = start + 1; i < end; i += 1) {
			const line = (lines[i] ?? "").replace(/\s+$/, "");
			if (line.trim() === "") {
				// A blank line closes the statement AND any open field. Without the
				// second part, every later note joined the last field's value.
				inStatement = false;
				inField = false;
				continue;
			}
			const field = FIELD_LINE_RE.exec(line);
			if (field && field[1] !== undefined) {
				inStatement = false;
				inField = true;
				fields.push({ key: field[1], value: (field[2] ?? "").trim() });
				usedLines += 1;
				continue;
			}
			if (inStatement) {
				statementParts.push(line.trim());
				usedLines += 1;
			} else if (inField) {
				const last = fields[fields.length - 1] as Field;
				last.value = `${last.value} ${line.trim()}`.trim();
				usedLines += 1;
			}
			// Anything else is prose between entries: ignored.
		}

		entries.push({
			id,
			area: areaLabel(id) ?? "",
			statement: statementParts.join(" ").trim(),
			fields,
			line: start + 1,
			lineCount: usedLines,
		});
	}
	return entries;
}

/** Render one entry: `ID: statement`, then each field indented two spaces. */
export function renderEntry(entry: Entry, opts: { withFields?: boolean } = {}): string {
	const withFields = opts.withFields !== false;
	const out = [`${entry.id}: ${entry.statement}`];
	if (withFields) for (const field of entry.fields) out.push(`  ${field.key}: ${field.value}`);
	return out.join("\n");
}

/** Discovery: the first conventional location that holds a file. */
export function findDecisionsFile(root: string): string | null {
	if (!root) return null;
	for (const dir of DECISIONS_SEARCH_SUBDIRS) {
		const candidate = dir ? path.join(root, dir, "DECISIONS.md") : path.join(root, "DECISIONS.md");
		try {
			if (fs.statSync(candidate).isFile()) return candidate;
		} catch {
			// absent is the normal case
		}
	}
	return null;
}
