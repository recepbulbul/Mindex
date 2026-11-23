# hmmlearn ships no type stubs; its use is confined to `fit`, everything else is plain numpy.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Three-state Gaussian HMM over market-wide features, labelled bull / bear / sideways.

Look-ahead protocol:
- The model (feature scaler, HMM parameters, state → label map) is fitted on the training
  split only.
- Labels come from the *filtered* posterior P(s_t | x_1..x_t): a forward pass, so the label
  of day t never depends on anything after t. hmmlearn's `predict` (Viterbi) and
  `predict_proba` (forward-backward, smoothed) condition on the whole sequence and would leak
  the future, so they are deliberately not used for labelling.
- The first `warmup_of(labeling)` days are dropped before fitting: their features come from
  partial windows (day 0 is all zeros) and would otherwise pull a state towards the warm-up.
- The forward pass starts from the stationary distribution of the transition matrix, not
  hmmlearn's `startprob_`: on a single training sequence EM collapses `startprob_` to a
  one-hot on the first day's state, which says nothing about where another sequence starts.

Labels are relative: the fitted states are named by ranking them on the training data, so
"bull" is the highest-trend state of this model, not a fixed return threshold. A model refitted
on other data (or with another seed) may draw the boundaries elsewhere.

How the states are named is selectable (`Labeling`, `mindex train-hmm --labeling`) and stored in
the artefact, which is the only place the runner reads it from:
- `momentum` (default, the original method): features are 14-day momentum and volatility; the
  states are ranked by their mean momentum (lowest bear, highest bull, the middle sideways).
- `trend-30`: adds a 30-day trend (trailing mean daily log return) as a third feature and ranks
  the states by its mean; volatility is only a second axis for the HMM.
- `return-60`: the default features, but the states are ranked by the trailing 60-day basket
  return of the training days each state claims (weighted by the filtered posterior).
- `vol-first`: the default features; the calmest state (lowest mean volatility) is sideways and
  of the other two the higher-momentum one is bull, the lower bear. Every regime is still used
  exactly once, so two "moving" states with the same trend sign are still split bull / bear.

Every method fixes the state → label map once, at fit time, from training data only; labelling a
day still reads only the filtered posterior of that day, so none of them adds look-ahead.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from mindex.domain.regime import Regime
from mindex.sim.market import MarketData

N_STATES = 3
WINDOW = 14  # trailing days for momentum and realised volatility
TREND_WINDOW = 30  # trailing days of the `trend-30` feature
RANK_WINDOW = 60  # trailing days of the basket return `return-60` ranks the states by
FEATURES = ("basket_momentum", "basket_volatility")
TREND = FEATURES.index("basket_momentum")  # states are labelled by their mean trend
VOLATILITY = FEATURES.index("basket_volatility")
N_RESTARTS = 10  # EM finds local optima; keep the best of several initialisations
TRANSMAT_FLOOR = 1e-6  # keeps every transition possible, so log(transmat) stays finite
ARTIFACT_VERSION = 3  # 3: the artefact records its `labeling` and that labeling's features

FloatArray = NDArray[np.float64]


class Labeling(StrEnum):
    """How the fitted states are named bull / bear / sideways (see the module docstring)."""

    MOMENTUM = "momentum"
    TREND_30 = "trend-30"
    RETURN_60 = "return-60"
    VOL_FIRST = "vol-first"


def features_of(labeling: Labeling) -> tuple[str, ...]:
    """The HMM's observed features under `labeling`, in column order."""
    if labeling is Labeling.TREND_30:
        return (*FEATURES, f"basket_trend_{TREND_WINDOW}")
    return FEATURES


def warmup_of(labeling: Labeling) -> int:
    """Leading days whose features come from partial windows; dropped before fitting."""
    return TREND_WINDOW if labeling is Labeling.TREND_30 else WINDOW


def basket_log_returns(market: MarketData) -> FloatArray:
    """Daily log return of the equal-weight basket (mean of the assets' log returns); day 0 is 0."""
    closes = np.array([[b.close for b in market.bars[a]] for a in market.assets], dtype=float)
    log_ret = np.zeros_like(closes)
    log_ret[:, 1:] = np.log(closes[:, 1:] / closes[:, :-1])
    return log_ret.mean(axis=0)


def trailing_log_return(log_ret: FloatArray, days: int) -> FloatArray:
    """Sum of the `days` daily log returns ending on day t (inclusive), NaN until `days` returns
    exist (`log_ret[0]` is the placeholder 0 of day 0). Reads only the past."""
    out = np.full(len(log_ret), np.nan)
    if len(log_ret) > days:
        cumulative = np.cumsum(log_ret)
        out[days:] = cumulative[days:] - cumulative[:-days]
    return out


def regime_features(market: MarketData, labeling: Labeling = Labeling.MOMENTUM) -> FloatArray:
    """Per day: trailing mean (momentum) and realised volatility of the equal-weight basket's
    daily log returns over `WINDOW` days; `trend-30` adds the trailing mean over `TREND_WINDOW`
    days as a third column.

    All use only closes up to and including that day; day 0 has no return, so all are 0.
    Raw daily returns are too noisy to tell a calm rally from a calm drift (the HMM spends a
    state on the spread of crash days instead); the trailing mean separates trends and the
    volatility separates calm from turbulent markets.
    """
    basket = basket_log_returns(market)
    momentum = np.zeros_like(basket)
    vol = np.zeros_like(basket)
    for t in range(1, len(basket)):
        window = basket[max(1, t - WINDOW + 1) : t + 1]
        momentum[t] = float(window.mean())
        vol[t] = float(window.std()) if len(window) > 1 else 0.0
    if labeling is not Labeling.TREND_30:
        return np.column_stack([momentum, vol])
    trend = np.zeros_like(basket)
    for t in range(1, len(basket)):
        trend[t] = float(basket[max(1, t - TREND_WINDOW + 1) : t + 1].mean())
    return np.column_stack([momentum, vol, trend])


def ranking_values(market: MarketData, labeling: Labeling) -> FloatArray | None:
    """What `RegimeModel.fit` ranks the states by when it is not a fitted feature: the trailing
    `RANK_WINDOW`-day basket log return for `return-60`, else None."""
    if labeling is not Labeling.RETURN_60:
        return None
    return trailing_log_return(basket_log_returns(market), RANK_WINDOW)


def stationary_distribution(transmat: FloatArray) -> FloatArray:
    """π with π A = π and Σπ = 1; unique because the floored matrix is strictly positive."""
    k = transmat.shape[0]
    system = np.vstack([transmat.T - np.eye(k), np.ones((1, k))])
    target = np.zeros(k + 1)
    target[-1] = 1.0
    pi = np.clip(np.linalg.lstsq(system, target, rcond=None)[0], 0.0, None)
    return pi / pi.sum()


def _floor_transmat(transmat: FloatArray) -> FloatArray:
    floored = np.maximum(transmat, TRANSMAT_FLOOR)
    return floored / floored.sum(axis=1, keepdims=True)


def _converged(history: Any, tol: float) -> bool:
    """EM stopped because the log-likelihood gain fell below `tol`, not because it ran out of
    iterations (hmmlearn's own `converged` also counts hitting `n_iter` as converged)."""
    h = [float(v) for v in history]
    return len(h) >= 2 and math.isfinite(h[-1]) and h[-1] - h[-2] < tol


def _log_gaussian(x: FloatArray, means: FloatArray, variances: FloatArray) -> FloatArray:
    """log N(x_t | mean_k, diag(var_k)) for every day t and state k → shape (T, K)."""
    diff = x[:, None, :] - means[None, :, :]
    return -0.5 * (
        np.sum(diff**2 / variances[None, :, :], axis=2)
        + np.sum(np.log(2 * math.pi * variances), axis=1)[None, :]
    )


def _logsumexp(a: FloatArray, axis: int) -> FloatArray:
    m = np.max(a, axis=axis, keepdims=True)
    return np.squeeze(m, axis=axis) + np.log(np.sum(np.exp(a - m), axis=axis))


def _ranked(score: FloatArray, labels: list[Regime], states: list[int]) -> None:
    """Name `states` by `score`: lowest bear, highest bull, any state in between sideways."""
    order = sorted(states, key=lambda k: float(score[k]))
    labels[order[0]] = Regime.BEAR
    labels[order[-1]] = Regime.BULL


@dataclass(frozen=True, slots=True)
class RegimeModel:
    feature_mean: FloatArray
    feature_std: FloatArray
    transmat: FloatArray  # floored at TRANSMAT_FLOOR, rows sum to 1
    means: FloatArray  # in scaled feature space, shape (K, F)
    variances: FloatArray  # diagonal covariances, shape (K, F)
    labels: tuple[Regime, ...]  # labels[k] is the regime of hidden state k
    labeling: Labeling = Labeling.MOMENTUM  # how `labels` were chosen; fixes the features

    @classmethod
    def fit(
        cls,
        features: FloatArray,
        *,
        labeling: Labeling = Labeling.MOMENTUM,
        rank_by: FloatArray | None = None,
        seed: int = 0,
        n_iter: int = 200,
        restarts: int = N_RESTARTS,
    ) -> "RegimeModel":
        """Fit on training-period features only (the caller is responsible for the split).

        `features` are `regime_features(market, labeling)`; `rank_by` is
        `ranking_values(market, labeling)`, aligned with them (needed by `return-60` only).
        The first `warmup_of(labeling)` rows (indicator warm-up) are dropped. Runs EM from
        `restarts` initialisations (seeds `seed*1000`, `seed*1000+1`, ...) and keeps the
        converged one with the highest finite training log-likelihood, so the result is
        deterministic per `seed`.
        """
        from hmmlearn.hmm import GaussianHMM  # heavy import, only needed to train

        if restarts < 1:
            raise ValueError("restarts must be at least 1")
        if features.ndim != 2 or features.shape[1] != len(features_of(labeling)):
            raise ValueError(f"{labeling} needs the features {features_of(labeling)}")
        if labeling is Labeling.RETURN_60 and (rank_by is None or len(rank_by) != len(features)):
            raise ValueError("return-60 needs rank_by aligned with the features")
        warmup = warmup_of(labeling)
        features = features[warmup:]
        if len(features) <= N_STATES:
            raise ValueError(f"need more than {warmup + N_STATES} days of features to fit")
        mean = features.mean(axis=0)
        std = features.std(axis=0)
        std[std == 0] = 1.0
        scaled = (features - mean) / std
        best: GaussianHMM | None = None
        best_score = -math.inf
        for k in range(restarts):
            candidate = GaussianHMM(
                n_components=N_STATES,
                covariance_type="diag",
                n_iter=n_iter,
                random_state=seed * 1000 + k,
            )
            try:
                candidate.fit(scaled)
                score = float(candidate.score(scaled))
            except ValueError:  # degenerate EM, e.g. a state that collects no days at all
                continue
            monitor = candidate.monitor_
            if not math.isfinite(score) or not _converged(monitor.history, monitor.tol):
                continue
            if score > best_score:
                best, best_score = candidate, score
        if best is None:
            raise ValueError(
                f"no HMM restart converged to a finite log-likelihood "
                f"(restarts={restarts}, n_iter={n_iter}); raise n_iter or check the features"
            )
        hmm = best
        means = np.asarray(hmm.means_, dtype=float)
        covars = np.asarray(hmm.covars_, dtype=float)  # (K, F, F) even for "diag"
        variances = np.array([np.diag(c) for c in covars], dtype=float)
        transmat = _floor_transmat(np.asarray(hmm.transmat_, dtype=float))
        labels: list[Regime] = [Regime.SIDEWAYS] * N_STATES
        states = list(range(N_STATES))
        if labeling is Labeling.MOMENTUM:
            _ranked(means[:, TREND], labels, states)
        elif labeling is Labeling.TREND_30:
            _ranked(means[:, -1], labels, states)
        elif labeling is Labeling.VOL_FIRST:
            calm = int(np.argmin(means[:, VOLATILITY]))
            _ranked(means[:, TREND], labels, [k for k in states if k != calm])
        else:  # RETURN_60: rank by the trailing return of the training days each state claims
            unnamed = cls(mean, std, transmat, means, variances, tuple(labels), labeling)
            weights = unnamed.filtered_proba(features)  # filtered: P(state_t | days up to t)
            values = cast(FloatArray, rank_by)[warmup:]  # checked above
            known = np.isfinite(values)
            if not known.any():
                raise ValueError(f"need more than {RANK_WINDOW} training days to rank by return")
            w = weights[known]
            _ranked((w * values[known, None]).sum(axis=0) / w.sum(axis=0), labels, states)
        return cls(mean, std, transmat, means, variances, tuple(labels), labeling)

    @classmethod
    def fit_market(
        cls, market: MarketData, labeling: Labeling = Labeling.MOMENTUM, **kwargs: Any
    ) -> "RegimeModel":
        """`fit` on a training-period market, with the inputs `labeling` needs."""
        return cls.fit(
            regime_features(market, labeling),
            labeling=labeling,
            rank_by=ranking_values(market, labeling),
            **kwargs,
        )

    @property
    def initial_proba(self) -> FloatArray:
        """Prior for the first day of any sequence: the chain's long-run state shares."""
        return stationary_distribution(self.transmat)

    def filtered_proba(self, features: FloatArray) -> FloatArray:
        """P(state_t | x_1..x_t) for every day: the forward algorithm in log space."""
        x = (features - self.feature_mean) / self.feature_std
        log_b = _log_gaussian(x, self.means, self.variances)
        log_a = np.log(self.transmat)
        alpha = np.empty_like(log_b)
        alpha[0] = np.log(self.initial_proba) + log_b[0]
        alpha[0] -= _logsumexp(alpha[0][None, :], axis=1)
        for t in range(1, len(x)):
            prior = _logsumexp(alpha[t - 1][:, None] + log_a, axis=0)
            alpha[t] = prior + log_b[t]
            alpha[t] -= _logsumexp(alpha[t][None, :], axis=1)  # normalise each step
        return np.exp(alpha)

    def label(self, features: FloatArray) -> list[Regime]:
        """Most probable regime per day under the filtered posterior. Labels are relative to
        this model's states (see the module docstring), not absolute market thresholds."""
        states = np.argmax(self.filtered_proba(features), axis=1)
        return [self.labels[int(k)] for k in states]

    def label_market(self, market: MarketData) -> list[Regime]:
        """`label` on the features of this model's own `labeling` (what the runner calls)."""
        return self.label(regime_features(market, self.labeling))

    # ---------------------------------------------------------------- persistence
    # JSON, not pickle: loading a model file must never execute code.

    def to_json(self) -> str:
        data = {
            "version": ARTIFACT_VERSION,
            "labeling": str(self.labeling),
            "features": list(features_of(self.labeling)),
            "window": WINDOW,
            "feature_mean": self.feature_mean.tolist(),
            "feature_std": self.feature_std.tolist(),
            "transmat": self.transmat.tolist(),
            "means": self.means.tolist(),
            "variances": self.variances.tolist(),
            "labels": [str(r) for r in self.labels],
        }
        return json.dumps(data, indent=2) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "RegimeModel":
        data = cast(dict[str, Any], json.loads(raw))
        if data.get("version") != ARTIFACT_VERSION:
            raise ValueError(
                f"regime model artifact was built by an incompatible version "
                f"({data.get('version')!r}, expected {ARTIFACT_VERSION}); "
                "retrain it with `mindex train-hmm --labeling ...`"
            )
        try:
            labeling = Labeling(data.get("labeling"))
        except ValueError as exc:
            raise ValueError("regime model artifact is malformed: labeling") from exc
        if data.get("features") != list(features_of(labeling)) or data.get("window") != WINDOW:
            raise ValueError("regime model artifact was built by an incompatible version")

        def arr(key: str, shape: tuple[int, ...]) -> FloatArray:
            try:
                value = np.asarray(data[key], dtype=float)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"regime model artifact is malformed: {key}") from exc
            if value.shape != shape or not np.isfinite(value).all():
                raise ValueError(f"regime model artifact is malformed: {key}")
            return value

        n_features = len(features_of(labeling))
        feature_mean = arr("feature_mean", (n_features,))
        feature_std = arr("feature_std", (n_features,))
        transmat = arr("transmat", (N_STATES, N_STATES))
        means = arr("means", (N_STATES, n_features))
        variances = arr("variances", (N_STATES, n_features))
        if (feature_std <= 0).any() or (variances <= 0).any():
            raise ValueError("regime model artifact is malformed: non-positive scale")
        if (transmat <= 0).any() or not np.allclose(transmat.sum(axis=1), 1.0):
            raise ValueError("regime model artifact is malformed: transmat")
        try:
            labels = tuple(Regime(r) for r in cast(list[str], data["labels"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("regime model artifact is malformed: labels") from exc
        if sorted(labels) != sorted(Regime):
            raise ValueError("regime model artifact is malformed: labels")
        return cls(feature_mean, feature_std, transmat, means, variances, labels, labeling)

    def save(self, path: Path) -> str:
        """Write the artifact and return its SHA-256 (recorded with experiments for NF5)."""
        raw = self.to_json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8", newline="\n")
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def load(cls, path: Path) -> "RegimeModel":
        return cls.from_json(path.read_text(encoding="utf-8"))
