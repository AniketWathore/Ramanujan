/**
 * Ramanujan pi extension: math tools + human commands + prompt/guard hooks.
 *
 * Default export is the pi InlineExtension factory. Human confirmation
 * actions (/card confirm|edit|reject) are slash commands — human-only by
 * construction. The model has NO confirm tool and cannot self-confirm:
 * killcheck_run refuses unconfirmed cards AND the tool_call hook blocks them.
 *
 * Command handlers render via ctx.ui.notify (the verified output primitive)
 * and return void, matching pi's RegisteredCommand contract.
 */

import type { PiCommandContext, PiExtensionAPI } from "./piTypes.ts";
import { appendMathPrompt, reframeBareVerdict } from "./systemPrompt.ts";

export interface RamanujanExtensionOptions {
	journalPath?: string;
	engineBin?: string;
}

export default function ramanujanExtension(pi: PiExtensionAPI, opts: RamanujanExtensionOptions = {}): void {
	// System prompt contribution (chained with other extensions).
	pi.on("before_agent_start", (event) => ({ systemPrompt: appendMathPrompt(event.systemPrompt) }));

	// Bare-verdict reframe guard. The `as never` keeps pi's overload
	// resolution on message_end (our mirror widens AgentMessage).
	pi.on("message_end", (event) => {
		const msg = event.message as { role: string; content: unknown };
		if (msg.role !== "assistant" || typeof msg.content !== "string") return;
		const reframed = reframeBareVerdict(msg.content);
		if (reframed !== msg.content) {
			return { message: { ...(event.message as Record<string, unknown>), content: reframed } } as never;
		}
	});

	// No killcheck tools or v1 slash commands registered.
	// Five-stage pipeline is now via the engine CLI / shared journal:
	// Initialiser → Literature → Computational worktrees → Consolidation → Reviewer.
	// Human checkpoints are confirm/revise via the journal, not /card.
	void opts;
}

export type { PiCommandContext, PiExtensionAPI };
