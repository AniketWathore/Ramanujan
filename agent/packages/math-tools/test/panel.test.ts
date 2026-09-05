/**
 * Panel: sealed debate, candidate funnel, advisory-only.
 * Mocked panelist LLM + REAL engineVerify (deterministic decider).
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { engineReplay } from "@ramanujan/bridge";
import { renderPanelCard, runPanel, type PanelistSpec } from "../src/index.ts";
import { PRIME_CARD, engineBin, tmpJournal } from "./helper.ts";

const A: PanelistSpec = { provider: "nvidia", modelId: "nvidia/model-a", family: "nvidia", key: "fake", baseUrl: "https://example.com/v1" };
const B: PanelistSpec = { provider: "openrouter", modelId: "openrouter/model-b", family: "openrouter", key: "fake", baseUrl: "https://example.com/v1" };

function scripted(replies: Record<string, string[]>) {
	const seen: Array<{ modelId: string; messages: Array<{ role: string; content: string }> }> = [];
	const calls: Record<string, number> = {};
	const fn = async (spec: PanelistSpec, messages: Array<{ role: "system" | "user"; content: string }>) => {
		seen.push({ modelId: spec.modelId, messages });
		const n = calls[spec.modelId] ?? 0;
		calls[spec.modelId] = n + 1;
		const text = replies[spec.modelId]?.[n] ?? replies[spec.modelId]?.[0] ?? "";
		return { text, inputTokens: 10, outputTokens: 10 };
	};
	return { fn, seen };
}

const R1_A = JSON.stringify({ position: "object", confidence: 0.8, objection: "fails at n=40", counterexample_candidate: { n: 40 }, reasoning: "Euler polynomial" });
const R1_B = JSON.stringify({ position: "doubt", confidence: 0.5, objection: "bound looks tight", reasoning: "unsure" });
const R2_A = JSON.stringify({ position: "object", confidence: 0.9, objection: "confirmed at n=40", counterexample_candidate: { n: 40 }, reasoning: "still object" });
const R2_B = JSON.stringify({ position: "support", confidence: 0.6, reasoning: "convinced by A" });

describe("panel", () => {
	it("seals round 1: panelist B never sees A's output", async () => {
		const journal = tmpJournal();
		const { fn, seen } = scripted({ [A.modelId]: [R1_A, R1_A], [B.modelId]: [R1_B, R1_B] });
		const res = await runPanel(PRIME_CARD as never, "no prior killcheck", [A, B], { journalPath: journal, engineBin: engineBin(), callPanelist: fn });
		expect(res.round1).toHaveLength(2);
		const promptB_R1 = seen.find((s) => s.modelId === B.modelId)!.messages.map((m) => m.content).join("\n");
		// A's unique marker must not appear in B's round-1 prompt
		expect(promptB_R1).not.toContain("Euler polynomial");
		expect(promptB_R1).not.toContain("fails at n=40");
		expect(res.tally).toEqual({ support: 0, doubt: 1, object: 1 });
	});

	it("funnels candidates through the engine and never writes claim_refuted", async () => {
		const journal = tmpJournal();
		const { fn } = scripted({ [A.modelId]: [R1_A, R2_A], [B.modelId]: [R1_B, R2_B] });
		const res = await runPanel(PRIME_CARD as never, "killcheck: SURVIVED (stale summary)", [A, B], {
			journalPath: journal,
			engineBin: engineBin(),
			callPanelist: fn,
		});
		// Engine verified n=40 even though the summary was stale
		expect(res.engineVerifiedCandidates).toEqual([{ modelId: A.modelId, candidate: { n: 40 } }]);
		expect(res.advisory).toContain("Engine-verified candidates");
		expect(res.advisory).toContain("panel:");
		// Advisory phrasing only — no verdict claim
		expect(res.advisory).not.toContain("REFUTED");
		// Journal conformance via Python replay: positions + advisory + llm_calls, zero claim_refuted
		const replay = await engineReplay(journal, { engineBin: engineBin() });
		expect(replay.status).toBe("ok");
		if (replay.status !== "ok") return;
		const types = replay.events.map((e) => e.type);
		expect(types).toContain("panel_position");
		expect(types).toContain("panel_advisory");
		expect(types).not.toContain("claim_refuted");
		const llm = replay.events.filter((e) => e.type === "llm_call");
		expect(llm.length).toBeGreaterThanOrEqual(4); // 2 panelists × 2 rounds
		for (const e of llm) {
			expect((e.payload as { provider?: string }).provider).toBeDefined();
			expect((e.payload as { model_id?: string }).model_id).toBeDefined();
		}
		// Round-2 revision recorded
		const r2 = res.round2.find((r) => r.modelId === B.modelId)!;
		expect(r2.revised).toBe(true);
		expect(r2.position).toBe("support");
	});

	it("warns when all panelists share one family", async () => {
		const journal = tmpJournal();
		const A2 = { ...A, modelId: "nvidia/model-a2" };
		const { fn } = scripted({ [A.modelId]: [R1_B, R1_B], [A2.modelId]: [R1_B, R1_B] });
		const res = await runPanel(PRIME_CARD as never, "summary", [A, A2], { journalPath: journal, engineBin: engineBin(), callPanelist: fn });
		expect(res.sameFamilyWarning).toContain("nvidia");
		const card = renderPanelCard(res);
		expect(card).toContain("ADVISORY");
		expect(card).not.toContain("REFUTED");
	});

	it("requires ≥2 panelists", async () => {
		await expect(runPanel(PRIME_CARD as never, "s", [A], { journalPath: tmpJournal(), engineBin: engineBin() })).rejects.toThrow(/≥2/);
	});

	it("malformed panelist reply becomes doubt-0, never a crash", async () => {
		const journal = tmpJournal();
		const { fn } = scripted({ [A.modelId]: ["not json at all", "not json"], [B.modelId]: [R1_B, R1_B] });
		const res = await runPanel(PRIME_CARD as never, "s", [A, B], { journalPath: journal, engineBin: engineBin(), callPanelist: fn });
		const a = res.round1.find((r) => r.modelId === A.modelId)!;
		expect(a.position).toBe("doubt");
		expect(a.confidence).toBe(0);
		// Journal still validates
		const replay = await engineReplay(journal, { engineBin: engineBin() });
		expect(replay.status).toBe("ok");
	});

	it("unverified candidates are marked not-verified, advisory stays opinion", async () => {
		const journal = tmpJournal();
		const bad = JSON.stringify({ position: "object", confidence: 0.7, counterexample_candidate: { n: 0 }, reasoning: "wrong guess" });
		const { fn } = scripted({ [A.modelId]: [bad, bad], [B.modelId]: [R1_B, R1_B] });
		const res = await runPanel(PRIME_CARD as never, "s", [A, B], { journalPath: journal, engineBin: engineBin(), callPanelist: fn });
		expect(res.engineVerifiedCandidates).toEqual([]);
		const a = res.round1.find((r) => r.modelId === A.modelId)!;
		expect(a.candidateVerified).toBe(false);
		expect(res.advisory).toContain("No candidate verified");
	});
});
