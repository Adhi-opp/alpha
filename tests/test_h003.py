from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from alpha.data import pit
from alpha.study import h003
from alpha.study.h001b import build_day_paths


def _day(closes, trade_date="2025-06-03", spot=24000.0, strike=24000.0):
    ts = pd.date_range(f"{trade_date} 09:15", periods=len(closes), freq="1min",
                       tz="Asia/Kolkata").tz_convert("UTC")
    rows = []
    for side in ("CE", "PE"):
        rows.append(pd.DataFrame({
            "ts": ts, "side": side, "strike": strike,
            "high": closes, "low": closes, "close": closes, "spot": spot,
        }))
    df = pd.concat(rows, ignore_index=True)
    df["trade_date"] = pd.Timestamp(trade_date)
    return df


def _hurdle(p0, lot=65):
    return h003.COST_MODEL.breakeven_move(p0, lot) + 2 * h003.HALF_SPREAD_EST * p0


def test_scalp_energy_hand_computed():
    closes = np.where(np.arange(375) % 2 == 0, 100.0, 110.0)
    paths = build_day_paths(_day(closes))
    y = h003.scalp_energy(paths, lot=65)
    # window bars 30..360 -> 330 deltas of 10 per leg; p0 = 100 both legs
    h = _hurdle(100.0)
    assert y == pytest.approx(2 * 330 * (10.0 - h) / 200.0, rel=1e-9)


def test_micro_noise_scores_zero_but_bursts_score():
    # SAME raw path length, radically different tradeability
    noise = np.where(np.arange(375) % 2 == 0, 100.0, 100.4)   # 0.4 < hurdle
    burst = np.full(375, 100.0)
    burst[40:373:10] += 4.0        # sparse 4-pt spikes, each > hurdle
    y_noise = h003.scalp_energy(build_day_paths(_day(noise)), lot=65)
    y_burst = h003.scalp_energy(build_day_paths(_day(burst)), lot=65)
    assert y_noise == 0.0          # the grinder is worth nothing
    assert y_burst > 0.0           # the bursts are worth their net amplitude


def test_too_many_missing_bars_excludes_day():
    closes = np.full(375, 100.0)
    day = _day(closes)
    local = day["ts"].dt.tz_convert("Asia/Kolkata")
    pos = (local.dt.hour * 60 + local.dt.minute) - (9 * 60 + 15)
    # remove 40 CE bars inside the window (~12% > 10% cap)
    drop = (day["side"] == "CE") & pos.between(100, 139)
    paths = build_day_paths(day[~drop])
    assert h003.scalp_energy(paths, lot=65) is None


def _seed(tmp_path, n_days, wi_seq, bursty, rng):
    days = pd.bdate_range("2025-01-06", periods=n_days)
    poi_rows, bhav_rows, tidy_frames = [], [], []
    for i, d in enumerate(days):
        w = wi_seq[i]
        short = 200 * (1 + w)
        poi_rows.append({
            "trade_date": d, "client_type": "Client",
            "opt_idx_call_short": short / 2, "opt_idx_put_short": short / 2,
            "opt_idx_call_long": (400 - short) / 2,
            "opt_idx_put_long": (400 - short) / 2,
            "available_at": (d.tz_localize("Asia/Kolkata")
                             + pd.Timedelta(hours=22)).tz_convert("UTC"),
        })
        avail = (d.tz_localize("Asia/Kolkata")
                 + pd.Timedelta(hours=19)).tz_convert("UTC")
        # every day is its own front-week expiry (expiry-day universe)
        bhav_rows.append({
            "trade_date": d, "symbol": "NIFTY", "instrument": "IDO",
            "expiry": d, "strike": 24000.0, "option_type": "CE", "lot": 65.0,
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
            "prev_close": 1.0, "available_at": avail,
        })
        c = 24000 + rng.normal(0, 30)
        bhav_rows.append({
            "trade_date": d, "symbol": "NIFTY", "instrument": "IDF",
            "expiry": days[-1] + pd.Timedelta(days=30), "strike": np.nan,
            "option_type": "", "lot": 65.0,
            "open": c - rng.uniform(5, 40), "high": c + rng.uniform(10, 60),
            "low": c - rng.uniform(10, 60), "close": c,
            "prev_close": c - rng.normal(0, 25), "available_at": avail,
        })
        if bursty[i]:
            closes = np.full(375, 100.0)
            closes[35:370:5] += 5.0            # frequent > hurdle bursts
        else:
            closes = np.where(np.arange(375) % 2 == 0, 100.0, 100.3)
        td = _day(closes, trade_date=str(d.date()))
        td["available_at"] = (d.tz_localize("Asia/Kolkata")
                              + pd.Timedelta(hours=15, minutes=35)
                              ).tz_convert("UTC")
        tidy_frames.append(td)
    pit.append("participant_oi", pd.DataFrame(poi_rows),
               ["trade_date", "client_type"], root=tmp_path)
    pit.append("fo_bhavcopy", pd.DataFrame(bhav_rows),
               ["trade_date", "symbol", "instrument", "expiry", "strike",
                "option_type"], root=tmp_path)
    pit.append("dhan_rolling_1m", pd.concat(tidy_frames, ignore_index=True),
               ["ts", "strike", "side"], root=tmp_path)


def test_run_end_to_end_synthetic(tmp_path, monkeypatch):
    monkeypatch.setattr(h003, "SAMPLE_START", date(2025, 1, 6))
    monkeypatch.setattr(h003, "HOLDOUT_START", date(2027, 1, 1))
    monkeypatch.setattr(h003, "MIN_DAYS", 5)
    monkeypatch.setattr(h003, "N_RESAMPLES", 300)
    n = 30
    rng = np.random.default_rng(3)
    wi_seq = [(0.8 if i % 2 == 0 else -0.6) + rng.normal(0, 0.01)
              for i in range(n)]
    # day T's energy must follow wi(T-1) — same-day alignment would only
    # reward a leaky implementation
    bursty = [i > 0 and wi_seq[i - 1] > 0.5 for i in range(n)]
    _seed(tmp_path, n, wi_seq, bursty, rng)
    res = h003.run(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                   root=tmp_path)
    assert res["study"] == "H-003"
    assert res["n_days"] >= 20
    assert res["primary"]["partial_spearman"] > 0.5
    assert res["gates"][0]["passed"]           # CI excludes 0
    res2 = h003.run(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                    root=tmp_path)
    assert res2["primary"] == res["primary"]   # deterministic


def test_assemble_pit_trap_and_expiry_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(h003, "SAMPLE_START", date(2025, 1, 6))
    monkeypatch.setattr(h003, "HOLDOUT_START", date(2027, 1, 1))
    days = pd.bdate_range("2025-01-06", periods=4)
    poi_rows, bhav_rows = [], []
    for d in days:
        poi_rows.append({
            "trade_date": d, "client_type": "Client",
            "opt_idx_call_short": 100.0, "opt_idx_put_short": 100.0,
            "opt_idx_call_long": 50.0, "opt_idx_put_long": 50.0,
            # bug simulation: published 08:00 the SAME morning
            "available_at": (d.tz_localize("Asia/Kolkata")
                             + pd.Timedelta(hours=8)).tz_convert("UTC"),
        })
        avail = (d.tz_localize("Asia/Kolkata")
                 + pd.Timedelta(hours=19)).tz_convert("UTC")
        bhav_rows.append({
            "trade_date": d, "symbol": "NIFTY", "instrument": "IDO",
            "expiry": days[-1], "strike": 24000.0, "option_type": "CE",
            "lot": 65.0, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
            "prev_close": 1.0, "available_at": avail,
        })
        bhav_rows.append({
            "trade_date": d, "symbol": "NIFTY", "instrument": "IDF",
            "expiry": days[-1] + pd.Timedelta(days=30), "strike": np.nan,
            "option_type": "", "lot": 65.0, "open": 100.0, "high": 110.0,
            "low": 90.0, "close": 101.0, "prev_close": 100.0,
            "available_at": avail,
        })
    pit.append("participant_oi", pd.DataFrame(poi_rows),
               ["trade_date", "client_type"], root=tmp_path)
    pit.append("fo_bhavcopy", pd.DataFrame(bhav_rows),
               ["trade_date", "symbol", "instrument", "expiry", "strike",
                "option_type"], root=tmp_path)
    with pytest.raises(AssertionError, match="PIT violation"):
        h003.assemble(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                      root=tmp_path)
