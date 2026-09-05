from __future__ import annotations

from ramanujan.claimcard import evaluate_conclusion, evaluate_hypotheses, is_counterexample, validate_card
from ramanujan.schemas import ClaimCard


def card_factorial():
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


def test_validate_card_ok():
    c = card_factorial()
    assert validate_card(c).card_id == "c_0001"


def test_evaluate_factorial_true_survives():
    c = card_factorial()
    # n=4 -> 24 > 16 true, not counterexample
    assert evaluate_conclusion(c, {"n": 4}) is True
    assert is_counterexample(c, {"n": 4}) is False
    # n=10 -> 3628800 > 1024 true
    assert evaluate_conclusion(c, {"n": 10}) is True


def test_evaluate_factorial_false_is_counterexample():
    # Use 3^n variant to create false case
    c = ClaimCard.model_validate(
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
    # n=4 -> 24 > 81 false -> counterexample
    assert evaluate_conclusion(c, {"n": 4}) is False
    assert is_counterexample(c, {"n": 4}) is True
    # n=10 -> 3628800 > 59049 true -> not counterexample
    assert is_counterexample(c, {"n": 10}) is False


def test_hypotheses_filter():
    c = ClaimCard.model_validate(
        {
            "card_id": "c_0003",
            "statement_informal": "For n>=0, if n>5 then n! > 100",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
            "hypotheses": ["n > 5"],
            "conclusion": {"expr": "factorial(n) > 100", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    # n=4 hypotheses false -> not counterexample even though conclusion false
    assert evaluate_hypotheses(c, {"n": 4}) is False
    assert is_counterexample(c, {"n": 4}) is False
    # n=6 -> hyp true, conclusion 720 >100 true -> not counterexample
    assert is_counterexample(c, {"n": 6}) is False
    # craft false: factorial(n) > 1000, n=6 -> false -> counterexample when hyp true
    c2 = ClaimCard.model_validate(
        {
            "card_id": "c_0004",
            "statement_informal": "x",
            "claim_type": ["inequality-estimate"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
            "hypotheses": ["n > 5"],
            "conclusion": {"expr": "factorial(n) > 1000", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    assert is_counterexample(c2, {"n": 6}) is True  # 720 >1000 false


def test_prime_counterexample():
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
    # true through 39
    for n in range(40):
        assert evaluate_conclusion(c, {"n": n}) is True, f"failed at {n}"
    assert evaluate_conclusion(c, {"n": 40}) is False
    assert is_counterexample(c, {"n": 40}) is True
    assert is_counterexample(c, {"n": 41}) is True  # 41^2+41+41=1763=41*43


def test_sum_identity():
    c = ClaimCard.model_validate(
        {
            "card_id": "c_0006",
            "statement_informal": "sum 1+3+...+(2n-1)=n^2",
            "claim_type": ["algebraic-identity"],
            "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 1, "hi": None}}],
            "hypotheses": [],
            "conclusion": {"expr": "n**2 == n**2", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    assert evaluate_conclusion(c, {"n": 5}) is True


def test_set_sumset_card():
    # True: |A+B| >= |A|+|B|-1  for nonempty finite sets
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
    assert evaluate_conclusion(c_true, {"A": {1, 2}, "B": {10, 20}}) is True  # |{11,21,12,22}|=4 >=2+2-1=3
    assert is_counterexample(c_true, {"A": {1, 2}, "B": {10, 20}}) is False

    # False variant: |A+B| >= |A|+|B|  fails on e.g., A={0,1}, B={0,1} -> |{0,1,2}|=3 < 4
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
    assert evaluate_conclusion(c_false, {"A": {0, 1}, "B": {0, 1}}) is False
    assert is_counterexample(c_false, {"A": {0, 1}, "B": {0, 1}}) is True


def test_exists_quantifier_not_checked_by_is_counterexample():
    # is_counterexample is defined for universal vars; exists is not considered here
    # Just ensure no crash
    c = ClaimCard.model_validate(
        {
            "card_id": "c_0009",
            "statement_informal": "Exists m forall n m>n",
            "claim_type": ["quantifier-scope"],
            "quantifiers": [
                {"var": "m", "kind": "exists", "domain": {"type": "int", "lo": None, "hi": None}},
                {"var": "n", "kind": "forall", "domain": {"type": "int", "lo": None, "hi": None}},
            ],
            "hypotheses": [],
            "conclusion": {"expr": "m > n", "sympy_parseable": True},
            "set_vars": [],
        }
    )
    # interpreter still evaluates given assignment
    assert evaluate_conclusion(c, {"m": 5, "n": 10}) is False
