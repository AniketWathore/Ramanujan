"""Claims board — ramanujan/claims.py (v2 Phase 4).

The board is NOT a separate file. Every write goes through `journal.py`
(single writer) as a `claim_posted` event (immutable claim_id). Later events
(strengthened / refuted / superseded) are NEW entries with the same claim_id;
readers fold to the latest entry per claim_id.

This module provides the writer helper and the pure fold function used by
orchestrator, consolidation, tests, and CLI -- all via the journal.
"""

from __future__ import annotations

from typing import Any

from ramanujan.schemas import ClaimCard, ClaimPostedPayload, ClaimVerificationRoutedPayload


def post_claim(
    journal: Any,
    claim_id: str,
    worktree_id: str,
    card: ClaimCard,
) -> dict[str, Any]:
    """Write one claim_posted event via the single journal writer."""
    payload = ClaimPostedPayload(
        claim_id=claim_id,
        worktree_id=worktree_id,
        statement_informal=card.statement_informal,
        claim_type=list(card.claim_type),
        card=card.model_dump(),
    )
    return journal.write("claim_posted", payload.model_dump())  # type: ignore[arg-type]


def route_verification(
    journal: Any,
    claim_id: str,
    verification_path: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Record the §2 authority routing decision for a claim."""
    payload = ClaimVerificationRoutedPayload(
        claim_id=claim_id,
        verification_path=verification_path,  # type: ignore[arg-type]
        reason=reason,
    )
    return journal.write("claim_verification_routed", payload.model_dump())  # type: ignore[arg-type]


def fold_claims(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold journal events to latest payload per claim_id."""
    latest: dict[str, dict[str, Any]] = {}
    routed: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev.get("type") == "claim_posted":
            cid = ev["payload"].get("claim_id")
            if cid:
                latest[cid] = dict(ev["payload"])
        elif ev.get("type") == "claim_verification_routed":
            cid = ev["payload"].get("claim_id")
            if cid:
                routed[cid] = dict(ev["payload"])
    # Attach routing to the claim view (does not overwrite card)
    for cid, r in routed.items():
        if cid in latest:
            latest[cid]["verification_path"] = r.get("verification_path")
            if r.get("reason"):
                latest[cid]["verification_reason"] = r.get("reason")
        else:
            # Routed before posted (should not happen) -- keep a stub
            latest[cid] = {"claim_id": cid, "verification_path": r.get("verification_path")}
    return latest
