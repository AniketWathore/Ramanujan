/**
 * Config round-trip, permissions, precedence, masking, roles (mocked, fake keys).
 */

import { chmodSync, mkdtempSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
	keyStatus,
	loadConfig,
	maskKey,
	resolveProviderKey,
	resolveRole,
	saveConfig,
	validateModelPin,
} from "../src/index.ts";

function tmpPath(): string {
	return join(mkdtempSync(join(tmpdir(), "ramanujan-cfg-")), "config.toml");
}

afterEach(() => {
	vi.unstubAllEnvs();
});

describe("config", () => {
	it("round-trips providers and roles", () => {
		const p = tmpPath();
		saveConfig(
			{
				version: 1,
				providers: [
					{ id: "nvidia", name: "NVIDIA NIM", base_url: "https://integrate.api.nvidia.com/v1", api_key_env: "NVIDIA_API_KEY", api_key: "nvapi-fake123", family: "nvidia" },
					{ id: "openrouter", name: "OpenRouter", base_url: "https://openrouter.ai/api/v1", api_key_env: "OPENROUTER_API_KEY", family: "openrouter" },
				],
				roles: {
					encoder: { provider: "nvidia", model_id: "nvidia/llama-3.1-nemotron-70b-instruct" },
					panel: [
						{ provider: "nvidia", model_id: "nvidia/model-a" },
						{ provider: "openrouter", model_id: "openrouter/model-b" },
					],
				},
			},
			p,
		);
		const loaded = loadConfig(p);
		expect(loaded.version).toBe(1);
		expect(loaded.providers).toHaveLength(2);
		expect(loaded.providers[0].api_key).toBe("nvapi-fake123");
		expect(loaded.roles.encoder?.model_id).toBe("nvidia/llama-3.1-nemotron-70b-instruct");
		expect(loaded.roles.panel).toHaveLength(2);
	});

	it("creates the file with 0600", () => {
		const p = tmpPath();
		saveConfig({ version: 1, providers: [], roles: {} }, p);
		const mode = statSync(p).mode & 0o777;
		expect(mode).toBe(0o600);
		// Rewrite keeps 0600 even if something changed it
		chmodSync(p, 0o644);
		saveConfig({ version: 1, providers: [], roles: {} }, p);
		expect(statSync(p).mode & 0o777).toBe(0o600);
	});

	it("prefers env over stored keys", () => {
		const prov = { id: "nvidia", name: "N", base_url: "https://example.com/v1", api_key_env: "NVIDIA_API_KEY", api_key: "stored-key", family: "nvidia" };
		vi.stubEnv("NVIDIA_API_KEY", "");
		expect(resolveProviderKey(prov)).toBe("stored-key");
		vi.stubEnv("NVIDIA_API_KEY", "env-key");
		expect(resolveProviderKey(prov)).toBe("env-key");
	});

	it("masks keys and reports status without leaking", () => {
		expect(maskKey("nvapi-1234567890abcdef")).toBe("nvap…cdef");
		expect(maskKey("")).toBe("missing");
		const prov = { id: "x", name: "X", base_url: "https://example.com", api_key: "super-secret-value", family: "x" };
		expect(keyStatus(prov)).toBe("stored");
		expect(JSON.stringify({ status: keyStatus(prov), masked: maskKey(prov.api_key!) })).not.toContain("super-secret-value");
	});

	it("resolves roles with key and pin", () => {
		const p = tmpPath();
		saveConfig(
			{
				version: 1,
				providers: [{ id: "nvidia", name: "N", base_url: "https://integrate.api.nvidia.com/v1", api_key: "nvapi-fake", family: "nvidia" }],
				roles: { encoder: { provider: "nvidia", model_id: "nvidia/test-model" } },
			},
			p,
		);
		const spec = resolveRole("encoder", p);
		expect(spec.provider).toBe("nvidia");
		expect(spec.modelId).toBe("nvidia/test-model");
		expect(spec.key).toBe("nvapi-fake");
		expect(() => resolveRole("assistant", p)).toThrow(/not configured/);
	});

	it("rejects aliases for openai-compatible providers", () => {
		expect(() => validateModelPin("https://integrate.api.nvidia.com/v1", "llama-3.1", "nvidia")).toThrow(/full slug/);
		validateModelPin("https://integrate.api.nvidia.com/v1", "nvidia/llama-3.1", "nvidia");
		// First-party snapshots pass through
		validateModelPin("https://api.anthropic.com", "claude-sonnet-4-20250514", "anthropic");
	});

	it("parses comments and blank lines", () => {
		const p = tmpPath();
		writeFileSync(
			p,
			'# a comment\nversion = 1\n\n[[providers]]\n# another\nid = "a"\nname = "A"\nbase_url = "https://example.com/v1"\nfamily = "a"\n',
		);
		const loaded = loadConfig(p);
		expect(loaded.providers[0].id).toBe("a");
		expect(readFileSync(p, "utf-8")).toContain("# a comment");
	});
});
