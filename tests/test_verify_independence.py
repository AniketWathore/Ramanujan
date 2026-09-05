"""Test that verify.py is independent second path — monkeypatch search evaluator."""

from __future__ import annotations

from unittest.mock import patch

from ramanujan.schemas import ClaimCard


def _true_card():
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


def test_verify_catches_search_false_positive():
    """Patch search-side to return wrong True, verify must catch and prevent REFUTED."""
    from ramanujan.killcheck.runner import killcheck_card

    card = _true_card()

    # Patch the search-side is_counterexample to always claim n=4 is counterexample (which is false for true claim)
    # True claim n=4: 24>16 true, so is_counterexample should be False, but we fake True
    with patch("ramanujan.killcheck.numeric.is_counterexample", return_value=True):
        # Also need to patch the other import path that runner might use via claimcard?
        # The runner's numeric module is the search side; verify is independent so should still be correct
        res = killcheck_card(card, journal=None, exhaustive_limit=10, random_samples=0)
        # Search will think it found a counterexample at n=4, but verify should disagree
        # Runner should NOT report REFUTED, should report SURVIVED with disagreement flag
        assert res.verdict == "SURVIVED", f"expected SURVIVED due to verify disagreement, got {res.verdict}"
        assert res.counterexample is None
        # Stats should contain verify_disagreement
        assert res.stats.get("verify_disagreement") is True or "verify" in res.stats
        # Verify that the verify path itself is correct for true claim
        from ramanujan.killcheck.verify import verify_counterexample

        ok, reason = verify_counterexample(card, {"n": 4})
        assert ok is False
        assert "conclusion true" in reason


def test_verify_independent_no_shared_state():
    """Ensure verify does not use shared helpers that could be monkeypatched via claimcard."""
    # Verify that verify module does not import is_counterexample from claimcard
    # Check source: it should not have that import
    import inspect

    import ramanujan.claimcard as cc
    from ramanujan.killcheck import verify as verify_module

    src = inspect.getsource(verify_module)
    assert "from ramanujan.claimcard import is_counterexample" not in src
    assert "from ramanujan.claimcard import evaluate" not in src
    # Also check that patching claimcard does not affect verify
    card = _true_card()
    with patch.object(cc, "is_counterexample", return_value=True):
        # Direct claimcard is patched, but verify should still be correct (independent)
        from ramanujan.killcheck.verify import verify_counterexample

        ok, _ = verify_counterexample(card, {"n": 4})
        assert ok is False, "verify should be independent of claimcard patch"
