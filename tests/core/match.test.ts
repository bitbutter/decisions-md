import assert from "node:assert/strict";
import test from "node:test";
import { entriesForAreas, globMatch, matchAreas, simpleStem, tokenize } from "../../core/match.ts";
import type { Entry } from "../../core/types.ts";

function entry(id: string, statement: string, area: string): Entry {
	return { id, statement, area, fields: [], line: 1, lineCount: 1 };
}

test("glob: * does not cross a separator, ** does", () => {
	assert.equal(globMatch("src/a.gd", "src/*.gd"), true);
	assert.equal(globMatch("src/deep/a.gd", "src/*.gd"), false);
	assert.equal(globMatch("src/deep/a.gd", "src/**"), true);
	assert.equal(globMatch("src/deep/a.gd", "src/**/*.gd"), true);
	assert.equal(globMatch("other/a.gd", "src/**"), false);
});

test("stemming pairs plurals without mangling ss/us/is words", () => {
	assert.equal(simpleStem("cards"), "card");
	assert.equal(simpleStem("enemies"), "enemy");
	assert.equal(simpleStem("boxes"), "box");
	for (const word of ["class", "status", "process", "buses"]) assert.equal(simpleStem(word), simpleStem(word));
	assert.equal(simpleStem("class"), "class");
	assert.equal(simpleStem("status"), "status");
	assert.equal(simpleStem("process"), "process");
});

test("tokenize splits camelCase, snake_case and kebab-case, dropping short words", () => {
	const tokens = tokenize("PlayerController enemy_ai big-dodge a");
	assert.ok(tokens.has("player"));
	assert.ok(tokens.has("controller"));
	assert.ok(tokens.has("enemy"));
	assert.ok(tokens.has("dodge"));
	assert.ok(!tokens.has("a"));
});

test("a multi-segment area matches any of its segments in the path", () => {
	const entries = [entry("DEC-ENEMY-AI-001", "Monsters share one classifier.", "enemy-ai")];
	assert.deepEqual(matchAreas(entries, "src/enemy/monster.gd"), ["enemy-ai"]);
	assert.deepEqual(matchAreas(entries, "src/ui/hud.gd"), []);
});

test("area_map and a path token are unioned, map first", () => {
	const entries = [
		entry("DEC-ECONOMY-001", "Gold is earned in combat.", "economy"),
		entry("DEC-INPUT-001", "Jump is on A.", "input"),
	];
	const areas = matchAreas(entries, "src/input/systems.gd", { "src/input/*.gd": "economy" });
	assert.equal(areas[0], "economy");
	assert.ok(areas.includes("input"));
});

test("the fallback weighs a word by which area owns it", () => {
	const entries = [
		entry("DEC-CORE-001", "The atlas is rebuilt at load.", "core"),
		entry("DEC-CORE-002", "The atlas holds every sprite sheet.", "core"),
		entry("DEC-CORE-003", "Atlas padding is fixed.", "core"),
		entry("DEC-UI-001", "Tooltips fade after two seconds.", "ui"),
	];
	assert.deepEqual(matchAreas(entries, "src/atlas_cache.gd"), ["core"]);
});

test("a path with no relation to any area matches nothing", () => {
	const entries = [entry("DEC-INPUT-001", "Jump is on A.", "input")];
	assert.deepEqual(matchAreas(entries, "src/audio/mixer.gd"), []);
});

test("entriesForAreas drops empty statements and caps with a withheld count", () => {
	const entries = [
		entry("DEC-AA-001", "one", "aa"),
		entry("DEC-AA-002", "", "aa"),
		...Array.from({ length: 20 }, (_, i) => entry(`DEC-AA-${String(i + 10).padStart(3, "0")}`, `rule ${i}`, "aa")),
	];
	const { shown, withheld } = entriesForAreas(entries, ["aa"], 15);
	assert.equal(shown.length, 15);
	assert.equal(withheld, 6);
	assert.ok(shown.every((e) => e.statement !== ""));
});
