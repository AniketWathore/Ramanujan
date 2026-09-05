/**
 * Multi-model panel (A6) — ADVISORY ONLY.
 *
 * The panel proposes; the engine disposes. Sealed round 1 → candidate
 * funnel through engineVerify (deterministic, independent) → open round 2
 * → deterministic adjudication. The panel NEVER writes claim_refuted and
 * its output is always phrased as opinion, never verdict.
 */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Type } from "typebox";
import { appendJournalEvent, loadConfig, resolveProviderKey } from "@ramanujan/config";
import { engineVerify, type ClaimCard } from "@ramanujan/bridge";
import type { PendingCardStore } from "./pendingCards.ts";
import type { PiToolDefinition } from "./piTypes.ts";

export type PanelPositionValue = "support" | "doubt" | "object";

export interface PanelistSpec {
	provider: string;
	modelId: string;
	family: string;
	key: string;
	baseUrl: string;
}

export interface PanelistReply {
	position: PanelPositionValue;
	confidence: number;
	objection?: string;
	counterexample_candidate?: Record<string, number | number[]>;
	reasoning?: string;
}

export interface ScoredPosition extends PanelistReply {
	modelId: string;
	provider: string;
	round: 1 | 2;
	revised: boolean;
	candidateVerified?: boolean;
	candidateReason?: string;
}

export interface PanelResult {
	panelRunId: string;
	round1: ScoredPosition[];
	round2: ScoredPosition[];
	advisory: string;
	tally: { support: number; doubt: number; object: number };
	engineVerifiedCandidates: Array<{ modelId: string; candidate: Record<string, number | number[]> }>;
	sameFamilyWarning: string | null;
}

export interface PanelDeps {
	journalPath: string;
	engineBin?: string;
	/** Injectable panelist call (default: direct fetch, no journal — runPanel journals). */
	callPanelist?: (spec: PanelistSpec, messages: Array<{ role: "system" | "user"; content: string }>) => Promise<{ text: string; inputTokens: number; outputTokens: number }>;
	/** Injectable verify (default: real engineVerify — the ONLY decider). */
	verify?: typeof engineVerify;
	timeoutMs?: number;
}

const R1_SYSTEM = `You are an independent mathematics reviewer. You are one of several reviewers examining a claim; you cannot see the others.
Reply with STRICT JSON ONLY, exactly this shape:
{"position": "support"|"doubt"|"object", "confidence": 0.0-1.0, "objection": "optional text", "counterexample_candidate": {"var": value}, "reasoning": "brief"}
- support: you believe the claim holds. doubt: uncertain, state why. object: you believe it is false — include a concrete counterexample_candidate whenever possible.
- Your reply is ADVISORY. You do not issue verdicts; a deterministic engine verifies candidates.`;

function r1User(card: ClaimCard, summary: string): string {
	return `Claim card:\n${JSON.stringify(card)}\n\nKillcheck summary:\n${summary}\n\nReply with STRICT JSON only.`;
}

function r2User(card: ClaimCard, own: ScoredPosition, others: ScoredPosition[]): string {
	const lines = others.map((o) => `- ${o.modelId}: ${o.position} (confidence ${o.confidence})${o.objection ? ` — ${o.objection}` : ""}`);
	return `Claim card:\n${JSON.stringify(card)}\n\nYour round-1 position: ${own.position} (${own.confidence})${own.objection ? ` — ${own.objection}` : ""}\n\nOther reviewers' round-1 positions (attributed):\n${lines.join("\n")}\n\nYou may revise. Reply with STRICT JSON only, same shape as round 1.`;
}

export function extractPanelReply(text: string): PanelistReply {
	const start = text.indexOf("{");
	const end = text.lastIndexOf("}");
	if (start === -1 || end <= start) throw new Error("panelist reply contains no JSON object");
	const parsed = JSON.parse(text.slice(start, end + 1)) as Record<string, unknown>;
	const position = parsed["position"];
	if (position !== "support" && position !== "doubt" && position !== "object") {
		throw new Error(`panelist position must be support|doubt|object, got ${JSON.stringify(position)}`);
	}
	const confidence = Number(parsed["confidence"]);
	if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
		throw new Error(`panelist confidence must be 0..1, got ${JSON.stringify(parsed["confidence"])}`);
	}
	const reply: PanelistReply = { position, confidence };
	if (typeof parsed["objection"] === "string") reply.objection = parsed["objection"];
	if (typeof parsed["reasoning"] === "string") reply.reasoning = parsed["reasoning"];
	if (parsed["counterexample_candidate"] !== undefined) {
		const cand = parsed["counterexample_candidate"];
		if (typeof cand !== "object" || cand === null || Array.isArray(cand)) throw new Error("counterexample_candidate must be an object");
		for (const [k, v] of Object.entries(cand as Record<string, unknown>)) {
			if (typeof v !== "number" && !(Array.isArray(v) && v.every((x) => typeof x === "number"))) {
				throw new Error(`candidate value for ${k} must be a number or number[]`);
			}
		}
		reply.counterexample_candidate = cand as Record<string, number | number[]>;
	}
	return reply;
}

async function defaultCallPanelist(
	spec: PanelistSpec,
	messages: Array<{ role: "system" | "user"; content: string }>,
	timeoutMs: number,
): Promise<{ text: string; inputTokens: number; outputTokens: number }> {
	const ctrl = new AbortController();
	const timer = setTimeout(() => ctrl.abort(), timeoutMs);
	try {
		const resp = await fetch(`${spec.baseUrl}/chat/completions`, {
			method: "POST",
			headers: { "Content-Type": "application/json", Authorization: `Bearer ${spec.key}` },
			body: JSON.stringify({ model: spec.modelId, temperature: 0, max_tokens: 1024, messages }),
			signal: ctrl.signal,
		});
		if (!resp.ok) throw new Error(`HTTP ${resp.status} from ${spec.provider}`);
		const data = (await resp.json()) as { choices?: Array<{ message?: { content?: string } }>; usage?: { prompt_tokens?: number; completion_tokens?: number } };
		return {
			text: data.choices?.[0]?.message?.content ?? "",
			inputTokens: data.usage?.prompt_tokens ?? 0,
			outputTokens: data.usage?.completion_tokens ?? 0,
		};
	} finally {
		clearTimeout(timer);
	}
}

function newPanelRunId(): string {
	return `panel_${Math.random().toString(16).slice(2, 10)}`;
}

export async function runPanel(
	card: ClaimCard,
	summary: string,
	panelists: PanelistSpec[],
	deps: PanelDeps,
): Promise<PanelResult> {
	if (panelists.length < 2) throw new Error(`panel requires ≥2 panelists, got ${panelists.length}`);
	const panelRunId = newPanelRunId();
	const timeoutMs = deps.timeoutMs ?? 60000;
	const callPanelist = deps.callPanelist ?? ((spec, messages) => defaultCallPanelist(spec, messages, timeoutMs));
	const verify = deps.verify ?? engineVerify;

	const families = new Set(panelists.map((p) => p.family));
	const sameFamilyWarning =
		families.size === 1 ? `Warning: all ${panelists.length} panelists are family '${[...families][0]}' — cross-provider panels debate better.` : null;

	const journalLlm = (spec: PanelistSpec, inputTokens: number, outputTokens: number, latencyMs: number) => {
		appendJournalEvent(deps.journalPath, "llm_call", panelRunId, {
			model_id: spec.modelId,
			provider: spec.provider,
			family: spec.family,
			input_tokens: inputTokens,
			output_tokens: outputTokens,
			cost: 0,
			latency_ms: latencyMs,
			role: "panelist",
		});
	};

	// ROUND 1 — sealed: each panelist sees ONLY the card + summary.
	const round1: ScoredPosition[] = await Promise.all(
		panelists.map(async (spec) => {
			const start = Date.now();
			const { text, inputTokens, outputTokens } = await callPanelist(spec, [
				{ role: "system", content: `${R1_SYSTEM}\n(You are ${spec.modelId}.)` },
				{ role: "user", content: r1User(card, summary) },
			]);
			journalLlm(spec, inputTokens, outputTokens, Date.now() - start);
			let reply: PanelistReply;
			try {
				reply = extractPanelReply(text);
			} catch {
				reply = { position: "doubt", confidence: 0, objection: "malformed panelist reply (not strict JSON)" };
			}
			const scored: ScoredPosition = { ...reply, modelId: spec.modelId, provider: spec.provider, round: 1, revised: false };
			appendJournalEvent(deps.journalPath, "panel_position", panelRunId, {
				panel_run_id: panelRunId,
				round: 1,
				model_id: spec.modelId,
				provider: spec.provider,
				position: scored.position,
				confidence: scored.confidence,
				...(scored.objection ? { objection: scored.objection } : {}),
				revised: false,
			});
			return scored;
		}),
	);

	// CANDIDATE FUNNEL — every round-1 candidate goes through engineVerify.
	// The engine decides; the panel only records the outcome.
	const dir = mkdtempSync(join(tmpdir(), "ramanujan-panel-"));
	const cardFile = join(dir, "card.json");
	writeFileSync(cardFile, JSON.stringify(card));
	const engineVerifiedCandidates: PanelResult["engineVerifiedCandidates"] = [];
	for (const pos of round1) {
		if (!pos.counterexample_candidate) continue;
		try {
			const v = await verify(cardFile, pos.counterexample_candidate, { engineBin: deps.engineBin, timeoutMs });
			pos.candidateVerified = v.status === "counterexample_verified";
			pos.candidateReason = v.status === "counterexample_verified" ? v.reason : v.status === "not_counterexample" ? v.reason : v.message;
			if (v.status === "counterexample_verified" && pos.counterexample_candidate) {
				engineVerifiedCandidates.push({ modelId: pos.modelId, candidate: pos.counterexample_candidate });
			}
		} catch (e) {
			pos.candidateVerified = false;
			pos.candidateReason = `verify call failed: ${e}`;
		}
	}

	// ROUND 2 — open debate: each panelist sees the attributed round-1 positions.
	const round2: ScoredPosition[] = await Promise.all(
		panelists.map(async (spec, i) => {
			const own = round1[i];
			const others = round1.filter((_, j) => j !== i);
			const start = Date.now();
			const { text, inputTokens, outputTokens } = await callPanelist(spec, [
				{ role: "system", content: `${R1_SYSTEM}\n(You are ${spec.modelId}.)` },
				{ role: "user", content: r2User(card, own, others) },
			]);
			journalLlm(spec, inputTokens, outputTokens, Date.now() - start);
			let reply: PanelistReply;
			try {
				reply = extractPanelReply(text);
			} catch {
				reply = { position: own.position, confidence: own.confidence, objection: "malformed round-2 reply — keeping round-1 position" };
			}
			const revised = reply.position !== own.position || reply.confidence !== own.confidence;
			const scored: ScoredPosition = {
				...reply,
				modelId: spec.modelId,
				provider: spec.provider,
				round: 2,
				revised,
				counterexample_candidate: reply.counterexample_candidate ?? own.counterexample_candidate,
			};
			appendJournalEvent(deps.journalPath, "panel_position", panelRunId, {
				panel_run_id: panelRunId,
				round: 2,
				model_id: spec.modelId,
				provider: spec.provider,
				position: scored.position,
				confidence: scored.confidence,
				...(scored.objection ? { objection: scored.objection } : {}),
				revised,
			});
			return scored;
		}),
	);

	// ADJUDICATION v1 — deterministic aggregation, advisory phrasing only.
	const finals = round2.map((r2, i) => (r2.revised ? r2 : round1[i]));
	const tally = { support: 0, doubt: 0, object: 0 };
	for (const f of finals) tally[f.position]++;
	const objections = finals.filter((f) => f.objection).map((f) => `${f.modelId}: ${f.objection}`);
	const verifiedNote =
		engineVerifiedCandidates.length > 0
			? ` Engine-verified candidates (deterministic, independent): ${engineVerifiedCandidates.map((c) => `${c.modelId} → ${JSON.stringify(c.candidate)}`).join("; ")}.`
			: " No candidate verified by the engine.";
	const advisory =
		`panel: ${tally.support} support / ${tally.doubt} doubt / ${tally.object} object (n=${finals.length}).` +
		(objections.length > 0 ? ` Objections: ${objections.join(" | ")}.` : " No objections recorded.") +
		verifiedNote;
	appendJournalEvent(deps.journalPath, "panel_advisory", panelRunId, {
		panel_run_id: panelRunId,
		support: tally.support,
		doubt: tally.doubt,
		object: tally.object,
		advisory,
	});

	return { panelRunId, round1, round2, advisory, tally, engineVerifiedCandidates, sameFamilyWarning };
}

export interface PanelReviewDeps {
	journalPath?: string;
	engineBin?: string;
	store: PendingCardStore;
	loadPanelists?: () => PanelistSpec[];
	runPanelFn?: typeof runPanel;
	callPanelist?: PanelDeps["callPanelist"];
}

const panelReviewSchema = Type.Object({
	card_id: Type.Optional(Type.String({ description: "Pending card id from the store" })),
	card: Type.Optional(Type.Object({}, { description: "Inline claim card JSON (alternative to card_id)" })),
});

/** panel_review tool — advisory debate, never a verdict. */
export function createPanelReviewTool(deps: PanelReviewDeps): PiToolDefinition {
	return {
		name: "panel_review",
		label: "Panel: review",
		description:
			"Request multi-model panel review of a claim card (advisory opinions + engine-verified candidates, never a verdict). Offered after SURVIVED or on explicit request. Takes card_id (pending store) or inline card JSON.",
		parameters: panelReviewSchema,
		promptGuidelines: [
			"Panel output is advisory opinion, never a verdict — phrase it that way.",
			"A panel objection is not a refutation. Only the engine's double-verified counterexample refutes.",
		],
		execute: async (_toolCallId, params: unknown) => {
			const p = params as { card_id?: string; card?: ClaimCard };
			let card: ClaimCard | undefined;
			let summary = "no prior killcheck in this session";
			if (typeof p.card_id === "string") {
				const entry = deps.store.get(p.card_id);
				if (!entry) {
					return { content: [{ type: "text", text: `No card ${p.card_id} in the pending store. Encode it first with killcheck_encode.` }], details: { refused: "unknown_card" } };
				}
				card = entry.card;
				if (entry.lastSummary) summary = entry.lastSummary;
			} else if (p.card && typeof p.card === "object") {
				card = p.card;
			} else {
				return {
					content: [{ type: "text", text: "panel_review needs card_id or inline card JSON." }],
					details: { refused: "missing_card" },
				};
			}
			let panelists: PanelistSpec[];
			try {
				panelists = deps.loadPanelists ? deps.loadPanelists() : loadPanelistsFromConfig();
			} catch (e) {
				return {
					content: [{ type: "text", text: `Panel unavailable: ${e}. Configure ≥2 panelists (roles set-panel …).` }],
					details: { unavailable: String(e).slice(0, 200) },
				};
			}
			const run = deps.runPanelFn ?? runPanel;
			const result = await run(card, summary, panelists, {
				journalPath: deps.journalPath ?? "journal.jsonl",
				engineBin: deps.engineBin,
				callPanelist: deps.callPanelist,
			});
			return { content: [{ type: "text", text: renderPanelCard(result) }], details: result };
		},
	};
}

export function renderPanelCard(result: PanelResult): string {
	const lines: string[] = [];
	lines.push("Panel review (ADVISORY — opinions, not a verdict):");
	for (const p of result.round2.length > 0 ? result.round2 : result.round1) {
		lines.push(`- ${p.modelId} [${p.provider}]: ${p.position} (confidence ${p.confidence})${p.revised ? " [revised]" : ""}${p.objection ? ` — ${p.objection}` : ""}`);
		if (p.counterexample_candidate) {
			lines.push(`  candidate ${JSON.stringify(p.counterexample_candidate)} → ${p.candidateVerified ? "ENGINE-VERIFIED" : "not verified by engine"}`);
		}
	}
	lines.push(result.advisory);
	if (result.sameFamilyWarning) lines.push(result.sameFamilyWarning);
	return lines.join("\n");
}

/** Load panelists from config roles.panel (≥2), resolving keys (env > stored). */
export function loadPanelistsFromConfig(configPath?: string): PanelistSpec[] {
	const cfg = loadConfig(configPath);
	const panel = cfg.roles.panel ?? [];
	if (panel.length < 2) throw new Error(`panel needs ≥2 configured panelists, got ${panel.length} (roles set-panel …)`);
	return panel.map((r) => {
		const prov = cfg.providers.find((p) => p.id === r.provider);
		if (!prov) throw new Error(`provider ${r.provider} not found`);
		const key = resolveProviderKey(prov);
		if (!key) throw new Error(`no key for provider ${prov.id}`);
		return { provider: prov.id, modelId: r.model_id, family: prov.family, key, baseUrl: prov.base_url.replace(/\/+$/, "") };
	});
}
