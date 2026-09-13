/**
 * Typed contract for the ramanujan-engine bridge.
 * Mirrors agent/docs/bridge.md — the TS side codes against the doc.
 */

export interface ClaimCard {
	card_id: string;
	statement_informal: string;
	claim_type: string[];
	quantifiers: Array<{
		var: string;
		kind: "forall" | "exists";
		domain: { type: "int" | "real" | "finite_set_of_ints"; lo: number | null; hi: number | null };
	}>;
	hypotheses: string[];
	conclusion: { expr: string; sympy_parseable: boolean };
	set_vars: string[];
}

export type EncodeResult =
	| { status: "card"; card: ClaimCard; run_id: string; provider: string; model_id: string }
	| { status: "not_encodable"; reason: string; run_id: string; provider: string; model_id: string }
	| { status: "encoder_error"; reason: string; run_id: string; provider: string; model_id: string }
	| { status: "error"; message: string; run_id: string };

export type CheckResult =
	| {
			status: "refuted";
			run_id: string;
			counterexample: Record<string, number | number[]>;
			double_verified: true;
			budget: Record<string, number | null>;
			elapsed_sec: number;
	  }
	| {
			status: "survived";
			run_id: string;
			counterexample: null;
			double_verified: false;
			budget: Record<string, number | null>;
			elapsed_sec: number;
	  }
	| { status: "budget_exceeded"; run_id: string; budget: Record<string, number | null>; elapsed_sec: number }
	| { status: "error"; message: string; run_id: string };

export type VerifyResult =
	| { status: "counterexample_verified"; reason: string }
	| { status: "not_counterexample"; reason: string }
	| { status: "error"; message: string };

export interface ReplayEvent {
	ts: string;
	run_id: string;
	type: string;
	payload: Record<string, unknown>;
}

export type ReplayResult = { status: "ok"; events: ReplayEvent[] } | { status: "error"; message: string };

export interface ProblemSpecVariable {
	name: string;
	type: string;
	constraints: string;
}

export interface ProblemSpec {
	id: string;
	domain: string[];
	statement_informal: string;
	statement_formal: string | null;
	variables: ProblemSpecVariable[];
	objective: string;
	known_special_cases: string[];
	kill_check_config: { run_smt: boolean; run_numeric_search: boolean; small_case_limit: number };
	open_questions_for_user: string[];
}

export interface NumericKillCheck {
	status: "refuted" | "survived";
	counterexample: Record<string, number | number[]> | null;
	double_verified: boolean;
	methods: string[];
	checked_total: number;
	run_smt: boolean;
	smt_executed: boolean;
	verify_disagreement: boolean;
}

/** Stage 1 Initialiser outcome. Transport failures map to initialiser_error (never throws). */export type InitialiseResult =
	| {
			status: "spec";
			spec: ProblemSpec;
			numeric_killcheck: NumericKillCheck;
			checkpoint_id: string;
			run_id: string;
			provider: string;
			model_id: string;
	  }
	| { status: "not_initialisable"; reason: string; run_id: string; provider: string; model_id: string }
	| { status: "initialiser_error"; reason: string; run_id: string; provider: string; model_id: string }
	| { status: "error"; message: string; run_id: string };

export interface PaperEntry {
	id: string;
	title: string;
	authors: string[];
	year: number | null;
	source_url: string | null;
	provenance: string;
	relevance: string;
	note: string;
}

export interface PapersIndex {
	papers: PaperEntry[];
	synthesis: string;
}

/** Stage 2 Literature outcome. Transport failures map to literature_error (never throws). */
export type LiteratureResult =
	| {
			status: "index";
			index: PapersIndex;
			checkpoint_id: string;
			run_id: string;
			provider: string;
			model_id: string;
	  }
	| { status: "not_searchable"; reason: string; run_id: string; provider: string; model_id: string }
	| { status: "literature_error"; reason: string; run_id: string; provider: string; model_id: string }
	| { status: "error"; message: string; run_id: string };

export interface WorktreeSpawnResult {
	status: "ok";
	worktree_id: string;
	provider: string;
	model_id: string;
	family: string;
}

export interface ClaimPostTier0 {
	verdict: string;
	counterexample: Record<string, number | number[]> | null;
	double_verified: boolean;
	elapsed_sec: number | null;
}

export interface ClaimPostLean {
	status: string;
	detail: string;
	lean_version: string;
	mathlib_version: string;
	elapsed_sec: number;
}

export interface ClaimPostResult {
	status: "ok";
	claim_id: string;
	worktree_id: string;
	verification_path: string;
	tier1: { claim_id: string; linted: boolean; obligations: string[]; missing_citations: string[]; notes: string[] };
	tier0: ClaimPostTier0;
	/** Per-worktree Lean check (advisory). Absent on older engines. */
	lean?: ClaimPostLean;
}

export interface PresetInfo {
	models: string[];
	families: string[];
	ok: boolean;
	warning: string | null;
	note: string | null;
}

export type PresetsResult = { status: "ok"; presets: Record<string, PresetInfo> } | { status: "error"; message: string };

export type PresetAddResult =
	| { status: "ok"; name: string; models: string[]; families: string[]; ok: boolean; warning: string | null; note: string | null }
	| { status: "error"; message: string };

export interface QuestionPosted {
	question_id: string;
	worktree_id: string | null;
	agent_label: string;
	question: string;
	timeout_default: string;
	posted_at: string;
	timeout_sec: number;
}

export interface QuestionResult {
	status: "ok";
	question_id?: string;
	worktree_id?: string | null;
	timeout_default?: string;
	defaulted?: Array<{ question_id: string; answer: string; status: string }>;
	count?: number;
}

export interface CheckpointCSummary {
	status: "ok";
	worktrees: Array<{ worktree_id: string; status: string; best_claim: string | null; verdict: string | null; confidence: number }>;
	timeout_defaults: Array<{ question_id: string; answer: string; status: string }>;
	defaults_count: number;
}

export interface PanelRequestResult {
	status: "ok";
	claim_id: string;
	worktree_id: string;
	verification_path: "tier0" | "tier2-verdict" | "tier2-advisory-only";
	reason: string;
	panel_run_id: string;
	verdict: string;
	eligible_families: string[];
}

export interface ConsolidationResult {
	status: "ok";
	facts_count: number;
	contradictions: Array<Record<string, unknown>>;
	toolchain_lean_version: string;
	toolchain_mathlib_version: string;
	model_snapshot: string;
	mismatch: boolean;
	mismatch_details: string | null;
	checkpoint_id: string | null;
	facts: Array<Record<string, unknown>>;
}

export type ReviewResult =
	| { status: "review"; report_path: string; report: Record<string, unknown>; report_md: string; checkpoint_id: string; role_note: string; facts_count: number; worktrees_count: number; contradictions_count: number }
	| { status: "not_reviewable"; reason: string; role_note: string }
	| { status: "reviewer_error"; reason: string; role_note: string }
	| { status: "error"; message: string };

export class BridgeError extends Error {
	readonly command: string;
	readonly exitCode: number | null;
	readonly stderr: string;

	constructor(command: string, message: string, exitCode: number | null, stderr: string) {
		super(message);
		this.name = "BridgeError";
		this.command = command;
		this.exitCode = exitCode;
		this.stderr = stderr;
	}
}

export interface BridgeOptions {
	/** Engine binary. Default "ramanujan-engine" (PATH) or absolute path. */
	engineBin?: string;
	/** Default journal path for encode/check. */
	journal?: string;
	/** Per-call timeout in ms. Default 180000 encode (env RAMANUJAN_ENCODE_TIMEOUT_MS), 120000 check, 30000 verify/replay. */
	timeoutMs?: number;
	/** Extra env for the child (merged over process.env). */
	env?: NodeJS.ProcessEnv;
	/** Working directory for the child. */
	cwd?: string;
}
