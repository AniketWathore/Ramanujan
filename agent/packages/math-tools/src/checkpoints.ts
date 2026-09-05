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
