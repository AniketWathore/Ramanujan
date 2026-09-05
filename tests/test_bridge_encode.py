"""Bridge encode: offline mapping keyless-only + encoder_error status — tests/test_bridge_encode.py."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner


def _write_config(path: Path, *, with_key: bool) -> None:
    if with_key:
        path.write_text(
            "version = 1\n\n"
            "[[providers]]\n"
            'id = "nvidia"\n'
            'name = "NVIDIA"\n'
            'base_url = "https://integrate.api.nvidia.com/v1"\n'
            'api_key_env = "NVIDIA_API_KEY"\n'
            'family = "nvidia"\n\n'
            "[roles.encoder]\n"
            'provider = "nvidia"\n'
            'model_id = "nvidia/llama-3.1-nemotron-70b-instruct"\n',
            encoding="utf-8",
        )
    else:
        path.write_text("version = 1\n", encoding="utf-8")


def test_offline_mapping_used_when_keyless(tmp_path: Path, monkeypatch):
    from ramanujan.cli import main

    cfg = tmp_path / "config.toml"
    _write_config(cfg, with_key=False)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(cfg))
    monkeypatch.delenv("RAMANUJAN_MOCK_ENCODER", raising=False)
    journal = tmp_path / "journal.jsonl"
    runner = CliRunner()
    res = runner.invoke(
        main,
        ["encode", "--statement", "For every integer n >= 0, n^2 + n + 41 is prime.", "--journal", str(journal), "--json"],
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output.strip().splitlines()[-1])
    assert payload["status"] == "card"
    assert payload["provider"] == "offline"
    assert payload["card"]["conclusion"]["expr"] == "is_prime(n**2 + n + 41)"
    # Journal notes the offline source
    events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
    sources = [e["payload"].get("source") for e in events if e["type"] in ("encoding_attempted", "encoding_accepted")]
    assert "offline-mapping" in sources


def test_offline_mapping_skipped_when_key_resolves(tmp_path: Path, monkeypatch):
    """Full keyed runs MUST NEVER use the offline mapping."""
    from ramanujan.cli import main
    from ramanujan.encoder import EncodeResult

    cfg = tmp_path / "config.toml"
    _write_config(cfg, with_key=True)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(cfg))
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake-test-key-1234")
    monkeypatch.delenv("RAMANUJAN_MOCK_ENCODER", raising=False)

    marker_expr = "factorial(n) > 2**n"
    seen = {"called": False}

    def fake_encode(statement, spec, journal=None, caller=None, max_retries=3):
        seen["called"] = True
        # Prove we went through the live encoder path, not the mapping:
        # return a distinctive card the offline mapping would never emit.
        from ramanujan.schemas import ClaimCard

        card = ClaimCard.model_validate(
            {
                "card_id": "c_0001",
                "statement_informal": statement,
                "claim_type": ["inequality-estimate"],
                "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
                "hypotheses": [],
                "conclusion": {"expr": marker_expr, "sympy_parseable": True},
                "set_vars": [],
            }
        )
        return EncodeResult(card=card, error=None, raw="{}", attempts=1)

    import ramanujan.encoder as enc_mod

    monkeypatch.setattr(enc_mod, "encode_statement", fake_encode)
    journal = tmp_path / "journal.jsonl"
    runner = CliRunner()
    res = runner.invoke(
        main,
        ["encode", "--statement", "For every integer n >= 0, n^2 + n + 41 is prime.", "--journal", str(journal), "--json"],
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output.strip().splitlines()[-1])
    assert seen["called"] is True
    assert payload["status"] == "card"
    assert payload["provider"] == "nvidia"
    # Keyed path used the live encoder's card, NOT the offline prime card
    assert payload["card"]["conclusion"]["expr"] == marker_expr


def test_cli_encode_validation_failure_emits_encoder_error(tmp_path: Path, monkeypatch):
    from ramanujan.cli import main
    from ramanujan.encoder import EncodeResult

    cfg = tmp_path / "config.toml"
    _write_config(cfg, with_key=True)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(cfg))
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake-test-key-1234")
    monkeypatch.delenv("RAMANUJAN_MOCK_ENCODER", raising=False)

    def fake_fail(statement, spec, journal=None, caller=None, max_retries=3):
        return EncodeResult(card=None, error="ClaimCard validation failed: invalid claim_type 'prime'", raw="{}", attempts=3)

    import ramanujan.encoder as enc_mod

    monkeypatch.setattr(enc_mod, "encode_statement", fake_fail)
    journal = tmp_path / "journal.jsonl"
    runner = CliRunner()
    res = runner.invoke(main, ["encode", "--statement", "x", "--journal", str(journal), "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output.strip().splitlines()[-1])
    assert payload["status"] == "encoder_error"
    assert "prime" in payload["reason"]
    assert "NOT_ENCODABLE" not in payload["reason"]


def test_cli_encode_explicit_refusal_emits_not_encodable(tmp_path: Path, monkeypatch):
    from ramanujan.cli import main
    from ramanujan.encoder import EncodeResult

    cfg = tmp_path / "config.toml"
    _write_config(cfg, with_key=True)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(cfg))
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake-test-key-1234")
    monkeypatch.delenv("RAMANUJAN_MOCK_ENCODER", raising=False)

    def fake_refuse(statement, spec, journal=None, caller=None, max_retries=3):
        return EncodeResult(card=None, error="NOT_ENCODABLE: open-form sum", raw="{}", attempts=1)

    import ramanujan.encoder as enc_mod

    monkeypatch.setattr(enc_mod, "encode_statement", fake_refuse)
    journal = tmp_path / "journal.jsonl"
    runner = CliRunner()
    res = runner.invoke(main, ["encode", "--statement", "x", "--journal", str(journal), "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output.strip().splitlines()[-1])
    assert payload["status"] == "not_encodable"


def test_offline_journal_carries_no_key_material(tmp_path: Path, monkeypatch):
    from ramanujan.cli import main

    cfg = tmp_path / "config.toml"
    _write_config(cfg, with_key=False)
    monkeypatch.setenv("RAMANUJAN_CONFIG", str(cfg))
    monkeypatch.delenv("RAMANUJAN_MOCK_ENCODER", raising=False)
    journal = tmp_path / "journal.jsonl"
    runner = CliRunner()
    res = runner.invoke(
        main,
        ["encode", "--statement", "For every integer n >= 0, n^2 + n + 41 is prime.", "--journal", str(journal), "--json"],
    )
    assert res.exit_code == 0, res.output
    text = journal.read_text(encoding="utf-8")
    assert "nvapi-" not in text and "sk-ant-" not in text
