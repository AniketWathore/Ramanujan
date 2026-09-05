"""Tests for Tier-2 panel authority (§2) — Phase 7."""

from pathlib import Path

from ramanujan.journal import JournalWriter, replay
from ramanujan.orchestrator import Orchestrator
from ramanujan.panel_service import is_tier0_applicable
from ramanujan.presets import save_presets
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

# Tier0 NOT applicable: real domain + convergence-limit (outside numeric fragment)
REAL_CARD = {
    "card_id": "c_0001",
    "statement_informal": "For every real x, sin(x)/x -> 1 as x->0.",
    "claim_type": ["convergence-limit"],
    "quantifiers": [{"var": "x", "kind": "forall", "domain": {"type": "real", "lo": None, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "x > 0", "sympy_parseable": True},
    "set_vars": [],
}


def test_tier0_applicability_splits_claims():
    assert is_tier0_applicable(ClaimCard.model_validate(PRIME_CARD)) is True
    assert is_tier0_applicable(ClaimCard.model_validate(REAL_CARD)) is False


def test_tier0_applicable_cannot_reach_panel_verified_via_tier2(tmp_path: Path, monkeypatch):
    # Preset with 3 distinct families — trustworthy, but authority still blocks tier0 claims
    presets_path = tmp_path / "presets.json"
    save_presets(
        {
            "diverse-3": ["anthropic/claude-opus-5", "openai/gpt-5-2025-08-07", "google/gemini-3-pro"],
        },
        presets_path,
    )
    monkeypatch.setenv("RAMANUJAN_PRESETS", str(presets_path))
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_t2a")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    wt = orch.spawn_worktree(provider="anthropic", model_id="claude-opus-5", family="family:anthropic-opus", model_ref="anthropic/claude-opus-5")
    # Post the Tier0-applicable claim via Tier0 (so it's been attempted)
    r = orch.post_and_check_claim(wt["id"], ClaimCard.model_validate(PRIME_CARD))
    assert r["verification_path"] == "tier0"
    # Now request panel for that claim — must be advisory-only, never panel-verified
    preset_models = ["anthropic/claude-opus-5", "openai/gpt-5-2025-08-07", "google/gemini-3-pro"]
    res = orch.request_panel(claim_id=r["claim_id"], worktree_id=wt["id"], preset_models=preset_models)
    assert res["verification_path"] == "tier2-advisory-only"
    assert res["verdict"] != "panel-verified"
    # Journal never contains panel-verified for this claim
    evs = replay(tmp_path / "journal.jsonl")
    routed = [e for e in evs if e["type"] == "claim_verification_routed" and e["payload"]["claim_id"] == r["claim_id"]]
    assert any(e["payload"]["verification_path"] == "tier2-advisory-only" for e in routed)
    assert not any(e["type"] == "panel_verdict_issued" and e["payload"].get("verdict") == "panel-verified" and e["payload"]["claim_id"] == r["claim_id"] for e in evs)


def test_unattempted_tier0_cannot_fall_through_to_panel_verdict(tmp_path: Path, monkeypatch):
    presets_path = tmp_path / "presets.json"
    save_presets({"diverse-3": ["anthropic/claude-opus-5", "openai/gpt-5-2025-08-07", "google/gemini-3-pro"]}, presets_path)
    monkeypatch.setenv("RAMANUJAN_PRESETS", str(presets_path))
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_t2b")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    wt = orch.spawn_worktree(provider="anthropic", model_id="claude-opus-5", family="family:anthropic-opus", model_ref="anthropic/claude-opus-5")
    # Post claim WITHOUT running Tier0 — manually post to board via claims.post_claim (bypass dispatcher Tier0)
    from ramanujan.claims import post_claim

    card = ClaimCard.model_validate(PRIME_CARD)
    card.card_id = "c_001"
    post_claim(j, claim_id="c_001", worktree_id=wt["id"], card=card)
    # Panel request should route to tier0, never tier2-verdict, because Tier0 not yet attempted
    res = orch.request_panel(claim_id="c_001", worktree_id=wt["id"], preset_models=["anthropic/claude-opus-5", "openai/gpt-5-2025-08-07", "google/gemini-3-pro"])
    assert res["verification_path"] == "tier0"
    assert "not yet attempted" in res["reason"].lower()


def test_non_tier0_claim_can_reach_panel_verified_with_cross_family(tmp_path: Path, monkeypatch):
    presets_path = tmp_path / "presets.json"
    save_presets({"diverse-3": ["anthropic/claude-opus-5", "openai/gpt-5-2025-08-07", "google/gemini-3-pro"]}, presets_path)
    monkeypatch.setenv("RAMANUJAN_PRESETS", str(presets_path))
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_t2c")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    wt = orch.spawn_worktree(provider="anthropic", model_id="claude-opus-5", family="family:anthropic-opus", model_ref="anthropic/claude-opus-5")
    # Non-Tier0 claim: no Tier0 attempt needed
    from ramanujan.claims import post_claim

    card = ClaimCard.model_validate(REAL_CARD)
    card.card_id = "c_001"
    post_claim(j, claim_id="c_001", worktree_id=wt["id"], card=card)
    res = orch.request_panel(claim_id="c_001", worktree_id=wt["id"], preset_models=["anthropic/claude-opus-5", "openai/gpt-5-2025-08-07", "google/gemini-3-pro"])
    assert res["verification_path"] == "tier2-verdict"
    assert res["verdict"] == "panel-verified"
    evs = replay(tmp_path / "journal.jsonl")
    assert any(e["type"] == "panel_verdict_issued" and e["payload"]["verification_path"] == "tier2-verdict" for e in evs)


def test_single_family_preset_deadlocked_never_panel_verified(tmp_path: Path, monkeypatch):
    presets_path = tmp_path / "presets.json"
    # Single family via vendor relabel (same weights, same family — must be treated as one)
    save_presets({"solo": ["openai/gpt-5-2025-08-07", "openrouter/gpt-5"]}, presets_path)
    monkeypatch.setenv("RAMANUJAN_PRESETS", str(presets_path))
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_t2d")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    wt = orch.spawn_worktree(provider="openai", model_id="gpt-5-2025-08-07", family="family:openai-gpt5", model_ref="openai/gpt-5-2025-08-07")
    from ramanujan.claims import post_claim

    card = ClaimCard.model_validate(REAL_CARD)
    card.card_id = "c_001"
    post_claim(j, claim_id="c_001", worktree_id=wt["id"], card=card)
    # Even though Tier0 not applicable, single-family preset can never grant panel-verified
    # Provide solo preset models — same family as caller, eligible becomes empty
    res = orch.request_panel(claim_id="c_001", worktree_id=wt["id"], preset_models=["openai/gpt-5-2025-08-07", "openrouter/gpt-5"])
    assert res["verification_path"] == "tier2-advisory-only"
    assert res["verdict"] != "panel-verified"
