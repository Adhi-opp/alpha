"""Calendars derived from data, never from weekday rules.

A hardcoded expiry weekday once poisoned months of labels in the sibling
project. Here, expiry dates come from the contracts actually present in the
FO bhavcopy, and `expiry_weekday_counts` exists so any weekday assumption
can be checked against reality before it is used anywhere.
"""
from __future__ import annotations

from datetime import date

import pandas as pd


def trading_days(bhav: pd.DataFrame) -> list[date]:
    """Trading days = dates for which a bhavcopy row exists."""
    return sorted(pd.to_datetime(bhav["trade_date"]).dt.date.unique())


def expiries(
    bhav: pd.DataFrame, symbol: str, instrument: str = "IDO"
) -> list[date]:
    """All expiry dates actually traded for symbol/instrument."""
    mask = (bhav["symbol"] == symbol) & (bhav["instrument"] == instrument)
    return sorted(pd.to_datetime(bhav.loc[mask, "expiry"]).dt.date.unique())


def expiry_weekday_counts(
    bhav: pd.DataFrame, symbol: str, instrument: str = "IDO"
) -> pd.Series:
    """Weekday distribution of expiries — the anti-lore check.

    Run this before any logic that assumes an expiry weekday; expect a mix
    (holiday-shifted expiries land a day early), never assume a clean single
    weekday.
    """
    days = expiries(bhav, symbol, instrument)
    names = pd.Series([d.strftime("%A") for d in days], name="expiry_weekday")
    return names.value_counts()


def next_expiry(expiry_dates: list[date], on: date) -> date:
    """First expiry on or after `on`."""
    for d in expiry_dates:
        if d >= on:
            return d
    raise ValueError(f"no expiry on or after {on} in the derived calendar")


def is_expiry_day(expiry_dates: list[date], on: date) -> bool:
    return on in set(expiry_dates)
