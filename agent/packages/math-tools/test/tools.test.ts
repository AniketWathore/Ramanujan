/**
 * Math tools: mocked LLM (fake encode) + REAL bridge check on planted cards.
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { createMathTools } from "../src/index.ts";
import { PRIME_CARD, PRIME_STATEMENT, engineBin, tmpJournal } from "./helper.ts";

function fakeEncodePrime() {
	return async () => ({
		status: "card",
		card: PRIME_CARD,
		run_id: "enc_test",
		provider: "mock",
		model_id: "mock/encoder",
	});
}

describe("math tools", () => {
	it("happy path: encode → human confirm → refuted n=40 double-verified", async () => {
		const journal = tmpJournal();
		const { store, definitions } = createMathTools({
			bridge: { encode: fakeEncodePrime() as never },
			journalPath: journal,
			engineBin: engineBin(),
		});
		const encode = definitions.find((d) => d.name === "killcheck_encode")!;
		const run = definitions.find((d) => d.name === "killcheck_run")!;
		const encRes = await encode.execute("t1", { statement: PRIME_STATEMENT });
		expect(encRes.content[0].text).toContain("c_0001");
		expect(store.pending()).toHaveLength(1);

		// Human confirms (simulates /card confirm in the TUI)
		store.confirm("c_0001");
		const runRes = await run.execute("t2", { card_id: "c_0001" });
		const text = runRes.content[0].text;
		expect(text).toContain("REFUTED");
		expect(text).toContain("40");
		expect(text).toContain("Double-verified: YES");
		expect(text).toContain("/verdict run_");
		expect((runRes.details as { double_verified?: boolean }).double_verified).toBe(true);

		// Journal order: run_started … claim_refuted
		const events = readFileSync(journal, "utf-8").trim().split("\n").map((l) => JSON.parse(l));
		const types = events.map((e) => e.type);
		expect(types[0]).toBe("run_started");
		expect(types).toContain("claim_refuted");
		expect(types.indexOf("run_started")).toBeLessThan(types.indexOf("claim_refuted"));
	});

	it("killcheck_run guidelines: run after user-confirmed, never re-ask", async () => {
		const { definitions } = createMathTools({ journalPath: tmpJournal(), engineBin: engineBin() });
		const run = definitions.find((d) => d.name === "killcheck_run")!;
		const guidelines = (run.promptGuidelines ?? []).join("\n");
		expect(guidelines).toContain("already confirmed");
	});

	it("not_encodable returns an honest message and proposes nothing", async () => {
		const { store, definitions } = createMathTools({
			bridge: {
				encode: (async () => ({ status: "not_encodable", reason: "open-form sum", run_id: "e", provider: "m", model_id: "m" })) as never,
			},
			journalPath: tmpJournal(),
			engineBin: engineBin(),
		});
		const encode = definitions.find((d) => d.name === "killcheck_encode")!;
		const res = await encode.execute("t1", { statement: "sums…" });
		expect(res.content[0].text).toContain("NOT_ENCODABLE");
		expect(store.pending()).toHaveLength(0);
	});

	it("encoder_error never claims the DSL cannot express it", async () => {
		const { store, definitions } = createMathTools({
			bridge: {
				encode: (async () => ({
					status: "encoder_error",
					reason: "invalid claim_type 'prime' after 3 attempts",
					run_id: "e",
					provider: "m",
					model_id: "m",
				})) as never,
			},
			journalPath: tmpJournal(),
			engineBin: engineBin(),
		});
		const encode = definitions.find((d) => d.name === "killcheck_encode")!;
		const res = await encode.execute("t1", { statement: "prime…" });
		expect(res.content[0].text).toContain("ENCODER ERROR");
		expect(res.content[0].text).toContain("stronger model");
		expect(res.content[0].text).not.toContain("outside the current claim-card DSL");
		expect(store.pending()).toHaveLength(0);
	});

	it("edited card runs the edited (confirmed) card", async () => {
		const journal = tmpJournal();
		const { store, definitions } = createMathTools({
			bridge: { encode: fakeEncodePrime() as never },
			journalPath: journal,
			engineBin: engineBin(),
		});
		const encode = definitions.find((d) => d.name === "killcheck_encode")!;
		const run = definitions.find((d) => d.name === "killcheck_run")!;
		await encode.execute("t1", { statement: PRIME_STATEMENT });
		// Human edits lo 0 → 5 (n=40 still in domain) and confirms
		const edited = JSON.parse(JSON.stringify(PRIME_CARD));
		edited.quantifiers[0].domain.lo = 5;
		store.edit(edited);
		const res = await run.execute("t2", { card_id: "c_0001" });
		expect(res.content[0].text).toContain("REFUTED");
	});

	it("rejected card is refused, never run", async () => {
		const { store, definitions } = createMathTools({
			bridge: { encode: fakeEncodePrime() as never },
			journalPath: tmpJournal(),
			engineBin: engineBin(),
		});
		const encode = definitions.find((d) => d.name === "killcheck_encode")!;
		const run = definitions.find((d) => d.name === "killcheck_run")!;
		await encode.execute("t1", { statement: PRIME_STATEMENT });
		store.reject("c_0001");
		const res = await run.execute("t2", { card_id: "c_0001" });
		expect(res.content[0].text).toContain("REFUSED");
		expect(res.content[0].text).toContain("rejected");
	});

	it("unconfirmed card is refused — the model cannot self-confirm", async () => {
		const { store, definitions } = createMathTools({
			bridge: { encode: fakeEncodePrime() as never },
			journalPath: tmpJournal(),
			engineBin: engineBin(),
		});
		const encode = definitions.find((d) => d.name === "killcheck_encode")!;
		const run = definitions.find((d) => d.name === "killcheck_run")!;
		await encode.execute("t1", { statement: PRIME_STATEMENT });
		expect(store.isConfirmed("c_0001")).toBe(false);
		const res = await run.execute("t2", { card_id: "c_0001" });
		expect(res.content[0].text).toContain("REFUSED");
		expect(res.content[0].text).toContain("/card confirm");
		// No confirm tool is registered for the model
		expect(definitions.map((d) => d.name)).toEqual(["killcheck_encode", "killcheck_run"]);
	});

	it("unknown card id is refused", async () => {
		const { definitions } = createMathTools({ journalPath: tmpJournal(), engineBin: engineBin() });
		const run = definitions.find((d) => d.name === "killcheck_run")!;
		const res = await run.execute("t1", { card_id: "c_9999" });
		expect(res.content[0].text).toContain("REFUSED");
	});

	it("budget breach returns an honest event, never a verdict", async () => {
		const journal = tmpJournal();
		const { store, definitions } = createMathTools({
			bridge: { encode: fakeEncodePrime() as never },
			journalPath: journal,
			engineBin: engineBin(),
			budgetSec: 0.0001,
		});
		const encode = definitions.find((d) => d.name === "killcheck_encode")!;
		const run = definitions.find((d) => d.name === "killcheck_run")!;
		await encode.execute("t1", { statement: PRIME_STATEMENT });
		store.confirm("c_0001");
		const res = await run.execute("t2", { card_id: "c_0001" });
		expect(res.content[0].text).toContain("Budget exceeded");
		expect(res.content[0].text).not.toContain("REFUTED");
		expect(res.content[0].text).not.toContain("SURVIVED");
	});

	it("encoder bridge failure returns ENCODER ERROR text, never throws no-stdout", async () => {
		const { store, definitions } = createMathTools({
			bridge: {
				encode: (async () => {
					throw new Error("engine produced no stdout (exit null): spawn ramanujan-engine ENOENT");
				}) as never,
			},
			journalPath: tmpJournal(),
			engineBin: engineBin(),
		});
		const encode = definitions.find((d) => d.name === "killcheck_encode")!;
		const res = await encode.execute("t1", { statement: "x" });
		expect(res.content[0].text).toContain("ENCODER ERROR");
		expect(res.content[0].text).toContain("ENOENT");
		expect(res.content[0].text).not.toContain("outside the current claim-card DSL");
		expect(store.pending()).toHaveLength(0);
	});

	it("engine error status maps to ENCODER ERROR text (never a throw)", async () => {
		const { definitions } = createMathTools({
			bridge: {
				encode: (async () => ({ status: "error", message: "role encoder not configured", run_id: "e" })) as never,
			},
			journalPath: tmpJournal(),
			engineBin: engineBin(),
		});
		const encode = definitions.find((d) => d.name === "killcheck_encode")!;
		const res = await encode.execute("t1", { statement: "x" });
		expect(res.content[0].text).toContain("ENCODER ERROR");
		expect(res.content[0].text).toContain("not configured");
	});
});
