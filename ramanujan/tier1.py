"""Tier 1 lint — ramanujan/tier1.py (v2 Phase 4, cheap inline).

Obligation extraction + usage-site checking against the literature index and
the claims board. Deterministic, cheap, runs inline per worktree per claim.

This is Tier 1: not a verdict, just a lint. It never promotes a claim to
panel-verified; Tier 0 and Tier 2 (panel) do that per §2.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ramanujan.schemas import ClaimCard


class Tier1Result(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim_id: str = Field(pattern=r"^c_\d+$")
    linted: bool = True
    obligations: list[str] = Field(default_factory=list)
    missing_citations: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def lint_claim(
    card: ClaimCard,
    claim_id: str,
    *,
    papers_index: dict[str, Any] | None = None,
    folded_claims: dict[str, Any] | None = None,
) -> Tier1Result:
    """Cheap inline lint: extract obligations, check citation usage.

    Current obligations (deterministic, no LLM):
    - every claim_type tag is already validated by ClaimCard; no extra check.
    - hypotheses/conclusion must be sympy-parseable (already validated).
    - if papers_index is given, any explicit `lit_NNN` mentions in the
      informal statement are checked for existence in the index.
    """
    obligations: list[str] = []
    missing: list[str] = []
    notes: list[str] = []

    # Obligation: quantifier domains must be well-formed (already validated)
    for q in card.quantifiers:
        obligations.append(f"quantifier {q.var} : {q.domain.type}")

    # Obligation: set_vars must be declared (already validated by ClaimCard)
    if card.set_vars:
        obligations.append(f"set_vars {card.set_vars} declared")

    # Citation drift check: `lit_NNN` mentions should exist in the index.
    if papers_index is not None:
        papers = papers_index.get("papers", []) if isinstance(papers_index, dict) else []
        known_ids = {p.get("id") for p in papers if isinstance(p, dict) and p.get("id")}
        text = card.statement_informal or ""
        # Cheap scan for lit_NNN patterns.
        import re

        for lit_id in re.findall(r"lit_\d+", text):
            if lit_id not in known_ids:
                missing.append(lit_id)

    if folded_claims is not None:
        # No contradiction flagging here (Phase 5 does that cross-worktree).
        # Tier 1 just notes how many claims already exist.
        notes.append(f"board has {len(folded_claims)} folded claims")

    return Tier1Result(claim_id=claim_id, linted=True, obligations=obligations, missing_citations=missing, notes=notes)
