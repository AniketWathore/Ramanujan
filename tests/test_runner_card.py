from __future__ import annotations

from ramanujan.killcheck.runner import killcheck_card
from ramanujan.schemas import ClaimCard


def card_true_factorial2():
    return ClaimCard.model_validate(
        {
            "card_id": "c_0001",
            "statement_informal": "For every integer n >= 4, n! > 2^n.",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
            "hypotheses": [],
            "conclusion": {"expr": "factorial(n) > 2**n", "sympy_parseable": True},
            "set_vars": [],
        }
    )


def card_false_factorial3():
    return ClaimCard.model_validate(
        {
            "card_id": "c_0002",
            "statement_informal": "For every integer n >= 4, n! > 3^n.",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
            "hypotheses": [],
            "conclusion": {"expr": "factorial(n) > 3**n", "sympy_parseable": True},
            "set_vars": [],
        }
    )


def test_runner_true_survives():
    c = card_true_factorial2()
    res = killcheck_card(c, journal=None, exhaustive_limit=200, random_samples=2000)
    assert res.verdict == "SURVIVED"
    assert res.counterexample is None
    # Must have tried phases
    assert len(res.stats["phases"]) >= 1


def test_runner_false_refuted_with_double_verify():
    c = card_false_factorial3()
    res = killcheck_card(c, journal=None, exhaustive_limit=100)
    assert res.verdict == "REFUTED"
    assert res.counterexample is not None
    assert res.counterexample["n"] == 4
    assert res.stats["verify"]["ok"] is True
    assert "verify_disagreement" not in res.stats


def test_runner_prime_hidden_counterexample():
    c = ClaimCard.model_validate(
        {
            "card_id": "c_0005",
            "statement_informal": "For n>=0, n^2+n+41 is prime",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
            "hypotheses": [],
            "conclusion": {"expr": "is_prime(n**2 + n + 41)", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    # This tests search depth: true through 39, fails at 40
    res = killcheck_card(c, journal=None, exhaustive_limit=1000)
    assert res.verdict == "REFUTED"
    assert res.counterexample["n"] == 40


def test_runner_true_sumset_survives():
    c = ClaimCard.model_validate(
        {
            "card_id": "c_0007",
            "statement_informal": "|A+B| >= |A|+|B|-1",
            "claim_type": ["combinatorial-construction"],
            "quantifiers": [
                {
                    "var": "A",
                    "kind": "forall",
                    "domain": {"type": "finite_set_of_ints", "lo": None, "hi": None},
                },
                {
                    "var": "B",
                    "kind": "forall",
                    "domain": {"type": "finite_set_of_ints", "lo": None, "hi": None},
                },
            ],
            "hypotheses": [],
            "conclusion": {"expr": "|A+B| >= |A|+|B|-1", "sympy_parseable": True},
            "set_vars": ["A", "B"],
        }
    )
    res = killcheck_card(c, journal=None)
    assert res.verdict == "SURVIVED"


def test_runner_false_sumset_refuted():
    c = ClaimCard.model_validate(
        {
            "card_id": "c_0008",
            "statement_informal": "|A+B| >= |A|+|B|",
            "claim_type": ["combinatorial-construction"],
            "quantifiers": [
                {
                    "var": "A",
                    "kind": "forall",
                    "domain": {"type": "finite_set_of_ints", "lo": None, "hi": None},
                },
                {
                    "var": "B",
                    "kind": "forall",
                    "domain": {"type": "finite_set_of_ints", "lo": None, "hi": None},
                },
            ],
            "hypotheses": [],
            "conclusion": {"expr": "|A+B| >= |A|+|B|", "sympy_parseable": True},
            "set_vars": ["A", "B"],
        }
    )
    res = killcheck_card(c, journal=None)
    assert res.verdict == "REFUTED"
    # Verify independent path matches
    assert res.stats["verify"]["ok"] is True


def test_runner_budget_exhausted_gives_survived_with_caveat():
    c = card_true_factorial2()
    res = killcheck_card(c, journal=None, budget_sec=0.0001, exhaustive_limit=5000)
    # With tiny budget, may breach; if so should be SURVIVED budget_exhausted
    assert res.verdict == "SURVIVED"
    # Might have budget_breach or budget_exhausted flag
    # Not asserting exact, just that it doesn't falsely refute
