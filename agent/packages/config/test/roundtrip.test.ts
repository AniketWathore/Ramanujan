/**
 * Cross-runtime round-trip, both directions, through real binaries.
 * TS save → Python engine CLI reads; Python engine CLI writes → TS loads.
 * Fake keys only.
 */

import { execFile } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { loadConfig, saveConfig } from "../src/index.ts";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..", "..", "..");

function engineBin(): string {
	const override = process.env["RAMANUJAN_ENGINE_BIN"];
	if (override) return override;
	const venvBin = join(repoRoot, ".venv", "bin", "ramanujan-engine");
	if (existsSync(venvBin)) return venvBin;
	return "ramanujan-engine";
}

function runEngine(args: string[], env: NodeJS.ProcessEnv): Promise<{ stdout: string; code: number | null }> {
	return new Promise((resolveP) => {
		execFile(engineBin(), args, { env: { ...process.env, ...env }, timeout: 60000 }, (err, stdout) => {
			const code = err && typeof (err as { code?: unknown }).code === "number" ? ((err as { code: number }).code) : 0;
			resolveP({ stdout: String(stdout ?? ""), code });
		});
	});
}

describe("cross-runtime round-trip", () => {
	it("TS save → Python engine list reads it (no key leaked)", async () => {
		const dir = mkdtempSync(join(tmpdir(), "ramanujan-rt-"));
		const cfgPath = join(dir, "config.toml");
		saveConfig(
			{
				version: 1,
				providers: [{ id: "mock", name: "Mock", base_url: "http://127.0.0.1:9/v1", api_key: "fake-ts-key-123", family: "mock" }],
				roles: { encoder: { provider: "mock", model_id: "mock/model" } },
			},
			cfgPath,
		);
		const res = await runEngine(["providers", "list"], { RAMANUJAN_CONFIG: cfgPath });
		expect(res.code).toBe(0);
		expect(res.stdout).toContain("mock");
		expect(res.stdout).not.toContain("fake-ts-key-123");
	});

	it("Python engine add → TS load sees it", async () => {
		const dir = mkdtempSync(join(tmpdir(), "ramanujan-rt-"));
		const cfgPath = join(dir, "config.toml");
		const env = { RAMANUJAN_CONFIG: cfgPath };
		const res = await runEngine(
		 ["providers", "add", "pyprov", "--name", "Py", "--base-url", "http://127.0.0.1:9/v1", "--family", "py", "--api-key", "fake-py-key-456"],
			env,
		);
		expect(res.code).toBe(0);
		const loaded = loadConfig(cfgPath);
		const prov = loaded.providers.find((p) => p.id === "pyprov");
		expect(prov?.base_url).toBe("http://127.0.0.1:9/v1");
		expect(prov?.api_key).toBe("fake-py-key-456");
	});
});
