/**
 * Math tools: killcheck removed per user request (Option 1: pipeline via engine CLI).
 * createMathTools now returns empty definitions; store still works for panel compatibility.
 */

import { describe, expect, it } from "vitest";
import { createMathTools } from "../src/index.ts";
import { tmpJournal, engineBin } from "./helper.ts";
import { mathToolCallGate } from "../src/tools.ts";
import { PendingCardStore } from "../src/pendingCards.ts";
import { PRIME_CARD } from "./helper.ts";

describe("math tools (killcheck removed)", () => {
	it("createMathTools returns no killcheck tools", () => {
		const { definitions } = createMathTools({ journalPath: tmpJournal(), engineBin: engineBin() });
		expect(definitions).toHaveLength(0);
		expect(definitions.map((d) => d.name)).not.toContain("killcheck_encode");
		expect(definitions.map((d) => d.name)).not.toContain("killcheck_run");
	});

	it("mathToolCallGate is now a no-op", () => {
		const store = new PendingCardStore();
		store.propose(PRIME_CARD as never);
		expect(mathToolCallGate(store, { type: "tool_call", toolCallId: "t1", toolName: "killcheck_run", input: { card_id: "c_0001" } })).toBeUndefined();
		expect(mathToolCallGate(store, { type: "tool_call", toolCallId: "t2", toolName: "read", input: {} })).toBeUndefined();
	});

	it("PendingCardStore still tracks pending/reviewable (for panel compatibility)", () => {
		const { store } = createMathTools({ journalPath: tmpJournal(), engineBin: engineBin() });
		store.propose(PRIME_CARD as never);
		expect(store.pending()).toHaveLength(1);
		expect(store.reviewable()?.cardId).toBe("c_0001");
	});
});
