"""Temporal train / validation / test split and the sealed test-set guard (look-ahead protocol).

The test window starts after the LLM's release (2 March 2026), so the model cannot have seen it.
It is only opened for the final evaluation: reading it needs an explicit `unseal=True`, and is
refused outright on CI.
"""

import os
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Split(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class Window:
    start: date
    end: date  # inclusive

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("window end must not be before its start")

    def __contains__(self, day: object) -> bool:
        return isinstance(day, date) and self.start <= day <= self.end

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


SPLITS: dict[Split, Window] = {
    # All five pairs trade on Binance from September 2020 on (SOL listed in August 2020).
    Split.TRAIN: Window(date(2020, 9, 1), date(2025, 9, 30)),
    Split.VALIDATION: Window(date(2025, 10, 1), date(2026, 3, 31)),
    Split.TEST: Window(date(2026, 4, 1), date(2026, 9, 30)),
}

MODEL_RELEASE = date(2026, 3, 2)  # Qwen3.5 release; the test set must start after it
FULL_RANGE = Window(SPLITS[Split.TRAIN].start, SPLITS[Split.TEST].end)


class SealedTestSetError(PermissionError):
    """Raised when the test split is read without unsealing it (or on CI at all)."""


def split_of(day: date) -> Split | None:
    for split, window in SPLITS.items():
        if day in window:
            return split
    return None


def ensure_readable(split: Split, *, unseal: bool = False) -> None:
    if split is not Split.TEST:
        return
    if os.environ.get("CI"):
        raise SealedTestSetError("the test split is never read on CI (look-ahead protocol)")
    if not unseal:
        raise SealedTestSetError(
            "the test split is sealed until the final evaluation; pass unseal=True deliberately"
        )
