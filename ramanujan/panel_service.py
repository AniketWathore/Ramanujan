"""Tier-2 panel service — ramanujan/panel_service.py (v2 Phase 7).

Authority model (§2): Tier 0 remains authoritative wherever a deterministic
check applies. The cross-provider panel gains verdict-granting power only
where Tier 0 has NO applicable deterministic check — and only using providers
from a different family than the calling worktree (family_registry).

Every claim gets an explicit, recorded routing decision
`verification_path: tier0 | tier2-verdict | tier2-advisory-only` (never
implicit). A claim that could be Tier0-checked but wasn't yet attempted must
never fall through to panel-verdict.

This module is the Python engine's view of the panel (deterministic, testable
without live LLM calls). The TS `panel.ts` sealed→reveal mechanic stays as
built; its authority check must mirror this logic (different-family + Tier0
inapplicability) — the tests enforce the contract from both sides.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

from ramanujan.families import DEFAULT_REGISTRY_PATH, load_registry, preset_families, validate_preset
from ramanujan.journal import JournalWriter, replay
from ramanujan.schemas import ClaimCard

# ------------------------------------------------------------------ Tier0 applicability


TIER0_SUPPORTED_TYPES: set[str] = {
    "inequality-estimate",
    "algebraic-identity",
    "combinatorial-construction",
    "quantifier-scope",
    "induction-recursion",
    # statement-equivalence / generalization / convergence-limit / compactness / code
    # are outside the decidable numeric/SMT fragment — panel-verdict territory.
}


def is_tier0_applicable(card: ClaimCard) -> bool:
    """True if Tier 0 has a deterministic check for this claim."""
    # Real variables are outside the current numeric/SMT fragment.
    for q in card.quantifiers:
        if q.domain.type == "real":
            return False
    # Empty quantifiers or unsupported claim types are not Tier0-checkable.
    if not card.claim_type:
        return False
    # If every tag is in the Tier0-supported set, we have a check.
    return all(tag in TIER0_SUPPORTED_TYPES for tag in card.claim_type)


def has_tier0_been_attempted(claim_id: str, journal: JournalWriter) -> bool:
    """True if a claim_verification_routed: tier0 already exists for claim_id."""
    try:
        evs = replay(journal.path)
    except Exception:
        return False
    for ev in evs:
        if ev["type"] == "claim_verification_routed" and ev["payload"].get("claim_id") == claim_id:
            if ev["payload"].get("verification_path") == "tier0":
                return True
        # Also consider the dispatcher Tier0 run wrote `check_executed` for the card's run?
        # For Phase 7, the presence of a tier0 routing is enough.
    return False


# ------------------------------------------------------------------ Routing decision


def route_for_claim(
    card: ClaimCard,
    claim_id: str,
    caller_family: str,
    preset_models: list[str],
    journal: JournalWriter,
    registry_path: str | None = None,
) -> tuple[str, str]:
    """Return (verification_path, reason) per §2 authority rule.

    Explicit, recorded decision — never implicit.
    """
    reg = load_registry(registry_path or DEFAULT_REGISTRY_PATH)
    preset_check = validate_preset("tmp", preset_models, reg)
    eligible = preset_families(preset_models, reg) - {caller_family}
    # Remove unknown bucket from eligible count — it cannot prove independence.
    eligible.discard("family:unknown")

    applicable = is_tier0_applicable(card)
    attempted = has_tier0_been_attempted(claim_id, journal)

    if applicable:
        if not attempted:
            return "tier0", "Tier0 applicable but not yet attempted — run Tier0 first (panel cannot grant verdict by default)"
        # Tier0 applicable and already attempted → panel may only advise
        return "tier2-advisory-only", "Tier0 has applicable deterministic check — panel advisory-only (Tier0 remains authoritative)"
    # Tier0 not applicable
    if not preset_check.ok or not eligible:
        return "tier2-advisory-only", "Tier0 not applicable but preset deadlocked (fewer than 2 distinct families or no eligible panel family) — advisory-only"
    if len(eligible) == 0:
        return "tier2-advisory-only", "No eligible panel family different from caller — advisory-only"
    return "tier2-verdict", "Tier0 not applicable and eligible cross-family panel available — panel-verdict"


# ------------------------------------------------------------------ Mock panel run (deterministic, no LLM)


def _mock_panel_run(card: ClaimCard, panel_families: list[str]) -> dict[str, Any]:
    """Deterministic mock panel (no network) — produces sealed→reveal shape.

    For TIER0_NOT_APPLICABLE claims we simulate support; for others doubt.
    The candidate funnel is irrelevant here — panel-verdict in this mock is
    based solely on routing, not on engine-verified candidates.
    """
    panel_run_id = f"panel_{uuid.uuid4().hex[:8]}"
    # Simple deterministic tally: if Tier0 not applicable, support; else advisory doubt
    applicable = is_tier0_applicable(card)
    if not applicable:
        tally = {"support": len(panel_families), "doubt": 0, "object": 0}
        advisory = f"panel: {tally['support']} support / 0 doubt / 0 object — Tier0 not applicable, cross-family panel grants panel-verified."
    else:
        tally = {"support": 0, "doubt": len(panel_families), "object": 0}
        advisory = "panel: advisory-only — Tier0 remains authoritative."
    return {"panel_run_id": panel_run_id, "tally": tally, "advisory": advisory, "panel_families": panel_families}


def request_panel_for_claim(
    claim_id: str,
    worktree_id: str,
    card: ClaimCard,
    caller_family: str,
    preset_models: list[str],
    journal: JournalWriter,
    registry_path: str | None = None,
) -> dict[str, Any]:
    """On-demand Tier-2 panel (mock, shared service). Records routing + panel verdict.

    Returns dict with verification_path, panel_run_id, etc., and writes
    claim_verification_routed + panel_verdict_issued (single writer).
    Never writes claim_refuted — panel NEVER has that power (spine probe).
    """
    verification_path, reason = route_for_claim(card, claim_id, caller_family, preset_models, journal, registry_path)
    # Journal the routing decision (explicit, recorded per §2)
    journal.write(
        "claim_verification_routed",
        {"claim_id": claim_id, "verification_path": verification_path, "reason": reason},
    )
    # Determine eligible families for the panel run
    reg = load_registry(registry_path or DEFAULT_REGISTRY_PATH)
    eligible = sorted(preset_families(preset_models, reg) - {caller_family} - {"family:unknown"})

    verdict = "advisory-only"
    panel_run_id = f"panel_{uuid.uuid4().hex[:8]}"
    if verification_path == "tier2-verdict":
        # Mock panel execution (deterministic)
        mock = _mock_panel_run(card, eligible)
        panel_run_id = mock["panel_run_id"]
        verdict = "panel-verified"
        # Also journal mock positions/advisory for replay validation (optional, but keep minimal)
        # We emit a synthetic panel_advisory for the run so replay sees at least one.
        with contextlib.suppress(Exception):
            journal.write(
                "panel_advisory",
                {
                    "panel_run_id": panel_run_id,
                    "support": mock["tally"]["support"],
                    "doubt": mock["tally"]["doubt"],
                    "object": mock["tally"]["object"],
                    "advisory": mock["advisory"],
                },
            )
        # Record the verdict
        journal.write(
            "panel_verdict_issued",
            {
                "claim_id": claim_id,
                "panel_run_id": panel_run_id,
                "verification_path": verification_path,
                "worktree_id": worktree_id,
                "caller_family": caller_family,
                "panel_families": eligible,
                "verdict": verdict,
            },
        )
    elif verification_path == "tier2-advisory-only":
        # Advisory path: still record but verdict is advisory-only
        journal.write(
            "panel_verdict_issued",
            {
                "claim_id": claim_id,
                "panel_run_id": panel_run_id,
                "verification_path": verification_path,
                "worktree_id": worktree_id,
                "caller_family": caller_family,
                "panel_families": eligible,
                "verdict": verdict,
            },
        )
    else:
        # tier0 path — no panel verdict (Tier0 will be run by dispatcher)
        journal.write(
            "panel_verdict_issued",
            {
                "claim_id": claim_id,
                "panel_run_id": panel_run_id,
                "verification_path": verification_path,
                "worktree_id": worktree_id,
                "caller_family": caller_family,
                "panel_families": eligible,
                "verdict": "tier0-routed",
            },
        )

    return {
        "claim_id": claim_id,
        "worktree_id": worktree_id,
        "verification_path": verification_path,
        "reason": reason,
        "panel_run_id": panel_run_id,
        "verdict": verdict,
        "eligible_families": eligible,
    }
