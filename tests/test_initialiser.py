"""Tests for initialise_statement three-way contract — Phase 1."""

import json
from pathlib import Path
from types import SimpleNamespace

from ramanujan.encoder import EncodeResult
from ramanujan.journal import JournalWriter, replay
from ramanujan.problem_spec import initialise_statement
from ramanujan.schemas import ClaimCard
from tests.test_problem_spec import PRIME_CARD

STATEMENT = PRIME_CARD["statement_informal"]

# Minimal stand-in for a resolved model spec (pin validation skips it:
# provider "mock" is neither first-party nor openai-compatible-listed).
FAKE_MODEL_SPEC = SimpleNamespace(model_id="mock/spec-model", provider="mock", family="mock")


def _card():
    return ClaimCard.model_validate(PRIME_CARD)


def _encode_ok(stmt):
    return EncodeResult(card=_card(), error=None, raw="{}", attempts=1)


def _encode_refused(stmt):
    return EncodeResult(card=None, error="NOT_ENCODABLE: no quantifiers", raw="{}", attempts=1)


def _encode_failed(stmt):
    return EncodeResult(card=None, error="ClaimCard validation failed: bad tag", raw="{}", attempts=3)


def _spec_caller(body):
    def caller(spec, messages):
        return {"text": json.dumps(body), "input_tokens": 1, "output_tokens": 1}

    return caller


def test_derive_path_success(tmp_path):
    j = JournalWriter(tmp_path / "j.jsonl", run_id="run_t1")
    res = initialise_statement(STATEMENT, encode_fn=_encode_ok, journal=j)
    assert res.status == "spec"
    assert res.success and not res.is_not_initialisable and not res.is_initialiser_error
    assert res.spec is not None and res.spec.statement_formal is None
    assert res.numeric is not None and res.numeric.status == "refuted"
    assert res.numeric.counterexample == {"n": 40}
    assert res.numeric.smt_executed is False and res.numeric.run_smt is True
    types = [e["type"] for e in replay(tmp_path / "j.jsonl")]
    assert "problem_spec_created" in types
    assert "check_executed" in types


def test_llm_spec_body_used_when_caller_given():
    body = {
        "domain": ["number-theory"],
        "variables": [{"name": "n", "type": "nonnegative integer", "constraints": "n >= 0"}],
        "objective": "determine-truth-value",
        "known_special_cases": ["n=0 gives 41, prime"],
        "open_questions_for_user": [],
    }
    res = initialise_statement(STATEMENT, encode_fn=_encode_ok, caller=_spec_caller(body), model_spec=FAKE_MODEL_SPEC, journal=None)
    assert res.status == "spec"
    assert res.spec is not None
    assert res.spec.domain == ["number-theory"]
    assert res.spec.variables[0].type == "nonnegative integer"
    assert res.spec.statement_formal is None
    assert res.attempts == 1


def test_llm_refusal_is_not_initialisable():
    def caller(spec, messages):
        return {"text": '{"error": "NOT_INITIALISABLE", "reason": "no content"}'}

    res = initialise_statement(STATEMENT, encode_fn=_encode_ok, caller=caller, model_spec=FAKE_MODEL_SPEC, journal=None)
    assert res.status == "not_initialisable"
    assert res.is_not_initialisable and not res.is_initialiser_error
    assert res.spec is None and res.numeric is None


def test_llm_garbage_is_initialiser_error_not_refusal():
    def caller(spec, messages):
        return {"text": "not json at all"}

    res = initialise_statement(STATEMENT, encode_fn=_encode_ok, caller=caller, model_spec=FAKE_MODEL_SPEC, journal=None, max_retries=2)
    assert res.status == "initialiser_error"
    assert res.is_initialiser_error and not res.is_not_initialisable
    assert res.attempts == 2


def test_llm_call_failure_is_initialiser_error():
    def caller(spec, messages):
        raise RuntimeError("boom")

    res = initialise_statement(STATEMENT, encode_fn=_encode_ok, caller=caller, model_spec=FAKE_MODEL_SPEC, journal=None)
    assert res.status == "initialiser_error"
    assert "LLM call failed" in (res.error or "")


def test_upstream_encoder_refusal_propagates_as_not_initialisable():
    res = initialise_statement(STATEMENT, encode_fn=_encode_refused, journal=None)
    assert res.status == "not_initialisable"
    assert res.is_not_initialisable


def test_upstream_encoder_failure_is_initialiser_error():
    res = initialise_statement(STATEMENT, encode_fn=_encode_failed, journal=None)
    assert res.status == "initialiser_error"
    assert res.is_initialiser_error


def test_encode_fn_exception_is_initialiser_error():
    def encode_fn(stmt):
        raise RuntimeError("transport down")

    res = initialise_statement(STATEMENT, encode_fn=encode_fn, journal=None)
    assert res.status == "initialiser_error"


def test_spec_json_written_to_file(tmp_path: Path):
    j = JournalWriter(tmp_path / "j.jsonl", run_id="run_t2")
    res = initialise_statement(STATEMENT, encode_fn=_encode_ok, journal=j)
    assert res.spec is not None
    out = tmp_path / "problem_spec.json"
    out.write_text(json.dumps(res.spec.model_dump(), indent=2), encoding="utf-8")
    assert json.loads(out.read_text(encoding="utf-8"))["statement_formal"] is None
