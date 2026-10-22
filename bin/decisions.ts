#!/usr/bin/env node
/**
 * The subprocess envelope. See docs/ADAPTERS.md §3.
 *
 * One JSON object in on stdin, one JSON object out on stdout, exit 0 for any
 * handled request. The CLI never exits 2: that is a harness convention and it
 * belongs in an adapter.
 */

import * as fs from "node:fs";
import { handle, VERBS } from "../core/operations.ts";
import type { Envelope } from "../core/types.ts";

function emit(envelope: Envelope): void {
	process.stdout.write(`${JSON.stringify(envelope)}\n`);
}

function failEnvelope(code: string, text: string): Envelope {
	return { action: "fail", text, code, details: {} };
}

function readStdin(): string {
	try {
		return fs.readFileSync(0, "utf8");
	} catch {
		return "";
	}
}

function main(): void {
	const raw = readStdin();
	let input: Record<string, unknown>;
	try {
		input = raw.trim() === "" ? {} : (JSON.parse(raw) as Record<string, unknown>);
	} catch {
		emit(failEnvelope("invalid_input", "input is not valid JSON"));
		return;
	}

	const verb = input["verb"];
	if (typeof verb !== "string" || !Object.prototype.hasOwnProperty.call(VERBS, verb)) {
		emit(failEnvelope("invalid_input", `unknown or missing verb: ${String(verb)}`));
		return;
	}

	emit(handle(verb, input as Record<string, unknown>));
}

main();
process.exitCode = 0;
