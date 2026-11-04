# Polars 2 annotates its expression inputs with types pyright cannot resolve without
# numpy/pyarrow stubs, which strict mode reports as "partially unknown".
# pyright: reportUnknownMemberType=false
"""In-memory daily market data and a point-in-time view that cannot see the future."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import polars as pl

from mindex.domain.decision import Asset


@dataclass(frozen=True, slots=True)
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class MarketData:
    """Aligned daily bars: `bars[asset][i]` is the bar of `days[i]` for every asset."""

    days: tuple[date, ...]
    assets: tuple[Asset, ...]
    bars: Mapping[Asset, tuple[Bar, ...]]
    fear_greed: tuple[int | None, ...]
    funding: Mapping[Asset, tuple[float | None, ...]]

    def __post_init__(self) -> None:
        n = len(self.days)
        if any(len(self.bars[a]) != n or len(self.funding[a]) != n for a in self.assets):
            raise ValueError("every asset needs a bar for every day")
        if len(self.fear_greed) != n:
            raise ValueError("fear_greed must align with days")

    def __len__(self) -> int:
        return len(self.days)

    def index_of(self, day: date) -> int:
        return self.days.index(day)

    @classmethod
    def from_frame(cls, df: pl.DataFrame) -> "MarketData":
        """Build from a snapshot frame, keeping only days on which every asset has a candle."""
        assets = tuple(Asset(a) for a in sorted(df["asset"].unique().to_list()))
        complete = (
            df.group_by("day")
            .agg(pl.col("asset").n_unique().alias("n"))
            .filter(pl.col("n") == len(assets))
        )
        df = df.join(complete.select("day"), on="day").sort("day")
        days = tuple(df.filter(pl.col("asset") == str(assets[0]))["day"].to_list())
        bars: dict[Asset, tuple[Bar, ...]] = {}
        funding: dict[Asset, tuple[float | None, ...]] = {}
        for asset in assets:
            part = df.filter(pl.col("asset") == str(asset))
            bars[asset] = tuple(
                Bar(*row)
                for row in part.select("open", "high", "low", "close", "volume").iter_rows()
            )
            funding[asset] = tuple(part["funding_rate"].to_list())
        first = df.filter(pl.col("asset") == str(assets[0]))
        return cls(days, assets, bars, tuple(first["fear_greed"].to_list()), funding)


@dataclass(frozen=True, slots=True)
class MarketView:
    """What an agent may see at the close of day `t`: nothing after `t` (no look-ahead)."""

    market: MarketData
    t: int

    @property
    def day(self) -> date:
        return self.market.days[self.t]

    @property
    def assets(self) -> tuple[Asset, ...]:
        return self.market.assets

    def bar(self, asset: Asset) -> Bar:
        return self.market.bars[asset][self.t]

    def closes(self, asset: Asset, n: int) -> list[float]:
        """Last `n` closes up to and including `t` (fewer if history is shorter)."""
        start = max(0, self.t - n + 1)
        return [b.close for b in self.market.bars[asset][start : self.t + 1]]

    @property
    def fear_greed(self) -> int | None:
        return self.market.fear_greed[self.t]

    def funding_rate(self, asset: Asset) -> float | None:
        return self.market.funding[asset][self.t]
