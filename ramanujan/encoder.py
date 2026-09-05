"""LLM-assisted statement -> claim card — ramanujan/encoder.py

Strict JSON prompt, pydantic validation, retry up to 3 times feeding validation error.
"""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any

from pydantic import ValidationError

from ramanujan.claimcard import validate_card  # noqa: F401
from ramanujan.providers import LlmCaller, VerifierSpec, call_llm
from ramanujan.schemas import ClaimCard

ENCODER_SYSTEM = """You are the Ramanujan encoder. Convert informal math -> Claim Card DSL.

You MUST output STRICT JSON matching schema exactly — no markdown:

{
  "card_id": "c_0001",
  "statement_informal": "<original>",
  "claim_type": ["<one of 10 tags>"],
  "quantifiers": [
    {"var": "n", "kind": "forall|exists",
     "domain": {"type": "int|real|finite_set_of_ints",
                "lo": <int|float|null>, "hi": <int|float|null>}}
  ],
  "hypotheses": ["<bool expr>"],
  "conclusion": {"expr": "<bool expr>", "sympy_parseable": true},
  "set_vars": ["<subset of quantifier vars that are sets>"]
}

claim_type MUST be one or more of exactly these 10 frozen tags (never invent others):
- inequality-estimate
- quantifier-scope
- algebraic-identity
- convergence-limit
- compactness-existence
- combinatorial-construction
- induction-recursion
- code-algorithmic
- statement-equivalence
- generalization
There is NO "prime"/"prime_number"/"primality" tag. Primality claims use
"inequality-estimate" (e.g. is_prime conclusions below).

Rules:
- variables typed int/real/finite set of ints only.
- exprs must be sympy-parseable: factorial(n), 2**n, is_prime(x) etc.
  For sets: |A| cardinality, A+B sumset, in, subset.
- If not encodable: {"error": "NOT_ENCODABLE", "reason": "<why>"}
  ONLY refuse yourself when the DSL truly cannot express the statement.
  NEVER emit NOT_ENCODABLE because of a validation error — fix the JSON instead.
- Always use card_id "c_0001".
- Temperature 0, precise.

Examples:
- "For every n >=4, n! > 2^n." => quantifiers [{var:n, forall, int lo:4}],
  conclusion "factorial(n) > 2**n", claim_type ["inequality-estimate"]
- "For finite sets A,B, |A+B| >= |A|+|B|-1." => quantifiers A,B finite_set,
  conclusion "|A+B| >= |A|+|B|-1", set_vars ["A","B"],
  claim_type ["combinatorial-construction"]
- Worked card for "For every integer n >= 0, n^2 + n + 41 is prime.":
  {"card_id": "c_0001",
   "statement_informal": "For every integer n >= 0, n^2 + n + 41 is prime.",
   "claim_type": ["inequality-estimate"],
   "quantifiers": [{"var": "n", "kind": "forall",
                    "domain": {"type": "int", "lo": 0, "hi": null}}],
   "hypotheses": [],
   "conclusion": {"expr": "is_prime(n**2 + n + 41)", "sympy_parseable": true},
   "set_vars": []}
"""


def _build_prompt(statement: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": ENCODER_SYSTEM},
        {
            "role": "user",
            "content": f"Statement to encode:\n{statement}\n\nOutput strict JSON only.",
        },
    ]


def _extract_json(text: str) -> str:
    """Extract JSON object from LLM text (strip markdown fences)."""
    text = text.strip()
    # Remove ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if m:
        return m.group(1)
    # Find first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


class EncodeResult:
    def __init__(self, card: ClaimCard | None, error: str | None, raw: str, attempts: int) -> None:
        self.card = card
        self.error = error
        self.raw = raw
        self.attempts = attempts
        self.is_not_encodable = error is not None and "NOT_ENCODABLE" in error

    @property
    def success(self) -> bool:
        return self.card is not None

    @property
    def is_encoder_error(self) -> bool:
        """True when the encoder MODEL failed (LLM/timeout/validation after
        retries) — NOT a DSL refusal. Distinct from is_not_encodable, which
        is ONLY true when the model itself explicitly refused."""
        return not self.success and not self.is_not_encodable

    @property
    def status(self) -> str:
        """Machine status: card | not_encodable | encoder_error."""
        if self.success:
            return "card"
        if self.is_not_encodable:
            return "not_encodable"
        return "encoder_error"


def encode_statement(
    statement: str,
    spec: VerifierSpec,
    journal: Any | None = None,
    *,
    caller: LlmCaller | None = None,
    max_retries: int = 3,
) -> EncodeResult:
    """Encode statement -> ClaimCard with validation-retry loop.

    Logs encoding_attempted / encoding_accepted / encoding_failed to journal.
    Returns EncodeResult.
    """
    attempts = 0
    last_raw = ""
    last_error = ""
    messages = _build_prompt(statement)

    for attempt in range(max_retries):
        attempts += 1
        if journal is not None:
            with contextlib.suppress(Exception):
                journal.write("encoding_attempted", {"statement": statement, "attempt": attempt + 1})
        # Call LLM
        try:
            resp = call_llm(spec, messages, journal=journal, caller=caller)
            raw_text = resp["text"]
        except Exception as e:
            last_error = f"LLM call failed: {e}"
            # Feed error back to messages for retry
            messages.append({"role": "assistant", "content": last_error})
            messages.append(
                {
                    "role": "user",
                    "content": f"Previous failed: {last_error}\nRetry strict JSON schema.",
                }
            )
            continue
        last_raw = raw_text
        json_str = _extract_json(raw_text)
        # Check NOT_ENCODABLE first
        try:
            parsed = json.loads(json_str)
        except Exception as e:
            last_error = f"JSON parse error: {e}; raw: {raw_text[:500]}"
            messages.append({"role": "assistant", "content": raw_text})
            messages.append(
                {
                    "role": "user",
                    "content": (f"Validation error: {last_error}\nOutput strict JSON matching the ClaimCard schema."),
                }
            )
            continue
        if isinstance(parsed, dict) and parsed.get("error") == "NOT_ENCODABLE":
            reason = parsed.get("reason", "not encodable")
            last_error = f"NOT_ENCODABLE: {reason}"
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.write("encoding_failed", {"reason": reason, "attempt": attempts})
            return EncodeResult(card=None, error=last_error, raw=last_raw, attempts=attempts)
        # Try ClaimCard validation
        try:
            card = ClaimCard.model_validate(parsed)
            # Extra interpreter check: expressions must parse
            from ramanujan.claimcard import validate_card as _vc

            _vc(card)
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.write("encoding_accepted", {"card_id": card.card_id, "attempt": attempts})
            return EncodeResult(card=card, error=None, raw=last_raw, attempts=attempts)
        except (ValidationError, ValueError) as e:
            last_error = f"ClaimCard validation failed: {e}"
            messages.append({"role": "assistant", "content": raw_text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Validation error: {last_error}\nFix JSON to match schema. "
                        "card_id c_0001, claim_type from frozen list, valid quantifiers."
                    ),
                }
            )
            continue
        except Exception as e:
            last_error = f"validation error: {e}"
            messages.append({"role": "assistant", "content": raw_text})
            messages.append(
                {
                    "role": "user",
                    "content": f"Validation error: {last_error}\nRetry with valid JSON.",
                }
            )
            continue

    # Exhausted retries
    if journal is not None:
        with contextlib.suppress(Exception):
            journal.write("encoding_failed", {"reason": last_error, "attempt": attempts})
    return EncodeResult(card=None, error=last_error or "encoding failed", raw=last_raw, attempts=attempts)
