"""Reusable human checkpoint — ramanujan/checkpoint.py (v2 Phase 1).

One abstraction for all five stages (Build Brief §1): the confirm/revise
CONTRACT is identical everywhere, only the content differs per stage
(spec / lit summary / worktree table / fact set / report).

- propose (agent) → confirm | revise(feedback) (HUMAN only).
- `revise` loops: feedback is recorded, revision bumps, the same checkpoint
  is re-presented until confirmed.
- Stop is a separate, always-available global action — NOT a checkpoint
  option, so it never appears here. Stopping destroys nothing: every
  proposed/resolved checkpoint is journaled as produced
  (`checkpoint_reached` / `checkpoint_resolved`), and state refolds from
  the journal via `fold_checkpoints`.
"""

from __future__ import annotations

import contextlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CHECKPOINT_OPTIONS: list[str] = ["confirm", "revise"]


class CheckpointRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    checkpoint_id: str = Field(pattern=r"^cp_\d+$")
    stage: str = Field(min_length=1)
    output_ref: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    options: list[str] = Field(default_factory=lambda: list(CHECKPOINT_OPTIONS))
    status: str = Field(default="pending", pattern=r"^(pending|confirmed)$")
    revision: int = Field(default=0, ge=0)
    feedback: list[str] = Field(default_factory=list)


class CheckpointStore:
    """In-memory checkpoints, journaled as produced (single writer stays journal.py)."""

    def __init__(self, journal: Any | None = None) -> None:
        self._journal = journal
        self._records: dict[str, CheckpointRecord] = {}
        self._counter = 0

    def propose(self, stage: str, output_ref: str, prompt: str) -> CheckpointRecord:
        self._counter += 1
        rec = CheckpointRecord(
            checkpoint_id=f"cp_{self._counter:03d}",
            stage=stage,
            output_ref=output_ref,
            prompt=prompt,
        )
        self._records[rec.checkpoint_id] = rec
        if self._journal is not None:
            with contextlib.suppress(Exception):
                self._journal.write(
                    "checkpoint_reached",
                    {
                        "checkpoint_id": rec.checkpoint_id,
                        "stage": stage,
                        "output_ref": output_ref,
                        "revision": rec.revision,
                    },
                )
        return rec

    def confirm(self, checkpoint_id: str) -> CheckpointRecord:
        rec = self._get_pending(checkpoint_id)
        rec.status = "confirmed"
        if self._journal is not None:
            with contextlib.suppress(Exception):
                self._journal.write(
                    "checkpoint_resolved",
                    {"checkpoint_id": checkpoint_id, "decision": "confirm", "revision": rec.revision},
                )
        return rec

    def revise(self, checkpoint_id: str, feedback: str) -> CheckpointRecord:
        """Record free-text feedback and re-present the SAME checkpoint pending."""
        rec = self._get_pending(checkpoint_id)
        rec.feedback.append(feedback)
        rec.revision += 1
        # status stays pending: loops until confirmed.
        if self._journal is not None:
            with contextlib.suppress(Exception):
                self._journal.write(
                    "checkpoint_resolved",
                    {
                        "checkpoint_id": checkpoint_id,
                        "decision": "revise",
                        "feedback": feedback,
                        "revision": rec.revision,
                    },
                )
                self._journal.write(
                    "checkpoint_reached",
                    {
                        "checkpoint_id": checkpoint_id,
                        "stage": rec.stage,
                        "output_ref": rec.output_ref,
                        "revision": rec.revision,
                    },
                )
        return rec

    def get(self, checkpoint_id: str) -> CheckpointRecord | None:
        return self._records.get(checkpoint_id)

    def pending(self) -> list[CheckpointRecord]:
        return [r for r in self._records.values() if r.status == "pending"]

    def _get_pending(self, checkpoint_id: str) -> CheckpointRecord:
        rec = self._records.get(checkpoint_id)
        if rec is None:
            raise KeyError(f"no checkpoint {checkpoint_id}")
        if rec.status != "pending":
            raise ValueError(f"checkpoint {checkpoint_id} already {rec.status}")
        return rec

    @staticmethod
    def fold_checkpoints(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Fold journal events to latest status per checkpoint_id."""
        state: dict[str, dict[str, Any]] = {}
        for ev in events:
            if ev.get("type") == "checkpoint_reached":
                cid = ev["payload"].get("checkpoint_id")
                if cid:
                    state[cid] = {
                        "status": "pending",
                        "revision": ev["payload"].get("revision", 0),
                        "stage": ev["payload"].get("stage"),
                    }
            elif ev.get("type") == "checkpoint_resolved":
                cid = ev["payload"].get("checkpoint_id")
                if cid and cid in state:
                    if ev["payload"].get("decision") == "confirm":
                        state[cid]["status"] = "confirmed"
                    state[cid]["revision"] = ev["payload"].get("revision", state[cid]["revision"])
        return state
