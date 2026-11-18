"""Counterfactual table: hand-computed examples, round-trip detection and the look-ahead rule."""

import math
from datetime import date, timedelta

import pytest

from mindex.domain.decision import Asset
from mindex.postmortem.counterfactual import closed_on, counterfactual, round_trips
from mindex.sim.engine import ExecutionCosts, Fill, Portfolio, Side, rebalance
from mindex.sim.market import Bar, MarketData

D0 = date(2025, 3, 1)
NO_COSTS = ExecutionCosts(0.0, 0.0)


def day(i: int) -> date:
    return D0 + timedelta(days=i)


def bar(open_: float, low: float, close: float | None = None) -> Bar:
    close = open_ if close is None else close
    return Bar(open_, max(open_, close) + 1, low, close, 1.0)


def make_market(btc: list[Bar]) -> MarketData:
    n = len(btc)
    flat = tuple(bar(50.0, 49.0) for _ in range(n))
    return MarketData(
        days=tuple(day(i) for i in range(n)),
        assets=(Asset.BTC, Asset.ETH),
        bars={Asset.BTC: tuple(btc), Asset.ETH: flat},
        fear_greed=(50,) * n,
        funding={Asset.BTC: (None,) * n, Asset.ETH: (None,) * n},
    )


def buy(i: int, qty: float, price: float, fee: float = 0.0) -> Fill:
    return Fill(day(i), Asset.BTC, Side.BUY, qty, price, fee)


def sell(i: int, qty: float, price: float, fee: float = 0.0) -> Fill:
    return Fill(day(i), Asset.BTC, Side.SELL, qty, price, fee)


# Without costs: buy 10 @ 100 on day 1, sell 10 @ 90 on day 4. Stop level 95; day 3's low
# (94) reaches it with the open (97) above it, so the stop sells at 95.
LOSS_BARS = [bar(100, 99), bar(100, 98), bar(98, 96), bar(97, 94), bar(90, 89), bar(91, 90)]
LOSS_FILLS = [buy(1, 10, 100), sell(4, 10, 90)]


def test_loss_without_costs_hand_computed() -> None:
    cf = counterfactual(round_trips(LOSS_FILLS)[0], make_market(LOSS_BARS), costs=NO_COSTS)
    assert cf.cost == pytest.approx(1000)
    assert cf.actual == pytest.approx(-0.10)  # (900 - 1000) / 1000
    assert cf.skip == 0
    assert cf.half == pytest.approx(-0.05)
    assert cf.stop_loss == pytest.approx(-0.05)  # (950 - 1000) / 1000
    assert cf.stop_day == day(3)
    assert cf.holding_days == 3
    assert cf.table() == {"actual": -0.1, "skip": 0.0, "half": -0.05, "stop_loss": -0.05}


def test_gain_with_costs_hand_computed() -> None:
    # Default costs: 5 bps slippage, 0.1 % commission. Buy 10 at open 100 -> price 100.05,
    # fee 1.0005, cost 1001.5005. Sell at open 110 -> price 109.945, fee 1.09945,
    # proceeds 1098.35055. The lows never reach 95.0475, so the stop keeps the actual PnL.
    bars = [bar(100, 99), bar(100, 99), bar(104, 101), bar(108, 103), bar(110, 60)]
    fills = [buy(1, 10, 100.05, 1.0005), sell(4, 10, 109.945, 1.09945)]
    cf = counterfactual(round_trips(fills)[0], make_market(bars))
    expected = (1098.35055 - 1001.5005) / 1001.5005
    assert cf.cost == pytest.approx(1001.5005)
    assert cf.actual == pytest.approx(expected)
    assert cf.half == pytest.approx(expected / 2)
    # The closing day's low (60) cannot trigger the stop: the position is sold at its open.
    assert cf.stop_loss == pytest.approx(expected)
    assert cf.stop_day is None


def test_stop_gap_fills_at_open_with_costs() -> None:
    # Level 100.05 * 0.95 = 95.0475; day 3 opens at 90, below it, so the stop sells at 90:
    # price 89.955, fee 0.89955, proceeds 898.65045.
    bars = [bar(100, 99), bar(100, 99), bar(99, 97), bar(90, 88), bar(92, 91)]
    fills = [buy(1, 10, 100.05, 1.0005), sell(4, 10, 91.954, 0.91954)]
    cf = counterfactual(round_trips(fills)[0], make_market(bars))
    assert cf.stop_loss == pytest.approx((898.65045 - 1001.5005) / 1001.5005)
    assert cf.actual == pytest.approx((918.62046 - 1001.5005) / 1001.5005)
    assert cf.stop_day == day(3)


def test_entry_day_low_can_trigger_the_stop() -> None:
    bars = [bar(100, 99), bar(100, 94), bar(101, 100), bar(102, 101)]
    fills = [buy(1, 10, 100), sell(3, 10, 102)]
    cf = counterfactual(round_trips(fills)[0], make_market(bars), costs=NO_COSTS)
    assert cf.stop_day == day(1)
    assert cf.stop_loss == pytest.approx(-0.05)
    assert cf.actual == pytest.approx(0.02)


def test_stop_uses_average_entry_and_skips_later_fills() -> None:
    # Day 1 buy 10 @ 100, day 2 add 10 @ 80: average 90, level 85.5. Day 2 opens at 80
    # (below the level) and its low 79 triggers: all 20 sold at 80; the day 3 buy never happens.
    bars = [bar(100, 99), bar(100, 99), bar(80, 79), bar(82, 81), bar(85, 84)]
    fills = [buy(1, 10, 100), buy(2, 10, 80), buy(3, 5, 82), sell(4, 25, 85)]
    cf = counterfactual(round_trips(fills)[0], make_market(bars), costs=NO_COSTS, stop_pct=0.05)
    cost = 1000 + 800 + 410
    assert cf.cost == pytest.approx(cost)
    assert cf.actual == pytest.approx((25 * 85 - cost) / cost)
    assert cf.stop_loss == pytest.approx((1600 - 1800) / cost)
    assert cf.stop_day == day(2)


def test_stop_pct_is_a_parameter() -> None:
    market = make_market(LOSS_BARS)
    trip = round_trips(LOSS_FILLS)[0]
    wide = counterfactual(trip, market, costs=NO_COSTS, stop_pct=0.2)
    assert wide.stop_day is None
    assert wide.stop_loss == pytest.approx(wide.actual)
    with pytest.raises(ValueError, match="stop_pct"):
        counterfactual(trip, market, stop_pct=0)


def test_round_trips_adds_and_trims_belong_to_one_trip() -> None:
    fills = [
        sell(0, 1, 100),  # holding from before the window: ignored
        buy(1, 10, 100),
        buy(2, 5, 100),
        sell(3, 5, 100),  # trim: not a closing
        sell(4, 10, 100),
        buy(5, 1, 100),  # still open at the end: no post-mortem yet
    ]
    trips = round_trips(fills)
    assert len(trips) == 1
    assert [f.day for f in trips[0].fills] == [day(1), day(2), day(3), day(4)]
    assert closed_on(fills, day(3)) == []
    assert closed_on(fills, day(4)) == trips


def test_round_trip_closes_despite_float_residue() -> None:
    fills = [buy(1, 0.1, 100), buy(2, 0.2, 100), sell(3, 0.3, 100)]
    assert 0.1 + 0.2 - 0.3 != 0  # the residue the tolerance exists for
    assert len(round_trips(fills)) == 1


def test_round_trips_from_rebalance_match_cash() -> None:
    """Fills produced by the simulator's `rebalance` close cleanly and `actual` is the cash PnL."""
    market = make_market([bar(100, 99), bar(100, 99), bar(103, 101), bar(106, 104)])
    costs = ExecutionCosts()
    start = Portfolio(10_000.0)
    p1, f1 = rebalance(start, {Asset.BTC: 0.6}, {Asset.BTC: 100.0, Asset.ETH: 50.0}, costs, day(1))
    p2, f2 = rebalance(p1, {Asset.BTC: 0.3}, {Asset.BTC: 103.0, Asset.ETH: 50.0}, costs, day(2))
    p3, f3 = rebalance(p2, {}, {Asset.BTC: 106.0, Asset.ETH: 50.0}, costs, day(3))
    assert p3.holdings == {}
    trips = closed_on([*f1, *f2, *f3], day(3))
    assert len(trips) == 1
    cf = counterfactual(trips[0], market, costs=costs)
    assert cf.actual * cf.cost == pytest.approx(p3.cash - start.cash)


def test_no_look_ahead_prefix_and_perturbed_future() -> None:
    """Only bars up to the closing day matter: truncating or changing later bars is a no-op."""
    trip = round_trips(LOSS_FILLS)[0]
    full = make_market(LOSS_BARS)
    exit_index = full.index_of(trip.exit_day)
    prefix = make_market(LOSS_BARS[: exit_index + 1])
    future = [*LOSS_BARS[: exit_index + 1], *(bar(1.0, 0.5) for _ in LOSS_BARS[exit_index + 1 :])]
    perturbed = make_market(future)
    results = [counterfactual(trip, m) for m in (full, prefix, perturbed)]
    assert results[0] == results[1] == results[2]
    assert all(math.isfinite(v) for v in results[0].table().values())


def test_window_before_entry_is_ignored() -> None:
    crash_before = [bar(100, 1), *LOSS_BARS[1:]]
    trip = round_trips(LOSS_FILLS)[0]
    a = counterfactual(trip, make_market(LOSS_BARS), costs=NO_COSTS)
    b = counterfactual(trip, make_market(crash_before), costs=NO_COSTS)
    assert a == b


def test_no_look_ahead_with_float_residue_close() -> None:
    """0.1 + 0.2 - 0.3 leaves a residual holding after the close; a crash after the exit day
    must still not trigger the stop (reading bars past the exit would)."""
    fills = [buy(1, 0.1, 100), buy(2, 0.2, 100), sell(3, 0.3, 100)]
    head = [bar(100, 99), bar(100, 99), bar(100, 99), bar(100, 99)]
    trip = round_trips(fills)[0]
    full = make_market([*head, bar(100, 99), bar(100, 99)])
    prefix = make_market(head)
    crash = make_market([*head, bar(1.0, 0.5), bar(1.0, 0.5)])
    results = [counterfactual(trip, m, costs=NO_COSTS) for m in (full, prefix, crash)]
    assert results[0] == results[1] == results[2]
    assert results[0].stop_day is None
