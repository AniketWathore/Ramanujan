"""Worktree registry — ramanujan/worktree.py (v2 Phase 4).

Dispatcher-spawned worktrees are journal-first: every spawn and status change
writes via `journal.py` (single writer). No worktree process appends directly.
Per §4.5, per-worktree budgets/stalls are Phase 5; Phase 4 tracks only
running/completed/panel-verified and the spawn identity.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ramanujan.schemas import WorktreeSpawnedPayload, WorktreeStatusChangedPayload


class WorktreeStore:
    """In-memory worktree registry, journaled as produced."""

    def __init__(self, journal: Any | None = None) -> None:
        self._journal = journal
        self._records: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def spawn(self, provider: str, model_id: str, family: str, model_ref: str) -> dict[str, Any]:
        self._counter += 1
        wid = f"wt_{self._counter:03d}"
        payload = WorktreeSpawnedPayload(worktree_id=wid, provider=provider, model_id=model_id, family=family, model_ref=model_ref)
        rec = payload.model_dump()
        self._records[wid] = {"id": wid, **rec, "status": "running"}
        if self._journal is not None:
            with contextlib.suppress(Exception):
                self._journal.write("worktree_spawned", rec)
                self._journal.write(
                    "worktree_status_changed",
                    WorktreeStatusChangedPayload(worktree_id=wid, status="running").model_dump(),  # type: ignore[arg-type]
                )
        return dict(self._records[wid])

    def set_status(self, worktree_id: str, status: str, reason: str | None = None) -> dict[str, Any]:
        if worktree_id not in self._records:
            raise KeyError(f"no worktree {worktree_id}")
        self._records[worktree_id]["status"] = status
        if reason:
            self._records[worktree_id]["reason"] = reason
        if self._journal is not None:
            with contextlib.suppress(Exception):
                self._journal.write(
                    "worktree_status_changed",
                    WorktreeStatusChangedPayload(worktree_id=worktree_id, status=status, reason=reason).model_dump(),  # type: ignore[arg-type]
                )
        return dict(self._records[worktree_id])

    def get(self, worktree_id: str) -> dict[str, Any] | None:
        return self._records.get(worktree_id)

    def list(self) -> list[dict[str, Any]]:
        return list(self._records.values())

    @staticmethod
    def fold_worktrees(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Fold journal events to latest status per worktree_id."""
        state: dict[str, dict[str, Any]] = {}
        for ev in events:
            if ev.get("type") == "worktree_spawned":
                wid = ev["payload"].get("worktree_id")
                if wid:
                    state[wid] = dict(ev["payload"])
                    state[wid]["status"] = "running"
            elif ev.get("type") == "worktree_status_changed":
                wid = ev["payload"].get("worktree_id")
                if wid and wid in state:
                    state[wid]["status"] = ev["payload"].get("status", state[wid]["status"])
                    if ev["payload"].get("reason"):
                        state[wid]["reason"] = ev["payload"]["reason"]
        return state
