import json
import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from mindex import cli
from mindex.data import snapshot as snapshot_module
from mindex.data.snapshot import SCHEMA, write_snapshot
from mindex.data.splits import SPLITS, Split, ensure_readable
from mindex.domain.decision import Asset
from mindex.domain.regime import Regime
from mindex.regime.hmm import Labeling, RegimeModel
from mindex.regime.report import (
    forward_log_return,
    label_report,
    mean_durations,
    to_markdown,
)

B, S, R = Regime.BULL, Regime.SIDEWAYS, Regime.BEAR

# 40 days: flat for days 1-30, then the nine evaluated days 31-39 move as below.
MOVES = [0.1, 0.0, -0.1, -0.1, 0.0, 0.0, 0.1, 0.1, 0.0]
LOG_RET = np.array([0.0] * 31 + MOVES)
LABELS = [S] * 31 + [B, B, R, R, R, S, B, B, B]
START = 31


def e(x: float) -> float:
    return math.expm1(x)


def test_forward_return_never_runs_past_the_end() -> None:
    out = forward_log_return(np.array([0.0, 0.1, 0.2, 0.3]), 2)
    assert np.allclose(out[:2], [0.3, 0.5])
    assert np.isnan(out[2:]).all()
    assert np.isnan(forward_log_return(np.array([0.0, 0.1]), 2)).all()


def test_mean_durations() -> None:
    assert mean_durations([B, B, R, R, R, S, B, B, B]) == {B: 2.5, R: 3.0, S: 1.0}
    assert mean_durations([]) == {}


def test_label_report_matches_a_hand_computed_example() -> None:
    report = label_report(LABELS, LOG_RET, None, START)
    assert report["days"] == 9
    assert report["btc_return"] is None
    assert report["basket_return"] == pytest.approx(0.0)  # days 32-39 sum to zero
    bull, side, bear = (report["labels"][str(r)] for r in (B, S, R))
    assert (bull["days"], side["days"], bear["days"]) == (5, 1, 3)
    assert bull["share"] == pytest.approx(5 / 9)
    assert (bull["mean_duration"], side["mean_duration"], bear["mean_duration"]) == (2.5, 1, 3)

    # Trailing 30 days on day t is the sum of the moves from day 31 to t (days 1-30 are flat).
    trailing = bull["basket"]["trailing_30d"]
    assert trailing["n"] == 5
    assert trailing["mean"] == pytest.approx((4 * e(0.1) + e(0.0)) / 5)
    assert bear["basket"]["trailing_30d"]["mean"] == pytest.approx((e(0.0) + 2 * e(-0.1)) / 3)
    assert side["basket"]["trailing_30d"]["mean"] == pytest.approx(e(-0.1))

    # Forward 1 day: the next day's move; the last day has none.
    f1 = bull["basket"]["forward_1d"]
    assert f1["n"] == 4
    assert f1["mean"] == pytest.approx((e(0.0) + e(-0.1) + e(0.1) + e(0.0)) / 4)
    assert bear["basket"]["forward_1d"]["mean"] == pytest.approx((e(-0.1) + 2 * e(0.0)) / 3)
    assert side["basket"]["forward_1d"]["mean"] == pytest.approx(e(0.1))

    # Forward 5 days exists for days 31-34 only (day 39 is the last).
    assert bull["basket"]["forward_5d"]["mean"] == pytest.approx((e(-0.2) + e(-0.1)) / 2)
    assert bear["basket"]["forward_5d"] == {"mean": pytest.approx((e(0.1) + e(0.2)) / 2), "n": 2}
    assert side["basket"]["forward_5d"] == {"mean": None, "n": 0}
    # Forward 20 days would read past the end on every evaluated day.
    assert all(report["labels"][str(r)]["basket"]["forward_20d"]["n"] == 0 for r in (B, S, R))

    assert report["coherent"]["basket"] == {
        "trailing_30d": False,  # sideways (-9.5 %) below bear (-6.3 %)
        "forward_1d": False,
        "forward_5d": None,  # sideways has no value
        "forward_20d": None,
    }


def test_label_report_is_coherent_when_the_order_holds() -> None:
    labels = [S] * 31 + [B, S, R]
    log_ret = np.array([0.0] * 31 + [0.0, 0.2, 0.0])
    report = label_report(labels, log_ret, log_ret, START)
    # Trailing: bull 0, sideways +0.2, bear +0.2 → not ordered; forward 1d: bull +0.2,
    # sideways 0, bear none.
    assert report["coherent"]["basket"]["trailing_30d"] is False
    assert report["coherent"]["basket"]["forward_1d"] is None
    ordered = label_report([S] * 31 + [R, S, B], np.array([0.0] * 31 + [-0.2, 0.1, 0.3]), None, 31)
    assert ordered["coherent"]["basket"]["trailing_30d"] is True
    assert report["coherent"]["btc"] == report["coherent"]["basket"]


def test_label_report_rejects_misaligned_inputs() -> None:
    with pytest.raises(ValueError, match="same days"):
        label_report(LABELS[:-1], LOG_RET, None, START)
    with pytest.raises(ValueError, match="same days"):
        label_report(LABELS, LOG_RET, None, len(LABELS))


def test_markdown_table() -> None:
    part = label_report(LABELS, LOG_RET, LOG_RET, START)
    md = to_markdown(
        {
            "labeling": "momentum",
            "sha256": "ab" * 32,
            "splits": {"validation": {"start": "2025-10-01", "end": "2026-03-31", **part}},
        }
    )
    assert "| bull | 55.6% | 2.5 | +8.4% |" in md
    assert "TUTMUYOR" in md
    assert "belirsiz" in md
    assert "BTC +0.0%" in md


# ---------------------------------------------------------------- CLI on a synthetic snapshot

# (mean, sd, days) of the basket's daily log return; the train split is the last 210 days of
# its window, the validation split all of its 182 days.
TRAIN_SEGMENTS = ((0.015, 0.01, 70), (-0.02, 0.02, 70), (0.0, 0.005, 70))
VALIDATION_SEGMENTS = ((-0.02, 0.02, 60), (0.015, 0.01, 60), (0.0, 0.005, 62))


def regime_snapshot(out: Path) -> Path:
    rng = np.random.default_rng(3)
    rets = np.concatenate(
        [rng.normal(mu, sd, n) for mu, sd, n in TRAIN_SEGMENTS + VALIDATION_SEGMENTS]
    )
    closes = 100.0 * np.exp(np.cumsum(rets))
    start = SPLITS[Split.VALIDATION].start - timedelta(days=sum(n for *_, n in TRAIN_SEGMENTS))
    rows: list[dict[str, object]] = []
    for k, asset in enumerate(Asset):
        for i, close in enumerate(closes):
            c = float(close) * (k + 1)
            rows.append(
                {
                    "asset": str(asset),
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
    write_snapshot(pl.DataFrame(rows, schema=SCHEMA), out, source="synthetic")
    return out


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return regime_snapshot(tmp_path_factory.mktemp("snap") / "snap")


@pytest.mark.parametrize("labeling", list(Labeling), ids=str)
def test_cli_train_hmm_writes_a_report_and_never_reads_the_test_split(
    snapshot: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, labeling: Labeling
) -> None:
    asked: list[Split] = []

    def spy(split: Split, *, unseal: bool = False) -> None:
        asked.append(split)
        ensure_readable(split, unseal=unseal)

    monkeypatch.setattr(snapshot_module, "ensure_readable", spy)
    monkeypatch.setattr(cli, "ensure_readable", spy)
    out = tmp_path / "models" / f"regime-hmm-{labeling}.json"
    reports = tmp_path / "reports"
    argv = ["--snapshot", str(snapshot), "--reports", str(reports)]
    cli.main([*argv, "train-hmm", "--labeling", str(labeling), "--out", str(out)])

    assert Split.TEST not in asked
    assert {Split.TRAIN, Split.VALIDATION} <= set(asked)
    assert RegimeModel.load(out).labeling is labeling
    report = json.loads((reports / f"regime-report-{labeling}.json").read_text(encoding="utf-8"))
    assert report["labeling"] == str(labeling)
    assert list(report["splits"]) == ["train", "validation"]
    validation = report["splits"]["validation"]
    assert validation["start"] == SPLITS[Split.VALIDATION].start.isoformat()
    assert validation["end"] == SPLITS[Split.VALIDATION].end.isoformat()
    assert validation["days"] == 182
    assert sum(v["share"] for v in validation["labels"].values()) == pytest.approx(1.0)
    # Forward returns stop at the end of the validation split instead of reading the test one.
    for h in (1, 5, 20):
        n = sum(v["basket"][f"forward_{h}d"]["n"] for v in validation["labels"].values())
        assert n == 182 - h
    assert (reports / f"regime-report-{labeling}.md").exists()

    # `regime-report` on the saved artefact reproduces the same report.
    asked.clear()
    cli.main([*argv, "regime-report", "--model", str(out)])
    again = json.loads((reports / f"regime-report-{labeling}.json").read_text(encoding="utf-8"))
    assert again == report
    assert Split.TEST not in asked


def test_cli_regime_report_refuses_an_old_artifact(snapshot: Path, tmp_path: Path) -> None:
    old = tmp_path / "regime-hmm.json"
    old.write_text(json.dumps({"version": 2, "features": [], "window": 14}), encoding="utf-8")
    with pytest.raises(SystemExit, match="retrain"):
        cli.main(["--snapshot", str(snapshot), "regime-report", "--model", str(old)])
