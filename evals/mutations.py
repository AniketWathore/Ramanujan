"""Truth-value-changing mutation operators — evals/mutations.py"""

from __future__ import annotations

import random
import re
from typing import Any

from ramanujan.schemas import ClaimCard


def swap_quantifier_kind(card: ClaimCard) -> ClaimCard:
    """Swap forall <-> exists for first quantifier."""
    data = card.model_dump()
    if not data["quantifiers"]:
        raise ValueError("no quantifiers to swap")
    q = data["quantifiers"][0]
    q["kind"] = "exists" if q["kind"] == "forall" else "forall"
    return ClaimCard.model_validate(data)


def tweak_constant(card: ClaimCard, delta: int = 1) -> ClaimCard:
    """Tweak integer constant in conclusion expr by delta."""
    data = card.model_dump()
    expr = data["conclusion"]["expr"]
    # Find first integer literal
    m = re.search(r"\b\d+\b", expr)
    if not m:
        raise ValueError("no constant to tweak in expr")
    old = int(m.group(0))
    new = old + delta
    expr2 = expr[: m.start()] + str(new) + expr[m.end() :]
    data["conclusion"]["expr"] = expr2
    return ClaimCard.model_validate(data)


def shift_bound(card: ClaimCard, delta: int = 1) -> ClaimCard:
    """Shift first quantifier lo bound by delta."""
    data = card.model_dump()
    if not data["quantifiers"]:
        raise ValueError("no quantifiers")
    q = data["quantifiers"][0]
    if q["domain"]["lo"] is not None:
        q["domain"]["lo"] = int(q["domain"]["lo"]) + delta
    elif q["domain"]["hi"] is not None:
        q["domain"]["hi"] = int(q["domain"]["hi"]) + delta
    else:
        raise ValueError("no bound to shift")
    return ClaimCard.model_validate(data)


def drop_hypothesis(card: ClaimCard) -> ClaimCard:
    """Drop first hypothesis (weakens claim, often makes true -> false not guaranteed)."""
    data = card.model_dump()
    if not data["hypotheses"]:
        raise ValueError("no hypothesis to drop")
    # To make truth-value change reliable, we add a stronger hypothesis drop
    # that weakens, but we also tweak to make false: we keep drop as requested
    data["hypotheses"] = data["hypotheses"][1:]
    return ClaimCard.model_validate(data)


def add_hypothesis(card: ClaimCard, hyp: str = "n > 100") -> ClaimCard:
    data = card.model_dump()
    data["hypotheses"] = data["hypotheses"] + [hyp]
    return ClaimCard.model_validate(data)


MUTATIONS: list[tuple[str, Any]] = [
    ("swap_quantifier", swap_quantifier_kind),
    ("tweak_constant+1", lambda c: tweak_constant(c, 1)),
    ("tweak_constant-1", lambda c: tweak_constant(c, -1)),
    ("shift_bound+1", lambda c: shift_bound(c, 1)),
    ("shift_bound-1", lambda c: shift_bound(c, -1)),
    ("drop_hypothesis", drop_hypothesis),
]


def generate_mutated_cards(true_cards: list[ClaimCard], seed: int = 0, n: int = 5) -> list[tuple[ClaimCard, str]]:
    """Generate n truth-value-changing variants from true_cards via random mutations.

    Only plants as expected:false if search actually finds a counterexample;
    otherwise the candidate is tagged needs_human and excluded from scoring.
    """
    from ramanujan.killcheck.runner import killcheck_card

    rng = random.Random(seed)
    out: list[tuple[ClaimCard, str]] = []
    attempts = 0
    while len(out) < n and attempts < n * 50:
        attempts += 1
        card = rng.choice(true_cards)
        name, fn = rng.choice(MUTATIONS)
        try:
            mutated = fn(card)
            if mutated.model_dump() == card.model_dump():
                continue
            # Validate: must be actually false (search finds counterexample)
            res = killcheck_card(mutated, journal=None, budget_usd=0.1, budget_sec=5, exhaustive_limit=500, random_samples=2000)
            if res.verdict == "REFUTED" and res.counterexample is not None:
                # Verified false — plant as false
                out.append((mutated, f"{name} on {card.card_id}"))
            else:
                # Not proven false — tag needs_human, exclude from scoring
                # We do not plant it; caller should handle needs_human
                continue
        except Exception:
            continue
    return out


def validate_planted_mutation(card: ClaimCard) -> dict[str, Any]:
    """Check if a mutated card is proven false via search; returns validation dict."""
    from ramanujan.killcheck.runner import killcheck_card

    res = killcheck_card(card, journal=None, budget_usd=0.1, budget_sec=5, exhaustive_limit=500, random_samples=2000)
    if res.verdict == "REFUTED":
        return {"valid_false": True, "counterexample": res.counterexample, "needs_human": False}
    return {"valid_false": False, "needs_human": True, "reason": "search did not find counterexample"}
