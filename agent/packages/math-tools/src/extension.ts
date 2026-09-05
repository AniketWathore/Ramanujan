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

import { mathToolCallGate, confirmVerdict, createMathTools, type MathToolDeps } from "./tools.ts";
import { createPanelReviewTool, loadPanelistsFromConfig, renderPanelCard, runPanel } from "./panel.ts";
import { PendingCardStore } from "./pendingCards.ts";
import type { PiCommandContext, PiExtensionAPI } from "./piTypes.ts";
import { appendMathPrompt, reframeBareVerdict } from "./systemPrompt.ts";
import { listRuns, renderResultCard, renderRunList } from "./render.ts";

export interface RamanujanExtensionOptions extends MathToolDeps {
	journalPath?: string;
	engineBin?: string;
}

export default function ramanujanExtension(pi: PiExtensionAPI, opts: RamanujanExtensionOptions = {}): void {
	const { store, definitions } = createMathTools(opts);
	const journalPath = opts.journalPath ?? "journal.jsonl";

	for (const tool of definitions) {
		pi.registerTool(tool);
	}
	pi.registerTool(createPanelReviewTool({ journalPath, engineBin: opts.engineBin, store }));

	// Harness gate: block unconfirmed killcheck_run at the harness level too.
	pi.on("tool_call", (event) => mathToolCallGate(store, event));

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

	// Human commands.
	pi.registerCommand("card", {
		description: "Confirm, edit, reject, or show the pending claim card",
		handler: async (args: string, ctx: PiCommandContext) => {
			ctx.ui.notify(await cardCommand(store, opts, args), "info");
		},
	});
	pi.registerCommand("runs", {
		description: "List verification runs from the shared journal",
		handler: async (_args: string, ctx: PiCommandContext) => {
			ctx.ui.notify(renderRunList(await listRuns(opts.engineBin, journalPath)).split("\n").slice(0, 12).join("\n"), "info");
		},
	});
	pi.registerCommand("panel", {
		description: "Run multi-model panel review on a pending card: /panel [card_id]",
		handler: async (args: string, ctx: PiCommandContext) => {
			const cardId = args.trim().split(/\s+/)[0];
			const entry = cardId ? store.get(cardId) : store.reviewable();
			if (!entry) {
				ctx.ui.notify("No card to review. Encode one first with killcheck_encode, or pass a confirmed card id: /panel <card_id>.", "warning");
				return;
			}
			let panelists;
			try {
				panelists = loadPanelistsFromConfig();
			} catch (e) {
				ctx.ui.notify(`Panel unavailable: ${e}. Configure ≥2 panelists (roles set-panel …).`, "error");
				return;
			}
			const result = await runPanel(entry.card, entry.lastSummary ?? "no prior killcheck in this session", panelists, {
				journalPath,
				engineBin: opts.engineBin,
			});
			ctx.ui.notify(renderPanelCard(result).split("\n").slice(0, 20).join("\n"), "info");
		},
	});
	pi.registerCommand("verdict", {
		description: "Tap ground truth: /verdict <run_id> correct|incorrect",
		handler: async (args: string, ctx: PiCommandContext) => {
			const [runId, word] = args.trim().split(/\s+/);
			if (!runId || (word !== "correct" && word !== "incorrect")) {
				ctx.ui.notify("Usage: /verdict <run_id> correct|incorrect", "warning");
				return;
			}
			confirmVerdict(journalPath, runId, word === "correct");
			ctx.ui.notify(`Recorded ground truth for ${runId}: ${word}`, "info");
		},
	});
}

async function cardCommand(store: PendingCardStore, opts: RamanujanExtensionOptions, args: string): Promise<string> {
	void opts;
	const [sub, ...rest] = args.trim().split(/\s+/);
	if (sub === "confirm") {
		const entry = store.pending()[0];
		if (!entry && !rest[0]) return "No pending card.";
		const target = rest[0] ? store.get(rest[0]) : store.pending()[0];
		if (!target) return `No pending card ${rest[0] ?? ""}.`;
		store.confirm(target.cardId);
		return `Card ${target.cardId} confirmed — killcheck_run may now proceed. Next: tell the agent to run it (e.g. say "run it") — confirming alone does not start the check.`;
	}
	if (sub === "reject") {
		const target = rest[0] ? store.get(rest[0]) : store.pending()[0];
		if (!target) return "No pending card.";
		store.reject(target.cardId);
		return `Card ${target.cardId} rejected — nothing will run.`;
	}
	if (sub === "edit") {
		// /card edit <card_id> <card-json> — re-validated through the engine ClaimCard schema via bridge check at run time;
		// here we validate JSON shape only (full schema check happens in killcheck_run via the engine).
		const cardId = rest[0];
		const target = cardId ? store.get(cardId) : store.pending()[0];
		if (!target) return "No pending card.";
		const jsonText = rest.slice(cardId ? 1 : 0).join(" ");
		if (!jsonText) return "Usage: /card edit <card_id> <card-json>";
		let parsed: unknown;
		try {
			parsed = JSON.parse(jsonText);
		} catch {
			return "Edit failed: not valid JSON.";
		}
		// Structural check now; the engine validates the full ClaimCard schema when the confirmed card runs.
		if (typeof parsed !== "object" || parsed === null || (parsed as { card_id?: unknown }).card_id !== target.cardId) {
			return `Edit failed: card_id must stay ${target.cardId}.`;
		}
		store.edit(parsed as Parameters<PendingCardStore["edit"]>[0]);
		return `Card ${target.cardId} edited + confirmed — killcheck_run may now proceed. Next: tell the agent to run it (e.g. say "run it") — confirming alone does not start the check.`;
	}
	// show
	const pend = store.pending();
	if (pend.length === 0) return "No pending cards.";
	return pend.map((p) => `Pending ${p.cardId}: ${p.card.statement_informal}\nConclusion: ${p.card.conclusion.expr}\n/card confirm ${p.cardId} | /card reject ${p.cardId}`).join("\n\n");
}

export { renderResultCard };
export type { PiCommandContext, PiExtensionAPI };
