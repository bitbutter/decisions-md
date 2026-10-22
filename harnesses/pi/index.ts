/**
 * pi adapter for the decisions engine. See docs/ADAPTERS.md §8.
 *
 * This file is the only place that knows pi exists. It resolves a target path,
 * supplies a session identity, and maps the engine's four actions onto pi's
 * mechanisms. It never parses a decision, matches an area, lints a file or keeps
 * decision state: every one of those answers comes back from core as a code.
 */

import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { handle } from "../../core/operations.ts";
import { pruneState } from "../../core/state.ts";
import type { Envelope } from "../../core/types.ts";

const WRITE_TOOLS = new Set(["edit", "write"]);
const CUSTOM_TYPE = "decisions-md";

interface ToolEventLike {
	toolName?: string;
	input?: unknown;
}

function targetPath(event: ToolEventLike, root: string): string | null {
	const input = event.input;
	if (!input || typeof input !== "object") return null;
	const raw = (input as Record<string, unknown>)["path"];
	if (typeof raw !== "string" || raw.trim() === "") return null;
	return path.resolve(root, raw);
}

/** One id per session; pi gives a session file when the session is persisted. */
function makeSessionId(ctx: { sessionManager?: { getSessionFile?: () => string | undefined } }): string {
	try {
		const file = ctx.sessionManager?.getSessionFile?.();
		if (typeof file === "string" && file.trim() !== "") return file;
	} catch {
		// an ephemeral session has no file
	}
	return `ephemeral-${Date.now().toString(36)}`;
}

export default function decisionsMd(pi: ExtensionAPI): void {
	let session = "ephemeral";

	const deliver = (text: string, delivery: "nextTurn" | "followUp"): void => {
		try {
			pi.sendMessage({ customType: CUSTOM_TYPE, content: text, display: false }, { deliverAs: delivery });
		} catch {
			// A failed injection must never stand between the user and their work.
		}
	};

	const notifyFailure = (() => {
		const seen = new Set<string>();
		return (ctx: { ui: { notify: (message: string, type?: "info" | "warning" | "error") => void } }, envelope: Envelope): void => {
			if (envelope.action !== "fail" || seen.has(envelope.code)) return;
			seen.add(envelope.code);
			try {
				ctx.ui.notify(`decisions: ${envelope.text} (${envelope.code})`, "warning");
			} catch {
				// no UI in this mode
			}
		};
	})();

	const orientation = (ctx: { cwd: string }): void => {
		const envelope = handle("orient", { root: ctx.cwd });
		if (envelope.action === "inject") {
			// The lookup line is the adapter's: core text names no command.
			deliver(`${envelope.text}\n  Look them up: /decisions <area|keywords>`, "nextTurn");
		}
	};

	pi.on("session_start", async (_event, ctx) => {
		session = makeSessionId(ctx);
		try {
			pruneState(ctx.cwd);
		} catch {
			// pruning is housekeeping
		}
		orientation(ctx);
	});

	pi.on("session_compact", async (_event, ctx) => {
		// Compaction is the one place the orientation can be lost.
		orientation(ctx);
	});

	pi.on("tool_call", async (event, ctx) => {
		if (!WRITE_TOOLS.has(event.toolName)) return;
		const file = targetPath(event, ctx.cwd);
		if (!file) return;
		const envelope = handle("decide", { root: ctx.cwd, file, session });
		if (envelope.action === "inject") {
			// pi feeds `reason` back to the model and the agent retries the edit. The
			// area is already claimed, so the retry passes.
			return { block: true, reason: envelope.text };
		}
		notifyFailure(ctx, envelope);
		return;
	});

	pi.on("tool_result", async (event, ctx) => {
		if (!WRITE_TOOLS.has(event.toolName)) return;
		const file = targetPath(event, ctx.cwd);
		if (!file) return;

		const recorded = handle("record-edit", { root: ctx.cwd, file, session });
		notifyFailure(ctx, recorded);

		if (recorded.code !== "recorded_decisions_file") return;
		const played = handle("lint", { root: ctx.cwd });
		if (played.action !== "block") return;
		// The write already happened and cannot be reverted, so the report is
		// attached to the result instead of blocking anything.
		const content = Array.isArray(event.content) ? event.content : [];
		return { content: [...content, { type: "text" as const, text: played.text }] };
	});

	pi.on("turn_end", async (_event, ctx) => {
		const envelope = handle("uncovered", { root: ctx.cwd, session });
		if (envelope.action === "inject") deliver(envelope.text, "followUp");
		else notifyFailure(ctx, envelope);
	});

	pi.registerCommand("decisions", {
		description: "Read the project's binding DECISIONS.md: areas, one area, or a keyword search",
		handler: async (args, ctx) => {
			const trimmed = (args ?? "").trim();
			const input: { root: string; session: string; area?: string; terms?: string } = {
				root: ctx.cwd,
				session,
			};
			const areaFlag = /^--area\s+(.+)$/.exec(trimmed);
			if (areaFlag?.[1]) input.area = areaFlag[1].trim();
			else if (trimmed) input.terms = trimmed;
			const envelope = handle("query", input);
			ctx.ui.notify(envelope.text || `decisions: ${envelope.code}`, envelope.action === "fail" ? "warning" : "info");
		},
	});

	pi.registerCommand("decisions-lint", {
		description: "Check DECISIONS.md's format",
		handler: async (_args, ctx) => {
			const envelope = handle("lint", { root: ctx.cwd });
			ctx.ui.notify(envelope.text || `decisions: ${envelope.code}`, envelope.action === "fail" ? "warning" : "info");
		},
	});

	pi.registerCommand("decisions-migrate", {
		description: "Check, --write, or --archive-superseded the decisions file",
		handler: async (args, ctx) => {
			const trimmed = (args ?? "").trim();
			const mode = trimmed === "--write" ? "write" : trimmed === "--archive-superseded" ? "archive-superseded" : "check";
			const envelope = handle("migrate", { root: ctx.cwd, mode });
			ctx.ui.notify(envelope.text || `decisions: ${envelope.code}`, envelope.action === "fail" ? "warning" : "info");
		},
	});

	pi.registerCommand("decisions-doctor", {
		description: "Report whether the decisions engine is working in this project",
		handler: async (_args, ctx) => {
			const envelope = handle("doctor", { root: ctx.cwd, session });
			ctx.ui.notify(envelope.text, envelope.code === "problems" ? "warning" : "info");
		},
	});

}
