/**
 * Minimal journal writer for TS-emitted events.
 * Envelope MUST pass `ramanujan-engine replay --json` validation:
 * {ts, run_id, type, payload}, type in the frozen 14.
 */

import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

export const JOURNAL_EVENT_TYPES = [
	"run_started",
	"claim_registered",
	"llm_call",
	"encoding_attempted",
	"encoding_accepted",
	"encoding_failed",
	"check_executed",
	"counterexample_found",
	"counterexample_reverified",
	"claim_refuted",
	"claim_survived",
	"budget_event",
	"run_completed",
	"ground_truth_recorded",
	// v0.4 A6 (schema ADR, append-only — mirrors ramanujan/schemas.py)
	"panel_position",
	"panel_advisory",
	// v2 Phases 1-7 (append-only)
	"problem_spec_created",
	"checkpoint_reached",
	"checkpoint_resolved",
	"literature_entry_added",
	"worktree_spawned",
	"worktree_status_changed",
	"claim_posted",
	"claim_verification_routed",
	"panel_verdict_issued",
	"stall_detected",
	"question_posted",
	"question_answered_or_defaulted",
	"consolidation_completed",
] as const;

export type JournalEventType = (typeof JOURNAL_EVENT_TYPES)[number];

export interface LlmCallPayload {
	model_id: string;
	provider: string;
	family?: string;
	input_tokens: number;
	output_tokens: number;
	cost: number;
	latency_ms: number;
	retries?: number;
	role?: string;
}

export function appendJournalEvent(
	journalPath: string,
	type: JournalEventType,
	runId: string,
	payload: Record<string, unknown>,
): void {
	if (!(JOURNAL_EVENT_TYPES as readonly string[]).includes(type)) throw new Error(`unknown journal event type: ${type}`);
	if (type === "llm_call" && typeof (payload as unknown as LlmCallPayload).model_id !== "string") {
		throw new Error("llm_call payload requires model_id");
	}
	if (type === "panel_position") {
		const p = payload as unknown as Record<string, unknown>;
		if (!["support", "doubt", "object"].includes(String(p["position"]))) throw new Error("panel_position requires position support|doubt|object");
		for (const k of ["panel_run_id", "model_id", "provider"]) {
			if (typeof p[k] !== "string") throw new Error(`panel_position requires ${k}`);
		}
		if (p["round"] !== 1 && p["round"] !== 2) throw new Error("panel_position round must be 1|2");
	}
	if (type === "panel_advisory") {
		const p = payload as unknown as Record<string, unknown>;
		if (typeof p["panel_run_id"] !== "string" || typeof p["advisory"] !== "string") {
			throw new Error("panel_advisory requires panel_run_id + advisory");
		}
	}
	mkdirSync(dirname(journalPath), { recursive: true });
	const event = { ts: new Date().toISOString(), run_id: runId, type, payload };
	appendFileSync(journalPath, JSON.stringify(event) + "\n", "utf-8");
}

export function appendLlmCall(
	journalPath: string,
	runId: string,
	payload: LlmCallPayload & { role?: string },
): void {
	// Key material must never reach the journal — hard guard.
	const dumped = JSON.stringify(payload);
	if (/nvapi-|sk-ant-|sk-or-|sk-[A-Za-z0-9]{8,}/.test(dumped)) {
		throw new Error("refusing to journal possible key material");
	}
	appendJournalEvent(journalPath, "llm_call", runId, payload as unknown as Record<string, unknown>);
}

export function journalExists(journalPath: string): boolean {
	return existsSync(journalPath);
}
