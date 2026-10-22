/**
 * Path helpers shared by the verbs and by state. All comparisons are made on
 * normalised, forward-slashed paths; case folding follows the filesystem.
 */

import * as path from "node:path";

const CASE_INSENSITIVE = process.platform === "win32";

/** Absolute, forward-slashed, and case-folded only where the filesystem is. */
export function normalizePath(p: string): string {
	const resolved = path.resolve(p);
	const slashed = resolved.split(path.sep).join("/");
	return CASE_INSENSITIVE ? slashed.toLowerCase() : slashed;
}

/** True only if `file` resolves inside `root` (or is `root`). */
export function isWithinProject(file: string, root: string): boolean {
	if (!file || !root) return false;
	try {
		const target = normalizePath(file);
		const base = normalizePath(root).replace(/\/+$/, "");
		return target === base || target.startsWith(`${base}/`);
	} catch {
		return false;
	}
}

/** Project-relative, forward-slashed; falls back to the basename off-root. */
export function relativePath(file: string, root: string): string {
	try {
		const rel = path.relative(path.resolve(root), path.resolve(file));
		if (rel && !rel.startsWith("..") && !path.isAbsolute(rel)) return rel.split(path.sep).join("/");
		// A case-only difference defeats path.relative on some platforms.
		const target = normalizePath(file);
		const base = normalizePath(root).replace(/\/+$/, "");
		if (target.startsWith(`${base}/`)) return target.slice(base.length + 1);
		return path.basename(file);
	} catch {
		return path.basename(file);
	}
}

/** True when both paths resolve to the same file. */
export function isSamePath(a: string, b: string): boolean {
	try {
		return normalizePath(a) === normalizePath(b);
	} catch {
		return false;
	}
}

/** Compare form for prefix matching: forward-slashed, case-folded where the FS is. */
export function compareForm(p: string): string {
	const slashed = p.split(path.sep).join("/");
	return CASE_INSENSITIVE ? slashed.toLowerCase() : slashed;
}
