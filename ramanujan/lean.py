"""Lean verifier for computational worktrees — ramanujan/lean.py.

Every worktree gets a Lean verifier. When a claim completes (post) or a
worktree completes (`completed` / `panel-verified`), the claim's Lean
source (if attached) is checked with the Lean 4 toolchain and the result
is stored per-worktree on disk + journaled as `lean_verified`.

Honest-by-design: Lean is NOT installed on most machines. Missing binary
or missing Lean source is `skipped` (never a verdict). Lean NEVER writes
`claim_refuted` / `claim_survived` and never changes Tier0/Tier1 — it is
an additional formal check recorded alongside them.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LeanResult(BaseModel):
    """Outcome of one Lean check for one claim in one worktree."""

    model_config = ConfigDict(extra="forbid", strict=True)

    claim_id: str = Field(pattern=r"^c_\d+$")
    worktree_id: str = Field(pattern=r"^wt_\d+$")
    status: str = Field(description="verified | failed | skipped | error")
    detail: str = Field(default="", description="human-readable reason, truncated")
    lean_version: str = Field(min_length=1)
    mathlib_version: str = Field(min_length=1)
    elapsed_sec: float = Field(default=0.0, ge=0.0)

    @classmethod
    def check_status(cls, v: str) -> str:
        allowed = {"verified", "failed", "skipped", "error"}
        if v not in allowed:
            raise ValueError(f"invalid lean status: {v!r}")
        return v


def lean_binary() -> str | None:
    """Resolve the Lean binary: LEAN_BIN env > PATH. None when not installed."""
    env_bin = os.environ.get("LEAN_BIN")
    if env_bin:
        p = Path(env_bin)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        return env_bin
    return shutil.which("lean")


def get_lean_versions() -> dict[str, str]:
    """Best-effort Lean/Mathlib versions (never raises)."""
    lean = os.environ.get("LEAN_VERSION") or os.environ.get("LEAN_TOOLCHAIN") or ""
    if not lean:
        binary = lean_binary()
        if binary:
            try:
                out = subprocess.check_output([binary, "--version"], text=True, timeout=5)
                lean = out.strip().splitlines()[0][:120]
            except Exception:
                lean = "lean-unknown"
        else:
            lean = "lean-unknown"
    mathlib = os.environ.get("MATHLIB_VERSION") or "mathlib-unknown"
    return {"lean": lean.strip() or "lean-unknown", "mathlib": mathlib.strip()}


def worktree_lean_dir(session_dir: Path | str, worktree_id: str) -> Path:
    """Per-worktree Lean result dir: <session>/worktrees/<wt>/lean/."""
    d = Path(session_dir) / "worktrees" / worktree_id / "lean"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_lean_code(session_dir: Path, claim_id: str) -> str | None:
    """Look for attached Lean source: lean/<claim>.json or lean/<fact>.json.

    Formal artifacts are JSON files with a `content` (or `lean_code`) string
    holding Lean 4 source. Returns None when nothing is attached.
    """
    formal_dir = Path(session_dir) / "lean"
    if not formal_dir.exists():
        return None
    fact_id = claim_id.replace("c_", "f_")
    for pat in (f"{claim_id}.json", f"{fact_id}.json"):
        p = formal_dir / pat
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            for key in ("content", "lean_code", "lean_source"):
                code = data.get(key)
                if isinstance(code, str) and code.strip():
                    return code
    return None


def verify_claim(
    *,
    card: Any,
    worktree_id: str,
    claim_id: str,
    session_dir: Path | str = ".",
    journal: Any | None = None,
    timeout_sec: float = 60.0,
    lean_code: str | None = None,
) -> LeanResult:
    """Run the Lean verifier for one claim; always stores + journals (never raises)."""
    t0 = time.monotonic()
    session_path = Path(session_dir)
    versions = get_lean_versions()

    def _finish(status: str, detail: str, log: str = "") -> LeanResult:
        elapsed = max(0.0, time.monotonic() - t0)
        res = LeanResult(
            claim_id=claim_id,
            worktree_id=worktree_id,
            status=LeanResult.check_status(status),
            detail=(detail[:500] + (f" | {log[:1500]}" if log else ""))[:2000],
            lean_version=versions["lean"],
            mathlib_version=versions["mathlib"],
            elapsed_sec=elapsed,
        )
        with contextlib.suppress(Exception):
            out_dir = worktree_lean_dir(session_path, worktree_id)
            payload = res.model_dump()
            payload["conclusion"] = getattr(getattr(card, "conclusion", None), "expr", "")
            from ramanujan.journal import write_json_atomic

            write_json_atomic(out_dir / f"{claim_id}.json", payload)
        if journal is not None:
            with contextlib.suppress(Exception):
                journal.write(
                    "lean_verified",
                    {
                        "claim_id": claim_id,
                        "worktree_id": worktree_id,
                        "status": res.status,
                        "detail": res.detail[:500],
                        "lean_version": res.lean_version,
                        "mathlib_version": res.mathlib_version,
                        "elapsed_sec": res.elapsed_sec,
                    },
                )
        return res

    binary = lean_binary()
    if not binary:
        return _finish("skipped", "lean binary not found (LEAN_BIN or PATH); install Lean 4 + Mathlib to enable formal verification")
    code = lean_code
    if code is None:
        with contextlib.suppress(Exception):
            code = _find_lean_code(session_path, claim_id)
    if not code or not code.strip():
        return _finish("skipped", "no Lean source attached to claim; add lean/<claim_id>.json with a `content` field to enable")

    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=f"{claim_id}_", suffix=".lean")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(code)
        proc = subprocess.run(
            [binary, tmp_path],
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_sec)),
        )
        log = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
        if proc.returncode == 0:
            return _finish("verified", "lean elaborated with exit 0", log)
        return _finish("failed", f"lean exited with code {proc.returncode}", log)
    except subprocess.TimeoutExpired:
        return _finish("error", f"lean timed out after {timeout_sec}s")
    except Exception as e:
        return _finish("error", f"lean run failed: {e}"[:500])
    finally:
        if tmp_path:
            with contextlib.suppress(Exception):
                os.unlink(tmp_path)


def verify_worktree(
    *,
    worktree_id: str,
    session_dir: Path | str,
    journal: Any | None = None,
    board: dict[str, Any] | None = None,
    timeout_sec: float = 60.0,
) -> list[LeanResult]:
    """Verify every board claim belonging to a worktree (completion hook). Never raises."""
    from ramanujan.claims import fold_claims
    from ramanujan.schemas import ClaimCard

    session_path = Path(session_dir)
    results: list[LeanResult] = []
    try:
        if board is None:
            if journal is not None and hasattr(journal, "path") and Path(journal.path).exists():
                from ramanujan.journal import replay

                board = fold_claims(replay(Path(journal.path)))
            else:
                return results
        for cid, payload in board.items():
            if payload.get("worktree_id") != worktree_id:
                continue
            card_dict = payload.get("card")
            if not card_dict:
                continue
            try:
                card = ClaimCard.model_validate(card_dict)
            except Exception:
                continue
            with contextlib.suppress(Exception):
                results.append(
                    verify_claim(
                        card=card,
                        worktree_id=worktree_id,
                        claim_id=cid,
                        session_dir=session_path,
                        journal=journal,
                        timeout_sec=timeout_sec,
                    )
                )
    except Exception:
        pass
    return results
