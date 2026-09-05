/**
 * Bridge interop gate (v0.4 A3). Must pass before A4.
 * 1. TS writes a conforming llm_call event to a temp journal;
 *    ramanujan-engine replay --json validates it clean.
 * 2. encode→check round-trip on the planted offline prime card →
 *    refuted, double_verified true.
 *
 * No API keys. Encode uses RAMANUJAN_MOCK_ENCODER=1 (test-only planted mock).
 */

import { appendFileSync, chmodSync, existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { defaultEncodeTimeoutMs, engineCheck, engineEncode, engineInitialise, engineLiterature, engineReplay, engineVerify, resolveEngineBin } from "../src/index.ts";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..", "..", "..");

function engineBin(): string {
	const override = process.env["RAMANUJAN_ENGINE_BIN"];
	if (override) return override;
	const venvBin = join(repoRoot, ".venv", "bin", "ramanujan-engine");
	if (existsSync(venvBin)) return venvBin;
	return "ramanujan-engine";
}

function tmpJournal(): string {
	const dir = mkdtempSync(join(tmpdir(), "ramanujan-bridge-"));
	return join(dir, "journal.jsonl");
}

const PRIME = "For every integer n >= 0, n^2 + n + 41 is prime.";

describe("encode never fails silent (v0.4.3)", () => {
	function fakeEngine(name: string, body: string): string {
		const dir = mkdtempSync(join(tmpdir(), "ramanujan-fakeeng-"));
		const bin = join(dir, name);
		writeFileSync(bin, `#!/bin/sh\n${body}\n`);
		chmodSync(bin, 0o755);
		return bin;
	}

	it("non-zero exit with no JSON returns encoder_error, never throws", async () => {
		const bin = fakeEngine("fail.sh", 'echo "boom" >&2\nexit 1');
		const res = await engineEncode("x", { engineBin: bin, journal: tmpJournal(), timeoutMs: 15000 });
		expect(res.status).toBe("encoder_error");
		if (res.status !== "encoder_error") return;
		expect(res.reason).toContain("no usable JSON");
	});

	it("invalid JSON stdout returns encoder_error, never throws", async () => {
		const bin = fakeEngine("badjson.sh", 'echo "this is not json"');
		const res = await engineEncode("x", { engineBin: bin, journal: tmpJournal(), timeoutMs: 15000 });
		expect(res.status).toBe("encoder_error");
	});

	it("missing binary (ENOENT) returns encoder_error with the spawn reason", async () => {
		const res = await engineEncode("x", { engineBin: "/nonexistent/ramanujan-engine", journal: tmpJournal(), timeoutMs: 15000 });
		expect(res.status).toBe("encoder_error");
		if (res.status !== "encoder_error") return;
		expect(res.reason).toMatch(/ENOENT|spawn|no such file/i);
		expect(res.reason).not.toContain("outside the current claim-card DSL");
	});

	it("engine encoder_error JSON (e.g. NVIDIA 404) passes through with its reason", async () => {
		const payload = JSON.stringify({
			status: "encoder_error",
			reason: "LLM call failed after 3 retries: OpenAI-compatible API error 404: Function 'abc' Not found for account 'x'",
			run_id: "enc_404",
			provider: "nvidia",
			model_id: "nvidia/llama-3.1-nemotron-70b-instruct",
		});
		const bin = fakeEngine("e404.sh", `echo '${payload}'`);
		const res = await engineEncode("x", { engineBin: bin, journal: tmpJournal(), timeoutMs: 15000 });
		expect(res.status).toBe("encoder_error");
		if (res.status !== "encoder_error") return;
		expect(res.reason).toContain("404");
		expect(res.run_id).toBe("enc_404");
	});

	it("engine error status (spec/key failure) maps to encoder_error, not a throw", async () => {
		const payload = JSON.stringify({ status: "error", message: "spec resolution failed: role 'encoder' not configured", run_id: "enc_nokey" });
		const bin = fakeEngine("err.sh", `echo '${payload}'\nexit 1`);
		const res = await engineEncode("x", { engineBin: bin, journal: tmpJournal(), timeoutMs: 15000 });
		expect(res.status).toBe("encoder_error");
		if (res.status !== "encoder_error") return;
		expect(res.reason).toContain("not configured");
	});
});

describe("encode timeout", () => {
	it("defaults to 180s and honors RAMANUJAN_ENCODE_TIMEOUT_MS", () => {
		const prev = process.env["RAMANUJAN_ENCODE_TIMEOUT_MS"];
		delete process.env["RAMANUJAN_ENCODE_TIMEOUT_MS"];
		expect(defaultEncodeTimeoutMs()).toBe(180000);
		process.env["RAMANUJAN_ENCODE_TIMEOUT_MS"] = "45000";
		expect(defaultEncodeTimeoutMs()).toBe(45000);
		process.env["RAMANUJAN_ENCODE_TIMEOUT_MS"] = "bogus";
		expect(defaultEncodeTimeoutMs()).toBe(180000);
		if (prev === undefined) delete process.env["RAMANUJAN_ENCODE_TIMEOUT_MS"];
		else process.env["RAMANUJAN_ENCODE_TIMEOUT_MS"] = prev;
	});
});

describe("interop gate", () => {
	it("validates a TS-written llm_call via engine replay", async () => {
		const journal = tmpJournal();
		// Write the event with plain JSON (same envelope the Python writer uses).
		const event = {
			ts: new Date().toISOString(),
			run_id: "run_ts_interop",
			type: "llm_call",
			payload: {
				model_id: "mock/ts-interop-model",
				provider: "mock",
				input_tokens: 10,
				output_tokens: 5,
				cost: 0,
				latency_ms: 1,
				retries: 0,
			},
		};
		appendFileSync(journal, JSON.stringify(event) + "\n");
		const res = await engineReplay(journal, { engineBin: engineBin(), timeoutMs: 30000 });
		expect(res.status).toBe("ok");
		if (res.status === "ok") {
			expect(res.events).toHaveLength(1);
			expect(res.events[0].type).toBe("llm_call");
		}
	});

	it("round-trips encode→check on the planted prime card", async () => {
		const journal = tmpJournal();
		const bin = engineBin();
		const env = { RAMANUJAN_MOCK_ENCODER: "1" };
		const enc = await engineEncode(PRIME, { engineBin: bin, journal, env, timeoutMs: 60000 });
		expect(enc.status).toBe("card");
		if (enc.status !== "card") return;
		expect(enc.card.conclusion.expr).toContain("is_prime");

		const dir = dirname(journal);
		const cardFile = join(dir, "prime_card.json");
		writeFileSync(cardFile, JSON.stringify(enc.card));
		const chk = await engineCheck(cardFile, { engineBin: bin, journal, env, timeoutMs: 120000 });
		expect(chk.status).toBe("refuted");
		if (chk.status !== "refuted") return;
		expect(chk.counterexample).toEqual({ n: 40 });
		expect(chk.double_verified).toBe(true);

		// Candidate funnel: verify the found witness + reject a non-witness.
		const ok = await engineVerify(cardFile, { n: 40 }, { engineBin: bin, timeoutMs: 30000 });
		expect(ok.status).toBe("counterexample_verified");
		const no = await engineVerify(cardFile, { n: 0 }, { engineBin: bin, timeoutMs: 30000 });
		expect(no.status).toBe("not_counterexample");
	});

	it("initialise returns the spec + numeric-only kill-check on the planted prime card", async () => {
		const journal = tmpJournal();
		const bin = engineBin();
		const env = { RAMANUJAN_MOCK_ENCODER: "1" };
		const res = await engineInitialise(PRIME, { engineBin: bin, journal, env, timeoutMs: 120000 });
		expect(res.status).toBe("spec");
		if (res.status !== "spec") return;
		expect(res.spec.statement_formal).toBeNull();
		expect(res.spec.kill_check_config.run_smt).toBe(true);
		expect(res.numeric_killcheck.status).toBe("refuted");
		expect(res.numeric_killcheck.counterexample).toEqual({ n: 40 });
		expect(res.numeric_killcheck.double_verified).toBe(true);
		// The §4.3 trim: SMT recorded, never executed.
		expect(res.numeric_killcheck.smt_executed).toBe(false);
		expect(res.checkpoint_id).toMatch(/^cp_\d+$/);

		// The journal carries the new Phase 1 events and replays clean.
		const rep = await engineReplay(journal, { engineBin: bin, timeoutMs: 30000 });
		expect(rep.status).toBe("ok");
		if (rep.status === "ok") {
			const types = rep.events.map((e) => e.type);
			expect(types).toContain("problem_spec_created");
			expect(types).toContain("checkpoint_reached");
		}
	});

	it("initialise never throws on transport failure", async () => {
		const res = await engineInitialise("x", { engineBin: "/nonexistent/ramanujan-engine", journal: tmpJournal(), timeoutMs: 15000 });
		expect(res.status).toBe("initialiser_error");
	});

	it("literature keyless → honest empty index with provenance rule vacuously satisfied", async () => {
		const journal = tmpJournal();
		const bin = engineBin();
		// Force keyless even when the real config has a key (deterministic, no network).
		const cfgDir = mkdtempSync(join(tmpdir(), "litcfg-"));
		const fakeCfg = join(cfgDir, "config.toml");
		const res = await engineLiterature("some problem?", {
			engineBin: bin,
			journal,
			timeoutMs: 30000,
			env: { RAMANUJAN_CONFIG: fakeCfg },
		});
		expect(res.status).toBe("index");
		if (res.status !== "index") return;
		expect(res.index.papers).toHaveLength(0);
		expect(res.index.synthesis).toContain("no LLM key");
		expect(res.checkpoint_id).toMatch(/^cp_\d+$/);
		for (const p of res.index.papers) {
			expect(p.source_url !== null || p.provenance === "model-memory, unverified").toBe(true);
		}
		const rep = await engineReplay(journal, { engineBin: bin, timeoutMs: 30000 });
		expect(rep.status).toBe("ok");
		if (rep.status === "ok") {
			expect(rep.events.some((e) => e.type === "checkpoint_reached")).toBe(true);
		}
	});

	it("literature never throws on transport failure", async () => {
		const res = await engineLiterature("x", { engineBin: "/nonexistent/ramanujan-engine", journal: tmpJournal(), timeoutMs: 15000 });
		expect(res.status).toBe("literature_error");
	});
});

describe("engine binary resolution (no PATH, no uv)", () => {
	function withCwd<T>(dir: string, fn: () => T): T {
		const prev = process.cwd();
		process.chdir(dir);
		try {
			return fn();
		} finally {
			process.chdir(prev);
		}
	}

	function withEnv<T>(key: string, value: string | undefined, fn: () => T): T {
		const prev = process.env[key];
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
		try {
			return fn();
		} finally {
			if (prev === undefined) delete process.env[key];
			else process.env[key] = prev;
		}
	}

	function fakeRepoWithEngine(cardJson: string): string {
		const dir = mkdtempSync(join(tmpdir(), "ramanujan-fakerepo-"));
		const bindir = join(dir, ".venv", "bin");
		mkdirSync(bindir, { recursive: true });
		const bin = join(bindir, "ramanujan-engine");
		writeFileSync(bin, `#!/bin/sh\necho '${cardJson}'\n`);
		chmodSync(bin, 0o755);
		return dir;
	}

	it("explicit non-default opt wins over everything", () => {
		const custom = join(tmpdir(), "custom-engine");
		withEnv("RAMANUJAN_ENGINE_BIN", "/from/env", () => {
			expect(resolveEngineBin({ engineBin: custom })).toBe(custom);
		});
	});

	it("env RAMANUJAN_ENGINE_BIN wins over the bare default", () => {
		withEnv("RAMANUJAN_ENGINE_BIN", "/from/env", () => {
			expect(resolveEngineBin({})).toBe("/from/env");
			expect(resolveEngineBin({ engineBin: "ramanujan-engine" })).toBe("/from/env");
		});
	});

	it("falls back to <cwd>/.venv/bin/ramanujan-engine when present", () => {
		const payload = JSON.stringify({ status: "card", card: { card_id: "c_0001" }, run_id: "e", provider: "p", model_id: "m" });
		const dir = fakeRepoWithEngine(payload);
		withEnv("RAMANUJAN_ENGINE_BIN", undefined, () => {
			withCwd(dir, () => {
				// NB: process.cwd() resolves the /var -> /private/var symlink.
				expect(resolveEngineBin({})).toBe(join(process.cwd(), ".venv", "bin", "ramanujan-engine"));
			});
		});
	});

	it("encode works with no engineBin opt, no env, no PATH — via .venv fallback", async () => {
		const payload = JSON.stringify({ status: "card", card: { card_id: "c_0001" }, run_id: "e", provider: "p", model_id: "m" });
		const dir = fakeRepoWithEngine(payload);
		const journal = join(dir, "journal.jsonl");
		await withEnv("RAMANUJAN_ENGINE_BIN", undefined, async () => {
			await withCwd(dir, async () => {
				// No engineBin passed (like the TUI default) — must not ENOENT.
				const res = await engineEncode("x", { journal, timeoutMs: 15000 });
				expect(res.status).toBe("card");
			});
		});
	});
});
