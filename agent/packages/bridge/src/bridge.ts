/**
 * Typed spawn wrapper around `ramanujan-engine --json`.
 * Zero dependencies — only node builtins (child_process/fs/path).
 */

import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import type {
	BridgeOptions,
	CheckResult,
	CheckpointCSummary,
	ClaimPostResult,
	ConsolidationResult,
	EncodeResult,
	InitialiseResult,
	LiteratureResult,
	PanelRequestResult,
	QuestionResult,
	ReplayResult,
	ReviewResult,
	VerifyResult,
	WorktreeSpawnResult,
} from "./types.ts";
import { BridgeError } from "./types.ts";

const DEFAULT_TIMEOUTS = { encode: 180000, check: 120000, verify: 30000, replay: 30000, initialise: 180000, literature: 120000, worktree: 30000, claim: 120000, question: 30000, checkpoint: 30000, panel: 60000, consolidate: 60000, review: 120000 } as const;

export function defaultEncodeTimeoutMs(): number {
	const raw = process.env["RAMANUJAN_ENCODE_TIMEOUT_MS"];
	if (raw !== undefined) {
		const n = Number(raw);
		if (Number.isFinite(n) && n > 0) return Math.floor(n);
	}
	return DEFAULT_TIMEOUTS.encode;
}

/**
 * Resolve the engine binary without ever needing `uv` (no syncs, no installs).
 *
 * Order: explicit non-default opt > RAMANUJAN_ENGINE_BIN env >
 * `<cwd>/.venv/bin/ramanujan-engine` when present (repo-checkout TUI case) >
 * bare `ramanujan-engine` (PATH lookup). The `.venv` fallback is what makes
 * the TUI work when launched from the repo without the venv on PATH.
 */
export function resolveEngineBin(opts: BridgeOptions = {}): string {
	const opt = opts.engineBin;
	if (opt !== undefined && opt !== "ramanujan-engine") return opt;
	const envBin = process.env["RAMANUJAN_ENGINE_BIN"];
	if (envBin) return envBin;
	try {
		const local = join(process.cwd(), ".venv", "bin", "ramanujan-engine");
		if (existsSync(local)) return local;
	} catch {
		// ignore — fall through to PATH lookup
	}
	return "ramanujan-engine";
}

interface RunResult {
	stdout: string;
	stderr: string;
	exitCode: number | null;
	timedOut: boolean;
	/** Underlying spawn/exec error text (ENOENT, EACCES, …). Empty when the child ran. */
	spawnError: string;
}

function runEngine(args: string[], opts: BridgeOptions, timeoutMs: number): Promise<RunResult> {
	const bin = resolveEngineBin(opts);
	return new Promise((resolve) => {
		const child = execFile(
			bin,
			args,
			{
				timeout: timeoutMs,
				maxBuffer: 8 * 1024 * 1024,
				cwd: opts.cwd,
				env: { ...process.env, ...opts.env },
			},
			(error, stdout, stderr) => {
				if (error) {
					const e = error as NodeJS.ErrnoException & { code?: number | string; killed?: boolean; signal?: string };
					const timedOut = e.killed === true || (typeof e.signal === "string" && e.signal === "SIGTERM");
					resolve({
						stdout: String(stdout ?? ""),
						stderr: String(stderr ?? ""),
						exitCode: typeof e.code === "number" ? e.code : null,
						timedOut,
						spawnError: error.message ?? String(error),
					});
					return;
				}
				resolve({ stdout: String(stdout ?? ""), stderr: String(stderr ?? ""), exitCode: 0, timedOut: false, spawnError: "" });
			},
		);
		// execFile with timeout kills automatically; nothing more needed.
		void child;
	});
}

function parseJson(stdout: string, command: string, exitCode: number | null, stderr: string): Record<string, unknown> {
	const text = stdout.trim();
	if (!text) {
		throw new BridgeError(command, `engine produced no stdout (exit ${exitCode}): ${stderr.slice(0, 500)}`, exitCode, stderr);
	}
	// Contract: exactly one JSON object on stdout. Take the last non-empty line
	// to be tolerant of stray warnings, then require it to parse as an object.
	const lines = text.split("\n").filter((l) => l.trim().length > 0);
	const last = lines[lines.length - 1];
	try {
		const parsed: unknown = JSON.parse(last);
		if (typeof parsed !== "object" || parsed === null) {
			throw new Error("not an object");
		}
		return parsed as Record<string, unknown>;
	} catch (e) {
		throw new BridgeError(
			command,
			`engine stdout is not JSON (exit ${exitCode}): ${last.slice(0, 300)}: ${e}`,
			exitCode,
			stderr,
		);
	}
}

export async function engineEncode(statement: string, opts: BridgeOptions = {}): Promise<EncodeResult> {
	const timeoutMs = opts.timeoutMs ?? defaultEncodeTimeoutMs();
	const args = ["encode", "--statement", statement, "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	const fail = (reason: string, runId = "unknown"): EncodeResult => ({
		status: "encoder_error",
		reason,
		run_id: runId,
		provider: "unknown",
		model_id: "unknown",
	});
	let res: RunResult;
	try {
		res = await runEngine(args, opts, timeoutMs);
	} catch (e) {
		// runEngine never rejects today; belt-and-braces so encode NEVER throws.
		return fail(`engine spawn failed: ${e instanceof Error ? e.message : String(e)}`);
	}
	if (res.timedOut) {
		return fail(
			`engine encode timed out after ${timeoutMs}ms (exit ${res.exitCode})${res.spawnError ? `: ${res.spawnError}` : ""}${res.stderr ? `: ${res.stderr.slice(0, 300)}` : ""}`,
		);
	}
	let parsed: Record<string, unknown>;
	try {
		parsed = parseJson(res.stdout, "encode", res.exitCode, res.stderr);
	} catch (e) {
		const detail = e instanceof Error ? e.message : String(e);
		const spawn = res.spawnError ? ` spawn: ${res.spawnError.slice(0, 300)}` : "";
		return fail(`engine encode produced no usable JSON (exit ${res.exitCode}): ${detail}${spawn}`);
	}
	const status = parsed["status"];
	if (status === "card" || status === "not_encodable" || status === "encoder_error") {
		return parsed as unknown as EncodeResult;
	}
	if (status === "error") {
		// Spec/key/provider failure is a model/infra failure, never a DSL refusal.
		const runId = typeof parsed["run_id"] === "string" ? (parsed["run_id"] as string) : "unknown";
		const message = typeof parsed["message"] === "string" ? (parsed["message"] as string) : JSON.stringify(parsed).slice(0, 500);
		return fail(message, runId);
	}
	return fail(
		`engine encode returned unknown status ${JSON.stringify(status).slice(0, 100)} (exit ${res.exitCode}): ${JSON.stringify(parsed).slice(0, 300)}`,
		typeof parsed["run_id"] === "string" ? (parsed["run_id"] as string) : "unknown",
	);
}

export async function engineCheck(
	cardFile: string,
	opts: BridgeOptions & { budgetUsd?: number; budgetSec?: number } = {},
): Promise<CheckResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.check;
	const args = ["check", "--card-file", cardFile, "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	if (opts.budgetUsd !== undefined) args.push("--budget-usd", String(opts.budgetUsd));
	if (opts.budgetSec !== undefined) args.push("--budget-sec", String(opts.budgetSec));
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) {
		throw new BridgeError("check", `engine check timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	}
	const parsed = parseJson(res.stdout, "check", res.exitCode, res.stderr);
	if (res.exitCode !== 0 && parsed["status"] !== "error") {
		throw new BridgeError("check", `engine check failed (exit ${res.exitCode}): ${res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	}
	const status = parsed["status"];
	if (status !== "refuted" && status !== "survived" && status !== "budget_exceeded" && status !== "error") {
		throw new BridgeError("check", `engine check returned unknown status: ${String(status)}`, res.exitCode, res.stderr);
	}
	return parsed as unknown as CheckResult;
}

/**
 * Stage 1 Initialiser: statement → ProblemSpec + numeric-only kill-check.
 * Same never-throw guarantee as engineEncode: transport failures, timeouts,
 * and engine `error` statuses all return `initialiser_error` with the reason.
 */
export async function engineInitialise(statement: string, opts: BridgeOptions = {}): Promise<InitialiseResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.initialise;
	const args = ["initialise", "--statement", statement, "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	const fail = (reason: string, runId = "unknown"): InitialiseResult => ({
		status: "initialiser_error",
		reason,
		run_id: runId,
		provider: "unknown",
		model_id: "unknown",
	});
	let res: RunResult;
	try {
		res = await runEngine(args, opts, timeoutMs);
	} catch (e) {
		return fail(`engine spawn failed: ${e instanceof Error ? e.message : String(e)}`);
	}
	if (res.timedOut) {
		return fail(
			`engine initialise timed out after ${timeoutMs}ms (exit ${res.exitCode})${res.spawnError ? `: ${res.spawnError}` : ""}${res.stderr ? `: ${res.stderr.slice(0, 300)}` : ""}`,
		);
	}
	let parsed: Record<string, unknown>;
	try {
		parsed = parseJson(res.stdout, "initialise", res.exitCode, res.stderr);
	} catch (e) {
		const detail = e instanceof Error ? e.message : String(e);
		const spawn = res.spawnError ? ` spawn: ${res.spawnError.slice(0, 300)}` : "";
		return fail(`engine initialise produced no usable JSON (exit ${res.exitCode}): ${detail}${spawn}`);
	}
	const status = parsed["status"];
	if (status === "spec" || status === "not_initialisable" || status === "initialiser_error") {
		return parsed as unknown as InitialiseResult;
	}
	if (status === "error") {
		const runId = typeof parsed["run_id"] === "string" ? (parsed["run_id"] as string) : "unknown";
		const message = typeof parsed["message"] === "string" ? (parsed["message"] as string) : JSON.stringify(parsed).slice(0, 500);
		return fail(message, runId);
	}
	return fail(
		`engine initialise returned unknown status ${JSON.stringify(status).slice(0, 100)} (exit ${res.exitCode}): ${JSON.stringify(parsed).slice(0, 300)}`,
		typeof parsed["run_id"] === "string" ? (parsed["run_id"] as string) : "unknown",
	);
}

export async function engineVerify(
	cardFile: string,
	assignment: Record<string, number | number[]>,
	opts: BridgeOptions = {},
): Promise<VerifyResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.verify;
	const args = ["verify", "--card-file", cardFile, "--assignment", JSON.stringify(assignment), "--json"];
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) {
		throw new BridgeError("verify", `engine verify timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	}
	const parsed = parseJson(res.stdout, "verify", res.exitCode, res.stderr);
	if (res.exitCode !== 0 && parsed["status"] !== "error") {
		throw new BridgeError("verify", `engine verify failed (exit ${res.exitCode}): ${res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	}
	return parsed as unknown as VerifyResult;
}

export async function engineReplay(journal: string, opts: BridgeOptions = {}): Promise<ReplayResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.replay;
	const args = ["replay", "--journal", journal, "--json"];
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) {
		throw new BridgeError("replay", `engine replay timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	}
	const parsed = parseJson(res.stdout, "replay", res.exitCode, res.stderr);
	return parsed as unknown as ReplayResult;
}

export type LiteratureBridgeOptions = BridgeOptions & { specFile?: string; outDir?: string };

/**
 * Stage 2 Literature: statement → papers index + synthesis.
 * Same never-throw guarantee as engineInitialise/Encode: transport failures,
 * timeouts, and engine `error` statuses all return `literature_error` with the reason.
 */
export async function engineLiterature(statement: string, opts: LiteratureBridgeOptions = {}): Promise<LiteratureResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.literature;
	const args = ["literature", "--statement", statement, "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	if (opts.specFile) args.push("--spec-file", opts.specFile);
	if (opts.outDir) args.push("--out-dir", opts.outDir);
	const fail = (reason: string, runId = "unknown"): LiteratureResult => ({
		status: "literature_error",
		reason,
		run_id: runId,
		provider: "unknown",
		model_id: "unknown",
	});
	let res: RunResult;
	try {
		res = await runEngine(args, opts, timeoutMs);
	} catch (e) {
		return fail(`engine spawn failed: ${e instanceof Error ? e.message : String(e)}`);
	}
	if (res.timedOut) {
		return fail(
			`engine literature timed out after ${timeoutMs}ms (exit ${res.exitCode})${res.spawnError ? `: ${res.spawnError}` : ""}${res.stderr ? `: ${res.stderr.slice(0, 300)}` : ""}`,
		);
	}
	let parsed: Record<string, unknown>;
	try {
		parsed = parseJson(res.stdout, "literature", res.exitCode, res.stderr);
	} catch (e) {
		const detail = e instanceof Error ? e.message : String(e);
		const spawn = res.spawnError ? ` spawn: ${res.spawnError.slice(0, 300)}` : "";
		return fail(`engine literature produced no usable JSON (exit ${res.exitCode}): ${detail}${spawn}`);
	}
	const status = parsed["status"];
	if (status === "index" || status === "not_searchable" || status === "literature_error") {
		return parsed as unknown as LiteratureResult;
	}
	if (status === "error") {
		const runId = typeof parsed["run_id"] === "string" ? (parsed["run_id"] as string) : "unknown";
		const message = typeof parsed["message"] === "string" ? (parsed["message"] as string) : JSON.stringify(parsed).slice(0, 500);
		return fail(message, runId);
	}
	return fail(
		`engine literature returned unknown status ${JSON.stringify(status).slice(0, 100)} (exit ${res.exitCode}): ${JSON.stringify(parsed).slice(0, 300)}`,
		typeof parsed["run_id"] === "string" ? (parsed["run_id"] as string) : "unknown",
	);
}

export async function engineSpawnWorktree(
	opts: BridgeOptions & { provider: string; modelId: string; family: string; modelRef: string },
): Promise<WorktreeSpawnResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.worktree;
	const args = ["worktree", "spawn", "--provider", opts.provider, "--model-id", opts.modelId, "--family", opts.family, "--model-ref", opts.modelRef, "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) throw new BridgeError("worktree spawn", `engine worktree spawn timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	const parsed = parseJson(res.stdout, "worktree spawn", res.exitCode, res.stderr);
	if (res.exitCode !== 0) throw new BridgeError("worktree spawn", `engine worktree spawn failed (exit ${res.exitCode}): ${parsed["message"] ?? res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	if (parsed["status"] !== "ok") throw new BridgeError("worktree spawn", `unexpected status: ${String(parsed["status"])}`, res.exitCode, res.stderr);
	return parsed as unknown as WorktreeSpawnResult;
}

export async function enginePostClaim(
	cardFile: string,
	opts: BridgeOptions & { worktreeId: string; papersIndexFile?: string },
): Promise<ClaimPostResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.claim;
	const args = ["claim", "post", "--worktree-id", opts.worktreeId, "--card-file", cardFile, "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	if (opts.papersIndexFile) args.push("--papers-index", opts.papersIndexFile);
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) throw new BridgeError("claim post", `engine claim post timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	const parsed = parseJson(res.stdout, "claim post", res.exitCode, res.stderr);
	if (res.exitCode !== 0) throw new BridgeError("claim post", `engine claim post failed (exit ${res.exitCode}): ${parsed["message"] ?? res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	if (parsed["status"] !== "ok") throw new BridgeError("claim post", `unexpected status: ${String(parsed["status"])}`, res.exitCode, res.stderr);
	return parsed as unknown as ClaimPostResult;
}

export async function enginePostQuestion(
	question: string,
	timeoutDefault: string,
	opts: BridgeOptions & { worktreeId?: string | null; agentLabel?: string; timeoutSec?: number; sessionDir?: string },
): Promise<QuestionResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.question;
	const args = ["question", "post", "--question", question, "--timeout-default", timeoutDefault, "--json"];
	if (opts.worktreeId) args.push("--worktree-id", opts.worktreeId);
	if (opts.agentLabel) args.push("--agent-label", opts.agentLabel);
	if (opts.timeoutSec !== undefined) args.push("--timeout-sec", String(opts.timeoutSec));
	if (opts.journal) args.push("--journal", opts.journal);
	if (opts.sessionDir) args.push("--session-dir", opts.sessionDir);
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) throw new BridgeError("question post", `engine question post timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	const parsed = parseJson(res.stdout, "question post", res.exitCode, res.stderr);
	if (res.exitCode !== 0) throw new BridgeError("question post", `engine question post failed (exit ${res.exitCode}): ${parsed["message"] ?? res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	return parsed as unknown as QuestionResult;
}

export async function engineCheckQuestionTimeouts(opts: BridgeOptions & { sessionDir?: string } = {}): Promise<QuestionResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.question;
	const args = ["question", "check-timeouts", "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	if (opts.sessionDir) args.push("--session-dir", opts.sessionDir);
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) throw new BridgeError("question check-timeouts", `engine timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	const parsed = parseJson(res.stdout, "question check-timeouts", res.exitCode, res.stderr);
	if (res.exitCode !== 0) throw new BridgeError("question check-timeouts", `engine failed (exit ${res.exitCode}): ${parsed["message"] ?? res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	return parsed as unknown as QuestionResult;
}

export async function engineCheckpointCSummary(opts: BridgeOptions & { sessionDir?: string } = {}): Promise<CheckpointCSummary> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.checkpoint;
	const args = ["checkpoint", "c-summary", "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	if (opts.sessionDir) args.push("--session-dir", opts.sessionDir);
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) throw new BridgeError("checkpoint c-summary", `engine timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	const parsed = parseJson(res.stdout, "checkpoint c-summary", res.exitCode, res.stderr);
	if (res.exitCode !== 0) throw new BridgeError("checkpoint c-summary", `engine failed (exit ${res.exitCode}): ${parsed["message"] ?? res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	return parsed as unknown as CheckpointCSummary;
}

export async function engineRequestPanel(
	cardFile: string,
	opts: BridgeOptions & { claimId: string; worktreeId: string; preset?: string; modelRefs?: string[] },
): Promise<PanelRequestResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.panel;
	const args = ["orchestrator", "request-panel", "--claim-id", opts.claimId, "--worktree-id", opts.worktreeId, "--card-file", cardFile, "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	if (opts.preset) args.push("--preset", opts.preset);
	if (opts.modelRefs) for (const m of opts.modelRefs) args.push("--model-ref", m);
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) throw new BridgeError("panel request", `engine timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	const parsed = parseJson(res.stdout, "panel request", res.exitCode, res.stderr);
	if (res.exitCode !== 0) throw new BridgeError("panel request", `engine failed (exit ${res.exitCode}): ${parsed["message"] ?? res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	return parsed as unknown as PanelRequestResult;
}

export async function engineConsolidate(opts: BridgeOptions & { sessionDir?: string; leanVersion?: string; mathlibVersion?: string; modelSnapshot?: string }): Promise<ConsolidationResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.consolidate;
	const args = ["consolidate", "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	if (opts.sessionDir) args.push("--session-dir", opts.sessionDir);
	if (opts.leanVersion) args.push("--lean-version", opts.leanVersion);
	if (opts.mathlibVersion) args.push("--mathlib-version", opts.mathlibVersion);
	if (opts.modelSnapshot) args.push("--model-snapshot", opts.modelSnapshot);
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) throw new BridgeError("consolidate", `engine timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	const parsed = parseJson(res.stdout, "consolidate", res.exitCode, res.stderr);
	if (res.exitCode !== 0) throw new BridgeError("consolidate", `engine failed (exit ${res.exitCode}): ${parsed["message"] ?? res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	return parsed as unknown as ConsolidationResult;
}

export async function engineReview(
	statement: string,
	opts: BridgeOptions & { sessionDir?: string; outFile?: string },
): Promise<ReviewResult> {
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUTS.review;
	const args = ["review", "--statement", statement, "--json"];
	if (opts.journal) args.push("--journal", opts.journal);
	if (opts.sessionDir) args.push("--session-dir", opts.sessionDir);
	if (opts.outFile) args.push("--out-file", opts.outFile);
	const res = await runEngine(args, opts, timeoutMs);
	if (res.timedOut) throw new BridgeError("review", `engine timed out after ${timeoutMs}ms`, res.exitCode, res.stderr);
	const parsed = parseJson(res.stdout, "review", res.exitCode, res.stderr);
	if (parsed["status"] === "review" || parsed["status"] === "not_reviewable" || parsed["status"] === "reviewer_error") {
		return parsed as unknown as ReviewResult;
	}
	if (parsed["status"] === "error") throw new BridgeError("review", `engine review failed (exit ${res.exitCode}): ${parsed["message"] ?? res.stderr.slice(0, 500)}`, res.exitCode, res.stderr);
	throw new BridgeError("review", `engine review returned unknown status: ${String(parsed["status"])}`, res.exitCode, res.stderr);
}
