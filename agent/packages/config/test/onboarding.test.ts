/**
 * Onboarding flow: add → live models (mocked fetch) → roles incl. panel.
 * Asserts no key material in any returned object.
 */

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi, afterEach } from "vitest";
import { loadConfig, saveConfig } from "../src/index.ts";
import { onboardAddProvider, onboardFetchModels, onboardSetRole } from "../src/index.ts";
import { resolveRole } from "../src/index.ts";

function tmpPath(): string {
	return join(mkdtempSync(join(tmpdir(), "ramanujan-onb-")), "config.toml");
}

afterEach(() => {
	vi.unstubAllEnvs();
	vi.unstubAllGlobals();
});

describe("onboarding", () => {
	it("adds provider, fetches models mocked, assigns assistant+encoder+panel", async () => {
		const p = tmpPath();
		saveConfig({ version: 1, providers: [], roles: {} }, p);

		const added = await onboardAddProvider(
		 { id: "nvidia", name: "NVIDIA NIM", baseUrl: "https://integrate.api.nvidia.com/v1", family: "nvidia", apiKey: "nvapi-fake-onboard" },
			p,
		);
		expect(added.id).toBe("nvidia");
		expect(added.keyStatus).toBe("stored");

		const fakeFetch = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => {
			// Assert bearer carries the stored key
			const headers = (_init?.headers ?? {}) as Record<string, string>;
			const auth = headers["Authorization"] ?? "";
			expect(auth).toContain("nvapi-fake-onboard");
			return new Response(JSON.stringify({ data: [{ id: "nvidia/llama-a" }, { id: "nvidia/llama-b" }] }), { status: 200 });
		});
		const models = await onboardFetchModels("nvidia", p, fakeFetch as unknown as typeof fetch);
		expect(models).toEqual(["nvidia/llama-a", "nvidia/llama-b"]);

		await onboardSetRole("assistant", "nvidia", "nvidia/llama-a", p);
		await onboardSetRole("encoder", "nvidia", "nvidia/llama-a", p);
		const w1 = await onboardSetRole("panel", "nvidia", "nvidia/llama-a", p);
		expect(w1.warning).toBeNull();
		const w2 = await onboardSetRole("panel", "nvidia", "nvidia/llama-b", p);
		expect(w2.warning).toContain("nvidia");

		const cfg = loadConfig(p);
		expect(cfg.roles.assistant?.model_id).toBe("nvidia/llama-a");
		expect(cfg.roles.panel).toHaveLength(2);

		const spec = resolveRole("assistant", p);
		expect(spec.modelId).toBe("nvidia/llama-a");

		// No key material in any API-shaped response
		const dumped = JSON.stringify({ added, models, roles: cfg.roles });
		expect(dumped).not.toContain("nvapi-fake-onboard");
	});

	it("rejects alias pins and unknown providers", async () => {
		const p = tmpPath();
		saveConfig({ version: 1, providers: [], roles: {} }, p);
		await onboardAddProvider({ id: "nvidia", name: "N", baseUrl: "https://integrate.api.nvidia.com/v1", family: "nvidia", apiKey: "k" }, p);
		await expect(onboardSetRole("assistant", "nvidia", "llama-a", p)).rejects.toThrow(/full slug/);
		await expect(onboardSetRole("assistant", "nope", "x/y", p)).rejects.toThrow(/not found/);
		await expect(onboardFetchModels("nope", p)).rejects.toThrow(/not found/);
	});

	it("env key overrides stored during fetch", async () => {
		const p = tmpPath();
		saveConfig(
			{
				version: 1,
				providers: [{ id: "nvidia", name: "N", base_url: "https://integrate.api.nvidia.com/v1", api_key_env: "NVIDIA_API_KEY", api_key: "stored", family: "nvidia" }],
				roles: {},
			},
			p,
		);
		vi.stubEnv("NVIDIA_API_KEY", "env-key-xyz");
		let seen = "";
		const fakeFetch = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
			seen = ((init?.headers ?? {}) as Record<string, string>)["Authorization"] ?? "";
			return new Response(JSON.stringify({ data: [] }), { status: 200 });
		});
		await onboardFetchModels("nvidia", p, fakeFetch as unknown as typeof fetch);
		expect(seen).toContain("env-key-xyz");
		expect(seen).not.toContain("stored");
	});
});
