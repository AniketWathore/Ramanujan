"""Tests for presets + main_model — Phase 3."""

import json
import stat

from ramanujan.config import ProviderConfig, RamanujanConfig, load_config, save_config
from ramanujan.presets import check_preset, load_presets, save_presets, set_preset


def test_main_model_round_trip(tmp_path):
    p = tmp_path / "config.toml"
    cfg = RamanujanConfig(
        providers=[ProviderConfig(id="nvidia", name="NVIDIA", base_url="https://example.com/v1", api_key="nvapi-fake", family="nvidia")],
        roles={
            "encoder": {"provider": "nvidia", "model_id": "nvidia/m-enc"},
            "main_model": {"provider": "nvidia", "model_id": "nvidia/m-main"},
        },  # type: ignore
    )
    save_config(cfg, p)
    loaded = load_config(p)
    assert loaded.roles.main_model is not None
    assert loaded.roles.main_model.model_id == "nvidia/m-main"
    # providers.remove should clear main_model if id matches
    cfg2 = load_config(p)
    # simulate cli providers remove clearing
    cfg2.providers = [pr for pr in cfg2.providers if pr.id != "nvidia"]
    if cfg2.roles.main_model and cfg2.roles.main_model.provider == "nvidia":
        cfg2.roles.main_model = None
    save_config(cfg2, p)
    assert load_config(p).roles.main_model is None


def test_presets_round_trip_and_0600(tmp_path):
    p = tmp_path / "presets.json"
    save_presets({"fast-3": ["a/m1", "b/m2"]}, p)
    assert load_presets(p) == {"fast-3": ["a/m1", "b/m2"]}
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_presets_deadlock_warning(tmp_path):
    p = tmp_path / "presets.json"
    # Single family (openai + openrouter share family) -> warns
    chk = set_preset("dead", ["openai/gpt-5-2025-08-07", "openrouter/gpt-5"], p)
    assert chk.ok is False
    assert chk.warning is not None and "never panel-verified" in chk.warning
    # Still saved — never blocked
    assert load_presets(p)["dead"] == ["openai/gpt-5-2025-08-07", "openrouter/gpt-5"]
    # Two families -> ok with note
    chk2 = set_preset("ok2", ["openai/gpt-5-2025-08-07", "google/gemini-3-pro"], p)
    assert chk2.ok is True
    assert chk2.note is not None and "3+" in chk2.note
    # Empty list -> warns
    chk3 = check_preset("empty", [], None)
    assert chk3.ok is False


def test_presets_cli_smoke(tmp_path, monkeypatch):
    # Ensure presets and config are isolated
    cfg_path = tmp_path / "config.toml"
    presets_path = tmp_path / "presets.json"
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(cfg_path))
    monkeypatch.setenv("RAMANUJAN_PRESETS", str(presets_path))
    from ramanujan.config import ProviderConfig, RamanujanConfig, save_config

    save_config(
        RamanujanConfig(
            providers=[
                ProviderConfig(id="nvidia", name="NVIDIA", base_url="https://example.com/v1", api_key="nvapi-fake", family="nvidia"),
                ProviderConfig(id="google", name="Google", base_url="https://example.com/v1", api_key="fake2", family="google"),
            ],
            roles={},
        ),
        cfg_path,
    )
    from click.testing import CliRunner

    from ramanujan.cli import main

    runner = CliRunner()
    # set main_model
    res = runner.invoke(main, ["roles", "set-main-model", "nvidia", "nvidia/main-1"])
    assert res.exit_code == 0, res.output
    res = runner.invoke(main, ["roles", "show"])
    assert "main_model: provider=nvidia" in res.output
    # presets add -> two families ok with note (but saved)
    res = runner.invoke(main, ["presets", "add", "demo", "nvidia/main-1", "google/gemini-3-pro"])
    assert res.exit_code == 0, res.output
    res = runner.invoke(main, ["presets", "list", "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["presets"]["demo"]["ok"] is True
    # presets show json
    res = runner.invoke(main, ["presets", "show", "demo", "--json"])
    assert res.exit_code == 0
    assert "demo" in res.output
    # presets add single-family warns but still adds
    res = runner.invoke(main, ["presets", "add", "solo", "nvidia/main-1"])
    assert res.exit_code == 0
    assert "never panel-verified" in res.output
    res = runner.invoke(main, ["presets", "show", "solo", "--json"])
    assert json.loads(res.output)["ok"] is False
    # remove
    res = runner.invoke(main, ["presets", "remove", "solo"])
    assert res.exit_code == 0


def test_initialise_uses_main_model_fallback(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    presets_path = tmp_path / "presets.json"
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(cfg_path))
    monkeypatch.setenv("RAMANUJAN_PRESETS", str(presets_path))
    monkeypatch.setenv("RAMANUJAN_MOCK_ENCODER", "1")
    from ramanujan.config import ProviderConfig, RamanujanConfig, save_config

    save_config(
        RamanujanConfig(
            providers=[ProviderConfig(id="nvidia", name="N", base_url="https://example.com/v1", api_key="nvapi-fake", family="nvidia")],
            roles={"main_model": {"provider": "nvidia", "model_id": "nvidia/main-1"}},  # type: ignore
        ),
        cfg_path,
    )
    from click.testing import CliRunner

    from ramanujan.cli import main

    runner = CliRunner()
    stmt = "For every integer n >= 0, n^2 + n + 41 is prime."
    res = runner.invoke(main, ["initialise", "--statement", stmt, "--journal", str(tmp_path / "j.jsonl"), "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["status"] == "spec"
    assert data["provider"] == "nvidia"
    assert data["model_id"] == "nvidia/main-1"
    assert "main_model" in data["role_note"]
    # Fallback: remove main_model, encoder remains -> initialise still works via encoder fallback
    save_config(
        RamanujanConfig(
            providers=[ProviderConfig(id="nvidia", name="N", base_url="https://example.com/v1", api_key="nvapi-fake", family="nvidia")],
            roles={"encoder": {"provider": "nvidia", "model_id": "nvidia/enc-1"}},  # type: ignore
        ),
        cfg_path,
    )
    res2 = runner.invoke(main, ["initialise", "--statement", stmt, "--journal", str(tmp_path / "j2.jsonl"), "--json"])
    assert res2.exit_code == 0, res2.output
    data2 = json.loads(res2.output)
    assert data2["status"] == "spec"
    assert "fallback" in data2["role_note"]
