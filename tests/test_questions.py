"""Tests for micro question queue (Pattern B) — Phase 6."""

import time
from pathlib import Path

from ramanujan.journal import JournalWriter, replay
from ramanujan.orchestrator import Orchestrator
from ramanujan.questions import QuestionStore


def test_question_post_nullable_worktree_id(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_q")
    qs = QuestionStore(j, session_dir=tmp_path / "sess")
    # Orchestrator-level question (nullable)
    rec = qs.post_question(question="stop rest or keep running?", timeout_default="let the rest keep running", worktree_id=None, agent_label="orchestrator", timeout_sec=0.1)
    assert rec["worktree_id"] is None
    assert rec["timeout_default"] == "let the rest keep running"
    # Per-worktree question
    _ = qs.post_question(question="use lemma X?", timeout_default="assume no", worktree_id="wt_001", timeout_sec=300)
    evs = replay(tmp_path / "journal.jsonl")
    folded = QuestionStore.fold_questions(evs)
    assert folded["q_001"]["worktree_id"] is None
    assert folded["q_002"]["worktree_id"] == "wt_001"
    assert folded["q_001"]["status"] == "open"


def test_question_timeout_default_surfaced_in_checkpoint_c(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_q2")
    orch = Orchestrator(j, session_dir=tmp_path / "sess", stall_threshold_sec=300, question_timeout_sec=0.01)
    wt = orch.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    # Orchestrator-level question: micro question, default "let the rest keep running"
    q = orch.post_question(question="wt_2 has panel-verified. Stop rest?", timeout_default="let the rest keep running", worktree_id=None, agent_label="orchestrator", timeout_sec=0.05)
    assert q["worktree_id"] is None
    # Per-worktree question
    q2 = orch.post_question(question="should i use approach B?", timeout_default="assume no", worktree_id=wt["id"], timeout_sec=0.05)
    assert q2["worktree_id"] == wt["id"]
    # Don't answer; wait for timeout
    time.sleep(0.2)
    defaulted = orch.check_question_timeouts()
    assert len(defaulted) == 2
    assert {d["question_id"] for d in defaulted} == {"q_001", "q_002"}
    # Checkpoint C must surface every timeout default unmissably
    summary = orch.checkpoint_c_summary()
    assert summary["defaults_count"] == 2
    assert len(summary["timeout_defaults"]) == 2
    # Propose Checkpoint C: prompt must contain assumptions
    rec = orch.propose_checkpoint_c()
    assert "Timeout-assumed" in rec.prompt or "let the rest" in rec.prompt
    # Check shared/questions.jsonl mirror exists
    assert (tmp_path / "sess" / "shared" / "questions.jsonl").exists()
    # Journal contains question_answered_or_defaulted with defaulted status
    evs = replay(tmp_path / "journal.jsonl")
    defaulted_evs = [e for e in evs if e["type"] == "question_answered_or_defaulted" and e["payload"]["status"] == "defaulted"]
    assert len(defaulted_evs) == 2
    # Answering a question before timeout does not get defaulted
    j2 = JournalWriter(tmp_path / "journal2.jsonl", run_id="sess_q3")
    orch2 = Orchestrator(j2, session_dir=tmp_path / "sess3", question_timeout_sec=1.0)
    orch2.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    q3 = orch2.post_question(question="needs answer?", timeout_default="assume no", worktree_id="wt_001", timeout_sec=10)
    orch2.answer_question(q3["question_id"], answer="yes please", answered_by="wt_001")
    time.sleep(0.1)
    assert orch2.check_question_timeouts() == []
    summary2 = orch2.checkpoint_c_summary()
    assert summary2["defaults_count"] == 0


def test_primary_stop_question_is_pattern_b(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_q4")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    wt1 = orch.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    _ = orch.spawn_worktree(provider="b", model_id="b/m2", family="family:b", model_ref="b/m2")
    # When any worktree hits primary stop, orchestrator posts pattern B with orchestrator-level worktree_id None
    q = orch.primary_stop_question(verifying_worktree_id=wt1["id"])
    assert q["worktree_id"] is None
    assert q["agent_label"] == "orchestrator"
    assert q["timeout_default"] == "let the rest keep running"
    assert "wt_001 has a panel-verified" in q["question"]


def test_cli_question_post_and_checkpoint_c(tmp_path: Path):
    from click.testing import CliRunner

    from ramanujan.cli import main

    j = tmp_path / "journal.jsonl"
    runner = CliRunner()
    # Spawn one worktree so checkpoint C has a row
    runner.invoke(main, ["worktree", "spawn", "--provider", "a", "--model-id", "a/m1", "--family", "family:a", "--model-ref", "a/m1", "--journal", str(j), "--json"])
    # Orchestrator-level question via CLI (no worktree-id)
    res = runner.invoke(main, ["question", "post", "--question", "wt_1 resolved target, stop rest?", "--timeout-default", "let the rest keep running", "--journal", str(j), "--json"])
    assert res.exit_code == 0
    import json

    data = json.loads(res.output)
    assert data["worktree_id"] is None
    assert data["timeout_default"] == "let the rest keep running"
    # Checkpoint C summary via CLI should show worktree table and no defaults yet (not timed out)
    res2 = runner.invoke(main, ["checkpoint", "c-summary", "--journal", str(j), "--json"])
    assert res2.exit_code == 0
    s = json.loads(res2.output)
    assert len(s["worktrees"]) == 1
    assert s["worktrees"][0]["worktree_id"] == "wt_001"
    # Timeout case: post with tiny timeout, wait, check-timeouts, then c-summary shows defaults
    res3 = runner.invoke(main, ["question", "post", "--question", "tiny timeout?", "--timeout-default", "assume no", "--timeout-sec", "0.05", "--journal", str(j), "--json"])
    assert res3.exit_code == 0
    time.sleep(0.2)
    runner.invoke(main, ["question", "check-timeouts", "--journal", str(j), "--json"])
    res4 = runner.invoke(main, ["checkpoint", "c-summary", "--journal", str(j), "--json"])
    s2 = json.loads(res4.output)
    assert s2["defaults_count"] >= 1
