"""Tests for consolidation (Phase 8) — toolchain pinning + independent re-execution."""

import json
from pathlib import Path

from ramanujan.consolidation import consolidate
from ramanujan.journal import JournalWriter, replay
from ramanujan.orchestrator import Orchestrator
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

TRUE_GT = {
    "card_id": "c_0001",
    "statement_informal": "For every n >=0, n+1 > n.",
    "claim_type": ["inequality-estimate"],
    "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "n + 1 > n", "sympy_parseable": True},
    "set_vars": [],
}

TRUE_LE = {
    "card_id": "c_0001",
    "statement_informal": "For every n >=0, n+1 <= n.",
    "claim_type": ["inequality-estimate"],
    "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "n + 1 <= n", "sympy_parseable": True},
    "set_vars": [],
}


def test_consolidation_toolchain_mismatch_flagged(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_con")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    wt = orch.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    orch.post_and_check_claim(wt["id"], ClaimCard.model_validate(TRUE_GT))
    # Formal artifact for c_001 with lean v1
    lean_dir = tmp_path / "sess" / "lean"
    lean_dir.mkdir(parents=True, exist_ok=True)
    (lean_dir / "c_001.json").write_text(
        json.dumps({"lean_version": "lean4-v1", "mathlib_version": "mathlib-v1", "model_snapshot": "m1", "content": "proof"}),
        encoding="utf-8",
    )
    # First consolidation with same toolchain: no mismatch
    res1 = consolidate(j, tmp_path / "sess", toolchain_lean_version="lean4-v1", toolchain_mathlib_version="mathlib-v1", model_snapshot="m1")
    assert res1.mismatch is False
    assert res1.checkpoint_id is not None
    evs = replay(tmp_path / "journal.jsonl")
    assert any(e["type"] == "consolidation_completed" and not e["payload"]["mismatch"] for e in evs)
    assert any(e["type"] == "checkpoint_reached" and e["payload"]["stage"] == "consolidation" for e in evs)
    facts_dir = tmp_path / "sess" / "consolidation" / "facts"
    assert (facts_dir / "f_001.json").exists()
    data = json.loads((facts_dir / "f_001.json").read_text(encoding="utf-8"))
    assert data["status"] in ("formal", "tier0-checked", "panel-verified", "plausibility-only", "refuted")
    # Second consolidation after upgrade to v2: must visibly flag mismatch, not silently re-check
    res2 = consolidate(j, tmp_path / "sess", toolchain_lean_version="lean4-v2", toolchain_mathlib_version="mathlib-v1", model_snapshot="m1")
    assert res2.mismatch is True
    assert "lean4-v1" in (res2.mismatch_details or "") and "lean4-v2" in (res2.mismatch_details or "")
    evs2 = replay(tmp_path / "journal.jsonl")
    assert any(e["type"] == "consolidation_completed" and e["payload"]["mismatch"] for e in evs2)


def test_consolidation_independent_reexecution_and_coherence(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_con2")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    wt1 = orch.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    wt2 = orch.spawn_worktree(provider="b", model_id="b/m2", family="family:b", model_ref="b/m2")
    # Contradictory claims from different worktrees
    orch.post_and_check_claim(wt1["id"], ClaimCard.model_validate(TRUE_GT))
    orch.post_and_check_claim(wt2["id"], ClaimCard.model_validate(TRUE_LE))
    # Also add a refuted prime claim
    orch.post_and_check_claim(wt1["id"], ClaimCard.model_validate(PRIME_CARD))
    res = consolidate(j, tmp_path / "sess", toolchain_lean_version="lean4-v1", toolchain_mathlib_version="mathlib-v1", model_snapshot="m1")
    # Coherence: orchestrator flagged contradiction (same check via consolidation)
    assert len(res.contradictions) >= 1
    # Labeled fact set: should have 3 facts with statuses covering refuted + at least one tier0-checked/panel-verified etc.
    statuses = {f.status for f in res.facts}
    assert "refuted" in statuses
    # At least one fact should be formal|tier0-checked|panel-verified|plausibility-only (not just refuted)
    assert any(s in statuses for s in ("tier0-checked", "panel-verified", "formal", "plausibility-only"))
    # Facts are written and journal shows consolidation_completed with facts_count
    evs = replay(tmp_path / "journal.jsonl")
    comp = [e for e in evs if e["type"] == "consolidation_completed"]
    assert comp and comp[-1]["payload"]["facts_count"] == len(res.facts)
    assert comp[-1]["payload"]["contradictions_found"] == len(res.contradictions)


def test_cli_consolidate_toolchain_flag(tmp_path: Path):
    from click.testing import CliRunner

    from ramanujan.cli import main

    j = tmp_path / "journal.jsonl"
    sess = tmp_path / "sess"
    runner = CliRunner()
    runner.invoke(
        main,
        [
            "worktree",
            "spawn",
            "--provider",
            "a",
            "--model-id",
            "a/m1",
            "--family",
            "family:a",
            "--model-ref",
            "a/m1",
            "--journal",
            str(j),
            "--json",
        ],
    )
    card = tmp_path / "card.json"
    card.write_text(json.dumps(TRUE_GT), encoding="utf-8")
    runner.invoke(main, ["claim", "post", "--worktree-id", "wt_001", "--card-file", str(card), "--journal", str(j), "--json"])
    lean_dir = sess / "lean"
    lean_dir.mkdir(parents=True, exist_ok=True)
    (lean_dir / "c_001.json").write_text(
        json.dumps({"lean_version": "lean-v1", "mathlib_version": "m1", "model_snapshot": "snap1"}), encoding="utf-8"
    )
    res = runner.invoke(
        main,
        [
            "consolidate",
            "--journal",
            str(j),
            "--session-dir",
            str(sess),
            "--lean-version",
            "lean-v1",
            "--mathlib-version",
            "m1",
            "--model-snapshot",
            "snap1",
            "--json",
        ],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["mismatch"] is False
    # Upgrade
    res2 = runner.invoke(
        main,
        [
            "consolidate",
            "--journal",
            str(j),
            "--session-dir",
            str(sess),
            "--lean-version",
            "lean-v2",
            "--mathlib-version",
            "m1",
            "--model-snapshot",
            "snap1",
            "--json",
        ],
    )
    assert res2.exit_code == 0
    data2 = json.loads(res2.output)
    assert data2["mismatch"] is True
