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
