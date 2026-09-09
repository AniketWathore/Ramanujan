/**
 * Ramanujan pi extension: math tools + human commands + prompt/guard hooks.
 *
 * Restores v0.4 A5 gates (killcheck_encode/run + /card flow shows as
 * streaming tool cards, not raw slash echo) and adds v2 five-stage
 * checkpoint flow: after every stage the agent MUST stop and await
 * human confirm/revise via /checkpoint. Both gates are human-only;
 * no confirm tool is ever registered for the LLM.
 */

import { Type } from "typebox";
import { engineInitialise, engineLiterature, engineSpawnWorktree, enginePostClaim } from "@ramanujan/bridge";
import { mathToolCallGate, createMathTools, type MathToolDeps } from "./tools.ts";
import { createPanelReviewTool, loadPanelistsFromConfig, renderPanelCard, runPanel } from "./panel.ts";
import { PendingCardStore } from "./pendingCards.ts";
import { CheckpointStore } from "./checkpoints.ts";
import type { PiCommandContext, PiExtensionAPI } from "./piTypes.ts";
import { appendMathPrompt, reframeBareVerdict } from "./systemPrompt.ts";
import { listRuns, renderRunList } from "./render.ts";

export interface RamanujanExtensionOptions extends MathToolDeps {
	journalPath?: string;
	engineBin?: string;
}

export default function ramanujanExtension(pi: PiExtensionAPI, opts: RamanujanExtensionOptions = {}): void {
	const journalPath = opts.journalPath ?? "journal.jsonl";
	const { store, definitions } = createMathTools(opts);
	const checkpointStore = new CheckpointStore<unknown>();
	// Keep the last successful Initialiser spec so Literature always searches from it (fixes timeout/irrelevant-search when called without specFile).
	let latestInitialiserSpec: Record<string, unknown> | null = null;

	// v1 killcheck + panel tools — render as live tool cards (subagent-style), not raw commands.
	for (const tool of definitions) pi.registerTool(tool);
	pi.registerTool(createPanelReviewTool({ journalPath, engineBin: opts.engineBin, store }));

	// v2 five-stage Initialiser + Literature as agent tools (streaming, then blocking checkpoint).
	pi.registerTool({
		name: "ramanujan_initialise",
		label: "Ramanujan: initialise",
		description: "Stage 1 Initialiser — statement → ProblemSpec + numeric-only kill-check. Returns checkpoint A and WAITS for human /checkpoint confirm.",
		parameters: Type.Object({ statement: Type.String({ description: "Informal problem statement verbatim" }) }),
		promptGuidelines: [
			"Call ramanujan_initialise once per problem, then present its checkpoint card and WAIT for human /checkpoint confirm — never auto-continue.",
		],
		execute: async (_id, params) => {
			const statement = String((params as { statement: string }).statement);
			const res = await engineInitialise(statement, { journal: journalPath, engineBin: opts.engineBin });
			if (res.status === "spec") {
				// Remember for Literature: literature must always search from Initialiser's checkpoint.
				try {
					latestInitialiserSpec = (res.spec as unknown as Record<string, unknown>) ?? null;
				} catch {
					// keep previous
				}
				const cp = checkpointStore.propose("initialiser", `run ${res.run_id} problem_spec`, "Checkpoint A — structured spec + numeric kill-check. Confirm to proceed, or revise with feedback.", res);
				const spec = res.spec as { id: string; domain: string[]; statement_informal: string; statement_formal: string | null; variables: Array<{ name: string; type: string; constraints: string }>; objective: string; known_special_cases: string[]; kill_check_config: { run_smt: boolean; run_numeric_search: boolean; small_case_limit: number | null }; open_questions_for_user: string[] };
				const nk = res.numeric_killcheck as { status: string; checked_total: number; methods: string[] };
				const limitDisplay = spec.kill_check_config.small_case_limit == null ? "no pre-set limit — scope decided with you at this checkpoint (bounded N / random sampling / symbolic via worktrees)" : String(spec.kill_check_config.small_case_limit);
				const nkDisplay = nk.methods.length === 0 && nk.checked_total === 0
					? `survived — not applicable at this stage (informal problem, formal checks deferred to worktrees; ${limitDisplay})`
					: `${nk.status} (checked=${nk.checked_total} methods=${nk.methods.join(",")})`;
				const body = [
					`Checkpoint ${cp.checkpointId} — Initialiser Stage`,
					``,
					`Problem Specification Built:`,
					` - ID: ${spec.id}`,
					` - Domain: ${spec.domain.length ? spec.domain.join(", ") : "(none — inferred as number-theory, please confirm)"}`,
					` - Statement (informal): "${spec.statement_informal}"`,
					...(spec.variables.length ? [` - Variables: ${spec.variables.map((v) => `${v.name}: ${v.type}${v.constraints ? ` (${v.constraints})` : ""}`).join(", ")}`] : [` - Variables: (none — inferred n: positive integer, please confirm)`]),
					` - Objective: ${spec.objective}`,
					...(spec.known_special_cases.length ? [` - Known cases: ${spec.known_special_cases.join("; ")}`] : []),
					` - Kill check config: SMT=${spec.kill_check_config.run_smt}, numeric search=${spec.kill_check_config.run_numeric_search}, limit: ${limitDisplay}`,
					``,
					`Numeric Check Result: ${nkDisplay}`,
					``,
					...(spec.open_questions_for_user.length ? [`Open questions for you:`, ...spec.open_questions_for_user.map((q) => ` - ${q}`), ``] : []),
					`—`.repeat(40),
					``,
					`Do you want to confirm and continue, or do you have any issues, changes, or fixes?`,
					`Type your response in the chatbox:`,
					` - Say "confirm", "yes", "continue", "looks good", or any positive to proceed — I'll automatically continue to Stage 2 (Literature).`,
					` - Or describe any changes you'd like (domain, variables, limit, wording) — I'll chat normally and wait until you say confirm.`,
				].join("\n");
				return {
					content: [{ type: "text", text: body }],
					details: { checkpointId: cp.checkpointId, run_id: res.run_id, spec: res.spec },
				};
			}
			if (res.status === "not_initialisable") return { content: [{ type: "text", text: `NOT_INITIALISABLE (honest): ${(res as { reason: string }).reason}` }], details: res };
			return { content: [{ type: "text", text: `INITIALISER ERROR (model failed, not a refusal): ${(res as { reason: string }).reason ?? (res as { message: string }).message}` }], details: res };
		},
	});
	pi.registerTool({
		name: "ramanujan_literature",
		label: "Ramanujan: literature",
		description: "Stage 2 Literature — statement → papers index + synthesis (always seeded from Initialiser's checkpoint/spec when available). Returns checkpoint B and WAITS for human /checkpoint confirm.",
		parameters: Type.Object({ statement: Type.String({ description: "Informal statement verbatim (ignored when Initialiser spec exists — search uses checkpoint A's spec)" }) }),
		promptGuidelines: [
			"Call ramanujan_literature after checkpoint A is confirmed — it always searches from Initialiser's checkpoint/spec (specFile), so it works for every problem. Then present checkpoint B and WAIT for human /checkpoint confirm.",
		],
		execute: async (_id, params) => {
			const rawStatement = String((params as { statement: string }).statement);
			// Always seed literature from Initialiser's checkpoint when available — this is what makes it work for every problem.
			let statement = rawStatement;
			let specFile: string | undefined;
			if (latestInitialiserSpec && typeof latestInitialiserSpec === "object") {
				try {
					const info = latestInitialiserSpec as { statement_informal?: unknown };
					if (typeof info.statement_informal === "string" && info.statement_informal.trim().length > 0) {
						statement = info.statement_informal;
					}
					const { mkdtempSync, writeFileSync } = await import("node:fs");
					const { tmpdir } = await import("node:os");
					const { join } = await import("node:path");
					const dir = mkdtempSync(join(tmpdir(), "ramanujan-spec-"));
					specFile = join(dir, "problem_spec.json");
					writeFileSync(specFile, JSON.stringify(latestInitialiserSpec));
				} catch {
					// fall back to raw statement without specFile
					specFile = undefined;
				}
			}
			const res = await engineLiterature(statement, { journal: journalPath, engineBin: opts.engineBin, specFile });
			if (res.status === "index") {
				const cp = checkpointStore.propose("literature", `run ${res.run_id} papers_index`, "Checkpoint B — synthesis + papers index. Confirm to proceed, or revise.", res);
				// Per-category counts from retrieved papers (arXiv/Scholar -> papers, DuckDuckGo -> websites/blogs/books)
				const cats: Record<string, number> = {};
				for (const p of res.index.papers as Array<{ relevance: string }>) {
					const r = p.relevance.toLowerCase();
					let c = "papers";
					if (r.includes("blog")) c = "blogs";
					else if (r.includes("book")) c = "books";
					else if (r.includes("discussion")) c = "discussions";
					else if (r.includes("website") || r.includes("duckduckgo")) c = "websites";
					else if (r.includes("article")) c = "articles";
					else if (r.includes("arxiv") || r.includes("scholar")) c = "papers";
					cats[c] = (cats[c] ?? 0) + 1;
				}
				const catLine = Object.entries(cats).map(([k, v]) => `${k}: ${v}`).join(" | ") || "papers: 0";
				const body = [
					`Checkpoint ${cp.checkpointId} — Literature Stage (Obscura headless: arXiv + Scholar JS + DuckDuckGo, text only, no-render)`,
					``,
					`Synthesis: ${(res.index.synthesis ?? "").slice(0, 700)}`,
					`Collected: ${res.index.papers.length} entries — ${catLine}`,
					`Saved: literature/papers/<id>.md (+ books/websites/blogs/articles per category, text only)`,
					``,
					`Do you want to confirm and continue? Type "confirm"/"yes"/"continue" to proceed, or describe any changes — I'll wait until you confirm.`,
				].join("\n");
				return {
					content: [{ type: "text", text: body }],
					details: { checkpointId: cp.checkpointId, run_id: res.run_id, categories: cats },
				};
			}
			if (res.status === "not_searchable") return { content: [{ type: "text", text: `NOT_SEARCHABLE: ${(res as { reason: string }).reason}` }], details: res };
			return { content: [{ type: "text", text: `LITERATURE ERROR: ${(res as { reason: string }).reason ?? (res as { message: string }).message}` }], details: res };
		},
	});
	// Natural-language checkpoint handler — agent calls this when human says confirm/yes or gives feedback.
	// Human never calls a slash; they just type in chat. This keeps the flow you asked for.
	pi.registerTool({
		name: "checkpoint_respond",
		label: "Checkpoint: respond",
		description: "Respond to a pending checkpoint. Call with decision=confirm when human says confirm/yes/continue/looks good, or decision=revise with feedback when human asks for changes. Human-only gate: never call without explicit human confirm/feedback text.",
		parameters: Type.Object({ checkpoint_id: Type.String({ description: "Checkpoint id, e.g. cp_001" }), decision: Type.String({ description: "confirm or revise" }), feedback: Type.Optional(Type.String({ description: "Feedback when revise" })) }),
		promptGuidelines: [
			"After proposing a checkpoint, ask human in natural language (do not mention /checkpoint).",
			"When human says confirm/yes/continue/proceed/looks good/go ahead, call checkpoint_respond with decision=confirm.",
			"When human describes changes, call checkpoint_respond with decision=revise and feedback=their text, then re-present and WAIT again.",
			"Never auto-confirm without human text.",
		],
		execute: async (_id, params) => {
			const p = params as { checkpoint_id: string; decision: string; feedback?: string };
			const id = String(p.checkpoint_id);
			const dec = String(p.decision).toLowerCase();
			if (dec === "confirm" || dec === "approve" || dec === "continue") {
				try {
					checkpointStore.confirm(id);
					return { content: [{ type: "text", text: `Checkpoint ${id} confirmed — proceeding to next stage.` }], details: { checkpoint_id: id, decision: "confirm" } };
				} catch (e) { return { content: [{ type: "text", text: String(e) }], details: { error: String(e) }, isError: true }; }
			}
			if (dec === "revise" || dec === "feedback" || dec === "change") {
				const fb = String(p.feedback ?? "").trim();
				if (!fb) return { content: [{ type: "text", text: "Revise needs feedback text." }], details: {}, isError: true };
				try {
					checkpointStore.revise(id, fb);
					return { content: [{ type: "text", text: `Checkpoint ${id} revised — re-presented pending (rev ${checkpointStore.get(id)?.revision}). Awaiting confirm.` }], details: { checkpoint_id: id, decision: "revise", feedback: fb } };
				} catch (e) { return { content: [{ type: "text", text: String(e) }], details: { error: String(e) }, isError: true }; }
			}
			return { content: [{ type: "text", text: `Unknown decision ${p.decision}; use confirm or revise.` }], details: {}, isError: true };
		},
	});

	// Stage 3 worktrees — render as live subagent panels (not raw slash echo).
	pi.registerTool({
		name: "worktree_spawn",
		label: "Worktree: spawn",
		description: "Spawn a computational worktree (subagent-style). Returns wt_id; show its live progress as a subagent panel.",
		parameters: Type.Object({ provider: Type.String(), modelId: Type.String(), family: Type.String(), modelRef: Type.String() }),
		promptGuidelines: ["Spawn worktrees via this tool so they render as live subagent cards; do not run bare CLI."],
		execute: async (_id, params) => {
			const p = params as { provider: string; modelId: string; family: string; modelRef: string };
			const res = await engineSpawnWorktree({ ...p, journal: journalPath, engineBin: opts.engineBin });
			return { content: [{ type: "text", text: `Worktree ${res.worktree_id} spawned (${p.provider}/${p.modelId} family ${p.family}) — live subagent panel now tracking.` }], details: res };
		},
	});
	pi.registerTool({
		name: "claim_post",
		label: "Claim: post",
		description: "Post a ClaimCard from a worktree; runs Tier0+Tier1 inline and renders verdict. Use worktree subagent flow, not bare commands.",
		parameters: Type.Object({ worktreeId: Type.String(), card: Type.Unknown() }),
		promptGuidelines: ["Post claims via this tool so verdicts render in subagent cards; wait for engine double-verification."],
		execute: async (_id, params) => {
			const p = params as { worktreeId: string; card: unknown };
			const { mkdtempSync, writeFileSync } = await import("node:fs");
			const { tmpdir } = await import("node:os");
			const { join } = await import("node:path");
			const dir = mkdtempSync(join(tmpdir(), "ramanujan-claim-"));
			const cardFile = join(dir, "card.json");
			writeFileSync(cardFile, JSON.stringify(p.card));
			const res = await enginePostClaim(cardFile, { worktreeId: p.worktreeId, journal: journalPath, engineBin: opts.engineBin });
			return { content: [{ type: "text", text: `Claim ${res.claim_id} via ${p.worktreeId} — Tier0 ${res.tier0.verdict} verification_path=${res.verification_path}\n${JSON.stringify(res.tier1).slice(0, 400)}` }], details: res };
		},
	});

	// Harness gate: block unconfirmed killcheck_run (defense in depth).
	pi.on("tool_call", (event) => mathToolCallGate(store, event));

	// System prompt + verdict reframe.
	pi.on("before_agent_start", (event) => ({ systemPrompt: appendMathPrompt(event.systemPrompt) }));
	pi.on("message_end", (event) => {
		const msg = event.message as { role: string; content: unknown };
		if (msg.role !== "assistant" || typeof msg.content !== "string") return;
		const reframed = reframeBareVerdict(msg.content);
		if (reframed !== msg.content) return { message: { ...(event.message as Record<string, unknown>), content: reframed } } as never;
	});

	// Human commands — all render via ctx.ui.notify and block LLM self-confirm.
	pi.registerCommand("card", {
		description: "Confirm, edit, reject, or show the pending claim card",
		handler: async (args: string, ctx: PiCommandContext) => {
			ctx.ui.notify(await cardCommand(store, args), "info");
		},
	});
	pi.registerCommand("checkpoint", {
		description: "Checkpoint gate: /checkpoint confirm <cp_id> | /checkpoint revise <cp_id> <feedback> | /checkpoint list",
		handler: async (args: string, ctx: PiCommandContext) => {
			ctx.ui.notify(await checkpointCommand(checkpointStore, args), "info");
		},
	});
	pi.registerCommand("runs", {
		description: "List verification runs from the shared journal",
		handler: async (_args: string, ctx: PiCommandContext) => {
			ctx.ui.notify(renderRunList(await listRuns(opts.engineBin, journalPath)).split("\n").slice(0, 12).join("\n"), "info");
		},
	});
	pi.registerCommand("panel", {
		description: "Run multi-model panel review on a pending card: /panel [card_id]",
		handler: async (args: string, ctx: PiCommandContext) => {
			const cardId = args.trim().split(/\s+/)[0];
			const entry = cardId ? store.get(cardId) : store.reviewable();
			if (!entry) {
				ctx.ui.notify("No card to review. Encode one first with killcheck_encode, or pass a confirmed card id: /panel <card_id>.", "warning");
				return;
			}
			let panelists;
			try { panelists = loadPanelistsFromConfig(); } catch (e) { ctx.ui.notify(`Panel unavailable: ${e}`, "error"); return; }
			const result = await runPanel(entry.card, entry.lastSummary ?? "no prior killcheck in this session", panelists, { journalPath, engineBin: opts.engineBin });
			ctx.ui.notify(renderPanelCard(result).split("\n").slice(0, 20).join("\n"), "info");
		},
	});
	pi.registerCommand("verdict", {
		description: "Tap ground truth: /verdict <run_id> correct|incorrect",
		handler: async (args: string, ctx: PiCommandContext) => {
			const [runId, word] = args.trim().split(/\s+/);
			if (!runId || (word !== "correct" && word !== "incorrect")) { ctx.ui.notify("Usage: /verdict <run_id> correct|incorrect", "warning"); return; }
			const { confirmVerdict } = await import("./tools.ts");
			confirmVerdict(journalPath, runId, word === "correct");
			ctx.ui.notify(`Recorded ground truth for ${runId}: ${word}`, "info");
		},
	});
}

async function cardCommand(store: PendingCardStore, args: string): Promise<string> {
	const [sub, ...rest] = args.trim().split(/\s+/);
	if (sub === "confirm") {
		const target = rest[0] ? store.get(rest[0]) : store.pending()[0];
		if (!target) return `No pending card ${rest[0] ?? ""}.`;
		if (target.status !== "pending") return `Card ${target.cardId} already ${target.status}.`;
		store.confirm(target.cardId);
		return `Card ${target.cardId} confirmed — killcheck_run may now proceed. Next: tell the agent to run it (e.g. say "run it") — confirming alone does not start the check.`;
	}
	if (sub === "reject") {
		const target = rest[0] ? store.get(rest[0]) : store.pending()[0];
		if (!target) return "No pending card.";
		store.reject(target.cardId);
		return `Card ${target.cardId} rejected — nothing will run.`;
	}
	if (sub === "edit") {
		const cardId = rest[0];
		const target = cardId ? store.get(cardId) : store.pending()[0];
		if (!target) return "No pending card.";
		const jsonText = rest.slice(cardId ? 1 : 0).join(" ");
		if (!jsonText) return "Usage: /card edit <card_id> <card-json>";
		let parsed: unknown;
		try { parsed = JSON.parse(jsonText); } catch { return "Edit failed: not valid JSON."; }
		if (typeof parsed !== "object" || parsed === null || (parsed as { card_id?: unknown }).card_id !== target.cardId) return `Edit failed: card_id must stay ${target.cardId}.`;
		store.edit(parsed as Parameters<PendingCardStore["edit"]>[0]);
		return `Card ${target.cardId} edited + confirmed — killcheck_run may now proceed.`;
	}
	const pend = store.pending();
	if (pend.length === 0) return "No pending cards.";
	return pend.map((p) => `Pending ${p.cardId}: ${p.card.statement_informal}\nConclusion: ${p.card.conclusion.expr}\n/card confirm ${p.cardId} | /card reject ${p.cardId}`).join("\n\n");
}

async function checkpointCommand(store: CheckpointStore<unknown>, args: string): Promise<string> {
	const [sub, cpId, ...rest] = args.trim().split(/\s+/);
	if (sub === "list" || !sub) {
		const pend = store.pending();
		if (pend.length === 0) return "No pending checkpoints.";
		return pend.map((c) => `Pending ${c.checkpointId} (${c.stage}) rev ${c.revision}: ${c.prompt.slice(0, 120)}\n/checkpoint confirm ${c.checkpointId} | /checkpoint revise ${c.checkpointId} <feedback>`).join("\n\n");
	}
	if (sub === "confirm") {
		if (!cpId) return "Usage: /checkpoint confirm <cp_id>";
		try { store.confirm(cpId); return `Checkpoint ${cpId} confirmed — stage may proceed.`; } catch (e) { return String(e); }
	}
	if (sub === "revise") {
		if (!cpId) return "Usage: /checkpoint revise <cp_id> <feedback>";
		const feedback = rest.join(" ").trim();
		if (!feedback) return "Revise needs feedback text.";
		try { store.revise(cpId, feedback); return `Checkpoint ${cpId} revised — re-presented pending (rev ${store.get(cpId)?.revision}). Awaiting /checkpoint confirm.`; } catch (e) { return String(e); }
	}
	return "Usage: /checkpoint [list|confirm <id>|revise <id> <feedback>]";
}

export type { PiCommandContext, PiExtensionAPI };
