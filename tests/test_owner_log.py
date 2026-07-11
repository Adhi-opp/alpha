from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from alpha.data import pit
from alpha.paper import owner_log


def test_contract_parse():
    assert owner_log.parse_contract("NIFTY2671424050CE") == ("NIFTY", 24050.0, "CE")
    assert owner_log.parse_contract("SENSEX2670976700PE") == ("SENSEX", 76700.0, "PE")
    with pytest.raises(ValueError):
        owner_log.parse_contract("BANKNIFTY26714CE")


def test_real_journal_loads_and_reconciles():
    sessions, trades = owner_log.load_journal()
    assert len(sessions) == 6
    assert len(trades) == 39
    # every transcribed session's implied charges sit in the plausible band
    for row in sessions[sessions["trades_transcribed"] > 0].itertuples():
        gross = trades.loc[trades["session_date"] == row.session_date,
                           "gross_pnl"].sum()
        assert 0 < gross - row.day_net_pnl < owner_log.MAX_PLAUSIBLE_CHARGES
    # the measured scalping profile: sub-minute-to-minutes holds
    assert trades["hold_s"].median() < 300
    assert trades["hold_s"].min() >= 5
    # the known fat-tail trade is present and correct
    worst = trades.loc[trades["gross_pnl"].idxmin()]
    assert worst["contract"] == "SENSEX2670277600PE"
    assert worst["gross_pnl"] == pytest.approx(-7156.0)


def test_validation_refuses_bad_reconciliation(tmp_path):
    (tmp_path / "sessions_x.csv").write_text(
        "session_date,exchange,note_id,day_net_pnl,n_round_trips,trades_transcribed\n"
        "2026-07-01,NSE,X,99999.0,1,1\n")
    (tmp_path / "trades_x.csv").write_text(
        "session_date,exchange,contract,expiry,qty,entry_time,exit_time,"
        "entry_wap,exit_wap\n"
        "2026-07-01,NSE,NIFTY2670724300CE,2026-07-07,65,10:00:00,10:05:00,"
        "100.0,110.0\n")
    with pytest.raises(ValueError, match="outside plausible band"):
        owner_log.load_journal(tmp_path)


def test_session_ratings_scope_on_real_data():
    sessions, _ = owner_log.load_journal()
    rated = owner_log.session_ratings(
        sessions, asof=datetime(2026, 7, 11, tzinfo=timezone.utc))
    by = {str(r.session_date.date()): r for r in rated.itertuples()}
    # 2026-07-07 was a Tuesday NIFTY expiry traded on NSE -> validated scope
    assert by["2026-07-07"].is_nifty_expiry
    assert by["2026-07-07"].scope == "validated"
    # 2026-07-10 (Friday, NSE) is not an expiry; SENSEX days are observational
    assert not by["2026-07-10"].is_nifty_expiry
    assert by["2026-07-10"].scope == "observational"
    assert by["2026-07-09"].scope == "observational"
    # every session has a rating computed strictly from prior files
    assert all(r.wi_pctile_252 is not None for r in rated.itertuples())
    assert all(r.tier in ("FAVORABLE", "NEUTRAL", "UNFAVORABLE")
               for r in rated.itertuples())


def test_attach_mae_synthetic(tmp_path):
    # a NIFTY trade whose premium dips 40% below entry mid-hold -> flagged
    ts = pd.date_range("2026-07-10 10:00", periods=10, freq="1min",
                       tz="Asia/Kolkata").tz_convert("UTC")
    closes = [100, 95, 60, 58, 70, 90, 100, 105, 108, 110.0]
    tidy = pd.DataFrame({
        "ts": ts, "side": "CE", "strike": 24050.0, "close": closes,
        "trade_date": pd.Timestamp("2026-07-10"),
        "available_at": ts[-1] + pd.Timedelta(hours=6),
    })
    pit.append("dhan_rolling_1m", tidy, ["ts", "strike", "side"], root=tmp_path)
    trades = pd.DataFrame([{
        "session_date": pd.Timestamp("2026-07-10"), "exchange": "NSE",
        "contract": "NIFTY2671424050CE", "symbol": "NIFTY",
        "strike": 24050.0, "side": "CE", "qty": 260,
        "entry_ts": ts[0], "exit_ts": ts[9],
        "entry_wap": 100.0, "exit_wap": 110.0,
    }])
    out = owner_log.attach_mae(
        trades, asof=datetime(2026, 7, 12, tzinfo=timezone.utc), root=tmp_path)
    assert out["mae_pct"].iloc[0] == pytest.approx(-0.42)
    # green trade, but the hold breached -30%: undisciplined-and-lucky
    assert out["discipline_flag"].iloc[0] == True  # noqa: E712


def test_attach_mae_no_coverage_stays_null():
    _, trades = owner_log.load_journal()
    out = owner_log.attach_mae(
        trades, asof=datetime(2026, 7, 11, tzinfo=timezone.utc))
    # tidy premium data ends 2026-07-06; all July trades are later or BSE
    assert out["mae_pct"].isna().all()
    assert out["discipline_flag"].isna().all()
