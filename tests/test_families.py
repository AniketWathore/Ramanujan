"""Tests for ramanujan/families.py — Phase 0 deadlock guard."""

from ramanujan.families import (
    DEADLOCK_WARNING,
    UNKNOWN_FAMILY,
    family_of,
    load_registry,
    preset_families,
    validate_preset,
)


def _example_registry() -> dict[str, str]:
    return load_registry()  # repo specs/family_registry.json


def test_registry_loads_and_maps_relabels_to_same_family():
    reg = _example_registry()
    # The gaming guard: vendor-relabeled endpoints share one family.
    assert reg["openai/gpt-5-2025-08-07"] == reg["openrouter/gpt-5"] == "family:openai-gpt5"
    assert reg["anthropic/claude-opus-5"] == "family:anthropic-opus"
    assert reg["local/self-hosted-oss-70b"] == "family:local-oss"


def test_single_family_preset_warns_but_does_not_block():
    reg = _example_registry()
    check = validate_preset("single", ["openai/gpt-5-2025-08-07", "openrouter/gpt-5"], reg)
    assert check.ok is False
    assert check.warning is not None
    assert "never panel-verified" in check.warning
    assert "Proceed anyway?" in check.warning
    # Warning carries the exact verbatim deadlock sentence.
    assert DEADLOCK_WARNING in check.warning


def test_one_model_preset_warns():
    reg = _example_registry()
    check = validate_preset("solo", ["google/gemini-3-pro"], reg)
    assert check.ok is False
    assert check.warning is not None and DEADLOCK_WARNING in check.warning


def test_empty_preset_warns():
    reg = _example_registry()
    check = validate_preset("empty", [], reg)
    assert check.ok is False
    assert check.warning is not None and DEADLOCK_WARNING in check.warning


def test_two_family_preset_passes_with_recommendation_note():
    reg = _example_registry()
    check = validate_preset("two", ["google/gemini-3-pro", "openai/gpt-5-2025-08-07"], reg)
    assert check.ok is True
    assert check.warning is None
    assert check.note is not None and "3+" in check.note


def test_diverse_preset_passes_cleanly():
    reg = _example_registry()
    models = [
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "openai/gpt-5-2025-08-07",
        "google/gemini-3-pro",
        "local/self-hosted-oss-70b",
    ]
    check = validate_preset("diverse-5", models, reg)
    assert check.ok is True
    assert check.warning is None
    assert check.note is None  # 4 families: no recommendation needed
    assert len(check.families) == 5  # only the openai pair shares one family
    assert preset_families(models, reg) == check.families


def test_unknown_refs_share_conservative_bucket():
    reg = _example_registry()
    assert family_of("some-new-vendor/some-new-model", reg) == UNKNOWN_FAMILY
    # Two unknown refs cannot prove independence → still deadlocked.
    check = validate_preset("unknowns", ["aaa/m1", "bbb/m2"], reg)
    assert check.ok is False
    assert check.warning is not None and DEADLOCK_WARNING in check.warning
    # One unknown + one known family is enough to pass the floor.
    check2 = validate_preset("mixed", ["aaa/m1", "google/gemini-3-pro"], reg)
    assert check2.ok is True
