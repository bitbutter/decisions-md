import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import {
	areaServed,
	claimBackstop,
	claimServed,
	decisionsTouched,
	markDecisionsTouched,
	projectKey,
	projectStateDir,
	pruneState,
	recordEdit,
	resetSession,
	safeComponent,
	sessionDir,
	takeEdits,
} from "../../core/state.ts";
import { decide } from "../../core/operations.ts";

function withTempState(): { root: string; cleanup: () => void } {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-state-"));
	const previous = process.env["DECISIONS_STATE_DIR"];
	process.env["DECISIONS_STATE_DIR"] = path.join(dir, "state");
	return {
		root: path.join(dir, "project"),
		cleanup: () => {
			if (previous === undefined) delete process.env["DECISIONS_STATE_DIR"];
			else process.env["DECISIONS_STATE_DIR"] = previous;
			fs.rmSync(dir, { recursive: true, force: true });
		},
	};
}

test("a claim is won exactly once", () => {
	const { root, cleanup } = withTempState();
	try {
		assert.equal(claimServed(root, "s1", "input"), true);
		assert.equal(claimServed(root, "s1", "input"), false);
		assert.equal(areaServed(root, "s1", "input"), true);
		assert.equal(areaServed(root, "s1", "render"), false);
		assert.equal(claimServed(root, "s2", "input"), true);
		assert.equal(claimBackstop(root, "s1"), true);
		assert.equal(claimBackstop(root, "s1"), false);
	} finally {
		cleanup();
	}
});

test("recorded edits are taken once, in order", () => {
	const { root, cleanup } = withTempState();
	try {
		recordEdit(root, "s1", "src/a.gd");
		recordEdit(root, "s1", "src/b.gd");
		recordEdit(root, "s1", "src/a.gd");
		assert.deepEqual(takeEdits(root, "s1"), ["src/a.gd", "src/b.gd"]);
		assert.deepEqual(takeEdits(root, "s1"), []);
	} finally {
		cleanup();
	}
});

test("the decisions-touched flag is per session", () => {
	const { root, cleanup } = withTempState();
	try {
		assert.equal(decisionsTouched(root, "s1"), false);
		markDecisionsTouched(root, "s1");
		assert.equal(decisionsTouched(root, "s1"), true);
		assert.equal(decisionsTouched(root, "s2"), false);
		resetSession(root, "s1");
		assert.equal(decisionsTouched(root, "s1"), false);
	} finally {
		cleanup();
	}
});

test("a session identity cannot escape the state directory", () => {
	assert.equal(safeComponent("../../etc/passwd"), "etc-passwd");
	assert.equal(safeComponent(".."), null);
	assert.equal(safeComponent(""), null);
	assert.equal(sessionDir("C:/project", ".."), null);
});

test("the project key is stable for one root and distinct across roots", () => {
	assert.equal(projectKey("C:/a/project"), projectKey("C:/a/project"));
	assert.notEqual(projectKey("C:/a/project"), projectKey("C:/b/project"));
	assert.match(projectKey("C:/a/project"), /^project-[0-9a-f]{10}$/);
});

test("state lives outside the project, and a serve writes nothing into it", () => {
	const { root, cleanup } = withTempState();
	try {
		fs.mkdirSync(path.join(root, "src", "input"), { recursive: true });
		fs.writeFileSync(path.join(root, "DECISIONS.md"), "DEC-INPUT-001: Jump is on A.\n");
		fs.writeFileSync(path.join(root, "src", "input", "player.gd"), "extends Node\n");
		const before = walk(root);

		const envelope = decide({ root, file: path.join(root, "src", "input", "player.gd"), session: "s1" });
		assert.equal(envelope.code, "served");
		assert.deepEqual(walk(root), before);
		assert.equal(projectStateDir(root).startsWith(root), false);
		assert.ok(fs.existsSync(projectStateDir(root)));
	} finally {
		cleanup();
	}
});

test("pruning removes sessions untouched for longer than the TTL", () => {
	const { root, cleanup } = withTempState();
	try {
		claimServed(root, "old", "input");
		const dir = sessionDir(root, "old") as string;
		const old = Date.now() / 1000 - 8 * 24 * 60 * 60;
		for (const target of [dir, path.join(dir, "served"), path.join(dir, "served", "input")]) {
			fs.utimesSync(target, old, old);
		}
		pruneState(root);
		assert.equal(fs.existsSync(dir), false);
	} finally {
		cleanup();
	}
});

function walk(dir: string, base = dir): string[] {
	const out: string[] = [];
	for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
		const full = path.join(dir, entry.name);
		const rel = path.relative(base, full);
		if (entry.isDirectory()) out.push(`${rel}/`, ...walk(full, base));
		else out.push(rel);
	}
	return out.sort();
}
