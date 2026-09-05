"""Frozen claim-type taxonomy v1 — ramanujan/taxonomy.py"""

from __future__ import annotations

CLAIM_TYPES: list[str] = [
    "inequality-estimate",
    "quantifier-scope",
    "algebraic-identity",
    "convergence-limit",
    "compactness-existence",
    "combinatorial-construction",
    "induction-recursion",
    "code-algorithmic",
    "statement-equivalence",
    "generalization",
]

CLAIM_TYPES_SET: set[str] = set(CLAIM_TYPES)


def validate_claim_types(tags: list[str]) -> list[str]:
    """Validate every tag is in the frozen taxonomy; raise ValueError otherwise."""
    invalid = [t for t in tags if t not in CLAIM_TYPES_SET]
    if invalid:
        raise ValueError(f"invalid claim_type tags: {invalid}; allowed: {CLAIM_TYPES}")
    return tags


def is_valid_claim_type(tag: str) -> bool:
    return tag in CLAIM_TYPES_SET
