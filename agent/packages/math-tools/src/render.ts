/**
 * Result rendering — TS renders, never computes.
 * Verdict strings below are COPIES of engine output for display only.
 */

import type { CheckResult } from "@ramanujan/bridge";
import { engineReplay } from "@ramanujan/bridge";

export function renderResultCard(res: CheckResult): string {
	if (res.status === "error") return `Check failed: ${res.message}`;
	if (res.status === "budget_exceeded") {
		return `Budget exceeded — checks incomplete (run ${res.run_id}). No verdict. Raise --budget-usd/--budget-sec and re-run after human confirmation.`;
	}
	const lines: string[] = [];
	if (res.status === "refuted") {
		lines.push(`Verdict: REFUTED (run ${res.run_id})`);
		lines.push(`Counterexample: ${JSON.stringify(res.counterexample)}`);
		lines.push(`Double-verified: ${res.double_verified ? "YES — independent verifier agreed" : "NO"}`);
	} else {
		lines.push(`Verdict: SURVIVED (run ${res.run_id})`);
		lines.push("The claim survived all deterministic checks. This is not a proof — only that no counterexample was found.");
	}
	lines.push(`Budget: ${JSON.stringify(res.budget)} · ${res.elapsed_sec.toFixed(2)}s`);
	lines.push(`Ground truth: run /verdict ${res.run_id} correct|incorrect in the TUI (journals your tap for the reliability table).`);
	return lines.join("\n");
}

export interface RunSummary {
	run_id: string;
	statement: string | null;
	verdict: string | null;
	ground_truth: unknown;
}

/** Run history from engine replay (same journal both runtimes share). */
export async function listRuns(engineBin: string | undefined, journalPath: string): Promise<RunSummary[]> {
	const res = await engineReplay(journalPath, engineBin ? { engineBin } : {});
	if (res.status !== "ok") throw new Error(`replay failed: ${res.message}`);
	const runs = new Map<string, RunSummary & { ts: string }>();
	for (const e of res.events) {
		let entry = runs.get(e.run_id);
		if (!entry) {
			entry = { run_id: e.run_id, statement: null, verdict: null, ground_truth: null, ts: e.ts };
			runs.set(e.run_id, entry);
		}
		const payload = e.payload as Record<string, unknown>;
		if (e.type === "run_started" && typeof payload["statement"] === "string") {
			entry.statement = payload["statement"];
			entry.ts = e.ts;
		}
		if (e.type === "claim_refuted") entry.verdict = "REFUTED";
		if (e.type === "claim_survived") entry.verdict = "SURVIVED";
		if (e.type === "run_completed" && typeof payload["verdict"] === "string") entry.verdict = payload["verdict"];
		if (e.type === "ground_truth_recorded") entry.ground_truth = payload;
	}
	return [...runs.values()]
		.sort((a, b) => (a.ts < b.ts ? 1 : -1))
		.map(({ run_id, statement, verdict, ground_truth }) => ({ run_id, statement, verdict, ground_truth }));
}

export function renderRunList(runs: RunSummary[]): string {
	if (runs.length === 0) return "No runs yet.";
	return runs
		.slice(0, 30)
		.map((r) => `- [${r.verdict ?? "?"}] ${r.statement ?? "(no statement)"} (${r.run_id})`)
		.join("\n");
}
