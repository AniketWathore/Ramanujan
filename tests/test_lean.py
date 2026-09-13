"""Tests for ramanujan/lean.py — per-worktree Lean verifier (advisory only)."""

import json
import os
import stat
from pathlib import Path

from ramanujan import lean as lean_mod
from ramanujan.dispatcher import Dispatcher
from ramanujan.journal import JournalWriter, replay
from ramanujan.schemas import ClaimCard

TRUE_CARD = {
    "card_id": "c_0001",
    "statement_informal": "For every integer n >= 0, n + 1 > n.",
    "claim_type": ["inequality-estimate"],
    "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
    "hypotheses": [],
    "conclusion": {"expr": "n + 1 > n", "sympy_parseable": True},
    "set_vars": [],
}


def test_lean_skipped_without_binary(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LEAN_BIN", "/nonexistent/lean_xyz_ramanujan")
    monkeypatch.delenv("LEAN_VERSION", raising=False)
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_lean")
    card = ClaimCard.model_validate(TRUE_CARD)
    res = lean_mod.verify_claim(card=card, worktree_id="wt_001", claim_id="c_001", session_dir=tmp_path, journal=j)
    assert res.status == "skipped"
    assert res.worktree_id == "wt_001" and res.claim_id == "c_001"
    out = tmp_path / "worktrees" / "wt_001" / "lean" / "c_001.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "skipped"
    types = [e["type"] for e in replay(tmp_path / "journal.jsonl")]
    assert "lean_verified" in types


def _make_fake_lean(tmp_path: Path, exit_code: int) -> str:
    script = tmp_path / f"fake_lean_{exit_code}.sh"
    script.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_lean_verified_and_failed_with_fake_binary(tmp_path: Path, monkeypatch):
    ok_bin = _make_fake_lean(tmp_path, 0)
    bad_bin = _make_fake_lean(tmp_path, 1)
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_lean2")
    card = ClaimCard.model_validate(TRUE_CARD)
    monkeypatch.setenv("LEAN_BIN", ok_bin)
    res_ok = lean_mod.verify_claim(
        card=card,
        worktree_id="wt_001",
        claim_id="c_001",
        session_dir=tmp_path,
        journal=j,
        lean_code="-- dummy lean source",
    )
    assert res_ok.status == "verified"
    monkeypatch.setenv("LEAN_BIN", bad_bin)
    res_bad = lean_mod.verify_claim(
        card=card,
        worktree_id="wt_001",
        claim_id="c_002",
        session_dir=tmp_path,
        journal=j,
        lean_code="-- dummy lean source",
    )
    assert res_bad.status == "failed"
    assert (tmp_path / "worktrees" / "wt_001" / "lean" / "c_001.json").exists()
    assert (tmp_path / "worktrees" / "wt_001" / "lean" / "c_002.json").exists()


def test_lean_skipped_without_source_when_binary_present(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LEAN_BIN", _make_fake_lean(tmp_path, 0))
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_lean3")
    card = ClaimCard.model_validate(TRUE_CARD)
    res = lean_mod.verify_claim(card=card, worktree_id="wt_001", claim_id="c_001", session_dir=tmp_path, journal=j)
    assert res.status == "skipped"


def test_dispatcher_claim_includes_lean_and_stores(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LEAN_BIN", "/nonexistent/lean_xyz_ramanujan")
    j = JournalWriter(tmp_path / "journal.jsonl", run_id="sess_1")
    disp = Dispatcher(j)
    wt = disp.spawn_worktree(provider="t", model_id="t/m", family="t", model_ref="t/m")
    r = disp.post_and_check_claim(wt["id"], ClaimCard.model_validate(TRUE_CARD))
    assert r["kill_result"].verdict == "SURVIVED"
    assert r["lean"]["status"] == "skipped"
    assert r["lean"]["worktree_id"] == wt["id"] and r["lean"]["claim_id"] == "c_001"
    out = tmp_path / "worktrees" / wt["id"] / "lean" / "c_001.json"
    assert out.exists()
    types = [e["type"] for e in replay(tmp_path / "journal.jsonl")]
    assert "lean_verified" in types
    # Lean never writes verdicts
    for e in replay(tmp_path / "journal.jsonl"):
        assert "lean" not in (e.get("payload") or {}) or e["type"] == "lean_verified"


def test_orchestrator_completion_verifies_worktree(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LEAN_BIN", "/nonexistent/lean_xyz_ramanujan")
    os.environ.pop("LEAN_VERSION", None)
    from ramanujan.journal import JournalWriter as JW
    from ramanujan.orchestrator import Orchestrator

    j = JW(tmp_path / "journal.jsonl", run_id="sess_o")
    orch = Orchestrator(j, session_dir=tmp_path / "sess")
    rec = orch.spawn_worktree(provider="t", model_id="t/m", family="t", model_ref="t/m")
    r = orch.post_and_check_claim(rec["id"], ClaimCard.model_validate(TRUE_CARD))
    assert r["lean"]["status"] == "skipped"
    orch.set_status(rec["id"], "completed")
    out = tmp_path / "sess" / "worktrees" / rec["id"] / "lean" / f"{r['claim_id']}.json"
    assert out.exists()
