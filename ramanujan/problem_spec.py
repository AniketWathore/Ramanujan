"""Stage 1 Initialiser — ramanujan/problem_spec.py (v2 Phase 1, trimmed scope).

Produces a structured ProblemSpec from an informal problem statement, plus a
NUMERIC-ONLY kill-check in a bare sandbox. Deliberate trims (Build Brief §4.3):
- `run_smt` is recorded as True in the config but SMT is NEVER executed here;
  SMT execution is deferred to Stage 3 worktrees. This module must not import
  `ramanujan.killcheck.smt` on any path.
- `statement_formal` is always None here; formalization happens in worktrees.

Three-way contract (mirrors encoder.EncodeResult — never conflate refusal with
system failure):
- `spec` — structured spec (+ numeric kill-check result) produced.
- `not_initialisable` — the model/encoder itself explicitly refused
  (NOT_ENCODABLE upstream, or its own NOT_INITIALISABLE).
- `initialiser_error` — model failure, timeout, or validation failure after
  retries. Never rendered as "outside scope".
"""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ramanujan.schemas import ClaimCard

Objective = Literal["prove", "refute", "determine-truth-value", "bound", "construct"]

OBJECTIVES: list[str] = ["prove", "refute", "determine-truth-value", "bound", "construct"]


class VariableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    type: str = Field(min_length=1, description="e.g. positive integer, real number, finite set of integers")
    constraints: str = Field(default="")


class KillCheckConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # Stage-1 is scope-agnostic by default for informal problems (None = no
    # pre-set limit, human chooses bounded N / sampling / symbolic at checkpoint).
    # For formal ClaimCards the engine still uses 1000 as safe sandbox default.
    run_smt: bool = True
    run_numeric_search: bool = True
    small_case_limit: int | None = Field(default=1000, gt=0, description="None = no pre-set limit, scope decided with human at checkpoint")


class ProblemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^prob_\d+$")
    domain: list[str] = Field(default_factory=list)
    statement_informal: str = Field(min_length=1)
    # Explicitly None at this stage; formalization happens inside worktrees.
    statement_formal: str | None = None
    variables: list[VariableSpec] = Field(default_factory=list)
    objective: Objective = "determine-truth-value"
    known_special_cases: list[str] = Field(default_factory=list)
    kill_check_config: KillCheckConfig = Field(default_factory=KillCheckConfig)
    open_questions_for_user: list[str] = Field(default_factory=list)


class NumericKillCheckResult(BaseModel):
    """Outcome of the Stage-1 numeric-only kill-check (never a verdict word)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["refuted", "survived"] = "survived"
    counterexample: dict[str, Any] | None = None
    double_verified: bool = False
    methods: list[str] = Field(default_factory=list)
    checked_total: int = Field(default=0, ge=0)
    # The §4.3 trim, recorded on every result: SMT configured but not run.
    run_smt: bool = True
    smt_executed: bool = False
    verify_disagreement: bool = False


INITIALISER_SYSTEM = """You are the Ramanujan Initialiser. Convert an informal math problem into a structured problem spec.

CRITICAL — OUTPUT RULES:
- Output ONLY a single JSON object — no markdown, no thinking process, no analysis.
- Do NOT output "Here's a thinking process:" or any chain-of-thought.

You MUST output STRICT JSON matching schema exactly:

{
  "domain": ["<subject areas, e.g. additive-combinatorics>"],
  "variables": [{"name": "n", "type": "positive integer", "constraints": "n > N0"}],
  "objective": "prove | refute | determine-truth-value | bound | construct",
  "known_special_cases": ["<small cases or instances already known>"],
  "open_questions_for_user": ["<ambiguities you need the user to resolve>"]
}

Rules:
- Do NOT formalize the statement (no statement_formal — that happens later).
- Pick the objective that matches what is asked: a conjecture asserting truth -> "refute" is not assumed; use "determine-truth-value" unless the user explicitly asks to prove/refute/bound/construct.
- If the problem is meaningless or has no mathematical content: {"error": "NOT_INITIALISABLE", "reason": "<why>"}
  ONLY refuse yourself when the problem truly has no specifiable content.
  NEVER emit NOT_INITIALISABLE because of a validation error — fix the JSON instead.
- Temperature 0, precise.
"""


def _extract_json(text: str) -> str:
    """Extract JSON object from LLM text (robust to thinking)."""
    text = text.strip()
    # Fenced blocks — take last that looks like problem spec (has domain)
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        for cand in reversed(fenced):
            try:
                parsed = json.loads(cand)
                if isinstance(parsed, dict) and ("domain" in parsed or "error" in parsed):
                    return cand
            except Exception:
                continue
        return fenced[-1]
    # Balanced spans — prefer last that contains domain/error
    spans: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        j = i
        while j < n:
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    spans.append(text[i : j + 1])
                    break
            j += 1
        i = j + 1 if j < n and depth == 0 else i + 1
    for cand in reversed(spans):
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict) and ("domain" in parsed or "error" in parsed):
                return cand
        except Exception:
            continue
    if spans:
        return spans[-1]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _domain_type_to_variable_type(domain_type: str) -> str:
    return {
        "int": "integer",
        "real": "real number",
        "finite_set_of_ints": "finite set of integers",
    }.get(domain_type, domain_type)


def derive_spec_from_card(
    statement: str,
    card: ClaimCard,
    *,
    prob_id: str = "prob_001",
    small_case_limit: int | None = 1000,
) -> ProblemSpec:
    """Deterministic keyless fallback: build the spec body from the card's quantifiers.

    Used when no LLM key resolves (demo without a key). Source is recorded in
    the open questions so a human knows the spec was derived, not reasoned.
    """
    variables: list[VariableSpec] = []
    for q in card.quantifiers:
        lo = q.domain.lo
        hi = q.domain.hi
        if q.domain.type == "finite_set_of_ints":
            constraints = ""
        elif lo is not None and hi is not None:
            constraints = f"{lo} <= {q.var} <= {hi}"
        elif lo is not None:
            constraints = f"{q.var} >= {lo}"
        elif hi is not None:
            constraints = f"{q.var} <= {hi}"
        else:
            constraints = ""
        variables.append(VariableSpec(name=q.var, type=_domain_type_to_variable_type(q.domain.type), constraints=constraints))
    return ProblemSpec(
        id=prob_id,
        domain=[],
        statement_informal=statement,
        statement_formal=None,
        variables=variables,
        objective="determine-truth-value",
        known_special_cases=[],
        kill_check_config=KillCheckConfig(run_smt=True, run_numeric_search=True, small_case_limit=small_case_limit),
        open_questions_for_user=[
            "Spec derived offline from the encoded card (no LLM key) — confirm the objective and subject domain.",
        ],
    )


def run_numeric_killcheck(
    card: ClaimCard,
    *,
    small_case_limit: int = 1000,
    journal: Any | None = None,
) -> NumericKillCheckResult:
    """Numeric-search-only kill-check. SMT is never attempted on this path.

    Runs the four numeric/set search methods, then confirms any candidate via
    the independent verifier (no shared helpers with search). A verifier
    disagreement is recorded, never a refutation.
    """
    # NOTE: ramanujan.killcheck.smt must never be imported here (§4.3 trim).
    from ramanujan.killcheck.numeric import (
        bounded_exhaustion,
        exhaustive_small_set,
        random_set_sampling,
        randomized_sampling,
    )
    from ramanujan.killcheck.verify import verify_counterexample

    methods: list[str] = []
    checked_total = 0
    verify_disagreement = False

    searches = [
        ("bounded_exhaustion", lambda: bounded_exhaustion(card, exhaustive_limit=small_case_limit)),
        ("randomized_sampling", lambda: randomized_sampling(card)),
        ("exhaustive_small_set", lambda: exhaustive_small_set(card)),
        ("random_set_sampling", lambda: random_set_sampling(card)),
    ]
    for name, fn in searches:
        try:
            candidate, stats = fn()
        except Exception:
            continue
        methods.append(name)
        with contextlib.suppress(Exception):
            checked_total += int(stats.get("checked", 0))
        if journal is not None:
            with contextlib.suppress(Exception):
                journal.write("check_executed", {"method": name, "stats": stats, "stage": "initialiser"})
        if candidate is None:
            continue
        ok, reason = verify_counterexample(card, candidate)
        if ok:
            logged = {k: (sorted(v) if isinstance(v, set) else v) for k, v in candidate.items()}
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.write("counterexample_found", {"assignment": logged, "method": name, "stage": "initialiser"})
                    journal.write("counterexample_reverified", {"reason": reason, "stage": "initialiser"})
            return NumericKillCheckResult(
                status="refuted",
                counterexample=logged,
                double_verified=True,
                methods=methods,
                checked_total=checked_total,
                run_smt=True,
                smt_executed=False,
            )
        verify_disagreement = True
    return NumericKillCheckResult(
        status="survived",
        counterexample=None,
        double_verified=False,
        methods=methods,
        checked_total=checked_total,
        run_smt=True,
        smt_executed=False,
        verify_disagreement=verify_disagreement,
    )


class InitialiseResult:
    """Three-way outcome: spec | not_initialisable | initialiser_error."""

    def __init__(
        self,
        spec: ProblemSpec | None,
        numeric: NumericKillCheckResult | None,
        error: str | None,
        attempts: int,
    ) -> None:
        self.spec = spec
        self.numeric = numeric
        self.error = error
        self.attempts = attempts
        self.is_not_initialisable = error is not None and "NOT_INITIALISABLE" in error

    @property
    def success(self) -> bool:
        return self.spec is not None

    @property
    def is_initialiser_error(self) -> bool:
        return not self.success and not self.is_not_initialisable

    @property
    def status(self) -> str:
        if self.success:
            return "spec"
        if self.is_not_initialisable:
            return "not_initialisable"
        return "initialiser_error"


def _fallback_spec(statement: str, prob_id: str, small_case_limit: int | None, note: str) -> ProblemSpec:
    """Minimal spec when no ClaimCard is available (Option 1: store problem, don't block).

    Stage-1 does NOT pre-impose a numeric limit — scope is decided with the
    human at Checkpoint A. Instead of small_case_limit we ask:
    bounded up to N | random sampling with budget | symbolic via worktrees | no limit.
    Heuristic domain/variable inference keeps Checkpoint A meaningful.
    """
    s = statement.lower()
    # Stage 1 informal: no pre-set numeric limit — human decides scope at checkpoint
    small_case_limit = None
    domain: list[str] = []
    variables: list[VariableSpec] = []
    known: list[str] = []
    objective: str = "determine-truth-value"
    # Heuristic: Collatz / 3n+1 / even-odd iteration
    if any(k in s for k in ["collatz", "3n+1", "3n + 1", "3 * n + 1", "divide it by 2", "multiply it by 3"]):
        domain = ["number-theory", "dynamical-systems"]
        variables = [VariableSpec(name="n", type="positive integer", constraints="n >= 1")]
        known = ["n=1 → 1, n=2 → 1, n=3 → 10→5→16→8→4→2→1"]
        objective = "determine-truth-value"
        # No pre-set limit for informal problems — human chooses scope at checkpoint
        small_case_limit = None
    elif any(k in s for k in ["prime", "even integer", "goldbach"]):
        domain = ["number-theory"]
        variables = [VariableSpec(name="n", type="integer", constraints="n > 2, n is even" if "even" in s else "")]
        small_case_limit = None
        # Goldbach is not a bounded check — verified to 4e18; worktrees do proof search, not exhaustive limit
    elif any(k in s for k in ["factorial", "n!"]):
        domain = ["number-theory"]
        variables = [VariableSpec(name="n", type="integer", constraints="n >= 0")]
    elif any(k in s for k in ["set", "|a", "sumset"]):
        domain = ["additive-combinatorics"]
    elif any(k in s for k in ["quantum", "particle", "eigenfunction", "ψ", "psi", "schrodinger", "wave function", "probability density", "probability current", "hamiltonian"]):
        domain = ["quantum-mechanics"]
        variables = []  # continuous x,t — not a bounded integer search
        objective = "prove"
    else:
        # Generic fallback: at least one variable so spec is not vacuously empty
        if "positive" in s and ("integer" in s or "number" in s or "whole number" in s):
            variables = [VariableSpec(name="n", type="positive integer", constraints="n >= 1")]
            domain = ["number-theory"]

    # Tailor scope question — Goldbach/Collatz get a concrete recommendation instead of 4-way choice
    if "goldbach" in s or ("even integer" in s and "prime" in s):
        scope_q = "No pre-set numeric limit — this is correct for Goldbach. Exhaustive bounded check up to N is not a proof (already verified to 4×10¹⁸). Recommend: confirm to proceed to Literature, then worktrees will attempt proof/search with budget caps (symbolic + heuristic). If you want an additional bounded sanity check, tell me N (e.g., 1e6) and I'll configure it — otherwise just confirm."
    elif "collatz" in s or "divide it by 2" in s:
        scope_q = "No pre-set numeric limit — correct for Collatz. Bounded exhaustive up to N is not a proof. Recommend: confirm to Literature, then worktrees with sampling/budget. If you want a bounded check (e.g., n ≤ 1e6), tell me N — otherwise just confirm."
    else:
        scope_q = "How would you like to proceed? No pre-set limit — tell me your preference and I'll configure worktrees: (a) bounded exhaustive up to N, (b) random sampling with budget, (c) symbolic proof via worktrees. Otherwise just confirm with current spec."
    return ProblemSpec(
        id=prob_id,
        domain=domain,
        statement_informal=statement,
        statement_formal=None,
        variables=variables,
        objective=objective,  # type: ignore[arg-type]
        known_special_cases=known,
        kill_check_config=KillCheckConfig(run_smt=True, run_numeric_search=True, small_case_limit=small_case_limit),
        open_questions_for_user=[note, scope_q],
    )


def initialise_statement(
    statement: str,
    *,
    encode_fn,
    journal: Any | None = None,
    caller=None,
    model_spec=None,
    prob_id: str = "prob_001",
    small_case_limit: int | None = 1000,
    max_retries: int = 3,
) -> InitialiseResult:
    """Build a ProblemSpec + numeric-only kill-check for a statement.

    `encode_fn(statement)` must return an encoder-style result with
    `.card` / `.error` / `.is_not_encodable` (e.g. encoder.EncodeResult).

    Option 1 (v2): the initial problem is stored as problem_spec.json and
    passed to Literature — it does NOT require a ClaimCard. If the encoder
    returns NOT_ENCODABLE or fails, we still produce a ProblemSpec (via LLM or
    fallback) and treat the numeric kill-check as not applicable (survived).

    When `model_spec` is given, the spec body is built by LLM (`caller` is an
    optional call_llm-compatible injection for tests; None means a real call);
    otherwise it is derived deterministically from the card when available,
    or via fallback when not.
    `statement_formal` is None on every path.
    """
    # 1. Try to encode — but do not fail the whole Initialiser if it does not produce a card.
    #    The numeric kill-check needs a card; if we have none, we treat it as not applicable.
    card: ClaimCard | None = None
    encode_error: str | None = None
    encode_is_not_encodable = False
    try:
        enc = encode_fn(statement)
        card = getattr(enc, "card", None)
        encode_error = getattr(enc, "error", None)
        encode_is_not_encodable = bool(getattr(enc, "is_not_encodable", False))
    except Exception as e:
        encode_error = f"encode failed: {e}"
        encode_is_not_encodable = False

    # 2. Spec body: LLM when a caller is provided, else deterministic derive.
    # Fast path for Stage 1 informal problems — they are NOT ClaimCards (card=None).
    # Don't burn 60s on LLM for the generic fallback; produce deterministic spec
    # and let the human refine it at Checkpoint A. Only use LLM when we have a
    # card-derived context or the caller explicitly wants LLM refinement.
    attempts = 0
    last_error = ""
    if model_spec is not None and not (card is None and encode_is_not_encodable):
        spec_body: dict[str, Any] | None = None
        from ramanujan.providers import call_llm

        messages = [
            {"role": "system", "content": INITIALISER_SYSTEM},
            {"role": "user", "content": f"Problem to specify:\n{statement}\n\nOutput strict JSON only."},
        ]
        for _attempt in range(max_retries):
            attempts += 1
            try:
                # Stage 1 must be fast — single LLM attempt, transport failure falls back to deterministic spec.
                resp = call_llm(model_spec, messages, journal=journal, caller=caller, retries=1)
                raw_text = resp["text"]
            except Exception as e:
                last_error = f"LLM call failed: {e}"
                # Fast fallback on transport/timeout/502 — don't burn 180s retrying for Stage 1.
                if "timed out" in str(e).lower() or "502" in str(e) or "503" in str(e) or "504" in str(e) or "api error" in str(e).lower():
                    break
                continue
            try:
                parsed = json.loads(_extract_json(raw_text))
            except Exception as e:
                last_error = f"JSON parse error: {e}"
                continue
            if isinstance(parsed, dict) and parsed.get("error") == "NOT_INITIALISABLE":
                reason = str(parsed.get("reason", "")).strip()
                # Guard placeholder the model sometimes echoes verbatim ("<why>")
                if not reason or reason == "<why>" or reason.lower() == "why":
                    last_error = f"spec validation failed: NOT_INITIALISABLE with empty/placeholder reason {reason!r}"
                    continue
                return InitialiseResult(spec=None, numeric=None, error=f"NOT_INITIALISABLE: {reason}", attempts=attempts)
            try:
                body = {
                    "domain": list(parsed.get("domain", [])),
                    "variables": list(parsed.get("variables", [])),
                    "objective": parsed.get("objective", "determine-truth-value"),
                    "known_special_cases": list(parsed.get("known_special_cases", [])),
                    "open_questions_for_user": list(parsed.get("open_questions_for_user", [])),
                }
                if body["objective"] not in OBJECTIVES:
                    raise ValueError(f"invalid objective: {body['objective']!r}")
                # Validate through the real schema (variables typed).
                ProblemSpec(
                    id=prob_id,
                    domain=body["domain"],
                    statement_informal=statement,
                    statement_formal=None,
                    variables=body["variables"],
                    objective=body["objective"],  # type: ignore[arg-type]
                    known_special_cases=body["known_special_cases"],
                    open_questions_for_user=body["open_questions_for_user"],
                )
                spec_body = body
                break
            except Exception as e:
                last_error = f"spec validation failed: {e}"
                continue
        if spec_body is None:
            # Informal problems (card=None) fallback fast — human corrects at Checkpoint A.
            # For card-present problems, preserve contract: garbage is initialiser_error.
            if card is None:
                fallback_note = last_error or "spec build failed"
                spec = _fallback_spec(statement, prob_id, small_case_limit, f"LLM spec build failed ({fallback_note}) — fallback spec, please confirm/correct domain/objective at Checkpoint A.")
                numeric = NumericKillCheckResult(
                    status="survived",
                    counterexample=None,
                    double_verified=False,
                    methods=[],
                    checked_total=0,
                    run_smt=True,
                    smt_executed=False,
                )
                if journal is not None:
                    with contextlib.suppress(Exception):
                        journal.write("problem_spec_created", {"prob_id": spec.id, "objective": spec.objective, "numeric_status": numeric.status, "fallback": True})
                        journal.write("checkpoint_reached", {"checkpoint_id": "cp_001", "stage": "initialiser", "output_ref": "run fallback problem_spec (initialiser_error suppressed)", "revision": 0})
                return InitialiseResult(spec=spec, numeric=numeric, error=None, attempts=attempts)
            return InitialiseResult(spec=None, numeric=None, error=last_error or "spec build failed", attempts=attempts)
        spec = ProblemSpec(
            id=prob_id,
            domain=spec_body["domain"],
            statement_informal=statement,
            statement_formal=None,
            variables=spec_body["variables"],
            objective=spec_body["objective"],  # type: ignore[arg-type]
            known_special_cases=spec_body["known_special_cases"],
            kill_check_config=KillCheckConfig(run_smt=True, run_numeric_search=True, small_case_limit=small_case_limit),
            open_questions_for_user=spec_body["open_questions_for_user"],
        )
    else:
        if card is not None:
            spec = derive_spec_from_card(statement, card, prob_id=prob_id, small_case_limit=small_case_limit)
        else:
            note = "Spec derived without ClaimCard (encoder unavailable or not encodable) — confirm objective/domain."
            if encode_is_not_encodable and encode_error:
                note = f"Encoder returned NOT_ENCODABLE ({encode_error}) — spec built without ClaimCard."
            elif encode_error:
                note = f"Encoder unavailable ({encode_error}) — spec built without ClaimCard."
            spec = _fallback_spec(statement, prob_id, small_case_limit, note)

    # 3. Numeric-only kill-check (SMT recorded, never executed).
    if card is not None:
        numeric = run_numeric_killcheck(card, small_case_limit=small_case_limit, journal=journal)
    else:
        numeric = NumericKillCheckResult(
            status="survived",
            counterexample=None,
            double_verified=False,
            methods=[],
            checked_total=0,
            run_smt=True,
            smt_executed=False,
        )

    if journal is not None:
        with contextlib.suppress(Exception):
            journal.write(
                "problem_spec_created",
                {"prob_id": spec.id, "objective": spec.objective, "numeric_status": numeric.status},
            )
    return InitialiseResult(spec=spec, numeric=numeric, error=None, attempts=attempts)
