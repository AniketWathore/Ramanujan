/**
 * Harness gate + extension wiring (FakePI) + prompt/guard hooks.
 */

import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { engineCheck } from "@ramanujan/bridge";
import ramanujanExtension from "../src/extension.ts";
import type { PiCommandContext, PiExtensionAPI, PiToolCallEvent } from "../src/piTypes.ts";
import { appendMathPrompt, reframeBareVerdict } from "../src/systemPrompt.ts";
import { mathToolCallGate } from "../src/tools.ts";
import { PendingCardStore } from "../src/pendingCards.ts";
import { PRIME_CARD, engineBin, tmpJournal } from "./helper.ts";

interface Captured {
	tools: { name: string }[];
	commands: string[];
	hooks: string[];
}

function fakeCtx() {
	const notified: Array<{ message: string; type?: string }> = [];
	const ctx: PiCommandContext = { ui: { notify: (message, type) => void notified.push({ message, type }) } };
	return { ctx, notified };
}

function fakePI(): { pi: PiExtensionAPI; captured: Captured; handlers: Record<string, Array<(e: never) => unknown>> } {
	const captured: Captured = { tools: [], commands: [], hooks: [] };
	const handlers: Record<string, Array<(e: never) => unknown>> = {};
	const pi: PiExtensionAPI = {
		registerTool: (tool) => {
			captured.tools.push({ name: tool.name });
		},
		registerCommand: (name) => {
			captured.commands.push(name);
		},
		on: (event: "tool_call" | "before_agent_start" | "message_end", handler: (e: never) => unknown) => {
			captured.hooks.push(event);
			handlers[event] = [...(handlers[event] ?? []), handler];
		},
	};
	return { pi, captured, handlers };
}

describe("gate + extension", () => {
	it("registers five-stage pipeline tools and human slash commands (killcheck removed per user request)", () => {
		const { pi, captured } = fakePI();
		ramanujanExtension(pi, { journalPath: tmpJournal(), engineBin: engineBin() });
		expect(captured.tools).toHaveLength(9);
		expect(captured.tools.map((t) => t.name)).toEqual(expect.arrayContaining(["ramanujan_initialise", "ramanujan_literature", "checkpoint_respond", "preset_select", "worktree_spawn", "worktree_status", "claim_post", "ramanujan_consolidate", "ramanujan_review"]));
		expect(captured.tools.map((t) => t.name)).not.toContain("killcheck_encode");
		expect(captured.tools.map((t) => t.name)).not.toContain("killcheck_run");
		expect(captured.commands).toEqual(expect.arrayContaining(["checkpoint"]));
		expect(captured.hooks).toContain("before_agent_start");
		expect(captured.hooks).toContain("message_end");
		expect(captured.hooks).not.toContain("tool_call");
	});

	it("tool_call gate is now a no-op (killcheck removed)", () => {
		const store = new PendingCardStore();
		store.propose(PRIME_CARD as never);
		const ev: PiToolCallEvent = { type: "tool_call", toolCallId: "t1", toolName: "killcheck_run", input: { card_id: "c_0001" } };
		expect(mathToolCallGate(store, ev)).toBeUndefined();
		expect(mathToolCallGate(store, { type: "tool_call", toolCallId: "t2", toolName: "read", input: {} })).toBeUndefined();
	});

	it("extension no longer exposes tool_call gate", async () => {
		const { pi, handlers } = fakePI();
		ramanujanExtension(pi, { journalPath: tmpJournal(), engineBin: engineBin() });
		expect(handlers["tool_call"]).toBeUndefined();
	});

	it("before_agent_start appends the math prompt (chained)", () => {
		expect(appendMathPrompt("base prompt")).toContain("base prompt");
		expect(appendMathPrompt("base prompt")).toContain("You are Ramanujan");
		expect(appendMathPrompt("base prompt")).toContain("five-stage pipeline");
		// Idempotent
		const once = appendMathPrompt("base");
		expect(appendMathPrompt(once)).toBe(once);
	});

	it("message_end reframes bare verdicts, passes clean text through", () => {
		expect(reframeBareVerdict("Hello, let's explore.")).toBe("Hello, let's explore.");
		const reframed = reframeBareVerdict("I checked: REFUTED with n=40.");
		expect(reframed).toContain("REFUTED");
		expect(reframed).toContain("tool-result cards");
	});

	it("math prompt describes five-stage pipeline and checkpoint blocking", () => {
		const prompt = appendMathPrompt("base");
		expect(prompt).toContain("five-stage pipeline");
		expect(prompt).toContain("problem_spec.json");
		expect(prompt).toContain("CHECKPOINT PROTOCOL");
		expect(prompt).toContain("checkpoint_respond");
		expect(prompt).not.toContain("/checkpoint confirm");
	});

	it("math prompt keeps panel advisory phrasing", () => {
		const prompt = appendMathPrompt("base");
		expect(prompt).toContain("ADVISORY OPINIONS");
	});

	it("confirmVerdict writes CLI-shaped ground_truth_recorded (no /verdict slash needed)", async () => {
		const journal = tmpJournal();
		const dir = mkdtempSync(join(tmpdir(), "ramanujan-vt-"));
		const cardFile = join(dir, "c.json");
		writeFileSync(cardFile, JSON.stringify(PRIME_CARD));
		const chk = await engineCheck(cardFile, { engineBin: engineBin(), journal });
		if (chk.status !== "refuted") throw new Error("fixture check did not refute");
		const { confirmVerdict } = await import("../src/tools.ts");
		confirmVerdict(journal, chk.run_id, true);
		const lines = readFileSync(journal, "utf-8").trim().split("\n").map((l) => JSON.parse(l));
		const gt = lines.filter((e) => e.type === "ground_truth_recorded");
		expect(gt).toHaveLength(1);
		expect(gt[0].payload).toMatchObject({ target: "f_0001", resolution: "confirmed", source: "human" });
	});

	it("checkpoint store adopts engine ids and rehydrates from journal (no more 'no checkpoint cp_NNN')", async () => {
		const { CheckpointStore, findCheckpointInJournal } = await import("../src/checkpoints.ts");
		const journal = tmpJournal();
		const { appendJournalEvent } = await import("@ramanujan/config");
		appendJournalEvent(journal, "checkpoint_reached", "run_x", { checkpoint_id: "cp_004", stage: "computational", output_ref: "engine", revision: 0 });
		const store = new CheckpointStore<unknown>();
		store.rehydrateFromJournal(journal);
		// Next propose continues the shared sequence instead of re-minting cp_001.
		const cp = store.propose("reviewer", "out", "prompt", {});
		expect(cp.checkpointId).toBe("cp_005");
		// Unknown engine id is adopted from the journal instead of erroring.
		expect(findCheckpointInJournal(journal, "cp_004")?.stage).toBe("computational");
		const adopted = store.adopt("cp_004", "computational", "prompt", {});
		expect(adopted.checkpointId).toBe("cp_004");
		store.confirm("cp_004");
		expect(store.get("cp_004")?.status).toBe("confirmed");
	});

	it("PendingCardStore still tracks pending/reviewable (via /card)", async () => {
		const { default: ext } = await import("../src/extension.ts");
		const pi2: PiExtensionAPI = { registerTool: () => {}, registerCommand: () => {}, on: () => {} };
		ext(pi2, { journalPath: tmpJournal(), engineBin: engineBin() });
		// Extension registers /card and /checkpoint; store itself still works
		const store = new PendingCardStore();
		store.propose(PRIME_CARD as never);
		expect(store.pending()).toHaveLength(1);
		expect(store.reviewable()?.cardId).toBe("c_0001");
	});

	it("reviewable(): explicit id, then pending, then last confirmed — never empty-after-confirm", () => {
		const store = new PendingCardStore();
		expect(store.reviewable()).toBeUndefined();
		store.propose(PRIME_CARD as never);
		expect(store.reviewable()?.cardId).toBe("c_0001");
		// After confirm there is nothing pending, but the card stays reviewable.
		store.confirm("c_0001");
		expect(store.pending()).toHaveLength(0);
		expect(store.reviewable()?.cardId).toBe("c_0001");
		expect(store.reviewable("c_0001")?.cardId).toBe("c_0001");
		expect(store.reviewable("c_9999")).toBeUndefined();
	});
});
