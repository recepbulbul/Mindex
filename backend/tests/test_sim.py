# Polars 2 signatures are partially unknown to strict pyright (see mindex.sim.market).
# pyright: reportUnknownMemberType=false
from datetime import date

import polars as pl
import pytest

from conftest import synthetic_frame
from mindex.domain.decision import Allocation, Asset, Decision
from mindex.sim.engine import (
    ExecutionCosts,
    Observation,
    Portfolio,
    Side,
    SimState,
    Simulator,
    rebalance,
)
from mindex.sim.market import MarketData, MarketView

DAY = date(2025, 1, 2)
PRICES = {Asset.BTC: 100.0, Asset.ETH: 50.0}


class Scripted:
    """Agent that replays fixed weights and records what it was shown."""

    def __init__(self, agent_id: str, weights: dict[Asset, float] | None) -> None:
        self.agent_id = agent_id
        self.weights = weights
        self.seen: list[Observation] = []

    def decide(self, obs: Observation) -> Decision | None:
        self.seen.append(obs)
        if self.weights is None:
            return None
        return Decision(
            allocations=[Allocation(asset=a, weight=w) for a, w in self.weights.items()],
            confidence=0.5,
            rationale="scripted test decision",
        )


def test_costs_validation() -> None:
    assert ExecutionCosts().slippage == pytest.approx(0.0005)
    with pytest.raises(ValueError, match="commission"):
        ExecutionCosts(commission_rate=0.5)
    with pytest.raises(ValueError, match="slippage"):
        ExecutionCosts(slippage_bps=-1)


def test_buy_applies_slippage_and_commission() -> None:
    costs = ExecutionCosts()
    pf, fills = rebalance(Portfolio(10_000.0), {Asset.BTC: 1.0}, PRICES, costs, DAY)
    (fill,) = fills
    assert fill.side is Side.BUY
    assert fill.price == pytest.approx(100.05)
    assert pf.cash >= 0
    # All cash spent; total cost = notional * (1 + commission)
    assert fill.quantity * fill.price + fill.fee == pytest.approx(10_000.0)
    assert pf.value(PRICES) < 10_000.0  # costs are real


def test_sell_then_buy_and_no_leverage() -> None:
    pf = Portfolio(0.0, {Asset.BTC: 100.0})  # 10 000 USDT of BTC
    new, fills = rebalance(pf, {Asset.ETH: 1.0}, PRICES, ExecutionCosts(), DAY)
    assert [f.side for f in fills] == [Side.SELL, Side.BUY]
    assert Asset.BTC not in new.holdings
    assert new.cash >= 0
    assert new.weights(PRICES)[Asset.ETH] == pytest.approx(1.0, abs=1e-6)


def test_tiny_drift_is_not_traded() -> None:
    pf = Portfolio(5.0, {Asset.BTC: 99.95})
    _, fills = rebalance(pf, {Asset.BTC: 1.0}, PRICES, ExecutionCosts(), DAY)
    assert fills == []


def test_zero_cost_rebalance_is_exact() -> None:
    free = ExecutionCosts(commission_rate=0.0, slippage_bps=0.0)
    pf, _ = rebalance(Portfolio(1000.0), {Asset.BTC: 0.5, Asset.ETH: 0.25}, PRICES, free, DAY)
    assert pf.holdings == {Asset.BTC: pytest.approx(5.0), Asset.ETH: pytest.approx(5.0)}
    assert pf.cash == pytest.approx(250.0)
    assert Portfolio(0.0).weights(PRICES) == {}


def test_market_view_has_no_future(market: MarketData) -> None:
    view = MarketView(market, 10)
    assert view.day == market.days[10]
    assert view.closes(Asset.BTC, 5)[-1] == market.bars[Asset.BTC][10].close
    assert len(view.closes(Asset.BTC, 100)) == 11
    assert view.bar(Asset.ETH) == market.bars[Asset.ETH][10]
    assert view.fear_greed == market.fear_greed[10]
    assert view.funding_rate(Asset.BTC) == pytest.approx(0.0001)
    assert market.index_of(market.days[3]) == 3


def test_market_drops_incomplete_days() -> None:
    df = synthetic_frame(date(2025, 1, 1), 5)
    df = df.filter(~((pl.col("asset") == "ETH") & (pl.col("day") == date(2025, 1, 3))))
    market = MarketData.from_frame(df)
    assert date(2025, 1, 3) not in market.days
    assert len(market) == 4


def test_market_rejects_misaligned_data(market: MarketData) -> None:
    with pytest.raises(ValueError, match="every asset"):
        MarketData(market.days[:-1], market.assets, market.bars, market.fear_greed, market.funding)
    with pytest.raises(ValueError, match="fear_greed"):
        MarketData(market.days, market.assets, market.bars, (), market.funding)


def test_decide_at_close_execute_next_open(market: MarketData) -> None:
    agent = Scripted("a", {Asset.BTC: 1.0})
    sim = Simulator(market, [agent], start=5)
    state = sim.step(sim.initial_state())
    assert agent.seen[0].view.t == 5
    assert agent.seen[0].step == 0
    fill = state.books["a"].fills[0]
    assert fill.day == market.days[6]
    assert fill.price == pytest.approx(market.bars[Asset.BTC][6].open * 1.0005)
    assert len(state.books["a"].equity) == 2


def test_holding_agent_keeps_cash(market: MarketData) -> None:
    state = Simulator(market, [Scripted("cash", None)]).run()
    book = state.books["cash"]
    assert set(book.equity) == {10_000.0}
    assert book.holds == book.decisions == len(market) - 1
    assert book.invested == [0.0] * len(market)


def test_checkpoint_resume_is_identical(market: MarketData) -> None:
    def make() -> Simulator:
        return Simulator(
            market, [Scripted("btc", {Asset.BTC: 0.6}), Scripted("eth", {Asset.ETH: 0.3})]
        )

    full = make().run()
    half = make().run(until=30)
    assert half.t == 30
    resumed = make().run(SimState.from_json(half.to_json()))
    assert resumed.to_json() == full.to_json()


def test_simulator_validates_setup(market: MarketData) -> None:
    with pytest.raises(ValueError, match="start"):
        Simulator(market, [], start=len(market) - 1)
    with pytest.raises(ValueError, match="unique"):
        Simulator(market, [Scripted("x", None), Scripted("x", None)])
