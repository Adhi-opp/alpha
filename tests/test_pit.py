from datetime import datetime, timezone

import pandas as pd
import pytest

from alpha.data import pit


def _df(dates_and_avail):
    return pd.DataFrame({
        "trade_date": [pd.Timestamp(d) for d, _ in dates_and_avail],
        "value": range(len(dates_and_avail)),
        "available_at": [pd.Timestamp(a, tz="UTC") for _, a in dates_and_avail],
    })


def test_load_filters_strictly_before_asof(tmp_path):
    df = _df([
        ("2026-07-01", "2026-07-01 16:30"),
        ("2026-07-02", "2026-07-02 16:30"),
        ("2026-07-03", "2026-07-03 16:30"),
    ])
    pit.append("ds", df, ["trade_date"], root=tmp_path)

    asof = datetime(2026, 7, 3, 3, 45, tzinfo=timezone.utc)  # 09:15 IST Jul 3
    out = pit.load("ds", asof, root=tmp_path)
    assert list(out["trade_date"].dt.strftime("%Y-%m-%d")) == ["2026-07-01", "2026-07-02"]

    # exactly at publication instant: strictly-before excludes the row
    at_pub = datetime(2026, 7, 2, 16, 30, tzinfo=timezone.utc)
    assert len(pit.load("ds", at_pub, root=tmp_path)) == 1


def test_naive_asof_rejected(tmp_path):
    pit.append("ds", _df([("2026-07-01", "2026-07-01 16:30")]),
               ["trade_date"], root=tmp_path)
    with pytest.raises(ValueError, match="timezone-aware"):
        pit.load("ds", datetime(2026, 7, 2), root=tmp_path)


def test_append_dedups_first_write_wins(tmp_path):
    df = _df([("2026-07-01", "2026-07-01 16:30")])
    pit.append("ds", df, ["trade_date"], root=tmp_path)
    changed = df.assign(value=[99])
    pit.append("ds", changed, ["trade_date"], root=tmp_path)
    out = pit.load_all_unsafe("ds", root=tmp_path)
    assert len(out) == 1
    assert out["value"].iloc[0] == 0  # original kept, revision ignored


def test_partitions_by_year(tmp_path):
    df = _df([("2025-12-31", "2025-12-31 16:30"), ("2026-01-01", "2026-01-01 16:30")])
    pit.append("ds", df, ["trade_date"], root=tmp_path)
    assert (tmp_path / "ds" / "2025.parquet").exists()
    assert (tmp_path / "ds" / "2026.parquet").exists()
    assert len(pit.load_all_unsafe("ds", root=tmp_path)) == 2


def test_missing_available_at_rejected(tmp_path):
    bad = pd.DataFrame({"trade_date": [pd.Timestamp("2026-07-01")], "v": [1]})
    with pytest.raises(ValueError, match="available_at"):
        pit.append("ds", bad, ["trade_date"], root=tmp_path)
