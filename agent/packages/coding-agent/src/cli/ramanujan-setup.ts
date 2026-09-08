/**
 * Ramanujan first-launch setup wizard (TUI).
 *
 * Mirrors pi's /login → /models flow, but writes Ramanujan config:
 *   1. pick a provider from the known list (like /login — no base_url,
 *      no family questions; both come from pi-ai's provider catalog)
 *   2. API key asked ONCE (env var or paste)
 *   3. pick main model from the FULL live model list (like /models shows),
 *      manual slug entry always available
 *   4. computational pool: "use existing providers" or "add new provider",
 *      then multi-pick models from same/different providers (Done is a
 *      separate Tab-reachable row under a 4-row scrolling window)
 *   5. confirm selection → save as default preset, optionally more presets
 *   6. final confirm → ASCII home + chat
 *
 * The picked main model is also wired into pi chat (key into pi auth storage
 * + persisted default model) so the footer shows it and chat uses it.
 * Never blocks: any cancel skips the rest and boots normally.
 */

import type { Credential } from "@earendil-works/pi-ai";
import { builtinProviders, getBuiltinModels } from "@earendil-works/pi-ai/providers/all";
import {
	loadConfig,
	needsSetupWizard,
	onboardAddProvider,
	onboardFetchModels,
	onboardSavePreset,
	onboardSetRole,
} from "@ramanujan/config";
import { AuthStorage } from "../core/auth-storage.ts";
import type { SettingsManager } from "../core/settings-manager.ts";
import { detectTerminalThemeForAuto } from "../modes/interactive/theme/theme.ts";
import { RAMANUJAN_SETUP_HEADER, createStartupTui, showStartupInput, showStartupSelector } from "./startup-ui.ts";

interface KnownProvider {
	id: string;
	name: string;
	baseUrl: string;
}

function knownProviders(): KnownProvider[] {
	try {
		return builtinProviders()
			.filter((p) => typeof p.baseUrl === "string" && p.baseUrl.length > 0 && p.auth?.apiKey != null)
			.map((p) => ({ id: p.id, name: p.name, baseUrl: p.baseUrl as string }))
			.sort((a, b) => a.name.localeCompare(b.name));
	} catch {
		return [];
	}
}

function staticModels(providerId: string): string[] {
	try {
		const models = getBuiltinModels(providerId as never) as Array<{ id?: string }>;
		return (models ?? []).map((m) => String(m.id ?? "")).filter(Boolean).sort();
	} catch {
		return [];
	}
}

function mergeModels(live: string[], fallback: string[]): string[] {
	const seen = new Set<string>();
	const out: string[] = [];
	for (const m of [...live, ...fallback]) {
		const t = m.trim();
		if (t && !seen.has(t)) {
			seen.add(t);
			out.push(t);
		}
	}
	return out;
}

async function askInput(
	settingsManager: SettingsManager,
	theme: string | undefined,
	title: string,
	placeholder?: string,
): Promise<string | undefined> {
	const v = await showStartupInput(settingsManager, title, placeholder, {
		...(theme ? { themeOverride: theme } : {}),
		header: RAMANUJAN_SETUP_HEADER,
	});
	if (v === undefined) return undefined;
	const t = v.trim();
	return t.length > 0 ? t : undefined;
}

async function askSelect<T>(
	settingsManager: SettingsManager,
	theme: string | undefined,
	title: string,
	options: Array<{ label: string; value: T }>,
	footer?: { label: string; value: T },
): Promise<T | undefined> {
	return showStartupSelector(settingsManager, title, options, {
		maxVisible: 4,
		searchable: true,
		header: RAMANUJAN_SETUP_HEADER,
		...(footer ? { footer } : {}),
		...(theme ? { themeOverride: theme } : {}),
	});
}

export function shouldRunRamanujanSetup(): boolean {
	return needsSetupWizard();
}

async function detectTheme(settingsManager: SettingsManager): Promise<string | undefined> {
	try {
		const ui = await createStartupTui(settingsManager);
		ui.start();
		try {
			const t = await Promise.race([
				detectTerminalThemeForAuto({ ui, timeoutMs: 1500 }),
				new Promise<undefined>((r) => setTimeout(() => r(undefined), 2000)),
			]);
			return t ?? undefined;
		} finally {
			ui.stop();
		}
	} catch {
		return undefined;
	}
}

async function addProviderFlow(
	settingsManager: SettingsManager,
	theme: string | undefined,
	catalog: KnownProvider[],
): Promise<{ id: string; models: string[]; key: string | undefined; apiKeyEnv: string | undefined } | undefined> {
	const pick = await askSelect(
		settingsManager,
		theme,
		"Select provider to configure (sign in with an API key):",
		catalog.map((p) => ({ label: `${p.name} (${p.id})`, value: p.id })),
	);
	if (!pick) return undefined;
	const known = catalog.find((p) => p.id === pick)!;

	// API key asked ONCE: method first, then a single input.
	const method = await askSelect(settingsManager, theme, `API key for ${known.name}:`, [
		{ label: "Use environment variable", value: "env" },
		{ label: "Paste API key (stored 0600)", value: "paste" },
	]);
	if (!method) return undefined;
	let apiKeyEnv: string | undefined;
	let apiKey: string | undefined;
	if (method === "env") {
		apiKeyEnv = await askInput(
			settingsManager,
			theme,
			`Env var holding the ${known.name} key:`,
			`e.g. ${known.id.toUpperCase().replace(/[^A-Z0-9]/g, "_")}_API_KEY`,
		);
		if (!apiKeyEnv) return undefined;
		if (!process.env[apiKeyEnv]) {
			console.log(`Note: ${apiKeyEnv} is not set in this shell — export it before chatting, or re-run setup.`);
		}
	} else {
		apiKey = await askInput(settingsManager, theme, `Paste API key for ${known.name} (stored 0600):`, undefined);
		if (!apiKey) {
			console.log("No key provided — provider saved without a key; add one before chatting.");
		}
	}

	try {
		await onboardAddProvider(
			{ id: known.id, name: known.name, baseUrl: known.baseUrl, family: known.id, apiKeyEnv, apiKey },
			undefined,
		);
	} catch (e) {
		console.log(`Could not save provider: ${e instanceof Error ? e.message : String(e)}`);
		return undefined;
	}
	console.log(`Provider ${known.name} saved. Fetching models…`);

	let models: string[] = [];
	try {
		models = mergeModels(await onboardFetchModels(known.id, undefined), staticModels(known.id));
	} catch (e) {
		console.log(`Live model list failed (${e instanceof Error ? e.message : String(e)}). Using built-in catalog…`);
		models = staticModels(known.id);
	}
	if (models.length === 0) {
		console.log(`No models found for ${known.name}.`);
	}
	return { id: known.id, models, key: apiKey, apiKeyEnv };
}

async function pickModel(
	settingsManager: SettingsManager,
	theme: string | undefined,
	title: string,
	models: string[],
): Promise<string | undefined> {
	if (models.length === 1) return models[0];
	const MANUAL = "__manual_slug";
	const pick = await askSelect(settingsManager, theme, title, [
		{ label: "✎ Type model slug manually…", value: MANUAL },
		...models.map((m) => ({ label: m, value: m })),
	]);
	if (!pick || pick === MANUAL) {
		if (!pick) return undefined;
		return askInput(settingsManager, theme, "Model slug (must contain /, e.g. nvidia/model):", undefined);
	}
	return pick;
}

/** Wire the picked model into pi chat: key into pi auth + persisted default model.
 * The model id is stored verbatim (pi catalog ids already match what providers
 * list, e.g. `deepseek-ai/deepseek-v4-flash-0731`) — never strip prefixes, or
 * boot resolution fails and the footer falls back to another provider.
 */
async function wireChatModel(
	settingsManager: SettingsManager,
	providerId: string,
	modelSlug: string,
	pastedKey: string | undefined,
): Promise<void> {
	try {
		if (pastedKey) {
			const store = AuthStorage.create();
			const cred: Credential = { type: "api_key", key: pastedKey };
			await store.modify(providerId, async () => cred);
		}
		settingsManager.setDefaultModelAndProvider(providerId, modelSlug);
	} catch (e) {
		console.log(`Note: chat model wiring skipped (${e instanceof Error ? e.message : String(e)}). Use /model in chat.`);
	}
}

/** Mirror a pool provider's key into pi chat auth WITHOUT touching the default.
 * /model only lists providers with configured auth, so pool providers added
 * in setup must be visible to pi even though the main model stays as picked
 * in step 3. Never overwrites an existing pi credential.
 */
async function wirePoolProviderKey(
	providerId: string,
	pastedKey: string | undefined,
	apiKeyEnv: string | undefined,
): Promise<void> {
	try {
		const store = AuthStorage.create();
		const existing = await store.read(providerId);
		if (existing) return;
		if (pastedKey) {
			const cred: Credential = { type: "api_key", key: pastedKey };
			await store.modify(providerId, async () => cred);
		} else if (apiKeyEnv) {
			// Env-referenced key: store as "$VAR" so pi resolves via process.env.
			const cred: Credential = { type: "api_key", key: `$${apiKeyEnv}` };
			await store.modify(providerId, async () => cred);
		}
	} catch (e) {
		console.log(`Note: pool auth mirror skipped for ${providerId} (${e instanceof Error ? e.message : String(e)}).`);
	}
}

/** Boot-time repair: mirror every Ramanujan config provider key into pi auth.
 * Fixes existing installs where setup saved 2 providers to config.toml but
 * only the first reached pi auth, so /model showed one provider. Idempotent:
 * only fills missing pi credentials, never overwrites, never touches default.
 */
export async function syncRamanujanProvidersToChatAuth(): Promise<void> {
	try {
		const cfg = loadConfig();
		if (cfg.providers.length === 0) return;
		const store = AuthStorage.create();
		for (const prov of cfg.providers) {
			try {
				const existing = await store.read(prov.id);
				if (existing) continue;
				const envVal = prov.api_key_env ? process.env[prov.api_key_env] : undefined;
				if (prov.api_key) {
					await store.modify(prov.id, async () => ({ type: "api_key", key: prov.api_key as string }));
				} else if (prov.api_key_env && envVal) {
					await store.modify(prov.id, async () => ({ type: "api_key", key: `$${prov.api_key_env as string}` }));
				}
				// else: no resolvable key — leave for /login.
			} catch {
				// per-provider best effort; one failure must not block others.
			}
		}
	} catch {
		// config unreadable — boot must not break.
	}
}

/** Best-effort: record a /model pick as the next Ramanujan main_model role.
 * Chat default is handled by the caller via settingsManager; this only keeps
 * config.toml roles.main_model in sync. Never throws into chat.
 */
export async function updateRamanujanMainModel(providerId: string, modelId: string): Promise<void> {
	try {
		await onboardSetRole("main_model", providerId, modelId, undefined);
	} catch {
		// stale provider / slug rule — chat default still applies.
	}
}

export async function runRamanujanSetup(settingsManager: SettingsManager): Promise<void> {
	// No ASCII banner here — boot's homepage owns the single banner (themed).
	// All wizard chatter below is cleared on successful completion so "open
	// chat" lands on the normal default state (banner + chatbox, nothing else).
	const say = (s: string) => console.log(s);
	say("Welcome to Ramanujan — first-time setup.");
	say("(Esc cancels any step; setup can be re-run later from chat.)");

	// Query the real terminal background once so selectors never render
	// invisible (e.g. black-on-black from a wrong env guess).
	const theme = await detectTheme(settingsManager);

	const catalog = knownProviders();
	if (catalog.length === 0) {
		say("No known providers available — skipping setup.");
		return;
	}

	// Steps 1–2: provider + API key (like /login).
	const first = await addProviderFlow(settingsManager, theme, catalog);
	if (!first) return;

	// Step 3: main model from the FULL live list (like /models shows).
	const mainPick = await pickModel(settingsManager, theme, "Pick the main model:", first.models);
	if (!mainPick) return;
	try {
		await onboardSetRole("main_model", first.id, mainPick, undefined);
		say(`Main model → ${first.id} / ${mainPick}`);
	} catch (e) {
		say(`Could not set main model: ${e instanceof Error ? e.message : String(e)}`);
		return;
	}
	await wireChatModel(settingsManager, first.id, mainPick, first.key);

	// Step 4: computational pool — existing providers or add new ones.
	const pool: string[] = [];
	for (;;) {
		const configured = loadConfig().providers;
		const choice = await askSelect(settingsManager, theme, "Computational subagents — add models from:", [
			...(configured.length > 0 ? [{ label: "Use existing providers", value: "existing" }] : []),
			{ label: "Add new provider", value: "new" },
		], { label: `Done (${pool.length} picked)`, value: "__done" });
		if (!choice || choice === "__done") break;
		if (choice === "new") {
			const added = await addProviderFlow(
				settingsManager,
				theme,
				catalog.filter((p) => !configured.some((c) => c.id === p.id)),
			);
			if (!added) continue;
			// NOTE: never touch the chat default here — it stays exactly the
			// main model picked in step 3. Pool providers only join presets,
			// but their key IS mirrored so /model lists both providers.
			await wirePoolProviderKey(added.id, added.key, added.apiKeyEnv);
			for (;;) {
				const m = await askSelect(settingsManager, theme, `Pick models from ${added.id}:`, [
					...added.models.filter((x) => !pool.includes(x)).map((x) => ({ label: x, value: x })),
					{ label: "✎ Type model slug manually…", value: "__manual" },
				], { label: `Done (${pool.length} picked)`, value: "__done" });
				if (!m || m === "__done") break;
				const slug = m === "__manual"
					? await askInput(settingsManager, theme, `Model slug for ${added.id} (must contain /):`, undefined)
					: m;
				if (slug && !pool.includes(slug)) pool.push(slug);
			}
			continue;
		}
		// existing: pick a provider, fetch its models, multi-pick
		const provPick = await askSelect(
			settingsManager,
			theme,
			"Pick a configured provider:",
			configured.map((p) => ({ label: `${p.name} (${p.id})`, value: p.id })),
		);
		if (!provPick) continue;
		let models: string[] = [];
		try {
			models = mergeModels(await onboardFetchModels(provPick, undefined), staticModels(provPick));
		} catch (e) {
			say(`Model list fetch failed (${e instanceof Error ? e.message : String(e)}). Using built-in catalog…`);
			models = staticModels(provPick);
		}
		if (models.length === 0) {
			say(`No models found for ${provPick}.`);
			continue;
		}
		for (;;) {
			const m = await askSelect(settingsManager, theme, `Pick models from ${provPick}:`, [
				...models.filter((x) => !pool.includes(x)).map((x) => ({ label: x, value: x })),
				{ label: "✎ Type model slug manually…", value: "__manual" },
			], { label: `Done (${pool.length} picked)`, value: "__done" });
			if (!m || m === "__done") break;
			const slug = m === "__manual"
				? await askInput(settingsManager, theme, `Model slug for ${provPick} (must contain /):`, undefined)
				: m;
			if (slug && !pool.includes(slug)) pool.push(slug);
		}
	}

	if (pool.length === 0) {
		say("No pool models picked — skipping presets. You can set them up later from chat.");
	} else {
		// Step 5: confirm selection → default preset, optionally more presets.
		for (;;) {
			say("Selected pool:");
			for (const m of pool) say(`  ${m}`);
			const presetName = (await askInput(settingsManager, theme, "Save this pool as preset (name)", "default")) ?? "default";
			try {
				const check = await onboardSavePreset(presetName, pool, undefined);
				say(`Preset ${presetName} saved (${pool.length} models, ${check.families.length} families).`);
				if (check.warning) say(`Warning: ${check.warning}`);
				else if (check.note) say(check.note);
			} catch (e) {
				say(`Could not save preset: ${e instanceof Error ? e.message : String(e)}`);
			}
			const more = await askSelect(settingsManager, theme, "Set up another preset?", [
				{ label: "No — continue", value: "no" },
				{ label: "Yes — pick another pool", value: "yes" },
			]);
			if (more !== "yes") break;
			pool.length = 0;
			const configured = loadConfig().providers;
			if (configured.length === 0) {
				say("No providers configured — cannot pick more models.");
				break;
			}
			const provPick = await askSelect(
				settingsManager,
				theme,
				"Pick a provider for the next preset:",
				configured.map((p) => ({ label: `${p.name} (${p.id})`, value: p.id })),
			);
			if (!provPick) break;
			let models: string[] = [];
			try {
				models = mergeModels(await onboardFetchModels(provPick, undefined), staticModels(provPick));
			} catch {
				models = staticModels(provPick);
			}
			for (;;) {
				const m = await askSelect(settingsManager, theme, `Pick models from ${provPick}:`, [
					...models.filter((x) => !pool.includes(x)).map((x) => ({ label: x, value: x })),
					{ label: "✎ Type model slug manually…", value: "__manual" },
				], { label: `Done (${pool.length} picked)`, value: "__done" });
				if (!m || m === "__done") break;
				const slug = m === "__manual"
					? await askInput(settingsManager, theme, `Model slug for ${provPick} (must contain /):`, undefined)
					: m;
				if (slug && !pool.includes(slug)) pool.push(slug);
			}
			if (pool.length === 0) break;
		}
	}

	// Step 6: final confirm → home.
	const go = await askSelect(settingsManager, theme, "Setup complete. Start Ramanujan?", [
		{ label: "Yes — open chat", value: "yes" },
	]);
	if (go === undefined) return;
	// Clear all setup chatter: "open chat" must land on the normal default
	// state (single themed ASCII banner + chatbox, nothing else in scrollback).
	try {
		console.clear();
	} catch {
		// non-TTY already excluded by the gate; best effort
	}
}
