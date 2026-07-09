import numpy as np
import pandas as pd
import pytest

from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07 as CM
from alpha.measure.execution_mc import (
    FOCUSED_DESK, OWNER_2026_07, AdverseFillModel, LatencyModel, McTicket,
    arrival_pos, simulate_ticket,
)


def test_owner_latency_matches_reported_profile():
    rng = np.random.default_rng(0)
    lat = OWNER_2026_07.draw(50_000, rng)
    finite = lat[np.isfinite(lat)]
    med = np.median(finite)
    assert 80 <= med <= 115                     # ~95 s median
    assert 25 <= np.percentile(finite, 10) <= 40    # P10 ~30 s (owner's floor)
    assert 240 <= np.percentile(finite, 90) <= 380  # P90 ~5 min (owner's bulk cap)
    abandoned = np.isinf(lat).mean()
    assert 0.001 < abandoned < 0.02             # ~0.6% past the 15-min stretch


def test_focused_desk_is_the_optimistic_scenario():
    rng = np.random.default_rng(1)
    med = np.median(FOCUSED_DESK.draw(20_000, rng))
    assert 25 <= med <= 36                      # ~30 s — flattering, hence not default
    assert OWNER_2026_07.name == "owner_2026_07"


def test_arrival_pos_ceils_to_next_bar():
    assert arrival_pos(10, 30.0) == 11          # 30 s cannot fill inside bar 10
    assert arrival_pos(10, 61.0) == 12
    assert arrival_pos(10, np.inf) is None      # abandoned


def _path(bars):
    ts = pd.date_range("2026-07-06 09:15", periods=len(bars), freq="1min", tz="UTC")
    return pd.DataFrame({"timestamp": ts,
                         "high": [b[0] for b in bars],
                         "low": [b[1] for b in bars],
                         "close": [b[2] for b in bars]})


def test_adverse_fill_pays_high_on_volatile_bar():
    calm = [(100.5, 99.5, 100.0)] * 40          # trailing range 1.0
    wide = [(110.0, 98.0, 100.0)]               # arrival bar range 12 -> volatile
    path = _path(calm + wide)
    fm = AdverseFillModel(half_spread_frac=0.0)
    assert fm.fill_price(path, 40, "B") == pytest.approx(110.0)   # the HIGH
    assert fm.fill_price(path, 40, "S") == pytest.approx(98.0)    # the LOW
    # calm arrival bar -> close
    assert fm.fill_price(path, 39, "B") == pytest.approx(100.0)


def test_insufficient_history_counts_as_volatile():
    path = _path([(101, 99, 100)] * 5)
    fm = AdverseFillModel(half_spread_frac=0.0, vol_window=30)
    assert fm.fill_price(path, 3, "B") == pytest.approx(101.0)    # conservative


def test_simulate_ticket_produces_distribution_and_costs_bite():
    # premium drifts up steadily: latency hurts the entry, never helps
    n = 400
    closes = 100 + 0.05 * np.arange(n)
    path = _path([(c + 0.3, c - 0.3, c) for c in closes])
    t = McTicket(qty=65, target_ret=0.5, stop_ret=0.5, max_bars=300)
    res = simulate_ticket(t, path, signal_pos=0, cost_model=CM,
                          fill_model=AdverseFillModel(half_spread_frac=0.005),
                          latency=OWNER_2026_07, n_draws=300, seed=3)
    assert res["fill_rate"] > 0.9
    assert res["net_q05"] <= res["net_q50"] <= res["net_q95"]
    # dispersion must exist — latency is stochastic
    assert res["net_q95"] - res["net_q05"] > 0
    # focused desk fills earlier on an uptrend -> better median net
    res_fast = simulate_ticket(t, path, signal_pos=0, cost_model=CM,
                               fill_model=AdverseFillModel(half_spread_frac=0.005),
                               latency=FOCUSED_DESK, n_draws=300, seed=3)
    assert res_fast["net_q50"] > res["net_q50"]


def test_signal_too_late_in_day_is_no_fill_not_free_money():
    path = _path([(101, 99, 100)] * 3)
    t = McTicket(qty=65, target_ret=0.2, stop_ret=0.2, max_bars=10)
    res = simulate_ticket(t, path, signal_pos=2, cost_model=CM,
                          fill_model=AdverseFillModel(half_spread_frac=0.005),
                          n_draws=200, seed=4)
    assert res["fill_rate"] == 0.0
    assert np.isnan(res["net_mean"])
