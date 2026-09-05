"""Tests for single worktree posting multiple claims with inline Tier0/Tier1 — Phase 4."""

from pathlib import Path

from ramanujan.claims import fold_claims
from ramanujan.dispatcher import Dispatcher
from ramanujan.journal import JournalWriter, replay
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

FALSE_CARD = {
    "card_id": "c_0001",
    "statement_informal": "For every integer n >= 0, n < n + 0.",
    "claim_type": ["inequality-estimate"],
    "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "n < n", "sympy_parseable": True},
    "set_vars": [],
}


def test_single_worktree_posts_multiple_claims_inline_tier0_tier1(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_1")
    disp = Dispatcher(j)
    wt = disp.spawn_worktree(provider="test", model_id="test/model", family="family:test", model_ref="test/model")
    assert wt["id"] == "wt_001"

    # First claim: prime (refuted n=40)
    r1 = disp.post_and_check_claim(wt["id"], ClaimCard.model_validate(PRIME_CARD))
    assert r1["claim_id"] == "c_001"
    assert r1["verification_path"] == "tier0"
    assert r1["kill_result"].verdict == "REFUTED"
    assert r1["kill_result"].counterexample == {"n": 40}
    assert r1["tier1"]["linted"] is True

    # Second claim: true (survived)
    r2 = disp.post_and_check_claim(wt["id"], ClaimCard.model_validate(TRUE_CARD))
    assert r2["claim_id"] == "c_002"
    assert r2["kill_result"].verdict == "SURVIVED"
    assert r2["verification_path"] == "tier0"

    # Third claim: trivially false (refuted immediately)
    r3 = disp.post_and_check_claim(wt["id"], ClaimCard.model_validate(FALSE_CARD))
    assert r3["claim_id"] == "c_003"
    assert r3["kill_result"].verdict == "REFUTED"

    # Board folded: three claims via same journal file (no second writer)
    evs = replay(tmp_path / "journal.jsonl")
    board = fold_claims(evs)
    assert set(board.keys()) == {"c_001", "c_002", "c_003"}
    # Verify journal carries every expected type and replays clean
    types = {e["type"] for e in evs}
    assert "worktree_spawned" in types
    assert "claim_posted" in types
    assert "claim_verification_routed" in types
    assert "check_executed" in types
    # No one-ClaimCard-per-run assumption: three Tier0 runs share the same session run_id
    assert len({e["run_id"] for e in evs}) == 1


def test_tier1_citation_drift_detection(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_1")
    disp = Dispatcher(j)
    wt = disp.spawn_worktree(provider="t", model_id="t/m", family="t", model_ref="t/m")
    card = ClaimCard.model_validate(
        {
            **TRUE_CARD,
            "statement_informal": "By lit_999 the claim holds for n.",
            "conclusion": {"expr": "n + 1 > n", "sympy_parseable": True},
        }
    )
    papers_empty = {"papers": [], "synthesis": "none"}
    r = disp.post_and_check_claim(wt["id"], card, papers_index=papers_empty)
    assert "lit_999" in r["tier1"]["missing_citations"]
