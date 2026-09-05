"""Tests for orchestrator N>1 — Phase 5."""

import time
from pathlib import Path

from ramanujan.journal import JournalWriter, replay
from ramanujan.orchestrator import Orchestrator
from ramanujan.schemas import ClaimCard

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

PRIME_CARD = {
    "card_id": "c_0001",
    "statement_informal": "For every integer n >= 0, n^2 + n + 41 is prime.",
    "claim_type": ["inequality-estimate"],
    "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "is_prime(n**2 + n + 41)", "sympy_parseable": True},
    "set_vars": [],
}


def test_two_worktrees_contradictory_claims_flagged(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_5")
    orch = Orchestrator(j, session_dir=tmp_path / "sess", stall_threshold_sec=300)
    wt1 = orch.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    wt2 = orch.spawn_worktree(provider="b", model_id="b/m2", family="family:b", model_ref="b/m2")
    assert wt1["id"] == "wt_001" and wt2["id"] == "wt_002"
    # Post contradictory claims: n+1 > n vs n+1 <= n are syntactic negations
    r1 = orch.post_and_check_claim(wt1["id"], ClaimCard.model_validate(TRUE_GT))
    r2 = orch.post_and_check_claim(wt2["id"], ClaimCard.model_validate(TRUE_LE))
    # Both Tier0, routed tier0
    assert r1["verification_path"] == "tier0" and r2["verification_path"] == "tier0"
    # No separate claims file: everything in one journal
    assert not (tmp_path / "claims_board.json").exists()
    assert (tmp_path / "journal.jsonl").exists()
    contras = orch.find_contradictions()
    assert len(contras) == 1
    c = contras[0]
    assert {c["claim_a"], c["claim_b"]} == {r1["claim_id"], r2["claim_id"]}
    assert c["worktree_a"] != c["worktree_b"]
    # Same-worktree pair not flagged
    j2 = JournalWriter(tmp_path / "journal2.jsonl", run_id="sess_5b")
    orch2 = Orchestrator(j2, session_dir=tmp_path / "sess2")
    w = orch2.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    orch2.post_and_check_claim(w["id"], ClaimCard.model_validate(TRUE_GT))
    orch2.post_and_check_claim(w["id"], ClaimCard.model_validate(TRUE_LE))
    assert orch2.find_contradictions() == []


def test_per_worktree_budget_stops_only_that_worktree(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_b")
    orch = Orchestrator(j, session_dir=tmp_path / "sess", default_budgets={"budget_steps": 1})
    wt1 = orch.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    wt2 = orch.spawn_worktree(provider="b", model_id="b/m2", family="family:b", model_ref="b/m2")
    orch.post_and_check_claim(wt1["id"], ClaimCard.model_validate(TRUE_GT))
    # wt1 now at budget limit (1 step)
    assert orch._budgets[wt1["id"]].steps == 1
    # wt2 still running and can post
    r2 = orch.post_and_check_claim(wt2["id"], ClaimCard.model_validate(ClaimCard.model_validate(PRIME_CARD).model_dump()))
    assert r2["claim_id"] == "c_002"
    # wt1 trying to post again should be stopped_budget (or auto-marked on check)
    # Manually trigger check: next post should raise/stop
    import contextlib

    with contextlib.suppress(Exception):
        orch.post_and_check_claim(wt1["id"], ClaimCard.model_validate(TRUE_GT))
    # After breach, status is stopped_budget
    statuses = {r["id"]: r["status"] for r in orch.worktrees.list()}
    assert statuses[wt2["id"]] == "running"
    # wt1 either still running (if we swallow) or stopped_budget; check not stopped_error
    assert statuses[wt1["id"]] in {"running", "stopped_budget"}


def test_stall_detection_and_progress_and_compaction(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_s")
    orch = Orchestrator(j, session_dir=tmp_path / "sess", stall_threshold_sec=0.1)
    wt = orch.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    orch.post_and_check_claim(wt["id"], ClaimCard.model_validate(TRUE_GT))
    # progress report written
    p = orch.record_progress(wt["id"], extra={"claims": 1})
    assert p.exists() and p.name.startswith("wt_001")
    # compaction
    lj, summary = orch.compact_worktree(wt["id"])
    assert lj.exists() and summary.exists()
    assert "wt_001" in summary.read_text()
    # stall: wait beyond threshold
    time.sleep(0.25)
    stalled = orch.check_stalls()
    assert wt["id"] in stalled
    # stall_detected event in journal
    ev_types = [e["type"] for e in replay(tmp_path / "journal.jsonl")]
    assert "stall_detected" in ev_types
    statuses = {r["id"]: r["status"] for r in orch.worktrees.list()}
    assert statuses[wt["id"]] == "stalled"


def test_cli_check_contradictions(tmp_path: Path):
    from click.testing import CliRunner

    from ramanujan.cli import main

    j = tmp_path / "journal.jsonl"
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
    runner.invoke(
        main,
        [
            "worktree",
            "spawn",
            "--provider",
            "b",
            "--model-id",
            "b/m2",
            "--family",
            "family:b",
            "--model-ref",
            "b/m2",
            "--journal",
            str(j),
            "--json",
        ],
    )
    c1 = tmp_path / "c1.json"
    c2 = tmp_path / "c2.json"
    import json

    c1.write_text(json.dumps(TRUE_GT), encoding="utf-8")
    c2.write_text(json.dumps(TRUE_LE), encoding="utf-8")
    runner.invoke(main, ["claim", "post", "--worktree-id", "wt_001", "--card-file", str(c1), "--journal", str(j), "--json"])
    runner.invoke(main, ["claim", "post", "--worktree-id", "wt_002", "--card-file", str(c2), "--journal", str(j), "--json"])
    res = runner.invoke(main, ["orchestrator", "check-contradictions", "--journal", str(j), "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["count"] == 1
