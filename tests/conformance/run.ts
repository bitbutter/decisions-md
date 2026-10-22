/**
 * Conformance runner. Implements the procedure in tests/conformance/README.md:
 * copy each case into a temporary directory whose own name contains a space,
 * point DECISIONS_STATE_DIR at a fresh directory, run the steps in order, and
 * compare envelopes and files.
 *
 * Every case runs twice — once in process, once through bin/decisions.ts — and
 * the two envelope sequences must be identical. That is the adapter contract in
 * docs/ADAPTERS.md §3 and §10: an in-process adapter and a subprocess adapter
 * answer the same question the same way. `--in-process` skips the second run.
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { handle, VERBS, type VerbInput } from "../../core/operations.ts";
import type { Envelope } from "../../core/types.ts";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const CASES = path.join(HERE, "cases");
const CLI = path.join(HERE, "..", "..", "bin", "decisions.ts");

type Mode = "in-process" | "envelope";

interface Step {
	id: string;
	verb: string;
	input: Record<string, unknown>;
	expect: {
		action?: string;
		code?: string;
		text?: string;
		textIncludes?: string[];
		textExcludes?: string[];
		details?: unknown;
		files?: Record<string, string>;
		filesAbsent?: string[];
	};
}

interface Case {
	name: string;
	description: string;
	project: string;
	steps: Step[];
}

const failures: string[] = [];
let checks = 0;

function fail(caseName: string, stepId: string, message: string): void {
	failures.push(`${caseName} / ${stepId}: ${message}`);
}

/** The CLI is a subprocess adapter: one JSON object in, one out, exit 0. */
function callEnvelope(verb: string, input: Record<string, unknown>): Promise<Envelope> {
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
		child.on("close", (code) => {
			if (code !== 0) {
				reject(new Error(`${verb}: the CLI exited ${code} instead of 0\n    stderr: ${stderr.trim()}`));
				return;
			}
			const lines = stdout.trim().split("\n");
			if (lines.length !== 1) {
				reject(new Error(`${verb}: the CLI wrote ${lines.length} line(s) on stdout, expected one JSON envelope`));
				return;
			}
			try {
				resolve(JSON.parse(lines[0] ?? "") as Envelope);
			} catch {
				reject(new Error(`${verb}: the CLI did not emit JSON on stdout: ${JSON.stringify(stdout)}`));
			}
		});
		child.stdin.end(JSON.stringify({ verb, ...input }));
	});
}

/**
 * Replace the run's temporary paths with their tokens, so the in-process run and
 * the envelope run — two copies in two different directories — can be compared
 * field for field. The state directory carries a hash of the project path, so the
 * hash is a token too: it must differ between two copies by design.
 */
function scrubPaths(value: unknown, vars: Record<string, string>): unknown {
	if (typeof value === "string") {
		let out = value;
		for (const [token, real] of Object.entries(vars)) {
			for (const variant of new Set([real, real.split(path.sep).join("/"), real.split("/").join(path.sep)])) {
				if (variant) out = out.split(variant).join(token);
			}
		}
		return out.replace(/project-[0-9a-f]{6,}/g, "project-$KEY");
	}
	if (Array.isArray(value)) return value.map((item) => scrubPaths(item, vars));
	if (value && typeof value === "object") {
		const out: Record<string, unknown> = {};
		for (const [key, item] of Object.entries(value)) out[key] = scrubPaths(item, vars);
		return out;
	}
	return value;
}

function walk(dir: string, base = dir): Map<string, string> {
	const out = new Map<string, string>();
	let entries: fs.Dirent[];
	try {
		entries = fs.readdirSync(dir, { withFileTypes: true });
	} catch {
		return out;
	}
	for (const entry of entries) {
		const full = path.join(dir, entry.name);
		if (entry.isDirectory()) {
			for (const [k, v] of walk(full, base)) out.set(k, v);
		} else if (entry.isFile()) {
			const rel = path.relative(base, full).split(path.sep).join("/");
			out.set(rel, createHash("sha256").update(fs.readFileSync(full)).digest("hex"));
		}
	}
	return out;
}

function copyTree(from: string, to: string): void {
	fs.cpSync(from, to, { recursive: true });
}

function substitute(value: unknown, vars: Record<string, string>): unknown {
	if (typeof value === "string") {
		let out = value;
		for (const [name, replacement] of Object.entries(vars)) out = out.split(name).join(replacement);
		return out;
	}
	if (Array.isArray(value)) return value.map((v) => substitute(v, vars));
	if (value && typeof value === "object") {
		const out: Record<string, unknown> = {};
		for (const [k, v] of Object.entries(value)) out[k] = substitute(v, vars);
		return out;
	}
	return value;
}

function deepPartial(actual: unknown, expected: unknown, where: string): void {
	if (Array.isArray(expected)) {
		if (!Array.isArray(actual)) throw new Error(`${where}: expected an array, got ${typeof actual}`);
		if (actual.length !== expected.length) {
			throw new Error(`${where}: expected ${expected.length} item(s), got ${actual.length}`);
		}
		expected.forEach((item, i) => deepPartial(actual[i], item, `${where}[${i}]`));
		return;
	}
	if (expected && typeof expected === "object") {
		if (!actual || typeof actual !== "object" || Array.isArray(actual)) {
			throw new Error(`${where}: expected an object, got ${typeof actual}`);
		}
		for (const [key, value] of Object.entries(expected as Record<string, unknown>)) {
			deepPartial((actual as Record<string, unknown>)[key], value, `${where}.${key}`);
		}
		return;
	}
	const a = JSON.stringify(actual);
	const e = JSON.stringify(expected);
	if (a !== e) throw new Error(`${where}: expected ${e}, got ${a}`);
}

async function runCase(caseDir: string, mode: Mode): Promise<Envelope[]> {
	const loaded = JSON.parse(fs.readFileSync(path.join(caseDir, "case.json"), "utf8")) as Case;
	const name = loaded.name;
	const envelopes: Envelope[] = [];

	const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "decisions conformance "));
	const caseCopy = path.join(tmpRoot, "case");
	copyTree(caseDir, caseCopy);
	const stateDir = path.join(tmpRoot, "state");
	fs.mkdirSync(stateDir, { recursive: true });

	const previousStateDir = process.env["DECISIONS_STATE_DIR"];
	process.env["DECISIONS_STATE_DIR"] = stateDir;

	const project = path.join(caseCopy, loaded.project);
	const vars = {
		$CASE: caseCopy,
		$PROJECT: project,
		$STATE: stateDir,
	};
	// Longest path first: $PROJECT begins with $CASE.
	const scrubVars = { $PROJECT: project, $CASE: caseCopy, $STATE: stateDir };

	try {
		for (const step of loaded.steps) {
			const before = walk(caseCopy);
			const input = substitute(step.input, vars) as Record<string, unknown>;
			const verb = step.verb;
			if (!Object.prototype.hasOwnProperty.call(VERBS, verb)) {
				fail(name, step.id, `unknown verb ${verb}`);
				continue;
			}

			let raw: Envelope;
			try {
				raw = mode === "in-process" ? handle(verb, input as VerbInput) : await callEnvelope(verb, input);
			} catch (error) {
				fail(name, step.id, (error as Error).message);
				continue;
			}
			const envelope = scrubPaths(raw, scrubVars) as Envelope;
			envelopes.push(envelope);

			checks += 1;
			const expect = step.expect;
			if (expect.action !== undefined && envelope.action !== expect.action) {
				fail(name, step.id, `action: expected ${expect.action}, got ${envelope.action}`);
			}
			if (expect.code !== undefined && envelope.code !== expect.code) {
				fail(name, step.id, `code: expected ${expect.code}, got ${envelope.code}`);
			}
			if (expect.text !== undefined && envelope.text !== expect.text) {
				fail(
					name,
					step.id,
					`text mismatch\n    expected: ${JSON.stringify(expect.text)}\n    actual:   ${JSON.stringify(envelope.text)}`,
				);
			}
			for (const needle of expect.textIncludes ?? []) {
				if (!envelope.text.includes(needle)) {
					fail(name, step.id, `text is missing ${JSON.stringify(needle)}\n    actual: ${JSON.stringify(envelope.text)}`);
				}
			}
			for (const needle of expect.textExcludes ?? []) {
				if (envelope.text.includes(needle)) {
					fail(name, step.id, `text unexpectedly contains ${JSON.stringify(needle)}`);
				}
			}
			if (expect.details !== undefined) {
				try {
					deepPartial(envelope.details, expect.details, "details");
				} catch (error) {
					fail(name, step.id, (error as Error).message);
				}
			}

			const after = walk(caseCopy);
			const declared = new Set(Object.keys(expect.files ?? {}));
			for (const rel of new Set([...before.keys(), ...after.keys()])) {
				if (before.get(rel) === after.get(rel)) continue;
				if (declared.has(rel)) continue;
				fail(name, step.id, `file changed but is not declared in expect.files: ${rel}`);
			}
			for (const [rel, reference] of Object.entries(expect.files ?? {})) {
				const actualFile = path.join(caseCopy, rel);
				const referenceFile = path.join(caseDir, reference);
				let actual: Buffer;
				try {
					actual = fs.readFileSync(actualFile);
				} catch {
					fail(name, step.id, `expected file missing: ${rel}`);
					continue;
				}
				const expected = fs.readFileSync(referenceFile);
				if (!actual.equals(expected)) {
					fail(name, step.id, `${rel} does not match ${reference}`);
				}
			}
			for (const rel of expect.filesAbsent ?? []) {
				if (fs.existsSync(path.join(caseCopy, rel))) {
					fail(name, step.id, `file should not exist: ${rel}`);
				}
			}
		}
	} finally {
		if (previousStateDir === undefined) delete process.env["DECISIONS_STATE_DIR"];
		else process.env["DECISIONS_STATE_DIR"] = previousStateDir;
		fs.rmSync(tmpRoot, { recursive: true, force: true });
	}
	return envelopes;
}

async function main(): Promise<void> {
	let names: string[];
	try {
		names = fs
			.readdirSync(CASES)
			.filter((name) => fs.existsSync(path.join(CASES, name, "case.json")))
			.sort();
	} catch {
		console.error(`no cases found under ${CASES}`);
		process.exit(1);
	}

	const envelopeRun = !process.argv.includes("--in-process");
	let compared = 0;

	for (const name of names) {
		const caseDir = path.join(CASES, name);
		const inProcess = await runCase(caseDir, "in-process");
		if (!envelopeRun) continue;

		const throughEnvelope = await runCase(caseDir, "envelope");
		if (inProcess.length !== throughEnvelope.length) {
			fail(
				name,
				"case",
				`different step counts: ${inProcess.length} in process, ${throughEnvelope.length} through the envelope`,
			);
		}
		for (let i = 0; i < Math.min(inProcess.length, throughEnvelope.length); i += 1) {
			compared += 1;
			const a = JSON.stringify(inProcess[i]);
			const b = JSON.stringify(throughEnvelope[i]);
			if (a !== b) {
				fail(
					name,
					`step ${i + 1}`,
					`in process and through the envelope disagree\n    in process: ${a}\n    envelope:   ${b}`,
				);
			}
		}
	}

	const steps = envelopeRun ? checks / 2 : checks;
	if (failures.length > 0) {
		console.error(`conformance: ${failures.length} failure(s), ${steps} step(s) run\n`);
		for (const failure of failures) console.error(`  ${failure}\n`);
		process.exit(1);
	}
	const agreement = envelopeRun ? `, ${compared} envelope(s) agree with the in-process run` : " (in process only)";
	console.log(`conformance: ${names.length} case(s), ${steps} step(s), all passed${agreement}`);
}

await main();
