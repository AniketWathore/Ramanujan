/** Shared test helpers: engine binary resolution + tmp journal. */

import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const repoRoot = resolve(here, "..", "..", "..", "..");

export function engineBin(): string {
	const override = process.env["RAMANUJAN_ENGINE_BIN"];
	if (override) return override;
	const venvBin = join(repoRoot, ".venv", "bin", "ramanujan-engine");
	if (existsSync(venvBin)) return venvBin;
	return "ramanujan-engine";
}

export function tmpJournal(): string {
	const dir = mkdtempSync(join(tmpdir(), "ramanujan-mathtools-"));
	return join(dir, "journal.jsonl");
}

export const PRIME_CARD = {
	card_id: "c_0001",
	statement_informal: "For every integer n >= 0, n^2 + n + 41 is prime.",
	claim_type: ["inequality-estimate"],
	quantifiers: [{ var: "n", kind: "forall", domain: { type: "int", lo: 0, hi: null } }],
	hypotheses: [],
	conclusion: { expr: "is_prime(n**2 + n + 41)", sympy_parseable: true },
	set_vars: [],
};

export const PRIME_STATEMENT = "For every integer n >= 0, n^2 + n + 41 is prime.";
