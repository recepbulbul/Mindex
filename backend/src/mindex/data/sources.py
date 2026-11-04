# ccxt ships without type stubs; its calls are wrapped and cast in the two adapter classes.
# pyright: reportMissingTypeStubs=false
"""Raw data sources: Binance daily OHLCV and funding rates via ccxt, Fear & Greed index.

Fetching goes through small protocols so pagination and parsing are tested with fakes;
only `CcxtSpot` / `CcxtFutures` / `http_get` touch the network.
"""

import json
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import fmean
from typing import Any, Protocol, cast

from mindex.domain.decision import Asset

DAY_MS = 86_400_000
PAGE_LIMIT = 1000
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=0&format=json"
QUOTE = "USDT"


@dataclass(frozen=True, slots=True)
class Candle:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class OhlcvSource(Protocol):
    def fetch_ohlcv(self, symbol: str, since: int, limit: int) -> list[list[float]]: ...


class FundingSource(Protocol):
    def fetch_funding(self, symbol: str, since: int, limit: int) -> list[tuple[int, float]]: ...


def to_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def from_ms(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date()


def spot_symbol(asset: Asset) -> str:
    return f"{asset}/{QUOTE}"


def perp_symbol(asset: Asset) -> str:
    return f"{asset}/{QUOTE}:{QUOTE}"


def fetch_daily_candles(source: OhlcvSource, asset: Asset, start: date, end: date) -> list[Candle]:
    """All daily candles with start <= day <= end, paginating forward from `start`."""
    since, end_ms = to_ms(start), to_ms(end)
    candles: dict[date, Candle] = {}
    while since <= end_ms:
        page = source.fetch_ohlcv(spot_symbol(asset), since, PAGE_LIMIT)
        if not page:
            break
        for ts, o, h, low, c, v in page:
            if ts > end_ms:
                break
            day = from_ms(int(ts))
            candles[day] = Candle(day, float(o), float(h), float(low), float(c), float(v))
        last = int(page[-1][0])
        if last < since:  # defensive: the exchange must make progress
            break
        since = last + DAY_MS
    return [candles[d] for d in sorted(candles)]


def fetch_daily_funding(
    source: FundingSource, asset: Asset, start: date, end: date
) -> dict[date, float]:
    """Mean of the (8-hourly) perpetual funding rates per UTC day."""
    since, end_ms = to_ms(start), to_ms(end) + DAY_MS - 1
    per_day: dict[date, list[float]] = defaultdict(list)
    while since <= end_ms:
        page = source.fetch_funding(perp_symbol(asset), since, PAGE_LIMIT)
        if not page:
            break
        for ts, rate in page:
            if ts <= end_ms:
                per_day[from_ms(ts)].append(rate)
        last = page[-1][0]
        if last < since:
            break
        since = last + 1
    return {d: fmean(rates) for d, rates in sorted(per_day.items())}


def parse_fear_greed(payload: bytes) -> dict[date, int]:
    body = cast(Mapping[str, Any], json.loads(payload))
    rows = cast(list[Mapping[str, str]], body.get("data", []))
    return {from_ms(int(row["timestamp"]) * 1000): int(row["value"]) for row in rows}


def http_get(url: str, timeout: float = 30.0) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("only https URLs are fetched")
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (scheme checked)
        return cast(bytes, resp.read())


def fetch_fear_greed(get: Callable[[str], bytes] = http_get) -> dict[date, int]:
    return parse_fear_greed(get(FEAR_GREED_URL))


class CcxtSpot:
    """Binance spot market data (public endpoints, no API key)."""

    def __init__(self) -> None:
        import ccxt  # heavy import, only needed when fetching

        self._exchange: Any = ccxt.binance({"enableRateLimit": True})

    def fetch_ohlcv(self, symbol: str, since: int, limit: int) -> list[list[float]]:
        return cast(list[list[float]], self._exchange.fetch_ohlcv(symbol, "1d", since, limit))


class CcxtFutures:
    """Binance USDⓈ-M perpetual funding history (public endpoint, observation feature only)."""

    def __init__(self) -> None:
        import ccxt

        self._exchange: Any = ccxt.binanceusdm({"enableRateLimit": True})

    def fetch_funding(self, symbol: str, since: int, limit: int) -> list[tuple[int, float]]:
        rows = cast(
            list[Mapping[str, Any]], self._exchange.fetch_funding_rate_history(symbol, since, limit)
        )
        return [(int(r["timestamp"]), float(r["fundingRate"])) for r in rows]


def utc_today() -> date:
    return datetime.now(UTC).date()


def last_closed_day() -> date:
    """Most recent day whose daily candle has closed."""
    return utc_today() - timedelta(days=1)
