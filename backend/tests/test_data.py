# Polars 2 signatures are partially unknown to strict pyright (see mindex.sim.market).
# pyright: reportUnknownMemberType=false
import json
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import polars as pl
import pytest

from conftest import synthetic_frame
from mindex.data import sources
from mindex.data.snapshot import (
    MANIFEST,
    DataQualityError,
    build_frame,
    check_quality,
    load_split,
    load_window,
    write_snapshot,
)
from mindex.data.sources import Candle
from mindex.data.splits import (
    MODEL_RELEASE,
    SPLITS,
    SealedTestSetError,
    Split,
    Window,
    ensure_readable,
    split_of,
)
from mindex.domain.decision import Asset


class FakeExchange:
    """Daily candles from 2021-01-01, served `page` at a time like Binance."""

    def __init__(self, days: int, page: int = 3) -> None:
        self.start = sources.to_ms(date(2021, 1, 1))
        self.rows = [
            [self.start + i * sources.DAY_MS, 10.0 + i, 12.0 + i, 9.0 + i, 11.0 + i, 5.0]
            for i in range(days)
        ]
        self.page = page
        self.calls = 0

    def fetch_ohlcv(self, symbol: str, since: int, limit: int) -> list[list[float]]:
        assert symbol.endswith("/USDT")
        self.calls += 1
        return [r for r in self.rows if r[0] >= since][: min(limit, self.page)]

    def fetch_funding(self, symbol: str, since: int, limit: int) -> list[tuple[int, float]]:
        assert symbol.endswith("/USDT:USDT")
        self.calls += 1
        eight_h = sources.DAY_MS // 3
        points = [(self.start + i * eight_h, 0.0001 * (i % 3)) for i in range(9)]
        return [p for p in points if p[0] >= since][: min(limit, self.page)]


# --- splits ---------------------------------------------------------------


def test_splits_are_ordered_and_contiguous() -> None:
    windows = [SPLITS[s] for s in Split]
    for a, b in pairwise(windows):
        assert b.start == a.end + timedelta(days=1)
    assert SPLITS[Split.TEST].start > MODEL_RELEASE


def test_split_of() -> None:
    assert split_of(date(2023, 5, 1)) is Split.TRAIN
    assert split_of(date(2026, 1, 15)) is Split.VALIDATION
    assert split_of(date(2026, 6, 1)) is Split.TEST
    assert split_of(date(2019, 1, 1)) is None


def test_window_validation_and_size() -> None:
    assert Window(date(2026, 1, 1), date(2026, 1, 31)).days == 31
    assert "2026-01-01" not in Window(date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(ValueError, match="before"):
        Window(date(2026, 1, 2), date(2026, 1, 1))


def test_test_split_is_sealed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    ensure_readable(Split.VALIDATION)
    with pytest.raises(SealedTestSetError, match="sealed"):
        ensure_readable(Split.TEST)
    ensure_readable(Split.TEST, unseal=True)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(SealedTestSetError, match="CI"):
        ensure_readable(Split.TEST, unseal=True)


# --- sources --------------------------------------------------------------


def test_fetch_daily_candles_paginates_and_clips() -> None:
    ex = FakeExchange(days=10, page=3)
    candles = sources.fetch_daily_candles(ex, Asset.BTC, date(2021, 1, 2), date(2021, 1, 8))
    assert [c.day for c in candles] == [date(2021, 1, d) for d in range(2, 9)]
    assert candles[0] == Candle(date(2021, 1, 2), 11.0, 13.0, 10.0, 12.0, 5.0)
    assert ex.calls >= 3


def test_fetch_daily_candles_stops_on_empty_page() -> None:
    ex = FakeExchange(days=2)
    candles = sources.fetch_daily_candles(ex, Asset.ETH, date(2021, 1, 1), date(2021, 2, 1))
    assert len(candles) == 2


def test_fetch_daily_funding_averages_per_day() -> None:
    ex = FakeExchange(days=0, page=2)
    funding = sources.fetch_daily_funding(ex, Asset.BTC, date(2021, 1, 1), date(2021, 1, 2))
    assert funding[date(2021, 1, 1)] == pytest.approx(0.0001)
    assert set(funding) == {date(2021, 1, 1), date(2021, 1, 2)}


def test_parse_fear_greed() -> None:
    payload = json.dumps(
        {
            "data": [
                {"value": "25", "timestamp": "1609459200"},
                {"value": "80", "timestamp": "1609545600"},
            ]
        }
    ).encode()
    assert sources.fetch_fear_greed(lambda _url: payload) == {
        date(2021, 1, 1): 25,
        date(2021, 1, 2): 80,
    }


def test_http_get_rejects_plain_http() -> None:
    with pytest.raises(ValueError, match="https"):
        sources.http_get("http://example.com")


def test_ms_round_trip() -> None:
    assert sources.from_ms(sources.to_ms(date(2024, 2, 29))) == date(2024, 2, 29)
    assert sources.last_closed_day() < sources.utc_today()


# --- snapshot -------------------------------------------------------------


def test_build_frame_joins_sentiment() -> None:
    day = date(2021, 1, 1)
    df = build_frame(
        {Asset.BTC: [Candle(day, 1, 2, 0.5, 1.5, 10)]},
        {day: 40},
        {Asset.BTC: {day: 0.0002}},
    )
    row = df.row(0, named=True)
    assert row["fear_greed"] == 40
    assert row["funding_rate"] == pytest.approx(0.0002)


def test_quality_reports_gaps_and_rejects_bad_candles() -> None:
    df = synthetic_frame(date(2021, 1, 1), 5)
    gappy = df.filter(pl.col("day") != date(2021, 1, 3))
    report = check_quality(gappy)
    assert report.missing_days == {"BTC": ["2021-01-03"], "ETH": ["2021-01-03"]}

    with pytest.raises(DataQualityError, match="violate"):
        check_quality(df.with_columns(pl.col("low") * 10))
    with pytest.raises(DataQualityError, match="duplicate"):
        check_quality(pl.concat([df, df.head(1)]))


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    start = SPLITS[Split.VALIDATION].start - timedelta(days=40)
    df = synthetic_frame(start, 40 + 182 + 10)
    write_snapshot(df, tmp_path, source="synthetic")
    return tmp_path


def test_write_and_load_snapshot(snapshot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    manifest = json.loads((snapshot / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["files"]["validation"]["rows"] == 182 * 2
    val = load_split(snapshot, Split.VALIDATION)
    assert val["day"].min() == SPLITS[Split.VALIDATION].start
    with pytest.raises(SealedTestSetError):
        load_split(snapshot, Split.TEST)
    assert load_split(snapshot, Split.TEST, unseal=True).height == 10 * 2


def test_load_window_adds_lookback(snapshot: Path) -> None:
    df = load_window(snapshot, Split.VALIDATION, lookback_days=31)
    assert df["day"].min() == SPLITS[Split.VALIDATION].start - timedelta(days=31)
    assert load_window(snapshot, Split.TRAIN, lookback_days=31)["day"].min() == (
        SPLITS[Split.VALIDATION].start - timedelta(days=40)
    )


def test_tampered_snapshot_is_rejected(snapshot: Path) -> None:
    path = snapshot / "validation.parquet"
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(DataQualityError, match="checksum"):
        load_split(snapshot, Split.VALIDATION)
