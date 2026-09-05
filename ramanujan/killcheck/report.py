"""Markdown report generation — ramanujan/killcheck/report.py"""

from __future__ import annotations

from typing import Any

from ramanujan.schemas import ClaimCard


def render_report(
    card: ClaimCard,
    result: Any,
    *,
    budget_usd: float | None = None,
    budget_sec: float | None = None,
) -> str:
    """Render markdown report for a KillResult."""
    stats = result.stats
    env = stats.get("env", {})
    elapsed = stats.get("elapsed_sec", 0)
    lines: list[str] = []
    lines.append(f"# Kill-check report — {card.card_id}")
    lines.append("")
    lines.append(f"**Statement:** {card.statement_informal}")
    lines.append("")
    lines.append(f"**Claim types:** {', '.join(card.claim_type) or '—'}")
    lines.append("")
    q_str = ", ".join(f"{q.var}:{q.kind}:{q.domain.type}[{q.domain.lo},{q.domain.hi}]" for q in card.quantifiers)
    lines.append(f"**Quantifiers:** {q_str}")
    lines.append(f"**Conclusion:** `{card.conclusion.expr}`")
    if card.hypotheses:
        lines.append(f"**Hypotheses:** {', '.join(card.hypotheses)}")
    lines.append("")
    lines.append(f"## Verdict: {result.verdict}")
    lines.append("")
    if result.verdict == "REFUTED" and result.counterexample is not None:
        ce = result.counterexample
        pretty = {k: (sorted(v) if isinstance(v, set) else v) for k, v in ce.items()}
        lines.append(f"**Counterexample (double-verified):** `{pretty}`")
        verify = stats.get("verify", {})
        if verify:
            lines.append(f"- Verify: {verify.get('reason')}")
        # show phase
        for p in stats.get("phases", []):
            if p.get("found_at"):
                lines.append(f"- Found in phase: {p.get('phase')}")
                break
    elif result.verdict == "SURVIVED":
        if result.budget_exhausted:
            lines.append("**Budget exhausted — checks incomplete (caveat).**")
        else:
            lines.append("Survived all checks.")
        lines.append("")
        lines.append("**What was tried:**")
        for p in stats.get("phases", []):
            lines.append(f"- {p.get('phase')}: {p}")
    lines.append("")
    lines.append("## Environment")
    lines.append(f"- python {env.get('python')} / sympy {env.get('sympy')} / z3 {env.get('z3')}")
    lines.append(f"- elapsed {elapsed:.3f}s / budget ${budget_usd} / {budget_sec}s")
    budget_snap = stats.get("budget", {})
    if budget_snap:
        remaining = budget_snap.get("remaining_usd")
    lines.append(f"- spent ${budget_snap.get('spent_usd', 0):.4f} remaining ${remaining}")
    lines.append("")
    lines.append("## Journal")
    lines.append("Run `ramanujan replay` to inspect events.")
    lines.append("Confirm with `ramanujan confirm <run_id> [correct|incorrect]`")
    lines.append("")
    return "\n".join(lines)
