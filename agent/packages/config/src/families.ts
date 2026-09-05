/**
 * Family registry + preset deadlock guard — mirrors ramanujan/families.py.
 * Family for a `provider/model` ref is looked up literally, never inferred.
 */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export const UNKNOWN_FAMILY = "family:unknown";
export const DEADLOCK_WARNING = "This preset can only reach budget/stall termination, never panel-verified. Proceed anyway?";

function defaultRegistryPath(): string {
	// Repo checkout: agent/packages/config/src/* -> ../../../../specs/family_registry.json
	try {
		const here = fileURLToPath(import.meta.url);
		const cand = join(here, "..", "..", "..", "..", "..", "specs", "family_registry.json");
		if (existsSync(cand)) return cand;
	} catch {
		// ignore
	}
	return "specs/family_registry.json";
}

export function loadRegistry(path?: string): Record<string, string> {
	const p = path ?? defaultRegistryPath();
	const data = JSON.parse(readFileSync(p, "utf-8"));
	if (typeof data !== "object" || data === null || Array.isArray(data)) throw new Error(`family registry must be object: ${p}`);
	for (const [k, v] of Object.entries(data)) {
		if (typeof k !== "string" || !k.trim() || typeof v !== "string" || !v.trim()) throw new Error(`invalid registry entry: ${k}: ${v}`);
	}
	return data as Record<string, string>;
}

export function familyOf(modelRef: string, registry: Record<string, string>): string {
	return registry[modelRef.trim()] ?? UNKNOWN_FAMILY;
}

export function presetFamilies(models: string[], registry: Record<string, string>): Set<string> {
	return new Set(models.map((m) => familyOf(m, registry)));
}

export interface PresetCheck {
	name: string;
	models: string[];
	families: Set<string>;
	ok: boolean;
	warning: string | null;
	note: string | null;
}

export function validatePreset(name: string, models: string[], registry: Record<string, string>): PresetCheck {
	const families = presetFamilies(models, registry);
	if (families.size < 2) {
		return {
			name,
			models: [...models],
			families,
			ok: false,
			warning: `Preset ${JSON.stringify(name)} covers ${families.size} distinct family (${[...families].sort().join(", ") || "none"}). ${DEADLOCK_WARNING}`,
			note: null,
		};
	}
	let note: string | null = null;
	if (families.size === 2) {
		note = `Preset ${JSON.stringify(name)} covers exactly 2 distinct families ${JSON.stringify([...families].sort())} — the bare deadlock-avoiding floor. 3+ families recommended for trustworthy panel-verified stops.`;
	}
	return { name, models: [...models], families, ok: true, warning: null, note };
}
