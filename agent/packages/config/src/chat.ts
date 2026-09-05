/**
 * OpenAI-compatible chat caller used by the assistant (A5) and panelists (A6).
 * Every call appends a schema-conforming llm_call to the shared journal.
 */

import { appendLlmCall } from "./journal.ts";
import type { ResolvedRole } from "./config.ts";

export interface ChatMessage {
	role: "system" | "user" | "assistant";
	content: string;
}

export interface ChatResult {
	text: string;
	inputTokens: number;
	outputTokens: number;
	latencyMs: number;
}

async function sleep(ms: number): Promise<void> {
	return new Promise((r) => setTimeout(r, ms));
}

export async function chatCompletion(
	resolved: ResolvedRole,
	messages: ChatMessage[],
	opts: { journalPath?: string; runId?: string; timeoutMs?: number; retries?: number } = {},
): Promise<ChatResult> {
	const url = `${resolved.baseUrl}/chat/completions`;
	const body = {
		model: resolved.modelId,
		temperature: 0,
		max_tokens: 2048,
		messages,
	};
	const retries = opts.retries ?? 3;
	const timeoutMs = opts.timeoutMs ?? 60000;
	let lastErr: unknown = null;
	for (let attempt = 0; attempt < retries; attempt++) {
		const start = Date.now();
		try {
			const ctrl = new AbortController();
			const timer = setTimeout(() => ctrl.abort(), timeoutMs);
			let resp: Response;
			try {
				resp = await fetch(url, {
					method: "POST",
					headers: { "Content-Type": "application/json", Authorization: `Bearer ${resolved.key}` },
					body: JSON.stringify(body),
					signal: ctrl.signal,
				});
			} finally {
				clearTimeout(timer);
			}
			if (resp.status === 429 || resp.status >= 500) {
				const retryAfter = resp.headers.get("retry-after");
				if (retryAfter) {
					const delay = Math.min(parseInt(retryAfter, 10) * 1000 || 0, 10000);
					if (delay > 0) await sleep(delay);
				}
				throw new Error(`HTTP ${resp.status} from ${resolved.provider}`);
			}
			if (!resp.ok) {
				const text = await resp.text().catch(() => "");
				throw new Error(`HTTP ${resp.status} from ${resolved.provider}: ${text.slice(0, 300)}`);
			}
			const data = (await resp.json()) as {
				choices?: Array<{ message?: { content?: string } }>;
				usage?: { prompt_tokens?: number; completion_tokens?: number };
			};
			const text = data.choices?.[0]?.message?.content ?? "";
			const inputTokens = data.usage?.prompt_tokens ?? 0;
			const outputTokens = data.usage?.completion_tokens ?? 0;
			const latencyMs = Date.now() - start;
			if (opts.journalPath && opts.runId) {
				appendLlmCall(opts.journalPath, opts.runId, {
					model_id: resolved.modelId,
					provider: resolved.provider,
					family: resolved.family,
					input_tokens: inputTokens,
					output_tokens: outputTokens,
					cost: 0,
					latency_ms: latencyMs,
					retries: attempt,
					role: resolved.role,
				});
			}
			return { text, inputTokens, outputTokens, latencyMs };
		} catch (e) {
			lastErr = e;
			if (attempt < retries - 1) await sleep(500 * 2 ** attempt);
		}
	}
	throw new Error(`chat completion failed after ${retries} retries: ${lastErr}`);
}
