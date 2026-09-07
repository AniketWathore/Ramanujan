/**
 * Math tools (pi-native shape): killcheck_encode + killcheck_run.
 * panel_review lands in A6 with the panel it fronts.
 *
 * Bridge functions are injectable for tests; defaults call the real engine.
 */

import { Type } from "typebox";
import { engineCheck, engineEncode, type BridgeOptions, type engineReplay } from "@ramanujan/bridge";
import { appendJournalEvent } from "@ramanujan/config";
import { PendingCardStore } from "./pendingCards.ts";
import type { PiToolDefinition } from "./piTypes.ts";
import { renderResultCard } from "./render.ts";

export interface MathToolDeps {
	bridge?: {
		encode?: typeof engineEncode;
		check?: typeof engineCheck;
		replay?: typeof engineReplay;
	};
	journalPath?: string;
	engineBin?: string;
	budgetUsd?: number;
	budgetSec?: number;
}

export interface MathTools {
	store: PendingCardStore;
	definitions: PiToolDefinition[];
}

const encodeSchema = Type.Object({
	statement: Type.String({ description: "The user's conjecture, verbatim" }),
});

const runSchema = Type.Object({
	card_id: Type.String({ description: "Pending card id (must be human-confirmed)" }),
});

export function createMathTools(deps: MathToolDeps = {}): MathTools {
	const store = new PendingCardStore();
	const bridgeOpts: BridgeOptions = {
		engineBin: deps.engineBin,
		journal: deps.journalPath,
		env: process.env["RAMANUJAN_MOCK_ENCODER"] ? { RAMANUJAN_MOCK_ENCODER: "1" } : undefined,
	};
	const encode = deps.bridge?.encode ?? engineEncode;
	const check = deps.bridge?.check ?? engineCheck;

	const killcheck_encode: PiToolDefinition = {
		name: "killcheck_encode",
		label: "Killcheck: encode",
		description:
			"Encode a natural-language mathematical conjecture into a claim card for deterministic checking. Returns the pending card (NOT yet checked — the human must confirm it first). If the statement cannot be expressed in the DSL, returns an honest NOT_ENCODABLE message.",
		parameters: encodeSchema,
		promptGuidelines: [
			"Do NOT call killcheck_encode for the Stage-1 initial problem (informal conjecture). That problem goes via ramanujan_initialise → ProblemSpec + Checkpoint A only. killcheck_encode is for worktree-formalized claims only.",
			"Call killcheck_encode only when the user explicitly gives a formalized claim to check as a ClaimCard.",
			"After it returns a pending card, ask the user to confirm (/card confirm) and WAIT — never call killcheck_run yourself on an unconfirmed card.",
		],
		execute: async (_toolCallId, params: unknown) => {
			const statement = String((params as { statement: string }).statement);
			let res: Awaited<ReturnType<typeof encode>>;
			try {
				res = await encode(statement, bridgeOpts);
			} catch (e) {
				// The bridge must never surface a bare transport failure ("no stdout").
				// Report it as an encoder-model failure with the real reason.
				const reason = e instanceof Error ? e.message : String(e);
				return {
					content: [
						{
							type: "text",
							text: `ENCODER ERROR (model failed — NOT a DSL refusal): ${reason}. The encoder model failed — re-run or switch to a stronger model. Do NOT conclude the DSL cannot express the statement.`,
						},
					],
					details: { reason, run_id: "unknown" },
				};
			}
			if (res.status === "card") {
				store.propose(res.card);
				return {
					content: [
						{
							type: "text",
							text: `Pending card ${res.card.card_id} (provider ${res.provider}, model ${res.model_id}). Awaiting HUMAN confirmation — ask the user to run /card confirm. Card: ${JSON.stringify(res.card)}`,
						},
					],
					details: { card: res.card, run_id: res.run_id },
				};
			}
			if (res.status === "not_encodable") {
				return {
					content: [{ type: "text", text: `NOT_ENCODABLE (honest): ${res.reason}. The statement is outside the current claim-card DSL.` }],
					details: { reason: res.reason, run_id: res.run_id },
				};
			}
			if (res.status === "encoder_error") {
				return {
					content: [
						{
							type: "text",
							text: `ENCODER ERROR (model failed — NOT a DSL refusal): ${res.reason}. The encoder model failed — re-run or switch to a stronger model. Do NOT conclude the DSL cannot express the statement.`,
						},
					],
					details: { reason: res.reason, run_id: res.run_id },
				};
			}
			if (res.status === "error") {
				return {
					content: [
						{
							type: "text",
							text: `ENCODER ERROR (model failed — NOT a DSL refusal): ${res.message}. The encoder model failed — re-run or switch to a stronger model. Do NOT conclude the DSL cannot express the statement.`,
						},
					],
					details: { reason: res.message, run_id: res.run_id },
				};
			}
			throw new Error(`encode failed: ${JSON.stringify(res).slice(0, 300)}`);
		},
	};

	const killcheck_run: PiToolDefinition = {
		name: "killcheck_run",
		label: "Killcheck: run",
		description:
			"Run the deterministic killcheck engine on a HUMAN-CONFIRMED claim card. REFUSES unconfirmed cards — the human must confirm via /card confirm first. Returns the engine verdict (refuted/survived/budget_exceeded) with double-verification status.",
		parameters: runSchema,
		promptGuidelines: [
			"NEVER call killcheck_run unless the human has confirmed the card. The call will be refused.",
			"When the user says they already confirmed the card in the TUI, call killcheck_run with its card_id — do not ask them to confirm again.",
			"Render the returned verdict exactly as given; never restate it from reasoning.",
		],
		execute: async (_toolCallId, params: unknown) => {
			const cardId = String((params as { card_id: string }).card_id);
			const entry = store.get(cardId);
			if (!entry) {
				return {
					content: [{ type: "text", text: `REFUSED: no pending card ${cardId}. Encode it first with killcheck_encode.` }],
					details: { refused: "unknown_card", card_id: cardId },
				};
			}
			if (entry.status !== "confirmed") {
				return {
					content: [
						{
							type: "text",
							text: `REFUSED: card ${cardId} is ${entry.status}, not human-confirmed. Ask the user to run /card confirm (or edit/reject) and wait. You cannot confirm it yourself.`,
						},
					],
					details: { refused: "unconfirmed", card_id: cardId, status: entry.status },
				};
			}
			// Write the confirmed card to a temp file for the bridge.
			const { mkdtempSync, writeFileSync } = await import("node:fs");
			const { tmpdir } = await import("node:os");
			const { join } = await import("node:path");
			const dir = mkdtempSync(join(tmpdir(), "ramanujan-card-"));
			const cardFile = join(dir, `${cardId}.json`);
			writeFileSync(cardFile, JSON.stringify(entry.card));
			const res = await check(cardFile, {
				...bridgeOpts,
				budgetUsd: deps.budgetUsd,
				budgetSec: deps.budgetSec,
			});
			if (res.status === "error") throw new Error(`check failed: ${res.message}`);
			let text = renderResultCard(res);
			if (res.status === "survived") {
				text += "\nPanel review available: call panel_review or run /panel for multi-model opinions (advisory only).";
			}
			store.recordSummary(cardId, text);
			return { content: [{ type: "text", text }], details: res };
		},
	};

	return { store, definitions: [killcheck_encode, killcheck_run] };
}

/**
 * Harness-level gate for pi's on("tool_call") hook (defense in depth —
 * the in-tool refusal above is the primary enforcement).
 */
export function mathToolCallGate(store: PendingCardStore, event: { toolName: string; input: Record<string, unknown> }): { block?: boolean; reason?: string } | void {
	if (event.toolName !== "killcheck_run") return;
	const cardId = String(event.input["card_id"] ?? "");
	if (!store.isConfirmed(cardId)) {
		return { block: true, reason: `Card ${cardId || "(missing)"} is not human-confirmed. The human must run /card confirm first; the model cannot self-confirm.` };
	}
}

/** Ground-truth tap — same payload shape as CLI confirm. */
export function confirmVerdict(journalPath: string, runId: string, correct: boolean): void {
	appendJournalEvent(journalPath, "ground_truth_recorded", runId, {
		target: "f_0001",
		resolution: correct ? "confirmed" : "refuted",
		source: "human",
	});
}
