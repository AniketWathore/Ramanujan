"""Provider-family registry + preset deadlock guard — ramanujan/families.py (v2 Phase 0).

Maps full `provider/model` refs to independence families. Maintained MANUALLY
in `specs/family_registry.json` — never inferred from the provider string,
because vendor-relabeled endpoints (e.g. openrouter/gpt-5 vs
openai/gpt-5-2025-08-07) are the same underlying weights and must be treated
as the same family, or the Tier-2 panel's independence guarantee is trivially
gamed.

Deadlock rule (Build Brief §4.2): Tier 2 excludes the calling worktree's own
family, so a preset with fewer than 2 distinct families can never produce a
`panel-verified` stop. That is a WARNING, never a hard block — a user with one
API key still gets budget/stall-terminated value. Recommend 3+ families; 2 is
the bare floor, not a target.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "specs" / "family_registry.json"

#: Family assigned to refs absent from the registry. A single shared bucket
#: (conservative): unmapped refs cannot prove independence, so they never
#: inflate the distinct-family count toward the 2-family floor.
UNKNOWN_FAMILY = "family:unknown"

#: Verbatim user-facing warning for deadlocked presets. Must always offer
#: "proceed anyway" — never hard-block.
DEADLOCK_WARNING = "This preset can only reach budget/stall termination, never panel-verified. Proceed anyway?"


def load_registry(path: Path | str | None = None) -> dict[str, str]:
    """Load the manual ref → family map. Keys are full `provider/model` refs."""
    p = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"family registry must be a JSON object: {p}")
    for k, v in data.items():
        if not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip():
            raise ValueError(f"invalid family registry entry: {k!r}: {v!r}")
    return dict(data)


def family_of(model_ref: str, registry: dict[str, str]) -> str:
    """Return the family for a full `provider/model` ref; unknown refs → shared bucket."""
    return registry.get(model_ref.strip(), UNKNOWN_FAMILY)


def preset_families(models: list[str], registry: dict[str, str]) -> set[str]:
    """Distinct families covered by a preset list of full `provider/model` refs."""
    return {family_of(m, registry) for m in models}


@dataclass
class PresetCheck:
    """Result of validating one preset against the registry."""

    name: str
    models: list[str] = field(default_factory=list)
    families: set[str] = field(default_factory=set)
    ok: bool = False
    warning: str | None = None
    note: str | None = None


def validate_preset(name: str, models: list[str], registry: dict[str, str]) -> PresetCheck:
    """Validate a preset. <2 distinct families → deadlock warning (non-blocking).

    Exactly 2 families passes the floor but carries a note recommending 3+.
    """
    families = preset_families(models, registry)
    if len(families) < 2:
        return PresetCheck(
            name=name,
            models=list(models),
            families=families,
            ok=False,
            warning=(
                f"Preset {name!r} covers {len(families)} distinct family ({sorted(families) if families else 'none'}). " + DEADLOCK_WARNING
            ),
        )
    note = None
    if len(families) == 2:
        note = (
            f"Preset {name!r} covers exactly 2 distinct families {sorted(families)} — "
            "the bare deadlock-avoiding floor. 3+ families recommended for "
            "trustworthy panel-verified stops."
        )
    return PresetCheck(name=name, models=list(models), families=families, ok=True, note=note)
