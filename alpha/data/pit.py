"""Point-in-time accessor — the ONLY sanctioned read path for studies.

Direct parquet/CSV reads inside study code are a code-review reject
(docs/ARCHITECTURE.md §1). `load(dataset, asof)` returns only rows whose
available_at is strictly before asof, so a decision simulated at asof can
never see data that had not yet been published.

Derived datasets live at data/derived/<dataset>/<year>.parquet, partitioned
by trade_date year, each carrying a tz-aware UTC available_at column.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from alpha.config import DERIVED_ROOT


def _dataset_dir(dataset: str, root: Path | None) -> Path:
    return (root or DERIVED_ROOT) / dataset


def append(
    dataset: str,
    df: pd.DataFrame,
    dedup_keys: list[str],
    root: Path | None = None,
) -> None:
    """Merge rows into the dataset, deduplicating on dedup_keys.

    First-write-wins on duplicates: a revised exchange file becomes a .rev
    in the raw archive and a deliberate re-derivation, never a silent update.
    """
    if "available_at" not in df.columns:
        raise ValueError(f"{dataset}: DataFrame lacks available_at column")
    if df["available_at"].dt.tz is None:
        raise ValueError(f"{dataset}: available_at must be tz-aware")
    if "trade_date" not in df.columns:
        raise ValueError(f"{dataset}: DataFrame lacks trade_date column")

    target_dir = _dataset_dir(dataset, root)
    target_dir.mkdir(parents=True, exist_ok=True)
    for year, chunk in df.groupby(df["trade_date"].dt.year):
        path = target_dir / f"{year}.parquet"
        if path.exists():
            existing = pd.read_parquet(path)
            merged = pd.concat([existing, chunk], ignore_index=True)
        else:
            merged = chunk.copy()
        merged = (
            merged.drop_duplicates(subset=dedup_keys, keep="first")
            .sort_values(["trade_date", *[k for k in dedup_keys if k != "trade_date"]])
            .reset_index(drop=True)
        )
        merged.to_parquet(path, index=False)


def load(
    dataset: str,
    asof: datetime,
    root: Path | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Load all rows of `dataset` published strictly before `asof`."""
    if asof.tzinfo is None:
        raise ValueError(
            "asof must be timezone-aware — a naive asof silently breaks "
            "point-in-time discipline"
        )
    target_dir = _dataset_dir(dataset, root)
    files = sorted(target_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no derived data for dataset {dataset!r}")
    frames = [pd.read_parquet(f, columns=columns) for f in files]
    df = pd.concat(frames, ignore_index=True)
    if "available_at" not in df.columns:
        raise ValueError(f"{dataset}: derived data lacks available_at column")
    cutoff = pd.Timestamp(asof).tz_convert("UTC")
    return df[df["available_at"] < cutoff].reset_index(drop=True)


def load_all_unsafe(dataset: str, root: Path | None = None) -> pd.DataFrame:
    """Full dataset with NO point-in-time filter.

    For ops/integrity/calendar-building only. The _unsafe suffix is the
    grep handle: this function appearing in study code is a review reject.
    """
    target_dir = _dataset_dir(dataset, root)
    files = sorted(target_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no derived data for dataset {dataset!r}")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
