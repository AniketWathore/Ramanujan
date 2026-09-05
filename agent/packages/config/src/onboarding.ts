/**
 * Onboarding flow: add provider → live /models → pick → assign roles.
 * Headless-testable via injected fetch; the TUI binds these steps
 * in A5 (same integration point as the math tools — one pi diff).
 */

import { keyStatus, loadConfig, resolveProviderKey, resolveRole, saveConfig, validateModelPin, type ResolvedRole } from "./config.ts";
import { validateProviderConfig } from "./types.ts";

export interface PromptFn {
	(question: string, opts?: { mask?: boolean }): Promise<string>;
}

export interface OnboardingProviderInput {
	id: string;
	name: string;
	baseUrl: string;
	family: string;
	apiKeyEnv?: string;
	apiKey?: string;
}

export async function onboardAddProvider(
	input: OnboardingProviderInput,
	configPath?: string,
): Promise<{ id: string; keyStatus: string }> {
	const cfg = loadConfig(configPath);
	const prov = {
		id: input.id,
		name: input.name,
		base_url: input.baseUrl.replace(/\/+$/, ""),
		api_key_env: input.apiKeyEnv ?? null,
		api_key: input.apiKey ?? null,
		family: input.family,
	};
	validateProviderConfig(prov);
	const existing = cfg.providers.findIndex((p) => p.id === input.id);
	if (existing >= 0) cfg.providers[existing] = prov;
	else cfg.providers.push(prov);
	saveConfig(cfg, configPath);
	return { id: prov.id, keyStatus: keyStatus(prov) };
}

export async function onboardFetchModels(
	providerId: string,
	configPath?: string,
	fetchFn: typeof fetch = fetch,
): Promise<string[]> {
	const cfg = loadConfig(configPath);
	const prov = cfg.providers.find((p) => p.id === providerId);
	if (!prov) throw new Error(`provider ${providerId} not found`);
	const key = resolveProviderKey(prov);
	if (!key) throw new Error(`no key for provider ${providerId}`);
	const url = `${prov.base_url.replace(/\/+$/, "")}/models`;
	const resp = await fetchFn(url, { headers: { Authorization: `Bearer ${key}` } });
	if (!resp.ok) throw new Error(`models fetch failed: HTTP ${resp.status}`);
	const data = (await resp.json()) as { data?: Array<{ id?: string }> };
	return (data.data ?? []).map((m) => String(m.id)).filter(Boolean).sort();
}

export async function onboardSetRole(
	role: "assistant" | "encoder" | "panel",
	providerId: string,
	modelId: string,
	configPath?: string,
): Promise<{ warning: string | null }> {
	const cfg = loadConfig(configPath);
	const prov = cfg.providers.find((p) => p.id === providerId);
	if (!prov) throw new Error(`provider ${providerId} not found`);
	validateModelPin(prov.base_url, modelId, providerId);
	if (role === "panel") {
		cfg.roles.panel = [...(cfg.roles.panel ?? []), { provider: providerId, model_id: modelId }];
	} else if (role === "assistant") {
		cfg.roles.assistant = { provider: providerId, model_id: modelId };
	} else {
		cfg.roles.encoder = { provider: providerId, model_id: modelId };
	}
	saveConfig(cfg, configPath);
	// Warn when the panel is single-family (cross-provider is the point).
	let warning: string | null = null;
	const panel = cfg.roles.panel ?? [];
	if (role === "panel" && panel.length >= 2) {
		const families = new Set(
			panel.map((r) => cfg.providers.find((p) => p.id === r.provider)?.family ?? r.provider),
		);
		if (families.size === 1) {
			warning = `Warning: all ${panel.length} panelists are family '${[...families][0]}' — cross-provider panels debate better.`;
		}
	}
	return { warning };
}

export { resolveRole };

/** Interactive terminal runner (manual verification; TUI binding lands in A5). */
export async function runOnboardingInteractive(prompt: PromptFn, configPath?: string): Promise<void> {
	const say = (s: string) => console.log(s);
	say("Ramanujan onboarding — add a provider, pick a model, assign roles.");
	const id = await prompt("Provider id (e.g. nvidia): ");
	const name = (await prompt(`Display name [${id}]: `)) || id;
	const baseUrl = await prompt("Base URL (e.g. https://integrate.api.nvidia.com/v1): ");
	const family = (await prompt(`Family [${id}]: `)) || id;
	const apiKeyEnv = (await prompt("API key env var (empty for stored key): ")) || undefined;
	let apiKey: string | undefined;
	if (!apiKeyEnv || !process.env[apiKeyEnv]) {
		apiKey = (await prompt("API key (stored 0600, env overrides): ", { mask: true })) || undefined;
	}
	await onboardAddProvider({ id, name, baseUrl, family, apiKeyEnv, apiKey }, configPath);
	say(`Provider ${id} saved. Fetching models…`);
	const models = await onboardFetchModels(id, configPath);
	for (const m of models.slice(0, 30)) say(`  ${m}`);
	const pick = await prompt("Pick a model slug (must contain /): ");
	validateModelPin(baseUrl, pick, id);
	const roles = (await prompt("Assign to roles (comma: assistant,encoder,panel) [assistant,encoder]: ")) || "assistant,encoder";
	for (const r of roles.split(",").map((s) => s.trim()).filter(Boolean)) {
		if (r !== "assistant" && r !== "encoder" && r !== "panel") throw new Error(`unknown role: ${r}`);
		await onboardSetRole(r, id, pick, configPath);
		say(`Role ${r} → ${id} / ${pick}`);
	}
	say("Onboarding complete.");
}
