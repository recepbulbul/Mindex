"""LLM latency statistics and the experiment compute budget (risk table, İP3: ≈ 50 hours)."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from mindex.data.splits import SPLITS, Split

P95_TARGET_SECONDS = 10.0  # NF1: decision call p95 < 10 s
BUDGET_HOURS = 50.0


def percentile(samples: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in [0, 100])."""
    if not samples:
        raise ValueError("no samples")
    if not 0 <= q <= 100:
        raise ValueError("q must be within [0, 100]")
    ordered = sorted(samples)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


@dataclass(frozen=True, slots=True)
class LatencySummary:
    n: int
    p50_s: float
    p95_s: float
    max_s: float

    @classmethod
    def of(cls, seconds: Sequence[float]) -> "LatencySummary":
        return cls(len(seconds), percentile(seconds, 50), percentile(seconds, 95), max(seconds))

    @property
    def meets_target(self) -> bool:
        return self.p95_s < P95_TARGET_SECONDS


@dataclass(frozen=True, slots=True)
class ComputeBudget:
    """LLM calls for the main test-period experiment: days * LLM agents * conditions * seeds."""

    days: int = SPLITS[Split.TEST].days
    llm_agents: int = 4
    conditions: int = 5  # C0, C1, C1_NO_REGIME, C2, C3
    seeds: int = 5

    @property
    def calls(self) -> int:
        return self.days * self.llm_agents * self.conditions * self.seeds

    def hours(self, seconds_per_call: float) -> float:
        return self.calls * seconds_per_call / 3600

    def max_seconds_per_call(self, budget_hours: float = BUDGET_HOURS) -> float:
        return budget_hours * 3600 / self.calls
