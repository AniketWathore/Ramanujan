/**
 * chatCompletion: bearer/URL, 429 backoff, journal fields, no key in journal.
 */

import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { chatCompletion } from "../src/index.ts";
import type { ResolvedRole } from "../src/index.ts";

const resolved: ResolvedRole = {
	provider: "mock",
	providerName: "Mock",
	baseUrl: "https://example.com/v1",
	modelId: "mock/model",
	family: "mock",
	role: "assistant",
	key: "fake-chat-key",
};

function tmpJournal(): string {
	return join(mkdtempSync(join(tmpdir(), "ramanujan-chat-")), "journal.jsonl");
}

afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe("chatCompletion", () => {
	it("posts to base_url with bearer and journals provider+model", async () => {
		const journal = tmpJournal();
		let seenUrl = "";
		let seenAuth = "";
		const fakeFetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
			seenUrl = String(url);
			seenAuth = ((init?.headers ?? {}) as Record<string, string>)["Authorization"] ?? "";
			return new Response(
				JSON.stringify({ choices: [{ message: { content: "hello" } }], usage: { prompt_tokens: 5, completion_tokens: 7 } }),
				{ status: 200 },
			);
		});
		vi.stubGlobal("fetch", fakeFetch);
		const res = await chatCompletion(resolved, [{ role: "user", content: "hi" }], { journalPath: journal, runId: "run_chat1" });
		expect(res.text).toBe("hello");
		expect(seenUrl).toBe("https://example.com/v1/chat/completions");
		expect(seenAuth).toBe("Bearer fake-chat-key");
		const lines = readFileSync(journal, "utf-8").trim().split("\n");
		expect(lines).toHaveLength(1);
		const ev = JSON.parse(lines[0]);
		expect(ev.type).toBe("llm_call");
		expect(ev.payload.provider).toBe("mock");
		expect(ev.payload.model_id).toBe("mock/model");
		expect(ev.payload.input_tokens).toBe(5);
		expect(JSON.stringify(ev)).not.toContain("fake-chat-key");
	});

	it("retries 429 then succeeds", async () => {
		let n = 0;
		const fakeFetch = vi.fn(async () => {
			n++;
			if (n === 1) return new Response("busy", { status: 429, headers: { "retry-after": "0" } });
			return new Response(JSON.stringify({ choices: [{ message: { content: "ok" } }], usage: {} }), { status: 200 });
		});
		vi.stubGlobal("fetch", fakeFetch);
		const res = await chatCompletion(resolved, [{ role: "user", content: "hi" }], { retries: 3, timeoutMs: 5000 });
		expect(res.text).toBe("ok");
		expect(n).toBe(2);
	});

	it("fails after retries on 500", async () => {
		const fakeFetch = vi.fn(async () => new Response("err", { status: 500 }));
		vi.stubGlobal("fetch", fakeFetch);
		await expect(chatCompletion(resolved, [{ role: "user", content: "hi" }], { retries: 2, timeoutMs: 5000 })).rejects.toThrow(/failed after 2/);
	});
});
