"""Memory recall for a decision (C1 / C1'): what is asked of the store, and what reaches the
prompt. A spy replaces the store, so no database is needed."""

import uuid
from datetime import date
from typing import Any, cast

from mindex.db.models import MemoryRow
from mindex.domain.decision import Asset
from mindex.domain.regime import Regime
from mindex.memory.recall import make_recall, recall_query
from mindex.memory.store import MemoryHit, MemoryStore
from mindex.sim.engine import Observation, Portfolio
from mindex.sim.market import MarketData, MarketView

AGENT = uuid.uuid4()


def obs(market: MarketData, t: int, weights: dict[Asset, float] | None = None) -> Observation:
    return Observation(MarketView(market, t), t, Portfolio(10_000.0), weights or {}, 10_000.0)


def hit(lesson: str, *, day: date = date(2025, 1, 5), score: float = 0.5) -> MemoryHit:
    row = MemoryRow(id=uuid.uuid4(), day=day, lesson=lesson, regime=Regime.BEAR)
    return MemoryHit(memory=row, score=score)


class SpyStore:
    def __init__(self, hits: list[MemoryHit]) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def search(self, agent_id: uuid.UUID, query: str, **kwargs: Any) -> list[MemoryHit]:
        self.calls.append({"agent_id": agent_id, "query": query, **kwargs})
        return self.hits


def recall_with(store: SpyStore, regimes: list[Regime], *, use_regime: bool = True):
    return make_recall(cast(MemoryStore, store), AGENT, regimes=regimes, use_regime=use_regime, k=2)


def test_recall_asks_only_for_lessons_before_the_decision_day(market: MarketData) -> None:
    store = SpyStore([hit("ASSET_A girişi %3,2 kaybettirdi; girmemek daha iyiydi.")])
    regimes = [Regime.SIDEWAYS] * 20 + [Regime.BULL] * 40
    o = obs(market, 30)
    got = recall_with(store, regimes)(o)
    (call,) = store.calls
    assert call["agent_id"] == AGENT
    assert call["as_of_day"] == o.view.day  # the store keeps `day < as_of_day`
    assert (call["regime"], call["use_regime"], call["k"]) == (Regime.BULL, True, 2)
    assert [x.lesson for x in got] == ["ASSET_A girişi %3,2 kaybettirdi; girmemek daha iyiydi."]
    assert got[0].regime == "bear"


def test_c1_prime_asks_without_the_regime_bonus(market: MarketData) -> None:
    store = SpyStore([])
    recall_with(store, [Regime.BEAR] * 60, use_regime=False)(obs(market, 30))
    assert store.calls[0]["use_regime"] is False


def test_c1_prime_keeps_the_regime_out_of_the_query_too(market: MarketData) -> None:
    """Only dropping the bonus is not enough: the regime word in the query changes the
    similarity ranking, so C1 vs C1' would not isolate regime conditioning."""
    queries: dict[bool, list[str]] = {}
    for use_regime in (True, False):
        store = SpyStore([])
        for regime in (Regime.BULL, Regime.BEAR):
            recall_with(store, [regime] * 60, use_regime=use_regime)(obs(market, 30))
        queries[use_regime] = [c["query"] for c in store.calls]
    assert queries[True][0] != queries[True][1]  # C1: the label is in the query
    assert queries[False][0] == queries[False][1]  # C1': same situation, same query
    assert not any(w in queries[False][0] for w in ("bull", "bear", "sideways"))


def test_lesson_naming_a_real_asset_is_left_out(market: MarketData) -> None:
    clean = hit("ASSET_B pozisyonu %2,5 kazandırdı; tutmak doğruydu.")
    leaky = hit("BTC pozisyonu %2,5 kazandırdı; tutmak doğruydu.")
    store = SpyStore([leaky, clean])
    got = recall_with(store, [Regime.BULL] * 60)(obs(market, 30))
    assert [x.memory_id for x in got] == [clean.memory.id]


def test_query_describes_regime_trend_and_holdings(market: MarketData) -> None:
    # BTC rises 1 %/day in the fixture, ETH oscillates.
    query = recall_query(obs(market, 40, {Asset.BTC: 0.4}), Regime.BEAR)
    words = query.split()
    assert words[0] == "bear"
    assert "ASSET_A yükseliş" in query
    assert "ASSET_A pozisyon" in query
    assert "ASSET_B pozisyon" not in query
    assert all(leak not in query for leak in ("BTC", "ETH"))
    assert query == recall_query(obs(market, 40, {Asset.BTC: 0.4}), Regime.BEAR)  # deterministic


def test_query_with_short_history_does_not_claim_a_trend(market: MarketData) -> None:
    assert "ASSET_A düşüş" in recall_query(obs(market, 3), Regime.SIDEWAYS)
