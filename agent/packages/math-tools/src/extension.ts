/**
 * Ramanujan pi extension: five-stage pipeline (Initialiser → Literature → worktrees → Consolidation → Reviewer).
 * killcheck_encode/run removed per user request (Option 1: pipeline via engine CLI, no direct ClaimCard encode).
 *
 * Checkpoint discipline: the TS store and the engine share ONE id sequence in
 * the shared journal. TS adopts engine-minted ids (never re-mints) and
 * journals every propose/resolve, so `checkpoint_respond` works on any id.
 */

import { Type } from "typebox";
import {
	engineCheckpointCSummary,
	engineConsolidate,
	engineInitialise,
	engineLiterature,
	enginePostClaim,
	enginePresetAdd,
	enginePresets,
	engineReview,
	engineSpawnWorktree,
} from "@ramanujan/bridge";
import { appendJournalEvent, familyOf, loadRegistry, UNKNOWN_FAMILY } from "@ramanujan/config";
import type { MathToolDeps } from "./tools.ts";
import { CheckpointStore, findCheckpointInJournal } from "./checkpoints.ts";
import type { PiCommandContext, PiExtensionAPI, PiToolResult } from "./piTypes.ts";
import { appendMathPrompt, reframeBareVerdict } from "./systemPrompt.ts";

export interface RamanujanExtensionOptions extends MathToolDeps {
	journalPath?: string;
	engineBin?: string;
}

function tsRunId(): string {
	return `ts_${Math.random().toString(16).slice(2, 10)}`;
}

function splitModelRef(ref: string): { provider: string; modelId: string } {
	const i = ref.indexOf("/");
	if (i <= 0) return { provider: ref.trim() || "unknown", modelId: ref.trim() };
	return { provider: ref.slice(0, i).trim(), modelId: ref.slice(i + 1).trim() || ref.trim() };
}

function familyForRef(ref: string): string {
	try {
		return familyOf(ref, loadRegistry());
	} catch {
		return UNKNOWN_FAMILY;
	}
}

export default function ramanujanExtension(pi: PiExtensionAPI, opts: RamanujanExtensionOptions = {}): void {
	const journalPath = opts.journalPath ?? "journal.jsonl";
	const runId = tsRunId();
	const checkpointStore = new CheckpointStore<unknown>();
	// Share one checkpoint id sequence with the engine (fresh processes would re-mint cp_001).
	checkpointStore.rehydrateFromJournal(journalPath);
	// Keep the last successful Initialiser spec so Literature always searches from it (fixes timeout/irrelevant-search when called without specFile).
	let latestInitialiserSpec: Record<string, unknown> | null = null;
	let latestInitialiserStatement = "";
	// Current problem session: worktrees spawned + claims posted via this instance.
	// The shared journal accumulates every past problem, so status/consolidation/review scope to these ids.
	const sessionWorktreeIds: string[] = [];
	const sessionClaimIds: string[] = [];
	let selectedPreset: { name: string; models: string[] } | null = null;

	const journalReached = (cpId: string, stage: string, outputRef: string, revision: number) => {
		try {
			appendJournalEvent(journalPath, "checkpoint_reached", runId, {
				checkpoint_id: cpId,
				stage,
				output_ref: outputRef,
				revision,
			});
		} catch {
			// best-effort — the card still works, just not journaled
		}
	};
	const journalResolved = (cpId: string, decision: string, revision: number, feedback?: string) => {
		try {
			appendJournalEvent(journalPath, "checkpoint_resolved", runId, {
				checkpoint_id: cpId,
				decision,
				revision,
				...(feedback ? { feedback } : {}),
			});
		} catch {
			// best-effort
		}
	};
	/** Resolve an id the TS store never proposed (engine-minted) by adopting it from the journal. */
	const ensureCheckpoint = (cpId: string): { ok: boolean; error?: string } => {
		if (checkpointStore.get(cpId)) return { ok: true };
		const found = findCheckpointInJournal(journalPath, cpId);
		if (!found) return { ok: false, error: `no checkpoint ${cpId}` };
		checkpointStore.adopt(cpId, found.stage, `Engine checkpoint ${cpId} (${found.stage}, ${found.outputRef}). Confirm to proceed, or revise with feedback.`, { adopted: true, outputRef: found.outputRef });
		return { ok: true };
	};

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
					latestInitialiserStatement = String((res.spec as { statement_informal?: unknown }).statement_informal ?? statement);
				} catch {
					// keep previous
				}
				// Adopt the engine's checkpoint id (it already journaled checkpoint_reached) — never re-mint.
				const cp = checkpointStore.adopt(
					res.checkpoint_id,
					"initialiser",
					"Checkpoint A — structured spec + numeric kill-check. Confirm to proceed, or revise with feedback.",
					res,
				);
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
				const cp = checkpointStore.adopt(
					res.checkpoint_id,
					"literature",
					"Checkpoint B — synthesis + papers index. Confirm to proceed, or revise.",
					res,
				);
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
	// Works on TS-proposed AND engine-minted ids (adopted from the journal) — never "no checkpoint".
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
			const ensured = ensureCheckpoint(id);
			if (!ensured.ok) return { content: [{ type: "text", text: String(ensured.error) }], details: { error: ensured.error }, isError: true };
			if (dec === "confirm" || dec === "approve" || dec === "continue") {
				try {
					const rec = checkpointStore.confirm(id);
					journalResolved(id, "confirm", rec.revision);
					return { content: [{ type: "text", text: `Checkpoint ${id} confirmed — proceeding to next stage.` }], details: { checkpoint_id: id, decision: "confirm" } };
				} catch (e) { return { content: [{ type: "text", text: String(e) }], details: { error: String(e) }, isError: true }; }
			}
			if (dec === "revise" || dec === "feedback" || dec === "change") {
				const fb = String(p.feedback ?? "").trim();
				if (!fb) return { content: [{ type: "text", text: "Revise needs feedback text." }], details: {}, isError: true };
				try {
					const rec = checkpointStore.revise(id, fb);
					journalResolved(id, "revise", rec.revision, fb);
					return { content: [{ type: "text", text: `Checkpoint ${id} revised — re-presented pending (rev ${checkpointStore.get(id)?.revision}). Awaiting confirm.` }], details: { checkpoint_id: id, decision: "revise", feedback: fb } };
				} catch (e) { return { content: [{ type: "text", text: String(e) }], details: { error: String(e) }, isError: true }; }
			}
			return { content: [{ type: "text", text: `Unknown decision ${p.decision}; use confirm or revise.` }], details: {}, isError: true };
		},
	});

	// Stage 3 preset picker — after checkpoint B the agent MUST ask which preset (or custom models) to use.
	pi.registerTool({
		name: "preset_select",
		label: "Preset: select",
		description: "List computational presets (models + families + deadlock warnings). Call with no args to list, then WAIT for the human to pick one, give custom models, or name a new preset to create (save_as + custom_models). Call again to record the choice. Required after checkpoint B before spawning worktrees.",
		parameters: Type.Object({ preset: Type.Optional(Type.String({ description: "Preset name to select, e.g. diverse-5" })), custom_models: Type.Optional(Type.Array(Type.String(), { description: "Custom provider/model refs, e.g. [\"nvidia/llama-3.1-70b\"]" })), save_as: Type.Optional(Type.String({ description: "Save custom_models as a new preset under this name" })) }),
		promptGuidelines: [
			"Call preset_select with no args right after checkpoint B is confirmed, present the presets, and WAIT for the human to pick one, give custom models, or ask to create a new preset — never invent models yourself.",
			"After the human picks, call preset_select again with the preset name (or custom_models, plus save_as to create a new preset) to record it, then spawn one worktree per model.",
		],
		execute: async (_id, params) => {
			const p = params as { preset?: string; custom_models?: string[]; save_as?: string };
			let presets: Record<string, { models: string[]; families: string[]; ok: boolean; warning: string | null; note: string | null }>;
			try {
				const res = await enginePresets({ journal: journalPath, engineBin: opts.engineBin });
				if (res.status !== "ok") throw new Error(res.message);
				presets = res.presets;
			} catch (e) {
				return { content: [{ type: "text", text: `Presets unavailable: ${e}. Ask the human for custom provider/model refs instead.` }], details: { error: String(e) }, isError: true };
			}
			const planFor = (name: string, models: string[]): PiToolResult => {
				const plan = models.map((ref) => {
					const { provider, modelId } = splitModelRef(ref);
					return { provider, modelId, family: familyForRef(ref), modelRef: ref };
				});
				return { content: [{ type: "text", text: `Preset "${name}" selected (${models.length} models). Spawn one worktree per model with worktree_spawn, then post claims and track with worktree_status.\n${plan.map((m) => ` - ${m.modelRef} (provider=${m.provider} family=${m.family})`).join("\n")}` }], details: { preset: name, models, plan } };
			};
			if (typeof p.preset === "string" && p.preset.trim()) {
				const name = p.preset.trim();
				const info = presets[name];
				if (!info) return { content: [{ type: "text", text: `Unknown preset ${JSON.stringify(name)}. Available: ${Object.keys(presets).join(", ") || "(none)"}.` }], details: {}, isError: true };
				selectedPreset = { name, models: info.models };
				return planFor(name, info.models);
			}
			if (Array.isArray(p.custom_models) && p.custom_models.length > 0) {
				const models = p.custom_models.map((m) => String(m).trim()).filter((m) => m.length > 0);
				const bad = models.filter((m) => !m.includes("/"));
				if (bad.length > 0) return { content: [{ type: "text", text: `Custom models must be full provider/model refs (got ${bad.join(", ")}).` }], details: {}, isError: true };
				const saveAs = typeof p.save_as === "string" ? p.save_as.trim() : "";
				if (saveAs) {
					try {
						const saved = await enginePresetAdd(saveAs, models, { journal: journalPath, engineBin: opts.engineBin });
						if (saved.status !== "ok") throw new Error(saved.message);
						selectedPreset = { name: saveAs, models };
						const warn = saved.warning ? ` ⚠ ${saved.warning}` : "";
						const note = saved.note ? ` (${saved.note})` : "";
						return { content: [{ type: "text", text: `Preset "${saveAs}" created (${models.length} models, families: ${saved.families.join(", ") || "none"}).${warn}${note}\nSpawn one worktree per model with worktree_spawn, then post claims and track with worktree_status.\n${models.map((m) => ` - ${m}`).join("\n")}` }], details: { preset: saveAs, models, saved } };
					} catch (e) {
						return { content: [{ type: "text", text: `Could not save preset ${JSON.stringify(saveAs)}: ${e}. Using the models without saving — pass custom_models again without save_as to proceed.` }], details: { error: String(e) }, isError: true };
					}
				}
				selectedPreset = { name: "custom", models };
				return planFor("custom", models);
			}
			const names = Object.keys(presets);
			if (names.length === 0) {
				return {
					content: [{ type: "text", text: `No presets saved yet. Ask the human for custom provider/model refs (e.g. "nvidia/llama-3.1-70b"), or save one via: ramanujan-engine presets add <name> <provider/model>...` }],
					details: { presets },
				};
			}
			const lines = names.map((n) => {
				const info = presets[n];
				const fam = info.families.length ? info.families.join(", ") : "none";
				const flag = info.ok ? "" : ` ⚠ ${info.warning}`;
				const note = info.note ? ` (${info.note})` : "";
				return ` - ${n} (${info.models.length} models, families: ${fam})${flag}${note}\n   ${info.models.join(", ")}`;
			});
			return {
				content: [{ type: "text", text: `Computational presets — ask the human to pick one, or give custom provider/model refs:\n${lines.join("\n")}\n\nType the preset name or custom refs in chat — I'll record it and spawn one worktree per model.` }],
				details: { presets, selected: selectedPreset },
			};
		},
	});

	// Stage 3 worktrees — one spawn per selected preset model; track with worktree_status (no bare CLI).
	pi.registerTool({
		name: "worktree_spawn",
		label: "Worktree: spawn",
		description: "Spawn a computational worktree (one per selected preset model). Returns wt_id; track progress with worktree_status — never claim live progress you cannot see.",
		parameters: Type.Object({ provider: Type.String(), modelId: Type.String(), family: Type.String(), modelRef: Type.String() }),
		promptGuidelines: ["Spawn one worktree per selected preset model via this tool; do not run bare CLI, do not invent models outside the selected preset."],
		execute: async (_id, params) => {
			const p = params as { provider: string; modelId: string; family: string; modelRef: string };
			const res = await engineSpawnWorktree({ ...p, journal: journalPath, engineBin: opts.engineBin });
			if (!sessionWorktreeIds.includes(res.worktree_id)) sessionWorktreeIds.push(res.worktree_id);
			return { content: [{ type: "text", text: `Worktree ${res.worktree_id} spawned (${p.provider}/${p.modelId} family ${p.family}). Track it with worktree_status — work only shows up once claims are posted.` }], details: res };
		},
	});
	// Live worktree view — scoped to THIS problem session (the shared journal holds every past problem).
	pi.registerTool({
		name: "worktree_status",
		label: "Worktree: status",
		description: "Live worktree table for the current session (status → best claim → confidence + timeout defaults). Call whenever the human asks if work is done or how to see it; doubles as Checkpoint C proposal (idempotent).",
		parameters: Type.Object({}),
		promptGuidelines: [
			"Call worktree_status (no args) to show live progress; it scopes to this session's worktrees and proposes Checkpoint C once — present the card and WAIT for human confirm.",
		],
		execute: async (_id) => {
			const scope = sessionWorktreeIds.length > 0 ? sessionWorktreeIds : undefined;
			const summary = await engineCheckpointCSummary({ journal: journalPath, engineBin: opts.engineBin, worktreeIds: scope });
			const rows = summary.worktrees.map((w) => ` - ${w.worktree_id}: ${w.status} best=${w.best_claim ?? "none"} verdict=${w.verdict ?? "—"} conf=${w.confidence}`).join("\n") || " - (no worktrees yet — spawn from the selected preset first)";
			const scopedNote = scope ? `(scoped to this session: ${scope.join(", ")})` : `(no session worktrees yet — showing all; spawn from the selected preset)`;
			const defaults = summary.timeout_defaults.length > 0
				? `\nTimeout assumptions (surfaced unmissably):\n${summary.timeout_defaults.map((d) => ` - ${d.question_id}: ${d.answer}`).join("\n")}`
				: "";
			// Checkpoint C: propose once per session (idempotent — re-present while pending).
			const pendingC = checkpointStore.pending().find((c) => c.stage === "computational");
			const cp = pendingC ?? checkpointStore.propose("computational", "worktree claims table (worktree_status)", "Checkpoint C — worktree claims table. Confirm to proceed to consolidation, or revise with feedback.", summary);
			if (!pendingC) journalReached(cp.checkpointId, "computational", "worktree claims table (worktree_status)", 0);
			const body = [
				`Checkpoint ${cp.checkpointId} — Computational Stage (Worktree Claims Table) ${scopedNote}`,
				``,
				rows,
				defaults,
				``,
				`Claims carry Tier0 (+double-verified) / Tier1 / Lean results on their claim_post cards.`,
				`Do you want to confirm and continue to consolidation? Type "confirm"/"yes"/"continue" to proceed, or describe changes — I'll wait until you confirm.`,
			].join("\n");
			return { content: [{ type: "text", text: body }], details: { checkpointId: cp.checkpointId, worktrees: summary.worktrees, sessionWorktrees: sessionWorktreeIds, sessionClaims: sessionClaimIds } };
		},
	});
	pi.registerTool({
		name: "claim_post",
		label: "Claim: post",
		description: "Post a ClaimCard OBJECT from a worktree (never a JSON string); runs Tier0+Tier1+Lean inline and renders verdict. Use worktree subagent flow, not bare commands.",
		parameters: Type.Object({ worktreeId: Type.String(), card: Type.Unknown() }),
		promptGuidelines: [
			"Post claims via this tool with card as a JSON OBJECT (not a string); wait for engine Tier0 double-verification + Lean. Render the returned verdict exactly.",
		],
		execute: async (_id, params) => {
			const p = params as { worktreeId: string; card: unknown };
			// The model sometimes passes a JSON string — parse it instead of failing with a pydantic type error.
			let card: unknown = p.card;
			if (typeof card === "string") {
				try {
					card = JSON.parse(card);
				} catch {
					return { content: [{ type: "text", text: `CLAIM ERROR: card must be a ClaimCard object or valid JSON string — got unparseable text. Fix the card and retry.` }], details: { error: "unparseable card string" }, isError: true };
				}
			}
			const { mkdtempSync, writeFileSync } = await import("node:fs");
			const { tmpdir } = await import("node:os");
			const { join } = await import("node:path");
			const dir = mkdtempSync(join(tmpdir(), "ramanujan-claim-"));
			const cardFile = join(dir, "card.json");
			writeFileSync(cardFile, JSON.stringify(card));
			try {
				const res = await enginePostClaim(cardFile, { worktreeId: p.worktreeId, journal: journalPath, engineBin: opts.engineBin });
				if (!sessionClaimIds.includes(res.claim_id)) sessionClaimIds.push(res.claim_id);
				const lean = res.lean ? `\nLean ${res.lean.status}: ${res.lean.detail} (lean ${res.lean.lean_version} / ${res.lean.mathlib_version})` : "";
				return { content: [{ type: "text", text: `Claim ${res.claim_id} via ${p.worktreeId} — Tier0 ${res.tier0.verdict} verification_path=${res.verification_path}${lean}\n${JSON.stringify(res.tier1).slice(0, 400)}` }], details: res };
			} catch (e) {
				const msg = e instanceof Error ? e.message : String(e);
				return { content: [{ type: "text", text: `CLAIM ERROR (not a verdict): ${msg.slice(0, 500)}. Fix the card (ClaimCard object, valid claim_type tags) and retry — never present this as a result.` }], details: { error: msg.slice(0, 500) }, isError: true };
			}
		},
	});

	// Stage 4 consolidation + Stage 5 reviewer as tools (scoped to this session; previously only reachable via bare CLI).
	pi.registerTool({
		name: "ramanujan_consolidate",
		label: "Ramanujan: consolidate",
		description: "Stage 4 Consolidation — independent re-execution + coherence over THIS session's claims. Returns Checkpoint D and WAITS for human confirm.",
		parameters: Type.Object({}),
		promptGuidelines: [
			"Call ramanujan_consolidate after checkpoint C is confirmed, then present Checkpoint D and WAIT for human /checkpoint confirm.",
		],
		execute: async (_id) => {
			const scope = sessionWorktreeIds.length > 0 ? sessionWorktreeIds : undefined;
			const res = await engineConsolidate({ journal: journalPath, engineBin: opts.engineBin, worktreeIds: scope });
			const cpId = res.checkpoint_id ?? "";
			const cp = cpId ? checkpointStore.adopt(cpId, "consolidation", "Checkpoint D — labeled fact set. Confirm to proceed to the reviewer, or revise with feedback.", res) : checkpointStore.propose("consolidation", "consolidation/facts", "Checkpoint D — labeled fact set. Confirm to proceed to the reviewer, or revise with feedback.", res);
			if (!cpId) journalReached(cp.checkpointId, "consolidation", "consolidation/facts", 0);
			const body = [
				`Checkpoint ${cp.checkpointId} — Consolidation Stage`,
				``,
				`Facts: ${res.facts_count}, contradictions: ${res.contradictions.length}, mismatch: ${res.mismatch}${res.mismatch_details ? ` (${res.mismatch_details})` : ""}`,
				`Toolchain: ${res.toolchain_lean_version} / ${res.toolchain_mathlib_version} / ${res.model_snapshot}`,
				scope ? `Scoped to this session: ${scope.join(", ")}` : `No session worktrees — consolidated all history (scope may include earlier problems).`,
				``,
				`Do you want to confirm and continue to the reviewer? Type "confirm"/"yes"/"continue" to proceed, or describe changes — I'll wait until you confirm.`,
			].join("\n");
			return { content: [{ type: "text", text: body }], details: { checkpointId: cp.checkpointId, ...res } };
		},
	});
	pi.registerTool({
		name: "ramanujan_review",
		label: "Ramanujan: review",
		description: "Stage 5 Reviewer — plain-language summary + technical appendix over THIS session. Returns the final checkpoint and WAITS for human confirm.",
		parameters: Type.Object({}),
		promptGuidelines: [
			"Call ramanujan_review after checkpoint D is confirmed, then present the final checkpoint and WAIT for human confirm — never auto-conclude.",
		],
		execute: async (_id) => {
			const statement = latestInitialiserStatement || "problem";
			const scope = sessionWorktreeIds.length > 0 ? sessionWorktreeIds : undefined;
			const res = await engineReview(statement, { journal: journalPath, engineBin: opts.engineBin, worktreeIds: scope });
			if (res.status !== "review") {
				const reason = (res as { reason?: string }).reason ?? (res as { message?: string }).message ?? "unknown";
				return { content: [{ type: "text", text: `REVIEWER ${res.status.toUpperCase()}: ${reason}` }], details: res };
			}
			const cp = checkpointStore.adopt(res.checkpoint_id, "reviewer", "Final report — confirm to conclude, or type feedback to re-run a stage.", res);
			const body = [
				`Checkpoint ${cp.checkpointId} — Reviewer Stage (final)`,
				``,
				`${(res.report_md ?? "").slice(0, 1500)}`,
				``,
				`Report: ${res.report_path} (facts ${res.facts_count}, worktrees ${res.worktrees_count}, contradictions ${res.contradictions_count})`,
				`Confirm to conclude, or type feedback to re-run a stage — I'll wait.`,
			].join("\n");
			return { content: [{ type: "text", text: body }], details: { checkpointId: cp.checkpointId, ...res } };
		},
	});

	// System prompt + verdict reframe.
	pi.on("before_agent_start", (event) => ({ systemPrompt: appendMathPrompt(event.systemPrompt) }));
	pi.on("message_end", (event) => {
		const msg = event.message as { role: string; content: unknown };
		if (msg.role !== "assistant" || typeof msg.content !== "string") return;
		const reframed = reframeBareVerdict(msg.content);
		if (reframed !== msg.content) return { message: { ...(event.message as Record<string, unknown>), content: reframed } } as never;
	});

	// Human checkpoint command (five-stage pipeline).
	pi.registerCommand("checkpoint", {
		description: "Checkpoint gate: /checkpoint confirm <cp_id> | /checkpoint revise <cp_id> <feedback> | /checkpoint list",
		handler: async (args: string, ctx: PiCommandContext) => {
			ctx.ui.notify(await checkpointCommand(checkpointStore, args), "info");
		},
	});
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

export type { PiExtensionAPI };
