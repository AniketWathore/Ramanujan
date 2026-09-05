/**
 * Minimal structural mirror of the pi extension surface we use.
 *
 * WHY NOT `import type ... from "@earendil-works/pi-coding-agent"`:
 * resolving pi's src into our tsc program drags the whole pi workspace
 * (unresolvable workspace imports + rootDir violations — verified
 * experimentally). These interfaces are structural: at A7 integration time
 * pi's own compiler checks our extension factory against ExtensionAPI, and
 * any drift surfaces then. Keep in sync with
 * agent/packages/coding-agent/src/core/extensions/types.ts.
 */

export interface PiToolContent {
	type: "text";
	text: string;
}

export interface PiToolResult {
	content: PiToolContent[];
	details: unknown;
	isError?: boolean;
}

import type { TSchema } from "typebox";

export interface PiToolDefinition {
	name: string;
	label: string;
	description: string;
	parameters: TSchema;
	promptGuidelines?: string[];
	execute: (
		toolCallId: string,
		params: unknown,
		signal?: AbortSignal,
	) => Promise<PiToolResult>;
}

export interface PiToolCallEvent {
	type: "tool_call";
	toolCallId: string;
	toolName: string;
	input: Record<string, unknown>;
}

export interface PiCommandContext {
	ui: { notify(message: string, type?: "info" | "warning" | "error"): void };
}

export interface PiExtensionAPI {
	registerTool(tool: PiToolDefinition): void;
	registerCommand(
		name: string,
		options: { description?: string; handler: (args: string, ctx: PiCommandContext) => Promise<void> },
	): void;
	on(event: "tool_call", handler: (event: PiToolCallEvent) => { block?: boolean; reason?: string } | void): void;
	on(
		event: "before_agent_start",
		handler: (event: { systemPrompt: string }) => { systemPrompt?: string } | void,
	): void;
	on(
		event: "message_end",
		handler: (event: { message: { role: string; content: unknown } }) => { message?: { role: string; content: unknown } } | void,
	): void;
}
