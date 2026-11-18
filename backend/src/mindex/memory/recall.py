"""Binds an agent's `MemoryStore` to its decisions (conditions C1 and C1').

`make_recall` returns the `Recall` callable an `LLMAgent` calls before every decision. It
searches only the agent's own lessons with `day < decision day` (enforced in SQL by
`MemoryStore.search`), using the day's regime label, and hands back anonymised lessons.
"""

from collections.abc import Sequence
from uuid import UUID

import structlog

from mindex.agents.llm import MEMORY_K, Recall, RecalledLesson, anonymise
from mindex.domain.regime import Regime
from mindex.memory.store import MemoryStore
from mindex.postmortem.lesson import REAL_SYMBOLS
from mindex.sim.engine import Observation

log = structlog.get_logger(__name__)


def recall_query(obs: Observation, regime: Regime) -> str:
    """Deterministic text describing today's situation, in the words lessons are written in:
    the regime and, per anonymised asset, the 7-day direction and whether it is held."""
    codes = anonymise(obs.view.assets)
    parts = [regime.value]
    for asset in obs.view.assets:
        closes = obs.view.closes(asset, 8)
        trend = "yükseliş" if len(closes) >= 8 and closes[-1] > closes[0] else "düşüş"
        parts.append(f"{codes[asset]} {trend}")
        if obs.weights.get(asset, 0.0) > 0:
            parts.append(f"{codes[asset]} pozisyon")
    return " ".join(parts)


def make_recall(
    store: MemoryStore,
    experiment_agent_id: UUID,
    *,
    regimes: Sequence[Regime],
    use_regime: bool,
    k: int = MEMORY_K,
) -> Recall:
    """`regimes[t]` is the label of day `t` (as the runner decided with); `use_regime` is False
    in C1', which keeps the regime out of the ranking."""

    def recall(obs: Observation) -> list[RecalledLesson]:
        regime = regimes[obs.view.t]
        hits = store.search(
            experiment_agent_id,
            recall_query(obs, regime),
            as_of_day=obs.view.day,
            regime=regime,
            k=k,
            use_regime=use_regime,
        )
        lessons: list[RecalledLesson] = []
        for hit in hits:
            m = hit.memory
            if REAL_SYMBOLS.search(m.lesson):
                # Written lessons never name a real asset; one that does would leak it back
                # into an anonymised prompt, so it is left out rather than edited.
                log.warning("lesson_names_real_asset", memory_id=str(m.id))
                continue
            lessons.append(RecalledLesson(m.id, m.lesson, hit.score, m.day, m.regime.value))
        return lessons

    return recall
