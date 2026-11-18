from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from mindex.data.snapshot import SCHEMA
from mindex.domain.regime import Regime
from mindex.regime.hmm import RegimeModel, regime_features
from mindex.sim.market import MarketData

# Three clearly different regimes: calm rally, volatile crash, calm drift.
SEGMENTS = ((0.015, 0.01), (-0.02, 0.02), (0.0, 0.005))
SEGMENT_DAYS = 80


def regime_market(
    seed: int = 7, segments: tuple[tuple[float, float], ...] = SEGMENTS
) -> MarketData:
    rng = np.random.default_rng(seed)
    rets = np.concatenate([rng.normal(mu, sd, SEGMENT_DAYS) for mu, sd in segments])
    closes = 100.0 * np.exp(np.cumsum(rets))
    start = date(2021, 1, 1)
    rows: list[dict[str, object]] = []
    for asset, scale in (("BTC", 1.0), ("ETH", 0.05)):
        for i, close in enumerate(closes):
            c = float(close) * scale
            rows.append(
                {
                    "asset": asset,
                    "day": start + timedelta(days=i),
                    "open": c,
                    "high": c * 1.01,
                    "low": c * 0.99,
                    "close": c,
                    "volume": 1.0,
                    "fear_greed": 50,
                    "funding_rate": 0.0,
                }
            )
    return MarketData.from_frame(pl.DataFrame(rows, schema=SCHEMA))


@pytest.fixture(scope="module")
def model() -> RegimeModel:
    return RegimeModel.fit(regime_features(regime_market()), seed=0)


def test_features_only_use_the_past() -> None:
    market = regime_market()
    full = regime_features(market)
    changed = regime_market(segments=(SEGMENTS[0], SEGMENTS[0], SEGMENTS[0]))
    # Same seed and same first segment → identical history for the first SEGMENT_DAYS days.
    assert np.allclose(regime_features(changed)[:SEGMENT_DAYS], full[:SEGMENT_DAYS])
    assert full.shape == (len(market), 2)
    assert (full[0] == 0.0).all()


def test_labels_follow_the_segments(model: RegimeModel) -> None:
    labels = model.label(regime_features(regime_market()))

    # Skip a warm-up at each regime change; the filter needs a few days to switch.
    def majority(i: int) -> Regime:
        seg = labels[i * SEGMENT_DAYS + 20 : (i + 1) * SEGMENT_DAYS]
        return max(set(seg), key=seg.count)

    assert [majority(i) for i in range(3)] == [Regime.BULL, Regime.BEAR, Regime.SIDEWAYS]


def test_labels_are_prefix_invariant(model: RegimeModel) -> None:
    """No look-ahead: day t's label is the same whether or not later days exist."""
    features = regime_features(regime_market())
    full = model.label(features)
    for t in (5, 79, 120, 200):
        assert model.label(features[: t + 1])[-1] == full[t]


def test_future_data_does_not_change_past_labels(model: RegimeModel) -> None:
    base = model.label(regime_features(regime_market()))
    other = model.label(
        regime_features(regime_market(segments=(SEGMENTS[0], (0.05, 0.1), (-0.05, 0.1))))
    )
    assert other[:SEGMENT_DAYS] == base[:SEGMENT_DAYS]


def test_filtered_probabilities_are_distributions(model: RegimeModel) -> None:
    proba = model.filtered_proba(regime_features(regime_market()))
    assert np.allclose(proba.sum(axis=1), 1.0)
    assert (proba >= 0).all()


def test_every_regime_is_labelled_once(model: RegimeModel) -> None:
    assert sorted(model.labels) == sorted(Regime)


def test_artifact_roundtrip(model: RegimeModel, tmp_path: Path) -> None:
    path = tmp_path / "regime-hmm.json"
    digest = model.save(path)
    assert len(digest) == 64
    loaded = RegimeModel.load(path)
    features = regime_features(regime_market())
    assert loaded.label(features) == model.label(features)


def test_incompatible_artifact_is_rejected(model: RegimeModel) -> None:
    raw = model.to_json().replace('"version": 1', '"version": 99')
    with pytest.raises(ValueError, match="incompatible"):
        RegimeModel.from_json(raw)
