/**
 * Pending card store — the human confirmation gate.
 *
 * propose (tool) → confirm|edit|reject (HUMAN slash-command path only).
 * killcheck_run refuses anything not human-confirmed. The model cannot
 * self-confirm: no confirm/edit/reject tool is ever registered for the LLM.
 */

import type { ClaimCard } from "@ramanujan/bridge";

export type CardStatus = "pending" | "confirmed" | "rejected";

export interface PendingCard {
	cardId: string;
	card: ClaimCard;
	status: CardStatus;
	proposedAt: number;
	decidedAt?: number;
	/** Last killcheck summary for this card (used as panel input). */
	lastSummary?: string;
}

export class PendingCardStore {
	private cards = new Map<string, PendingCard>();

	propose(card: ClaimCard): PendingCard {
		const entry: PendingCard = { cardId: card.card_id, card, status: "pending", proposedAt: Date.now() };
		this.cards.set(card.card_id, entry);
		return entry;
	}

	/** Human path: confirm the pending card as-is. */
	confirm(cardId: string): PendingCard {
		const entry = this.cards.get(cardId);
		if (!entry) throw new Error(`no pending card ${cardId}`);
		if (entry.status !== "pending") throw new Error(`card ${cardId} already ${entry.status}`);
		entry.status = "confirmed";
		entry.decidedAt = Date.now();
		return entry;
	}

	/** Human path: replace the pending card with an edited one (re-validated by caller via bridge). */
	edit(card: ClaimCard): PendingCard {
		const entry = this.cards.get(card.card_id);
		if (!entry) throw new Error(`no pending card ${card.card_id}`);
		if (entry.status !== "pending") throw new Error(`card ${card.card_id} already ${entry.status}`);
		entry.card = card;
		entry.status = "confirmed";
		entry.decidedAt = Date.now();
		return entry;
	}

	/** Human path: reject — nothing will ever run for this card. */
	reject(cardId: string): PendingCard {
		const entry = this.cards.get(cardId);
		if (!entry) throw new Error(`no pending card ${cardId}`);
		entry.status = "rejected";
		entry.decidedAt = Date.now();
		return entry;
	}

	get(cardId: string): PendingCard | undefined {
		return this.cards.get(cardId);
	}

	/** Record the last killcheck summary (panel input, not a verdict). */
	recordSummary(cardId: string, summary: string): void {
		const entry = this.cards.get(cardId);
		if (entry) entry.lastSummary = summary;
	}

	/** Gate predicate used by killcheck_run AND the tool_call hook. */
	isConfirmed(cardId: string): boolean {
		return this.cards.get(cardId)?.status === "confirmed";
	}

	pending(): PendingCard[] {
		return [...this.cards.values()].filter((c) => c.status === "pending");
	}

	confirmed(): PendingCard[] {
		return [...this.cards.values()].filter((c) => c.status === "confirmed");
	}

	/**
	 * Card selection for review commands (/panel): explicit id first, then
	 * the first pending card, then the most recently decided confirmed card
	 * (a confirmed card is reviewable — pending-only lookup wrongly reported
	 * "No pending card" right after a confirm). Undefined when truly empty.
	 */
	reviewable(cardId?: string): PendingCard | undefined {
		if (cardId) return this.cards.get(cardId);
		const pend = this.pending();
		if (pend.length > 0) return pend[0];
		const conf = this.confirmed();
		return conf.length > 0 ? conf[conf.length - 1] : undefined;
	}
}
