from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ramanujan.journal import JournalWriter, rebuild_state, replay


def test_journal_round_trip(tmp_path: Path):
    p = tmp_path / "journal.jsonl"
    w = JournalWriter(p, run_id="run_test1")
    w.write("run_started", {"statement": "hello"})
    w.write("claim_registered", {"fact_id": "f_0001"})
    # file has 2 lines
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "ts" in obj and "run_id" in obj and "type" in obj and "payload" in obj
    # replay validates and returns
    events = replay(p)
    assert len(events) == 2
    assert events[0]["type"] == "run_started"
    assert events[0]["run_id"] == "run_test1"


def test_journal_replay_rebuilds_state(tmp_path: Path):
    p = tmp_path / "journal.jsonl"
    w = JournalWriter(p, run_id="run_a")
    w.write("run_started", {})
    w.write("ground_truth_recorded", {"target": "f_0001", "resolution": "confirmed", "source": "human"})
    w2 = JournalWriter(p, run_id="run_b")
    w2.write("run_started", {})
    state = rebuild_state(p)
    assert state["total"] == 3
    assert state["counts"]["run_started"] == 2
    assert state["counts"]["ground_truth_recorded"] == 1
    # idempotent
    state2 = rebuild_state(p)
    assert state == state2


def test_journal_invalid_event_rejected_and_not_written(tmp_path: Path):
    p = tmp_path / "journal.jsonl"
    w = JournalWriter(p, run_id="run_x")
    w.write("run_started", {})
    assert len(p.read_text().strip().splitlines()) == 1
    with pytest.raises((ValidationError, ValueError)):
        w.write("not_a_real_type", {})
    # still only 1 line
    assert len(p.read_text().strip().splitlines()) == 1
    # ground_truth with bad payload also rejected
    with pytest.raises((ValidationError, ValueError)):
        w.write("ground_truth_recorded", {"target": "f_0001", "resolution": "bad", "source": "human"})
    assert len(p.read_text().strip().splitlines()) == 1


def test_journal_replay_malformed_line_raises(tmp_path: Path):
    p = tmp_path / "journal.jsonl"
    p.write_text('{"ts":"2026-01-01T00:00:00Z","run_id":"r","type":"run_started","payload":{}}\nnot json\n')
    with pytest.raises(ValueError, match="invalid JSON"):
        replay(p)


def test_journal_llm_call_requires_model_id(tmp_path: Path):
    p = tmp_path / "journal.jsonl"
    w = JournalWriter(p, run_id="run_llm")
    with pytest.raises(ValueError, match="model_id"):
        w.write("llm_call", {"tokens": 10})
    w.write("llm_call", {"model_id": "claude-sonnet-4-20250514", "tokens": 10})
    assert len(replay(p)) == 1
