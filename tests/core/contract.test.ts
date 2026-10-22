import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import { handle } from "../../core/operations.ts";
import { ENGINE_VERSION } from "../../core/version.ts";

const REPO = path.resolve(import.meta.dirname, "..", "..");
const CLI = path.join(REPO, "bin", "decisions.ts");

/**
 * One JSON object in on stdin, one out on stdout. `execFile` has no `input`
 * option, so the CLI's stdin was never written and never closed and every call
 * in this file sat in `readFileSync(0)` until the test run timed out.
 */
function cli(input: string): Promise<{ code: number; stdout: string; stderr: string }> {
	return new Promise((resolve, reject) => {
		const child = spawn(process.execPath, [CLI], { stdio: ["pipe", "pipe", "pipe"] });
		let stdout = "";
		let stderr = "";
		child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
			stdout += chunk;
		});
		child.stderr.setEncoding("utf8").on("data", (chunk: string) => {
			stderr += chunk;
		});
		child.on("error", reject);
		child.on("close", (code) => resolve({ code: code ?? 1, stdout, stderr }));
		child.stdin.end(input);
	});
}

function project(content = "DEC-AA-001: A rule.\n"): { root: string; cleanup: () => void } {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-cli-"));
	fs.writeFileSync(path.join(dir, "DECISIONS.md"), content);
	fs.mkdirSync(path.join(dir, "src", "aa"), { recursive: true });
	fs.writeFileSync(path.join(dir, "src", "aa", "thing.gd"), "extends Node\n");
	const previous = process.env["DECISIONS_STATE_DIR"];
	process.env["DECISIONS_STATE_DIR"] = path.join(dir, ".state-probe");
	return {
		root: dir,
		cleanup: () => {
			if (previous === undefined) delete process.env["DECISIONS_STATE_DIR"];
			else process.env["DECISIONS_STATE_DIR"] = previous;
			fs.rmSync(dir, { recursive: true, force: true });
		},
	};
}

test("the envelope has exactly four keys and never a trailing newline in text", () => {
	const { root, cleanup } = project();
	try {
		const envelope = handle("orient", { root });
		assert.deepEqual(Object.keys(envelope).sort(), ["action", "code", "details", "text"]);
		assert.equal(envelope.action, "inject");
		assert.ok(!envelope.text.endsWith("\n"));
	} finally {
		cleanup();
	}
});

test("a malformed payload is a fail envelope, not a throw", () => {
	const envelope = handle("decide", { root: process.cwd() });
	assert.equal(envelope.action, "fail");
	assert.equal(envelope.code, "invalid_input");

	const unknown = handle("nope", {});
	assert.equal(unknown.action, "fail");
	assert.equal(unknown.code, "invalid_input");
});

test("the CLI answers every handled request with exit code 0", async () => {
	const { root, cleanup } = project();
	try {
		const ok = await cli(JSON.stringify({ verb: "orient", root }));
		assert.equal(ok.code, 0);
		assert.equal(JSON.parse(ok.stdout).action, "inject");

		const blocked = await cli(JSON.stringify({ verb: "lint", root }));
		assert.equal(blocked.code, 0);
		assert.equal(JSON.parse(blocked.stdout).action, "none");

		const failed = await cli("{not json");
		assert.equal(failed.code, 0);
		const envelope = JSON.parse(failed.stdout);
		assert.equal(envelope.action, "fail");
		assert.equal(envelope.code, "invalid_input");

		const unknown = await cli(JSON.stringify({ verb: "nope" }));
		assert.equal(unknown.code, 0);
		assert.equal(JSON.parse(unknown.stdout).action, "fail");

		const lines = blocked.stdout.trim().split("\n");
		assert.equal(lines.length, 1, "exactly one JSON line on stdout");
	} finally {
		cleanup();
	}
});

test("the CLI never exits 2, even for a block", async () => {
	const { root, cleanup } = project("DEC-AA-001: rule\nStatus: Active\n");
	try {
		const result = await cli(JSON.stringify({ verb: "lint", root }));
		assert.equal(result.code, 0);
		assert.equal(JSON.parse(result.stdout).action, "block");
	} finally {
		cleanup();
	}
});

test("core holds no harness knowledge", () => {
	const forbidden = [
		/\bpi\b/i,
		/\bclaude\b/i,
		/\bcodex\b/i,
		/\bopencode\b/i,
		/\bpaseo\b/i,
		/\bhook\b/i,
		/\btool_call\b/,
		/\bPreToolUse\b/,
		/\bPostToolUse\b/,
		/\bSessionStart\b/,
		/\bexit\s*2\b/i,
		/\bexitCode\b/,
		/process\.stdout/,
		/\bconsole\./,
	];
	const files = fs.readdirSync(path.join(REPO, "core")).filter((f) => f.endsWith(".ts"));
	assert.ok(files.length >= 6);
	for (const file of files) {
		const source = fs.readFileSync(path.join(REPO, "core", file), "utf8");
		for (const pattern of forbidden) {
			assert.ok(!pattern.test(source), `${file} matches ${pattern}`);
		}
	}
});

test("doctor reports the adapter and the harness version it is told about", () => {
	const { root, cleanup } = project();
	try {
		const silent = handle("doctor", { root, session: "s" });
		const silentChecks = (silent.details as { checks: Array<{ name: string; status: string }> }).checks;
		assert.equal(silentChecks.find((check) => check.name === "adapter")?.status, "warn", "an adapter that says nothing is a warning");
		assert.equal(silentChecks.find((check) => check.name === "harness")?.status, "warn");

		const reported = handle("doctor", { root, session: "s", adapter: "pi", builtAgainst: "0.84.2" });
		assert.equal(reported.action, "none");
		assert.equal(reported.code, "ok");
		assert.ok(reported.text.includes("ok   adapter: pi"), reported.text);
		assert.ok(reported.text.includes("harness: 0.84.2"), reported.text);
	} finally {
		cleanup();
	}
});

test("the engine version matches package.json", () => {
	const pkg = JSON.parse(fs.readFileSync(path.join(REPO, "package.json"), "utf8")) as { version: string };
	assert.equal(ENGINE_VERSION, pkg.version);
});

test("the adapter imports core and the CLI, and nothing imports the adapter", () => {
	const adapter = fs.readFileSync(path.join(REPO, "harnesses", "pi", "index.ts"), "utf8");
	assert.ok(adapter.includes('from "../../core/operations.ts"'));
	for (const file of fs.readdirSync(path.join(REPO, "core"))) {
		if (!file.endsWith(".ts")) continue;
		const source = fs.readFileSync(path.join(REPO, "core", file), "utf8");
		assert.ok(!source.includes("harnesses"), `${file} imports an adapter`);
	}
});
