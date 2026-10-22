/**
 * Adapter tests, against a fake pi. docs/ADAPTERS.md §8 is the contract: one
 * case per event mapping, so a wrong argument or a wrong delivery mode fails
 * here instead of in a live session.
 *
 * The extension imports pi's types only, so this file runs without the pi
 * package installed.
 */

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import decisionsMd from "./index.ts";

type Handler = (event: unknown, ctx: unknown) => unknown;

interface Sent {
	message: { customType: string; content: string; display?: boolean };
	options?: { deliverAs?: string };
}

function fakePi(): {
	pi: Record<string, unknown>;
	handlers: Map<string, Handler>;
	sent: Sent[];
	commands: Map<string, unknown>;
	notices: Array<{ text: string; type?: string }>;
} {
	const handlers = new Map<string, Handler>();
	const sent: Sent[] = [];
	const commands = new Map<string, unknown>();
	const notices: Array<{ text: string; type?: string }> = [];
	const pi = {
		on(name: string, handler: Handler) {
			handlers.set(name, handler);
		},
		sendMessage(message: Sent["message"], options?: Sent["options"]) {
			sent.push({ message, options });
		},
		registerCommand(name: string, spec: unknown) {
			commands.set(name, spec);
		},
	};
	return { pi, handlers, sent, commands, notices };
}

function project(decisions = "DEC-INPUT-001: Jumping is bound to the A button.\n"): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-adapter-"));
	fs.writeFileSync(path.join(dir, "DECISIONS.md"), decisions);
	for (const file of ["src/input/player.gd", "src/audio/mixer.gd"]) {
		fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
		fs.writeFileSync(path.join(dir, file), "extends Node\n");
	}
	return dir;
}

interface Harness {
	ctx: Record<string, unknown>;
	fire: (name: string, event?: unknown) => Promise<unknown>;
	sent: Sent[];
	notices: Array<{ text: string; type?: string }>;
	commands: Map<string, { handler?: (args: string, ctx: unknown) => Promise<void> }>;
	cleanup: () => void;
}

function start(root: string, opts: { sessionFile?: string } = {}): Harness {
	const { pi, handlers, sent, notices, commands } = fakePi();
	decisionsMd(pi as never);
	const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-adapter-state-"));
	const previous = process.env["DECISIONS_STATE_DIR"];
	process.env["DECISIONS_STATE_DIR"] = stateDir;
	const ctx = {
		cwd: root,
		sessionManager: { getSessionFile: () => opts.sessionFile ?? "" },
		ui: {
			notify: (text: string, type?: string) => {
				notices.push({ text, ...(type === undefined ? {} : { type }) });
			},
		},
	};
	return {
		ctx,
		sent,
		notices,
		commands: commands as Map<string, { handler?: (args: string, ctx: unknown) => Promise<void> }>,
		fire: async (name: string, event: unknown = {}) => {
			const handler = handlers.get(name);
			assert.ok(handler, `the adapter does not listen to ${name}`);
			return handler(event, ctx);
		},
		cleanup: () => {
			if (previous === undefined) delete process.env["DECISIONS_STATE_DIR"];
			else process.env["DECISIONS_STATE_DIR"] = previous;
			for (const dir of [root, stateDir]) fs.rmSync(dir, { recursive: true, force: true });
		},
	};
}

test("session_start delivers the orientation text with the adapter's lookup line", async () => {
	const h = start(project());
	try {
		await h.fire("session_start");
		assert.equal(h.sent.length, 1);
		const [delivery] = h.sent;
		assert.equal(delivery?.message.customType, "decisions-md");
		assert.equal(delivery?.message.display, false);
		assert.equal(delivery?.options?.deliverAs, "nextTurn");
		const content = delivery?.message.content ?? "";
		assert.ok(content.startsWith("[DECISIONS] This project has binding design decisions."), content);
		assert.ok(content.includes("Look them up: /decisions <area|keywords>"), content);
		assert.ok(content.includes("1 decision (input:1)"), content);
	} finally {
		h.cleanup();
	}
});

test("an edit in a covered area blocks with the decisions, and the retry passes", async () => {
	const root = project();
	const h = start(root);
	try {
		await h.fire("session_start");
		const file = path.join(root, "src", "input", "player.gd");
		const blocked = (await h.fire("tool_call", { toolName: "edit", input: { path: file } })) as
			| { block?: boolean; reason?: string }
			| undefined;
		assert.equal(blocked?.block, true);
		assert.ok(
			blocked?.reason?.includes("DEC-INPUT-001: Jumping is bound to the A button."),
			blocked?.reason ?? "no reason",
		);

		const retry = await h.fire("tool_call", { toolName: "edit", input: { path: file } });
		assert.equal(retry, undefined, "the area is claimed, so the retry must not block");
	} finally {
		h.cleanup();
	}
});

test("a non-write tool and a pathless write are left alone", async () => {
	const root = project();
	const h = start(root);
	try {
		const read = await h.fire("tool_call", { toolName: "read", input: { path: path.join(root, "src", "input", "player.gd") } });
		assert.equal(read, undefined);
		const pathless = await h.fire("tool_call", { toolName: "write", input: {} });
		assert.equal(pathless, undefined);
	} finally {
		h.cleanup();
	}
});

test("turn_end asks the uncovered question once, after an edit outside every area", async () => {
	const root = project();
	const h = start(root);
	try {
		await h.fire("session_start");
		const file = path.join(root, "src", "audio", "mixer.gd");
		await h.fire("tool_call", { toolName: "write", input: { path: file } });
		await h.fire("tool_result", { toolName: "write", input: { path: file }, content: [] });
		await h.fire("turn_end");

		const asked = h.sent.at(-1);
		assert.equal(asked?.options?.deliverAs, "followUp");
		assert.ok(asked?.message.content.startsWith("This session edited files in territory no decision currently covers: src/audio/mixer.gd."), asked?.message.content);
		assert.ok(asked?.message.content.includes("No DECISIONS.md change needed."), asked?.message.content);

		await h.fire("turn_end");
		assert.equal(h.sent.length, 2, "the question is asked once per session");
	} finally {
		h.cleanup();
	}
});

test("a write to DECISIONS.md attaches the lint report to the tool result", async () => {
	const root = project("DEC-INPUT-001: One rule.\nDEC-INPUT-001: A duplicate ID.\n");
	const h = start(root);
	try {
		const file = path.join(root, "DECISIONS.md");
		const result = (await h.fire("tool_result", { toolName: "write", input: { path: file }, content: [{ type: "text", text: "Wrote 60 bytes" }] })) as
			| { content?: Array<{ type: string; text?: string }> }
			| undefined;
		assert.equal(result?.content?.length, 2, "the original content is kept and the report appended");
		assert.equal(result?.content?.[0]?.text, "Wrote 60 bytes");
		assert.ok(result?.content?.[1]?.text?.includes("duplicate"), result?.content?.[1]?.text ?? "no lint text");
	} finally {
		h.cleanup();
	}
});

test("a clean DECISIONS.md write adds nothing to the tool result", async () => {
	const root = project();
	const h = start(root);
	try {
		const file = path.join(root, "DECISIONS.md");
		const result = await h.fire("tool_result", { toolName: "write", input: { path: file }, content: [] });
		assert.equal(result, undefined);
	} finally {
		h.cleanup();
	}
});

test("the commands are registered and /decisions-lint reports the format", async () => {
	const root = project("DEC-INPUT-001: One rule.\nDEC-INPUT-001: A duplicate ID.\n");
	const h = start(root);
	try {
		for (const name of ["decisions", "decisions-lint", "decisions-migrate", "decisions-doctor"]) {
			const spec = h.commands.get(name);
			assert.ok(spec?.handler, `${name} is not registered`);
			await spec.handler("", h.ctx);
		}
		const lint = h.notices[1];
		assert.ok(lint?.text.includes("duplicate"), lint?.text ?? "no notify");
		const doctor = h.notices[3]?.text ?? "";
		assert.ok(doctor.includes("adapter: pi"), doctor);
		assert.ok(doctor.includes("harness: 0.84.2"), doctor);
		assert.equal(h.notices.length, 4, "one report per command");
		assert.equal(h.sent.length, 0, "commands notify, they do not inject");
	} finally {
		h.cleanup();
	}
});
