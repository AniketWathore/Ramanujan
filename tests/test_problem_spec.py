"""Tests for ramanujan/problem_spec.py — Phase 1 schema + numeric-only kill-check."""

import sys

import pytest
from pydantic import ValidationError

from ramanujan.problem_spec import (
    KillCheckConfig,
    NumericKillCheckResult,
    ProblemSpec,
    derive_spec_from_card,
    run_numeric_killcheck,
)
from ramanujan.schemas import ClaimCard

PRIME_CARD = {
    "card_id": "c_0001",
    "statement_informal": "For every integer n >= 0, n^2 + n + 41 is prime.",
    "claim_type": ["inequality-estimate"],
    "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "is_prime(n**2 + n + 41)", "sympy_parseable": True},
    "set_vars": [],
}

TRUE_CARD = {
    "card_id": "c_0001",
    "statement_informal": "For every integer n >= 0, n + 1 > n.",
    "claim_type": ["inequality-estimate"],
    "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "n + 1 > n", "sympy_parseable": True},
    "set_vars": [],
}


def test_spec_schema_defaults_and_rejections():
    spec = ProblemSpec(id="prob_001", statement_informal="x?")
    assert spec.statement_formal is None
    assert spec.objective == "determine-truth-value"
    assert spec.kill_check_config.run_smt is True
    assert spec.kill_check_config.small_case_limit == 1000
    with pytest.raises(ValidationError):
        ProblemSpec(id="p1", statement_informal="x?")  # bad id
    with pytest.raises(ValidationError):
        ProblemSpec(id="prob_001", statement_informal="x?", objective="solve")  # bad objective
    assert KillCheckConfig().run_numeric_search is True


def test_derive_spec_from_card_prime():
    card = ClaimCard.model_validate(PRIME_CARD)
    spec = derive_spec_from_card(PRIME_CARD["statement_informal"], card)
    assert spec.id == "prob_001"
    assert spec.statement_formal is None
    assert spec.objective == "determine-truth-value"
    assert [(v.name, v.type, v.constraints) for v in spec.variables] == [("n", "integer", "n >= 0")]
    assert spec.kill_check_config.run_smt is True
    assert spec.open_questions_for_user  # records offline derivation


def test_numeric_killcheck_refutes_prime_without_smt(monkeypatch):
    # SMT must be unreachable on this path: importing it raises.
    monkeypatch.setitem(sys.modules, "ramanujan.killcheck.smt", None)
    card = ClaimCard.model_validate(PRIME_CARD)
    res = run_numeric_killcheck(card, small_case_limit=1000)
    assert isinstance(res, NumericKillCheckResult)
    assert res.status == "refuted"
    assert res.counterexample == {"n": 40}
    assert res.double_verified is True
    assert res.methods == ["bounded_exhaustion"]
    assert res.run_smt is True
    assert res.smt_executed is False


def test_numeric_killcheck_true_survives_without_smt(monkeypatch):
    monkeypatch.setitem(sys.modules, "ramanujan.killcheck.smt", None)
    card = ClaimCard.model_validate(TRUE_CARD)
    res = run_numeric_killcheck(card, small_case_limit=200)
    assert res.status == "survived"
    assert res.counterexample is None
    assert res.double_verified is False
    assert res.run_smt is True
    assert res.smt_executed is False
    assert "bounded_exhaustion" in res.methods
