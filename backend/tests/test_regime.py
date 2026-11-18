# hmmlearn ships no type stubs; the reference test builds a GaussianHMM directly.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import ClassVar, cast

import numpy as np
import polars as pl
import pytest
from hmmlearn.hmm import GaussianHMM

from mindex.data.snapshot import SCHEMA
from mindex.domain.regime import Regime
from mindex.regime import hmm as hmm_module
from mindex.regime.hmm import WINDOW, RegimeModel, regime_features, stationary_distribution
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


def test_filtered_proba_is_prefix_invariant(model: RegimeModel) -> None:
    """No look-ahead: day t's probabilities are the same whether or not later days exist.

    Compares probabilities (not argmax labels) at every t, so a switch to smoothed
    forward-backward or Viterbi output is caught even where the argmax happens to agree.
    """
    features = regime_features(regime_market())
    full = model.filtered_proba(features)
    for t in range(len(features)):
        assert np.allclose(model.filtered_proba(features[: t + 1])[-1], full[t]), t
    labels = model.label(features)
    assert all(model.label(features[: t + 1])[-1] == labels[t] for t in range(len(features)))


def test_labels_are_the_argmax_of_the_filtered_proba(model: RegimeModel) -> None:
    """Labels must come from the filtered posterior, not from a separate Viterbi/smoothed path."""
    features = regime_features(regime_market())
    expected = [model.labels[int(k)] for k in np.argmax(model.filtered_proba(features), axis=1)]
    assert model.label(features) == expected


def test_future_data_does_not_change_past_probabilities(model: RegimeModel) -> None:
    base = regime_features(regime_market())
    changed = regime_features(regime_market(segments=(SEGMENTS[0], (0.05, 0.1), (-0.05, 0.1))))
    assert not np.allclose(changed[SEGMENT_DAYS:], base[SEGMENT_DAYS:])
    assert np.allclose(
        model.filtered_proba(changed)[:SEGMENT_DAYS], model.filtered_proba(base)[:SEGMENT_DAYS]
    )
    assert model.label(changed)[:SEGMENT_DAYS] == model.label(base)[:SEGMENT_DAYS]


def test_filtered_proba_matches_hmmlearn_prefix_reference(model: RegimeModel) -> None:
    """hmmlearn's smoothed posterior over x[:t+1] ends in the filtered posterior of day t."""
    reference = GaussianHMM(n_components=3, covariance_type="diag", init_params="", params="")
    reference.n_features = model.means.shape[1]
    reference.startprob_ = model.initial_proba
    reference.transmat_ = model.transmat
    reference.means_ = model.means
    reference.covars_ = model.variances
    features = regime_features(regime_market())
    x = (features - model.feature_mean) / model.feature_std
    ours = model.filtered_proba(features)
    for t in range(len(x)):
        expected = np.asarray(reference.predict_proba(x[: t + 1]))[-1]
        assert np.allclose(ours[t], expected, atol=1e-8), t


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
    raw = model.to_json().replace('"version": 2', '"version": 99')
    with pytest.raises(ValueError, match="incompatible"):
        RegimeModel.from_json(raw)


def test_fit_ignores_the_warm_up_rows(model: RegimeModel) -> None:
    features = regime_features(regime_market())
    garbage = features.copy()
    garbage[:WINDOW] = 5.0  # partial-window features must not shape the model
    assert RegimeModel.fit(garbage, seed=0).to_json() == model.to_json()


def test_forward_pass_starts_from_the_stationary_distribution(model: RegimeModel) -> None:
    pi = model.initial_proba
    assert np.allclose(pi @ model.transmat, pi)
    assert np.isclose(pi.sum(), 1.0)
    assert (pi > 0).all()  # the floored chain reaches every state
    features = regime_features(regime_market())[:1]
    x = (features - model.feature_mean) / model.feature_std
    likelihood = np.exp(hmm_module._log_gaussian(x, model.means, model.variances)[0])  # pyright: ignore[reportPrivateUsage]
    assert np.allclose(model.filtered_proba(features)[0], pi * likelihood / (pi * likelihood).sum())


def test_initial_proba_is_not_the_collapsed_startprob() -> None:
    """EM on one sequence drives startprob_ towards the first day's state; the stationary prior
    of a market that keeps switching regimes gives every state a real share instead."""
    features = regime_features(regime_market(segments=SEGMENTS * 2))
    model = RegimeModel.fit(features, seed=0, restarts=3)
    fitted = GaussianHMM(n_components=3, covariance_type="diag", random_state=0)
    fitted.fit((features[WINDOW:] - model.feature_mean) / model.feature_std)
    assert np.asarray(fitted.startprob_).min() < 1e-6  # a state ruled out on day 0
    assert model.initial_proba.min() > 0.05


def test_stationary_distribution_of_a_known_chain() -> None:
    transmat = np.array([[0.9, 0.1, 0.0], [0.5, 0.0, 0.5], [0.0, 0.2, 0.8]])
    pi = stationary_distribution(transmat)
    assert np.allclose(pi @ transmat, pi)
    assert np.isclose(pi.sum(), 1.0)


def test_transmat_is_floored_and_normalised(model: RegimeModel) -> None:
    assert (model.transmat >= hmm_module.TRANSMAT_FLOOR / 2).all()
    assert np.allclose(model.transmat.sum(axis=1), 1.0)
    floored = hmm_module._floor_transmat(np.array([[1.0, 0.0], [0.0, 1.0]]))  # pyright: ignore[reportPrivateUsage]
    assert (floored > 0).all()
    assert np.allclose(floored.sum(axis=1), 1.0)


def test_fit_is_deterministic() -> None:
    features = regime_features(regime_market())
    assert (
        RegimeModel.fit(features, seed=4, restarts=3).to_json()
        == RegimeModel.fit(features, seed=4, restarts=3).to_json()
    )


class _RecordingHMM(GaussianHMM):
    seeds: ClassVar[list[int]] = []

    def __init__(self, **kwargs: object) -> None:
        _RecordingHMM.seeds.append(int(cast(int, kwargs["random_state"])))
        super().__init__(**kwargs)  # pyright: ignore[reportArgumentType]


class _NaNScoreHMM(GaussianHMM):
    def score(self, X: object, lengths: object = None) -> float:  # noqa: N803
        return math.nan


class _DegenerateHMM(GaussianHMM):
    def fit(self, X: object, lengths: object = None) -> "_DegenerateHMM":  # noqa: N803
        raise ValueError("transmat_ rows must sum to 1")


def test_seed_selects_disjoint_restart_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    import hmmlearn.hmm

    monkeypatch.setattr(hmmlearn.hmm, "GaussianHMM", _RecordingHMM)
    _RecordingHMM.seeds = []
    features = regime_features(regime_market())
    RegimeModel.fit(features, seed=0, restarts=2)
    RegimeModel.fit(features, seed=3, restarts=2)
    assert _RecordingHMM.seeds == [0, 1, 3000, 3001]


def test_unusable_candidates_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    import hmmlearn.hmm

    features = regime_features(regime_market())
    with pytest.raises(ValueError, match="at least 1"):
        RegimeModel.fit(features, restarts=0)
    with pytest.raises(ValueError, match="converged"):
        RegimeModel.fit(features, n_iter=1, restarts=2)  # EM stopped by the iteration cap
    monkeypatch.setattr(hmmlearn.hmm, "GaussianHMM", _NaNScoreHMM)
    with pytest.raises(ValueError, match="finite log-likelihood"):
        RegimeModel.fit(features, restarts=2)
    monkeypatch.setattr(hmmlearn.hmm, "GaussianHMM", _DegenerateHMM)
    with pytest.raises(ValueError, match="no HMM restart converged"):
        RegimeModel.fit(features, restarts=2)


def test_too_short_training_data_is_rejected() -> None:
    with pytest.raises(ValueError, match="days of features"):
        RegimeModel.fit(np.zeros((WINDOW + 2, 2)))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("means", [[math.nan, 0.0], [0.0, 0.0], [1.0, 1.0]]),
        ("transmat", [[1.0]]),
        ("transmat", [[0.5, 0.5, 0.5]] * 3),
        ("variances", [[1.0, 1.0], [1.0, 0.0], [1.0, 1.0]]),
        ("feature_std", "abc"),
        ("labels", ["bull", "bull", "bear"]),
        ("labels", ["bull", "bear", "flat"]),
    ],
)
def test_malformed_artifact_is_rejected(model: RegimeModel, key: str, value: object) -> None:
    data = json.loads(model.to_json())
    data[key] = value
    with pytest.raises(ValueError, match="malformed"):
        RegimeModel.from_json(json.dumps(data))
