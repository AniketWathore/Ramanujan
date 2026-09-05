"""Tests for v0.4 A6 panel schema (append-only) + CLI panel commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from ramanujan.journal import JournalWriter, replay
from ramanujan.schemas import PanelAdvisoryPayload, PanelPositionPayload


def test_panel_position_valid():
    p = PanelPositionPayload(
        panel_run_id="panel_abc",
        round=1,
        model_id="nvidia/model-a",
        provider="nvidia",
        position="doubt",
        confidence=0.7,
        objection="bound looks tight",
    )
    assert p.position == "doubt"


def test_panel_position_rejects_bad_position():
    with pytest.raises(ValidationError):
        PanelPositionPayload(
            panel_run_id="panel_abc",
            round=1,
            model_id="m",
            provider="p",
            position="refuted",  # not a position — verdicts belong to the engine
            confidence=0.9,
        )


def test_panel_advisory_valid():
    a = PanelAdvisoryPayload(panel_run_id="panel_abc", support=1, doubt=1, object=1, advisory="panel: 1 support / 1 doubt / 1 object")
    assert a.object == 1


def test_journal_accepts_panel_events_and_replays(tmp_path: Path):
    j = tmp_path / "journal.jsonl"
    w = JournalWriter(j, run_id="panel_abc")
    w.write("llm_call", {"model_id": "nvidia/model-a", "provider": "nvidia", "role": "panelist"})
    w.write(
        "panel_position",
        {
            "panel_run_id": "panel_abc",
            "round": 1,
            "model_id": "nvidia/model-a",
            "provider": "nvidia",
            "position": "doubt",
            "confidence": 0.7,
        },
    )
    w.write(
        "panel_advisory",
        {"panel_run_id": "panel_abc", "support": 0, "doubt": 1, "object": 0, "advisory": "panel: 0 support / 1 doubt / 0 object"},
    )
    events = replay(j)
    assert [e["type"] for e in events] == ["llm_call", "panel_position", "panel_advisory"]


def test_journal_rejects_bad_panel_position(tmp_path: Path):
    j = tmp_path / "journal.jsonl"
    w = JournalWriter(j, run_id="panel_abc")
    with pytest.raises((ValidationError, ValueError)):
        w.write(
            "panel_position",
            {"panel_run_id": "panel_abc", "round": 1, "model_id": "m", "provider": "p", "position": "refuted", "confidence": 0.9},
        )
    # Nothing written
    assert replay(j) == []


def test_old_journal_without_panel_still_replays(tmp_path: Path):
    # Backward compat: pre-A6 journals have no panel events and must still validate
    j = tmp_path / "journal.jsonl"
    w = JournalWriter(j, run_id="run_old")
    w.write("run_started", {"statement": "x"})
    w.write("claim_survived", {"stats": {}})
    events = replay(j)
    assert len(events) == 2


def test_cli_set_panel_and_warning(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(tmp_path / "config.toml"))
    from ramanujan.cli import main

    runner = CliRunner()
    # Add two same-family providers (fake keys, flags-only)
    for pid in ("mock-a", "mock-b"):
        res = runner.invoke(
            main,
            ["providers", "add", pid, "--name", pid, "--base-url", "http://127.0.0.1:9/v1", "--family", "mockfam", "--api-key", "fake"],
        )
        assert res.exit_code == 0, res.output
    # First panelist: no warning
    res = runner.invoke(main, ["roles", "set-panel", "mock-a", "mockfam/model-a"])
    assert res.exit_code == 0, res.output
    assert "Warning" not in res.output
    # Second same-family panelist: warning
    res = runner.invoke(main, ["roles", "set-panel", "mock-b", "mockfam/model-b"])
    assert res.exit_code == 0, res.output
    assert "Warning" in res.output
    assert "mockfam" in res.output
    # Alias pin rejected
    res = runner.invoke(main, ["roles", "set-panel", "mock-a", "model-a"])
    assert res.exit_code != 0
    # Clear
    res = runner.invoke(main, ["roles", "clear-panel"])
    assert res.exit_code == 0, res.output
    res = runner.invoke(main, ["roles", "show"])
    assert res.exit_code == 0
    assert "panel" in res.output.lower()
