import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import { blankFencedBlocks, areaLabel, normalizeText, parseDecisions, parseId } from "../../core/parse.ts";

function tmpFile(name: string, content: string | Buffer): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-test-"));
	const file = path.join(dir, name);
	fs.writeFileSync(file, content);
	return file;
}

test("normalizeText strips a BOM, folds CRLF, and folds a whole-file CR file", () => {
	assert.equal(normalizeText("\ufeffDEC-AA-001: x\r\n"), "DEC-AA-001: x\n");
	assert.equal(normalizeText("DEC-AA-001: x\rDEC-AA-002: y"), "DEC-AA-001: x\nDEC-AA-002: y");
});

test("normalizeText leaves a lone CR in an LF file alone", () => {
	assert.equal(normalizeText("DEC-AA-001: x\rDEC-AA-002: y\n"), "DEC-AA-001: x\rDEC-AA-002: y\n");
});

test("parseDecisions joins wrapped statements and fields with single spaces", () => {
	const entries = parseDecisions(
		"DEC-AA-001: one\nwrapped over\nthree lines.\n\nContext: reason\nwrapped too.\n",
	);
	assert.equal(entries.length, 1);
	assert.equal(entries[0]?.statement, "one wrapped over three lines.");
	assert.deepEqual(entries[0]?.fields, [{ key: "Context", value: "reason wrapped too." }]);
});

test("a blank line closes the open field, so prose never joins it", () => {
	const entries = parseDecisions("DEC-AA-001: rule\nContext: reason\n\n## Heading\na note\n");
	assert.deepEqual(entries[0]?.fields, [{ key: "Context", value: "reason" }]);
	assert.equal(entries[0]?.statement, "rule");
});

test("entries written back to back parse as two entries", () => {
	const entries = parseDecisions("DEC-AA-001: one\nDEC-AA-002: two\n");
	assert.deepEqual(entries.map((e) => e.statement), ["one", "two"]);
});

test("an indented ID is not an entry and continues the statement above", () => {
	const entries = parseDecisions("DEC-AA-001: one\n  DEC-AA-002: absorbed\n");
	assert.equal(entries.length, 1);
	assert.equal(entries[0]?.statement, "one DEC-AA-002: absorbed");
	assert.equal(entries[0]?.lineCount, 2);
});

test("lineCount counts only the lines the entry occupies", () => {
	const text = "DEC-AA-001: one\n\n## Heading\n\nparagraph\n\nDEC-AA-002: two\n";
	const entries = parseDecisions(text);
	assert.deepEqual(entries.map((e) => e.lineCount), [1, 1]);
});

test("an entry with an empty statement still parses", () => {
	const entries = parseDecisions("DEC-AA-001:\n\nDEC-AA-002: two\n");
	assert.equal(entries[0]?.statement, "");
});

test("no trailing newline at end of file still parses", () => {
	const entries = parseDecisions("DEC-AA-001: only entry, no newline");
	assert.equal(entries.length, 1);
	assert.equal(entries[0]?.statement, "only entry, no newline");
});

test("whitespace around the colon is not significant", () => {
	for (const line of ["DEC-AA-001:rule", "DEC-AA-001: rule", "DEC-AA-001 : rule"]) {
		assert.equal(parseDecisions(`${line}\n`)[0]?.statement, "rule", line);
	}
});

test("a closed fence is never an entry; a four-backtick block does not end early", () => {
	const text = [
		"DEC-AA-001: live",
		"",
		"````",
		"```",
		"DEC-AA-002: example inside a nested fence",
		"```",
		"````",
		"",
		"DEC-AA-003: also live",
	].join("\n");
	const entries = parseDecisions(text);
	assert.deepEqual(entries.map((e) => e.id), ["DEC-AA-001", "DEC-AA-003"]);
	const scan = blankFencedBlocks(text.split("\n"));
	assert.equal(scan.unclosedFenceLine, undefined);
});

test("an unclosed fence blanks nothing and reports its line", () => {
	const text = "DEC-AA-001: live\n\n```\nDEC-AA-002: still live\n";
	const entries = parseDecisions(text);
	assert.deepEqual(entries.map((e) => e.id), ["DEC-AA-001", "DEC-AA-002"]);
	assert.equal(blankFencedBlocks(text.split("\n")).unclosedFenceLine, 3);
});

test("parseId accepts the grammar and rejects every near miss", () => {
	const accepted: [string, string[]][] = [
		["DEC-INPUT-001", ["INPUT"]],
		["DEC-ENEMY-AI-001", ["ENEMY", "AI"]],
		["DEC-SAVE-TRANSACTION-002", ["SAVE", "TRANSACTION"]],
		["DEC-AI-001", ["AI"]],
	];
	for (const [id, areas] of accepted) assert.deepEqual(parseId(id)?.areas, areas, id);

	const rejected = [
		"DEC-INPUT-01", "DEC-INPUT-0001", "DEC-C-001", "DEC-INPUT-007d",
		"DEC-combat-001", "Dec-INPUT-002", "DEC-ENEMY_AI-001", "DEC-IMPACT_DEMO-003",
		"DEC-INPUT 003", "DEC-INPUT-004.1", "DEC--005", "DEC-COMBAT-10-01",
		"DEC-FOO-001-002", "DEC-", "DEC-INPUT-", "DEC-ÅREA-001", "DEC-INPUT-001 ",
	];
	for (const id of rejected) assert.equal(parseId(id), null, id);
});

test("areaLabel spans segments and lowercases", () => {
	assert.equal(areaLabel("DEC-ENEMY-AI-001"), "enemy-ai");
	assert.equal(areaLabel("DEC-INPUT-001"), "input");
	assert.equal(areaLabel("DEC-NOPE"), null);
});

test("a non-UTF-8 file still parses", () => {
	const file = tmpFile("DECISIONS.md", Buffer.from("DEC-TEXT-001: caf\xe9\n", "latin1"));
	const entries = parseDecisions(fs.readFileSync(file).toString("utf8"));
	assert.equal(entries.length, 1);
	assert.ok(entries[0]?.statement.includes("caf"));
});
