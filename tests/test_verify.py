from __future__ import annotations

from ramanujan.schemas import ClaimCard


def test_verify_true_counterexample():
    from ramanujan.killcheck.verify import verify_counterexample

    c = ClaimCard.model_validate(
        {
            "card_id": "c_0002",
            "statement_informal": "For n>=4, n! > 3^n",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
            "hypotheses": [],
            "conclusion": {"expr": "factorial(n) > 3**n", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    ok, reason = verify_counterexample(c, {"n": 4})
    assert ok is True
    assert "verified" in reason


def test_verify_rejects_vacuous():
    from ramanujan.killcheck.verify import verify_counterexample

    c = ClaimCard.model_validate(
        {
            "card_id": "c_0003",
            "statement_informal": "hyp false",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
            "hypotheses": ["n > 100"],
            "conclusion": {"expr": "factorial(n) > 0", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    ok, reason = verify_counterexample(c, {"n": 5})
    assert ok is False
    assert "hypotheses false" in reason


def test_verify_rejects_true_conclusion():
    from ramanujan.killcheck.verify import verify_counterexample

    c = ClaimCard.model_validate(
        {
            "card_id": "c_0001",
            "statement_informal": "true",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
            "hypotheses": [],
            "conclusion": {"expr": "factorial(n) > 2**n", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    ok, reason = verify_counterexample(c, {"n": 10})
    assert ok is False
    assert "conclusion true" in reason


def test_verify_set():
    from ramanujan.killcheck.verify import verify_counterexample

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
    ok, _ = verify_counterexample(c_false, {"A": {0, 1}, "B": {0, 1}})
    assert ok is True
    ok2, _ = verify_counterexample(c_false, {"A": {0}, "B": {0}})
    assert ok2 is True  # |{0}|=1, |A|+|B|=2 => 1>=2 false => valid counterexample
    # A={0} B={1} also counterexample; singletons always 1>=2 false
    # true card instead for non-counterexample
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
    ok3, _ = verify_counterexample(c_true, {"A": {0, 1}, "B": {0, 1}})
    assert ok3 is False  # true claim, no counterexample
