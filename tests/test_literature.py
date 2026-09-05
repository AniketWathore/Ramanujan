"""Tests for ramanujan/literature.py — Phase 2 provenance rule + three-way contract."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ramanujan.journal import JournalWriter, replay
from ramanujan.literature import (
    UNVERIFIED_PROVENANCE,
    PaperEntry,
    PapersIndex,
    survey_literature,
)

FAKE_MODEL_SPEC = SimpleNamespace(model_id="mock/lit-model", provider="mock", family="mock")

# Retrieved paper entry fixture.
RETRIEVED = {
    "title": "Cauchy–Davenport and friends",
    "authors": ["Cauchy"],
    "year": 1813,
    "source_url": "https://example.org/cauchy",
    "provenance": "retrieved",
    "relevance": "Classic sumset bound.",
    "note": "# note",
}

RECALLED = {
    "title": "A result I half-remember",
    "authors": [],
    "year": None,
    "source_url": None,
    "provenance": "model-memory, unverified",
    "relevance": "Possibly relevant.",
    "note": "",
}


def test_entry_accepts_retrieved_and_recalled():
    r = PaperEntry(id="lit_001", **RETRIEVED)
    assert r.provenance == "retrieved"
    m = PaperEntry(id="lit_002", **RECALLED)
    assert m.provenance == UNVERIFIED_PROVENANCE


def test_entry_rejects_unmarked_recall():
    # No URL + non-verbatim provenance → never validates (hallucination guard).
    with pytest.raises(ValidationError):
        PaperEntry(id="lit_001", title="t", relevance="r", source_url=None, provenance="retrieved")
    with pytest.raises(ValidationError):
        PaperEntry(id="lit_001", title="t", relevance="r", source_url=None, provenance="memory")
    # Bare defaults are SAFE by design: provenance defaults to the unverified tag.
    bare = PaperEntry(id="lit_001", title="t", relevance="r")
    assert bare.provenance == UNVERIFIED_PROVENANCE


def test_entry_rejects_url_without_retrieved_provenance():
    with pytest.raises(ValidationError):
        PaperEntry(
            id="lit_001",
            title="t",
            relevance="r",
            source_url="https://example.org/x",
            provenance="model-memory, unverified",
        )


def test_index_requires_synthesis():
    with pytest.raises(ValidationError):
        PapersIndex(papers=[], synthesis="")


def _caller(payload):
    def caller(spec, messages):
        return {"text": json.dumps(payload), "input_tokens": 1, "output_tokens": 1}

    return caller


def test_survey_mixed_provenance_success(tmp_path):
    j = JournalWriter(tmp_path / "j.jsonl", run_id="run_lit")
    payload = {"papers": [RETRIEVED, RECALLED], "synthesis": "Some known, some open."}
    res = survey_literature("sumsets?", journal=j, caller=_caller(payload), model_spec=FAKE_MODEL_SPEC)
    assert res.status == "index" and res.success
    assert res.index is not None
    assert [p.id for p in res.index.papers] == ["lit_001", "lit_002"]
    assert res.index.papers[1].provenance == UNVERIFIED_PROVENANCE
    assert res.index.synthesis == "Some known, some open."
    types = [e["type"] for e in replay(tmp_path / "j.jsonl")]
    assert types.count("literature_entry_added") == 2


def test_survey_refusal_is_not_searchable():
    payload = {"error": "NOT_SEARCHABLE", "reason": "not mathematics"}
    res = survey_literature("zzz", caller=_caller(payload), model_spec=FAKE_MODEL_SPEC, journal=None)
    assert res.status == "not_searchable"
    assert res.is_not_searchable and not res.is_literature_error


def test_survey_invalid_entries_then_error():
    bad = {"papers": [{"title": "t", "relevance": "r", "provenance": "memory"}], "synthesis": "s"}
    res = survey_literature("zzz", caller=_caller(bad), model_spec=FAKE_MODEL_SPEC, journal=None, max_retries=2)
    assert res.status == "literature_error"
    assert res.is_literature_error and not res.is_not_searchable
    assert res.attempts == 2


def test_survey_caller_failure_is_error():
    def caller(spec, messages):
        raise RuntimeError("down")

    res = survey_literature("zzz", caller=caller, model_spec=FAKE_MODEL_SPEC, journal=None)
    assert res.status == "literature_error"


def test_survey_parses_json_after_chain_of_thought():
    inner = json.dumps({"papers": [RECALLED], "synthesis": "Known in part."})
    thinking = (
        "Here's a thinking process:\n1. Analyze {the problem} carefully.\n"
        "2. Note braces like {x} in prose.\n3. Answer below.\n" + inner + "\nHope this helps!"
    )

    def caller(spec, messages):
        return {"text": thinking, "input_tokens": 1, "output_tokens": 1}

    res = survey_literature("sumsets?", caller=caller, model_spec=FAKE_MODEL_SPEC, journal=None)
    assert res.status == "index"
    assert res.index is not None and len(res.index.papers) == 1
    assert res.index.papers[0].provenance == UNVERIFIED_PROVENANCE


def test_keyless_empty_index_is_honest_success(tmp_path):
    j = JournalWriter(tmp_path / "j.jsonl", run_id="run_lit0")
    res = survey_literature("sumsets?", journal=j, model_spec=None)
    assert res.status == "index" and res.success
    assert res.index is not None and res.index.papers == []
    assert "no LLM key" in res.index.synthesis
