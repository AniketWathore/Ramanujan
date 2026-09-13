/**
 * Reusable human checkpoint — the ONE confirm/revise abstraction for all
 * five stages (Build Brief §1). Content differs per stage (spec / lit
 * summary / worktree table / fact set / report); the contract is identical:
 *
 * propose (agent) → confirm | revise(feedback) (HUMAN path only).
 * revise loops: feedback is recorded, revision bumps, the SAME checkpoint
 * is re-presented until confirmed. Stop is a separate global action, never
 * a checkpoint option — so it never appears here.
 *
 * Like PendingCardStore, no confirm/revise tool is ever registered for the
 * LLM: the model cannot resolve a checkpoint itself.
 */

import { existsSync, readFileSync } from "node:fs";

export type CheckpointStatus = "pending" | "confirmed";

export const CHECKPOINT_OPTIONS = ["confirm", "revise"] as const;

export interface Checkpoint<TContent> {
	checkpointId: string;
	stage: string;
	outputRef: string;
	prompt: string;
	options: readonly ["confirm", "revise"];
	content: TContent;
	status: CheckpointStatus;
	revision: number;
	feedback: string[];
	proposedAt: number;
	decidedAt?: number;
}

export class CheckpointStore<TContent> {
	private records = new Map<string, Checkpoint<TContent>>();
	private counter = 0;

	propose(stage: string, outputRef: string, prompt: string, content: TContent): Checkpoint<TContent> {
		this.counter += 1;
		const checkpointId = `cp_${String(this.counter).padStart(3, "0")}`;
		const record: Checkpoint<TContent> = {
			checkpointId,
			stage,
			outputRef,
			prompt,
			options: CHECKPOINT_OPTIONS,
			content,
			status: "pending",
			revision: 0,
			feedback: [],
			proposedAt: Date.now(),
		};
		this.records.set(checkpointId, record);
		return record;
	}

	/**
	 * Adopt an engine-minted checkpoint (e.g. cp_004 from `consolidate`)
	 * so confirm/revise works on it. The engine and the TS store share one
	 * id sequence; adoption keeps them in sync instead of erroring with
	 * "no checkpoint cp_NNN".
	 */
	adopt(checkpointId: string, stage: string, prompt: string, content: TContent): Checkpoint<TContent> {
		const existing = this.records.get(checkpointId);
		if (existing) return existing;
		const n = Number(checkpointId.split("_")[1]);
		if (Number.isFinite(n) && n > this.counter) this.counter = Math.floor(n);
		const record: Checkpoint<TContent> = {
			checkpointId,
			stage,
			outputRef: "engine",
			prompt,
			options: CHECKPOINT_OPTIONS,
			content,
			status: "pending",
			revision: 0,
			feedback: [],
			proposedAt: Date.now(),
		};
		this.records.set(checkpointId, record);
		return record;
	}

	/**
	 * Align the counter with the shared journal's max cp_NNN (best-effort,
	 * sync read). Without this a fresh TUI process re-mints cp_001 and
	 * collides with earlier stages.
	 */
	rehydrateFromJournal(journalPath: string): void {
		try {
			if (!existsSync(journalPath)) return;
			const text = readFileSync(journalPath, "utf-8");
			let mx = this.counter;
			for (const line of text.split("\n")) {
				const m = /"checkpoint_id"\s*:\s*"cp_(\d+)"/.exec(line);
				if (m) {
					const n = Number(m[1]);
					if (Number.isFinite(n) && n > mx) mx = Math.floor(n);
				}
			}
			this.counter = mx;
		} catch {
			// best-effort only — a missed rehydrate just risks an id collision
		}
	}

	/** Human path: confirm the checkpoint as presented. */
	confirm(checkpointId: string): Checkpoint<TContent> {
		const record = this.pendingRecord(checkpointId);
		record.status = "confirmed";
		record.decidedAt = Date.now();
		return record;
	}

	/** Human path: free-text feedback; the SAME checkpoint is re-presented pending. */
	revise(checkpointId: string, feedback: string): Checkpoint<TContent> {
		const record = this.pendingRecord(checkpointId);
		record.feedback.push(feedback);
		record.revision += 1;
		return record;
	}

	get(checkpointId: string): Checkpoint<TContent> | undefined {
		return this.records.get(checkpointId);
	}

	pending(): Checkpoint<TContent>[] {
		return [...this.records.values()].filter((r) => r.status === "pending");
	}

	private pendingRecord(checkpointId: string): Checkpoint<TContent> {
		const record = this.records.get(checkpointId);
		if (!record) throw new Error(`no checkpoint ${checkpointId}`);
		if (record.status !== "pending") throw new Error(`checkpoint ${checkpointId} already ${record.status}`);
		return record;
	}
}

/**
 * Look up an engine-minted checkpoint in the shared journal (best-effort).
 * Returns stage + output ref when the journal has a `checkpoint_reached`
 * for the id, else undefined.
 */
export function findCheckpointInJournal(journalPath: string, checkpointId: string): { stage: string; outputRef: string; revision: number } | undefined {
	try {
		if (!existsSync(journalPath)) return undefined;
		const text = readFileSync(journalPath, "utf-8");
		let found: { stage: string; outputRef: string; revision: number } | undefined;
		for (const line of text.split("\n")) {
			if (!line.includes(checkpointId)) continue;
			let ev: { type?: unknown; payload?: Record<string, unknown> };
			try {
				ev = JSON.parse(line) as typeof ev;
			} catch {
				continue;
			}
			if (ev.type !== "checkpoint_reached") continue;
			const p = ev.payload ?? {};
			if (p["checkpoint_id"] !== checkpointId) continue;
			found = {
				stage: typeof p["stage"] === "string" ? (p["stage"] as string) : "engine",
				outputRef: typeof p["output_ref"] === "string" ? (p["output_ref"] as string) : "engine",
				revision: typeof p["revision"] === "number" ? (p["revision"] as number) : 0,
			};
		}
		return found;
	} catch {
		return undefined;
	}
}
