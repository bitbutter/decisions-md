/**
 * Project configuration, `.decisions/config.json`. Contract: docs/ADAPTERS.md §6.
 *
 * Missing or malformed config is `{}` and then defaults: a project that cannot
 * configure the engine is a project that gets defaults.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { Config } from "./types.ts";

export const CONFIG_RELPATH = path.join(".decisions", "config.json");

export const DEFAULT_TRACKED_EXTENSIONS = [
	// Godot
	".gd", ".tscn", ".tres", ".gdshader", ".gdextension",
	// Common scripting / source languages
	".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
	".rb", ".go", ".rs", ".lua", ".sh", ".ps1",
];

export const DEFAULT_EXEMPT_PATHS = [
	"DECISIONS.md", ".decisions/", "tools/",
	"addons/", "vendor/", "third_party/", "node_modules/", ".godot/", "build/", "dist/",
];

function stringList(value: unknown): unknown[] | null {
	return Array.isArray(value) ? value : null;
}

export function normalizeTrackedExtensions(value: unknown): string[] {
	const list = stringList(value);
	if (!list) return [...DEFAULT_TRACKED_EXTENSIONS];
	// An explicit [] means "track nothing" and is honoured. A list whose entries
	// are not extensions is a typo, and coercing it would silently switch the
	// engine off with no diagnostic anywhere.
	const usable = list
		.filter((e): e is string => typeof e === "string" && e.startsWith(".") && e.length > 1)
		.map((e) => e.toLowerCase());
	if (list.length > 0 && usable.length === 0) return [...DEFAULT_TRACKED_EXTENSIONS];
	return usable;
}

export function normalizeExemptPaths(value: unknown): string[] {
	const list = stringList(value) ?? DEFAULT_EXEMPT_PATHS;
	const out: string[] = [];
	for (const item of list) {
		let s = String(item).split("\\").join("/").trim();
		// Strip a leading "./" only: lstrip("./") would eat the dot of ".decisions/".
		if (s.startsWith("./")) s = s.slice(2);
		s = s.replace(/\/+$/, "");
		if (s) out.push(s);
	}
	return out;
}

export function normalizeAreaMap(value: unknown): Record<string, string> {
	if (!value || typeof value !== "object" || Array.isArray(value)) return {};
	const out: Record<string, string> = {};
	for (const [glob, area] of Object.entries(value as Record<string, unknown>)) {
		out[String(glob).split("\\").join("/")] = String(area).toLowerCase();
	}
	return out;
}

/** Read `<root>/.decisions/config.json`; absent or malformed means defaults. */
export function loadConfig(root: string): Config {
	let raw: unknown = {};
	if (root) {
		try {
			raw = JSON.parse(fs.readFileSync(path.join(root, CONFIG_RELPATH), "utf8"));
		} catch {
			raw = {};
		}
	}
	const obj = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
	return {
		enabled: obj.enabled !== false,
		trackedExtensions: normalizeTrackedExtensions(obj.tracked_extensions),
		exemptPaths: normalizeExemptPaths(obj.exempt_paths),
		areaMap: normalizeAreaMap(obj.area_map),
	};
}

/** Is this extension (including the dot, lowercased) tracked. */
export function isTrackedExtension(file: string, tracked: string[]): boolean {
	const ext = path.extname(file).toLowerCase();
	return ext !== "" && tracked.includes(ext);
}

/** True if the file IS the decisions file, or sits under an exempt prefix. */
export function isExemptPath(
	file: string,
	relPath: string,
	exemptPaths: string[],
	decisionsFile: string | null,
): boolean {
	if (!file) return true;
	if (decisionsFile) {
		const a = path.resolve(file);
		const b = path.resolve(decisionsFile);
		const same = process.platform === "win32" ? a.toLowerCase() === b.toLowerCase() : a === b;
		if (same) return true;
	}
	const rel = relPath.split("\\").join("/");
	const folded = process.platform === "win32" ? rel.toLowerCase() : rel;
	for (const exempt of exemptPaths) {
		const e = (process.platform === "win32" ? exempt.toLowerCase() : exempt).replace(/\/+$/, "");
		if (e && (folded === e || folded.startsWith(`${e}/`))) return true;
	}
	return false;
}
