"""Simulator core (F3, NF2).

Each day `t` every agent sees the market up to the close of `t` and returns target weights;
orders execute at the open of `t+1` with commission and slippage. Long-only, no leverage.
The run is deterministic and can be checkpointed after any day and resumed bit for bit.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Protocol, cast

from mindex.domain.decision import Asset, Decision
from mindex.sim.market import MarketData, MarketView

DEFAULT_COMMISSION = 0.001  # 0.1 % per trade
DEFAULT_SLIPPAGE_BPS = 5.0
DEFAULT_INITIAL_CASH = 10_000.0
MIN_TRADE_FRACTION = 0.001  # trades under 0.1 % of equity are skipped (no fee churn on drift)


@dataclass(frozen=True, slots=True)
class ExecutionCosts:
    commission_rate: float = DEFAULT_COMMISSION
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS

    def __post_init__(self) -> None:
        if not 0 <= self.commission_rate <= 0.01:
            raise ValueError("commission_rate must be within [0, 0.01]")
        if not 0 <= self.slippage_bps <= 100:
            raise ValueError("slippage_bps must be within [0, 100]")

    @property
    def slippage(self) -> float:
        return self.slippage_bps / 10_000


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class Fill:
    day: date
    asset: Asset
    side: Side
    quantity: float
    price: float  # including slippage
    fee: float


@dataclass(frozen=True, slots=True)
class Portfolio:
    cash: float
    holdings: Mapping[Asset, float] = field(default_factory=dict[Asset, float])

    def value(self, prices: Mapping[Asset, float]) -> float:
        return self.cash + sum(q * prices[a] for a, q in self.holdings.items())

    def weights(self, prices: Mapping[Asset, float]) -> dict[Asset, float]:
        equity = self.value(prices)
        if equity <= 0:
            return {}
        return {a: q * prices[a] / equity for a, q in self.holdings.items() if q > 0}


def rebalance(
    portfolio: Portfolio,
    targets: Mapping[Asset, float],
    prices: Mapping[Asset, float],
    costs: ExecutionCosts,
    day: date,
) -> tuple[Portfolio, list[Fill]]:
    """Move the portfolio towards `targets` at `prices` (the open). Sells first, then buys.

    Buys are scaled down if fees would push cash below zero, so cash never goes negative.
    """
    equity = portfolio.value(prices)
    min_trade = equity * MIN_TRADE_FRACTION
    holdings = dict(portfolio.holdings)
    cash = portfolio.cash
    fills: list[Fill] = []

    deltas = {
        a: targets.get(a, 0.0) * equity - holdings.get(a, 0.0) * prices[a]
        for a in sorted(set(targets) | set(holdings))
    }
    for asset, delta in deltas.items():
        if delta < -min_trade:
            price = prices[asset] * (1 - costs.slippage)
            qty = min(holdings.get(asset, 0.0), -delta / prices[asset])
            fee = qty * price * costs.commission_rate
            cash += qty * price - fee
            holdings[asset] = holdings.get(asset, 0.0) - qty
            fills.append(Fill(day, asset, Side.SELL, qty, price, fee))

    buys = {a: d for a, d in deltas.items() if d > min_trade}
    unit_cost = 1 + costs.slippage
    needed = sum(d * unit_cost * (1 + costs.commission_rate) for d in buys.values())
    scale = min(1.0, cash / needed) if needed > 0 else 0.0
    for asset, delta in buys.items():
        price = prices[asset] * unit_cost
        qty = delta * scale / prices[asset]
        fee = qty * price * costs.commission_rate
        cash -= qty * price + fee
        holdings[asset] = holdings.get(asset, 0.0) + qty
        fills.append(Fill(day, asset, Side.BUY, qty, price, fee))

    clean = {a: q for a, q in holdings.items() if q > 1e-12}
    return Portfolio(max(cash, 0.0), clean), fills


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything an agent receives at the close of day `t`."""

    view: MarketView
    step: int  # days since the simulation started (0 on the first decision day)
    portfolio: Portfolio
    weights: Mapping[Asset, float]
    equity: float


class Agent(Protocol):
    @property
    def agent_id(self) -> str: ...

    def decide(self, obs: Observation) -> Decision | None:
        """Target weights for the next open, or None to keep the current portfolio."""
        ...


@dataclass(slots=True)
class AgentBook:
    portfolio: Portfolio
    equity: list[float]  # mark-to-market at each close, starting with the initial cash
    invested: list[float]  # non-cash weight at each close (herd correlation input)
    fills: list[Fill]
    decisions: int = 0
    holds: int = 0


@dataclass(slots=True)
class SimState:
    """Checkpoint: the next day to decide on and every agent's book so far."""

    t: int
    books: dict[str, AgentBook]

    def to_json(self) -> str:
        def book(b: AgentBook) -> dict[str, Any]:
            return {
                "cash": b.portfolio.cash,
                "holdings": {str(a): q for a, q in b.portfolio.holdings.items()},
                "equity": b.equity,
                "invested": b.invested,
                "fills": [_fill_to_dict(f) for f in b.fills],
                "decisions": b.decisions,
                "holds": b.holds,
            }

        return json.dumps({"t": self.t, "books": {k: book(v) for k, v in self.books.items()}})

    @classmethod
    def from_json(cls, raw: str) -> "SimState":
        data = cast(dict[str, Any], json.loads(raw))
        books: dict[str, AgentBook] = {}
        for agent_id, b in cast(dict[str, dict[str, Any]], data["books"]).items():
            holdings = {
                Asset(a): float(q) for a, q in cast(dict[str, float], b["holdings"]).items()
            }
            fills = [_fill_from_dict(f) for f in cast(list[dict[str, Any]], b["fills"])]
            books[agent_id] = AgentBook(
                Portfolio(float(b["cash"]), holdings),
                [float(e) for e in cast(list[float], b["equity"])],
                [float(w) for w in cast(list[float], b["invested"])],
                fills,
                int(b["decisions"]),
                int(b["holds"]),
            )
        return cls(int(data["t"]), books)


def _fill_to_dict(f: Fill) -> dict[str, Any]:
    return {
        "day": f.day.isoformat(),
        "asset": str(f.asset),
        "side": str(f.side),
        "quantity": f.quantity,
        "price": f.price,
        "fee": f.fee,
    }


def _fill_from_dict(d: Mapping[str, Any]) -> Fill:
    return Fill(
        date.fromisoformat(str(d["day"])),
        Asset(str(d["asset"])),
        Side(str(d["side"])),
        float(d["quantity"]),
        float(d["price"]),
        float(d["fee"]),
    )


class Simulator:
    def __init__(
        self,
        market: MarketData,
        agents: Sequence[Agent],
        *,
        start: int = 0,
        costs: ExecutionCosts | None = None,
        initial_cash: float = DEFAULT_INITIAL_CASH,
    ) -> None:
        if not 0 <= start < len(market) - 1:
            raise ValueError("start must leave at least one day to execute on")
        ids = [a.agent_id for a in agents]
        if len(ids) != len(set(ids)):
            raise ValueError("agent ids must be unique")
        self.market = market
        self.agents = list(agents)
        self.start = start
        self.costs = costs or ExecutionCosts()
        self.initial_cash = initial_cash

    def initial_state(self) -> SimState:
        return SimState(
            self.start,
            {
                a.agent_id: AgentBook(Portfolio(self.initial_cash), [self.initial_cash], [0.0], [])
                for a in self.agents
            },
        )

    def step(self, state: SimState) -> SimState:
        """Decide at the close of `state.t`, execute at the open of `t+1`, mark at its close."""
        t = state.t
        view = MarketView(self.market, t)
        bars = self.market.bars
        close_t = {a: bars[a][t].close for a in self.market.assets}
        open_next = {a: bars[a][t + 1].open for a in self.market.assets}
        close_next = {a: bars[a][t + 1].close for a in self.market.assets}
        for agent in self.agents:
            book = state.books[agent.agent_id]
            obs = Observation(
                view,
                t - self.start,
                book.portfolio,
                book.portfolio.weights(close_t),
                book.portfolio.value(close_t),
            )
            decision = agent.decide(obs)
            book.decisions += 1
            if decision is None:
                book.holds += 1
            else:
                book.portfolio, fills = rebalance(
                    book.portfolio,
                    decision.weights(),
                    open_next,
                    self.costs,
                    self.market.days[t + 1],
                )
                book.fills.extend(fills)
            equity = book.portfolio.value(close_next)
            book.equity.append(equity)
            book.invested.append(1 - book.portfolio.cash / equity if equity > 0 else 0.0)
        state.t = t + 1
        return state

    def run(self, state: SimState | None = None, *, until: int | None = None) -> SimState:
        """Run from `state` (or the start) until day index `until` (default: the last day)."""
        state = state or self.initial_state()
        last = len(self.market) - 1 if until is None else min(until, len(self.market) - 1)
        while state.t < last:
            state = self.step(state)
        return state
