/**
 * Minimal TOML for the Ramanujan config schema only.
 * Handles: comments (#), blank lines, `key = "string"|int`, `[table]`,
 * `[[array-table]]`. String escapes \" and \\. Anything else throws —
 * the Python side (tomllib) is the reference parser.
 */

import type { ProviderConfig, RamanujanConfig, RoleSpec } from "./types.ts";

function unescape(s: string): string {
	return s.replace(/\\(.)/g, (_, ch: string) => (ch === "n" ? "\n" : ch === "t" ? "\t" : ch));
}

function escape(s: string): string {
	return s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function parseValue(raw: string): string | number {
	const t = raw.trim();
	if (t.startsWith('"') && t.endsWith('"') && t.length >= 2) {
		return unescape(t.slice(1, -1));
	}
	if (/^-?\d+$/.test(t)) return parseInt(t, 10);
	throw new Error(`unsupported TOML value: ${raw}`);
}

export function parseConfig(text: string): RamanujanConfig {
	const cfg: RamanujanConfig = { version: 1, providers: [], roles: {} };
	let current: { kind: "root" } | { kind: "provider"; ref: ProviderConfig } | { kind: "role"; role: "encoder" | "assistant" | "main_model" } | { kind: "panel"; ref: RoleSpec } =
		{ kind: "root" };

	for (const rawLine of text.split("\n")) {
		const line = rawLine.trim();
		if (!line || line.startsWith("#")) continue;
		const tableMatch = line.match(/^\[\[([^\]]+)\]\]$/);
		if (tableMatch) {
			const name = tableMatch[1].trim();
			if (name === "providers") {
				const ref: ProviderConfig = { id: "", name: "", base_url: "", family: "" };
				cfg.providers.push(ref);
				current = { kind: "provider", ref };
				continue;
			}
			if (name === "roles.panel") {
				const ref: RoleSpec = { provider: "", model_id: "" };
				cfg.roles.panel = cfg.roles.panel ?? [];
				cfg.roles.panel.push(ref);
				current = { kind: "panel", ref };
				continue;
			}
			throw new Error(`unsupported array table: [[${name}]]`);
		}
		const singleMatch = line.match(/^\[([^\]]+)\]$/);
		if (singleMatch) {
			const name = singleMatch[1].trim();
			if (name === "roles.encoder") {
				cfg.roles.encoder = { provider: "", model_id: "" };
				current = { kind: "role", role: "encoder" };
				continue;
			}
			if (name === "roles.assistant") {
				cfg.roles.assistant = { provider: "", model_id: "" };
				current = { kind: "role", role: "assistant" };
				continue;
			}
			if (name === "roles.main_model") {
				cfg.roles.main_model = { provider: "", model_id: "" };
				current = { kind: "role", role: "main_model" };
				continue;
			}
			throw new Error(`unsupported table: [${name}]`);
		}
		const kvMatch = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/);
		if (!kvMatch) throw new Error(`cannot parse TOML line: ${rawLine}`);
		const key = kvMatch[1];
		const value = parseValue(kvMatch[2]);
		if (current.kind === "root") {
			if (key === "version") {
				if (typeof value !== "number") throw new Error("version must be an integer");
				cfg.version = value;
				continue;
			}
			throw new Error(`unexpected root key: ${key}`);
		}
		if (current.kind === "provider") {
			const ref = current.ref as unknown as Record<string, string | number>;
			if (typeof value === "number") throw new Error(`provider field ${key} must be a string`);
			ref[key] = value;
			continue;
		}
		if (current.kind === "role") {
			const target =
				current.role === "encoder"
					? cfg.roles.encoder
					: current.role === "assistant"
						? cfg.roles.assistant
						: cfg.roles.main_model;
			if (!target) throw new Error("internal: role target missing");
			(target as unknown as Record<string, string | number>)[key] = value;
			continue;
		}
		const pref = current.ref as unknown as Record<string, string | number>;
		pref[key] = value;
	}
	return cfg;
}

export function stringifyConfig(cfg: RamanujanConfig): string {
	const lines: string[] = [];
	lines.push(`version = ${cfg.version}`);
	lines.push("");
	for (const p of cfg.providers) {
		lines.push("[[providers]]");
		lines.push(`id = "${escape(p.id)}"`);
		lines.push(`name = "${escape(p.name)}"`);
		lines.push(`base_url = "${escape(p.base_url)}"`);
		if (p.api_key_env) lines.push(`api_key_env = "${escape(p.api_key_env)}"`);
		if (p.api_key) lines.push(`api_key = "${escape(p.api_key)}"`);
		lines.push(`family = "${escape(p.family)}"`);
		lines.push("");
	}
	if (cfg.roles.encoder) {
		lines.push("[roles.encoder]");
		lines.push(`provider = "${escape(cfg.roles.encoder.provider)}"`);
		lines.push(`model_id = "${escape(cfg.roles.encoder.model_id)}"`);
		lines.push("");
	}
	if (cfg.roles.assistant) {
		lines.push("[roles.assistant]");
		lines.push(`provider = "${escape(cfg.roles.assistant.provider)}"`);
		lines.push(`model_id = "${escape(cfg.roles.assistant.model_id)}"`);
		lines.push("");
	}
	if (cfg.roles.main_model) {
		lines.push("[roles.main_model]");
		lines.push(`provider = "${escape(cfg.roles.main_model.provider)}"`);
		lines.push(`model_id = "${escape(cfg.roles.main_model.model_id)}"`);
		lines.push("");
	}
	for (const r of cfg.roles.panel ?? []) {
		lines.push("[[roles.panel]]");
		lines.push(`provider = "${escape(r.provider)}"`);
		lines.push(`model_id = "${escape(r.model_id)}"`);
		lines.push("");
	}
	return lines.join("\n");
}
