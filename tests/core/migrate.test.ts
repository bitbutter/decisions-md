import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import { archiveSuperseded, checkMigration, supersededRecords, writeMigration } from "../../core/migrate.ts";

function tmp(content: string | Buffer, name = "DECISIONS.md"): { dir: string; file: string } {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions-migrate-"));
	const file = path.join(dir, name);
	fs.writeFileSync(file, content);
	return { dir, file };
}

test("--write removes trivial status lines only, and is idempotent", () => {
	const { file } = tmp("DEC-AA-001: rule\nStatus: Active (2026-01-02)\n\nDEC-AA-002: rule\nStatus: Active (2026-01-02) do not delete me\n");
	const first = writeMigration(file);
	assert.deepEqual(first, { removed: 1, kept: 1, changed: true });
	const after = fs.readFileSync(file, "utf8");
	assert.ok(after.includes("Status: Active (2026-01-02) do not delete me"));
	assert.ok(!after.includes("DEC-AA-001: rule\nStatus: Active (2026-01-02)"));
	const second = writeMigration(file);
	assert.deepEqual(second, { removed: 0, kept: 1, changed: false });
	assert.equal(fs.readFileSync(file, "utf8"), after);
});

test("--write keeps CRLF terminators byte for byte", () => {
	const { file } = tmp("DEC-AA-001: rule\r\nStatus: Active\r\n\r\nDEC-AA-002: rule\r\n");
	writeMigration(file);
	assert.equal(fs.readFileSync(file, "utf8"), "DEC-AA-001: rule\r\n\r\nDEC-AA-002: rule\r\n");
});

test("a file with nothing to remove is left byte-identical, BOM included", () => {
	const original = Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from("DEC-AA-001: rule\n")]);
	const { file } = tmp(original);
	const result = writeMigration(file);
	assert.equal(result.changed, false);
	assert.deepEqual(fs.readFileSync(file), original);
});

test("a non-UTF-8 file is never rewritten", () => {
	const original = Buffer.from("DEC-AA-001: caf\xe9\nStatus: Active\n", "latin1");
	const { file } = tmp(original);
	assert.deepEqual(writeMigration(file), { removed: 0, kept: 0, changed: false });
	assert.deepEqual(fs.readFileSync(file), original);
});

test("successor comes from the Status value, or from the Superseded by phrase", () => {
	const text = [
		"DEC-AA-001: Superseded by DEC-AA-003 -- old shape.",
		"Status: Superseded (DEC-AA-003, 2026-01-01)",
		"",
		"DEC-AA-002: Something else.",
		"Status: Superseded (2026-01-01)",
		"",
		"DEC-AA-003: The new rule.",
		"",
	].join("\n");
	const records = supersededRecords(text);
	assert.deepEqual(
		records.map((r) => [r.entry.id, r.successorId]),
		[
			["DEC-AA-001", "DEC-AA-003"],
			["DEC-AA-002", null],
		],
	);
});

test("archiving refuses, and writes nothing, when the successor is missing", () => {
	const { dir, file } = tmp("DEC-AA-001: rule\nStatus: Superseded (DEC-AA-999, 2026-01-01)\n");
	const original = fs.readFileSync(file);
	const archive = path.join(dir, "support", "decision_archive.md");
	const result = archiveSuperseded(file, archive, "2026-01-02T03:04:05Z");
	assert.equal(result.refused, "archive_refused_missing_successor");
	assert.deepEqual(fs.readFileSync(file), original);
	assert.equal(fs.existsSync(archive), false);
});

test("archiving refuses when no successor is named at all", () => {
	const { dir, file } = tmp("DEC-AA-001: rule\nStatus: Superseded (2026-01-01)\n");
	const archive = path.join(dir, "support", "decision_archive.md");
	const result = archiveSuperseded(file, archive, "2026-01-02T03:04:05Z");
	assert.equal(result.refused, "archive_refused_no_successor");
	assert.equal(fs.existsSync(archive), false);
});

test("archiving writes the archive first and then removes the record", () => {
	const { dir, file } = tmp(
		[
			"DEC-AA-001: live rule.",
			"",
			"DEC-AA-002: Superseded by DEC-AA-003 -- gone.",
			"Status: Superseded (DEC-AA-003, 2026-01-01)",
			"",
			"DEC-AA-003: live rule two.",
			"",
		].join("\n"),
	);
	const archive = path.join(dir, "support", "decision_archive.md");
	const result = archiveSuperseded(file, archive, "2026-01-02T03:04:05Z");
	assert.deepEqual(result.archived, ["DEC-AA-002"]);
	assert.equal(
		fs.readFileSync(file, "utf8"),
		"DEC-AA-001: live rule.\n\nDEC-AA-003: live rule two.\n",
	);
	const archived = fs.readFileSync(archive, "utf8");
	assert.ok(archived.startsWith("# Decision archive\n"));
	assert.ok(archived.includes("## Archived 2026-01-02T03:04:05Z from DECISIONS.md"));
	assert.ok(archived.includes("DEC-AA-002: Superseded by DEC-AA-003 -- gone.\nStatus: Superseded (DEC-AA-003, 2026-01-01)"));
	// A second run has nothing to do and adds no section.
	assert.deepEqual(archiveSuperseded(file, archive, "2026-01-09T00:00:00Z"), { archived: [] });
	assert.equal(fs.readFileSync(archive, "utf8"), archived);
});

test("check reports counts without touching anything", () => {
	const { file } = tmp("DEC-AA-001: rule\nStatus: Active\n\nDEC-AA-002: rule\nStatus: Active (2026-01-01) note\n");
	const before = fs.readFileSync(file);
	const report = checkMigration(file);
	assert.equal(report.trivialStatus, 1);
	assert.equal(report.nontrivialStatus, 1);
	assert.equal(report.superseded.length, 0);
	assert.ok(report.formatErrors >= 2);
	assert.deepEqual(fs.readFileSync(file), before);
});
