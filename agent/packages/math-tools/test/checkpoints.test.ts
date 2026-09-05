/**
 * Generic CheckpointStore: one confirm/revise contract for all five stages.
 */

import { describe, expect, it } from "vitest";
import { CHECKPOINT_OPTIONS, CheckpointStore } from "../src/checkpoints.ts";

describe("CheckpointStore", () => {
	it("proposes pending with confirm/revise options only (never stop)", () => {
		const store = new CheckpointStore<string>();
		const rec = store.propose("initialiser", "run run_x problem_spec (inline)", "Confirm?", "spec-body");
		expect(rec.checkpointId).toBe("cp_001");
		expect(rec.status).toBe("pending");
		expect(rec.options).toEqual(["confirm", "revise"]);
		expect(CHECKPOINT_OPTIONS).toEqual(["confirm", "revise"]);
		expect(store.pending()).toHaveLength(1);
	});

	it("confirm resolves; double-confirm and unknown ids throw", () => {
		const store = new CheckpointStore<string>();
		store.propose("s", "o", "p", "c");
		store.confirm("cp_001");
		expect(store.get("cp_001")?.status).toBe("confirmed");
		expect(store.pending()).toHaveLength(0);
		expect(() => store.confirm("cp_001")).toThrow(/already confirmed/);
		expect(() => store.confirm("cp_999")).toThrow(/no checkpoint/);
		expect(() => store.revise("cp_001", "too late")).toThrow(/already confirmed/);
	});

	it("revise records feedback, bumps revision, and re-presents pending", () => {
		const store = new CheckpointStore<{ n: number }>();
		const rec = store.propose("literature", "literature/summary.md", "Confirm?", { n: 1 });
		store.revise("cp_001", "add the 2024 survey");
		expect(rec.status).toBe("pending");
		expect(rec.revision).toBe(1);
		expect(rec.feedback).toEqual(["add the 2024 survey"]);
		store.revise("cp_001", "still missing methods");
		expect(rec.revision).toBe(2);
		store.confirm("cp_001");
		expect(rec.status).toBe("confirmed");
		expect(rec.feedback).toHaveLength(2);
	});

	it("ids increment across stages", () => {
		const store = new CheckpointStore<null>();
		const a = store.propose("a", "oa", "pa", null);
		const b = store.propose("b", "ob", "pb", null);
		expect(a.checkpointId).toBe("cp_001");
		expect(b.checkpointId).toBe("cp_002");
		expect(store.get("cp_404")).toBeUndefined();
	});
});
