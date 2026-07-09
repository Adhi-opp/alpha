from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from alpha.data import pit
from alpha.study import h001r
from alpha.study.bootstrap import two_sided_p


def test_write_intensity_hand_computed():
    poi = pd.DataFrame([{
        "trade_date": pd.Timestamp("2025-01-01"), "client_type": "Client",
        "available_at": pd.Timestamp("2025-01-01 16:30", tz="UTC"),
        "opt_idx_call_short": 60, "opt_idx_put_short": 40,
        "opt_idx_call_long": 30, "opt_idx_put_long": 20,
    }, {
        "trade_date": pd.Timestamp("2025-01-01"), "client_type": "FII",
        "available_at": pd.Timestamp("2025-01-01 16:30", tz="UTC"),
        "opt_idx_call_short": 999, "opt_idx_put_short": 999,
        "opt_idx_call_long": 0, "opt_idx_put_long": 0,
    }])
    out = h001r.client_write_intensity(poi)
    assert len(out) == 1                      # Client row only
    # (100 - 50) / 150 = 1/3
    assert out["wi"].iloc[0] == pytest.approx(1 / 3)


def test_front_month_picks_nearest_expiry_and_trendiness():
    bhav = pd.DataFrame([
        {"trade_date": pd.Timestamp("2025-06-02"), "symbol": "NIFTY",
         "instrument": "IDF", "expiry": pd.Timestamp("2025-06-26"),
         "open": 100.0, "high": 110.0, "low": 90.0, "close": 108.0,
         "prev_close": 100.0},
        {"trade_date": pd.Timestamp("2025-06-02"), "symbol": "NIFTY",
         "instrument": "IDF", "expiry": pd.Timestamp("2025-07-31"),
         "open": 101.0, "high": 111.0, "low": 91.0, "close": 109.0,
         "prev_close": 101.0},
        {"trade_date": pd.Timestamp("2025-06-02"), "symbol": "BANKNIFTY",
         "instrument": "IDF", "expiry": pd.Timestamp("2025-06-26"),
         "open": 1, "high": 2, "low": 0.5, "close": 1.5, "prev_close": 1},
    ])
    out = h001r.front_month_daily(bhav)
    assert len(out) == 1
    # nearest expiry row: |108-100| / (110-90) = 0.4
    assert out["trendiness"].iloc[0] == pytest.approx(0.4)


def _seed_derived(tmp_path, n_days=8):
    """Synthetic participant_oi + fo_bhavcopy derived datasets."""
    days = pd.bdate_range("2025-06-02", periods=n_days)
    poi_rows, bhav_rows = [], []
    for i, d in enumerate(days):
        poi_rows.append({
            "trade_date": d, "client_type": "Client",
            "opt_idx_call_short": 100 + 10 * i, "opt_idx_put_short": 100,
            "opt_idx_call_long": 50, "opt_idx_put_long": 50,
            "available_at": (d.tz_localize("Asia/Kolkata") + pd.Timedelta(hours=22)
                             ).tz_convert("UTC"),
        })
        bhav_rows.append({
            "trade_date": d, "symbol": "NIFTY", "instrument": "IDF",
            "expiry": days[-1] + pd.Timedelta(days=20),
            "open": 100.0, "high": 110.0, "low": 90.0,
            "close": 100.0 + i, "prev_close": 99.0 + i,
            "available_at": (d.tz_localize("Asia/Kolkata") + pd.Timedelta(hours=19)
                             ).tz_convert("UTC"),
        })
    pit.append("participant_oi", pd.DataFrame(poi_rows),
               ["trade_date", "client_type"], root=tmp_path)
    pit.append("fo_bhavcopy", pd.DataFrame(bhav_rows),
               ["trade_date", "symbol", "instrument", "expiry"], root=tmp_path)
    return days


def test_assemble_conditions_on_previous_day(tmp_path, monkeypatch):
    monkeypatch.setattr(h001r, "SAMPLE_START", date(2025, 6, 2))
    monkeypatch.setattr(h001r, "HOLDOUT_START", date(2027, 1, 1))
    days = _seed_derived(tmp_path)
    df = h001r.assemble(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                        root=tmp_path)
    # first day has no prior file -> dropped; every kept day i conditions on i-1
    assert df["trade_date"].min() > days[0]
    # wi grows with i, so the conditioning value for day i must equal wi(i-1):
    # wi(i) = (200+10i-100)/(300+10i)
    i = 3  # day index in `days`
    row = df[df["trade_date"] == days[i]].iloc[0]
    expected_prev = (200 + 10 * (i - 1) - 100) / (300 + 10 * (i - 1))
    assert row["wi"] == pytest.approx(expected_prev)


def test_assemble_raises_on_same_day_conditioning(tmp_path, monkeypatch):
    monkeypatch.setattr(h001r, "SAMPLE_START", date(2025, 6, 2))
    monkeypatch.setattr(h001r, "HOLDOUT_START", date(2027, 1, 1))
    days = pd.bdate_range("2025-06-02", periods=4)
    poi_rows, bhav_rows = [], []
    for i, d in enumerate(days):
        poi_rows.append({
            "trade_date": d, "client_type": "Client",
            "opt_idx_call_short": 100, "opt_idx_put_short": 100,
            "opt_idx_call_long": 50, "opt_idx_put_long": 50,
            # PIT bug simulation: published 08:00 IST SAME morning
            "available_at": (d.tz_localize("Asia/Kolkata") + pd.Timedelta(hours=8)
                             ).tz_convert("UTC"),
        })
        bhav_rows.append({
            "trade_date": d, "symbol": "NIFTY", "instrument": "IDF",
            "expiry": days[-1] + pd.Timedelta(days=20),
            "open": 100.0, "high": 110.0, "low": 90.0, "close": 101.0,
            "prev_close": 100.0,
            "available_at": (d.tz_localize("Asia/Kolkata") + pd.Timedelta(hours=19)
                             ).tz_convert("UTC"),
        })
    pit.append("participant_oi", pd.DataFrame(poi_rows),
               ["trade_date", "client_type"], root=tmp_path)
    pit.append("fo_bhavcopy", pd.DataFrame(bhav_rows),
               ["trade_date", "symbol", "instrument", "expiry"], root=tmp_path)
    with pytest.raises(AssertionError, match="PIT violation"):
        h001r.assemble(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                       root=tmp_path)


def test_tercile_diff_hand_computed():
    x = np.arange(9, dtype=float)
    y = np.array([0, 0, 0, 0, 0, 0, 1, 1, 1], dtype=float)
    assert h001r.tercile_diff(x, y) == pytest.approx(1.0)


def test_spearman_and_partial():
    rng = np.random.default_rng(0)
    c = rng.normal(size=400)
    # y driven ONLY by the control -> partial must collapse toward 0
    y = c + 0.1 * rng.normal(size=400)
    x = 0.8 * c + 0.6 * rng.normal(size=400)   # x correlated with c too
    raw = h001r.spearman(x, y)
    part = h001r.partial_spearman(x, y, c.reshape(-1, 1))
    assert raw > 0.5                # looks impressive raw…
    assert abs(part) < 0.15         # …and dies under the control (G003 lesson)
    # and a REAL x->y link survives its control
    y2 = x + 0.5 * rng.normal(size=400)
    assert h001r.partial_spearman(x, y2, c.reshape(-1, 1)) > 0.5


def test_two_sided_p():
    assert two_sided_p(np.full(999, 0.5)) < 0.01
    rng = np.random.default_rng(1)
    assert two_sided_p(rng.normal(size=999)) > 0.5
