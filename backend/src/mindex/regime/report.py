"""Diagnostics for regime labels: how often and how long each label holds, and what the market
did around the days that carry it (`mindex train-hmm`, `mindex regime-report`).

Look-ahead: the *forward* returns here (`forward_1d` / `forward_5d` / `forward_20d`) read days
after the labelled day. They are an evaluation of finished labels only and never feed a
decision, a label or a fit; nothing in the decision path imports this module. They are computed
inside the market the caller passes, so a day whose horizon runs past its end (the last days of
the validation split) is left out rather than read from the next split; `n` says how many days
each mean covers. The test split is never part of a report.

Returns are simple returns over the horizon, exp(Σ daily log returns) - 1. The basket is the
equal-weight basket of `basket_log_returns` (the HMM's own input); BTC is reported beside it.
"""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from mindex.domain.regime import Regime
from mindex.regime.hmm import FloatArray, trailing_log_return

TRAILING_DAYS = 30
HORIZONS = (1, 5, 20)
ORDER = (Regime.BULL, Regime.SIDEWAYS, Regime.BEAR)  # the order a coherent labelling shows


def forward_log_return(log_ret: FloatArray, days: int) -> FloatArray:
    """Sum of the `days` daily log returns after day t (t+1 .. t+days); NaN where the horizon
    runs past the end. EVALUATION ONLY: this reads the future."""
    out = np.full(len(log_ret), np.nan)
    if len(log_ret) > days:
        cumulative = np.cumsum(log_ret)
        out[:-days] = cumulative[days:] - cumulative[:-days]
    return out


def mean_durations(labels: Sequence[Regime]) -> dict[Regime, float]:
    """Mean length of the runs of consecutive days with the same label (runs cut by the start
    or end of `labels` count with the days they have)."""
    runs: dict[Regime, list[int]] = {}
    i = 0
    while i < len(labels):
        j = i
        while j < len(labels) and labels[j] == labels[i]:
            j += 1
        runs.setdefault(labels[i], []).append(j - i)
        i = j
    return {r: sum(v) / len(v) for r, v in runs.items()}


def _returns(log_ret: FloatArray, start: int) -> dict[str, FloatArray]:
    """Per-day simple returns from `start` on: trailing `TRAILING_DAYS` and each forward
    horizon."""
    series = {f"trailing_{TRAILING_DAYS}d": trailing_log_return(log_ret, TRAILING_DAYS)}
    for h in HORIZONS:
        series[f"forward_{h}d"] = forward_log_return(log_ret, h)
    return {k: np.expm1(v[start:]) for k, v in series.items()}


def _stats(values: FloatArray, mask: np.ndarray[Any, np.dtype[np.bool_]]) -> dict[str, Any]:
    picked = values[mask]
    picked = picked[np.isfinite(picked)]
    return {"mean": float(picked.mean()) if len(picked) else None, "n": len(picked)}


def label_report(
    labels: Sequence[Regime],
    basket_log_ret: FloatArray,
    btc_log_ret: FloatArray | None,
    start: int,
) -> dict[str, Any]:
    """Diagnostics of `labels[start:]`; all three sequences cover the same days, and the days
    before `start` serve only as history for the trailing return.

    Returns `days`, the period's `basket_return` / `btc_return`, per label `days`, `share`,
    `mean_duration` and the mean basket and BTC returns (`trailing_30d`, `forward_{1,5,20}d`,
    each with its `n`), and `coherent`: per series and return, whether the label means are
    ordered bull > sideways > bear (None when a label has no value to compare).
    """
    if not len(labels) == len(basket_log_ret) or start >= len(labels):
        raise ValueError("labels and returns must cover the same days, with days after start")
    window = list(labels[start:])
    series = {"basket": basket_log_ret} | ({} if btc_log_ret is None else {"btc": btc_log_ret})
    returns = {name: _returns(log_ret, start) for name, log_ret in series.items()}
    durations = mean_durations(window)
    tags = np.array([str(r) for r in window])
    per_label: dict[str, Any] = {}
    for regime in ORDER:
        mask = tags == str(regime)
        count = int(mask.sum())
        per_label[str(regime)] = {
            "days": count,
            "share": count / len(window),
            "mean_duration": durations.get(regime),
        } | {
            name: {key: _stats(values, mask) for key, values in by_key.items()}
            for name, by_key in returns.items()
        }
    coherent: dict[str, dict[str, bool | None]] = {}
    for name, by_key in returns.items():
        coherent[name] = {}
        for key in by_key:
            means = [per_label[str(r)][name][key]["mean"] for r in ORDER]
            coherent[name][key] = (
                None if any(m is None for m in means) else bool(means[0] > means[1] > means[2])
            )
    return {
        "days": len(window),
        "basket_return": math.expm1(float(basket_log_ret[start + 1 :].sum())),
        "btc_return": None
        if btc_log_ret is None
        else math.expm1(float(btc_log_ret[start + 1 :].sum())),
        "labels": per_label,
        "coherent": coherent,
    }


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:+.1f}%"


def to_markdown(report: dict[str, Any]) -> str:
    """The report as Markdown tables (one per split), ready to paste into an issue."""
    keys = [f"trailing_{TRAILING_DAYS}d", *(f"forward_{h}d" for h in HORIZONS)]
    head = ["geriye 30g", *(f"ileri {h}g" for h in HORIZONS)]
    lines = [
        f"### Rejim tanısı: `{report['labeling']}` (sha256 `{report['sha256'][:12]}`)",
        "",
    ]
    for split, part in report["splits"].items():
        btc = "" if part["btc_return"] is None else f", BTC {_pct(part['btc_return'])}"
        lines += [
            f"**{split}** ({part['start']} → {part['end']}, {part['days']} gün; "
            f"sepet {_pct(part['basket_return'])}{btc})",
            "",
            "| etiket | gün payı | ort. süre | "
            + " | ".join(f"sepet {h}" for h in head)
            + " | "
            + " | ".join(f"BTC {h}" for h in head)
            + " |",
            "|---" * (3 + 2 * len(head)) + "|",
        ]
        for regime in ORDER:
            row = part["labels"][str(regime)]
            duration = row["mean_duration"]
            cells = [
                str(regime),
                f"{row['share'] * 100:.1f}%",
                "-" if duration is None else f"{duration:.1f}",
            ]
            for name in ("basket", "btc"):
                cells += [_pct(row[name][k]["mean"]) if name in row else "-" for k in keys]
            lines.append("| " + " | ".join(cells) + " |")
        verdicts: list[str] = []
        for name, by_key in part["coherent"].items():
            for key, ok in by_key.items():
                mark = "belirsiz" if ok is None else ("tutuyor" if ok else "TUTMUYOR")
                verdicts.append(f"{name} {key}: {mark}")
        lines += ["", "Boğa > yatay > ayı sırası: " + "; ".join(verdicts), ""]
    return "\n".join(lines)
