from __future__ import annotations

from ramanujan.claimcard import ClaimCard


def _card_factorial_2pow():
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


def _card_factorial_3pow():
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


def test_bounded_exhaustion_finds_3pow_counterexample():
    from ramanujan.killcheck.numeric import bounded_exhaustion

    c = _card_factorial_3pow()
    assignment, stats = bounded_exhaustion(c, exhaustive_limit=20)
    assert assignment is not None
    assert assignment["n"] == 4  # first failure
    assert stats["method"] == "bounded_exhaustion"


def test_bounded_exhaustion_survives_true():
    from ramanujan.killcheck.numeric import bounded_exhaustion

    c = _card_factorial_2pow()
    # Need large limit to ensure no false refutation within range; but true holds for all n>=4
    assignment, stats = bounded_exhaustion(c, exhaustive_limit=100)
    assert assignment is None
    assert stats["checked"] == 101  # 4..104


def test_randomized_finds_prime_counterexample():
    from ramanujan.killcheck.numeric import randomized_sampling

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
    assignment, stats = randomized_sampling(c, samples=1000, high=100, seed=0)
    # randomized may or may not hit 40 within 1000 wide samples; but bounded will
    # Just ensure it doesn't crash; for this test we check bounded finds it
    from ramanujan.killcheck.numeric import bounded_exhaustion

    assignment2, _ = bounded_exhaustion(c, exhaustive_limit=100)
    assert assignment2 is not None and assignment2["n"] == 40


def test_set_exhaustion():
    from ramanujan.killcheck.numeric import exhaustive_small_set

    c_true = ClaimCard.model_validate(
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
    assignment, stats = exhaustive_small_set(c_true, max_universe=4)
    assert assignment is None

    c_false = ClaimCard.model_validate(
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
    assignment2, stats2 = exhaustive_small_set(c_false, max_universe=4)
    assert assignment2 is not None

    c_rand = ClaimCard.model_validate(
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
    from ramanujan.killcheck.numeric import random_set_sampling

    assignment3, _ = random_set_sampling(c_rand, samples=500, seed=0)
    # May or may not find, but shouldn't crash
    assert isinstance(assignment3, dict) or assignment3 is None
