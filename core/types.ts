/**
 * Shared types. Structural only: no classes, no harness vocabulary.
 */

/** What the engine wants a harness to do. See docs/ADAPTERS.md §2. */
export type Action = "none" | "inject" | "block" | "fail";

/** One lint finding. `line` is absent for file-level findings. */
export interface Issue {
	code: string;
	message: string;
	line?: number;
}

/** One `Key: value` line under an entry. `Context` is the conventional one. */
export interface Field {
	key: string;
	value: string;
}

/** One parsed entry. */
export interface Entry {
	id: string;
	/** Area label: the ID's area segments, lowercased, hyphen-joined. */
	area: string;
	/** Statement, wrapped lines joined with single spaces. */
	statement: string;
	fields: Field[];
	/** 1-based line of the ID line, over the normalised text. */
	line: number;
	/** Non-blank lines from the ID line to the next ID line. */
	lineCount: number;
}

/** Normalised project config, `.decisions/config.json`. */
export interface Config {
	enabled: boolean;
	trackedExtensions: string[];
	exemptPaths: string[];
	areaMap: Record<string, string>;
}

/** The wire format. See docs/ADAPTERS.md §3. */
export interface Envelope {
	action: Action;
	text: string;
	code: string;
	details: Record<string, unknown>;
}

/** A read decisions file: normalised text plus whether the bytes were valid UTF-8. */
export interface ReadResult {
	text: string;
	validUtf8: boolean;
}

export interface MigrationReport {
	trivialStatus: number;
	nontrivialStatus: number;
	superseded: { line: number; id: string; successor: string | null }[];
	formatErrors: number;
}

export class InvalidInput extends Error {}
