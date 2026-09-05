"""Tests for claims board + worktree — Phase 4."""

from pathlib import Path

from ramanujan.claims import fold_claims, post_claim, route_verification
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


def test_claim_post_and_fold_single_writer(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_1")
    card = ClaimCard.model_validate(PRIME_CARD)
    post_claim(j, claim_id="c_001", worktree_id="wt_001", card=card)
    post_claim(j, claim_id="c_002", worktree_id="wt_001", card=ClaimCard.model_validate(TRUE_CARD))
    # No separate file: everything in journal.jsonl via journal.py
    assert not (tmp_path / "claims_board.json").exists()
    evs = replay(tmp_path / "journal.jsonl")
    board = fold_claims(evs)
    assert set(board.keys()) == {"c_001", "c_002"}
    assert board["c_001"]["worktree_id"] == "wt_001"
    assert board["c_001"]["statement_informal"] == PRIME_CARD["statement_informal"]


def test_claim_fold_supersedes_same_id(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_1")
    card_a = ClaimCard.model_validate({**PRIME_CARD, "conclusion": {"expr": "is_prime(n**2 + n + 41)", "sympy_parseable": True}})
    card_b = ClaimCard.model_validate({**PRIME_CARD, "conclusion": {"expr": "is_prime(n**2 + n + 41 + 1)", "sympy_parseable": True}})
    post_claim(j, claim_id="c_001", worktree_id="wt_001", card=card_a)
    # Strengthened version with same claim_id
    post_claim(j, claim_id="c_001", worktree_id="wt_001", card=card_b)
    board = fold_claims(replay(tmp_path / "journal.jsonl"))
    assert board["c_001"]["card"]["conclusion"]["expr"] == "is_prime(n**2 + n + 41 + 1)"


def test_claim_verification_routed(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_1")
    card = ClaimCard.model_validate(PRIME_CARD)
    post_claim(j, claim_id="c_001", worktree_id="wt_001", card=card)
    route_verification(j, claim_id="c_001", verification_path="tier0", reason="tier0 available")
    board = fold_claims(replay(tmp_path / "journal.jsonl"))
    assert board["c_001"]["verification_path"] == "tier0"
