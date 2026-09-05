"""Cost/time accounting — ramanujan/budget.py

Budgets are enforced, not advisory. On breach, stop cleanly and emit partial report.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    """Raised when a budget cap is hit."""

    def __init__(self, kind: str, limit: float, used: float) -> None:
        super().__init__(f"budget exceeded ({kind}): used={used:.4f} limit={limit:.4f}")
        self.kind = kind
        self.limit = limit
        self.used = used


@dataclass
class Budget:
    """Per-run budget. Check between every search phase."""

    budget_usd: float | None = None
    budget_sec: float | None = None
    spent_usd: float = 0.0
    t0: float = field(default_factory=time.monotonic)

    def add_cost(self, usd: float) -> None:
        self.spent_usd += float(usd)
        self.check()

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def remaining_usd(self) -> float | None:
        if self.budget_usd is None:
            return None
        return self.budget_usd - self.spent_usd

    def remaining_sec(self) -> float | None:
        if self.budget_sec is None:
            return None
        return self.budget_sec - self.elapsed()

    def check(self) -> None:
        """Raise BudgetExceeded if any cap is breached."""
        if self.budget_usd is not None and self.spent_usd > self.budget_usd + 1e-9:
            raise BudgetExceeded("cost", self.budget_usd, self.spent_usd)
        if self.budget_sec is not None and self.elapsed() > self.budget_sec + 1e-9:
            raise BudgetExceeded("time", self.budget_sec, self.elapsed())

    def is_exceeded(self) -> tuple[bool, str | None]:
        try:
            self.check()
            return False, None
        except BudgetExceeded as e:
            return True, e.kind

    def snapshot(self) -> dict[str, float | None]:
        return {
            "budget_usd": self.budget_usd,
            "spent_usd": self.spent_usd,
            "remaining_usd": self.remaining_usd(),
            "budget_sec": self.budget_sec,
            "elapsed_sec": self.elapsed(),
            "remaining_sec": self.remaining_sec(),
        }
