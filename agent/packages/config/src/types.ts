/**
 * Config schema — identical to ramanujan/config.py.
 * roles.panel is multi-model (A6 consumes it); assistant/encoder single.
 */

export interface ProviderConfig {
	id: string;
	name: string;
	base_url: string;
	api_key_env?: string | null;
	api_key?: string | null;
	family: string;
}

export interface RoleSpec {
	provider: string;
	model_id: string;
}

export interface RolesConfig {
	encoder?: RoleSpec | null;
	assistant?: RoleSpec | null;
	panel?: RoleSpec[] | null;
}

export interface RamanujanConfig {
	version: number;
	providers: ProviderConfig[];
	roles: RolesConfig;
}

export function emptyConfig(): RamanujanConfig {
	return { version: 1, providers: [], roles: {} };
}

const PROVIDER_ID_RE = /^[a-z0-9_-]+$/;

export function validateProviderConfig(p: ProviderConfig): void {
	if (!PROVIDER_ID_RE.test(p.id)) throw new Error(`invalid provider id: ${p.id} (must match [a-z0-9_-]+)`);
	if (!p.name) throw new Error("provider name required");
	if (!p.base_url) throw new Error("provider base_url required");
	if (!p.family) throw new Error("provider family required");
}

export function validateRoleSpec(r: RoleSpec): void {
	if (!r.provider) throw new Error("role provider required");
	if (!r.model_id) throw new Error("role model_id required");
}

export function validateConfig(cfg: RamanujanConfig): void {
	if (cfg.version < 1) throw new Error(`unsupported config version: ${cfg.version}`);
	for (const p of cfg.providers) validateProviderConfig(p);
	if (cfg.roles.encoder) validateRoleSpec(cfg.roles.encoder);
	if (cfg.roles.assistant) validateRoleSpec(cfg.roles.assistant);
	for (const r of cfg.roles.panel ?? []) validateRoleSpec(r);
}
