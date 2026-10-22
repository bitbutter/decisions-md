/**
 * Per-session bookkeeping. Contract: docs/ADAPTERS.md §4.6 and §7.
 *
 * Every fact is its own small file and no file is ever read-modify-written.
 * Two processes rewriting one JSON blob silently discard each other's writes;
 * disjoint files remove the race instead of guarding it, and creating a marker
 * with O_EXCL is an atomic claim — exactly the question "has this area been
 * served yet?" is asking.
 *
 * Nothing here is ever written inside the consuming project.
 */

import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export const SESSION_TTL_SECONDS = 7 * 24 * 60 * 60;
export const TMP_TTL_SECONDS = 60 * 60;

export function homeIsResolvable(): boolean {
	const home = (() => {
		try {
			return os.homedir();
		} catch {
			return "";
		}
	})();
	return Boolean(home) && home !== "~" && path.isAbsolute(home);
}

/** The home directory, or a labelled temp fallback when there is none. */
export function stateHome(): string {
	return homeIsResolvable() ? os.homedir() : path.join(os.tmpdir(), "decisions-md-nohome");
}

/** `$DECISIONS_STATE_DIR`, else `~/.decisions-md/state`. Never inside a project. */
export function resolveStateDir(): string {
	const override = process.env.DECISIONS_STATE_DIR;
	if (override && override.trim()) return path.resolve(override.trim());
	return path.join(stateHome(), ".decisions-md", "state");
}

/** Readable slug plus a short hash of the normalised absolute root. */
export function projectKey(root: string): string {
	const resolved = path.resolve(root || process.cwd());
	const folded = process.platform === "win32" ? resolved.toLowerCase() : resolved;
	const digest = createHash("sha1").update(folded.split(path.sep).join("/")).digest("hex").slice(0, 10);
	const base = path.basename(resolved.replace(/[\\/]+$/, "")) || "project";
	const slug = base.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 40).replace(/^[-. ]+|[-. ]+$/g, "") || "project";
	return `${slug}-${digest}`;
}

/** One project's state directory. */
export function projectStateDir(root: string): string {
	return path.join(resolveStateDir(), projectKey(root));
}

/** A single path component that cannot escape its directory, or null. */
export function safeComponent(name: string): string | null {
	const s = String(name ?? "")
		.replace(/[^A-Za-z0-9._-]/g, "-")
		.replace(/^[-. ]+|[-. ]+$/g, "");
	if (!s || s.replace(/\./g, "") === "") return null;
	return s.slice(0, 80);
}

/**
 * The session directory, or null when the identity sanitises to nothing.
 *
 * The sanitised prefix is for a human reading the directory; the hash is what
 * keeps two long session identities that share a prefix from colliding, which
 * would mix their served markers and silently suppress a serve.
 */
export function sessionDir(root: string, session: string): string | null {
	const safe = safeComponent(session);
	if (!safe) return null;
	const digest = createHash("sha1").update(session, "utf8").digest("hex").slice(0, 8);
	return path.join(projectStateDir(root), `s-${safe.slice(0, 48)}-${digest}`);
}

/** Create `p` exactly once. True only for the caller that created it. */
function claim(p: string): boolean {
	try {
		fs.mkdirSync(path.dirname(p), { recursive: true });
		const fd = fs.openSync(p, "wx");
		fs.closeSync(fd);
		return true;
	} catch {
		return false;
	}
}

function writeMarker(p: string, text: string): boolean {
	try {
		fs.mkdirSync(path.dirname(p), { recursive: true });
		fs.writeFileSync(p, text, "utf8");
		return true;
	} catch {
		return false;
	}
}

export function claimServed(root: string, session: string, area: string): boolean {
	const dir = sessionDir(root, session);
	const name = safeComponent(area);
	if (!dir || !name) return false;
	return claim(path.join(dir, "served", name));
}

export function areaServed(root: string, session: string, area: string): boolean {
	const dir = sessionDir(root, session);
	const name = safeComponent(area);
	if (!dir || !name) return false;
	try {
		return fs.statSync(path.join(dir, "served", name)).isFile();
	} catch {
		return false;
	}
}

export function claimBackstop(root: string, session: string): boolean {
	const dir = sessionDir(root, session);
	return dir ? claim(path.join(dir, "backstop-asked")) : false;
}

export function recordEdit(root: string, session: string, relPath: string): boolean {
	const dir = sessionDir(root, session);
	if (!dir || !relPath) return false;
	const key = createHash("sha1").update(relPath, "utf8").digest("hex").slice(0, 16);
	return writeMarker(path.join(dir, "pending", key), relPath);
}

/** Return the edits recorded this session and forget them. */
export function takeEdits(root: string, session: string): string[] {
	const dir = sessionDir(root, session);
	if (!dir) return [];
	const pending = path.join(dir, "pending");
	let names: string[];
	try {
		names = fs.readdirSync(pending).sort();
	} catch {
		return [];
	}
	const found: string[] = [];
	for (const name of names) {
		const file = path.join(pending, name);
		let value: string;
		try {
			value = fs.readFileSync(file, "utf8").trim();
		} catch {
			continue;
		}
		try {
			fs.unlinkSync(file);
		} catch {
			// Removing it is what makes this a "take": reporting the edit anyway
			// would hand the same one back on the next call.
			continue;
		}
		if (value) found.push(value);
	}
	return found;
}

export function markDecisionsTouched(root: string, session: string): boolean {
	const dir = sessionDir(root, session);
	return dir ? writeMarker(path.join(dir, "decisions-touched"), "1") : false;
}

export function decisionsTouched(root: string, session: string): boolean {
	const dir = sessionDir(root, session);
	if (!dir) return false;
	try {
		return fs.statSync(path.join(dir, "decisions-touched")).isFile();
	} catch {
		return false;
	}
}

/** Forget everything about one session, so a new or resumed one starts clean. */
export function resetSession(root: string, session: string): void {
	const dir = sessionDir(root, session);
	if (!dir) return;
	try {
		fs.rmSync(dir, { recursive: true, force: true });
	} catch {
		// best effort
	}
}

/** Drop stale session directories and orphaned temp files. */
export function pruneState(root: string): void {
	const stateDir = projectStateDir(root);
	let names: string[];
	try {
		names = fs.readdirSync(stateDir);
	} catch {
		return;
	}
	const now = Date.now();
	for (const name of names) {
		const full = path.join(stateDir, name);
		try {
			if (name.startsWith("s-") && fs.statSync(full).isDirectory()) {
				if (now - lastTouched(full) > SESSION_TTL_SECONDS * 1000) {
					fs.rmSync(full, { recursive: true, force: true });
				}
			} else if (name.endsWith(".tmp") && now - fs.statSync(full).mtimeMs > TMP_TTL_SECONDS * 1000) {
				fs.unlinkSync(full);
			}
		} catch {
			// a concurrent removal or a locked file: skip it
		}
	}
}

/** Newest mtime of a session directory or its immediate children. */
function lastTouched(dir: string): number {
	let newest = fs.statSync(dir).mtimeMs;
	try {
		for (const entry of fs.readdirSync(dir)) {
			try {
				newest = Math.max(newest, fs.statSync(path.join(dir, entry)).mtimeMs);
			} catch {
				// skip
			}
		}
	} catch {
		// skip
	}
	return newest;
}
