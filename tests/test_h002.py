from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from alpha.study import h001b, h002
from test_h001b import _dense_day, _seed_pit


def _day_with_volatile_morning(n_volatile=60, trade_date="2025-06-03"):
    """ESCALATING ranges until `n_volatile` (each bar wider than its trailing
    75th pct -> volatile under the frozen relative test; a merely-wide but
    uniform morning would count calm), then a flat calm tape."""
    day = _dense_day(trade_date=trade_date)
    local = day["ts"].dt.tz_convert("Asia/Kolkata")
    pos = ((local.dt.hour * 60 + local.dt.minute) - (9 * 60 + 15)).to_numpy()
    band = np.where(pos < n_volatile, 1.05 ** pos, 0.0)
    day["high"] = day["close"] + band
    day["low"] = day["close"] - band
    return day


def test_trigger_skips_volatile_morning():
    paths = h001b.build_day_paths(_day_with_volatile_morning(n_volatile=60))
    t = h002.find_trigger(paths)
    # bars 30..59 escalate (always > trailing 75th pct); bar 60 is the first
    # calm one
    assert t == 60


def test_trigger_on_flat_tape_is_first_eligible_bar():
    paths = h001b.build_day_paths(_dense_day())
    assert h002.find_trigger(paths) == h002.TRIGGER_FIRST


def test_no_calm_bar_means_no_ticket():
    # alternate wide/wider bars all day: every bar exceeds its trailing 75th
    day = _dense_day()
    local = day["ts"].dt.tz_convert("Asia/Kolkata")
    pos = ((local.dt.hour * 60 + local.dt.minute) - (9 * 60 + 15)).to_numpy()
    day["high"] = day["close"] + 1.0 + pos * 0.5   # ranges strictly increase
    day["low"] = day["close"] - 1.0 - pos * 0.5
    paths = h001b.build_day_paths(day)
    assert h002.find_trigger(paths) is None


def test_calm_entry_collapses_adverse_rate():
    # constant band: every bar equals its trailing pctile -> calm (strict >),
    # but H001b's forced-volatile morning entry still pays close + band
    day = _dense_day()
    day["high"] = day["close"] + 0.3
    day["low"] = day["close"] - 0.3
    paths = h001b.build_day_paths(day)
    t = h002.find_trigger(paths)
    res, adverse_rate = h002.simulate_day(
        paths, t, lot=65, trade_date=pd.Timestamp("2025-06-03"),
        book="TOP", is_expiry=False)
    # flat tape: every arrival bar is calm -> adverse rate 0, vs H001b's
    # by-construction 100% at the open
    assert adverse_rate == 0.0
    assert res.ev < 0                        # flat tape still pays frictions
    # and those frictions are smaller than H001b's on the same tape
    res_b = h001b.simulate_day(paths, lot=65,
                               trade_date=pd.Timestamp("2025-06-03"),
                               book="TOP", is_expiry=False)
    assert res.ev > res_b.ev


def test_run_end_to_end_synthetic(tmp_path, monkeypatch):
    for mod in (h001b,):
        monkeypatch.setattr(mod, "SAMPLE_START", date(2025, 1, 6))
        monkeypatch.setattr(mod, "HOLDOUT_START", date(2027, 1, 1))
        monkeypatch.setattr(mod, "TRAIL", 6)
    monkeypatch.setattr(h002, "N_DRAWS", 40)
    monkeypatch.setattr(h002, "N_RESAMPLES", 200)
    monkeypatch.setattr(h002, "MIN_TOP_DAYS", 3)
    n = 30
    rng = np.random.default_rng(2)
    wi_seq = [0.8 if i % 3 == 0 else (-0.6 if i % 3 == 1 else 0.1)
              for i in range(n)]
    wi_seq = [w + rng.normal(0, 0.01) for w in wi_seq]
    ce_slopes = [0.30 if (i > 0 and wi_seq[i - 1] > 0.5) else 0.0
                 for i in range(n)]
    _seed_pit(tmp_path, n, wi_seq, ce_slopes, trail=6)
    res = h002.run(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                   root=tmp_path)
    assert res["study"] == "H-002"
    assert res["n_top"] >= 3 and res["n_bottom"] >= 3
    assert res["trigger"]["entry_adverse_hit_rate"] == 0.0   # flat synthetic
    assert res["primary"]["mean_ev_rs"] > 0                  # trend, calm fills
    assert res["differential"]["top_minus_bottom_rs"] > 0
    res2 = h002.run(asof=datetime(2027, 1, 1, tzinfo=timezone.utc),
                    root=tmp_path)
    assert res2["primary"]["mean_ev_rs"] == res["primary"]["mean_ev_rs"]
