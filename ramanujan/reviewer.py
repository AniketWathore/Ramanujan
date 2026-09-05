"""Stage 5 Reviewer — ramanujan/reviewer.py (v2 Phase 9).

Plain-language summary + technical appendix (labeled fact set, worktree
comparison, failed approaches reported as information, not omitted).
Final checkpoint: confirm (conclude) / type feedback (re-run a stage, spawn
redirected worktrees, re-panel a claim). Stop remains globally available.

Three-way contract (mirrors encoder/initialiser/literature — never conflate
refusal with system failure):
- `review` — report + Checkpoint E proposed.
- `not_reviewable` — the model itself explicitly refused (NOT_REVIEWABLE).
- `reviewer_error` — model failure, timeout, or validation failure after retries.

Uses `main_model` (like Initialiser/Literature/Tier-1/consolidation). Keyless
runs produce a deterministic template, not an error.
"""

from __future__ import annotations

import json
import re
from typing import Any

REVIEWER_SYSTEM = """You are the Ramanujan Reviewer. Synthesize the session into a final report.

You MUST output STRICT JSON matching schema exactly — no markdown:

{
  "summary": "<plain-language paragraph: what was proved/refuted, how, and what remains open>",
  "failed_approaches": ["<each failed worktree/claim/lane reported as information, not omitted>"],
  "open_questions": ["<what is still open>"]
}

Rules:
- Report failed approaches — do not omit them. A second proof or a failed lane is information.
- Be concise and honest; do not overclaim.
- If the session has no reviewable content (meaningless input): {"error": "NOT_REVIEWABLE", "reason": "<why>"}
  ONLY refuse yourself when there is truly nothing to review.
  NEVER emit NOT_REVIEWABLE because of a validation error — fix the JSON instead.
- Temperature 0, precise.
"""


def _extract_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if m:
        return m.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


class ReviewerResult:
    """Three-way outcome: review | not_reviewable | reviewer_error."""

    def __init__(self, report_md: str | None, report_json: dict[str, Any] | None, error: str | None, attempts: int) -> None:
        self.report_md = report_md
        self.report_json = report_json
        self.error = error
        self.attempts = attempts
        self.is_not_reviewable = error is not None and "NOT_REVIEWABLE" in error

    @property
    def success(self) -> bool:
        return self.report_md is not None

    @property
    def is_reviewer_error(self) -> bool:
        return not self.success and not self.is_not_reviewable

    @property
    def status(self) -> str:
        if self.success:
            return "review"
        if self.is_not_reviewable:
            return "not_reviewable"
        return "reviewer_error"


def _deterministic_report(
    statement: str,
    facts: list[dict[str, Any]],
    worktrees: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
    timeout_defaults: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Template report (keyless/mock path)."""
    fact_lines = "\n".join(f"- {f['id']}: {f['status']} — {f['conclusion'][:80]}" for f in facts) if facts else "- (no facts)"
    wt_lines = (
        "\n".join(f"- {w.get('id') or w.get('worktree_id')}: {w.get('status', 'running')}" for w in worktrees)
        if worktrees
        else "- (no worktrees)"
    )
    contra_lines = (
        "\n".join(f"- {c['claim_a']} vs {c['claim_b']}: {c['reason'][:60]}" for c in contradictions) if contradictions else "- none"
    )
    timeout_lines = "\n".join(f"- {t['question_id']}: {t['answer']!r}" for t in timeout_defaults) if timeout_defaults else "- none"
    # Failed approaches = refuted or stalled worktrees + contradictions as information
    failed = [f for f in facts if f["status"] == "refuted"]
    stalled = [w for w in worktrees if w.get("status") in ("stalled", "stopped_budget", "stopped_error")]
    failed_lines = ""
    if failed or stalled or contradictions:
        parts: list[str] = []
        for f in failed:
            parts.append(f"Fact {f['id']} refuted: {f['conclusion'][:60]}")
        for w in stalled:
            parts.append(f"Worktree {w.get('id') or w.get('worktree_id')} {w.get('status')}")
        for c in contradictions:
            parts.append(f"Contradiction {c['claim_a']} vs {c['claim_b']}")
        failed_lines = "\n".join(f"- {p}" for p in parts)
    else:
        failed_lines = "- none — all lanes succeeded"
    summary = f"Session for: {statement[:120]}. Facts: {len(facts)}, worktrees: {len(worktrees)}, contradictions: {len(contradictions)}."
    md = f"""# Final Report — Reviewer

## Summary (plain language)
{summary}
Failed approaches are listed below, not omitted.

## Technical Appendix

### Labeled fact set
{fact_lines}

### Worktree comparison
{wt_lines}

### Failed approaches (information, not omitted)
{failed_lines}

### Cross-worktree contradictions
{contra_lines}

### Timeout assumptions (from Stage 3, surfaced unmissably)
{timeout_lines}

*Generated deterministically (no LLM key) — main_model would refine the summary.*
"""
    j: dict[str, Any] = {"summary": summary, "failed_approaches": [f["id"] for f in failed], "open_questions": []}
    return md, j


def synthesize_report(
    statement: str,
    *,
    journal: Any | None = None,
    caller=None,
    model_spec=None,
    facts: list[dict[str, Any]] | None = None,
    worktrees: list[dict[str, Any]] | None = None,
    contradictions: list[dict[str, Any]] | None = None,
    timeout_defaults: list[dict[str, Any]] | None = None,
    max_retries: int = 3,
) -> ReviewerResult:
    """Run reviewer (LLM when caller+model_spec, else deterministic template)."""
    facts = facts or []
    worktrees = worktrees or []
    contradictions = contradictions or []
    timeout_defaults = timeout_defaults or []

    if caller is None or model_spec is None:
        md, j = _deterministic_report(statement, facts, worktrees, contradictions, timeout_defaults)
        return ReviewerResult(report_md=md, report_json=j, error=None, attempts=0)

    from ramanujan.providers import call_llm

    # Build prompt context from session snapshot
    ctx = {
        "statement": statement,
        "facts": [{"id": f["id"], "status": f["status"], "conclusion": f["conclusion"]} for f in facts],
        "worktrees": [{"id": w.get("id") or w.get("worktree_id"), "status": w.get("status")} for w in worktrees],
        "contradictions": contradictions,
        "timeout_defaults": timeout_defaults,
    }
    messages = [
        {"role": "system", "content": REVIEWER_SYSTEM},
        {"role": "user", "content": f"Session to review:\n{json.dumps(ctx, indent=2)}\n\nOutput strict JSON only."},
    ]
    attempts = 0
    last_error = ""
    for _attempt in range(max_retries):
        attempts += 1
        try:
            resp = call_llm(model_spec, messages, journal=journal, caller=caller)
            raw_text = resp["text"]
        except Exception as e:
            last_error = f"LLM call failed: {e}"
            continue
        try:
            parsed = json.loads(_extract_json(raw_text))
        except Exception as e:
            last_error = f"JSON parse error: {e}"
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({"role": "user", "content": f"Validation error: {last_error}\nOutput strict JSON matching schema."})
            continue
        if isinstance(parsed, dict) and parsed.get("error") == "NOT_REVIEWABLE":
            reason = parsed.get("reason", "not reviewable")
            return ReviewerResult(report_md=None, report_json=None, error=f"NOT_REVIEWABLE: {reason}", attempts=attempts)
        try:
            summary = parsed.get("summary", "")
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError("summary must be non-empty string")
            failed = list(parsed.get("failed_approaches", []))
            open_q = list(parsed.get("open_questions", []))
            # Build markdown from LLM summary + deterministic appendix
            md_appendix = _deterministic_report(statement, facts, worktrees, contradictions, timeout_defaults)[0].split(
                "## Technical Appendix"
            )[1]
            md = f"# Final Report — Reviewer\n\n## Summary (plain language)\n{summary.strip()}\n\n## Technical Appendix{md_appendix}"
            return ReviewerResult(
                report_md=md,
                report_json={"summary": summary, "failed_approaches": failed, "open_questions": open_q},
                error=None,
                attempts=attempts,
            )
        except Exception as e:
            last_error = f"report validation failed: {e}"
            messages.append({"role": "assistant", "content": raw_text})
            messages.append(
                {"role": "user", "content": f"Validation error: {last_error}\nFix the JSON: summary + failed_approaches + open_questions."}
            )
            continue
    return ReviewerResult(report_md=None, report_json=None, error=last_error or "review failed", attempts=attempts)
