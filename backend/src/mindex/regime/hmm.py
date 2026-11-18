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
"""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from mindex.domain.regime import Regime
from mindex.sim.market import MarketData

N_STATES = 3
WINDOW = 14  # trailing days for momentum and realised volatility
FEATURES = ("basket_momentum", "basket_volatility")
TREND = FEATURES.index("basket_momentum")  # states are labelled by their mean trend
N_RESTARTS = 10  # EM finds local optima; keep the best of several initialisations
ARTIFACT_VERSION = 1

FloatArray = NDArray[np.float64]


def regime_features(market: MarketData) -> FloatArray:
    """Per day: trailing mean (momentum) and realised volatility of the equal-weight basket's
    daily log returns over `WINDOW` days.

    Both use only closes up to and including that day; day 0 has no return, so both are 0.
    Raw daily returns are too noisy to tell a calm rally from a calm drift (the HMM spends a
    state on the spread of crash days instead); the trailing mean separates trends and the
    volatility separates calm from turbulent markets.
    """
    closes = np.array([[b.close for b in market.bars[a]] for a in market.assets], dtype=float)
    log_ret = np.zeros_like(closes)
    log_ret[:, 1:] = np.log(closes[:, 1:] / closes[:, :-1])
    basket = log_ret.mean(axis=0)
    momentum = np.zeros_like(basket)
    vol = np.zeros_like(basket)
    for t in range(1, len(basket)):
        window = basket[max(1, t - WINDOW + 1) : t + 1]
        momentum[t] = float(window.mean())
        vol[t] = float(window.std()) if len(window) > 1 else 0.0
    return np.column_stack([momentum, vol])


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


@dataclass(frozen=True, slots=True)
class RegimeModel:
    feature_mean: FloatArray
    feature_std: FloatArray
    startprob: FloatArray
    transmat: FloatArray
    means: FloatArray  # in scaled feature space, shape (K, F)
    variances: FloatArray  # diagonal covariances, shape (K, F)
    labels: tuple[Regime, ...]  # labels[k] is the regime of hidden state k

    @classmethod
    def fit(
        cls,
        features: FloatArray,
        *,
        seed: int = 0,
        n_iter: int = 200,
        restarts: int = N_RESTARTS,
    ) -> "RegimeModel":
        """Fit on training-period features only (the caller is responsible for the split).

        Runs EM from `restarts` initialisations (seeds `seed`, `seed+1`, ...) and keeps the one
        with the highest training log-likelihood, so the result is deterministic per `seed`.
        """
        from hmmlearn.hmm import GaussianHMM  # heavy import, only needed to train

        mean = features.mean(axis=0)
        std = features.std(axis=0)
        std[std == 0] = 1.0
        scaled = (features - mean) / std
        best: GaussianHMM | None = None
        best_score = -math.inf
        for k in range(restarts):
            candidate = GaussianHMM(
                n_components=N_STATES, covariance_type="diag", n_iter=n_iter, random_state=seed + k
            )
            candidate.fit(scaled)
            score = float(candidate.score(scaled))
            if score > best_score:
                best, best_score = candidate, score
        if best is None:
            raise ValueError("restarts must be at least 1")
        hmm = best
        means = np.asarray(hmm.means_, dtype=float)
        # Highest mean trend → bull, lowest → bear, the remaining state → sideways.
        order = np.argsort(means[:, TREND])
        labels: list[Regime] = [Regime.SIDEWAYS] * N_STATES
        labels[int(order[0])] = Regime.BEAR
        labels[int(order[-1])] = Regime.BULL
        covars = np.asarray(hmm.covars_, dtype=float)  # (K, F, F) even for "diag"
        variances = np.array([np.diag(c) for c in covars], dtype=float)
        return cls(
            mean,
            std,
            np.asarray(hmm.startprob_, dtype=float),
            np.asarray(hmm.transmat_, dtype=float),
            means,
            variances,
            tuple(labels),
        )

    def filtered_proba(self, features: FloatArray) -> FloatArray:
        """P(state_t | x_1..x_t) for every day: the forward algorithm in log space."""
        x = (features - self.feature_mean) / self.feature_std
        log_b = _log_gaussian(x, self.means, self.variances)
        log_a = np.log(self.transmat)
        alpha = np.empty_like(log_b)
        alpha[0] = np.log(self.startprob) + log_b[0]
        alpha[0] -= _logsumexp(alpha[0][None, :], axis=1)
        for t in range(1, len(x)):
            prior = _logsumexp(alpha[t - 1][:, None] + log_a, axis=0)
            alpha[t] = prior + log_b[t]
            alpha[t] -= _logsumexp(alpha[t][None, :], axis=1)  # normalise each step
        return np.exp(alpha)

    def label(self, features: FloatArray) -> list[Regime]:
        states = np.argmax(self.filtered_proba(features), axis=1)
        return [self.labels[int(k)] for k in states]

    # ---------------------------------------------------------------- persistence
    # JSON, not pickle: loading a model file must never execute code.

    def to_json(self) -> str:
        data = {
            "version": ARTIFACT_VERSION,
            "features": list(FEATURES),
            "window": WINDOW,
            "feature_mean": self.feature_mean.tolist(),
            "feature_std": self.feature_std.tolist(),
            "startprob": self.startprob.tolist(),
            "transmat": self.transmat.tolist(),
            "means": self.means.tolist(),
            "variances": self.variances.tolist(),
            "labels": [str(r) for r in self.labels],
        }
        return json.dumps(data, indent=2) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "RegimeModel":
        data = cast(dict[str, Any], json.loads(raw))
        if (
            data.get("features") != list(FEATURES)
            or data.get("version") != ARTIFACT_VERSION
            or data.get("window") != WINDOW
        ):
            raise ValueError("regime model artifact was built by an incompatible version")

        def arr(key: str) -> FloatArray:
            return np.asarray(data[key], dtype=float)

        labels = tuple(Regime(r) for r in cast(list[str], data["labels"]))
        return cls(
            arr("feature_mean"),
            arr("feature_std"),
            arr("startprob"),
            arr("transmat"),
            arr("means"),
            arr("variances"),
            labels,
        )

    def save(self, path: Path) -> str:
        """Write the artifact and return its SHA-256 (recorded with experiments for NF5)."""
        raw = self.to_json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8", newline="\n")
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def load(cls, path: Path) -> "RegimeModel":
        return cls.from_json(path.read_text(encoding="utf-8"))
