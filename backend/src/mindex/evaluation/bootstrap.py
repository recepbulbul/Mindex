"""Condition comparison of a study: mean Sharpe of LLM agents with a block-bootstrap 95% CI.

Daily returns are serially dependent (volatility clusters), so days are not resampled one by
one: a circular block bootstrap (Politis & Romano, 1992) draws blocks of `block` consecutive
days, wrapping at the end, until `n` days are filled. One draw of day indices is applied to
every series of every condition, so the cross-sectional dependence (agents trade the same
market, conditions share the same days) is kept and a difference of two conditions is a
paired statistic. The CI is the 2.5 / 97.5 percentile of the resampled statistic.

The block length defaults to round(n ** (1/3)) (the usual rate for the bias of the variance
estimate), the number of resamples to 2000, and the generator is seeded, so a CI reproduces
exactly. Sharpe here is `domain.metrics.sharpe_ratio` (annualised, sample std, 0 when flat).
"""

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from mindex.domain.metrics import CRYPTO_PERIODS_PER_YEAR

RESAMPLES = 2000
SEED = 54  # fixed: the CI of a study is reproducible (#54)
CI = 0.95

Matrix = npt.NDArray[np.float64]


def block_length(n: int) -> int:
    return max(1, round(n ** (1 / 3)))


def block_indices(n: int, block: int, rng: random.Random) -> list[int]:
    """Day indices of one circular block-bootstrap resample of `n` days."""
    if n < 1 or block < 1:
        raise ValueError("n and block must be positive")
    out: list[int] = []
    while len(out) < n:
        start = rng.randrange(n)
        out.extend((start + k) % n for k in range(block))
    return out[:n]


def mean_sharpe(returns: Matrix) -> Matrix:
    """Mean annualised Sharpe over series (rows of the last-but-one axis).

    `returns` has shape (..., series, days); the result drops the last two axes."""
    mu = returns.mean(axis=-1)
    sd = returns.std(axis=-1, ddof=1)
    safe = np.where(sd > 0, sd, 1.0)
    sharpe = np.where(sd > 0, mu / safe * math.sqrt(CRYPTO_PERIODS_PER_YEAR), 0.0)
    return sharpe.mean(axis=-1)


def percentile_ci(samples: Sequence[float], level: float = CI) -> tuple[float, float]:
    """Linear-interpolation percentiles (numpy's default) of the central `level` share."""
    tail = (1 - level) / 2 * 100
    lo, hi = np.percentile(np.asarray(samples, dtype=np.float64), [tail, 100 - tail])
    return float(lo), float(hi)


@dataclass(frozen=True, slots=True)
class Estimate:
    value: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True, slots=True)
class Bootstrap:
    days: int
    block: int
    resamples: int
    sharpe: dict[str, Estimate]  # per group (condition)
    differences: dict[tuple[str, str], Estimate]  # (group, baseline) -> group - baseline


def bootstrap_sharpe(
    groups: Mapping[str, Sequence[Sequence[float]]],
    pairs: Sequence[tuple[str, str]] = (),
    *,
    resamples: int = RESAMPLES,
    seed: int = SEED,
    block: int | None = None,
) -> Bootstrap:
    """Mean Sharpe per group of daily-return series (all of the same length) with its CI, and
    the paired CI of `group - baseline` for each pair whose groups both exist."""
    if not groups:
        raise ValueError("no groups")
    arrays = {g: np.asarray(series, dtype=np.float64) for g, series in groups.items()}
    lengths = {a.shape[-1] for a in arrays.values()}
    if len(lengths) != 1 or any(a.ndim != 2 or a.shape[0] == 0 for a in arrays.values()):
        raise ValueError("every group needs series of one common length")
    n = lengths.pop()
    if n < 2:
        raise ValueError("need at least two days")
    size = block or block_length(n)
    rng = random.Random(seed)  # noqa: S311 (resampling, not cryptography)
    idx = np.asarray([block_indices(n, size, rng) for _ in range(resamples)], dtype=np.intp)
    point = {g: float(mean_sharpe(a)) for g, a in arrays.items()}
    # (resamples,) per group: every group sees the same resampled days.
    draws = {g: mean_sharpe(np.swapaxes(a[:, idx], 0, 1)) for g, a in arrays.items()}
    sharpe = {g: Estimate(point[g], *percentile_ci(draws[g].tolist())) for g in arrays}
    differences = {
        (g, b): Estimate(point[g] - point[b], *percentile_ci((draws[g] - draws[b]).tolist()))
        for g, b in pairs
        if g in arrays and b in arrays
    }
    return Bootstrap(n, size, resamples, sharpe, differences)
