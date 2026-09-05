/**
 * Config load/save/resolve — mirrors ramanujan/config.py.
 * Atomic write (temp + rename), 0600, env > stored precedence, masked keys.
 */

import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { parseConfig, stringifyConfig } from "./toml.ts";
import { emptyConfig, validateConfig, type ProviderConfig, type RamanujanConfig, type RoleSpec } from "./types.ts";

export function defaultConfigPath(): string {
	const override = process.env["RAMANUJAN_CONFIG"];
	if (override) return override;
	return join(homedir(), ".config", "ramanujan", "config.toml");
}

export function loadConfig(path?: string): RamanujanConfig {
	const p = path ?? defaultConfigPath();
	if (!existsSync(p)) return emptyConfig();
	const cfg = parseConfig(readFileSync(p, "utf-8"));
	validateConfig(cfg);
	// Normalize optional nulls
	for (const prov of cfg.providers) {
		if (prov.api_key_env === undefined) prov.api_key_env = null;
		if (prov.api_key === undefined) prov.api_key = null;
	}
	return cfg;
}

export function saveConfig(cfg: RamanujanConfig, path?: string): void {
	validateConfig(cfg);
	const p = path ?? defaultConfigPath();
	mkdirSync(dirname(p), { recursive: true });
	const content = stringifyConfig(cfg);
	// Atomic: temp in same dir + rename, then 0600.
	const tmp = join(dirname(p), `.config.${process.pid}.${Date.now()}.tmp`);
	writeFileSync(tmp, content, "utf-8");
	renameSync(tmp, p);
	try {
		chmodSync(p, 0o600);
	} catch {
		// best effort (non-POSIX)
	}
}

export function resolveProviderKey(provider: ProviderConfig): string | null {
	if (provider.api_key_env) {
		const v = process.env[provider.api_key_env];
		if (v) return v;
	}
	if (provider.api_key) return provider.api_key;
	return null;
}

export function maskKey(key: string): string {
	if (!key) return "missing";
	if (key.length <= 8) return `${key.slice(0, 2)}…${key.slice(-2)}`;
	return `${key.slice(0, 4)}…${key.slice(-4)}`;
}

export function keyStatus(provider: ProviderConfig): "env" | "stored" | "missing" {
	if (provider.api_key_env && process.env[provider.api_key_env]) return "env";
	if (provider.api_key) return "stored";
	return "missing";
}

export interface ResolvedRole {
	provider: string;
	providerName: string;
	baseUrl: string;
	modelId: string;
	family: string;
	role: string;
	key: string;
}

export function resolveRole(role: string, configPath?: string): ResolvedRole {
	const cfg = loadConfig(configPath);
	const spec: RoleSpec | null | undefined =
		role === "encoder" ? cfg.roles.encoder : role === "assistant" ? cfg.roles.assistant : undefined;
	if (role !== "encoder" && role !== "assistant") throw new Error(`unknown role: ${role}`);
	if (!spec) throw new Error(`role ${role} not configured`);
	const prov = cfg.providers.find((p) => p.id === spec.provider);
	if (!prov) throw new Error(`provider ${spec.provider} for role ${role} not found in config`);
	const key = resolveProviderKey(prov);
	if (!key) {
		const envName = prov.api_key_env ?? `${prov.id.toUpperCase()}_API_KEY`;
		throw new Error(`no key for provider ${prov.id} (env ${envName} or stored api_key)`);
	}
	validateModelPin(prov.base_url, spec.model_id, prov.id);
	return {
		provider: prov.id,
		providerName: prov.name,
		baseUrl: prov.base_url.replace(/\/+$/, ""),
		modelId: spec.model_id,
		family: prov.family,
		role,
		key,
	};
}

export function isOpenAICompatible(baseUrl: string): boolean {
	return !baseUrl.includes("anthropic.com");
}

/** Anti-alias pin rule (BUILDLOG): openai-compatible pins are full slugs containing "/". */
export function validateModelPin(baseUrl: string, modelId: string, providerId: string): void {
	if (isOpenAICompatible(baseUrl) && !modelId.includes("/")) {
		throw new Error(`openai-compatible model_id must be full slug containing '/': got ${modelId} for provider ${providerId}`);
	}
}

export function tmpFile(prefix: string): string {
	const dir = mkdtempSync(join(tmpdir(), prefix));
	return join(dir, `${prefix}.json`);
}
