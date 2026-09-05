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
