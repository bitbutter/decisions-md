/**
 * The live check: does a real pi session actually get a decision in front of the
 * model? docs/ADAPTERS.md §8 and the plan's Phase 1 exit criterion ask for proof
 * from a transcript, not from a fixture.
 *
 * It builds a throwaway project whose only decision carries a random token, asks
 * pi to edit a covered file through the adapter loaded alone, and then reads the
 * session JSONL back looking for that token.
 *
 * Outcomes, one line each:
 *   live: pass (…)       the token reached the transcript and the edit landed
 *   live: fail (…)       the session exists but the contract did not hold
 *   live: unchecked (…)  the transcript could not be read at all — never "pass"
 *
 * Exit codes: 0 pass, 1 fail, 2 unchecked, so a wrapper can never read "could
 * not check" as success.
 *
 * A live run costs one model turn. It is not part of `npm test`.
 */

import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const ADAPTER = path.join(HERE, "..", "..", "harnesses", "pi", "index.ts");
/**
 * Model: DeepSeek Flash by default because it is cheap and stays available when
 * the z.ai coding plan is out of quota; override with DECISIONS_LIVE_MODEL.
 */
const MODEL = process.env["DECISIONS_LIVE_MODEL"] ?? "deepseek/deepseek-flash";
const TIMEOUT_MS = Number(process.env["DECISIONS_LIVE_TIMEOUT_MS"] ?? 180_000);

/**
 * What a provider says when it refuses to work. Matching any of these turns an
 * exit code into "the harness never ran", not "the adapter is broken".
 */
const PROVIDER_FAILURE = /(limit exhausted|weekly\/monthly limit|rate limit|quota|insufficient|not authenticated|no credentials|invalid api key|\b(401|402|403|429)\b)/i;

interface Outcome {
	status: "pass" | "fail" | "unchecked";
	detail: string;
}

function project(token: string): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "decisions live "));
	fs.writeFileSync(
		path.join(dir, "DECISIONS.md"),
		`DEC-INPUT-001: The decisions engine serves token ${token} when input code is edited.\n`,
	);
	fs.mkdirSync(path.join(dir, "src", "input"), { recursive: true });
	fs.writeFileSync(path.join(dir, "src", "input", "player.gd"), "extends Node\n");
	return dir;
}

/**
 * pi is installed as a shell shim, and a bare `pi` cannot be spawned on Windows
 * (ENOENT: the shim is a .cmd). Resolve the JavaScript entry instead.
 */
function piCli(): string | null {
	const candidates: string[] = [];
	if (process.env["DECISIONS_PI_CLI"]) candidates.push(process.env["DECISIONS_PI_CLI"]);
	const packageSuffix = path.join("@earendil-works", "pi-coding-agent", "dist", "cli.js");
	try {
		const globalRoot = execFileSync(process.platform === "win32" ? "npm.cmd" : "npm", ["root", "-g"], { encoding: "utf8" });
		candidates.push(path.join(String(globalRoot).trim(), packageSuffix));
	} catch {
		// npm may not be on PATH; fall through to the interpreter prefix
	}
	candidates.push(path.join(path.dirname(process.execPath), "node_modules", packageSuffix));
	for (const candidate of candidates) {
		if (candidate && fs.existsSync(candidate)) return candidate;
	}
	return null;
}

function piVersion(cli: string): string {
	try {
		const out = execFileSync(process.execPath, [cli, "--version"], { encoding: "utf8" });
		return String(out).trim() || "unknown";
	} catch {
		return "unknown";
	}
}

/** Every .jsonl under the session dir, newest last. */
function transcripts(dir: string): string[] {
	const out: string[] = [];
	const walk = (current: string): void => {
		let entries: fs.Dirent[];
		try {
			entries = fs.readdirSync(current, { withFileTypes: true });
		} catch {
			return;
		}
		for (const entry of entries) {
			const full = path.join(current, entry.name);
			if (entry.isDirectory()) walk(full);
			else if (entry.isFile() && entry.name.endsWith(".jsonl")) out.push(full);
		}
	};
	walk(dir);
	return out;
}

function firstLine(text: string): string {
	const line = text.split(/\n/).map((l) => l.trim()).find((l) => l !== "") ?? "";
	return line.length > 300 ? `${line.slice(0, 300)}…` : line;
}

function sessionId(paths: string[]): string {
	return paths.map((p) => path.basename(p, ".jsonl")).join(", ");
}

async function run(cli: string, root: string, sessionDir: string): Promise<{ code: number; stdout: string; stderr: string }> {
	return new Promise((resolve) => {
		const args = [
			"-p",
			"--model",
			MODEL,
			"--no-extensions",
			"--extension",
			ADAPTER,
			"--no-skills",
			"--no-prompt-templates",
			"--session-dir",
			sessionDir,
			"Use the edit tool to append the line `# decisions live check` to src/input/player.gd. Then reply with exactly DONE.",
		];
		const child = spawn(process.execPath, [cli, ...args], { cwd: root, stdio: ["ignore", "pipe", "pipe"], shell: false });
		let stdout = "";
		let stderr = "";
		const timer = setTimeout(() => {
			child.kill();
			resolve({ code: -1, stdout, stderr: `${stderr}\n[timeout after ${TIMEOUT_MS} ms]` });
		}, TIMEOUT_MS);
		child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
			stdout += chunk;
		});
		child.stderr.setEncoding("utf8").on("data", (chunk: string) => {
			stderr += chunk;
		});
		child.on("error", (error) => {
			clearTimeout(timer);
			resolve({ code: -1, stdout, stderr: `${stderr}\n${error.message}` });
		});
		child.on("close", (code) => {
			clearTimeout(timer);
			resolve({ code: code ?? -1, stdout, stderr });
		});
	});
}

async function main(): Promise<void> {
	const cli = piCli();
	if (!cli) {
		console.log('live: unchecked (pi CLI not found; set DECISIONS_PI_CLI to the package dist/cli.js)');
		process.exitCode = 2;
		return;
	}
	const token = `LIVE-${createHash("sha256").update(String(Date.now())).digest("hex").slice(0, 8).toUpperCase()}`;
	const root = project(token);
	const sessionDir = path.join(root, ".sessions");
	fs.mkdirSync(sessionDir, { recursive: true });

	let outcome: Outcome;
	try {
		const run1 = await run(cli, root, sessionDir);
		const output = `${run1.stdout}\n${run1.stderr}`.trim();
		const files = transcripts(sessionDir);
		if (run1.code !== 0 && PROVIDER_FAILURE.test(output)) {
			// The harness never got a turn: quota, auth or a provider limit. That is
			// the one case B5 insists must never read as a pass or as a product bug.
			outcome = { status: "unchecked", detail: `pi could not run a turn: ${firstLine(output)}` };
		} else if (files.length === 0) {
			outcome = {
				status: "unchecked",
				detail: `no session file under ${sessionDir} (pi exited ${run1.code}); ${firstLine(output) || "no output"}`,
			};
		} else {
			const newest = files.sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)[0] as string;
			const transcript = fs.readFileSync(newest, "utf8");
			const served = transcript.includes(token);
			const edited = fs.readFileSync(path.join(root, "src", "input", "player.gd"), "utf8").includes("# decisions live check");
			const session = sessionId([newest]);
			if (!served) {
				outcome = {
					status: "fail",
					detail: `token ${token} is not in session ${session}; the decision never reached the model (pi exited ${run1.code})${output ? `; ${firstLine(output)}` : ""}`,
				};
			} else if (!edited) {
				outcome = { status: "fail", detail: `token ${token} was served in session ${session} but the edit never landed — the retry did not pass` };
			} else {
				outcome = { status: "pass", detail: `token ${token} in session ${session}; edit landed; pi ${piVersion(cli)}; model ${MODEL}` };
			}
		}
	} finally {
		fs.rmSync(root, { recursive: true, force: true });
	}

	console.log(`live: ${outcome.status} (${outcome.detail})`);
	process.exitCode = outcome.status === "pass" ? 0 : outcome.status === "unchecked" ? 2 : 1;
}

await main();
