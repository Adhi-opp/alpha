from datetime import date

import pandas as pd
import pytest

from alpha.data import calendars


def _bhav():
    # NIFTY weekly expiries: three Tuesdays and one holiday-shifted Monday
    rows = []
    expiries = ["2026-06-09", "2026-06-15", "2026-06-23", "2026-06-30"]  # Tue, MON, Tue, Tue
    for i, (td, xp) in enumerate(zip(
        ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"], expiries
    )):
        rows.append({"trade_date": pd.Timestamp(td), "symbol": "NIFTY",
                     "instrument": "IDO", "expiry": pd.Timestamp(xp)})
        rows.append({"trade_date": pd.Timestamp(td), "symbol": "NIFTY",
                     "instrument": "IDF", "expiry": pd.Timestamp("2026-06-30")})
        rows.append({"trade_date": pd.Timestamp(td), "symbol": "BANKNIFTY",
                     "instrument": "IDO", "expiry": pd.Timestamp("2026-06-25")})
    return pd.DataFrame(rows)


def test_trading_days_sorted_unique():
    days = calendars.trading_days(_bhav())
    assert days == [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3), date(2026, 6, 4)]


def test_expiries_filters_symbol_and_instrument():
    xs = calendars.expiries(_bhav(), "NIFTY", "IDO")
    assert xs == [date(2026, 6, 9), date(2026, 6, 15), date(2026, 6, 23), date(2026, 6, 30)]
    assert calendars.expiries(_bhav(), "BANKNIFTY", "IDO") == [date(2026, 6, 25)]


def test_weekday_counts_expose_holiday_shifts():
    counts = calendars.expiry_weekday_counts(_bhav(), "NIFTY", "IDO")
    assert counts["Tuesday"] == 3
    assert counts["Monday"] == 1  # the anti-lore check: never a clean single weekday


def test_next_expiry():
    xs = calendars.expiries(_bhav(), "NIFTY", "IDO")
    assert calendars.next_expiry(xs, date(2026, 6, 10)) == date(2026, 6, 15)
    assert calendars.next_expiry(xs, date(2026, 6, 15)) == date(2026, 6, 15)
    with pytest.raises(ValueError):
        calendars.next_expiry(xs, date(2026, 7, 1))
