from __future__ import annotations

import time

import pytest

from ramanujan.budget import Budget, BudgetExceeded


def test_budget_cost_breach():
    b = Budget(budget_usd=0.50, budget_sec=120)
    b.add_cost(0.40)
    assert b.spent_usd == pytest.approx(0.40)
    with pytest.raises(BudgetExceeded) as exc:
        b.add_cost(0.20)
    assert exc.value.kind == "cost"
    # check is_exceeded
    exceeded, kind = b.is_exceeded()
    assert exceeded and kind == "cost"


def test_budget_time_breach():
    b = Budget(budget_usd=10, budget_sec=0.05)
    time.sleep(0.07)
    with pytest.raises(BudgetExceeded) as exc:
        b.check()
    assert exc.value.kind == "time"


def test_budget_no_breach():
    b = Budget(budget_usd=1.0, budget_sec=10)
    b.add_cost(0.1)
    b.check()
    exceeded, kind = b.is_exceeded()
    assert not exceeded
    assert kind is None


def test_budget_snapshot():
    b = Budget(budget_usd=1.0, budget_sec=60)
    b.add_cost(0.25)
    snap = b.snapshot()
    assert snap["spent_usd"] == pytest.approx(0.25)
    assert snap["remaining_usd"] == pytest.approx(0.75)
    assert snap["budget_sec"] == 60
