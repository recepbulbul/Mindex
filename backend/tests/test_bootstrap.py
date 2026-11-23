"""Block bootstrap of the condition comparison: small cases worked out by hand."""

# Seeded generators drive resampling here, not cryptography.
# ruff: noqa: S311

import math
import random

import numpy as np
import pytest

from mindex.domain.metrics import sharpe_ratio
from mindex.evaluation.bootstrap import (
    block_indices,
    block_length,
    bootstrap_sharpe,
    mean_sharpe,
    percentile_ci,
)


class Starts(random.Random):
    """A generator whose `randrange` returns the given block starts in turn."""

    def __init__(self, starts: list[int]) -> None:
        super().__init__(0)
        self.starts = iter(starts)

    def randrange(self, *_: object, **__: object) -> int:  # type: ignore[override]
        return next(self.starts)


def test_block_length_is_the_cube_root_rule() -> None:
    assert block_length(182) == 6  # 182 ** (1/3) = 5.67, the validation half-year
    assert block_length(14) == 2  # a smoke run
    assert block_length(1) == 1


def test_blocks_wrap_around_and_are_cut_to_n() -> None:
    # n = 5, blocks of 2 starting at 4, 1, 3: (4, 0), (1, 2), (3, 4) -> first five.
    assert block_indices(5, 2, Starts([4, 1, 3])) == [4, 0, 1, 2, 3]
    assert block_indices(3, 1, Starts([2, 2, 0])) == [2, 2, 0]
    with pytest.raises(ValueError, match="positive"):
        block_indices(0, 2, random.Random(1))


def test_mean_sharpe_by_hand() -> None:
    # mean 0.0066667, sample sd 0.0152753 -> 0.436436 * sqrt(365) = 8.3381
    r = [0.01, -0.01, 0.02]
    assert float(mean_sharpe(np.asarray([r]))) == pytest.approx(8.3381, abs=1e-4)
    assert float(mean_sharpe(np.asarray([r]))) == pytest.approx(sharpe_ratio(r))
    # The mean over series; a flat series counts as 0 (as `sharpe_ratio`).
    both = np.asarray([r, [0.0, 0.0, 0.0]])
    assert float(mean_sharpe(both)) == pytest.approx(8.3381 / 2, abs=1e-4)


def test_percentile_ci_interpolates() -> None:
    assert percentile_ci([float(x) for x in range(101)]) == pytest.approx((2.5, 97.5))
    assert percentile_ci([1.0, 2.0]) == pytest.approx((1.025, 1.975))


SERIES = [
    [0.01, -0.02, 0.015, 0.003, -0.004, 0.02, -0.01, 0.005],
    [0.002, 0.001, -0.003, 0.004, 0.0, -0.001, 0.006, -0.002],
]


def test_one_resample_is_the_statistic_on_those_days() -> None:
    """With one resample the CI collapses onto the Sharpe of the resampled days, which are
    the seeded generator's blocks: the whole computation checked end to end."""
    idx = block_indices(8, 3, random.Random(7))
    by_hand = sum(sharpe_ratio([s[i] for i in idx]) for s in SERIES) / len(SERIES)
    boot = bootstrap_sharpe({"C0": SERIES}, resamples=1, seed=7, block=3)
    est = boot.sharpe["C0"]
    assert (est.ci_low, est.ci_high) == pytest.approx((by_hand, by_hand))
    assert est.value == pytest.approx(sum(sharpe_ratio(s) for s in SERIES) / 2)
    assert (boot.days, boot.block, boot.resamples) == (8, 3, 1)


def test_seeded_and_paired() -> None:
    shifted = [[x + 0.01 for x in s] for s in SERIES]
    groups = {"C0": SERIES, "C3": shifted, "C2": SERIES}
    pairs = [("C3", "C0"), ("C2", "C0"), ("C3", "C1")]  # C1 is missing: no difference for it
    a = bootstrap_sharpe(groups, pairs, resamples=300, seed=1)
    assert a == bootstrap_sharpe(groups, pairs, resamples=300, seed=1)  # reproducible
    assert a != bootstrap_sharpe(groups, pairs, resamples=300, seed=2)
    assert set(a.differences) == {("C3", "C0"), ("C2", "C0")}
    same = a.differences[("C2", "C0")]  # identical groups on the same days: exactly 0
    assert (same.value, same.ci_low, same.ci_high) == (0.0, 0.0, 0.0)
    up = a.differences[("C3", "C0")]
    assert up.value > 0
    assert up.ci_low <= up.value <= up.ci_high
    for est in a.sharpe.values():
        assert est.ci_low <= est.ci_high
        assert math.isfinite(est.value)


def test_bad_input() -> None:
    with pytest.raises(ValueError, match="no groups"):
        bootstrap_sharpe({})
    with pytest.raises(ValueError, match="common length"):
        bootstrap_sharpe({"C0": [[0.1, 0.2]], "C1": [[0.1, 0.2, 0.3]]})
    with pytest.raises(ValueError, match="two days"):
        bootstrap_sharpe({"C0": [[0.1]]})
