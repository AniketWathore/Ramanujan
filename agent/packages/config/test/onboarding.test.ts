/**
 * Onboarding flow: add → live models (mocked fetch) → roles incl. panel.
 * Asserts no key material in any returned object.
 */

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi, afterEach } from "vitest";
import { loadConfig, saveConfig } from "../src/index.ts";
import { needsSetupWizard, onboardAddProvider, onboardFetchModels, onboardSavePreset, onboardSetRole } from "../src/index.ts";
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

	it("assigns main_model role and resolves it", async () => {
		const p = tmpPath();
		saveConfig({ version: 1, providers: [], roles: {} }, p);
		await onboardAddProvider({ id: "nvidia", name: "N", baseUrl: "https://integrate.api.nvidia.com/v1", family: "nvidia", apiKey: "k" }, p);
		const w = await onboardSetRole("main_model", "nvidia", "nvidia/llama-main", p);
		expect(w.warning).toBeNull();
		expect(loadConfig(p).roles.main_model?.model_id).toBe("nvidia/llama-main");
		expect(resolveRole("main_model", p).modelId).toBe("nvidia/llama-main");
	});

	it("saves presets with deadlock warning, never blocking", async () => {
		const dir = mkdtempSync(join(tmpdir(), "ramanujan-preset-"));
		const presetsPath = join(dir, "presets.json");
		const solo = await onboardSavePreset("solo", ["openai/gpt-5-2025-08-07", "openrouter/gpt-5"], { presetsPath });
		expect(solo.warning).toContain("never panel-verified");
		const { loadPresets } = await import("../src/index.ts");
		expect(loadPresets(presetsPath)["solo"]).toHaveLength(2);
		const diverse = await onboardSavePreset(
			"diverse-3",
			["anthropic/claude-opus-5", "openai/gpt-5-2025-08-07", "google/gemini-3-pro"],
			{ presetsPath },
		);
		expect(diverse.warning).toBeNull();
		expect(diverse.families.length).toBeGreaterThanOrEqual(3);
	});

	it("needsSetupWizard fires only on TTY with zero providers", () => {
		const stubTTY = (stdin: boolean, stdout: boolean): void => {
			Object.defineProperty(process.stdin, "isTTY", { value: stdin, configurable: true });
			Object.defineProperty(process.stdout, "isTTY", { value: stdout, configurable: true });
		};
		const p = tmpPath();
		vi.stubEnv("RAMANUJAN_CONFIG", p);
		saveConfig({ version: 1, providers: [], roles: {} }, p);
		stubTTY(true, true);
		expect(needsSetupWizard()).toBe(true);
		vi.stubEnv("RAMANUJAN_NO_SETUP", "1");
		expect(needsSetupWizard()).toBe(false);
		vi.stubEnv("RAMANUJAN_NO_SETUP", "");
		stubTTY(false, false);
		expect(needsSetupWizard()).toBe(false);
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
