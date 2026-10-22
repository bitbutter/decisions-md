/**
 * Format checking. Normative rules: spec/FORMAT.md §6.
 *
 * Errors are format violations and block. Warnings are bloat signals, never
 * block, and are never auto-edited.
 */

import { blankFencedBlocks, isLegacySuffixId, parseDecisions, parseId, readDecisionsFile } from "./parse.ts";
import { tokenize } from "./match.ts";
import type { Entry, Issue } from "./types.ts";

export const MAX_ENTRY_LINES = 8;
export const MAX_STATEMENT_WORDS = 120;
export const MAX_AREA_ENTRIES = 25;
export const NEAR_DUPLICATE_RATIO = 0.6;
export const NEAR_DUPLICATE_MAX_AREA = 250;
export const NEAR_DUPLICATE_PAIR_BUDGET = 60000;
export const NEAR_DUPLICATE_MAX_TOKENS = 60;

const STATUS_LINE_RE = /^Status:/;
/** The leading ID-shaped token, at any indentation. */
const ID_TOKEN_RE = /^([ \t]*)(DEC[-_][^\s:]*)[ \t]*:/i;
/** The same, with one extra token before the colon: "DEC-INPUT 003: ...". */
const ID_TOKEN_SPACED_RE = /^[ \t]*DEC[-_][^\s:]*[ \t]+[^\s:]+[ \t]*:/i;

const SOURCE_EXTENSIONS = "gd|tscn|tres|gdshader|py|js|jsx|mjs|cjs|ts|tsx|rb|go|rs|lua|sh|ps1|json|cfg";
const FILENAME_WORD_RE = new RegExp(
	`^[\\w/\\\\-]{1,60}(?:\\.[\\w/\\\\-]{1,20}){0,4}\\.(?:${SOURCE_EXTENSIONS})[.,;:)]?$`,
	"i",
);
const CALL_WORD_RE = /^\w{1,60}\(\)[.,;:]?$/;
const IDENTIFIER_WORD_RE = /^[a-z]{1,30}(?:_[a-z]{1,30}){2,}$/;

export interface LintResult {
	errors: Issue[];
	warnings: Issue[];
	entries: number;
}

function lineOf(text: string, offset: number): number {
	let line = 1;
	for (let i = 0; i < offset && i < text.length; i += 1) if (text[i] === "\n") line += 1;
	return line;
}

/** (matched text, label) for the first code fingerprint in a statement. */
function fingerprint(statement: string): { shown: string; label: string } | null {
	for (const word of statement.split(/\s+/)) {
		for (const [re, label] of [
			[FILENAME_WORD_RE, "a file name"],
			[CALL_WORD_RE, "a function call"],
			[IDENTIFIER_WORD_RE, "a code identifier"],
		] as const) {
			if (!re.test(word)) continue;
			let shown = word.replace(/[.,;:]+$/, "");
			// A function call ends in a paren that is part of the call, not punctuation.
			if (shown.endsWith(")") && !shown.includes("(")) shown = shown.slice(0, -1);
			return { shown, label };
		}
	}
	return null;
}

/**
 * Find lines that look like decisions but are not entries.
 *
 * Two shapes: the leading token at any indentation (an indented valid ID is
 * reported, because an indented entry is not an entry), and one extra token
 * before the colon (a space where the hyphen belongs). The second shape allows
 * only one extra token, so a wrapped statement line that merely mentions an ID
 * is not reported.
 */
function scanIdShapedLines(text: string, errors: Issue[]): void {
	const lines = text.split("\n");
	for (let i = 0; i < lines.length; i += 1) {
		const line = lines[i] ?? "";
		const lineNo = i + 1;
		const token = ID_TOKEN_RE.exec(line);
		if (token && token[2] !== undefined) {
			const indent = (token[1] ?? "").length;
			const id = token[2];
			if (parseId(id) !== null) {
				if (indent > 0) {
					errors.push({
						code: "malformed_id",
						line: lineNo,
						message: `line ${lineNo}: \`${id}\` starts an entry but is indented, so it is read as part of the entry above instead of an entry of its own. Start it at column 0.`,
					});
				}
				continue;
			}
			if (isLegacySuffixId(id)) {
				errors.push({
					code: "override_suffix_id",
					line: lineNo,
					message: `line ${lineNo}: ${id} uses the retired override-suffix form. Fold its rule into ${id.slice(0, -1)}, edit that entry in place, and delete this one.`,
				});
				continue;
			}
			errors.push({
				code: "malformed_id",
				line: lineNo,
				message: `line ${lineNo}: \`${id}\` looks like a decision but does not parse as one, so it is not binding and nothing else will mention it again. Expected DEC-<AREA>-<NNN>, with uppercase areas of two or more letters and a three-digit number.`,
			});
			continue;
		}
		if (ID_TOKEN_SPACED_RE.test(line)) {
			const shown = line.trim().split(":")[0] ?? "";
			errors.push({
				code: "malformed_id",
				line: lineNo,
				message: `line ${lineNo}: \`${shown}\` looks like a decision but has a space inside the identifier, so it is not binding and nothing else will mention it again. Areas are hyphen-separated, e.g. DEC-INPUT-001.`,
			});
		}
	}
}

/** Check one file. Issues are ordered by line, file-level first, then by code. */
export function lintFile(file: string): LintResult {
	const read = readDecisionsFile(file);
	if (!read) {
		return {
			errors: [{ code: "unreadable", message: `cannot read ${file}` }],
			warnings: [],
			entries: 0,
		};
	}
	const { text, validUtf8 } = read;
	const errors: Issue[] = [];
	const warnings: Issue[] = [];

	if (!validUtf8) {
		errors.push({
			code: "not_utf8",
			message:
				"the file is not valid UTF-8 -- some characters were read as replacements. Re-save it as UTF-8 (a Windows editor defaulting to the system codepage is the usual cause).",
		});
	}

	for (const match of text.matchAll(/^Status:.*$/gm)) {
		const line = lineOf(text, match.index ?? 0);
		errors.push({
			code: "status_line",
			line,
			message: `line ${line}: \`Status:\` lines are no longer part of the format -- delete this line. Every entry in the file is binding; git holds the history.`,
		});
	}

	const fenceScan = blankFencedBlocks(text.split("\n"));
	if (fenceScan.unclosedFenceLine !== undefined) {
		const line = fenceScan.unclosedFenceLine;
		errors.push({
			code: "unclosed_fence",
			line,
			message: `line ${line}: a code fence is opened here and never closed. An unclosed fence is how a decision stops being binding without anyone noticing, so close it or delete the marker.`,
		});
	}

	scanIdShapedLines(text, errors);

	const entries = parseDecisions(text);
	const seen = new Map<string, number>();
	for (const entry of entries) {
		const first = seen.get(entry.id);
		if (first !== undefined) {
			errors.push({
				code: "duplicate_id",
				line: entry.line,
				message: `line ${entry.line}: duplicate ID ${entry.id} (first seen at line ${first})`,
			});
		} else {
			seen.set(entry.id, entry.line);
		}
		if (entry.statement === "") {
			errors.push({
				code: "missing_statement",
				line: entry.line,
				message: `line ${entry.line}: ${entry.id} has no statement`,
			});
		}
	}

	for (const entry of entries) {
		if (entry.lineCount > MAX_ENTRY_LINES) {
			warnings.push({
				code: "entry_too_long",
				line: entry.line,
				message: `line ${entry.line}: ${entry.id} is ${entry.lineCount} lines. A decision is a rule, not a design document -- state the rule and cut the rest.`,
			});
		}
		const words = entry.statement.split(/\s+/).filter(Boolean).length;
		if (words > MAX_STATEMENT_WORDS) {
			warnings.push({
				code: "statement_too_long",
				line: entry.line,
				message: `line ${entry.line}: ${entry.id} states its rule in ${words} words. Past ~${MAX_STATEMENT_WORDS} an entry is usually several rules wearing one ID -- split it, or cut it back to the rule.`,
			});
		}
		const hit = fingerprint(entry.statement);
		if (hit) {
			warnings.push({
				code: "code_fingerprint",
				line: entry.line,
				message: `line ${entry.line}: ${entry.id} names ${hit.label} (\`${hit.shown}\`) in its statement. Decisions record intent; implementation belongs in a code comment citing ${entry.id}.`,
			});
		}
	}

	const byArea = new Map<string, Entry[]>();
	for (const entry of entries) {
		const group = byArea.get(entry.area);
		if (group) group.push(entry);
		else byArea.set(entry.area, [entry]);
	}

	for (const [area, group] of [...byArea.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
		if (group.length > MAX_AREA_ENTRIES) {
			warnings.push({
				code: "area_too_large",
				message: `area ${area.toUpperCase()} holds ${group.length} decisions. Past ~${MAX_AREA_ENTRIES} an area stops being memory and starts being noise -- consider whether some are dead and can be deleted.`,
			});
		}
	}

	let budget = NEAR_DUPLICATE_PAIR_BUDGET;
	const skipped: string[] = [];
	for (const [area, group] of [...byArea.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
		const pairs = (group.length * (group.length - 1)) / 2;
		if (group.length > NEAR_DUPLICATE_MAX_AREA || pairs > budget) {
			skipped.push(`${area.toUpperCase()} (${group.length})`);
			continue;
		}
		budget -= pairs;
		const tokenSets = group.map((entry) => ({
			entry,
			tokens: new Set([...tokenize(entry.statement)].slice(0, NEAR_DUPLICATE_MAX_TOKENS)),
		}));
		for (let i = 0; i < tokenSets.length; i += 1) {
			const a = tokenSets[i] as { entry: Entry; tokens: Set<string> };
			if (a.tokens.size < 4) continue;
			for (let j = i + 1; j < tokenSets.length; j += 1) {
				const b = tokenSets[j] as { entry: Entry; tokens: Set<string> };
				if (b.tokens.size < 4) continue;
				let shared = 0;
				for (const token of a.tokens) if (b.tokens.has(token)) shared += 1;
				const union = a.tokens.size + b.tokens.size - shared;
				if (union > 0 && shared / union >= NEAR_DUPLICATE_RATIO) {
					warnings.push({
						code: "near_duplicate",
						line: b.entry.line,
						message: `line ${b.entry.line}: ${b.entry.id} says nearly the same thing as ${a.entry.id} (line ${a.entry.line}). Keep one.`,
					});
				}
			}
		}
	}
	if (skipped.length > 0) {
		warnings.push({
			code: "near_duplicate_skipped",
			message: `near-duplicate checking was skipped for ${skipped.join(", ")} -- too many entries to compare without stalling the editor.`,
		});
	}

	const rank = (issue: Issue): number => (issue.line === undefined ? 0 : issue.line);
	errors.sort((a, b) => rank(a) - rank(b) || a.code.localeCompare(b.code));

	return { errors, warnings, entries: entries.length };
}
