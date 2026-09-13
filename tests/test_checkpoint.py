"""Tests for the reusable Checkpoint abstraction — Phase 1."""

import pytest

from ramanujan.checkpoint import CHECKPOINT_OPTIONS, CheckpointStore
from ramanujan.journal import JournalWriter, replay


def _store(tmp_path, run_id="run_cp"):
    j = JournalWriter(tmp_path / "j.jsonl", run_id=run_id)
    return CheckpointStore(j), tmp_path / "j.jsonl"


def test_propose_confirm_journaled(tmp_path):
    store, jpath = _store(tmp_path)
    rec = store.propose(stage="initialiser", output_ref="run run_x problem_spec (inline)", prompt="Confirm?")
    assert rec.checkpoint_id == "cp_001"
    assert rec.status == "pending"
    assert rec.options == ["confirm", "revise"] == CHECKPOINT_OPTIONS  # no stop option, ever
    assert store.pending() == [rec]
    store.confirm("cp_001")
    assert rec.status == "confirmed"
    assert store.pending() == []
    types = [e["type"] for e in replay(jpath)]
    assert types == ["checkpoint_reached", "checkpoint_resolved"]
    folded = CheckpointStore.fold_checkpoints(replay(jpath))
    assert folded["cp_001"]["status"] == "confirmed"


def test_revise_loops_until_confirmed(tmp_path):
    store, jpath = _store(tmp_path)
    rec = store.propose(stage="literature", output_ref="literature/summary.md", prompt="Confirm?")
    store.revise("cp_001", "add the 2024 survey")
    assert rec.status == "pending"  # re-presented, not resolved
    assert rec.revision == 1
    assert rec.feedback == ["add the 2024 survey"]
    store.revise("cp_001", "still missing methods section")
    assert rec.revision == 2
    store.confirm("cp_001")
    assert rec.status == "confirmed"
    folded = CheckpointStore.fold_checkpoints(replay(jpath))
    assert folded["cp_001"] == {"status": "confirmed", "revision": 2, "stage": "literature"}


def test_confirm_unknown_and_double_confirm_raise(tmp_path):
    store, _ = _store(tmp_path)
    with pytest.raises(KeyError):
        store.confirm("cp_999")
    store.propose(stage="s", output_ref="o", prompt="p")
    store.confirm("cp_001")
    with pytest.raises(ValueError):
        store.confirm("cp_001")
    with pytest.raises(ValueError):
        store.revise("cp_001", "too late")


def test_ids_increment_and_get(tmp_path):
    store, _ = _store(tmp_path)
    a = store.propose(stage="a", output_ref="oa", prompt="pa")
    b = store.propose(stage="b", output_ref="ob", prompt="pb")
    assert (a.checkpoint_id, b.checkpoint_id) == ("cp_001", "cp_002")
    assert store.get("cp_002") is b
    assert store.get("cp_404") is None


def test_cli_invocations_share_one_checkpoint_sequence(tmp_path):
    """Two CLI invocations must not both mint cp_001 (the TUI 'no checkpoint' bug)."""
    import json

    from click.testing import CliRunner

    from ramanujan.cli import _rehydrate_checkpoint_counter, main

    j = tmp_path / "journal.jsonl"
    runner = CliRunner()
    r1 = runner.invoke(main, ["initialise", "--statement", "For every integer n >= 0, n + 1 > n.", "--journal", str(j), "--json"])
    assert r1.exit_code == 0, r1.output
    assert json.loads(r1.output)["checkpoint_id"] == "cp_001"
    r2 = runner.invoke(
        main, ["literature", "--statement", "For every integer n >= 0, n + 1 > n.", "--journal", str(j), "--json"]
    )
    assert r2.exit_code == 0, r2.output
    assert json.loads(r2.output)["checkpoint_id"] == "cp_002"
    # Helper is a no-op on a missing journal and keeps existing counters otherwise.
    store, _ = _store(tmp_path, run_id="other")
    _rehydrate_checkpoint_counter(store, str(tmp_path / "missing.jsonl"))
    assert store._counter == 0


def test_c_summary_consolidate_scope_to_session_worktrees(tmp_path):
    """--worktree-id scopes c-summary/consolidate to one problem (no stale mixing)."""
    import json

    from click.testing import CliRunner

    from ramanujan.cli import main
    from ramanujan.schemas import ClaimCard

    j = tmp_path / "journal.jsonl"
    runner = CliRunner()
    for _ in range(2):
        r = runner.invoke(
            main,
            ["worktree", "spawn", "--provider", "t", "--model-id", "t/m", "--family", "t", "--model-ref", "t/m", "--journal", str(j), "--json"],
        )
        assert r.exit_code == 0, r.output
    card = {
        "card_id": "c_0001",
        "statement_informal": "For every integer n >= 0, n + 1 > n.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "n + 1 > n", "sympy_parseable": True},
        "set_vars": [],
    }
    p1 = tmp_path / "c1.json"
    p1.write_text(json.dumps(ClaimCard.model_validate(card).model_dump()), encoding="utf-8")
    r = runner.invoke(main, ["claim", "post", "--worktree-id", "wt_001", "--card-file", str(p1), "--journal", str(j), "--json"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(main, ["checkpoint", "c-summary", "--journal", str(j), "--worktree-id", "wt_002", "--json"])
    assert r.exit_code == 0, r.output
    scoped = json.loads(r.output)
    assert [w["worktree_id"] for w in scoped["worktrees"]] == ["wt_002"]
    r = runner.invoke(main, ["consolidate", "--journal", str(j), "--session-dir", str(tmp_path), "--worktree-id", "wt_002", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["facts_count"] == 0
    r = runner.invoke(main, ["consolidate", "--journal", str(j), "--session-dir", str(tmp_path), "--worktree-id", "wt_001", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["facts_count"] == 1
