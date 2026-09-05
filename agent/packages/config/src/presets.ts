/**
 * Preset store — mirrors ramanujan/presets.py.
 * ~/.config/ramanujan/presets.json (JSON object name -> string[]), env RAMANUJAN_PRESETS.
 * Warns on deadlock (validatePreset), never blocks.
 */

import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";
import { loadRegistry, validatePreset, type PresetCheck } from "./families.ts";

function defaultPresetsPath(): string {
	const over = process.env["RAMANUJAN_PRESETS"];
	if (over) return over;
	return join(homedir(), ".config", "ramanujan", "presets.json");
}

export function loadPresets(path?: string): Record<string, string[]> {
	const p = path ?? defaultPresetsPath();
	if (!existsSync(p)) return {};
	const data = JSON.parse(readFileSync(p, "utf-8"));
	if (typeof data !== "object" || data === null || Array.isArray(data)) throw new Error(`presets must be object at ${p}`);
	const out: Record<string, string[]> = {};
	for (const [k, v] of Object.entries(data)) {
		if (typeof k !== "string" || !k.trim()) throw new Error(`invalid preset name: ${k}`);
		if (!Array.isArray(v) || !v.every((x) => typeof x === "string" && (x as string).trim())) throw new Error(`preset ${k} must be string[]`);
		out[k.trim()] = (v as string[]).map((x) => x.trim());
	}
	return out;
}

export function savePresets(presets: Record<string, string[]>, path?: string): void {
	const p = path ?? defaultPresetsPath();
	mkdirSync(dirname(p), { recursive: true });
	const tmp = `${p}.${process.pid}.${Date.now()}.tmp`;
	writeFileSync(tmp, JSON.stringify(presets, null, 2) + "\n", "utf-8");
	renameSync(tmp, p);
	try {
		chmodSync(p, 0o600);
	} catch {
		// best effort
	}
}

export function getPreset(name: string, path?: string): string[] | null {
	return loadPresets(path)[name] ?? null;
}

export function checkPreset(name: string, models: string[], registryPath?: string): PresetCheck {
	const reg = loadRegistry(registryPath);
	return validatePreset(name, models, reg);
}

export function setPreset(name: string, models: string[], path?: string, registryPath?: string): PresetCheck {
	const reg = loadRegistry(registryPath);
	const check = validatePreset(name, models, reg);
	const presets = loadPresets(path);
	presets[name] = [...models];
	savePresets(presets, path);
	return check;
}

export function deletePreset(name: string, path?: string): boolean {
	const presets = loadPresets(path);
	if (!(name in presets)) return false;
	delete presets[name];
	savePresets(presets, path);
	return true;
}
