"""Config management — ramanujan/config.py

User-facing multi-provider config at ~/.config/ramanujan/config.toml (0600).
Keys may be stored in file (0600) or via env var (env overrides stored).
No key is ever journaled, logged, or printed except masked first-4 + ….
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Default path outside repo — never committed
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "ramanujan" / "config.toml"


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^[a-z0-9_-]+$", description="short id for CLI")
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1, description="OpenAI-compatible base_url, e.g. https://integrate.api.nvidia.com/v1")
    api_key_env: str | None = Field(default=None, description="env var name for key")
    api_key: str | None = Field(default=None, description="stored key, 0600 file")
    family: str = Field(min_length=1, description="family for panel exclusion")

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


class RoleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str = Field(min_length=1, description="provider id")
    model_id: str = Field(min_length=1, description="pinned full slug, e.g. nvidia/llama-3.1-nemotron-70b-instruct")


class RolesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    encoder: RoleSpec | None = None
    assistant: RoleSpec | None = None
    main_model: RoleSpec | None = None
    panel: list[RoleSpec] | None = None


class RamanujanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(default=1, ge=1)
    providers: list[ProviderConfig] = Field(default_factory=list)
    roles: RolesConfig = Field(default_factory=RolesConfig)

    def provider_by_id(self, pid: str) -> ProviderConfig | None:
        for p in self.providers:
            if p.id == pid:
                return p
        return None


def _config_path() -> Path:
    # Allow override via env for tests
    env = os.environ.get("RAMANUJAN_CONFIG")
    if env:
        return Path(env).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: Path | None = None) -> RamanujanConfig:
    p = Path(path) if path is not None else _config_path()
    if not p.exists():
        return RamanujanConfig()
    # Use tomllib (Python 3.11+)
    try:
        import tomllib  # type: ignore
    except ImportError:
        import tomli as tomllib  # type: ignore
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    # toml structure: version, [[providers]], [roles.encoder] etc.
    # Pydantic will validate
    return RamanujanConfig.model_validate(data)


def save_config(cfg: RamanujanConfig, path: Path | None = None) -> None:
    p = Path(path) if path is not None else _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Build toml manually to avoid extra deps and ensure 0600
    lines: list[str] = []
    lines.append(f"version = {cfg.version}")
    lines.append("")
    for prov in cfg.providers:
        lines.append("[[providers]]")
        lines.append(f'id = "{prov.id}"')
        lines.append(f'name = "{prov.name}"')
        lines.append(f'base_url = "{prov.base_url}"')
        if prov.api_key_env:
            lines.append(f'api_key_env = "{prov.api_key_env}"')
        if prov.api_key:
            # Escape quotes
            escaped = prov.api_key.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'api_key = "{escaped}"')
        lines.append(f'family = "{prov.family}"')
        lines.append("")
    if cfg.roles.encoder is not None:
        lines.append("[roles.encoder]")
        lines.append(f'provider = "{cfg.roles.encoder.provider}"')
        lines.append(f'model_id = "{cfg.roles.encoder.model_id}"')
        lines.append("")
    if cfg.roles.assistant is not None:
        lines.append("[roles.assistant]")
        lines.append(f'provider = "{cfg.roles.assistant.provider}"')
        lines.append(f'model_id = "{cfg.roles.assistant.model_id}"')
        lines.append("")
    if cfg.roles.main_model is not None:
        lines.append("[roles.main_model]")
        lines.append(f'provider = "{cfg.roles.main_model.provider}"')
        lines.append(f'model_id = "{cfg.roles.main_model.model_id}"')
        lines.append("")
    if cfg.roles.panel:
        for item in cfg.roles.panel:
            lines.append("[[roles.panel]]")
            lines.append(f'provider = "{item.provider}"')
            lines.append(f'model_id = "{item.model_id}"')
            lines.append("")
    content = "\n".join(lines)
    if not content.endswith("\n"):
        content += "\n"
    # Atomic write via tempfile+replace, then chmod 0600
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, p)
        # Ensure 0600
        with contextlib.suppress(Exception):
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def resolve_provider_key(provider: ProviderConfig) -> str | None:
    """Resolve key with precedence: env var > stored > None. Never logs key."""
    # Env override
    if provider.api_key_env:
        env_val = os.environ.get(provider.api_key_env)
        if env_val:
            return env_val
    # Stored
    if provider.api_key:
        return provider.api_key
    # Also try generic env based on id? Not needed, but check legacy
    return None


def mask_key(key: str) -> str:
    if not key:
        return "missing"
    if len(key) <= 8:
        return key[:2] + "…" + key[-2:]
    return key[:4] + "…" + key[-4:]


def key_status(provider: ProviderConfig) -> str:
    if provider.api_key_env and os.environ.get(provider.api_key_env):
        return "env"
    if provider.api_key:
        return "stored"
    return "missing"
