"""Tests for ramanujan/config.py — all mocked, fake keys."""

from __future__ import annotations

import stat
from pathlib import Path

from ramanujan.config import ProviderConfig, RamanujanConfig, load_config, mask_key, resolve_provider_key, save_config


def test_config_round_trip(tmp_path: Path):
    cfg = RamanujanConfig(
        version=1,
        providers=[
            ProviderConfig(
                id="nvidia",
                name="NVIDIA NIM",
                base_url="https://integrate.api.nvidia.com/v1",
                api_key_env="NVIDIA_API_KEY",
                api_key="nvapi-fake123",
                family="nvidia",
            ),
            ProviderConfig(
                id="openrouter",
                name="OpenRouter",
                base_url="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_API_KEY",
                family="openrouter",
            ),
        ],
        roles={"encoder": {"provider": "nvidia", "model_id": "nvidia/llama-3.1-nemotron-70b-instruct"}},  # type: ignore
    )
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded.version == 1
    assert len(loaded.providers) == 2
    assert loaded.providers[0].id == "nvidia"
    assert loaded.providers[0].api_key == "nvapi-fake123"
    assert loaded.roles.encoder is not None
    assert loaded.roles.encoder.provider == "nvidia"
    assert loaded.roles.encoder.model_id == "nvidia/llama-3.1-nemotron-70b-instruct"


def test_config_0600(tmp_path: Path):
    cfg = RamanujanConfig(
        providers=[ProviderConfig(id="test", name="Test", base_url="https://example.com/v1", family="test", api_key="secret123")]
    )
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, f"expected 0600 got {oct(mode)}"


def test_key_precedence_env_over_stored(tmp_path: Path, monkeypatch):
    cfg = RamanujanConfig(
        providers=[
            ProviderConfig(
                id="nvidia",
                name="NVIDIA",
                base_url="https://example.com/v1",
                api_key_env="NVIDIA_API_KEY",
                api_key="stored-key-123",
                family="nvidia",
            )
        ]
    )
    # Without env, stored wins
    assert resolve_provider_key(cfg.providers[0]) == "stored-key-123"
    # With env, env wins
    monkeypatch.setenv("NVIDIA_API_KEY", "env-key-xyz")
    assert resolve_provider_key(cfg.providers[0]) == "env-key-xyz"
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)


def test_masked_key():
    assert mask_key("nvapi-1234567890abcdef") == "nvap…cdef"
    assert mask_key("short") == "sh…rt"
    assert mask_key("") == "missing"


def test_resolve_role(tmp_path: Path, monkeypatch):
    # Setup config with provider and role
    cfg = RamanujanConfig(
        providers=[
            ProviderConfig(
                id="nvidia", name="NVIDIA", base_url="https://integrate.api.nvidia.com/v1", api_key="nvapi-fake", family="nvidia"
            )
        ],
        roles={"encoder": {"provider": "nvidia", "model_id": "nvidia/test-model"}},  # type: ignore
    )
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(p))
    from ramanujan.providers import resolve_role

    spec = resolve_role("encoder", config_path=p)
    assert spec.provider == "nvidia"
    assert spec.model_id == "nvidia/test-model"
    assert spec.base_url == "https://integrate.api.nvidia.com/v1"
    assert spec.family == "nvidia"
    monkeypatch.delenv("RAMANUJAN_CONFIG", raising=False)


def test_resolve_role_missing_key(tmp_path: Path, monkeypatch):
    cfg = RamanujanConfig(
        providers=[
            ProviderConfig(id="nvidia", name="NVIDIA", base_url="https://example.com/v1", api_key_env="NVIDIA_API_KEY", family="nvidia")
        ],
        roles={"encoder": {"provider": "nvidia", "model_id": "nvidia/test"}},  # type: ignore
    )
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(p))
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    from ramanujan.providers import resolve_role

    try:
        resolve_role("encoder", config_path=p)
        raise AssertionError("should have raised no key")
    except ValueError as e:
        assert "no key" in str(e).lower()
    monkeypatch.delenv("RAMANUJAN_CONFIG", raising=False)
