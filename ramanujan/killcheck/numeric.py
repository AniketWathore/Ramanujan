"""Deterministic numeric / random / set search — ramanujan/killcheck/numeric.py"""

from __future__ import annotations

import itertools
import random
from typing import Any

from ramanujan.claimcard import EvaluationTimeout, is_counterexample
from ramanujan.schemas import ClaimCard


def _get_forall_int_vars(card: ClaimCard) -> list[tuple[str, int | None, int | None]]:
    out: list[tuple[str, int | None, int | None]] = []
    for q in card.quantifiers:
        if q.kind == "forall" and q.domain.type == "int":
            out.append((q.var, q.domain.lo, q.domain.hi))
    return out


def _exhaustion_values(lo: int | None, hi: int | None, limit: int = 1000) -> list[int]:
    if lo is None:
        lo = -500
    if hi is not None:
        # bounded range
        r = list(range(int(lo), int(hi) + 1))
        return r[: limit + 1]
    # unbounded above: lo .. lo+limit (inclusive) plus near-boundary specials within domain
    base = list(range(int(lo), int(lo) + limit + 1))
    # specials are lo and lo+1 etc already in base; keep hook for hi edge if bounded (handled above)
    return base


def bounded_exhaustion(card: ClaimCard, *, exhaustive_limit: int = 1000) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Try bounded enumeration. Returns (assignment or None, stats)."""
    # Set cards handled separately
    if card.set_vars:
        return None, {"method": "bounded_exhaustion", "skipped": "set_card"}
    int_vars = _get_forall_int_vars(card)
    if not int_vars:
        return None, {"method": "bounded_exhaustion", "skipped": "no_forall_ints"}
    # Build per-var value lists
    per_var = []
    var_names = []
    for var, lo, hi in int_vars:
        # Normalize lo/hi to int if float
        lo_i = int(lo) if lo is not None else None  # noqa: E741
        hi_i = int(hi) if hi is not None else None
        vals = _exhaustion_values(lo_i, hi_i, limit=exhaustive_limit)
        per_var.append(vals)
        var_names.append(var)
    checked = 0
    # If single var, simple loop; if multiple, product but cap total checks to avoid explosion
    # cap product to 200k for exhaustive
    max_checks = 200_000
    # If product size > cap, truncate
    total_combo = 1
    for v in per_var:
        total_combo *= len(v)
        if total_combo > max_checks:
            break
    if total_combo > max_checks:
        # For multi-var, use sampled product via random instead
        return None, {
            "method": "bounded_exhaustion",
            "skipped": "combinatorial_explosion",
            "total_combo": total_combo,
        }

    timeouts = 0
    for combo in itertools.product(*per_var):
        assignment = dict(zip(var_names, combo, strict=False))
        checked += 1
        try:
            if is_counterexample(card, assignment):
                return assignment, {
                    "method": "bounded_exhaustion",
                    "checked": checked,
                    "found_at": dict(assignment),
                }
        except EvaluationTimeout:
            timeouts += 1
            continue
        except Exception:
            continue
    if timeouts:
        return None, {
            "method": "bounded_exhaustion",
            "checked": checked,
            "timeouts": timeouts,
            "skipped": "evaluation too costly",
            "found": False,
        }
    return None, {"method": "bounded_exhaustion", "checked": checked, "found": False}


def _has_factorial(card: ClaimCard) -> bool:
    return "factorial" in card.conclusion.expr or any("factorial" in h for h in card.hypotheses)


def randomized_sampling(
    card: ClaimCard, *, samples: int = 10_000, high: int = 10_000_000, seed: int = 0
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if card.set_vars:
        return None, {"method": "randomized_sampling", "skipped": "set_card"}
    int_vars = _get_forall_int_vars(card)
    if not int_vars:
        return None, {"method": "randomized_sampling", "skipped": "no_forall_ints"}
    # Cost-aware cap: factorial is costly, limit range
    if _has_factorial(card):
        high = min(high, 5000)
    rng = random.Random(seed)
    checked = 0
    timeouts = 0
    for _ in range(samples):
        assignment: dict[str, Any] = {}
        for var, lo, hi in int_vars:
            lo_i2 = int(lo) if lo is not None else -high  # noqa: E741
            hi_i2 = int(hi) if hi is not None else high
            # wide range: sample uniformly in [lo_i2, hi_i2] but bias small
            if rng.random() < 0.5 and lo is not None and lo_i2 + 1000 < hi_i2:
                # bias near lower bound (edge cases)
                assignment[var] = rng.randint(lo_i2, min(lo_i2 + 1000, hi_i2))
            else:
                # wide
                assignment[var] = rng.randint(max(lo_i2, -high), min(hi_i2, high))
        checked += 1
        try:
            if is_counterexample(card, assignment):
                return assignment, {
                    "method": "randomized_sampling",
                    "checked": checked,
                    "found_at": dict(assignment),
                }
        except EvaluationTimeout:
            timeouts += 1
            continue
        except Exception:
            continue
    if timeouts:
        return None, {
            "method": "randomized_sampling",
            "checked": checked,
            "timeouts": timeouts,
            "skipped": "evaluation too costly",
            "found": False,
        }
    return None, {"method": "randomized_sampling", "checked": checked, "found": False}


# ---------------------------------------------------------------------------
# Set search
# ---------------------------------------------------------------------------


def _random_finite_set(rng: random.Random, universe: list[int], min_size: int = 1) -> set[int]:
    # Nonempty required by most claims; ensure at least min_size
    k = rng.randint(min_size, len(universe))
    return set(rng.sample(universe, k))


def exhaustive_small_set(card: ClaimCard, *, max_universe: int = 5) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not card.set_vars:
        return None, {"method": "exhaustive_small_set", "skipped": "not_set_card"}
    # Small universe enumeration 1..max_universe
    # Universe = {0..u-1} or {1..u}
    checked = 0
    for u in range(1, max_universe + 1):
        universe = list(range(u + 1)) if u <= 3 else list(range(1, u + 1))
        # all subsets (nonempty)
        subsets = []
        for r in range(1, len(universe) + 1):
            for combo in itertools.combinations(universe, r):
                subsets.append(set(combo))
        # For 1 set var: iterate subsets
        if len(card.set_vars) == 1:
            var = card.set_vars[0]
            for s in subsets:
                checked += 1
                assignment = {var: s}
                try:
                    if is_counterexample(card, assignment):
                        return assignment, {
                            "method": "exhaustive_small_set",
                            "checked": checked,
                            "universe": u,
                            "found_at": {var: sorted(s)},
                        }
                except Exception:
                    continue
        elif len(card.set_vars) == 2:
            a_var, b_var = card.set_vars[0], card.set_vars[1]
            # For efficiency cap at 20000 combos per universe
            count = 0
            for a in subsets:
                for b in subsets:
                    count += 1
                    if count > 40000:
                        break
                    checked += 1
                    assignment = {a_var: a, b_var: b}
                    try:
                        if is_counterexample(card, assignment):
                            return assignment, {
                                "method": "exhaustive_small_set",
                                "checked": checked,
                                "universe": u,
                                "found_at": {a_var: sorted(a), b_var: sorted(b)},
                            }
                    except Exception:
                        continue
                if count > 40000:
                    break
        else:
            # >2 set vars: skip exhaustive, use random
            return None, {"method": "exhaustive_small_set", "skipped": "too_many_set_vars"}
    return None, {"method": "exhaustive_small_set", "checked": checked, "found": False}


def random_set_sampling(
    card: ClaimCard, *, samples: int = 5000, universe_max: int = 50, seed: int = 0
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not card.set_vars:
        return None, {"method": "random_set_sampling", "skipped": "not_set_card"}
    rng = random.Random(seed + 1)
    checked = 0
    for _ in range(samples):
        assignment: dict[str, Any] = {}
        for var in card.set_vars:
            # random universe size and elements
            u_size = rng.randint(5, universe_max)
            universe = list(range(-u_size // 2, u_size // 2 + 1))
            # pick random nonempty subset
            k = rng.randint(1, min(10, len(universe)))
            assignment[var] = set(rng.sample(universe, k))
        checked += 1
        try:
            if is_counterexample(card, assignment):
                # For logging, sort
                logged = {k: sorted(v) for k, v in assignment.items()}
                return assignment, {
                    "method": "random_set_sampling",
                    "checked": checked,
                    "found_at": logged,
                }
        except Exception:
            continue
    return None, {"method": "random_set_sampling", "checked": checked, "found": False}
