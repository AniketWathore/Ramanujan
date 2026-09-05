"""Micro question queue — ramanujan/questions.py (v2 Phase 6, pattern B).

Non-blocking per-worktree questions during Stage 3 only. Orchestrator-level
questions use nullable worktree_id via the SAME pattern (no third pattern).
If unanswered past timeout_sec, the system applies timeout_default, logs the
assumption, and continues. Every default must be surfaced in Checkpoint C.

All writes go through the single JournalWriter; no worktree appends directly.
A derived view `shared/questions.jsonl` is maintained for TS rendering, but
the journal is the source of truth (fold to latest per question_id).
"""

from __future__ import annotations

import contextlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ramanujan.schemas import QuestionAnsweredOrDefaultedPayload, QuestionPostedPayload


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class QuestionStore:
    """Non-blocking question queue (Stage 3 only)."""

    def __init__(
        self,
        journal: Any,
        session_dir: Path | str | None = None,
        default_timeout_sec: float = 300.0,
    ) -> None:
        self.journal = journal
        self.session_dir = Path(session_dir) if session_dir is not None else Path(f"session-{journal.run_id}")
        self.default_timeout_sec = float(default_timeout_sec)
        self._counter = 0
        # Rehydrate counter from existing journal events
        self._rehydrate()

    def _rehydrate(self) -> None:
        try:
            from ramanujan.journal import replay
        except Exception:
            return
        try:
            evs = replay(self.journal.path)
        except Exception:
            return
        mx = 0
        for ev in evs:
            if ev["type"] in ("question_posted", "question_answered_or_defaulted"):
                qid = ev["payload"].get("question_id", "")
                if qid.startswith("q_"):
                    with contextlib.suppress(Exception):
                        mx = max(mx, int(qid.split("_")[1]))
        self._counter = mx

    def post_question(
        self,
        question: str,
        timeout_default: str,
        *,
        worktree_id: str | None = None,
        agent_label: str | None = None,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        self._counter += 1
        qid = f"q_{self._counter:03d}"
        ts = _now_iso()
        sec = float(timeout_sec) if timeout_sec is not None else self.default_timeout_sec
        label = agent_label or (f"{worktree_id} ({worktree_id})" if worktree_id else "orchestrator")
        payload = QuestionPostedPayload(
            question_id=qid,
            worktree_id=worktree_id,
            agent_label=label,
            question=question,
            timeout_default=timeout_default,
            posted_at=ts,
            timeout_sec=sec,
        )
        rec = self.journal.write("question_posted", payload.model_dump())  # type: ignore[arg-type]
        # Mirror to file for TS (derived view, not source of truth)
        with contextlib.suppress(Exception):
            self._append_shared(payload.model_dump())
        return rec["payload"]

    def answer_question(self, question_id: str, answer: str, answered_by: str | None = None) -> dict[str, Any]:
        payload = QuestionAnsweredOrDefaultedPayload(question_id=question_id, answer=answer, status="answered", answered_by=answered_by)
        rec = self.journal.write("question_answered_or_defaulted", payload.model_dump())  # type: ignore[arg-type]
        with contextlib.suppress(Exception):
            self._append_shared(payload.model_dump())
        return rec["payload"]

    def check_timeouts(self, now: float | None = None) -> list[dict[str, Any]]:
        """Apply timeout defaults for expired open questions; return defaulted ids."""
        from ramanujan.journal import replay

        now = now if now is not None else time.time()
        evs = replay(self.journal.path) if self.journal.path.exists() else []
        posted: dict[str, dict[str, Any]] = {}
        answered: set[str] = set()
        answers: dict[str, dict[str, Any]] = {}
        for ev in evs:
            if ev["type"] == "question_posted":
                posted[ev["payload"]["question_id"]] = ev["payload"]
            elif ev["type"] == "question_answered_or_defaulted":
                answered.add(ev["payload"]["question_id"])
                answers[ev["payload"]["question_id"]] = ev["payload"]
        defaulted: list[dict[str, Any]] = []
        for qid, p in posted.items():
            if qid in answered:
                continue
            # posted_at iso -> epoch
            try:
                posted_epoch = datetime.fromisoformat(p["posted_at"].replace("Z", "+00:00")).timestamp()
            except Exception:
                posted_epoch = now
            if now - posted_epoch > float(p.get("timeout_sec", self.default_timeout_sec)):
                payload = QuestionAnsweredOrDefaultedPayload(
                    question_id=qid,
                    answer=p["timeout_default"],
                    status="defaulted",
                    answered_by="system-timeout",
                )
                with contextlib.suppress(Exception):
                    self.journal.write("question_answered_or_defaulted", payload.model_dump())  # type: ignore[arg-type]
                    self._append_shared(payload.model_dump())
                defaulted.append(payload.model_dump())
        return defaulted

    def _append_shared(self, payload: dict[str, Any]) -> None:
        out = self.session_dir / "shared" / "questions.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":")) + "\n")

    @staticmethod
    def fold_questions(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Fold to latest status per question_id."""
        state: dict[str, dict[str, Any]] = {}
        for ev in events:
            if ev["type"] == "question_posted":
                qid = ev["payload"]["question_id"]
                state[qid] = {"status": "open", **ev["payload"], "answer": None}
            elif ev["type"] == "question_answered_or_defaulted":
                qid = ev["payload"]["question_id"]
                if qid in state:
                    state[qid]["status"] = ev["payload"]["status"]
                    state[qid]["answer"] = ev["payload"]["answer"]
                    state[qid]["answered_by"] = ev["payload"].get("answered_by")
                else:
                    state[qid] = {**ev["payload"], "status": ev["payload"]["status"]}
        return state

    @staticmethod
    def timeout_defaults(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return every question that was defaulted (for Checkpoint C)."""
        out: list[dict[str, Any]] = []
        for ev in events:
            if ev["type"] == "question_answered_or_defaulted" and ev["payload"].get("status") == "defaulted":
                out.append(ev["payload"])
        return out
