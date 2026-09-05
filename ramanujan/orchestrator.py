"""Orchestrator — ramanujan/orchestrator.py (v2 Phase 5, N>1).

Monitor process (not an LLM): spawns worktrees, tracks running/stalled/etc,
enforces per-worktree budgets (time/step/cost via WorktreeBudget), detects
stalls, manages progress reports + per-worktree local journals + compaction,
and flags cross-worktree contradictions without NL arguing.

All writes go through the single JournalWriter; no worktree appends directly.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

from ramanujan.budget import BudgetExceeded, WorktreeBudget
from ramanujan.checkpoint import CheckpointStore
from ramanujan.claims import fold_claims, post_claim, route_verification
from ramanujan.journal import JournalWriter, replay, write_json_atomic
from ramanujan.questions import QuestionStore
from ramanujan.schemas import ClaimCard
from ramanujan.tier1 import lint_claim
from ramanujan.worktree import WorktreeStore


def _are_contradictory(card_a: ClaimCard, card_b: ClaimCard) -> bool:
    """Deterministic syntactic contradiction check (no LLM).

    Two claims contradict if their conclusions are syntactic negations:
    - `not (X)` vs `X`
    - `a > b` vs `a <= b`, `a >= b` vs `a < b`, `a == b` vs `a != b`
    """
    e1 = card_a.conclusion.expr.strip()
    e2 = card_b.conclusion.expr.strip()
    # not-wrapper case
    if e1.startswith("not ") or e1.startswith("not(") or e2.startswith("not ") or e2.startswith("not("):
        # Normalize: `not (X)` / `not X`
        def unwrap(e: str) -> str:
            t = e.strip()
            if t.startswith("not"):
                t = t[3:].strip()
                if t.startswith("(") and t.endswith(")"):
                    t = t[1:-1].strip()
            return t

        if unwrap(e1) == unwrap(e2) and (e1.strip().startswith("not") != e2.strip().startswith("not")):
            return True
    # Inequality-operator negation
    import re

    m1 = re.match(r"(.+?)\s*(>=|<=|==|!=|>|<)\s*(.+)", e1)
    m2 = re.match(r"(.+?)\s*(>=|<=|==|!=|>|<)\s*(.+)", e2)
    if m1 and m2:
        l1, op1, r1 = m1.group(1).strip(), m1.group(2), m1.group(3).strip()
        l2, op2, r2 = m2.group(1).strip(), m2.group(2), m2.group(3).strip()
        if l1 == l2 and r1 == r2 and {op1, op2} in ({">", "<="}, {"<", ">="}, {"==", "!="}):
            return True
        if l1 == r2 and r1 == l2 and {op1, op2} in ({">", "<="}, {"<", ">="}, {"==", "!="}):  # commutative swap
            return True
    # Exact opposite strings (fallback)
    return False


class Orchestrator:
    """N>1 orchestrator owning the session directory and all worktrees."""

    # Statuses per §4.5
    STATUSES = {
        "running",
        "stalled",
        "waiting_on_user",
        "stopped_error",
        "panel-verified",
        "completed",
        "stopped_budget",
        "stopped_stalled",
    }

    def __init__(
        self,
        journal: JournalWriter,
        session_dir: Path | str | None = None,
        stall_threshold_sec: float = 300.0,
        default_budgets: dict[str, Any] | None = None,
        question_timeout_sec: float = 300.0,
    ) -> None:
        self.journal = journal
        self.session_dir = Path(session_dir) if session_dir is not None else Path(f"session-{journal.run_id}")
        self.worktrees = WorktreeStore(journal)
        self._claim_counter = 0
        self.stall_threshold_sec = float(stall_threshold_sec)
        self.default_budgets = default_budgets or {}
        self._budgets: dict[str, WorktreeBudget] = {}
        self._last_activity: dict[str, float] = {}
        self._progress_cycle: dict[str, int] = {}
        self.questions = QuestionStore(journal, self.session_dir, default_timeout_sec=question_timeout_sec)
        self.checkpoints = CheckpointStore(journal)
        # Replay existing state if journal already has events (CLI multi-invoke case)
        self._rehydrate()

    def _rehydrate(self) -> None:
        try:
            evs = replay(self.journal.path)
        except Exception:
            return
        for ev in evs:
            if ev["type"] == "worktree_spawned":
                p = ev["payload"]
                wid = p["worktree_id"]
                self.worktrees._records[wid] = {"id": wid, **p, "status": "running"}  # type: ignore[attr-defined]
                with contextlib.suppress(Exception):
                    self.worktrees._counter = max(self.worktrees._counter, int(wid.split("_")[1]))  # type: ignore[attr-defined]
                self._last_activity.setdefault(wid, time.monotonic())
                self._budgets.setdefault(wid, WorktreeBudget(**self.default_budgets))
                self._progress_cycle.setdefault(wid, 0)
        for wid, rec in WorktreeStore.fold_worktrees(evs).items():
            if wid in self.worktrees._records:
                self.worktrees._records[wid]["status"] = rec["status"]  # type: ignore[attr-defined]
                self._last_activity[wid] = time.monotonic()
        board = fold_claims(evs)
        if board:
            with contextlib.suppress(Exception):
                self._claim_counter = max(int(cid.split("_")[1]) for cid in board)
        # Rehydrate questions/checkpoints counters
        with contextlib.suppress(Exception):
            self.questions._rehydrate()  # type: ignore[attr-defined]
        with contextlib.suppress(Exception):
            # checkpoint counter is private; scan for max cp id
            mx = 0
            for e in evs:
                if e["type"] == "checkpoint_reached":
                    cid = e["payload"].get("checkpoint_id", "")
                    if cid.startswith("cp_"):
                        with contextlib.suppress(Exception):
                            mx = max(mx, int(cid.split("_")[1]))
            self.checkpoints._counter = mx  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ spawn

    def spawn_worktree(self, provider: str, model_id: str, family: str, model_ref: str) -> dict[str, Any]:
        rec = self.worktrees.spawn(provider=provider, model_id=model_id, family=family, model_ref=model_ref)
        wid = rec["id"]
        self._budgets[wid] = WorktreeBudget(**self.default_budgets)
        self._last_activity[wid] = time.monotonic()
        self._progress_cycle[wid] = 0
        return rec

    def set_status(self, worktree_id: str, status: str, reason: str | None = None) -> dict[str, Any]:
        rec = self.worktrees.set_status(worktree_id, status, reason)
        self._last_activity[worktree_id] = time.monotonic()
        return rec

    # ------------------------------------------------------------------ claim (Tier0+Tier1 inline)

    def post_and_check_claim(
        self,
        worktree_id: str,
        card: ClaimCard,
        *,
        papers_index: dict[str, Any] | None = None,
        budget_usd: float | None = None,
        budget_sec: float | None = None,
    ) -> dict[str, Any]:
        """Post claim, enforce per-worktree budget, run Tier0+Tier1, route tier0."""
        if worktree_id not in {r["id"] for r in self.worktrees.list()}:
            raise KeyError(f"unknown worktree {worktree_id}")
        # Per-worktree budget pre-check
        wb = self._budgets.get(worktree_id)
        if wb is not None:
            # Override for this call if provided (not persistent)
            if budget_usd is not None:
                wb.budget_usd = budget_usd
            if budget_sec is not None:
                wb.budget_sec = budget_sec
            try:
                wb.check()
            except BudgetExceeded as e:
                self.set_status(worktree_id, "stopped_budget", reason=f"budget {e.kind} exceeded")
                raise
        self._claim_counter += 1
        claim_id = f"c_{self._claim_counter:03d}"
        card.card_id = claim_id  # type: ignore[assignment]

        # All writes via single journal writer
        from ramanujan.claims import fold_claims as _fold

        board_snapshot = _fold(replay(self.journal.path)) if self.journal.path.exists() else {}

        post_claim(self.journal, claim_id=claim_id, worktree_id=worktree_id, card=card)

        # Tier0 deterministic
        from ramanujan.killcheck.runner import killcheck_card

        kill_result = killcheck_card(card, journal=self.journal, budget_usd=budget_usd, budget_sec=budget_sec)

        route_verification(self.journal, claim_id=claim_id, verification_path="tier0", reason="tier0 available")

        # Tier1 lint
        tier1 = lint_claim(card, claim_id, papers_index=papers_index, folded_claims=board_snapshot)

        # Per-worktree accounting post-check
        if wb is not None:
            try:
                wb.add_step(1)
                # Cost is negligible for Tier0; use 0
                wb.add_cost(0.0)
            except BudgetExceeded as e:
                self.set_status(worktree_id, "stopped_budget", reason=f"budget {e.kind} exceeded after claim {claim_id}")

        self._last_activity[worktree_id] = time.monotonic()
        self._progress_cycle[worktree_id] = self._progress_cycle.get(worktree_id, 0) + 1
        return {
            "claim_id": claim_id,
            "worktree_id": worktree_id,
            "kill_result": kill_result,
            "tier1": tier1.model_dump(),
            "verification_path": "tier0",
        }

    # ------------------------------------------------------------------ progress / stall / compaction

    def record_progress(self, worktree_id: str, cycle: int | None = None, extra: dict[str, Any] | None = None) -> Path:
        """Write shared/progress_reports/<worktree>_<cycle>.json (Phase 5 layout)."""
        if worktree_id not in self._last_activity:
            raise KeyError(f"no worktree {worktree_id}")
        cyc = cycle if cycle is not None else self._progress_cycle.get(worktree_id, 0)
        out_dir = self.session_dir / "shared" / "progress_reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "worktree_id": worktree_id,
            "cycle": cyc,
            "ts": time.time(),
            "status": next((r["status"] for r in self.worktrees.list() if r["id"] == worktree_id), "running"),
        }
        if extra:
            payload.update(extra)
        path = out_dir / f"{worktree_id}_{cyc:04d}.json"
        write_json_atomic(path, payload)
        self._last_activity[worktree_id] = time.monotonic()
        return path

    def check_stalls(self) -> list[str]:
        """Detect stalled worktrees; emit stall_detected and flip to stalled."""
        now = time.monotonic()
        stalled: list[str] = []
        for wid, last in list(self._last_activity.items()):
            # Only running worktrees can stall
            rec = next((r for r in self.worktrees.list() if r["id"] == wid), None)
            if rec is None or rec.get("status") != "running":
                continue
            if now - last > self.stall_threshold_sec:
                stalled.append(wid)
                # Emit stall_detected
                with contextlib.suppress(Exception):
                    from datetime import UTC, datetime

                    self.journal.write(
                        "stall_detected",
                        {
                            "worktree_id": wid,
                            "stalled_cycles": 1,
                            "last_activity_ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                            "threshold_sec": self.stall_threshold_sec,
                        },
                    )
                self.set_status(wid, "stalled", reason="stall threshold exceeded")
        return stalled

    def compact_worktree(self, worktree_id: str) -> tuple[Path, Path]:
        """Write worktrees/<id>/local_journal.jsonl + regenerated summary.md."""
        if worktree_id not in self._last_activity:
            raise KeyError(f"no worktree {worktree_id}")
        wt_dir = self.session_dir / "worktrees" / worktree_id
        wt_dir.mkdir(parents=True, exist_ok=True)
        # Local journal: filter global journal events for this worktree/claim
        evs = replay(self.journal.path) if self.journal.path.exists() else []
        board = fold_claims(evs)
        local_ids = {cid for cid, p in board.items() if p.get("worktree_id") == worktree_id}
        local = [e for e in evs if e["payload"].get("worktree_id") == worktree_id or e["payload"].get("claim_id") in local_ids]
        lj = wt_dir / "local_journal.jsonl"
        lj.write_text(
            "\n".join(__import__("json").dumps(e, separators=(",", ":")) for e in local) + ("\n" if local else ""), encoding="utf-8"
        )
        summary = wt_dir / "summary.md"
        summary.write_text(
            f"# {worktree_id}\n\n- claims: {len(local_ids)}\n- status: {next((r['status'] for r in self.worktrees.list() if r['id'] == worktree_id), 'unknown')}\n",
            encoding="utf-8",
        )
        return lj, summary

    # ------------------------------------------------------------------ contradiction

    def find_contradictions(self) -> list[dict[str, Any]]:
        """Cross-worktree coherence check: flag syntactically contradictory claims."""
        evs = replay(self.journal.path) if self.journal.path.exists() else []
        board = fold_claims(evs)
        # Need the actual cards to compare
        cards: dict[str, ClaimCard] = {}
        for cid, payload in board.items():
            card_dict = payload.get("card")
            if card_dict:
                with contextlib.suppress(Exception):
                    cards[cid] = ClaimCard.model_validate(card_dict)
        out: list[dict[str, Any]] = []
        items = list(cards.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                cid_a, ca = items[i]
                cid_b, cb = items[j]
                wa = board[cid_a].get("worktree_id")
                wb = board[cid_b].get("worktree_id")
                if wa == wb:
                    continue
                if _are_contradictory(ca, cb):
                    out.append(
                        {
                            "claim_a": cid_a,
                            "claim_b": cid_b,
                            "worktree_a": wa,
                            "worktree_b": wb,
                            "reason": f"{ca.conclusion.expr!r} vs {cb.conclusion.expr!r} are syntactic negations",
                        }
                    )
        return out

    # ------------------------------------------------------------------ questions + Checkpoint C

    def post_question(
        self,
        question: str,
        timeout_default: str,
        *,
        worktree_id: str | None = None,
        agent_label: str | None = None,
        timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        """Non-blocking question (per-worktree or orchestrator-level when worktree_id is None)."""
        return self.questions.post_question(
            question=question,
            timeout_default=timeout_default,
            worktree_id=worktree_id,
            agent_label=agent_label,
            timeout_sec=timeout_sec,
        )

    def answer_question(self, question_id: str, answer: str, answered_by: str | None = None) -> dict[str, Any]:
        return self.questions.answer_question(question_id, answer, answered_by)

    def check_question_timeouts(self, now: float | None = None) -> list[dict[str, Any]]:
        return self.questions.check_timeouts(now=now)

    def primary_stop_question(self, verifying_worktree_id: str) -> dict[str, Any]:
        """Stage-level micro question (Pattern B): a worktree hit primary stop.

        Must be pattern B with timeout_default of "let the rest keep running" —
        the entire stage must NOT block when the user isn't watching.
        """
        return self.questions.post_question(
            question=f"{verifying_worktree_id} has a panel-verified result. Stop the remaining worktrees, or let them keep running for an independent second proof or method?",
            timeout_default="let the rest keep running",
            worktree_id=None,
            agent_label="orchestrator",
        )

    def checkpoint_c_summary(self) -> dict[str, Any]:
        """Build Checkpoint C table (worktree → status → best claim → confidence) + timeout assumptions."""
        evs = replay(self.journal.path) if self.journal.path.exists() else []
        board = fold_claims(evs)
        worktrees = self.worktrees.list()
        # Best claim per worktree = latest claim by that worktree (highest numeric suffix)
        best_by_wt: dict[str, dict[str, Any]] = {}
        for cid, payload in board.items():
            wid = payload.get("worktree_id")
            if wid not in best_by_wt or int(cid.split("_")[1]) > int(best_by_wt[wid].get("claim_id", "c_000").split("_")[1]):
                best_by_wt[wid] = {"claim_id": cid, **payload}
        table: list[dict[str, Any]] = []
        for rec in worktrees:
            wid = rec["id"]
            best = best_by_wt.get(wid)
            # confidence: map Tier0 verdict to rough confidence (placeholder)
            conf = 0.9 if best and best.get("verification_path") == "tier0" else 0.0
            table.append(
                {
                    "worktree_id": wid,
                    "status": rec.get("status", "running"),
                    "best_claim": best.get("claim_id") if best else None,
                    "verdict": best.get("card", {}).get("conclusion", {}).get("expr") if best else None,
                    "confidence": conf,
                }
            )
        from ramanujan.questions import QuestionStore as _QS

        defaults = _QS.timeout_defaults(evs)
        return {"worktrees": table, "timeout_defaults": defaults, "defaults_count": len(defaults)}

    def propose_checkpoint_c(self, prompt: str | None = None) -> Any:
        """Propose Checkpoint C via the reusable checkpoint abstraction."""
        summary = self.checkpoint_c_summary()
        out_ref = "orchestrator/checkpoint_c_summary.json"
        # Also write summary to session for inspection
        try:
            p = self.session_dir / "checkpoints_checkpoint_c.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(p, summary)
            out_ref = str(p)
        except Exception:
            pass
        assumptions_note = ""
        if summary["timeout_defaults"]:
            assumptions_note = " Timeout-assumed defaults: " + "; ".join(
                f"{d['question_id']}={d['answer']!r}" for d in summary["timeout_defaults"]
            )
        return self.checkpoints.propose(
            stage="computational",
            output_ref=out_ref,
            prompt=(prompt or "Stage 3 summary (worktree table + best claims) — confirm to proceed, or tell me what to change.") + assumptions_note,
            content=summary,  # type: ignore[arg-type]
        )

    def folded_board(self) -> dict[str, Any]:
        evs = replay(self.journal.path) if self.journal.path.exists() else []
        return fold_claims(evs)

    def folded_worktrees(self) -> dict[str, Any]:
        from ramanujan.worktree import WorktreeStore

        evs = replay(self.journal.path) if self.journal.path.exists() else []
        return WorktreeStore.fold_worktrees(evs)
