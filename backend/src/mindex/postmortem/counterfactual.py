"""Counterfactual PnL table of a closed position (pure, deterministic).

A *round trip* is the run of one agent's fills in one asset from flat to flat: it opens with
a buy while holding nothing and closes with the sell that brings the holding back to
(numerically) zero. Adds and trims in between belong to the same round trip; a trim is not
a closing, so it does not trigger a post-mortem.

Scenarios, all as fractions of the actual round trip's entry cost (sum of buy notional plus
fees), so they are directly comparable and match `Counterfactual` in the API contract:

- `actual`: realised PnL of the fills as executed (they already include slippage and fees);
- `skip`: never entering, always 0;
- `half`: every fill at half the quantity. Slippage and commission are proportional, so this
  is exactly `actual / 2`;
- `stop_loss`: the same fills, but the whole holding is sold once the intraday low reaches
  `(1 - stop_pct)` x the average entry price (incl. slippage) of the buys so far; no fill of
  the round trip after the trigger happens. The exit goes through `rebalance` at the stop
  level (or at the open if the bar gaps below it), so it pays the simulator's slippage and
  commission.

Look-ahead: only bars from the entry day up to the closing day are read, the post-mortem
runs at the close of the closing day. Assumptions about the intraday order: fills execute at
the open of `Fill.day` (as in the simulator) and the low comes after the open. So the entry
day's low can trigger the stop, the closing day's low cannot (the position is sold at that
open), and on every day the day's fills are applied before its low is checked.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from mindex.domain.decision import Asset
from mindex.sim.engine import ExecutionCosts, Fill, Portfolio, Side, rebalance
from mindex.sim.market import Bar, MarketData

DEFAULT_STOP_PCT = 0.05
CLOSE_TOLERANCE = 1e-9  # holding below this share of the largest holding counts as flat


@dataclass(frozen=True, slots=True)
class RoundTrip:
    asset: Asset
    fills: tuple[Fill, ...]  # chronological; first is a buy, last is the closing sell

    @property
    def entry_day(self) -> date:
        return self.fills[0].day

    @property
    def exit_day(self) -> date:
        return self.fills[-1].day


@dataclass(frozen=True, slots=True)
class Counterfactual:
    asset: Asset
    entry_day: date
    exit_day: date
    holding_days: int  # trading days from the entry fill to the closing fill
    stop_pct: float
    cost: float  # entry cost of the actual round trip, the denominator of every scenario
    actual: float
    skip: float
    half: float
    stop_loss: float
    stop_day: date | None  # day the stop would have fired, None if it never did

    def table(self) -> dict[str, float]:
        """The four scenarios, as stored in `memories.counterfactual` (API: `Counterfactual`)."""
        return {
            "actual": round(self.actual, 6),
            "skip": round(self.skip, 6),
            "half": round(self.half, 6),
            "stop_loss": round(self.stop_loss, 6),
        }


def round_trips(fills: Iterable[Fill]) -> list[RoundTrip]:
    """Closed round trips in `fills`, ordered by closing day then asset; open ones are left out."""
    by_asset: dict[Asset, list[Fill]] = defaultdict(list)
    for fill in fills:
        by_asset[fill.asset].append(fill)
    trips: list[RoundTrip] = []
    for asset, asset_fills in by_asset.items():
        current: list[Fill] = []
        held = peak = 0.0
        for fill in sorted(asset_fills, key=lambda f: f.day):
            if not current and fill.side is Side.SELL:
                continue  # selling something bought before `fills` starts: not a full trip
            current.append(fill)
            held += fill.quantity if fill.side is Side.BUY else -fill.quantity
            peak = max(peak, held)
            if fill.side is Side.SELL and held <= peak * CLOSE_TOLERANCE:
                trips.append(RoundTrip(asset, tuple(current)))
                current, held, peak = [], 0.0, 0.0
    trips.sort(key=lambda t: (t.exit_day, str(t.asset)))
    return trips


def closed_on(fills: Iterable[Fill], day: date) -> list[RoundTrip]:
    """Round trips whose closing sell executed on `day`: the post-mortems due at its close."""
    return [t for t in round_trips(fills) if t.exit_day == day]


def _cash_flow(fill: Fill) -> float:
    notional = fill.quantity * fill.price
    return notional - fill.fee if fill.side is Side.SELL else -(notional + fill.fee)


def _sell_all(
    asset: Asset, quantity: float, price: float, costs: ExecutionCosts, day: date
) -> float:
    """Cash from selling `quantity` at `price` with the simulator's slippage and commission."""
    after, _ = rebalance(Portfolio(0.0, {asset: quantity}), {}, {asset: price}, costs, day)
    return after.cash


def _stop_loss_pnl(
    trip: RoundTrip,
    bars: Sequence[Bar],
    days: Sequence[date],
    stop_pct: float,
    costs: ExecutionCosts,
) -> tuple[float, date | None]:
    fills_by_day: dict[date, list[Fill]] = defaultdict(list)
    for fill in trip.fills:
        fills_by_day[fill.day].append(fill)
    cash = held = bought_qty = bought_notional = 0.0
    for day, bar in zip(days[:-1], bars[:-1], strict=True):  # the closing day's low is moot
        for fill in fills_by_day.get(day, []):
            cash += _cash_flow(fill)
            if fill.side is Side.BUY:
                held += fill.quantity
                bought_qty += fill.quantity
                bought_notional += fill.quantity * fill.price
            else:
                held -= fill.quantity
        if held <= 0 or bought_qty == 0:
            continue
        level = bought_notional / bought_qty * (1 - stop_pct)
        if bar.low <= level:
            # A gap below the level fills at the open, never at the better stop price.
            return cash + _sell_all(trip.asset, held, min(bar.open, level), costs, day), day
    return sum(_cash_flow(f) for f in trip.fills), None


def counterfactual(
    trip: RoundTrip,
    market: MarketData,
    *,
    costs: ExecutionCosts | None = None,
    stop_pct: float = DEFAULT_STOP_PCT,
) -> Counterfactual:
    """Counterfactual table for `trip`, reading only `market` bars up to its closing day."""
    if not 0 < stop_pct < 1:
        raise ValueError("stop_pct must be within (0, 1)")
    costs = costs or ExecutionCosts()
    start = market.index_of(trip.entry_day)
    end = market.index_of(trip.exit_day)
    bars = market.bars[trip.asset][start : end + 1]
    days = market.days[start : end + 1]
    cost = sum(-_cash_flow(f) for f in trip.fills if f.side is Side.BUY)
    actual = sum(_cash_flow(f) for f in trip.fills)
    stop_pnl, stop_day = _stop_loss_pnl(trip, bars, days, stop_pct, costs)
    return Counterfactual(
        asset=trip.asset,
        entry_day=trip.entry_day,
        exit_day=trip.exit_day,
        holding_days=end - start,
        stop_pct=stop_pct,
        cost=cost,
        actual=actual / cost,
        skip=0.0,
        half=actual / 2 / cost,
        stop_loss=stop_pnl / cost,
        stop_day=stop_day,
    )
