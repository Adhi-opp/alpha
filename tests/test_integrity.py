from datetime import date, timedelta

import pandas as pd

from alpha.data import integrity, parse
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "participant_oi_20260706.csv"


def test_real_participant_day_has_no_errors():
    # the real file carries NSE's own +-1 TOTAL quirk -> warnings are fine,
    # errors are not
    df = parse.parse_participant_oi(FIXTURE, date(2026, 7, 6))
    issues = integrity.check_participant_oi_day(df)
    assert integrity.errors(issues) == []
    assert any("known NSE quirk" in i.message for i in issues)


def test_participant_sum_mismatch_detected():
    df = parse.parse_participant_oi(FIXTURE, date(2026, 7, 6))
    df.loc[df["client_type"] == "Client", "fut_idx_long"] += 1000
    issues = integrity.check_participant_oi_day(df)
    assert any("category sum != TOTAL" in i.message for i in integrity.errors(issues))


def test_participant_missing_category_detected():
    df = parse.parse_participant_oi(FIXTURE, date(2026, 7, 6))
    df = df[df["client_type"] != "FII"]
    issues = integrity.check_participant_oi_day(df)
    assert any("missing category FII" in i.message for i in integrity.errors(issues))


def _bhav_day(n_nifty=5):
    rows = []
    for i in range(n_nifty):
        rows.append({
            "trade_date": pd.Timestamp("2026-07-06"), "symbol": "NIFTY",
            "instrument": "IDO", "expiry": pd.Timestamp("2026-07-14"),
            "strike": 24000 + 50 * i, "option_type": "CE",
            "close": 100.0, "volume": 10,
        })
    return pd.DataFrame(rows)


def test_bhavcopy_missing_nifty_is_error():
    df = _bhav_day()
    df["symbol"] = "BANKNIFTY"
    issues = integrity.check_bhavcopy_day(df)
    assert any("no NIFTY index options" in i.message for i in integrity.errors(issues))


def test_bhavcopy_duplicates_detected():
    df = pd.concat([_bhav_day(), _bhav_day()], ignore_index=True)
    issues = integrity.check_bhavcopy_day(df)
    assert any("duplicate contract rows" in i.message for i in integrity.errors(issues))


def test_gap_report():
    ref = [date(2026, 7, 1) + timedelta(days=i) for i in range(3)]
    issues = integrity.gap_report("participant_oi", present=ref[:2], reference=ref)
    assert len(issues) == 1
    assert issues[0].ref == "2026-07-03"
