"""Per-agent persistent memory with hybrid retrieval (condition C1 / C1_NO_REGIME).

Retrieval = pgvector cosine distance + PostgreSQL full text (`lesson_tsv`), fused in
`fuse_scores` with an importance weight and an optional regime bonus.

Rules enforced in SQL, never after the fact:
- look-ahead: only lessons with `day < as_of_day` (a lesson learned today is not usable today);
- ownership: only the calling agent's own memories (sharing is the forum's job, P6).

The candidate step scores the agent's whole eligible set instead of
`ORDER BY embedding <=> q LIMIT n`: an HNSW scan filters after the index walk and could
return fewer than `k` rows for an agent with few memories among many. One agent holds at
most a few hundred lessons per run, so the exact scan is cheap.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from mindex.db.models import MemoryRow
from mindex.domain.regime import Regime
from mindex.memory.embedder import Embedder, tokenize

RRF_K = 10  # small lists (one agent's lessons): a lower k keeps rank differences visible
IMPORTANCE_WEIGHT = 0.3  # importance scales relevance into [1 - w, 1]
REGIME_BONUS = 0.2  # a regime match multiplies relevance by 1 + bonus (off in C1_NO_REGIME)


@dataclass(frozen=True, slots=True)
class Candidate:
    memory_id: uuid.UUID
    day: date
    regime: Regime
    importance: float
    cosine_distance: float
    text_rank: float  # ts_rank; 0 when the lesson matches no query term


@dataclass(frozen=True, slots=True)
class MemoryHit:
    memory: MemoryRow
    score: float  # in [0, 1]; stored in `decision_memories.score`


def _competition_ranks(values: Sequence[float], *, higher_is_better: bool) -> list[int]:
    """1-based ranks where ties share the best rank ("1224"), so equal inputs score equally."""
    sign = 1.0 if higher_is_better else -1.0
    keyed = [sign * v for v in values]
    return [1 + sum(1 for other in keyed if other > mine) for mine in keyed]


def fuse_scores(
    candidates: Sequence[Candidate],
    *,
    regime: Regime,
    use_regime: bool,
    rrf_k: int = RRF_K,
    importance_weight: float = IMPORTANCE_WEIGHT,
    regime_bonus: float = REGIME_BONUS,
) -> list[tuple[Candidate, float]]:
    """Rank candidates best first; returns `(candidate, score)` with scores in [0, 1].

    Reciprocal rank fusion (RRF) instead of a weighted min-max blend: cosine distance and
    `ts_rank` live on unrelated scales, `ts_rank` has no fixed maximum, and min-max breaks
    down when there is one candidate or all scores are equal (division by zero, or one
    lesson forced to 0 and another to 1 for a negligible difference). RRF fuses the two
    orderings without per-query normalisation.

    RRF alone discards how far a lesson is: the last of two lessons is only a little behind
    the first however unrelated it is, so the bonuses could lift a lesson at cosine distance
    0.99 over one at 0.01. The fused value is therefore multiplied by the absolute cosine
    similarity, a continuous relevance floor (a fixed distance cut-off would depend on the
    real model's similarity range, which is tuned on the validation period only):

    rrf        = [1/(k + rank_vec) + 1/(k + rank_text)] / (2/(k + 1))   in (0, 1]
                 (a lesson matching no query term gets no text term, not the last rank)
    relevance  = rrf * clamp(1 - cosine_distance, 0, 1)
    score      = relevance * (1 - w + w * importance) * (1 + bonus * match) / (1 + bonus)

    Bound: importance and the regime bonus multiply a score by at most
    (1 + bonus) / (1 - w) = 1.2 / 0.7 ~ 1.71, so a lesson overtakes another only if its
    relevance is at least ~58 % of the other's. Cost: a text match with zero vector
    similarity scores 0. Dividing by `1 + bonus` always (also when `use_regime` is false)
    keeps the score in [0, 1] without changing the order. Ties break on the newer lesson,
    then on id, so the order is deterministic.
    """
    if not candidates:
        return []
    vec_ranks = _competition_ranks([c.cosine_distance for c in candidates], higher_is_better=False)
    matched = [c for c in candidates if c.text_rank > 0]
    text_rank_of = dict(
        zip(
            (c.memory_id for c in matched),
            _competition_ranks([c.text_rank for c in matched], higher_is_better=True),
            strict=True,
        )
    )
    best = 2.0 / (rrf_k + 1)
    scored: list[tuple[Candidate, float]] = []
    for cand, vec_rank in zip(candidates, vec_ranks, strict=True):
        rrf = 1.0 / (rrf_k + vec_rank)
        if cand.memory_id in text_rank_of:
            rrf += 1.0 / (rrf_k + text_rank_of[cand.memory_id])
        similarity = min(max(1.0 - cand.cosine_distance, 0.0), 1.0)
        importance = min(max(cand.importance, 0.0), 1.0)
        weight = 1.0 - importance_weight + importance_weight * importance
        bonus = 1.0 + regime_bonus if use_regime and cand.regime == regime else 1.0
        scored.append((cand, (rrf / best) * similarity * weight * bonus / (1.0 + regime_bonus)))
    scored.sort(key=lambda cs: (-cs[1], -cs[0].day.toordinal(), str(cs[0].memory_id)))
    return scored


def text_query(query: str) -> str:
    """Query string for `websearch_to_tsquery`: terms OR-ed, since its default is AND and a
    sentence-like query would then only match lessons containing every word."""
    return " or ".join(t for t in tokenize(query) if t != "or")


class MemoryStore:
    def __init__(self, session: Session, embedder: Embedder | None = None) -> None:
        """`embedder` is needed to add and search lessons, not to `browse` them."""
        self.session = session
        self._embedder = embedder

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            raise ValueError("this MemoryStore was created without an embedder")
        return self._embedder

    def add(
        self,
        experiment_agent_id: uuid.UUID,
        day: date,
        lesson: str,
        counterfactual: dict[str, Any],
        regime: Regime,
        importance: float,
        source_trade_id: uuid.UUID | None = None,
    ) -> MemoryRow:
        """Embed and stage a lesson (flushed, not committed: the caller owns the transaction)."""
        row = MemoryRow(
            experiment_agent_id=experiment_agent_id,
            source_trade_id=source_trade_id,
            day=day,
            lesson=lesson,
            counterfactual=counterfactual,
            regime=regime,
            importance=Decimal(str(round(importance, 2))),
            embedding=self.embedder.embed([lesson])[0],
        )
        self.session.add(row)
        self.session.flush()
        return row

    def search(
        self,
        experiment_agent_id: uuid.UUID,
        query: str,
        as_of_day: date,
        regime: Regime,
        k: int,
        use_regime: bool,
    ) -> list[MemoryHit]:
        """Top-`k` own lessons learned strictly before `as_of_day`, best first."""
        if k <= 0:
            raise ValueError("k must be positive")
        query_vec = self.embedder.embed([query])[0]
        tsquery = func.websearch_to_tsquery("simple", text_query(query))
        distance: ColumnElement[float] = MemoryRow.embedding.cosine_distance(query_vec)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType, reportAttributeAccessIssue]
        text_rank = func.coalesce(func.ts_rank(MemoryRow.lesson_tsv, tsquery), 0.0)
        rows = self.session.execute(
            select(
                MemoryRow.id,
                MemoryRow.day,
                MemoryRow.regime,
                MemoryRow.importance,
                distance.label("distance"),
                text_rank.label("text_rank"),
            ).where(
                MemoryRow.experiment_agent_id == experiment_agent_id,
                MemoryRow.day < as_of_day,
            )
        ).all()
        candidates = [
            Candidate(
                memory_id=r.id,
                day=r.day,
                regime=r.regime,
                importance=float(r.importance),
                cosine_distance=float(r.distance),
                text_rank=float(r.text_rank),
            )
            for r in rows
        ]
        top = fuse_scores(candidates, regime=regime, use_regime=use_regime)[:k]
        if not top:
            return []
        loaded = {
            m.id: m
            for m in self.session.scalars(
                select(MemoryRow).where(MemoryRow.id.in_([c.memory_id for c, _ in top]))
            )
        }
        return [MemoryHit(memory=loaded[c.memory_id], score=s) for c, s in top]

    def browse(
        self,
        experiment_agent_ids: Sequence[uuid.UUID],
        *,
        regime: Regime | None = None,
        contains: str | None = None,
    ) -> list[MemoryRow]:
        """Lessons for the memory screen, most important first. Unlike `search` this is a read
        for people, not for an agent's decision: no embedding and no `as_of_day` cut-off."""
        query = select(MemoryRow).where(MemoryRow.experiment_agent_id.in_(experiment_agent_ids))
        if regime is not None:
            query = query.where(MemoryRow.regime == regime)
        if contains:
            escaped = contains.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(MemoryRow.lesson.ilike(f"%{escaped}%", escape="\\"))
        order = (MemoryRow.importance.desc(), MemoryRow.day.desc(), MemoryRow.id)
        return list(self.session.scalars(query.order_by(*order)))
