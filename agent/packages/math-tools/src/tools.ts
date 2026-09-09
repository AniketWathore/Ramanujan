/**
 * Math tools (pi-native shape): killcheck_run only (killcheck_encode removed per Option 1).
 * panel_review lands in A6 with the panel it fronts.
 *
 * Bridge functions are injectable for tests; defaults call the real engine.
 */

import { type engineReplay } from "@ramanujan/bridge";
import { engineCheck } from "@ramanujan/bridge";
import { appendJournalEvent } from "@ramanujan/config";
import { PendingCardStore } from "./pendingCards.ts";
import type { PiToolDefinition } from "./piTypes.ts";

export interface MathToolDeps {
	bridge?: {
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

export function createMathTools(deps: MathToolDeps = {}): MathTools {
	const store = new PendingCardStore();
	// killcheck_encode/run removed per user request (Option 1: pipeline via engine CLI, no direct ClaimCard encode). Keep store for panel compatibility.
	return { store, definitions: [] };
}

/**
 * Harness-level gate for pi's on("tool_call") hook (defense in depth —
 * killcheck removed, gate is now a no-op but kept for API compatibility).
 */
export function mathToolCallGate(_store: PendingCardStore, _event: { toolName: string; input: Record<string, unknown> }): { block?: boolean; reason?: string } | void {
	return;
}

/** Ground-truth tap — same payload shape as CLI confirm. */
export function confirmVerdict(journalPath: string, runId: string, correct: boolean): void {
	appendJournalEvent(journalPath, "ground_truth_recorded", runId, {
		target: "f_0001",
		resolution: correct ? "confirmed" : "refuted",
		source: "human",
	});
}
