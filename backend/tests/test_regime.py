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
from pydantic import SecretStr

from mindex.config import Settings
from mindex.data.snapshot import SCHEMA
from mindex.domain.regime import Regime
from mindex.regime import hmm as hmm_module
from mindex.regime.hmm import (
    TREND_WINDOW,
    WINDOW,
    Labeling,
    RegimeModel,
    features_of,
    ranking_values,
    regime_features,
    stationary_distribution,
    trailing_log_return,
    warmup_of,
)
from mindex.services.runner import regime_labels, regime_provenance
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


@pytest.fixture(scope="module", params=list(Labeling), ids=str)
def model(request: pytest.FixtureRequest) -> RegimeModel:
    """One model per labeling: every test that takes it runs for each method."""
    return RegimeModel.fit_market(regime_market(), cast(Labeling, request.param), seed=0)


def test_features_only_use_the_past() -> None:
    market = regime_market()
    full = regime_features(market)
    changed = regime_market(segments=(SEGMENTS[0], SEGMENTS[0], SEGMENTS[0]))
    # Same seed and same first segment → identical history for the first SEGMENT_DAYS days.
    assert np.allclose(regime_features(changed)[:SEGMENT_DAYS], full[:SEGMENT_DAYS])
    assert full.shape == (len(market), 2)
    assert (full[0] == 0.0).all()
    with_trend = regime_features(market, Labeling.TREND_30)
    assert with_trend.shape == (len(market), 3)
    assert np.array_equal(with_trend[:, :2], full)  # the shared columns are the default ones
    changed_trend = regime_features(changed, Labeling.TREND_30)
    assert np.allclose(changed_trend[:SEGMENT_DAYS], with_trend[:SEGMENT_DAYS])
    assert not np.allclose(changed_trend[SEGMENT_DAYS:], with_trend[SEGMENT_DAYS:])
    basket = hmm_module.basket_log_returns(market)
    t = 50
    assert with_trend[t, 2] == pytest.approx(basket[t - TREND_WINDOW + 1 : t + 1].mean())


def test_trailing_log_return_reads_only_the_past() -> None:
    log_ret = np.array([0.0, 0.1, -0.2, 0.3, 0.4])
    out = trailing_log_return(log_ret, 2)
    assert np.isnan(out[:2]).all()
    assert np.allclose(out[2:], [-0.1, 0.1, 0.7])
    assert np.isnan(trailing_log_return(log_ret, 5)).all()
    ranks = ranking_values(regime_market(), Labeling.RETURN_60)
    assert ranks is not None
    assert np.isnan(ranks[:60]).all()
    assert np.isfinite(ranks[60:]).all()
    assert ranking_values(regime_market(), Labeling.MOMENTUM) is None


def test_labels_follow_the_segments(model: RegimeModel) -> None:
    labels = model.label_market(regime_market())

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
    features = regime_features(regime_market(), model.labeling)
    full = model.filtered_proba(features)
    for t in range(len(features)):
        assert np.allclose(model.filtered_proba(features[: t + 1])[-1], full[t]), t
    labels = model.label(features)
    assert all(model.label(features[: t + 1])[-1] == labels[t] for t in range(len(features)))


def test_labels_are_the_argmax_of_the_filtered_proba(model: RegimeModel) -> None:
    """Labels must come from the filtered posterior, not from a separate Viterbi/smoothed path."""
    features = regime_features(regime_market(), model.labeling)
    expected = [model.labels[int(k)] for k in np.argmax(model.filtered_proba(features), axis=1)]
    assert model.label(features) == expected


def test_future_data_does_not_change_past_probabilities(model: RegimeModel) -> None:
    base = regime_features(regime_market(), model.labeling)
    changed = regime_features(
        regime_market(segments=(SEGMENTS[0], (0.05, 0.1), (-0.05, 0.1))), model.labeling
    )
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
    features = regime_features(regime_market(), model.labeling)
    x = (features - model.feature_mean) / model.feature_std
    ours = model.filtered_proba(features)
    for t in range(len(x)):
        expected = np.asarray(reference.predict_proba(x[: t + 1]))[-1]
        assert np.allclose(ours[t], expected, atol=1e-8), t


def test_filtered_probabilities_are_distributions(model: RegimeModel) -> None:
    proba = model.filtered_proba(regime_features(regime_market(), model.labeling))
    assert np.allclose(proba.sum(axis=1), 1.0)
    assert (proba >= 0).all()


def test_every_regime_is_labelled_once(model: RegimeModel) -> None:
    assert sorted(model.labels) == sorted(Regime)


def test_artifact_roundtrip(model: RegimeModel, tmp_path: Path) -> None:
    path = tmp_path / "regime-hmm.json"
    digest = model.save(path)
    assert len(digest) == 64
    loaded = RegimeModel.load(path)
    assert loaded.labeling == model.labeling
    assert loaded.label_market(regime_market()) == model.label_market(regime_market())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert (data["labeling"], data["features"]) == (
        str(model.labeling),
        list(features_of(model.labeling)),
    )


def test_incompatible_artifact_is_rejected(model: RegimeModel) -> None:
    raw = model.to_json().replace('"version": 3', '"version": 99')
    with pytest.raises(ValueError, match="incompatible"):
        RegimeModel.from_json(raw)


def test_version_2_artifact_asks_for_a_retrain(model: RegimeModel) -> None:
    """Artefacts from before `labeling` (v2, e.g. the model behind #50) are refused outright."""
    data = json.loads(model.to_json())
    data["version"] = 2
    del data["labeling"]
    with pytest.raises(ValueError, match=r"incompatible.*retrain"):
        RegimeModel.from_json(json.dumps(data))


def test_features_must_match_the_labeling(model: RegimeModel) -> None:
    data = json.loads(model.to_json())
    other = Labeling.MOMENTUM if model.labeling is Labeling.TREND_30 else Labeling.TREND_30
    data["labeling"] = str(other)  # the stored feature list now belongs to another method
    with pytest.raises(ValueError, match="incompatible"):
        RegimeModel.from_json(json.dumps(data))


def test_default_labeling_is_the_original_method() -> None:
    """`--labeling momentum` must reproduce the pre-v3 model: same features, same warm-up."""
    market = regime_market()
    assert features_of(Labeling.MOMENTUM) == hmm_module.FEATURES
    assert warmup_of(Labeling.MOMENTUM) == WINDOW
    assert np.array_equal(regime_features(market, Labeling.MOMENTUM), regime_features(market))
    default = RegimeModel.fit(regime_features(market), seed=0, restarts=3)
    assert default.labeling is Labeling.MOMENTUM
    # Ranked by the fitted mean momentum: bull highest, bear lowest.
    order = np.argsort(default.means[:, hmm_module.TREND])
    assert (default.labels[int(order[0])], default.labels[int(order[-1])]) == (
        Regime.BEAR,
        Regime.BULL,
    )


def test_fit_ignores_the_warm_up_rows(model: RegimeModel) -> None:
    market = regime_market()
    garbage = regime_features(market, model.labeling).copy()
    garbage[: warmup_of(model.labeling)] = 5.0  # partial-window features must not shape it
    refit = RegimeModel.fit(
        garbage, labeling=model.labeling, rank_by=ranking_values(market, model.labeling), seed=0
    )
    assert refit.to_json() == model.to_json()


# Calm rally, volatile flat, volatile crash: the calmest state is the rally, so `vol-first`
# names it sideways where the momentum ranking calls it bull.
CALM_RALLY = ((0.01, 0.003), (0.0, 0.03), (-0.02, 0.03))


def _majorities(labels: list[Regime]) -> list[Regime]:
    out: list[Regime] = []
    for i in range(3):
        seg = labels[i * SEGMENT_DAYS + 20 : (i + 1) * SEGMENT_DAYS]
        out.append(max(set(seg), key=seg.count))
    return out


def test_vol_first_names_the_calmest_state_sideways() -> None:
    market = regime_market(segments=CALM_RALLY)
    default = RegimeModel.fit_market(market, seed=0, restarts=4)
    vol_first = RegimeModel.fit_market(market, Labeling.VOL_FIRST, seed=0, restarts=4)
    assert _majorities(default.label_market(market)) == [
        Regime.BULL,
        Regime.SIDEWAYS,
        Regime.BEAR,
    ]
    assert _majorities(vol_first.label_market(market)) == [
        Regime.SIDEWAYS,
        Regime.BULL,
        Regime.BEAR,
    ]
    calm = int(np.argmin(vol_first.means[:, hmm_module.VOLATILITY]))
    assert vol_first.labels[calm] is Regime.SIDEWAYS


def test_return_60_ranks_by_the_given_trailing_return() -> None:
    """The ranking comes from `rank_by`, not from the fitted momentum: reversing it swaps bull
    and bear on the same fitted states."""
    market = regime_market()
    feats = regime_features(market, Labeling.RETURN_60)
    ranks = ranking_values(market, Labeling.RETURN_60)
    assert ranks is not None
    straight = RegimeModel.fit(feats, labeling=Labeling.RETURN_60, rank_by=ranks, seed=0)
    reversed_ = RegimeModel.fit(feats, labeling=Labeling.RETURN_60, rank_by=-ranks, seed=0)
    assert np.array_equal(straight.means, reversed_.means)
    swap = {Regime.BULL: Regime.BEAR, Regime.BEAR: Regime.BULL, Regime.SIDEWAYS: Regime.SIDEWAYS}
    assert reversed_.labels == tuple(swap[r] for r in straight.labels)
    # Only training days whose 60-day window is complete count.
    with pytest.raises(ValueError, match="rank by return"):
        RegimeModel.fit(
            feats, labeling=Labeling.RETURN_60, rank_by=np.full(len(feats), np.nan), seed=0
        )


def test_trend_30_ranks_by_the_trend_column() -> None:
    """Negating the 30-day trend (and nothing else) must flip which state is bull: the ranking
    reads the trend column, not the 14-day momentum."""
    feats = regime_features(regime_market(), Labeling.TREND_30)
    flipped = feats.copy()
    flipped[:, 2] = -flipped[:, 2]
    for fitted in (
        RegimeModel.fit(feats, labeling=Labeling.TREND_30, seed=0, restarts=3),
        RegimeModel.fit(flipped, labeling=Labeling.TREND_30, seed=0, restarts=3),
    ):
        assert fitted.labels[int(np.argmax(fitted.means[:, 2]))] is Regime.BULL
        assert fitted.labels[int(np.argmin(fitted.means[:, 2]))] is Regime.BEAR
    straight = RegimeModel.fit(feats, labeling=Labeling.TREND_30, seed=0, restarts=3)
    negated = RegimeModel.fit(flipped, labeling=Labeling.TREND_30, seed=0, restarts=3)
    # On the flipped series the trend now points against the momentum column.
    assert straight.label_market(regime_market()) != negated.label(flipped)


def test_fit_checks_the_inputs_of_its_labeling() -> None:
    market = regime_market()
    with pytest.raises(ValueError, match="needs the features"):
        RegimeModel.fit(regime_features(market), labeling=Labeling.TREND_30)
    with pytest.raises(ValueError, match="rank_by"):
        RegimeModel.fit(regime_features(market), labeling=Labeling.RETURN_60)


def test_runner_labels_with_the_artifacts_labeling(model: RegimeModel, tmp_path: Path) -> None:
    """The runner takes the labeling (and so the features) from the artefact and records it."""
    path = tmp_path / "regime.json"
    digest = model.save(path)
    settings = Settings(_env_file=None, jwt_secret=SecretStr("x" * 64), regime_model_path=path)  # pyright: ignore[reportCallIssue]
    market = regime_market()
    assert regime_labels(market, settings) == model.label_market(market)
    assert regime_provenance(settings) == {
        "regime_source": "hmm",
        "regime_sha256": digest,
        "regime_labeling": str(model.labeling),
    }
    placeholder = settings.model_copy(update={"regime_model_path": None})
    assert regime_provenance(placeholder)["regime_labeling"] is None


def test_forward_pass_starts_from_the_stationary_distribution(model: RegimeModel) -> None:
    pi = model.initial_proba
    assert np.allclose(pi @ model.transmat, pi)
    assert np.isclose(pi.sum(), 1.0)
    assert (pi > 0).all()  # the floored chain reaches every state
    features = regime_features(regime_market(), model.labeling)[:1]
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
        ("labeling", "random"),
    ],
)
def test_malformed_artifact_is_rejected(model: RegimeModel, key: str, value: object) -> None:
    data = json.loads(model.to_json())
    if key in ("means", "variances") and model.labeling is Labeling.TREND_30:
        value = [[*row, 1.0] for row in cast(list[list[float]], value)]  # the third feature
    data[key] = value
    with pytest.raises(ValueError, match="malformed"):
        RegimeModel.from_json(json.dumps(data))
