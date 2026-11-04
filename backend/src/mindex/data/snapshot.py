# Polars 2 annotates its expression inputs with types pyright cannot resolve without
# numpy/pyarrow stubs, which strict mode reports as "partially unknown".
# pyright: reportUnknownMemberType=false
"""Versioned Parquet snapshots, one file per split, plus a manifest with SHA-256 checksums (NF5).

Experiments read these snapshots, never the exchange, so a run is reproducible bit for bit.
The frame layout mirrors the `prices` table: one row per (asset, day).
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from mindex.data.sources import Candle
from mindex.data.splits import SPLITS, Split, ensure_readable
from mindex.domain.decision import Asset

MANIFEST = "manifest.json"
SCHEMA: dict[str, pl.DataType] = {
    "asset": pl.String(),
    "day": pl.Date(),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "volume": pl.Float64(),
    "fear_greed": pl.Int16(),
    "funding_rate": pl.Float64(),
}


class DataQualityError(ValueError):
    pass


def build_frame(
    candles: Mapping[Asset, list[Candle]],
    fear_greed: Mapping[date, int],
    funding: Mapping[Asset, Mapping[date, float]],
) -> pl.DataFrame:
    rows = [
        {
            "asset": str(asset),
            "day": c.day,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "fear_greed": fear_greed.get(c.day),
            "funding_rate": funding.get(asset, {}).get(c.day),
        }
        for asset, series in candles.items()
        for c in series
    ]
    return pl.DataFrame(rows, schema=SCHEMA).sort("asset", "day")


@dataclass(frozen=True, slots=True)
class QualityReport:
    rows: int
    missing_days: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    missing_fear_greed: int = 0
    missing_funding: int = 0


def check_quality(df: pl.DataFrame) -> QualityReport:
    """Hard errors for impossible candles and duplicates; gaps are reported, not fatal."""
    bad = df.filter(
        (pl.col("low") <= 0)
        | (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("high") < pl.max_horizontal("open", "close"))
        | (pl.col("volume") < 0)
    )
    if bad.height:
        raise DataQualityError(f"{bad.height} candle(s) violate low <= open,close <= high")
    if df.select(pl.struct("asset", "day").is_duplicated().any()).item():
        raise DataQualityError("duplicate (asset, day) rows")

    missing: dict[str, list[str]] = {}
    for (asset,), group in df.group_by("asset", maintain_order=True):
        days = set(group["day"].to_list())
        first, last = min(days), max(days)
        gaps = [
            (first + timedelta(days=i)).isoformat()
            for i in range((last - first).days + 1)
            if first + timedelta(days=i) not in days
        ]
        if gaps:
            missing[str(asset)] = gaps
    return QualityReport(
        rows=df.height,
        missing_days=missing,
        missing_fear_greed=df["fear_greed"].null_count(),
        missing_funding=df["funding_rate"].null_count(),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_snapshot(df: pl.DataFrame, out_dir: Path, *, source: str) -> dict[str, object]:
    """Write `<split>.parquet` for every split and a manifest; returns the manifest."""
    report = check_quality(df)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, object] = {}
    for split, window in SPLITS.items():
        part = df.filter(pl.col("day").is_between(window.start, window.end))
        path = out_dir / f"{split}.parquet"
        part.write_parquet(path, statistics=True)
        files[str(split)] = {
            "rows": part.height,
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            "sha256": _sha256(path),
        }
    manifest: dict[str, object] = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": source,
        "assets": sorted(df["asset"].unique().to_list()),
        "files": files,
        "quality": asdict(report),
    }
    (out_dir / MANIFEST).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def load_split(snapshot_dir: Path, split: Split, *, unseal: bool = False) -> pl.DataFrame:
    """Read one split, verifying its checksum against the manifest."""
    ensure_readable(split, unseal=unseal)
    path = snapshot_dir / f"{split}.parquet"
    manifest = json.loads((snapshot_dir / MANIFEST).read_text(encoding="utf-8"))
    expected = manifest["files"][str(split)]["sha256"]
    if _sha256(path) != expected:
        raise DataQualityError(f"{path.name} does not match the manifest checksum")
    return pl.read_parquet(path)


def load_window(
    snapshot_dir: Path, split: Split, *, lookback_days: int = 0, unseal: bool = False
) -> pl.DataFrame:
    """A split plus `lookback_days` of history from the preceding split (indicator warm-up)."""
    df = load_split(snapshot_dir, split, unseal=unseal)
    order = list(Split)
    idx = order.index(split)
    if lookback_days <= 0 or idx == 0:
        return df
    prev = load_split(snapshot_dir, order[idx - 1])
    since = SPLITS[split].start - timedelta(days=lookback_days)
    return pl.concat([prev.filter(pl.col("day") >= since), df]).sort("asset", "day")
