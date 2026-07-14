"""Acceptance tests for the 2026-07-14 hardening round: analytics-first
tokens, clock/market gating, the timer-driven drill, date-aware Dhan pulls,
and honest forward-vs-retro owner-log accounting."""
import asyncio
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.live import provider_upstox as up
from alpha.live.auth import load_upstox_token
from alpha.live.collector import SessionCapture
from alpha.paper import owner_log
from scripts.live_probe import (MAX_CLOCK_SKEW_S, ProbeCapture,
                                evaluate_gate)
from scripts.dhan_pull_rolling import build_parser, main as dhan_main


# ---- token preference -------------------------------------------------------

def test_analytics_token_preferred():
    token, source = load_upstox_token(
        {"UPSTOX_ANALYTICS_TOKEN": "a-token", "UPSTOX_ACCESS_TOKEN": "o-token"})
    assert (token, source) == ("a-token", "analytics")


def test_oauth_fallback_when_no_analytics():
    token, source = load_upstox_token(
        {"UPSTOX_ANALYTICS_TOKEN": "", "UPSTOX_ACCESS_TOKEN": "o-token"})
    assert (token, source) == ("o-token", "oauth")


def test_no_token_raises_without_leaking():
    with pytest.raises(RuntimeError) as ei:
        load_upstox_token({})
    assert "UPSTOX_ANALYTICS_TOKEN" in str(ei.value)   # names vars, not values


# ---- probe gate -------------------------------------------------------------

_LIVE_SUMMARY = {
    "segment_statuses": {"NSE_FO": "NORMAL_OPEN", "BSE_FO": "NORMAL_OPEN"},
    "live_feed_count": 5000, "initial_feed_count": 90,
    "freshest_trade_age_s": 1.2, "drill_resub_to_first_tick_ms": 350.0,
    "degraded_reason": None, "errors": [],
}


def test_gate_green_on_live_market():
    status, failures = evaluate_gate(dict(_LIVE_SUMMARY), preflight_skew_s=0.4)
    assert status == "GREEN" and failures == []


def test_gate_clock_skew_is_red():
    status, failures = evaluate_gate(dict(_LIVE_SUMMARY),
                                     preflight_skew_s=MAX_CLOCK_SKEW_S + 1)
    assert status == "RED"
    assert any("CLOCK_INVALID" in f for f in failures)


def test_gate_closed_market_is_partial_never_green():
    closed = dict(_LIVE_SUMMARY)
    closed["segment_statuses"] = {"NSE_FO": "NORMAL_CLOSE",
                                  "BSE_FO": "NORMAL_CLOSE"}
    closed["live_feed_count"] = 0
    closed["freshest_trade_age_s"] = 21600.0
    closed["drill_resub_to_first_tick_ms"] = None
    status, failures = evaluate_gate(closed, preflight_skew_s=0.1)
    assert status == "PARTIAL"
    assert any("market closed" in f for f in failures)
    assert any("live_feed" in f for f in failures)


def test_gate_degraded_capture_is_red():
    bad = dict(_LIVE_SUMMARY)
    bad["degraded_reason"] = "recorder queue full; capture halted"
    status, failures = evaluate_gate(bad, preflight_skew_s=0.1)
    assert status == "RED"


# ---- clock skew helper ------------------------------------------------------

def test_clock_skew_sign_and_magnitude():
    # provider 12h ahead of local (the measured incident, inverted sign)
    local_ns = 1_000_000_000 * 1_000_000_000
    provider_ms = (1_000_000_000 + 43_200) * 1_000
    assert up.clock_skew_s(provider_ms, local_ns) == pytest.approx(-43_200)


# ---- independent drill timer ------------------------------------------------

def test_drill_fires_without_any_ticks_and_survives_reconnect(tmp_path):
    async def scenario():
        cap = ProbeCapture("t", symbols=("NIFTY",), out_root=tmp_path,
                           drill_after_s=0.01, drill_resub_s=0.01,
                           drill_retry_s=0.01)
        chain = up.Chain(symbol="NIFTY", expiry="2026-07-21",
                         index_key="NSE_INDEX|Nifty 50", future_key=None,
                         options={(float(k), s): f"NSE_FO|{k}{s}"
                                  for k in range(24000, 24501, 50)
                                  for s in ("CE", "PE")},
                         strikes=[float(k) for k in range(24000, 24501, 50)])
        cap.chains["NIFTY"] = chain
        cap.bands["NIFTY"] = chain.strikes[:]
        sent = []
        calls = {"n": 0}

        async def flaky_send(change):
            calls["n"] += 1
            if calls["n"] == 1:      # first attempt: socket down (reconnect)
                return False
            sent.append(change.event["kind"])
            return True

        cap.send_change = flaky_send
        await cap._drill_loop()      # completes with NO tick traffic at all
        return sent

    sent = asyncio.run(scenario())
    assert sent == ["drill_unsub", "drill_resub"]


# ---- closed-market reconnect backoff ---------------------------------------

def test_silent_backoff_only_when_provider_says_closed(tmp_path):
    cap = SessionCapture("t", symbols=("NIFTY",), out_root=tmp_path)
    assert cap.market_open() is None            # nothing heard yet
    assert cap._silent_backoff_s() == 0.0       # unknown -> reconnect fast
    cap.market_status = {"NSE_FO": "NORMAL_OPEN", "BSE_FO": "NORMAL_OPEN"}
    assert cap.market_open() is True
    assert cap._silent_backoff_s() == 0.0       # open + silent = anomalous
    cap.market_status = {"NSE_FO": "NORMAL_CLOSE", "BSE_FO": "NORMAL_CLOSE"}
    assert cap.market_open() is False
    assert cap._silent_backoff_s() > 0          # closed + silent = correct


# ---- Dhan incremental CLI ---------------------------------------------------

def test_dhan_parser_dates():
    args = build_parser().parse_args(
        ["--symbol", "sensex", "--start", "2026-07-11", "--end", "2026-07-14"])
    assert args.start == date(2026, 7, 11)
    assert args.end == date(2026, 7, 14)


def test_dhan_rejects_inverted_and_future_end(capsys):
    assert dhan_main(["--start", "2026-07-14", "--end", "2026-07-10"]) == 2
    assert dhan_main(["--end", "2099-01-01"]) == 2


# ---- forward vs retro owner-log accounting ----------------------------------

def test_forward_ratings_refuse_retro_rows(tmp_path):
    (tmp_path / "ratings_forward.csv").write_text(
        "session_date,wi_pctile_252,tier,is_nifty_expiry,computed_from,"
        "emitted_at_ist,outcome,note\n"
        "2026-07-07,28.6,UNFAVORABLE,True,2026-07-06,x,pending,retro leak\n")
    with pytest.raises(ValueError, match="retro"):
        owner_log.load_forward_ratings(tmp_path)


def test_forward_ratings_real_file_counts():
    fwd = owner_log.load_forward_ratings()
    assert len(fwd) >= 1                                    # 2026-07-14 emitted
    first = fwd.iloc[0]
    assert str(first["session_date"].date()) == "2026-07-14"
    assert first["wi_pctile_252"] == pytest.approx(52.8)
    assert first["tier"] == "NEUTRAL"
    assert (fwd["session_date"] >= owner_log.H004_FORWARD_START).all()


def test_summary_separates_retro_from_forward():
    s = owner_log.summary()
    # the retro seed (2026-07-07 validated session) must NOT be presented
    # as H-004 progress
    assert s["retro_validated_sessions"] == 1
    assert s["h004_ratings_emitted"] >= 1
    assert s["h004_finalized"] <= s["h004_ratings_emitted"]
    assert s["h004_target"] == 40
    assert "sessions_validated_scope" not in s   # the misleading field is gone
