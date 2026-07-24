import json

import pytest

from alpha.live.cockpit import LOTS, MAXPAIN_SAMPLE_EVERY, Cockpit
from alpha.live.recorder import Recorder
from alpha.live import replay
from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07 as COST

IDX = "NSE_INDEX|Nifty 50"
_MAP = {IDX: {"symbol": "NIFTY", "kind": "index"}}
for i, (strike, side) in enumerate(
        [(24000.0, "CE"), (24000.0, "PE"), (24100.0, "CE"),
         (24100.0, "PE"), (24200.0, "CE"), (24200.0, "PE")]):
    _MAP[f"NSE_FO|{i}"] = {"symbol": "NIFTY", "kind": "option",
                           "expiry": "2026-07-28", "strike": strike,
                           "side": side}
_KEY = {(m["strike"], m["side"]): k for k, m in _MAP.items()
        if m["kind"] == "option"}


def _tick(key, t, ltp, oi=None, depth=None, **extra):
    ev = {"kind": "tick", "key": key, "t_local_ns": t, "provider_ts": t // 10**6,
          "feed_type": "live_feed", "ltp": ltp, "ltt": t // 10**6,
          "ltq": 65, "cp": 0.0, "atp": ltp, "vtt": 100, "oi": oi or 0.0,
          "iv": 12.0, "tbq": 10.0, "tsq": 10.0,
          "greeks": {"delta": 0.5, "theta": -5.0, "gamma": 0.001,
                     "vega": 8.0, "rho": 0.0},
          "depth": depth or []}
    ev.update(extra)
    return ev


def _events():
    t = 1_000_000_000_000
    evs = [
        {"kind": "session_start", "t_local_ns": t, "symbols": ["NIFTY"],
         "spots": {"NIFTY": 24100.0},
         "chains": {"NIFTY": {"expiry": "2026-07-28", "future_key": None,
                              "n_strikes": 3}},
         "bands": {"NIFTY": [24000.0, 24100.0, 24200.0]}, "n_keys": 7,
         "half_width": 1, "keep_raw": False},
        {"kind": "ws_connected", "t_local_ns": t + 1, "attempt": 1,
         "n_active_keys": 7},
        {"kind": "market_info", "t_local_ns": t + 2, "provider_ts": 1,
         "segments": {"NSE_FO": "NORMAL_OPEN", "BSE_FO": "NORMAL_OPEN"}},
        {"kind": "index", "key": IDX, "t_local_ns": t + 3,
         "provider_ts": 1, "feed_type": "live_feed", "ltp": 24120.0,
         "ltt": 1, "cp": 24000.0},
        # OI book: CE 100/50/200, PE 300/50/80 -> max pain 24100 (payouts
        # 21,000 / 18,000 / 25,000), walls order 24000(400) 24200(280)
        # 24100(100)
        _tick(_KEY[(24000.0, "CE")], t + 10, 150.0, oi=100.0),
        _tick(_KEY[(24000.0, "PE")], t + 11, 30.0, oi=300.0),
        _tick(_KEY[(24100.0, "CE")], t + 12, 100.0, oi=50.0,
              depth=[[100.0, 65.0, 101.0, 65.0]]),
        _tick(_KEY[(24100.0, "PE")], t + 13, 50.0, oi=50.0,
              depth=[[49.5, 65.0, 50.5, 130.0]]),
        _tick(_KEY[(24200.0, "CE")], t + 14, 60.0, oi=200.0),
        _tick(_KEY[(24200.0, "PE")], t + 15, 90.0, oi=80.0),
        # ATM CE moves 100 -> 102 -> 101: cum |dltp| = 3.0
        _tick(_KEY[(24100.0, "CE")], t + 16, 102.0, oi=50.0,
              depth=[[100.0, 65.0, 101.0, 65.0]]),
        _tick(_KEY[(24100.0, "CE")], t + 17, 101.0, oi=50.0,
              depth=[[100.0, 65.0, 101.0, 65.0]]),
    ]
    # pad oi ticks so the max-pain sampler fires once more (n=1, then
    # n=MAXPAIN_SAMPLE_EVERY+1) with the full book seen
    for j in range(MAXPAIN_SAMPLE_EVERY + 1 - 8):
        evs.append(_tick(_KEY[(24200.0, "PE")], t + 100 + j, 90.0, oi=80.0))
    evs.append({"kind": "session_end", "t_local_ns": t + 10_000,
                "degraded_reason": None})
    return evs


def _reduced():
    cp = Cockpit(_MAP)
    for ev in _events():
        cp.apply(ev)
    return cp


def test_spot_atm_and_walls():
    cp = _reduced()
    assert cp.spots["NIFTY"] == 24120.0          # index tick beats seed spot
    assert cp.atm_strike("NIFTY") == 24100.0
    walls = cp.oi_walls("NIFTY")
    assert [w["strike"] for w in walls] == [24000.0, 24200.0, 24100.0]
    assert walls[0]["ce_oi"] == 100.0 and walls[0]["pe_oi"] == 300.0
    # no OI change during the session -> zero migration
    assert walls[0]["d_ce"] == 0.0 and walls[0]["d_pe"] == 0.0


def test_max_pain_hand_computed():
    cp = _reduced()
    mp = cp.max_pain("NIFTY")
    assert mp["strike"] == 24100.0
    # sampler: first oi tick saw only 24000 (its own strike is the whole
    # book -> pain 0 there), the padded resample saw the full book
    assert [k for _, k in mp["history"]] == [24000.0, 24100.0]


def test_spread_table_is_the_live_hurdle():
    cp = _reduced()
    rows = {(r["strike"], r["side"]): r
            for r in cp.spread_table("NIFTY", width=1)}
    r = rows[(24100.0, "CE")]
    assert r["bid"] == 100.0 and r["ask"] == 101.0
    assert r["spread"] == pytest.approx(1.0)
    assert r["mid"] == pytest.approx(100.5)
    assert r["spread_pct"] == pytest.approx(1.0, abs=0.01)
    lot = LOTS["NIFTY"]
    statutory = COST.round_trip_cost(100.5 * lot, 100.5 * lot)
    expect = (1.0 * lot + statutory) / (100.5 * lot) * 100
    assert r["breakeven_pct"] == pytest.approx(expect, abs=0.01)
    # a side with no quotes reports None, never a guess
    assert rows[(24000.0, "CE")]["spread"] is None


def test_churn_panel_descriptive():
    cp = _reduced()
    out = cp.churn_panel("NIFTY")
    assert out["atm"] == 24100.0
    # CE cum |dltp| = 3.0, PE never moved -> 3.0 * lot
    assert out["churn_rs_per_lot"] == pytest.approx(3.0 * LOTS["NIFTY"])
    assert out["hurdle_rs"] is not None and out["hurdle_multiples"] is not None


def test_feed_health_and_degraded_banner():
    cp = _reduced()
    h = cp.feed_health()
    assert h["banner"] == "SESSION ENDED"
    assert h["segments_gate_open"] is True
    assert h["reconnects"] == 0 and h["errors"] == 0
    # a degraded session end must dominate the banner
    cp2 = Cockpit(_MAP)
    for ev in _events()[:-1]:
        cp2.apply(ev)
    cp2.apply({"kind": "ws_connected", "t_local_ns": 2, "attempt": 2,
               "n_active_keys": 7})
    cp2.apply({"kind": "session_end", "t_local_ns": 3,
               "degraded_reason": "recorder queue full; capture halted"})
    h2 = cp2.feed_health()
    assert h2["reconnects"] == 1
    assert h2["banner"].startswith("DEGRADED")


def test_reducer_is_deterministic():
    a = json.dumps(_reduced().snapshot(), sort_keys=True, default=str)
    b = json.dumps(_reduced().snapshot(), sort_keys=True, default=str)
    assert a == b


def test_replay_path_equals_direct_reduction(tmp_path):
    """The proof-layer contract: reducing the recorded file reproduces the
    live reduction exactly — same function, same stream, same numbers."""
    rec = Recorder(tmp_path, keep_raw=False)
    evs = _events()
    rec.write_batch(evs, [])
    rec.close({"label": "test"})
    cp = Cockpit(_MAP)
    n = 0
    for ev in replay.events(tmp_path):
        cp.apply(ev)
        n += 1
    assert n == len(evs)
    direct = json.dumps(_reduced().snapshot(), sort_keys=True, default=str)
    replayed = json.dumps(cp.snapshot(), sort_keys=True, default=str)
    assert direct == replayed
