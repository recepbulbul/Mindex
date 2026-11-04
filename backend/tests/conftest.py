import math
from datetime import date, timedelta

import polars as pl
import pytest

from mindex.data.snapshot import SCHEMA
from mindex.domain.decision import Asset
from mindex.sim.market import MarketData

ASSETS = (Asset.BTC, Asset.ETH)


def synthetic_frame(start: date, days: int, assets: tuple[Asset, ...] = ASSETS) -> pl.DataFrame:
    """Deterministic price paths: BTC trends up, ETH oscillates, others drift down."""
    rows: list[dict[str, object]] = []
    for k, asset in enumerate(assets):
        for i in range(days):
            if k == 0:
                close = 100.0 * (1.01**i)
            elif k == 1:
                close = 50.0 + 10.0 * math.sin(i / 3)
            else:
                close = 20.0 * (0.995**i)
            open_ = close * 0.995
            rows.append(
                {
                    "asset": str(asset),
                    "day": start + timedelta(days=i),
                    "open": open_,
                    "high": max(open_, close) * 1.01,
                    "low": min(open_, close) * 0.99,
                    "close": close,
                    "volume": 1000.0 + i,
                    "fear_greed": 50 + i % 10,
                    "funding_rate": 0.0001,
                }
            )
    return pl.DataFrame(rows, schema=SCHEMA)


@pytest.fixture
def market() -> MarketData:
    return MarketData.from_frame(synthetic_frame(date(2025, 1, 1), 60))
