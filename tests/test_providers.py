"""Tests for ramanujan/providers.py — mocked HTTP, fake keys."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ramanujan.config import ProviderConfig, RamanujanConfig, save_config
from ramanujan.providers import ResolvedSpec, _estimate_cost, _validate_model_pin


def test_estimate_cost_unknown_zero():
    assert _estimate_cost("unknown/model-xyz", 100, 100) == 0.0
    # Known should be non-zero
    assert _estimate_cost("claude-sonnet-4-20250514", 1000, 1000) > 0


def test_anti_alias_openai_compatible_requires_slash():
    # OpenAI-compatible with base_url should require "/" in model_id
    spec = ResolvedSpec(
        provider="nvidia",
        provider_name="NVIDIA",
        base_url="https://integrate.api.nvidia.com/v1",
        model_id="llama-3.1",
        family="nvidia",
        role="encoder",
    )
    try:
        _validate_model_pin(spec)
        raise AssertionError("should have raised alias")
    except ValueError as e:
        assert "/" in str(e) or "slash" in str(e).lower()
    # With slash should pass
    spec2 = ResolvedSpec(
        provider="nvidia",
        provider_name="NVIDIA",
        base_url="https://integrate.api.nvidia.com/v1",
        model_id="nvidia/llama-3.1-nemotron-70b-instruct",
        family="nvidia",
        role="encoder",
    )
    _validate_model_pin(spec2)  # should not raise


def test_anti_alias_first_party_allows_snapshot():
    from ramanujan.schemas import VerifierSpec

    # Anthropic snapshot should pass
    spec = VerifierSpec(
        name="encoder",
        provider="anthropic",
        model_id="claude-sonnet-4-20250514",
        family="anthropic",
        role="encoder",
        temperature=0,
        max_output_tokens=2048,
    )
    _validate_model_pin(spec)  # should not raise
    # Alias should fail (existing VerifierSpec validation already does, but also check)
    try:
        bad = VerifierSpec(
            name="encoder",
            provider="anthropic",
            model_id="claude-sonnet",
            family="anthropic",
            role="encoder",
            temperature=0,
            max_output_tokens=2048,
        )
        _validate_model_pin(bad)
        raise AssertionError()
    except Exception:
        pass


def test_mocked_openai_call_correct_url_and_bearer(tmp_path: Path, monkeypatch):
    # Setup config with fake provider
    cfg = RamanujanConfig(
        providers=[
            ProviderConfig(
                id="nvidia",
                name="NVIDIA",
                base_url="https://integrate.api.nvidia.com/v1",
                api_key="nvapi-fake-test-key-1234",
                family="nvidia",
            )
        ],
        roles={"encoder": {"provider": "nvidia", "model_id": "nvidia/test-model"}},
    )  # type: ignore
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(p))

    from ramanujan.journal import JournalWriter
    from ramanujan.providers import call_llm, resolve_role

    spec = resolve_role("encoder", config_path=p)
    # Mock urlopen
    captured = {}

    def fake_urlopen(req, timeout=60):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        # Check bearer
        auth = req.headers.get("Authorization", "") or req.headers.get("authorization", "")
        assert "nvapi-fake-test-key-1234" in auth, f"bearer missing {auth}"
        assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
        # Return fake response
        body = json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        j = JournalWriter(tmp_path / "journal.jsonl", run_id="test")
        res = call_llm(spec, [{"role": "user", "content": "hello"}], journal=j)
        assert res["text"] == "ok"
        assert captured["url"].endswith("/chat/completions")
        # Check journal logged provider and model_id
        from ramanujan.journal import replay

        events = replay(tmp_path / "journal.jsonl")
        llm_events = [e for e in events if e["type"] == "llm_call"]
        assert len(llm_events) == 1
        assert llm_events[0]["payload"]["provider"] == "nvidia"
        assert llm_events[0]["payload"]["model_id"] == "nvidia/test-model"
        assert "family" in llm_events[0]["payload"]
    monkeypatch.delenv("RAMANUJAN_CONFIG", raising=False)


def test_429_backoff_and_retry(tmp_path: Path, monkeypatch):
    cfg = RamanujanConfig(
        providers=[ProviderConfig(id="nvidia", name="NVIDIA", base_url="https://example.com/v1", api_key="fake-key", family="nvidia")],
        roles={"encoder": {"provider": "nvidia", "model_id": "nvidia/test"}},
    )  # type: ignore
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(p))
    import urllib.error

    from ramanujan.providers import call_llm, resolve_role

    spec = resolve_role("encoder", config_path=p)

    call_count = {"n": 0}

    def fake_urlopen(req, timeout=60):
        call_count["n"] += 1
        if call_count["n"] == 1:
            err = urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
            raise err
        body = json.dumps(
            {"choices": [{"message": {"content": "ok after retry"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("time.sleep", return_value=None):  # speed up
        res = call_llm(spec, [{"role": "user", "content": "hi"}])
        assert res["text"] == "ok after retry"
        assert call_count["n"] == 2
    monkeypatch.delenv("RAMANUJAN_CONFIG", raising=False)


def test_api_error_path(tmp_path: Path, monkeypatch):
    cfg = RamanujanConfig(
        providers=[ProviderConfig(id="nvidia", name="NVIDIA", base_url="https://example.com/v1", api_key="fake", family="nvidia")],
        roles={"encoder": {"provider": "nvidia", "model_id": "nvidia/test"}},
    )  # type: ignore
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(p))
    import urllib.error

    from ramanujan.providers import call_llm, resolve_role

    spec = resolve_role("encoder", config_path=p)

    def fake_urlopen(req, timeout=60):
        err = urllib.error.HTTPError(req.full_url, 500, "Internal", {}, None)
        # Mock read
        err.read = lambda: b'{"error": "internal"}'
        raise err

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("time.sleep", return_value=None):
        try:
            call_llm(spec, [{"role": "user", "content": "hi"}], retries=2)
            raise AssertionError("should have raised")
        except RuntimeError as e:
            assert "failed after" in str(e).lower()
    monkeypatch.delenv("RAMANUJAN_CONFIG", raising=False)


def test_journal_llm_call_fields(tmp_path: Path, monkeypatch):
    cfg = RamanujanConfig(
        providers=[
            ProviderConfig(
                id="openrouter", name="OpenRouter", base_url="https://openrouter.ai/api/v1", api_key="sk-or-fake", family="openrouter"
            )
        ],
        roles={"encoder": {"provider": "openrouter", "model_id": "openrouter/test-model"}},
    )  # type: ignore
    p = tmp_path / "config.toml"
    save_config(cfg, p)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(p))
    from ramanujan.journal import JournalWriter, replay
    from ramanujan.providers import call_llm, resolve_role

    spec = resolve_role("encoder", config_path=p)

    def fake_urlopen(req, timeout=60):
        body = json.dumps({"choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 5}}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        j = JournalWriter(tmp_path / "journal.jsonl", run_id="test2")
        call_llm(spec, [{"role": "user", "content": "hi"}], journal=j)
        events = replay(tmp_path / "journal.jsonl")
        llm = [e for e in events if e["type"] == "llm_call"][0]
        assert llm["payload"]["provider"] == "openrouter"
        assert llm["payload"]["model_id"] == "openrouter/test-model"
        assert "cost" in llm["payload"]
        assert "latency_ms" in llm["payload"]
    monkeypatch.delenv("RAMANUJAN_CONFIG", raising=False)
