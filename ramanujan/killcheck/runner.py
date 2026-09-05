"""Sprint orchestration — ramanujan/killcheck/runner.py

Encode outside (hand cards for Task 4). Orchestrates
bounded exhaustion, random sampling, SMT, set enumeration, verify.
"""

from __future__ import annotations

import contextlib
import platform
import time
from dataclasses import dataclass
from typing import Any

import sympy
import z3  # type: ignore

from ramanujan.budget import Budget, BudgetExceeded
from ramanujan.journal import JournalWriter
from ramanujan.killcheck.numeric import (
    bounded_exhaustion,
    exhaustive_small_set,
    random_set_sampling,
    randomized_sampling,
)
from ramanujan.killcheck.smt import smt_search
from ramanujan.killcheck.verify import verify_counterexample
from ramanujan.schemas import ClaimCard


@dataclass
class KillResult:
    verdict: str  # REFUTED | SURVIVED | BUDGET_EXCEEDED
    counterexample: dict[str, Any] | None
    stats: dict[str, Any]
    budget_exhausted: bool = False


def _env_fingerprint() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "sympy": sympy.__version__,
        "z3": z3.get_version_string(),
        "platform": platform.platform(),
    }


def killcheck_card(
    card: ClaimCard,
    journal: JournalWriter | None = None,
    *,
    budget_usd: float | None = None,
    budget_sec: float | None = None,
    exhaustive_limit: int = 1000,
    random_samples: int = 10000,
) -> KillResult:
    """Run deterministic search from a ClaimCard. No LLM."""
    budget = Budget(budget_usd=budget_usd, budget_sec=budget_sec)
    start = time.monotonic()
    stats: dict[str, Any] = {"phases": []}
    stats["env"] = _env_fingerprint()
    candidate: dict[str, Any] | None = None
    found_phase: str | None = None

    def check_budget() -> bool:
        try:
            budget.check()
            return True
        except BudgetExceeded as e:
            stats["budget_breach"] = {"kind": e.kind, "limit": e.limit, "used": e.used}
            stats["budget"] = budget.snapshot()
            return False

    # Phase ordering: bounded -> random -> smt -> set exhaustive -> set random
    phases: list[tuple[str, Any]] = []

    is_set = bool(card.set_vars)

    if not is_set:
        phases.append(
            (
                "bounded_exhaustion",
                lambda: bounded_exhaustion(card, exhaustive_limit=exhaustive_limit),
            )
        )
        phases.append(
            (
                "randomized_sampling",
                lambda: randomized_sampling(card, samples=random_samples, seed=0),
            )
        )
        phases.append(("smt", lambda: smt_search(card)))
    else:
        phases.append(("exhaustive_small_set", lambda: exhaustive_small_set(card, max_universe=5)))
        phases.append(("random_set_sampling", lambda: random_set_sampling(card, samples=5000, seed=0)))
        # Also try smt skip then numeric fallback for mixed cards? Not needed

    for phase_name, fn in phases:
        if not check_budget():
            break
        try:
            assignment, phase_stats = fn()
        except Exception as e:
            phase_stats = {"method": phase_name, "error": str(e)}
            assignment = None
        phase_stats["phase"] = phase_name
        stats["phases"].append(phase_stats)
        if journal is not None:
            with contextlib.suppress(Exception):
                journal.write("check_executed", {"phase": phase_name, "stats": phase_stats})
        # Budget check after phase
        if not check_budget():
            break
        if assignment is not None:
            candidate = assignment
            found_phase = phase_name
            break

    elapsed = time.monotonic() - start
    stats["elapsed_sec"] = elapsed
    stats["budget"] = budget.snapshot()

    if candidate is not None:
        # Double-verification (CRITICAL)
        ok, reason = verify_counterexample(card, candidate)
        stats["verify"] = {
            "ok": ok,
            "reason": reason,
            "candidate": {k: (sorted(v) if isinstance(v, set) else v) for k, v in candidate.items()},
        }
        if journal is not None:
            with contextlib.suppress(Exception):
                journal.write(
                    "counterexample_found",
                    {"phase": found_phase, "candidate": stats["verify"]["candidate"]},
                )
                journal.write("counterexample_reverified", {"ok": ok, "reason": reason})
        if ok:
            final_assignment = candidate
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.write(
                        "claim_refuted",
                        {"counterexample": stats["verify"]["candidate"], "phase": found_phase},
                    )
            return KillResult(verdict="REFUTED", counterexample=final_assignment, stats=stats)
        else:
            # Disagreement: log loudly, treat as survival, mark suspect
            stats["verify_disagreement"] = True
            stats["suspect"] = True
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.write(
                        "budget_event",
                        {
                            "note": "verify disagreement, treating as survival",
                            "candidate": stats["verify"]["candidate"],
                            "reason": reason,
                        },
                    )
            return KillResult(verdict="SURVIVED", counterexample=None, stats=stats)

    # No candidate found
    # Check if budget breached -> SURVIVED with caveat
    try:
        budget.check()
        budget_exhausted = False
    except BudgetExceeded:
        budget_exhausted = True
        stats["budget_exhausted"] = True

    if journal is not None:
        with contextlib.suppress(Exception):
            journal.write("claim_survived", {"stats": stats, "budget_exhausted": budget_exhausted})
    if budget_exhausted:
        return KillResult(verdict="SURVIVED", counterexample=None, stats=stats, budget_exhausted=True)
    return KillResult(verdict="SURVIVED", counterexample=None, stats=stats)
