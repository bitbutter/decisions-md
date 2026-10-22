/**
 * Reading the file: area counts, the overview line, and keyword search.
 * Contract: docs/ADAPTERS.md §4.3.
 */

import { renderEntry } from "./parse.ts";
import { MAX_QUERY_RESULTS, tokenize } from "./match.ts";
import type { Entry } from "./types.ts";

export interface QueryOptions {
	area?: string;
	terms?: string;
	limit?: number;
}

export interface QueryResult {
	results: Entry[];
	total: number;
}

/** Entries matching an area and/or keywords, best match first. */
export function queryDecisions(entries: Entry[], opts: QueryOptions = {}): QueryResult {
	const area = opts.area?.trim().toLowerCase();
	let pool = area ? entries.filter((e) => e.area === area) : entries;

	const terms = opts.terms?.trim();
	if (terms) {
		const stems = tokenize(terms);
		if (stems.size > 0) {
			const scored: { hits: number; entry: Entry }[] = [];
			for (const entry of pool) {
				const haystack = [entry.id, entry.statement, ...entry.fields.map((f) => f.value)].join(" ");
				let hits = 0;
				const entryTokens = tokenize(haystack);
				for (const stem of stems) if (entryTokens.has(stem)) hits += 1;
				// An ID typed verbatim is an exact request, not a fuzzy one.
				if (entry.id.includes(terms.toUpperCase())) hits += 10;
				if (hits > 0) scored.push({ hits, entry });
			}
			scored.sort((a, b) => b.hits - a.hits || a.entry.id.localeCompare(b.entry.id));
			pool = scored.map((s) => s.entry);
		}
	}

	return { results: pool.slice(0, opts.limit ?? MAX_QUERY_RESULTS), total: pool.length };
}

/** Entries per area label, sorted by label. */
export function areaCounts(entries: Entry[]): { area: string; count: number }[] {
	const counts = new Map<string, number>();
	for (const entry of entries) counts.set(entry.area, (counts.get(entry.area) ?? 0) + 1);
	return [...counts.entries()]
		.map(([area, count]) => ({ area, count }))
		.sort((a, b) => a.area.localeCompare(b.area));
}

/** `4 decisions (economy:2, input:2)`, or "" when there are none. */
export function overview(entries: Entry[]): string {
	const counts = areaCounts(entries);
	if (counts.length === 0) return "";
	const total = counts.reduce((sum, c) => sum + c.count, 0);
	const noun = total === 1 ? "decision" : "decisions";
	return `${total} ${noun} (${counts.map((c) => `${c.area}:${c.count}`).join(", ")})`;
}

/** The area table printed when query is called with no arguments. */
export function areaListText(entries: Entry[]): string {
	const counts = areaCounts(entries);
	if (counts.length === 0) return "DECISIONS.md has no entries yet.";
	const total = counts.reduce((sum, c) => sum + c.count, 0);
	const width = Math.max(...counts.map((c) => c.area.length), 4);
	const rows = counts.map((c) => `  ${c.area.padEnd(width)}  ${c.count}`);
	return [
		`Decision areas (${total} total):`,
		"",
		...rows,
		"",
		"Pass an area name to see one area in full; pass keywords to search across areas.",
	].join("\n");
}

/** Render a result set, grouped by area. */
export function queryText(entries: Entry[], opts: QueryOptions = {}): string {
	const { results, total } = queryDecisions(entries, opts);
	if (total === 0) return "";
	let label = "";
	if (opts.area) label += ` in area ${opts.area.trim().toLowerCase()}`;
	if (opts.terms) label += ` for '${opts.terms.trim()}'`;
	const lines = [
		`[DECISIONS] ${total} found${label}. These are binding. If one directly answers the question or contradicts a proposed change, stop and offer the user: abandon / adapt / override.`,
	];
	let currentArea: string | null = null;
	for (const entry of results) {
		if (entry.area !== currentArea) {
			currentArea = entry.area;
			lines.push("", `## ${entry.area.toUpperCase()}`);
		}
		lines.push("", renderEntry(entry));
	}
	if (total > results.length) {
		lines.push("", `(${total - results.length} more not shown -- narrow with an area or more specific keywords)`);
	}
	return lines.join("\n");
}
