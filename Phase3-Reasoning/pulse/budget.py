"""Per-run token/cost budget guard — Architecture.md §9.

Shared between clustering-adjacent stages and summarize.py: any call site
that spends tokens/cost records it here, and checks `has_budget()` before
spending more.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BudgetGuard:
    max_tokens: int
    max_cost_usd: float
    tokens_used: int = field(default=0, init=False)
    cost_usd: float = field(default=0.0, init=False)
    truncated: bool = field(default=False, init=False)

    def has_budget(self) -> bool:
        return self.tokens_used < self.max_tokens and self.cost_usd < self.max_cost_usd

    def record(self, tokens: int, cost_usd: float) -> None:
        self.tokens_used += tokens
        self.cost_usd += cost_usd

    def mark_truncated(self) -> None:
        self.truncated = True
