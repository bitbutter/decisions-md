/**
 * Conformance runner. Implements the procedure in tests/conformance/README.md:
 * copy each case into a temporary directory whose own name contains a space,
 * point DECISIONS_STATE_DIR at a fresh directory, run the steps in order, and
 * compare envelopes and files.
 */

import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { handle, VERBS, type VerbInput } from "../../core/operations.ts";
import type { Envelope } from "../../core/types.ts";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const CASES = path.join(HERE, "cases");

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

function runCase(caseDir: string): void {
	const loaded = JSON.parse(fs.readFileSync(path.join(caseDir, "case.json"), "utf8")) as Case;
	const name = loaded.name;

	const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "decisions conformance "));
	const caseCopy = path.join(tmpRoot, "case");
	copyTree(caseDir, caseCopy);
	const stateDir = path.join(tmpRoot, "state");
	fs.mkdirSync(stateDir, { recursive: true });

	const previousStateDir = process.env["DECISIONS_STATE_DIR"];
	process.env["DECISIONS_STATE_DIR"] = stateDir;

	const vars = {
		$CASE: caseCopy,
		$PROJECT: path.join(caseCopy, loaded.project),
		$STATE: stateDir,
	};

	try {
		for (const step of loaded.steps) {
			const before = walk(caseCopy);
			const input = substitute(step.input, vars) as Record<string, unknown>;
			const verb = step.verb;
			if (!Object.prototype.hasOwnProperty.call(VERBS, verb)) {
				fail(name, step.id, `unknown verb ${verb}`);
				continue;
			}

			const envelope: Envelope = handle(verb, input as VerbInput);

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
}

function main(): void {
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

	for (const name of names) runCase(path.join(CASES, name));

	if (failures.length > 0) {
		console.error(`conformance: ${failures.length} failure(s), ${checks} step(s) run\n`);
		for (const failure of failures) console.error(`  ${failure}\n`);
		process.exit(1);
	}
	console.log(`conformance: ${names.length} case(s), ${checks} step(s), all passed`);
}

main();
