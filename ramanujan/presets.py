"""Preset store + deadlock guard — ramanujan/presets.py (v2 Phase 3).

Named presets are validated against `family_registry.json`; <2 distinct families
can never produce a panel-verified stop (Tier 2 excludes the caller's family).
Save is NEVER blocked — even a single-family preset warns explicitly and still
proceeds, per §4.2. Keys never appear in presets.json (refs only).

File: ~/.config/ramanujan/presets.json (0600 via atomic tempfile+replace).
Env override: RAMANUJAN_PRESETS (tests).
Structure: {"diverse-5": ["anthropic/claude-opus-5", ...], ...}
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
from pathlib import Path

from ramanujan.families import DEFAULT_REGISTRY_PATH, PresetCheck, load_registry, validate_preset

DEFAULT_PRESETS_PATH = Path.home() / ".config" / "ramanujan" / "presets.json"


def _presets_path() -> Path:
    env = os.environ.get("RAMANUJAN_PRESETS")
    if env:
        return Path(env).expanduser()
    return DEFAULT_PRESETS_PATH


def load_presets(path: Path | str | None = None) -> dict[str, list[str]]:
    p = Path(path) if path is not None else _presets_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"presets file invalid JSON at {p}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"presets must be a JSON object at {p}")
    out: dict[str, list[str]] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not k.strip():
            raise ValueError(f"invalid preset name: {k!r}")
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
            raise ValueError(f"preset {k!r} must be a list of non-empty strings")
        out[k.strip()] = [x.strip() for x in v]  # type: ignore[arg-type]
    return out


def save_presets(presets: dict[str, list[str]], path: Path | str | None = None) -> None:
    p = Path(path) if path is not None else _presets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(presets, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, p)
        with contextlib.suppress(Exception):
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def get_preset(name: str, path: Path | str | None = None) -> list[str] | None:
    return load_presets(path).get(name)


def check_preset(name: str, models: list[str], registry_path: Path | str | None = None) -> PresetCheck:
    reg = load_registry(registry_path or DEFAULT_REGISTRY_PATH)
    return validate_preset(name, models, reg)


def validate_all_presets(presets: dict[str, list[str]], registry_path: Path | str | None = None) -> dict[str, PresetCheck]:
    reg = load_registry(registry_path or DEFAULT_REGISTRY_PATH)
    return {n: validate_preset(n, m, reg) for n, m in presets.items()}


def set_preset(
    name: str,
    models: list[str],
    path: Path | str | None = None,
    registry_path: Path | str | None = None,
) -> PresetCheck:
    """Validate (warning on deadlock) and persist. Always saves; never hard-blocks."""
    check = check_preset(name, models, registry_path)
    presets = load_presets(path)
    presets[name] = list(models)
    save_presets(presets, path)
    return check


def delete_preset(name: str, path: Path | str | None = None) -> bool:
    presets = load_presets(path)
    if name not in presets:
        return False
    del presets[name]
    save_presets(presets, path)
    return True
