"""Tests for reviewer (Phase 9) — plain summary + appendix + final checkpoint."""

import json
from pathlib import Path

from ramanujan.journal import JournalWriter
from ramanujan.orchestrator import Orchestrator
from ramanujan.reviewer import synthesize_report
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


def test_reviewer_deterministic_report_contains_appendix(tmp_path: Path):
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_rev")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    wt1 = orch.spawn_worktree(provider="a", model_id="a/m1", family="family:a", model_ref="a/m1")
    wt2 = orch.spawn_worktree(provider="b", model_id="b/m2", family="family:b", model_ref="b/m2")
    orch.post_and_check_claim(wt1["id"], ClaimCard.model_validate(TRUE_GT))
    orch.post_and_check_claim(wt2["id"], ClaimCard.model_validate(TRUE_LE))
    # Consolidate to get facts
    from ramanujan.consolidation import consolidate

    consolidate(j, tmp_path / "sess", toolchain_lean_version="lean-v1", toolchain_mathlib_version="m1", model_snapshot="snap")
    # Synthesize deterministically (no LLM)
    facts = [json.loads(p.read_text()) for p in sorted((tmp_path / "sess" / "consolidation" / "facts").glob("*.json"))]
    worktrees = list(orch.worktrees.list())
    contras = orch.find_contradictions()
    res = synthesize_report(
        "For every n, n+1 > n vs n+1 <= n?", facts=facts, worktrees=worktrees, contradictions=contras, timeout_defaults=[]
    )
    assert res.status == "review"
    assert res.report_md is not None
    assert "## Summary" in res.report_md
    assert "## Technical Appendix" in res.report_md
    assert "### Labeled fact set" in res.report_md
    assert "### Worktree comparison" in res.report_md
    assert "### Failed approaches" in res.report_md
    # Failed approaches must be reported, not omitted
    assert "refuted" in res.report_md or "Failed" in res.report_md


def test_reviewer_not_reviewable_and_error():
    # NOT_REVIEWABLE via LLM
    def caller_not_reviewable(spec, messages):
        return {"text": json.dumps({"error": "NOT_REVIEWABLE", "reason": "no content"}), "input_tokens": 1, "output_tokens": 1}

    from types import SimpleNamespace

    fake_spec = SimpleNamespace(model_id="mock/m", provider="mock", family="mock")
    res = synthesize_report(
        "zzz", caller=caller_not_reviewable, model_spec=fake_spec, facts=[], worktrees=[], contradictions=[], timeout_defaults=[]
    )  # type: ignore[arg-type]
    assert res.status == "not_reviewable"
    assert res.is_not_reviewable

    # LLM failure → reviewer_error
    def caller_fail(spec, messages):
        raise RuntimeError("boom")

    res2 = synthesize_report(
        "zzz", caller=caller_fail, model_spec=fake_spec, facts=[], worktrees=[], contradictions=[], timeout_defaults=[]
    )  # type: ignore[arg-type]
    assert res2.status == "reviewer_error"
    assert res2.is_reviewer_error


def test_cli_review_and_final_checkpoint(tmp_path: Path):
    from click.testing import CliRunner

    from ramanujan.cli import main

    j = tmp_path / "journal.jsonl"
    sess = tmp_path / "sess"
    runner = CliRunner()
    # Minimal session: one worktree + one claim -> consolidate -> review
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
    runner.invoke(
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
            "snap",
            "--json",
        ],
    )
    # Review (keyless deterministic)
    res = runner.invoke(main, ["review", "--statement", "For every n, n+1 > n", "--journal", str(j), "--session-dir", str(sess), "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["status"] == "review"
    assert data["checkpoint_id"].startswith("cp_")
    assert Path(data["report_path"]).exists()
    text = Path(data["report_path"]).read_text(encoding="utf-8")
    assert "## Summary" in text
    assert "## Technical Appendix" in text
    assert "Failed approaches" in text
    # Feedback path: revise the checkpoint (re-run a stage) — use CheckpointStore directly
    from ramanujan.journal import replay

    evs = replay(j)
    cps = [e for e in evs if e["type"] == "checkpoint_reached" and e["payload"]["stage"] == "reviewer"]
    assert cps
    cp_id = cps[0]["payload"]["checkpoint_id"]
    # Simulate human feedback: store.revise with new data would be new checkpoint loop
    # For this test, just confirm it exists and can be confirmed
    assert cp_id.startswith("cp_")


def test_cli_review_with_mock_llm(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RAMANUJAN_MOCK_ENCODER", "1")
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
    res = runner.invoke(main, ["review", "--statement", "For every n, n+1 > n", "--journal", str(j), "--session-dir", str(sess), "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["status"] == "review"
    assert "Mock summary" in Path(data["report_path"]).read_text(encoding="utf-8")
