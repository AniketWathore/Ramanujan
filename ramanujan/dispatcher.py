"""Dispatcher (N=1) — ramanujan/dispatcher.py (v2 Phase 4).

Minimal orchestrator for the single-worktree case: one shared JournalWriter
(session run_id), a WorktreeStore, and a claims counter. Each worktree posts
claims via `claims.post_claim` (single writer) and runs Tier 0 + Tier 1 inline,
routing `verification_path: tier0` for every claim (Tier 2 lands in Phase 7).

Every engine call stays behind the journal; no worktree appends directly.
"""

from __future__ import annotations

from typing import Any

from ramanujan.claims import fold_claims, post_claim, route_verification
from ramanujan.journal import JournalWriter
from ramanujan.schemas import ClaimCard
from ramanujan.tier1 import Tier1Result, lint_claim
from ramanujan.worktree import WorktreeStore


class Dispatcher:
    """Session dispatcher: one journal, one board, N worktrees (Phase 4: N=1)."""

    def __init__(self, journal: JournalWriter) -> None:
        self.journal = journal
        self.worktrees = WorktreeStore(journal)
        self._claim_counter = 0

    def spawn_worktree(self, provider: str, model_id: str, family: str, model_ref: str) -> dict[str, Any]:
        return self.worktrees.spawn(provider=provider, model_id=model_id, family=family, model_ref=model_ref)

    def set_worktree_status(self, worktree_id: str, status: str, reason: str | None = None) -> dict[str, Any]:
        rec = self.worktrees.set_status(worktree_id, status, reason)
        # Completion hook: every worktree has a Lean verifier; on completion
        # run it over that worktree's claims and store results (never raises,
        # never changes Tier0/Tier1).
        if status in ("completed", "panel-verified"):
            import contextlib as _ctx

            with _ctx.suppress(Exception):
                from ramanujan import lean as _lean

                _lean.verify_worktree(
                    worktree_id=worktree_id,
                    session_dir=self.journal.path.parent,
                    journal=self.journal,
                )
        return rec

    def post_and_check_claim(
        self,
        worktree_id: str,
        card: ClaimCard,
        *,
        papers_index: dict[str, Any] | None = None,
        folded_claims_for_tier1: dict[str, Any] | None = None,
        budget_usd: float | None = None,
        budget_sec: float | None = None,
    ) -> dict[str, Any]:
        """Post a claim, run Tier 0 + Tier 1 inline, route tier0, return bundle."""
        from ramanujan.killcheck.runner import killcheck_card

        if worktree_id not in {r["id"] for r in self.worktrees.list()}:
            raise KeyError(f"unknown worktree {worktree_id}")
        self._claim_counter += 1
        claim_id = f"c_{self._claim_counter:03d}"
        # Give the ClaimCard the board's claim_id (immutable once assigned).
        card.card_id = claim_id  # type: ignore[assignment]

        posted = post_claim(self.journal, claim_id=claim_id, worktree_id=worktree_id, card=card)

        # Tier 0 always, inline, deterministic.
        kill_result = killcheck_card(
            card,
            journal=self.journal,
            budget_usd=budget_usd,
            budget_sec=budget_sec,
        )
        route_verification(self.journal, claim_id=claim_id, verification_path="tier0", reason="tier0 available")

        # Tier 1 cheap lint.
        tier1: Tier1Result = lint_claim(
            card,
            claim_id,
            papers_index=papers_index,
            folded_claims=folded_claims_for_tier1,
        )

        # Lean verifier: every worktree has one; runs on each completed claim
        # and stores per-worktree results (file + lean_verified event).
        # Advisory only — never changes Tier0/Tier1, never raises.
        import contextlib as _ctx

        lean_res: dict[str, Any] = {"status": "skipped", "detail": "lean hook disabled"}
        with _ctx.suppress(Exception):
            from ramanujan import lean as _lean

            lr = _lean.verify_claim(
                card=card,
                worktree_id=worktree_id,
                claim_id=claim_id,
                session_dir=self.journal.path.parent,
                journal=self.journal,
            )
            lean_res = lr.model_dump()

        return {
            "claim_id": claim_id,
            "posted": posted,
            "kill_result": kill_result,
            "tier1": tier1.model_dump(),
            "verification_path": "tier0",
            "lean": lean_res,
        }

    def folded_board(self, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Folded latest-by-claim_id view (journal is source of truth)."""
        from ramanujan.journal import replay

        evs = events if events is not None else replay(self.journal.path)
        return fold_claims(evs)

    def folded_worktrees(self, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        from ramanujan.journal import replay

        evs = events if events is not None else replay(self.journal.path)
        return WorktreeStore.fold_worktrees(evs)
