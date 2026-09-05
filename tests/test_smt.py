from __future__ import annotations

import pytest

from ramanujan.schemas import ClaimCard

try:
    HAS_Z3 = True
except Exception:
    HAS_Z3 = False


@pytest.mark.skipif(not HAS_Z3, reason="z3 not installed")
def test_smt_sat_finds_linear_counterexample():
    from ramanujan.killcheck.smt import smt_search

    # False claim: forall n >=0, n > 5  -> counterexample n=0
    c = ClaimCard.model_validate(
        {
            "card_id": "c_0101",
            "statement_informal": "For n>=0, n > 5",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
            "hypotheses": [],
            "conclusion": {"expr": "n > 5", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    assignment, stats = smt_search(c)
    assert assignment is not None
    assert stats["status"] == "sat"
    assert assignment["n"] <= 5


@pytest.mark.skipif(not HAS_Z3, reason="z3 not installed")
def test_smt_unsat_true_claim():
    from ramanujan.killcheck.smt import smt_search

    # True: forall n in [0,10], n >=0  (domain itself ensures)
    c = ClaimCard.model_validate(
        {
            "card_id": "c_0102",
            "statement_informal": "For n in [0,5], n >=0",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": 5}}],
            "hypotheses": [],
            "conclusion": {"expr": "n >= 0", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    assignment, stats = smt_search(c)
    assert assignment is None
    assert stats["status"] == "unsat"


@pytest.mark.skipif(not HAS_Z3, reason="z3 not installed")
def test_smt_skips_unsupported():
    from ramanujan.killcheck.smt import smt_search

    c = ClaimCard.model_validate(
        {
            "card_id": "c_0103",
            "statement_informal": "factorial",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
            "hypotheses": [],
            "conclusion": {"expr": "factorial(n) > 2**n", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    assignment, stats = smt_search(c)
    assert stats["status"] == "skipped"


@pytest.mark.skipif(not HAS_Z3, reason="z3 not installed")
def test_smt_skips_set():
    from ramanujan.killcheck.smt import smt_search

    c = ClaimCard.model_validate(
        {
            "card_id": "c_0104",
            "statement_informal": "set",
            "claim_type": ["combinatorial-construction"],
            "quantifiers": [
                {
                    "var": "A",
                    "kind": "forall",
                    "domain": {"type": "finite_set_of_ints", "lo": None, "hi": None},
                }
            ],
            "hypotheses": [],
            "conclusion": {"expr": "|A| >= 1", "sympy_parseable": True},
            "set_vars": ["A"],
        }
    )
    assignment, stats = smt_search(c)
    assert stats["status"] == "skipped"
