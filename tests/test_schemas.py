from __future__ import annotations

import pytest
from pydantic import ValidationError

from ramanujan.schemas import (
    ClaimCard,
    Domain,
    Fact,
    FactProvenance,
    GroundTruthPayload,
    JournalEvent,
    Verdict,
    VerifierSpec,
)


def test_journal_event_valid():
    ev = JournalEvent(ts="2026-01-01T00:00:00Z", run_id="run_abc", type="run_started", payload={"statement": "hi"})
    assert ev.type == "run_started"


def test_journal_event_invalid_type_rejected():
    with pytest.raises(ValidationError):
        JournalEvent(ts="2026-01-01T00:00:00Z", run_id="run_abc", type="not_a_type", payload={})


def test_journal_event_invalid_ts_rejected():
    with pytest.raises(ValidationError):
        JournalEvent(ts="not-a-time", run_id="run_abc", type="run_started", payload={})


def test_fact_claim_type_validated():
    with pytest.raises(ValidationError):
        Fact(
            id="f_0001",
            statement_informal="x",
            conclusion="y",
            claim_type=["not-a-tag"],
            status="unverified",
            confidence=0.0,
            provenance=FactProvenance(run_id="run_1", created_by="test"),
        )


def test_verdict_requires_objection_anchor_pattern():
    with pytest.raises(ValidationError):
        Verdict(
            verdict_id="v_0001",
            claim_id="f_0001",
            reviewer="claude-sonnet-4-20250514",
            tier=0,
            verdict="approve",
            objections=[{"anchor": "bad", "severity": "critical", "text": "oops"}],
            no_objection_confirmed=True,
        )


def test_ground_truth_payload_valid():
    gt = GroundTruthPayload(target="f_0001", resolution="confirmed", source="human")
    assert gt.resolution == "confirmed"


def test_ground_truth_invalid_resolution():
    with pytest.raises(ValidationError):
        GroundTruthPayload(target="f_0001", resolution="nope", source="human")


def test_verifier_spec_rejects_alias():
    with pytest.raises(ValidationError):
        VerifierSpec(
            name="encoder",
            provider="anthropic",
            model_id="claude-sonnet",
            family="anthropic",
            role="encoder",
            temperature=0,
            max_output_tokens=2048,
        )


def test_verifier_spec_accepts_snapshot():
    s = VerifierSpec(
        name="encoder",
        provider="anthropic",
        model_id="claude-sonnet-4-20250514",
        family="anthropic",
        role="encoder",
        temperature=0,
        max_output_tokens=2048,
    )
    assert s.model_id == "claude-sonnet-4-20250514"


def test_claim_card_set_vars_validation():
    # set_var not in quantifiers -> error
    with pytest.raises(ValidationError):
        ClaimCard(
            card_id="c_0001",
            statement_informal="hi",
            claim_type=["inequality-estimate"],
            quantifiers=[{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
            hypotheses=[],
            conclusion={"expr": "n > 0", "sympy_parseable": True},
            set_vars=["A"],
        )


def test_claim_card_domain_lo_gt_hi_rejected():
    with pytest.raises(ValidationError):
        Domain(type="int", lo=10, hi=5)


def test_fact_status_invalid():
    with pytest.raises(ValidationError):
        Fact(
            id="f_0001",
            statement_informal="x",
            conclusion="y",
            claim_type=[],
            status="bogus",
            confidence=0.0,
            provenance=FactProvenance(run_id="run_1", created_by="test"),
        )
