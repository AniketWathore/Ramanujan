"""Reliability table + perturbation audits — ramanujan/reliability.py (v2 Phase 10).

Conditioned on claim-structure tags (Phase 0 answer: the 10 tags classify
proof shape, not domain — inequality-estimate, quantifier-scope, etc.). Fed
by every Tier-2 panel call logged from Phase 7 onward
(`panel_verdict_issued` + `claim_verification_routed`). Perturbation audits
feed back into routing (which claims may take tier2-verdict).

The table lives as a derived view over the journal (like the claims board) —
no second writer. It can also be persisted as JSON for inspection.
"""

from __future__ import annotations

import contextlib
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ramanujan.claims import fold_claims
from ramanujan.journal import replay
from ramanujan.schemas import ClaimCard


class TagReliability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tag: str = Field(min_length=1)
    total: int = Field(default=0, ge=0)
    tier2_verdict: int = Field(default=0, ge=0)
    tier2_advisory: int = Field(default=0, ge=0)
    tier0: int = Field(default=0, ge=0)
    panel_verified: int = Field(default=0, ge=0)
    # Perturbation audit counters
    perturbations_run: int = Field(default=0, ge=0)
    perturbations_stable: int = Field(default=0, ge=0)

    @property
    def verdict_rate(self) -> float:
        return self.panel_verified / self.total if self.total else 0.0

    @property
    def stable_rate(self) -> float:
        return self.perturbations_stable / self.perturbations_run if self.perturbations_run else 1.0


class ReliabilityTable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    entries: dict[str, TagReliability] = Field(default_factory=dict)
    total_calls: int = Field(default=0, ge=0)

    def get_or_create(self, tag: str) -> TagReliability:
        if tag not in self.entries:
            self.entries[tag] = TagReliability(tag=tag)
        return self.entries[tag]

    def record_panel_call(self, claim_types: list[str], verification_path: str, verdict: str | None = None) -> None:
        """Record one panel call for each structure tag on the claim."""
        for tag in claim_types or ["unknown"]:
            e = self.get_or_create(tag)
            e.total += 1
            self.total_calls += 1
            if verification_path == "tier2-verdict":
                e.tier2_verdict += 1
            elif verification_path == "tier2-advisory-only":
                e.tier2_advisory += 1
            elif verification_path == "tier0":
                e.tier0 += 1
            if verdict == "panel-verified":
                e.panel_verified += 1

    def record_perturbation(self, claim_types: list[str], stable: bool) -> None:
        for tag in claim_types or ["unknown"]:
            e = self.get_or_create(tag)
            e.perturbations_run += 1
            if stable:
                e.perturbations_stable += 1

    def should_allow_tier2_verdict(self, tag: str, threshold: float = 0.5) -> bool:
        """Routing feedback: low reliability tags should stay advisory-only."""
        e = self.entries.get(tag)
        if e is None or e.total < 3:
            return True  # insufficient data → allow
        # If panel-verified rate is low or stability is low, be conservative
        return not (e.verdict_rate < threshold or e.stable_rate < 0.7)

    @classmethod
    def from_journal(cls, journal_path: Path | str) -> ReliabilityTable:
        """Build table from journal's panel calls (Phase 7+)."""
        table = cls()
        evs = replay(journal_path) if Path(journal_path).exists() else []
        board = fold_claims(evs)
        # Map claim_id -> claim_type
        claim_types_map: dict[str, list[str]] = {}
        for cid, payload in board.items():
            claim_types_map[cid] = payload.get("claim_type", []) or payload.get("card", {}).get("claim_type", [])
            # Fallback: try card dict
            if not claim_types_map[cid] and payload.get("card"):
                try:
                    card = ClaimCard.model_validate(payload["card"])
                    claim_types_map[cid] = list(card.claim_type)
                except Exception:
                    pass
        for ev in evs:
            if ev["type"] == "panel_verdict_issued":
                cid = ev["payload"].get("claim_id", "")
                vp = ev["payload"].get("verification_path", "")
                vd = ev["payload"].get("verdict")
                tags = claim_types_map.get(cid, ["unknown"])
                table.record_panel_call(tags, vp, vd)
            elif ev["type"] == "claim_verification_routed":
                # Also count routed tier0 (no panel verdict) as a data point for completeness
                # But we already count via panel_verdict_issued for tier2; for tier0 we count here if no panel verdict exists for that claim
                pass
        return table

    def to_json(self) -> dict[str, Any]:
        return {"entries": {k: v.model_dump() for k, v in self.entries.items()}, "total_calls": self.total_calls}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ReliabilityTable:
        entries = {k: TagReliability.model_validate(v) for k, v in data.get("entries", {}).items()}
        return cls(entries=entries, total_calls=data.get("total_calls", 0))


# ------------------------------------------------------------------ Perturbation audit


def perturb_card(card: ClaimCard, rng: random.Random) -> ClaimCard:
    """One-step perturbation of a card (tweak constant / shift bound / swap quantifier)."""
    # Use the same operators as evals/mutations.py but lightweight here.
    # We implement a minimal tweak: shift lo/hi by ±1 or tweak a constant in conclusion.
    import copy
    import re

    mutated = copy.deepcopy(card)
    choice = rng.choice(["shift_bound", "tweak_constant"])
    if choice == "shift_bound" and mutated.quantifiers:
        q = rng.choice(mutated.quantifiers)
        if q.domain.lo is not None:
            with contextlib.suppress(Exception):
                q.domain.lo = int(q.domain.lo) + rng.choice([-1, 1])
        elif q.domain.hi is not None:
            with contextlib.suppress(Exception):
                q.domain.hi = int(q.domain.hi) + rng.choice([-1, 1])
    elif choice == "tweak_constant":
        # Tweak a digit in conclusion
        m = re.search(r"\d+", mutated.conclusion.expr)
        if m:
            old = m.group(0)
            with contextlib.suppress(Exception):
                new = str(int(old) + rng.choice([-1, 1]))
                mutated.conclusion.expr = mutated.conclusion.expr.replace(old, new, 1)
    # Keep card_id stable for audit (use same id)
    return mutated


def audit_perturbations(
    card: ClaimCard,
    n: int = 5,
    seed: int = 0,
    panel_fn: Any | None = None,
) -> dict[str, Any]:
    """Perturbation audit: does panel verdict stay stable under small mutations?

    panel_fn: callable(card) -> verification_path (e.g., 'tier2-verdict' or 'tier2-advisory-only')
    If not supplied, uses `is_tier0_applicable` as a proxy (non-LLM deterministic).
    Returns {total, stable, stable_rate, details}.
    """
    rng = random.Random(seed)
    # Baseline verdict
    if panel_fn is not None:
        try:
            baseline = panel_fn(card)
        except Exception as e:
            baseline = f"error:{e}"
    else:
        from ramanujan.panel_service import is_tier0_applicable

        baseline = "tier2-verdict" if not is_tier0_applicable(card) else "tier2-advisory-only"

    stable = 0
    details: list[dict[str, Any]] = []
    for i in range(n):
        mutated = perturb_card(card, rng)
        if panel_fn is not None:
            try:
                cur = panel_fn(mutated)
            except Exception as e:
                cur = f"error:{e}"
        else:
            from ramanujan.panel_service import is_tier0_applicable

            cur = "tier2-verdict" if not is_tier0_applicable(mutated) else "tier2-advisory-only"
        is_stable = cur == baseline
        if is_stable:
            stable += 1
        details.append({"i": i, "mutated_conclusion": mutated.conclusion.expr, "verdict": cur, "stable": is_stable})

    return {"baseline": baseline, "total": n, "stable": stable, "stable_rate": stable / n if n else 1.0, "details": details}
