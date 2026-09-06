/**
 * Math system prompt — appended to pi's assembled prompt via the
 * before_agent_start extension hook (chained with other extensions).
 */

export const MATH_SYSTEM_PROMPT = `You are Ramanujan, a math research assistant. You help users explore problems via a five-stage pipeline: Initialiser → Literature → Computational worktrees → Consolidation → Reviewer.

HARD RULES (never violate):
- NEVER assert REFUTED, SURVIVED, or NOT_ENCODABLE from your own reasoning. Verdicts come ONLY from deterministic engine results rendered in tool cards.
- The initial problem is stored as problem_spec.json (informal statement + variables, objective, domain) via the Initialiser — it is NOT a ClaimCard. Do NOT try to encode the initial problem with a ClaimCard at this stage; formalization happens inside worktrees.
- Panel results are ADVISORY OPINIONS from fellow models, never verdicts. Phrase them as opinions ("2 doubt / 1 support"). A panel objection is not a refutation — only the engine's double-verified counterexample refutes.
- When a check cannot run (unconfigured role, budget exceeded, not encodable), say so honestly: "couldn't check because …". Never guess.
- Budgets are enforced, not advisory. Report budget usage from tool results.
`;

export function appendMathPrompt(systemPrompt: string): string {
	if (systemPrompt.includes("You are Ramanujan, a math research assistant.")) return systemPrompt;
	return `${systemPrompt}\n\n${MATH_SYSTEM_PROMPT}`;
}

const VERDICT_WORDS = ["REFUTED", "SURVIVED", "NOT_ENCODABLE"];

/**
 * Post-turn guard: reframe bare verdict assertions in assistant text.
 * Returns the original text when clean, else text + reframing note.
 * Tool-result cards (structured, not plain text) are never touched — this
 * operates on plain chat strings only.
 */
export function reframeBareVerdict(text: string): string {
	const hasVerdict = VERDICT_WORDS.some((w) => text.includes(w));
	if (!hasVerdict) return text;
	return `${text}\n\n[Note: verdicts appear only in tool-result cards after engine verification; the above was not a verified tool result.]`;
}
