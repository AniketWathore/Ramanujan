"""Event envelope + append-only writer + replay — ramanujan/journal.py

Single write path for journal.jsonl. No other module may touch the file.
Borrowed atomic idiom from iteris project.py:write_json / append_jsonl.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ramanujan.schemas import JournalEvent


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


DEFAULT_JOURNAL = Path("journal.jsonl")


class JournalWriter:
    """Append-only JSONL writer. Single write path.

    Usage:
        writer = JournalWriter(Path("journal.jsonl"), run_id="run_abc")
        writer.write("run_started", {"statement": "..."})
        writer.write("claim_refuted", {"counterexample": {...}})
    """

    def __init__(self, path: Path | str = DEFAULT_JOURNAL, *, run_id: str | None = None) -> None:
        self.path = Path(path)
        self.run_id = run_id or _new_run_id()

    def write(self, event_type: str, payload: dict[str, Any] | None = None, *, ts: str | None = None) -> dict[str, Any]:
        """Validate and append one journal line. Returns the written dict.

        Raises pydantic ValidationError if the event is malformed — never writes it.
        """
        ts = ts or _now_iso()
        payload = payload or {}
        event = JournalEvent(ts=ts, run_id=self.run_id, type=event_type, payload=payload)
        # Validate payload shapes for a few typed events (ground_truth_recorded etc.)
        _validate_typed_payload(event)
        line = json.dumps(event.model_dump(), ensure_ascii=False, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Append is atomic for single line on POSIX; we also ensure file exists.
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return event.model_dump()

    def write_raw(self, event: JournalEvent) -> dict[str, Any]:
        """Write a pre-built JournalEvent (validated)."""
        _validate_typed_payload(event)
        line = json.dumps(event.model_dump(), ensure_ascii=False, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return event.model_dump()


def _validate_typed_payload(event: JournalEvent) -> None:
    """Extra per-type payload validation (strict)."""
    if event.type == "ground_truth_recorded":
        from ramanujan.schemas import GroundTruthPayload

        # payload must contain target/resolution/source
        GroundTruthPayload.model_validate(event.payload)
    elif event.type == "llm_call":
        # Must contain model_id at minimum
        if "model_id" not in event.payload:
            raise ValueError("llm_call payload missing model_id")
    elif event.type == "panel_position":
        from ramanujan.schemas import PanelPositionPayload

        PanelPositionPayload.model_validate(event.payload)
    elif event.type == "panel_advisory":
        from ramanujan.schemas import PanelAdvisoryPayload

        PanelAdvisoryPayload.model_validate(event.payload)
    elif event.type == "worktree_spawned":
        from ramanujan.schemas import WorktreeSpawnedPayload

        WorktreeSpawnedPayload.model_validate(event.payload)
    elif event.type == "worktree_status_changed":
        from ramanujan.schemas import WorktreeStatusChangedPayload

        WorktreeStatusChangedPayload.model_validate(event.payload)
    elif event.type == "claim_posted":
        from ramanujan.schemas import ClaimPostedPayload

        ClaimPostedPayload.model_validate(event.payload)
    elif event.type == "claim_verification_routed":
        from ramanujan.schemas import ClaimVerificationRoutedPayload

        ClaimVerificationRoutedPayload.model_validate(event.payload)
    elif event.type == "stall_detected":
        from ramanujan.schemas import StallDetectedPayload

        StallDetectedPayload.model_validate(event.payload)
    elif event.type == "panel_verdict_issued":
        from ramanujan.schemas import PanelVerdictIssuedPayload

        PanelVerdictIssuedPayload.model_validate(event.payload)
    elif event.type == "question_posted":
        from ramanujan.schemas import QuestionPostedPayload

        QuestionPostedPayload.model_validate(event.payload)
    elif event.type == "question_answered_or_defaulted":
        from ramanujan.schemas import QuestionAnsweredOrDefaultedPayload

        QuestionAnsweredOrDefaultedPayload.model_validate(event.payload)
    elif event.type == "consolidation_completed":
        from ramanujan.schemas import ConsolidationCompletedPayload

        ConsolidationCompletedPayload.model_validate(event.payload)
    # Other types are free-form for this slice (still envelope-validated)


def replay(journal_path: Path | str = DEFAULT_JOURNAL) -> list[dict[str, Any]]:
    """Read and validate every line; return list of event dicts.

    Raises on first malformed line (fail loud). Idempotent: call twice same result.
    """
    path = Path(journal_path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"journal line {lineno}: invalid JSON: {e}") from e
        # Validate envelope
        ev = JournalEvent.model_validate(data)
        _validate_typed_payload(ev)
        events.append(ev.model_dump())
    return events


def replay_iter(journal_path: Path | str = DEFAULT_JOURNAL) -> Iterator[dict[str, Any]]:
    """Streaming replay."""
    yield from replay(journal_path)


def rebuild_state(journal_path: Path | str = DEFAULT_JOURNAL) -> dict[str, Any]:
    """Derived view: counts per type + last run_id + ground truths.

    Pure function of replay; used in tests to verify idempotence.
    """
    events = replay(journal_path)
    counts: dict[str, int] = {}
    for ev in events:
        counts[ev["type"]] = counts.get(ev["type"], 0) + 1
    return {
        "total": len(events),
        "counts": counts,
        "run_ids": sorted({e["run_id"] for e in events}),
        "events": events,
    }


# Legacy helper: atomic write_json (borrowed idiom, for derived views if needed)
def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
