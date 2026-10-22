import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import { lintFile } from "../../core/lint.ts";
import { parseDecisions } from "../../core/parse.ts";

function lint(content: string | Buffer, name = "DECISIONS.md") {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-lint-"));
	const file = path.join(dir, name);
	fs.writeFileSync(file, content);
	return lintFile(file);
}

test("errors carry line numbers and a stable code", () => {
	const result = lint(
		[
			"DEC-AA-001: fine",
			"Status: Active",
			"",
			"  DEC-AA-002: indented entry",
			"",
			"DEC-AA 003: space inside the identifier",
			"",
			"DEC-AA-004d: retired suffix",
			"",
			"DEC-AA_005: underscore",
			"",
			"DEC-AA-006: duplicate",
			"",
			"DEC-AA-006: again",
			"",
			"DEC-AA-007:",
		].join("\n"),
	);
	assert.deepEqual(
		result.errors.map((e) => [e.line, e.code]),
		[
			[2, "status_line"],
			[4, "malformed_id"],
			[6, "malformed_id"],
			[8, "override_suffix_id"],
			[10, "malformed_id"],
			[14, "duplicate_id"],
			[16, "missing_statement"],
		],
	);
});

test("file-level issues are ordered before line issues", () => {
	const result = lint(Buffer.concat([Buffer.from("Status: Active\n"), Buffer.from([0xff, 0xfe]), Buffer.from("\n")]));
	assert.equal(result.errors[0]?.code, "not_utf8");
	assert.equal(result.errors[0]?.line, undefined);
	assert.ok(result.errors.some((e) => e.code === "status_line"));
});

test("an unreadable file reports unreadable", () => {
	const result = lintFile(path.join(os.tmpdir(), "definitely-not-here", "DECISIONS.md"));
	assert.deepEqual(result.errors.map((e) => e.code), ["unreadable"]);
});

test("warnings fire on bloat, never on format", () => {
	const longEntry = ["DEC-AA-001: a rule", ...Array.from({ length: 8 }, () => "more text")].join("\n");
	const longStatement = `DEC-AA-002: ${Array.from({ length: 121 }, () => "word").join(" ")}`;
	const fingerprint = "DEC-AA-003: the file player.gd owns this.";
	const duplicate = "DEC-AA-004: the same rule as its sibling here.\n\nDEC-AA-005: the same rule as its sibling here.\n";
	const result = lint([longEntry, "", longStatement, "", fingerprint, "", duplicate].join("\n"));
	const codes = result.warnings.map((w) => w.code);
	assert.ok(codes.includes("entry_too_long"));
	assert.ok(codes.includes("statement_too_long"));
	assert.ok(codes.includes("code_fingerprint"));
	assert.ok(codes.includes("near_duplicate"));
	assert.equal(result.errors.length, 0);
});

test("an area over 25 entries warns once", () => {
	const lines = Array.from({ length: 26 }, (_, i) => `DEC-BIG-${String(i + 1).padStart(3, "0")}: rule number ${i}.`).join("\n\n");
	const result = lint(lines + "\n");
	const areaWarnings = result.warnings.filter((w) => w.code === "area_too_large");
	assert.equal(areaWarnings.length, 1);
});

test("near-duplicate checking is skipped for an oversized area and says so", () => {
	const lines = Array.from({ length: 251 }, (_, i) => `DEC-BIG-${String(i + 1).padStart(3, "0")}: rule number ${i}.`).join("\n\n");
	const result = lint(lines + "\n");
	assert.ok(result.warnings.some((w) => w.code === "near_duplicate_skipped"));
});

test("a status line inside a closed fence is still reported", () => {
	const result = lint("DEC-AA-001: live\n\n```\nStatus: Active\n```\n");
	assert.deepEqual(result.errors.map((e) => e.code), ["status_line"]);
	assert.equal(parseDecisions("DEC-AA-001: live\n\n```\nStatus: Active\n```\n").length, 1);
});

test("a malformed ID with no colon is not reported, and an indented valid ID is", () => {
	const result = lint("DEC-AA-001: rule mentioning DEC-BB-002 in passing\n");
	assert.equal(result.errors.length, 0);
	const indented = lint("DEC-AA-001: rule\n  DEC-BB-002: absorbed\n");
	assert.deepEqual(indented.errors.map((e) => [e.line, e.code]), [[2, "malformed_id"]]);
});

test("lint does not modify the file", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-lint-"));
	const file = path.join(dir, "DECISIONS.md");
	const content = "Status: Active\nDEC-AA-001: x\n";
	fs.writeFileSync(file, content);
	lintFile(file);
	assert.equal(fs.readFileSync(file, "utf8"), content);
});
