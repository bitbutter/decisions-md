/**
 * The slice of pi's extension API this adapter uses, declared locally.
 *
 * pi is the harness we run in, not a dependency of the package, and its own
 * types pull in an Electron-sized package the repo does not otherwise need. So
 * this file declares the surface enumerated in docs/ADAPTERS.md §8 — `on` with
 * the five events, `sendMessage` with the delivery modes, `registerCommand` —
 * and nothing else. It is a narrowing, not a copy: if pi renames an event or
 * drops a delivery mode, the typecheck stays green and the live-session check is
 * what catches it.
 */

declare module "@earendil-works/pi-coding-agent" {
	export interface SessionManagerLike {
		getSessionFile?(): string | undefined;
	}

	export interface ExtensionUIContext {
		notify(message: string, type?: "info" | "warning" | "error"): void;
	}

	export interface ExtensionContext {
		cwd: string;
		sessionManager?: SessionManagerLike;
		ui: ExtensionUIContext;
	}

	export interface ToolCallEvent {
		toolName: string;
		toolCallId?: string;
		input?: unknown;
	}

	export interface ToolResultContent {
		type: string;
		text?: string;
	}

	export interface ToolResultEvent extends ToolCallEvent {
		content?: ToolResultContent[];
	}

	export interface ExtensionEventMap {
		session_start: unknown;
		session_compact: unknown;
		tool_call: ToolCallEvent;
		tool_result: ToolResultEvent;
		turn_end: unknown;
	}

	export interface CustomMessage {
		customType: string;
		content: string;
		display?: boolean;
		details?: unknown;
	}

	export interface SendMessageOptions {
		deliverAs?: "steer" | "followUp" | "nextTurn";
		triggerTurn?: boolean;
	}

	export interface RegisteredCommand {
		description?: string;
		handler: (args: string, ctx: ExtensionContext) => unknown;
	}

	export interface ExtensionAPI {
		on<K extends keyof ExtensionEventMap>(
			event: K,
			handler: (event: ExtensionEventMap[K], ctx: ExtensionContext) => unknown,
		): void;
		sendMessage(message: CustomMessage, options?: SendMessageOptions): void;
		registerCommand(name: string, command: RegisteredCommand): void;
	}
}
