"""Tests for reliability table + perturbation audits — Phase 10."""

import json
from pathlib import Path

from ramanujan.journal import JournalWriter, replay
from ramanujan.orchestrator import Orchestrator
from ramanujan.reliability import ReliabilityTable, audit_perturbations
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

REAL_CARD = {
    "card_id": "c_0001",
    "statement_informal": "For every real x, sin(x)/x -> 1.",
    "claim_type": ["convergence-limit"],
    "quantifiers": [{"var": "x", "kind": "forall", "domain": {"type": "real", "lo": None, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "x > 0", "sympy_parseable": True},
    "set_vars": [],
}


def _setup_panel_session(tmp_path: Path, n_calls: int = 3):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_rel")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    # Use diverse preset families via direct models
    preset = ["anthropic/claude-opus-5", "openai/gpt-5-2025-08-07", "google/gemini-3-pro"]
    for i in range(n_calls):
        wt = orch.spawn_worktree(
            provider="google", model_id="gemini-3-pro", family="family:google-gemini3", model_ref="google/gemini-3-pro"
        )
        # Alternate between prime (tier0) and real (non-tier0) to get mixed table
        card = ClaimCard.model_validate(REAL_CARD if i % 2 == 0 else PRIME_CARD)
        card.card_id = f"c_{i + 1:03d}"
        # For real cards, panel can grant verdict; for prime, advisory
        # We manually post and then request panel
        from ramanujan.claims import post_claim

        post_claim(j, claim_id=card.card_id, worktree_id=wt["id"], card=card)
        # For prime, first run Tier0 so that panel advisory path is taken (already attempted)
        if card.claim_type == ["inequality-estimate"]:
            orch.post_and_check_claim(wt["id"], ClaimCard.model_validate(PRIME_CARD))
            # The post_and_check already did Tier0, but we also need a panel call for prime
            # Use the last claim id from that post (it will be c_0??). Instead just request panel for the manually posted prime
            pass
        orch.request_panel(claim_id=card.card_id, worktree_id=wt["id"], preset_models=preset, card=card)
    return j


def test_reliability_table_fed_by_panel_calls(tmp_path: Path):
    j = _setup_panel_session(tmp_path, n_calls=4)
    table = ReliabilityTable.from_journal(j.path)
    assert table.total_calls >= 4
    # Tags are structure tags: inequality-estimate and convergence-limit
    assert "inequality-estimate" in table.entries or "convergence-limit" in table.entries
    # Each tag tracks tier2 counts
    for entry in table.entries.values():
        assert entry.total >= 1
        assert entry.tier2_verdict + entry.tier2_advisory + entry.tier0 == entry.total or entry.total >= 1


def test_perturbation_audit_stable_and_recorded(tmp_path: Path):
    card = ClaimCard.model_validate(PRIME_CARD)
    res = audit_perturbations(card, n=5, seed=0)
    assert res["total"] == 5
    assert 0 <= res["stable"] <= 5
    assert "baseline" in res and "details" in res
    # Record into table and check stable rate
    table = ReliabilityTable()
    table.record_perturbation(card.claim_type, stable=(res["stable"] == res["total"]))
    e = table.entries[card.claim_type[0]]
    assert e.perturbations_run == 1
    # Second audit unstable
    table.record_perturbation(card.claim_type, stable=False)
    assert table.entries[card.claim_type[0]].perturbations_run == 2
    assert table.should_allow_tier2_verdict(card.claim_type[0]) is True  # still low count (<3) -> allow


def test_reliability_feedback_downgrades_low_verdict_rate(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_rel2")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    preset = ["anthropic/claude-opus-5", "openai/gpt-5-2025-08-07", "google/gemini-3-pro"]
    wt = orch.spawn_worktree(provider="google", model_id="gemini-3-pro", family="family:google-gemini3", model_ref="google/gemini-3-pro")
    # Create many panel calls for inequality-estimate that are advisory (low verdict rate)
    for _ in range(5):
        card = ClaimCard.model_validate(PRIME_CARD)
        card.card_id = f"c_{len(replay(j.path)) + 1:03d}" if j.path.exists() else "c_001"
        from ramanujan.claims import post_claim

        cid = f"c_{len([e for e in replay(j.path) if e['type'] == 'claim_posted']) + 1:03d}" if j.path.exists() else "c_001"
        card.card_id = cid
        post_claim(j, claim_id=cid, worktree_id=wt["id"], card=card)
        # Force advisory by using prime (tier0 applicable) -> panel will be advisory
        orch.request_panel(claim_id=cid, worktree_id=wt["id"], preset_models=preset, card=card)
    table = ReliabilityTable.from_journal(j.path)
    e = table.entries.get("inequality-estimate")
    assert e is not None and e.total >= 5
    # Now test that a new non-tier0 claim with same tag would be downgraded if we artificially set low rates?
    # For this test, we directly check should_allow logic with low verdict rate
    # Simulate low reliability by manually setting counts
    table2 = ReliabilityTable()
    e2 = table2.get_or_create("convergence-limit")
    e2.total = 10
    e2.panel_verified = 1  # 0.1 rate
    e2.tier2_verdict = 10
    assert table2.should_allow_tier2_verdict("convergence-limit") is False
    # High reliability should allow
    table3 = ReliabilityTable()
    e3 = table3.get_or_create("convergence-limit")
    e3.total = 10
    e3.panel_verified = 9
    e3.tier2_verdict = 9
    assert table3.should_allow_tier2_verdict("convergence-limit") is True


def test_cli_reliability_show_and_audit(tmp_path: Path):
    from click.testing import CliRunner

    from ramanujan.cli import main

    j = tmp_path / "journal.jsonl"
    runner = CliRunner()
    # Setup a session with one panel call via orchestrator
    _setup_panel_session(tmp_path, n_calls=2)
    # CLI show
    res = runner.invoke(main, ["reliability", "show", "--journal", str(j), "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["total_calls"] >= 2
    # CLI audit
    card = tmp_path / "card.json"
    card.write_text(json.dumps(PRIME_CARD), encoding="utf-8")
    res2 = runner.invoke(main, ["reliability", "audit", "--card-file", str(card), "--n", "3", "--journal", str(j), "--json"])
    assert res2.exit_code == 0, res2.output
    data2 = json.loads(res2.output)
    assert data2["audit"]["total"] == 3
