from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from alpha.data import pit
from alpha.measure.execution_mc import AdverseFillModel, LatencyModel
from alpha.study import h001b


def test_trailing_cut_is_pit_safe(monkeypatch):
    monkeypatch.setattr(h001b, "TRAIL", 3)
    poi = pd.DataFrame({
        "trade_date": pd.bdate_range("2025-01-01", periods=5),
        "available_at": pd.date_range("2025-01-01 16:30", periods=5,
                                      freq="D", tz="UTC"),
        "wi": [1.0, 2.0, 3.0, 4.0, 100.0],
        "net_short": 0, "wi_z60": np.nan,
    })
    out = h001b.trailing_cuts(poi)
    assert out["cut_top"].isna().sum() == 2            # warmup rows
    # row 4 window [3,4,100] -> 2/3-quantile = 4 + (2/3*2-1)*(100-4) = 36
    assert out["cut_top"].iloc[4] == pytest.approx(36.0)
    # a full-sample cut would see the 100 from row 2's viewpoint; trailing
    # row 2 window [1,2,3] must not:
    assert out["cut_top"].iloc[2] == pytest.approx(2.0 + 1 / 3)


def test_is_volatile_matches_dense_adverse_model():
    rng = np.random.default_rng(5)
    n = 120
    close = 100 + np.cumsum(rng.normal(0, 0.4, n))
    spread = np.abs(rng.normal(0.5, 0.3, n))
    high, low = close + spread, close - spread
    path = pd.DataFrame({"high": high, "low": low, "close": close})
    dense = AdverseFillModel(half_spread_frac=0.0)
    for pos in [10, 31, 60, 100, 119]:
        assert h001b.is_volatile(high, low, close, pos) == \
            dense._is_volatile(path, pos), f"divergence at pos {pos}"


def test_exit_pos_caps_at_close():
    assert h001b._exit_pos(60.0) == 366        # one bar after 15:20 intent
    assert h001b._exit_pos(299.0) == 370
    assert h001b._exit_pos(900.0) == 374       # capped at 15:29
    assert h001b._exit_pos(np.inf) == 374      # forced flat by the close


def _dense_day(n_strikes=3, spot0=24000.0, ce_slope=0.0, pe_slope=0.0,
               trade_date="2025-06-03"):
    """One synthetic session: full 375 bars, flat spot, linear premiums."""
    ts = pd.date_range(f"{trade_date} 09:15", periods=375, freq="1min",
                       tz="Asia/Kolkata").tz_convert("UTC")
    rows = []
    strikes = [spot0 + 50 * (i - n_strikes // 2) for i in range(n_strikes)]
    for k in strikes:
        for side, slope in (("CE", ce_slope), ("PE", pe_slope)):
            c = 100.0 + slope * np.arange(375)
            rows.append(pd.DataFrame({
                "ts": ts, "side": side, "strike": k,
                "high": c + 0.0, "low": c - 0.0, "close": c, "spot": spot0,
            }))
    df = pd.concat(rows, ignore_index=True)
    df["trade_date"] = pd.Timestamp(trade_date)
    return df


def test_flat_tape_ev_is_pure_friction_and_deterministic():
    paths = h001b.build_day_paths(_dense_day())
    r1 = h001b.simulate_day(paths, lot=65, trade_date=pd.Timestamp("2025-06-03"),
                            book="TOP", is_expiry=False)
    r2 = h001b.simulate_day(paths, lot=65, trade_date=pd.Timestamp("2025-06-03"),
                            book="TOP", is_expiry=False)
    assert r1.ev == r2.ev                       # same seed -> identical
    assert r1.ev < 0                            # flat tape: frictions only
    assert r1.gross_move == pytest.approx(0.0)  # no premium move
    assert r1.ev_stress < r1.ev                 # wider spread hurts more
    assert r1.trunc_frac == 0.0


def test_attribution_identity_when_all_draws_fill(monkeypatch):
    # forced-finite latency: no no-fill dilution -> identity is exact
    monkeypatch.setattr(h001b, "OWNER_2026_07",
                        LatencyModel(mu=4.0, sigma=0.2, abandon_s=1e9,
                                     name="test"))
    day = _dense_day(ce_slope=0.05, pe_slope=-0.02)
    paths = h001b.build_day_paths(day)
    r = h001b.simulate_day(paths, lot=65, trade_date=pd.Timestamp("2025-06-03"),
                           book="TOP", is_expiry=False)
    assert r.no_fill_rate == 0.0
    total = (r.gross_move + r.latency_drag + r.adverse_drag
             + r.spread_drag - r.statutory)
    assert r.ev == pytest.approx(total, abs=1e-6)


def test_missing_exit_bars_truncate_not_fabricate():
    day = _dense_day()
    # strike fan vanishes from 15:00 (pos 345) onward
    local = day["ts"].dt.tz_convert("Asia/Kolkata")
    pos = (local.dt.hour * 60 + local.dt.minute) - (9 * 60 + 15)
    day = day[pos < 345]
    paths = h001b.build_day_paths(day)
    r = h001b.simulate_day(paths, lot=65, trade_date=pd.Timestamp("2025-06-03"),
                           book="TOP", is_expiry=False)
    assert r.trunc_frac > h001b.TRUNC_DAY_LIMIT
    assert not r.gradeable


def test_abandoned_entry_is_flat_zero(monkeypatch):
    # latency far past abandon threshold on every draw -> never in the market
    monkeypatch.setattr(h001b, "OWNER_2026_07",
                        LatencyModel(mu=12.0, sigma=0.05, abandon_s=900.0,
                                     name="glacial"))
    paths = h001b.build_day_paths(_dense_day(ce_slope=0.05))
    r = h001b.simulate_day(paths, lot=65, trade_date=pd.Timestamp("2025-06-03"),
                           book="TOP", is_expiry=False)
    assert r.fill_rate == 0.0
    assert r.no_fill_rate == 1.0
    assert r.ev == 0.0                          # flat is flat, not free money


def _seed_pit(tmp_path, n_days, wi_seq, ce_slopes, trail):
    """Full synthetic PIT store: participant_oi + fo_bhavcopy + tidy rolling."""
    days = pd.bdate_range("2025-01-06", periods=n_days)
    expiry = days[-1] + pd.Timedelta(days=7)
    poi_rows, bhav_rows, tidy_frames = [], [], []
    for i, d in enumerate(days):
        w = wi_seq[i]
        # invert wi = (s-l)/(s+l) with s+l = 400
        short = 200 * (1 + w)
        poi_rows.append({
            "trade_date": d, "client_type": "Client",
            "opt_idx_call_short": short / 2, "opt_idx_put_short": short / 2,
            "opt_idx_call_long": (400 - short) / 2,
            "opt_idx_put_long": (400 - short) / 2,
            "available_at": (d.tz_localize("Asia/Kolkata")
                             + pd.Timedelta(hours=22)).tz_convert("UTC"),
        })
        bhav_rows.append({
            "trade_date": d, "symbol": "NIFTY", "instrument": "IDO",
            "expiry": expiry, "strike": 24000.0, "option_type": "CE",
            "lot": 65.0, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
            "available_at": (d.tz_localize("Asia/Kolkata")
                             + pd.Timedelta(hours=19)).tz_convert("UTC"),
        })
        td = _dense_day(ce_slope=ce_slopes[i], trade_date=str(d.date()))
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
    return days


def test_run_end_to_end_synthetic(tmp_path, monkeypatch):
    monkeypatch.setattr(h001b, "SAMPLE_START", date(2025, 1, 6))
    monkeypatch.setattr(h001b, "HOLDOUT_START", date(2027, 1, 1))
    monkeypatch.setattr(h001b, "TRAIL", 6)
    monkeypatch.setattr(h001b, "N_DRAWS", 40)
    monkeypatch.setattr(h001b, "N_RESAMPLES", 200)
    monkeypatch.setattr(h001b, "MIN_TOP_DAYS", 3)
    n = 30
    rng = np.random.default_rng(2)
    # alternating regime: high-wi days get an uptrending call side
    wi_seq = [0.8 if i % 3 == 0 else (-0.6 if i % 3 == 1 else 0.1)
              for i in range(n)]
    wi_seq = [w + rng.normal(0, 0.01) for w in wi_seq]
    # day T's book is set by wi(T-1) — the tradeable trend must land on the
    # day AFTER the heavy-writing print (a same-day slope would only reward
    # a leaky implementation)
    ce_slopes = [0.30 if (i > 0 and wi_seq[i - 1] > 0.5) else 0.0
                 for i in range(n)]
    _seed_pit(tmp_path, n, wi_seq, ce_slopes, trail=6)
    res = h001b.run(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                    root=tmp_path)
    assert res["study"] == "H-001b"
    assert res["n_top"] >= 3 and res["n_bottom"] >= 3
    # top days trend (+0.30/min on the call): EV must clear frictions
    assert res["primary"]["mean_ev_rs"] > 0
    assert res["differential"]["top_minus_bottom_rs"] > 0
    # bottom days are flat tape -> pure friction, negative
    assert res["secondary"]["bottom_book_ev"] < 0
    assert res["verdict"] in ("GO", "NO-GO")   # gates may bind on tiny n
    # determinism end to end
    res2 = h001b.run(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                     root=tmp_path)
    assert res2["primary"]["mean_ev_rs"] == res["primary"]["mean_ev_rs"]


def test_assemble_pit_violation_trap(tmp_path, monkeypatch):
    monkeypatch.setattr(h001b, "SAMPLE_START", date(2025, 1, 6))
    monkeypatch.setattr(h001b, "HOLDOUT_START", date(2027, 1, 1))
    monkeypatch.setattr(h001b, "TRAIL", 3)
    days = pd.bdate_range("2025-01-06", periods=6)
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
        bhav_rows.append({
            "trade_date": d, "symbol": "NIFTY", "instrument": "IDO",
            "expiry": days[-1] + pd.Timedelta(days=7), "strike": 24000.0,
            "option_type": "CE", "lot": 65.0, "open": 1.0, "high": 1.0,
            "low": 1.0, "close": 1.0,
            "available_at": (d.tz_localize("Asia/Kolkata")
                             + pd.Timedelta(hours=19)).tz_convert("UTC"),
        })
    pit.append("participant_oi", pd.DataFrame(poi_rows),
               ["trade_date", "client_type"], root=tmp_path)
    pit.append("fo_bhavcopy", pd.DataFrame(bhav_rows),
               ["trade_date", "symbol", "instrument", "expiry", "strike",
                "option_type"], root=tmp_path)
    with pytest.raises(AssertionError, match="PIT violation"):
        h001b.assemble(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                       root=tmp_path)
