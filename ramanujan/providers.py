"""LLM abstraction — ramanujan/providers.py

VerifierSpec, call logging, retries, model pinning, multi-provider.
Supports generic OpenAI-compatible providers via config.
Every LLM call logged: provider id + exact model_id.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml  # type: ignore

from ramanujan.schemas import VerifierSpec


def load_spec(path: Path | str = "specs/verifier_specs/encoder.yaml") -> VerifierSpec:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return VerifierSpec.model_validate(data)


# Simple cost table (per 1M tokens) — unknown → 0.0
_COST_PER_1M: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku": {"input": 1.0, "output": 5.0},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "nvidia": {"input": 0.0, "output": 0.0},
    "openrouter": {"input": 0.0, "output": 0.0},
}

# Type for injected LLM caller (for tests)
LlmCaller = Callable[[VerifierSpec, list[dict[str, str]]], dict[str, Any]]


class ResolvedSpec:
    """Internal resolved spec from config or yaml — carries base_url, family, pin."""

    def __init__(
        self,
        provider: str,
        provider_name: str,
        base_url: str,
        model_id: str,
        family: str,
        role: str,
        temperature: float = 0,
        max_output_tokens: int = 2048,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.family = family
        self.role = role
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    # Compatibility with VerifierSpec attribute access
    @property
    def model_id_prop(self) -> str:
        return self.model_id


def _estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    # Unknown → 0.0, never crash
    for k, v in _COST_PER_1M.items():
        if model_id == k or model_id.startswith(k):
            return (v["input"] * input_tokens + v["output"] * output_tokens) / 1_000_000
        if "/" in model_id and k in model_id:
            # For slugs like nvidia/llama -> match family
            pass
    # If not found, check family prefix
    # For openai-compatible, unknown cost → 0.0
    return 0.0


def _is_openai_compatible_provider(provider_id: str, base_url: str) -> bool:
    # Any provider whose base_url is not anthropic.com is openai-compatible.
    return "anthropic.com" not in base_url


def _validate_model_pin(spec: ResolvedSpec | VerifierSpec) -> None:
    mid = spec.model_id
    provider = getattr(spec, "provider", "")
    base_url = getattr(spec, "base_url", "")
    # Determine if openai-compatible
    is_compat = False
    if isinstance(spec, ResolvedSpec):
        is_compat = _is_openai_compatible_provider(spec.provider, spec.base_url)
    else:
        # VerifierSpec: check provider field
        if (
            provider not in ("anthropic", "openai", "openai-codex")
            and base_url
            or provider in ("nvidia", "openrouter", "groq", "together", "vllm")
        ):
            is_compat = True
    if is_compat:
        # Full vendor/model slug containing "/" is the accepted pin
        if "/" not in mid:
            raise ValueError(f"openai-compatible model_id must be full slug containing '/': got {mid!r} for provider {provider}")
    else:
        # First-party: must be dated snapshot (existing VerifierSpec validator handles alias, but double-check)
        # Allow if contains date-like or snapshot
        pass


def resolve_role(role: str = "encoder", config_path: Path | None = None) -> ResolvedSpec:
    """Resolve role via config at ~/.config/ramanujan/config.toml (env > stored).
    Returns ResolvedSpec with base_url, model_id, family, provider.
    """
    from ramanujan.config import load_config, resolve_provider_key

    cfg = load_config(config_path)
    roles = cfg.roles
    # Get role spec
    role_spec = None
    if role == "encoder":
        role_spec = roles.encoder
    elif role == "assistant":
        role_spec = roles.assistant
    elif role == "main_model":
        role_spec = roles.main_model
    else:
        # Generic: try to get from roles dict if panel etc.
        # For now, only encoder/assistant/main_model
        raise ValueError(f"unknown role: {role}")

    if role_spec is None:
        raise ValueError(f"role {role!r} not configured. Run `ramanujan roles set-{role} <provider-id> <model-id>`")

    provider_cfg = cfg.provider_by_id(role_spec.provider)
    if provider_cfg is None:
        raise ValueError(f"provider {role_spec.provider!r} for role {role!r} not found in config")

    key = resolve_provider_key(provider_cfg)
    if not key:
        env_name = provider_cfg.api_key_env or f"{provider_cfg.id.upper()}_API_KEY"
        raise ValueError(
            f"no key for provider {provider_cfg.id!r} (env {env_name} or stored api_key). Run `ramanujan providers add` or set {env_name}"
        )

    spec = ResolvedSpec(
        provider=provider_cfg.id,
        provider_name=provider_cfg.name,
        base_url=provider_cfg.base_url,
        model_id=role_spec.model_id,
        family=provider_cfg.family,
        role=role,
    )
    _validate_model_pin(spec)
    return spec


def resolve_provider_by_id(provider_id: str, config_path: Path | None = None) -> tuple[ResolvedSpec, str]:
    """Resolve provider by id, return (dummy spec with base_url, key). Used for models/test."""
    from ramanujan.config import load_config, resolve_provider_key

    cfg = load_config(config_path)
    prov = cfg.provider_by_id(provider_id)
    if prov is None:
        raise ValueError(f"provider {provider_id!r} not found. Run `ramanujan providers list`")
    key = resolve_provider_key(prov)
    if not key:
        env_name = prov.api_key_env or f"{prov.id.upper()}_API_KEY"
        raise ValueError(f"no key for provider {prov.id!r} (env {env_name} or stored).")
    # Return a minimal spec for models/test
    spec = ResolvedSpec(
        provider=prov.id,
        provider_name=prov.name,
        base_url=prov.base_url,
        model_id="test",
        family=prov.family,
        role="test",
    )
    return spec, key


def _call_openai_compatible(
    spec: ResolvedSpec | VerifierSpec,
    messages: list[dict[str, str]],
    api_key: str,
) -> tuple[str, int, int]:
    # Use base_url from spec if ResolvedSpec, else default openai
    base_url = getattr(spec, "base_url", "https://api.openai.com/v1")
    # Ensure /chat/completions path
    url = base_url.rstrip("/") + "/chat/completions"
    # For some providers, base_url already includes /v1, so we append /chat/completions
    body = {
        "model": spec.model_id,
        "temperature": getattr(spec, "temperature", 0),
        "max_tokens": getattr(spec, "max_output_tokens", 2048),
        "messages": messages,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    # Handle 429/5xx with Retry-After
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Check for retryable
        if e.code in (429, 500, 502, 503, 504):
            # Try to honor Retry-After
            retry_after = e.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = int(retry_after)
                    time.sleep(min(delay, 10))
                except Exception:
                    pass
        err_body = e.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"OpenAI-compatible API error {e.code} at {url}: {err_body}") from e
    choice = resp_data.get("choices", [{}])[0]
    text = choice.get("message", {}).get("content", "") or choice.get("text", "")
    usage = resp_data.get("usage", {})
    input_tokens = int(usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0))
    output_tokens = int(usage.get("completion_tokens", 0) or usage.get("output_tokens", 0))
    return text, input_tokens, output_tokens


def call_llm(
    spec: VerifierSpec | ResolvedSpec,
    messages: list[dict[str, str]],
    *,
    journal: Any | None = None,
    retries: int = 3,
    caller: LlmCaller | None = None,
) -> dict[str, Any]:
    """Call LLM with retries, log to journal. Returns dict with text/tokens/cost/latency.
    Handles both VerifierSpec (legacy yaml) and ResolvedSpec (config).
    """
    # Validate pin
    try:
        _validate_model_pin(spec)
    except Exception as e:
        raise ValueError(f"model pin validation failed: {e}") from e

    # If caller injected (tests), use it
    if caller is not None:
        start = time.monotonic()
        result = caller(spec, messages)  # type: ignore[arg-type]
        latency_ms = int((time.monotonic() - start) * 1000)
        text = result.get("text", "")
        input_tokens = int(result.get("input_tokens", len(text) // 4))
        output_tokens = int(result.get("output_tokens", len(text) // 4))
        cost = float(result.get("cost", _estimate_cost(spec.model_id, input_tokens, output_tokens)))
        payload = {
            "model_id": spec.model_id,
            "provider": getattr(spec, "provider", "unknown"),
            "family": getattr(spec, "family", ""),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "latency_ms": latency_ms,
            "retries": 0,
        }
        if journal is not None:
            with contextlib.suppress(Exception):
                journal.write("llm_call", payload)
        return {
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "latency_ms": latency_ms,
        }

    # Real provider path
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            start = time.monotonic()
            # Determine provider type
            provider = getattr(spec, "provider", "")
            base_url = getattr(spec, "base_url", "")
            # Resolve key
            api_key = ""
            if isinstance(spec, ResolvedSpec):
                # For ResolvedSpec, resolve key via config
                from ramanujan.config import load_config, resolve_provider_key

                cfg = load_config()
                prov_cfg = cfg.provider_by_id(spec.provider)
                if prov_cfg is not None:
                    api_key = resolve_provider_key(prov_cfg) or ""
                else:
                    # Fallback to env
                    api_key = os.environ.get("OPENAI_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
            else:
                # VerifierSpec legacy: check env
                if provider == "anthropic":
                    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or ""
                elif provider in ("openai", "openai-codex"):
                    api_key = os.environ.get("OPENAI_API_KEY") or ""
                else:
                    # Generic openai-compatible VerifierSpec may have base_url in provider field?
                    # Try to get key from env based on provider
                    api_key = os.environ.get(f"{provider.upper()}_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
            if not api_key and isinstance(spec, ResolvedSpec):
                # Try to resolve again
                from ramanujan.config import load_config, resolve_provider_key

                cfg = load_config()
                prov_cfg = cfg.provider_by_id(spec.provider)
                if prov_cfg:
                    api_key = resolve_provider_key(prov_cfg) or ""

            if provider == "anthropic" and "anthropic.com" in base_url:
                text, input_tokens, output_tokens = _call_anthropic(spec, messages)  # type: ignore[arg-type]
            elif base_url and _is_openai_compatible_provider(provider, base_url):
                if not api_key:
                    raise RuntimeError(f"no key for provider {provider!r} (resolved base_url {base_url})")
                text, input_tokens, output_tokens = _call_openai_compatible(spec, messages, api_key)
            elif provider == "anthropic":
                text, input_tokens, output_tokens = _call_anthropic(spec, messages)  # type: ignore[arg-type]
            elif provider in ("openai", "openai-codex"):
                text, input_tokens, output_tokens = _call_openai(spec, messages)  # type: ignore[arg-type]
            else:
                # Generic fallback: try openai-compatible with base_url or default
                if base_url:
                    if not api_key:
                        # Try env
                        api_key = os.environ.get(f"{provider.upper()}_API_KEY", "") or ""
                    if not api_key:
                        raise RuntimeError(f"no key for provider {provider!r}")
                    text, input_tokens, output_tokens = _call_openai_compatible(spec, messages, api_key)
                else:
                    raise ValueError(f"unsupported provider: {provider}")

            latency_ms = int((time.monotonic() - start) * 1000)
            cost = _estimate_cost(spec.model_id, input_tokens, output_tokens)
            payload = {
                "model_id": spec.model_id,
                "provider": provider,
                "family": getattr(spec, "family", ""),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
                "latency_ms": latency_ms,
                "retries": attempt,
            }
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.write("llm_call", payload)
            return {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
                "latency_ms": latency_ms,
            }
        except Exception as e:
            last_err = e
            # Check if retryable (429/5xx already handled with delay, but generic retry)
            # Honor Retry-After if present in exception? Already did for openai-compatible
            # Backoff
            if attempt < retries - 1:
                # Exponential backoff, but respect Retry-After if we saw it
                time.sleep(0.5 * (2**attempt))
            continue
    raise RuntimeError(f"LLM call failed after {retries} retries: {last_err}") from last_err


def _call_anthropic(spec: VerifierSpec, messages: list[dict[str, str]]) -> tuple[str, int, int]:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or ""
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set (env only)")
    system = ""
    anth_messages: list[dict[str, str]] = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            anth_messages.append({"role": m["role"], "content": m["content"]})
    body = {
        "model": spec.model_id,
        "max_tokens": spec.max_output_tokens,
        "temperature": spec.temperature,
        "messages": anth_messages,
    }
    if system:
        body["system"] = system
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"Anthropic API error {e.code}: {err_body}") from e
    text_parts = []
    for block in resp_data.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    text = "\n".join(text_parts)
    usage = resp_data.get("usage", {})
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    return text, input_tokens, output_tokens


def _call_openai(spec: VerifierSpec, messages: list[dict[str, str]]) -> tuple[str, int, int]:
    api_key = os.environ.get("OPENAI_API_KEY") or ""
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set (env only)")
    body = {
        "model": spec.model_id,
        "temperature": spec.temperature,
        "max_tokens": spec.max_output_tokens,
        "messages": messages,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"OpenAI API error {e.code}: {err_body}") from e
    choice = resp_data.get("choices", [{}])[0]
    text = choice.get("message", {}).get("content", "") or choice.get("text", "")
    usage = resp_data.get("usage", {})
    input_tokens = int(usage.get("prompt_tokens", 0))
    output_tokens = int(usage.get("completion_tokens", 0))
    return text, input_tokens, output_tokens


# For CLI: list models via GET {base_url}/models
def list_models(provider_id: str, config_path: Path | None = None) -> list[str]:
    from ramanujan.config import load_config, resolve_provider_key

    cfg = load_config(config_path)
    prov = cfg.provider_by_id(provider_id)
    if prov is None:
        raise ValueError(f"provider {provider_id!r} not found")
    key = resolve_provider_key(prov)
    if not key:
        env_name = prov.api_key_env or f"{prov.id.upper()}_API_KEY"
        raise ValueError(f"no key for provider {prov.id!r} (env {env_name} or stored)")
    url = prov.base_url.rstrip("/") + "/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"list models failed {e.code} at {url}: {err_body}") from e
    # OpenAI-compatible returns {"data": [{"id": "model"}, ...]}
    models = []
    if isinstance(data, dict) and "data" in data:
        for item in data["data"]:
            if isinstance(item, dict) and "id" in item:
                models.append(str(item["id"]))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "id" in item:
                models.append(str(item["id"]))
    return sorted(models)


def test_provider(provider_id: str, config_path: Path | None = None) -> dict[str, Any]:
    """Test provider with trivial chat completion, return latency and masked key."""
    from ramanujan.config import load_config, mask_key, resolve_provider_key

    cfg = load_config(config_path)
    prov = cfg.provider_by_id(provider_id)
    if prov is None:
        raise ValueError(f"provider {provider_id!r} not found")
    key = resolve_provider_key(prov)
    if not key:
        env_name = prov.api_key_env or f"{prov.id.upper()}_API_KEY"
        raise ValueError(f"no key for provider {prov.id!r} (env {env_name} or stored)")
    # Use a resolved spec for test
    spec = ResolvedSpec(
        provider=prov.id,
        provider_name=prov.name,
        base_url=prov.base_url,
        model_id="test",
        family=prov.family,
        role="test",
    )
    # For test, we need a real model; try to list models and pick first if available
    # But we will just do a chat completion with a known test model if possible
    # Instead, try to call with the first available model from roles or fallback
    # If roles.encoder exists and uses this provider, use that model
    test_model = None
    if cfg.roles.encoder and cfg.roles.encoder.provider == provider_id:
        test_model = cfg.roles.encoder.model_id
    if not test_model:
        # Try to list models and pick first
        try:
            models = list_models(provider_id, config_path)
            if models:
                test_model = models[0]
        except Exception:
            pass
    if not test_model:
        test_model = "test-model"
    spec.model_id = test_model
    start = time.monotonic()
    try:
        # Use a simple message
        text, in_tok, out_tok = _call_openai_compatible(spec, [{"role": "user", "content": "Say ok"}], key)
        latency = int((time.monotonic() - start) * 1000)
        return {"ok": True, "latency_ms": latency, "model": test_model, "masked_key": mask_key(key), "response": text[:100]}
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        return {"ok": False, "latency_ms": latency, "masked_key": mask_key(key), "error": str(e)[:500]}
