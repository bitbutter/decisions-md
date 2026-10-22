import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import { archiveSuperseded } from "../../core/migrate.ts";
import { decide } from "../../core/operations.ts";
import { lintFile } from "../../core/lint.ts";
import { parseDecisions } from "../../core/parse.ts";

const REPO = path.resolve(import.meta.dirname, "..", "..");
const CLI = path.join(REPO, "bin", "decisions.ts");

function project(files: Record<string, string>): { root: string; cleanup: () => void } {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-adv-"));
	for (const [rel, content] of Object.entries(files)) {
		const full = path.join(dir, rel);
		fs.mkdirSync(path.dirname(full), { recursive: true });
		fs.writeFileSync(full, content);
	}
	const previous = process.env["DECISIONS_STATE_DIR"];
	process.env["DECISIONS_STATE_DIR"] = path.join(dir, ".state");
	return {
		root: dir,
		cleanup: () => {
			if (previous === undefined) delete process.env["DECISIONS_STATE_DIR"];
			else process.env["DECISIONS_STATE_DIR"] = previous;
			fs.rmSync(dir, { recursive: true, force: true });
		},
	};
}

function cli(input: unknown): Promise<{ code: number; stdout: string }> {
	return new Promise((resolve, reject) => {
		const child = spawn(process.execPath, [CLI], { stdio: ["pipe", "pipe", "pipe"] });
		let stdout = "";
		child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
			stdout += chunk;
		});
		child.on("error", reject);
		child.on("close", (code) => resolve({ code: code ?? 1, stdout }));
		child.stdin.end(typeof input === "string" ? input : JSON.stringify(input));
	});
}

test("two processes racing for one area produce exactly one serve", async () => {
	const { root, cleanup } = project({
		"DECISIONS.md": "DEC-INPUT-001: Jump is on A.\n",
		"src/input/player.gd": "extends Node\n",
	});
	try {
		const payload = {
			verb: "decide",
			root,
			file: path.join(root, "src", "input", "player.gd"),
			session: "race",
		};
		const results = await Promise.all(Array.from({ length: 6 }, () => cli(payload)));
		const actions = results.map((r) => JSON.parse(r.stdout).action as string);
		assert.equal(actions.filter((a) => a === "inject").length, 1, actions.join(","));
		assert.equal(actions.filter((a) => a === "none").length, 5, actions.join(","));
	} finally {
		cleanup();
	}
});

test("an area whose entries are all empty statements does not consume a claim", () => {
	const { root, cleanup } = project({
		"DECISIONS.md": "DEC-INPUT-001:\n\nDEC-INPUT-002: Jump is on A.\n",
		"src/input/player.gd": "extends Node\n",
	});
	try {
		const file = path.join(root, "src", "input", "player.gd");
		const first = decide({ root, file, session: "s1" });
		assert.equal(first.code, "served");
		assert.deepEqual(first.details["ids"], ["DEC-INPUT-002"]);
	} finally {
		cleanup();
	}
});

test("a serve reports no_match when every matched entry is empty", () => {
	const { root, cleanup } = project({
		"DECISIONS.md": "DEC-INPUT-001:\n",
		"src/input/player.gd": "extends Node\n",
	});
	try {
		const envelope = decide({ root, file: path.join(root, "src", "input", "player.gd"), session: "s1" });
		assert.equal(envelope.code, "no_matching_area");
	} finally {
		cleanup();
	}
});

test("a path that escapes the project root is outside_project", () => {
	const { root, cleanup } = project({
		"DECISIONS.md": "DEC-INPUT-001: Jump is on A.\n",
		"src/input/player.gd": "extends Node\n",
		"../outside/thing.gd": "extends Node\n",
	});
	try {
		const inside = decide({ root, file: path.join(root, "src", "input", "..", "input", "player.gd"), session: "s1" });
		assert.equal(inside.code, "served");
		const outside = decide({ root, file: path.join(root, "..", "outside", "thing.gd"), session: "s2" });
		assert.equal(outside.code, "outside_project");
	} finally {
		cleanup();
	}
});

test("random bytes never throw in parse or lint", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-fuzz-"));
	try {
		for (let i = 0; i < 30; i += 1) {
			const file = path.join(dir, `f${i}.md`);
			const bytes = Buffer.alloc(1 + Math.floor(Math.random() * 400));
			for (let b = 0; b < bytes.length; b += 1) bytes[b] = Math.floor(Math.random() * 256);
			fs.writeFileSync(file, bytes);
			assert.doesNotThrow(() => parseDecisions(fs.readFileSync(file).toString("utf8")));
			assert.doesNotThrow(() => lintFile(file));
		}
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

test("a pathological statement cannot stall parsing or linting", () => {
	const word = `${"a.".repeat(10000)}gd`;
	const text = `DEC-AA-001: ${word}\n\n${Array.from({ length: 400 }, (_, i) => `DEC-BB-${String(i + 1).padStart(3, "0")}: rule number ${i}.`).join("\n\n")}\n`;
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-perf-"));
	try {
		const file = path.join(dir, "DECISIONS.md");
		fs.writeFileSync(file, text);
		const started = Date.now();
		const entries = parseDecisions(text);
		lintFile(file);
		const elapsed = Date.now() - started;
		assert.equal(entries.length, 401);
		assert.ok(elapsed < 3000, `took ${elapsed}ms`);
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

test("a rerun after a partial archive does not duplicate history", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-archive-"));
	try {
		const file = path.join(dir, "DECISIONS.md");
		const archive = path.join(dir, "support", "decision_archive.md");
		const original = [
			"DEC-AA-001: live.",
			"",
			"DEC-AA-002: Superseded by DEC-AA-003 -- gone.",
			"Status: Superseded (DEC-AA-003, 2026-01-01)",
			"",
			"DEC-AA-003: live two.",
			"",
		].join("\n");
		fs.writeFileSync(file, original);
		archiveSuperseded(file, archive, "2026-01-02T00:00:00Z");
		const firstArchive = fs.readFileSync(archive, "utf8");
		// Simulate a failed rewrite: the record is back in the file, the archive kept.
		fs.writeFileSync(file, original);
		const second = archiveSuperseded(file, archive, "2026-01-03T00:00:00Z");
		assert.deepEqual(second.archived, ["DEC-AA-002"]);
		assert.equal(fs.readFileSync(archive, "utf8"), firstArchive, "the block was appended twice");
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});
