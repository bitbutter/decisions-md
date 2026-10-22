/**
 * The synthetic fifth adapter. docs/ADAPTERS.md §10 and review item B2 make this
 * the guard that core holds no harness knowledge: a harness is built from the
 * written contract alone — different event names, different blocking mechanism,
 * no import of core, no reference to pi — and must be able to do the same job.
 *
 * It speaks only the subprocess envelope (docs/ADAPTERS.md §3), so it also pins
 * that the envelope carries everything an adapter needs: nothing here reads a
 * decision, matches an area or keeps state.
 *
 * The vocabulary is deliberately a harness that does not exist: "session.begin",
 * "file.before-write" (can deny), "file.after-write" (can annotate the result),
 * "turn.finish".
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";

/** The envelope shape from docs/ADAPTERS.md §3, declared here, not imported. */
interface Envelope {
	action: string;
	text: string;
	code: string;
	details: unknown;
}

const REPO = path.resolve(import.meta.dirname, "..", "..");
const CLI = path.join(REPO, "bin", "decisions.ts");

function envelope(verb: string, input: Record<string, unknown>): Promise<Envelope> {
	return new Promise((resolve, reject) => {
		const child = spawn(process.execPath, [CLI], { stdio: ["pipe", "pipe", "pipe"] });
		let stdout = "";
		child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
			stdout += chunk;
		});
		child.on("error", reject);
		child.on("close", (code) => {
			if (code !== 0) {
				reject(new Error(`${verb} exited ${code}`));
				return;
			}
			resolve(JSON.parse(stdout) as Envelope);
		});
		child.stdin.end(JSON.stringify({ verb, ...input }));
	});
}

/** The whole adapter. It knows the four actions and nothing else. */
function fifthAdapter(root: string, session: string) {
	const delivered: Array<{ text: string; when: "before-turn" | "after-turn" }> = [];

	return {
		delivered,

		async "session.begin"(): Promise<void> {
			const answer = await envelope("orient", { root });
			if (answer.action === "inject") delivered.push({ text: answer.text, when: "before-turn" });
		},

		async "file.before-write"(input: { path: string }): Promise<{ deny: true; message: string } | undefined> {
			const answer = await envelope("decide", { root, file: input.path, session });
			if (answer.action !== "inject") return undefined;
			return { deny: true, message: answer.text };
		},

		async "file.after-write"(input: { path: string }): Promise<{ append: string } | undefined> {
			const recorded = await envelope("record-edit", { root, file: input.path, session });
			if (recorded.code !== "recorded_decisions_file") return undefined;
			const lint = await envelope("lint", { root });
			return lint.action === "block" ? { append: lint.text } : undefined;
		},

		async "turn.finish"(): Promise<void> {
			const answer = await envelope("uncovered", { root, session });
			if (answer.action === "inject") delivered.push({ text: answer.text, when: "after-turn" });
		},
	};
}

function project(decisions = "DEC-INPUT-001: Jumping is bound to the A button.\n"): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions fifth "));
	fs.writeFileSync(path.join(dir, "DECISIONS.md"), decisions);
	for (const file of ["src/input/player.gd", "src/audio/mixer.gd"]) {
		fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
		fs.writeFileSync(path.join(dir, file), "extends Node\n");
	}
	return dir;
}

function withProject<T>(root: string, body: () => Promise<T>): Promise<T> {
	const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions fifth state "));
	const previous = process.env["DECISIONS_STATE_DIR"];
	process.env["DECISIONS_STATE_DIR"] = stateDir;
	return body().finally(() => {
		if (previous === undefined) delete process.env["DECISIONS_STATE_DIR"];
		else process.env["DECISIONS_STATE_DIR"] = previous;
		for (const dir of [root, stateDir]) fs.rmSync(dir, { recursive: true, force: true });
	});
}

test("a harness with no knowledge of core can orient, gate, annotate and ask", async () => {
	const root = project();
	await withProject(root, async () => {
		const adapter = fifthAdapter(root, "fifth-1");
		await adapter["session.begin"]();
		assert.equal(adapter.delivered.length, 1);
		assert.ok(adapter.delivered[0]?.text.includes("binding design decisions"), adapter.delivered[0]?.text ?? "no delivery");

		const file = path.join(root, "src", "input", "player.gd");
		const gate = await adapter["file.before-write"]({ path: file });
		assert.equal(gate?.deny, true);
		assert.ok(gate?.message.includes("DEC-INPUT-001: Jumping is bound to the A button."), gate?.message);
		assert.equal(await adapter["file.before-write"]({ path: file }), undefined, "the retry must pass");

		await adapter["turn.finish"]();
		assert.equal(adapter.delivered.length, 1, "a covered edit raises no question");
	});
});

test("an uncovered edit is asked about once, in the after-turn delivery", async () => {
	const root = project();
	await withProject(root, async () => {
		const adapter = fifthAdapter(root, "fifth-2");
		const file = path.join(root, "src", "audio", "mixer.gd");
		assert.equal(await adapter["file.before-write"]({ path: file }), undefined, "no decision covers audio");
		await adapter["file.after-write"]({ path: file });

		await adapter["turn.finish"]();
		const asked = adapter.delivered.at(-1);
		assert.equal(asked?.when, "after-turn");
		assert.ok(asked?.text.includes("src/audio/mixer.gd"), asked?.text);
		assert.ok(asked?.text.includes("No DECISIONS.md change needed."), asked?.text);

		await adapter["turn.finish"]();
		assert.equal(adapter.delivered.length, 1, "asked once per session");
	});
});

test("a bad DECISIONS.md write comes back as an annotation on the result", async () => {
	const root = project("DEC-INPUT-001: One rule.\nDEC-INPUT-001: A duplicate ID.\n");
	await withProject(root, async () => {
		const adapter = fifthAdapter(root, "fifth-3");
		const annotation = await adapter["file.after-write"]({ path: path.join(root, "DECISIONS.md") });
		assert.ok(annotation?.append.includes("duplicate"), annotation?.append ?? "no annotation");
	});
});

test("the adapter imports nothing from core or from a real harness", () => {
	const source = fs.readFileSync(path.join(import.meta.dirname as string, "fifth-adapter.test.ts"), "utf8");
	// Built from parts so this test's own text is not the thing it finds.
	const needles = ["core" + "/operations", "harnesses" + "/pi"];
	for (const needle of needles) {
		assert.ok(!source.includes(needle), `the fifth adapter must not depend on ${needle}`);
	}
});
