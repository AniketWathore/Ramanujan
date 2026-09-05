"""All pydantic v2 schemas — ramanujan/schemas.py (frozen v1)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ramanujan.taxonomy import CLAIM_TYPES_SET

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EVENT_TYPES: set[str] = {
    "run_started",
    "claim_registered",
    "llm_call",
    "encoding_attempted",
    "encoding_accepted",
    "encoding_failed",
    "check_executed",
    "counterexample_found",
    "counterexample_reverified",
    "claim_refuted",
    "claim_survived",
    "budget_event",
    "run_completed",
    "ground_truth_recorded",
    # v0.4 A6 (schema ADR, append-only): multi-model panel. Panelist LLM
    # calls reuse llm_call (role=panelist in payload); positions and the
    # advisory use these two types. Panel NEVER writes claim_refuted.
    "panel_position",
    "panel_advisory",
    # v2 Phase 1 (schema ADR, append-only): Initialiser + human checkpoints.
    # Only the three types Phase 1 emits; the rest of the §4.9 list lands
    # with the phase that first writes them.
    "problem_spec_created",
    "checkpoint_reached",
    "checkpoint_resolved",
}


class PanelPositionPayload(BaseModel):
    """One panelist's recorded position (round 1 sealed or round 2 revised)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    panel_run_id: str = Field(min_length=1)
    round: int = Field(ge=1, le=2)
    model_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    position: str  # support | doubt | object
    confidence: float = Field(ge=0.0, le=1.0)
    objection: str | None = None
    revised: bool = False

    @field_validator("position")
    @classmethod
    def check_position(cls, v: str) -> str:
        if v not in {"support", "doubt", "object"}:
            raise ValueError(f"invalid panel position: {v!r}")
        return v


class PanelAdvisoryPayload(BaseModel):
    """Deterministic aggregation of a panel run — advisory only, never a verdict."""

    model_config = ConfigDict(extra="forbid", strict=True)
    panel_run_id: str = Field(min_length=1)
    support: int = Field(ge=0)
    doubt: int = Field(ge=0)
    object: int = Field(ge=0)
    advisory: str = Field(min_length=1)


FACT_STATUSES: set[str] = {
    "unverified",
    "tier0-checked",
    "tier1-linted",
    "panel-verified",
    "formal",
    "plausibility-only",
    "refuted",
}

VERDICT_VALUES: set[str] = {"approve", "objection", "uncertain"}
SEVERITIES: set[str] = {"critical", "minor"}
RESOLUTIONS: set[str] = {"confirmed", "refuted", "partially-confirmed"}
GROUND_TRUTH_SOURCES: set[str] = {"human", "eval", "formalization", "later-refutation"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Journal event envelope (frozen)
# ---------------------------------------------------------------------------


class JournalEvent(BaseModel):
    """Envelope: {"ts": ISO-8601, "run_id": str, "type": event_type, "payload": {...}}"""

    model_config = ConfigDict(extra="forbid", strict=True)

    ts: str = Field(description="ISO-8601 timestamp")
    run_id: str = Field(min_length=1)
    type: str = Field(description="event type")
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {v!r}; allowed: {sorted(EVENT_TYPES)}")
        return v

    @field_validator("ts")
    @classmethod
    def check_ts(cls, v: str) -> str:
        # Accept ISO-8601; verify it parses
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception as e:
            raise ValueError(f"invalid ts ISO-8601: {v!r}: {e}") from e
        return v


# ---------------------------------------------------------------------------
# Fact schema
# ---------------------------------------------------------------------------


class FactHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    formal: str | None = None


class FactProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^f_\d+$")
    statement_informal: str = Field(min_length=1)
    statement_formal: str | None = None
    hypotheses: list[FactHypothesis] = Field(default_factory=list)
    conclusion: str = Field(min_length=1)
    claim_type: list[str] = Field(default_factory=list)
    status: str = Field(default="unverified")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    depends_on: list[str] = Field(default_factory=list)
    used_by: list[str] = Field(default_factory=list)
    provenance: FactProvenance
    verdict_history: list[str] = Field(default_factory=list)

    @field_validator("claim_type")
    @classmethod
    def check_claim_type(cls, v: list[str]) -> list[str]:
        for tag in v:
            if tag not in CLAIM_TYPES_SET:
                raise ValueError(f"invalid claim_type tag: {tag!r}")
        return v

    @field_validator("status")
    @classmethod
    def check_status(cls, v: str) -> str:
        if v not in FACT_STATUSES:
            raise ValueError(f"invalid fact status: {v!r}")
        return v


# ---------------------------------------------------------------------------
# Verdict schema (frozen)
# ---------------------------------------------------------------------------


class Objection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    anchor: str = Field(pattern=r"^o_\d+$")
    severity: str
    text: str = Field(min_length=1)

    @field_validator("severity")
    @classmethod
    def check_severity(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError(f"invalid severity: {v!r}")
        return v


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    verdict_schema: Literal["verdict.v2"] = "verdict.v2"
    verdict_id: str = Field(pattern=r"^v_\d+$")
    claim_id: str = Field(pattern=r"^f_\d+$")
    reviewer: str = Field(min_length=1, description="pinned model id")
    tier: int = Field(ge=0)
    verdict: str
    objections: list[Objection] = Field(default_factory=list)
    no_objection_confirmed: bool
    panel: list[str] = Field(default_factory=list)
    reduced_panel: bool = False

    @field_validator("verdict")
    @classmethod
    def check_verdict(cls, v: str) -> str:
        if v not in VERDICT_VALUES:
            raise ValueError(f"invalid verdict: {v!r}")
        return v


# ---------------------------------------------------------------------------
# Ground-truth event payload
# ---------------------------------------------------------------------------


class GroundTruthPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target: str = Field(pattern=r"^f_\d+$")
    resolution: str
    source: str

    @field_validator("resolution")
    @classmethod
    def check_resolution(cls, v: str) -> str:
        if v not in RESOLUTIONS:
            raise ValueError(f"invalid resolution: {v!r}")
        return v

    @field_validator("source")
    @classmethod
    def check_source(cls, v: str) -> str:
        if v not in GROUND_TRUTH_SOURCES:
            raise ValueError(f"invalid source: {v!r}")
        return v


# ---------------------------------------------------------------------------
# VerifierSpec (specs/verifier_specs/encoder.yaml)
# ---------------------------------------------------------------------------


class VerifierSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model_id: str = Field(min_length=1, description="exact snapshot ID, never alias")
    family: str = Field(min_length=1)
    role: str = Field(min_length=1)
    temperature: float = Field(ge=0.0, le=2.0)
    max_output_tokens: int = Field(gt=0)

    @field_validator("model_id")
    @classmethod
    def check_model_id(cls, v: str) -> str:
        # Forbid obvious aliases: must not be like "claude-sonnet" without date, etc.
        # We enforce snapshot-like: contains digit and '-' or '.'; bare alias fails.
        if re.match(r"^(claude|gpt|sonnet|opus|haiku)[-a-z]*$", v.lower()):
            raise ValueError(f"model_id looks like alias, not snapshot: {v!r}")
        return v


# ---------------------------------------------------------------------------
# Claim card DSL — the core IR
# ---------------------------------------------------------------------------


class Domain(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["int", "real", "finite_set_of_ints"] = Field(description="variable type")
    lo: int | float | None = None
    hi: int | float | None = None

    @model_validator(mode="after")
    def check_lo_hi(self) -> Domain:
        if self.lo is not None and self.hi is not None and self.lo is not None and self.hi is not None:
            try:
                if self.lo > self.hi:  # type: ignore[operator]
                    raise ValueError(f"domain lo > hi: {self.lo} > {self.hi}")
            except TypeError:
                pass
        return self


class Quantifier(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    var: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    kind: Literal["forall", "exists"]
    domain: Domain


class Conclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expr: str = Field(min_length=1)
    sympy_parseable: bool = True


class ClaimCard(BaseModel):
    """Restricted claim DSL — encoder target."""

    model_config = ConfigDict(extra="forbid", strict=True)

    card_id: str = Field(pattern=r"^c_\d+$")
    statement_informal: str = Field(min_length=1)
    claim_type: list[str] = Field(default_factory=list)
    quantifiers: list[Quantifier] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list, description="boolean exprs over vars")
    conclusion: Conclusion
    set_vars: list[str] = Field(default_factory=list)

    @field_validator("claim_type")
    @classmethod
    def check_claim_type(cls, v: list[str]) -> list[str]:
        for tag in v:
            if tag not in CLAIM_TYPES_SET:
                raise ValueError(f"invalid claim_type tag: {tag!r}")
        return v

    @model_validator(mode="after")
    def check_set_vars(self) -> ClaimCard:
        # set_vars must refer to quantifier vars whose domain is finite_set_of_ints
        qvars = {q.var: q for q in self.quantifiers}
        for sv in self.set_vars:
            if sv not in qvars:
                raise ValueError(f"set_var {sv!r} not in quantifiers")
            if qvars[sv].domain.type != "finite_set_of_ints":
                raise ValueError(f"set_var {sv!r} must have domain finite_set_of_ints")
        return self
