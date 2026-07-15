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
    assert len(sessions) == 8
    assert len(trades) == 53
    # every transcribed session's implied charges sit in the plausible band
    # (turnover-proportional: the 2026-07-14 session's Rs2,310 of charges on
    # ~Rs1.1M turnover is legitimate)
    for row in sessions[sessions["trades_transcribed"] > 0].itertuples():
        day = trades[trades["session_date"] == row.session_date]
        gross = day["gross_pnl"].sum()
        turnover = ((day["entry_wap"] + day["exit_wap"]) * day["qty"]).sum()
        assert (0 < gross - row.day_net_pnl
                < owner_log.plausible_charges_hi(turnover))
    # the measured scalping profile: sub-minute-to-minutes holds
    assert trades["hold_s"].median() < 300
    assert trades["hold_s"].min() >= 5
    # the known fat-tail trade is present and correct
    worst = trades.loc[trades["gross_pnl"].idxmin()]
    assert worst["contract"] == "SENSEX2670277600PE"
    assert worst["gross_pnl"] == pytest.approx(-7156.0)
    # the overnight trade: entered 2026-07-13, realized at Tuesday's open
    on = trades[(trades["contract"] == "NIFTY2671424250PE")
                & (trades["session_date"] == pd.Timestamp("2026-07-14"))]
    assert len(on) == 1
    assert str(on["entry_ts"].iloc[0].date()) == "2026-07-13"
    assert on["hold_s"].iloc[0] > 20 * 3600
    assert on["gross_pnl"].iloc[0] == pytest.approx(8823.75)


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
        sessions, asof=datetime(2026, 7, 15, tzinfo=timezone.utc))
    by = {str(r.session_date.date()): r for r in rated.itertuples()}
    # 2026-07-07 was a Tuesday NIFTY expiry traded on NSE -> validated scope
    assert by["2026-07-07"].is_nifty_expiry
    assert by["2026-07-07"].scope == "validated"
    # 2026-07-10 (Friday, NSE) is not an expiry; SENSEX days are observational
    assert not by["2026-07-10"].is_nifty_expiry
    assert by["2026-07-10"].scope == "observational"
    assert by["2026-07-09"].scope == "observational"
    # 2026-07-14 = first H-004 forward expiry session; Monday before it is not
    assert by["2026-07-14"].is_nifty_expiry
    assert by["2026-07-14"].scope == "validated"
    assert by["2026-07-14"].wi_pctile_252 == pytest.approx(52.8)
    assert by["2026-07-13"].scope == "observational"
    # every session has a rating computed strictly from prior files
    assert all(r.wi_pctile_252 is not None for r in rated.itertuples())
    assert all(r.tier in ("FAVORABLE", "NEUTRAL", "UNFAVORABLE")
               for r in rated.itertuples())


def test_charges_band_is_turnover_aware():
    assert owner_log.plausible_charges_hi(0) == owner_log.MAX_PLAUSIBLE_CHARGES
    assert owner_log.plausible_charges_hi(100_000) == owner_log.MAX_PLAUSIBLE_CHARGES
    # ~Rs1.1M turnover session: real charges Rs2,310 must fit
    assert owner_log.plausible_charges_hi(1_100_000) == pytest.approx(5_500)


def test_overnight_mae_spans_both_days(tmp_path):
    # premium dips hard on the ENTRY day's afternoon; closes higher next
    # open — the excursion is only visible if entry-day bars are included
    ts1 = pd.date_range("2026-07-13 12:00", periods=5, freq="1min",
                        tz="Asia/Kolkata").tz_convert("UTC")
    ts2 = pd.date_range("2026-07-14 09:15", periods=2, freq="1min",
                        tz="Asia/Kolkata").tz_convert("UTC")
    tidy = pd.concat([
        pd.DataFrame({"ts": ts1, "side": "PE", "strike": 24250.0,
                      "close": [160.0, 150.0, 100.0, 140.0, 155.0],
                      "trade_date": pd.Timestamp("2026-07-13"),
                      "available_at": ts1[-1] + pd.Timedelta(hours=6)}),
        pd.DataFrame({"ts": ts2, "side": "PE", "strike": 24250.0,
                      "close": [204.0, 205.0],
                      "trade_date": pd.Timestamp("2026-07-14"),
                      "available_at": ts2[-1] + pd.Timedelta(hours=6)}),
    ], ignore_index=True)
    pit.append("dhan_rolling_1m", tidy, ["ts", "strike", "side"], root=tmp_path)
    trades = pd.DataFrame([{
        "session_date": pd.Timestamp("2026-07-14"), "exchange": "NSE",
        "contract": "NIFTY2671424250PE", "symbol": "NIFTY",
        "strike": 24250.0, "side": "PE", "qty": 195,
        "entry_ts": ts1[0], "exit_ts": ts2[0],
        "entry_wap": 159.30, "exit_wap": 204.55,
    }])
    out = owner_log.attach_mae(
        trades, asof=datetime(2026, 7, 15, tzinfo=timezone.utc), root=tmp_path)
    # worst close 100 on the entry day -> MAE (100-159.30)/159.30 = -37.2%
    assert out["mae_pct"].iloc[0] == pytest.approx(-0.3723, abs=1e-3)
    assert out["discipline_flag"].iloc[0] == True  # noqa: E712


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

    # sub-minute hold INSIDE one bar: entry bar floored in, clip at zero
    sub = trades.assign(
        entry_ts=ts[5] + pd.Timedelta(seconds=10),
        exit_ts=ts[5] + pd.Timedelta(seconds=45))
    out2 = owner_log.attach_mae(
        sub, asof=datetime(2026, 7, 12, tzinfo=timezone.utc), root=tmp_path)
    assert out2["mae_pct"].iloc[0] == pytest.approx(-0.10)  # bar close 90
    sub3 = trades.assign(entry_wap=80.0,
                         entry_ts=ts[5] + pd.Timedelta(seconds=10),
                         exit_ts=ts[5] + pd.Timedelta(seconds=45))
    out3 = owner_log.attach_mae(
        sub3, asof=datetime(2026, 7, 12, tzinfo=timezone.utc), root=tmp_path)
    assert out3["mae_pct"].iloc[0] == 0.0    # closes never below entry -> 0


def test_attach_mae_no_coverage_stays_null(tmp_path):
    # an empty derived root = zero coverage -> every MAE stays null, flagged
    _, trades = owner_log.load_journal()
    out = owner_log.attach_mae(
        trades, asof=datetime(2026, 7, 11, tzinfo=timezone.utc), root=tmp_path)
    assert out["mae_pct"].isna().all()
    assert out["discipline_flag"].isna().all()
    assert (out["mae_reason"] == "no premium data coverage").all()
