/**
 * Matching a project-relative path to decision areas, and the tokenisation both
 * matching and querying use. Contract: docs/ADAPTERS.md §4.2.
 */

import type { Entry } from "./types.ts";

/** Directory and filler words that carry no signal about which area a file is in. */
const PATH_STOPWORDS = new Set([
	"src", "source", "scripts", "script", "lib", "libs", "app", "apps", "core",
	"common", "util", "utils", "addons", "assets", "res", "code", "game", "pkg",
	"internal", "new", "old", "tmp", "temp", "node", "modules", "dist", "build",
	"test", "tests", "spec", "specs", "the", "and", "for",
]);

export const MAX_SERVED_STATEMENTS = 15;
export const MAX_QUERY_RESULTS = 12;

const AREA_OWNERSHIP_RATIO = 0.5;
const AREA_LIFT_THRESHOLD = 2.0;
const AREA_MIN_SCORE = 1.0;

/**
 * Crude singular/base form, so "cards" and "card" compare equal.
 *
 * The plural rules are spelled out rather than folded into one trailing-"s"
 * strip: a blanket strip made "enemies" -> "enem" while "enemy" stayed "enemy",
 * so the two forms of one word stopped matching, and it turned "class",
 * "status" and "process" into not-themselves.
 */
export function simpleStem(word: string): string {
	const w = word.toLowerCase();
	if (w.length > 4 && w.endsWith("ies")) return `${w.slice(0, -3)}y`;
	if (w.length > 4 && w.endsWith("es")) {
		const third = w[w.length - 3];
		if (third && "sxz".includes(third)) return w.slice(0, -2);
	}
	if (w.length > 3 && w.endsWith("s") && !/(ss|us|is)$/.test(w)) return w.slice(0, -1);
	for (const suffix of ["ing", "ed", "ly"]) {
		if (w.length > suffix.length + 2 && w.endsWith(suffix)) return w.slice(0, -suffix.length);
	}
	return w;
}

/** Lowercase word stems, splitting snake_case, kebab-case and camelCase. */
export function tokenize(text: string): Set<string> {
	const spaced = text.replace(/(?<=[a-z0-9])(?=[A-Z])/g, " ");
	const out = new Set<string>();
	for (const word of spaced.split(/[^\p{L}\p{N}]+/u)) {
		if (!word) continue;
		const isAscii = /^[\x20-\x7e]*$/.test(word);
		if (word.length >= 3 || (word.length >= 2 && !isAscii)) out.add(simpleStem(word));
	}
	return out;
}

/** Meaningful tokens from a project-relative path, minus generic directory noise. */
export function pathTokens(relPath: string, protectedAreas: Iterable<string> = []): Set<string> {
	const stem = relPath.replace(/\.[A-Za-z0-9]+$/, "");
	const keep = new Set<string>();
	for (const area of protectedAreas) {
		keep.add(area);
		keep.add(simpleStem(area));
		for (const segment of area.split("-")) {
			keep.add(segment);
			keep.add(simpleStem(segment));
		}
	}
	const out = new Set<string>();
	for (const token of tokenize(stem)) {
		if (keep.has(token) || !PATH_STOPWORDS.has(token)) out.add(token);
	}
	return out;
}

/**
 * Glob match where `*` does not cross a directory separator and `**` does.
 * Plain fnmatch treats "/" as an ordinary character, so "src/*" would also
 * match "src/deep/nested/thing.gd".
 */
export function globMatch(relPath: string, pattern: string): boolean {
	const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&");
	const body = escaped.replace(/\*\*|\*|\?/g, (m) => {
		if (m === "**") return ".*";
		if (m === "*") return "[^/]*";
		return "[^/]";
	});
	return new RegExp(`^${body}$`).test(relPath);
}

/** Every word of an entry worth matching on: statement AND field values. */
export function decisionTokens(entry: Entry): Set<string> {
	const text = [entry.statement, ...entry.fields.map((f) => f.value)].join(" ");
	const out = tokenize(text);
	for (const stop of PATH_STOPWORDS) out.delete(stop);
	return out;
}

function areaInTokens(area: string, tokens: Set<string>): boolean {
	if (tokens.has(area) || tokens.has(simpleStem(area))) return true;
	for (const segment of area.split("-")) {
		if (tokens.has(segment) || tokens.has(simpleStem(segment))) return true;
	}
	return false;
}

/**
 * Area labels plausibly governing `relPath`, best first.
 *
 * The two kinds of error are not symmetric: failing to surface a decision that
 * governs this file is the failure the product exists to prevent, while
 * surfacing one extra only costs tokens. Every tier is therefore unioned, not
 * short-circuited.
 */
export function matchAreas(
	entries: Entry[],
	relPath: string,
	areaMap: Record<string, string> = {},
): string[] {
	if (entries.length === 0) return [];
	const known = [...new Set(entries.map((e) => e.area))].sort();

	const confident: string[] = [];
	for (const [pattern, area] of Object.entries(areaMap)) {
		if (known.includes(area) && globMatch(relPath, pattern) && !confident.includes(area)) {
			confident.push(area);
		}
	}

	const tokens = pathTokens(relPath, known);
	for (const area of known) {
		if (areaInTokens(area, tokens) && !confident.includes(area)) confident.push(area);
	}
	if (tokens.size === 0) return confident;

	// Fallback: word overlap, weighted by which area a word BELONGS to rather than
	// by how rare it is. Counting raw overlap let everyday vocabulary carry a match;
	// filtering frequent words instead lost the one file an area is about.
	const perArea = new Map<string, Map<string, number>>();
	const totals = new Map<string, number>();
	const areaSize = new Map<string, number>();
	for (const entry of entries) {
		let bucket = perArea.get(entry.area);
		if (!bucket) {
			bucket = new Map();
			perArea.set(entry.area, bucket);
		}
		areaSize.set(entry.area, (areaSize.get(entry.area) ?? 0) + 1);
		for (const token of decisionTokens(entry)) {
			bucket.set(token, (bucket.get(token) ?? 0) + 1);
			totals.set(token, (totals.get(token) ?? 0) + 1);
		}
	}

	const totalDecisions = entries.length;
	const scores: { area: string; score: number }[] = [];
	for (const [area, bucket] of perArea) {
		if (confident.includes(area)) continue;
		const size = areaSize.get(area) ?? 1;
		let score = 0;
		for (const token of tokens) {
			const inArea = bucket.get(token);
			if (inArea === undefined) continue;
			const total = totals.get(token) ?? 0;
			const owned = inArea / total >= AREA_OWNERSHIP_RATIO;
			const lift = inArea / size / (total / totalDecisions);
			if (!owned && lift < AREA_LIFT_THRESHOLD) score += 0.4;
			else if (total >= 2) score += 1.0;
			else score += 0.6;
		}
		if (score >= AREA_MIN_SCORE) scores.push({ area, score });
	}
	scores.sort((a, b) => b.score - a.score || a.area.localeCompare(b.area));
	return confident.concat(scores.map((s) => s.area));
}

/**
 * Entries for the given areas, in file order, capped.
 *
 * Entries with an empty statement are dropped: there is no rule in them, lint
 * already reports them, and a bare ID in a binding block reads as a rule that
 * says nothing.
 */
export function entriesForAreas(
	entries: Entry[],
	areas: Iterable<string>,
	limit = MAX_SERVED_STATEMENTS,
): { shown: Entry[]; withheld: number } {
	const wanted = new Set(areas);
	const candidates = entries.filter((e) => wanted.has(e.area) && e.statement !== "");
	return { shown: candidates.slice(0, limit), withheld: Math.max(0, candidates.length - limit) };
}
