from __future__ import annotations

import json
from pathlib import Path

from ramanujan.journal import JournalWriter
from ramanujan.providers import load_spec


def _mock_caller_success(spec, messages):
    # Return factorial 2^n card
    card = {
        "card_id": "c_0001",
        "statement_informal": "For every integer n >= 4, n! > 2^n.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "factorial(n) > 2**n", "sympy_parseable": True},
        "set_vars": [],
    }
    return {"text": json.dumps(card), "input_tokens": 100, "output_tokens": 80, "cost": 0.001}


def _mock_caller_not_encodable(spec, messages):
    return {
        "text": json.dumps({"error": "NOT_ENCODABLE", "reason": "requires reals not in DSL"}),
        "input_tokens": 50,
        "output_tokens": 20,
        "cost": 0.0005,
    }


def _mock_caller_retry_then_success():
    calls = {"n": 0}

    def caller(spec, messages):
        calls["n"] += 1
        if calls["n"] == 1:
            # first return invalid JSON (bad claim_type)
            bad = {
                "card_id": "c_0001",
                "statement_informal": "x",
                "claim_type": ["not-a-tag"],
                "quantifiers": [],
                "hypotheses": [],
                "conclusion": {"expr": "n > 0", "sympy_parseable": True},
                "set_vars": [],
            }
            return {
                "text": json.dumps(bad),
                "input_tokens": 100,
                "output_tokens": 80,
                "cost": 0.001,
            }
        else:
            good = {
                "card_id": "c_0001",
                "statement_informal": "x",
                "claim_type": ["inequality-estimate"],
                "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
                "hypotheses": [],
                "conclusion": {"expr": "factorial(n) > 2**n", "sympy_parseable": True},
                "set_vars": [],
            }
            return {
                "text": json.dumps(good),
                "input_tokens": 100,
                "output_tokens": 80,
                "cost": 0.001,
            }

    caller.calls = calls  # type: ignore
    return caller


def test_encoder_success_mock(tmp_path: Path):
    from ramanujan.encoder import encode_statement

    spec = load_spec("specs/verifier_specs/encoder.yaml")
    journal = JournalWriter(tmp_path / "journal.jsonl", run_id="run_enc1")
    result = encode_statement("For every integer n >= 4, n! > 2^n.", spec, journal=journal, caller=_mock_caller_success)
    assert result.success
    assert result.card is not None
    assert result.card.card_id == "c_0001"
    assert result.card.conclusion.expr == "factorial(n) > 2**n"
    # journal has llm_call and encoding_attempted/accepted
    from ramanujan.journal import replay

    events = replay(tmp_path / "journal.jsonl")
    types = [e["type"] for e in events]
    assert "llm_call" in types
    assert "encoding_attempted" in types
    assert "encoding_accepted" in types


def test_encoder_not_encodable(tmp_path: Path):
    from ramanujan.encoder import encode_statement

    spec = load_spec("specs/verifier_specs/encoder.yaml")
    journal = JournalWriter(tmp_path / "journal.jsonl", run_id="run_enc2")
    result = encode_statement("For every real x > 0, sin(x) < x", spec, journal=journal, caller=_mock_caller_not_encodable)
    assert not result.success
    assert result.is_not_encodable
    assert "NOT_ENCODABLE" in result.error


def test_encoder_retry_on_validation_error(tmp_path: Path):
    from ramanujan.encoder import encode_statement

    spec = load_spec("specs/verifier_specs/encoder.yaml")
    journal = JournalWriter(tmp_path / "journal.jsonl", run_id="run_enc3")
    caller = _mock_caller_retry_then_success()
    result = encode_statement("For every integer n >= 4, n! > 2^n.", spec, journal=journal, caller=caller)
    assert result.success
    assert result.attempts == 2
    assert caller.calls["n"] == 2  # type: ignore
    from ramanujan.journal import replay

    events = replay(tmp_path / "journal.jsonl")
    # should have 2 llm_calls and 2 encoding_attempted, 1 accepted
    types = [e["type"] for e in events]
    assert types.count("llm_call") == 2
    assert types.count("encoding_attempted") == 2


def test_encoder_yaml_loads_pinned_snapshot():
    spec = load_spec("specs/verifier_specs/encoder.yaml")
    assert spec.model_id == "claude-sonnet-4-20250514"
    assert spec.provider == "anthropic"


def test_encoder_system_prompt_contains_all_taxonomy_tags():
    from ramanujan.encoder import ENCODER_SYSTEM
    from ramanujan.taxonomy import CLAIM_TYPES

    assert len(CLAIM_TYPES) == 10
    for tag in CLAIM_TYPES:
        assert tag in ENCODER_SYSTEM, f"prompt missing tag {tag!r}"
    # Worked stmt_05 example must match the planted mock claim_type exactly
    assert "is_prime(n**2 + n + 41)" in ENCODER_SYSTEM
    assert '"inequality-estimate"' in ENCODER_SYSTEM


def _mock_caller_always_invalid(spec, messages):
    bad = {
        "card_id": "c_0001",
        "statement_informal": "x",
        "claim_type": ["prime"],  # invented tag — the exact TUI failure
        "quantifiers": [],
        "hypotheses": [],
        "conclusion": {"expr": "n > 0", "sympy_parseable": True},
        "set_vars": [],
    }
    return {"text": json.dumps(bad), "input_tokens": 10, "output_tokens": 10, "cost": 0.0}


def test_encoder_validation_failure_is_encoder_error_not_not_encodable(tmp_path: Path):
    """DEFECT 1: invented claim_type tags after retries => encoder_error."""
    from ramanujan.encoder import encode_statement

    spec = load_spec("specs/verifier_specs/encoder.yaml")
    journal = JournalWriter(tmp_path / "journal.jsonl", run_id="run_enc_err")
    result = encode_statement("For every integer n >= 0, n^2 + n + 41 is prime.", spec, journal=journal, caller=_mock_caller_always_invalid)
    assert not result.success
    assert not result.is_not_encodable
    assert result.is_encoder_error
    assert result.status == "encoder_error"
    assert "NOT_ENCODABLE" not in (result.error or "")


def test_encoder_explicit_refusal_is_not_encodable(tmp_path: Path):
    from ramanujan.encoder import encode_statement

    spec = load_spec("specs/verifier_specs/encoder.yaml")
    journal = JournalWriter(tmp_path / "journal.jsonl", run_id="run_enc_ref")
    result = encode_statement("x", spec, journal=journal, caller=_mock_caller_not_encodable)
    assert not result.success
    assert result.is_not_encodable
    assert not result.is_encoder_error
    assert result.status == "not_encodable"
