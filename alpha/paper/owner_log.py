"""Owner log — the forward instrument that will promote (or kill) H-003.

The owner keeps scalping exactly as he does; this module turns his contract
notes (hand-curated into journal/*.csv) plus the system's own data into the
graded record: per-session rating vs realized P&L, per-trade hold times,
and MAE-based discipline flags COMPUTED from 1-min premium data at the
note's timestamps — never hand-entered, never trusted from memory.

Scope discipline: H-003 validated NIFTY expiry sessions only. Sessions that
are not NIFTY-expiry (including all SENSEX days until a BSE study exists)
are logged as scope="observational" — recorded, reported, never graded as
if the study covered them.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from alpha.config import IST, PROJECT_ROOT
from alpha.console.state import _tier
from alpha.data import pit
from alpha.study.h001r import client_write_intensity

JOURNAL_DIR = PROJECT_ROOT / "journal"
MAE_FLAG_FRAC = -0.30          # MAE beyond -30% of entry premium while held
MAX_PLAUSIBLE_CHARGES = 2000.0  # per-session reconciliation band (rupees)
_CONTRACT_RE = re.compile(
    r"^(NIFTY|SENSEX)(\d{2})([1-9OND])(\d{2})(\d+)(CE|PE)$")


def parse_contract(c: str) -> tuple[str, float, str]:
    """'NIFTY2671424050CE' -> ('NIFTY', 24050.0, 'CE')."""
    m = _CONTRACT_RE.match(c)
    if not m:
        raise ValueError(f"unparseable contract {c!r}")
    return m.group(1), float(m.group(5)), m.group(6)


def load_journal(journal_dir: Path | None = None
                 ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load + validate the committed journal. Refuses inconsistent data."""
    d = journal_dir or JOURNAL_DIR
    sessions = pd.concat([pd.read_csv(f, parse_dates=["session_date"])
                          for f in sorted(d.glob("sessions_*.csv"))],
                         ignore_index=True)
    trades = pd.concat([pd.read_csv(f, parse_dates=["session_date", "expiry"])
                        for f in sorted(d.glob("trades_*.csv"))],
                       ignore_index=True)

    for col in ("entry_time", "exit_time"):
        trades[col.replace("time", "ts")] = pd.to_datetime(
            trades["session_date"].dt.strftime("%Y-%m-%d") + " " + trades[col]
        ).dt.tz_localize(IST)
    trades["hold_s"] = (trades["exit_ts"] - trades["entry_ts"]).dt.total_seconds()
    trades["gross_pnl"] = (trades["exit_wap"] - trades["entry_wap"]) * trades["qty"]
    trades["ret_pct"] = (trades["exit_wap"] - trades["entry_wap"]) / trades["entry_wap"]
    parsed = trades["contract"].map(parse_contract)
    trades["symbol"] = parsed.map(lambda t: t[0])
    trades["strike"] = parsed.map(lambda t: t[1])
    trades["side"] = parsed.map(lambda t: t[2])

    problems = []
    if (trades["hold_s"] <= 0).any():
        problems.append("trade with exit_time <= entry_time")
    if (trades["qty"] <= 0).any():
        problems.append("trade with non-positive qty")
    counts = trades.groupby("session_date").size()
    for row in sessions.itertuples():
        n = int(counts.get(row.session_date, 0))
        if n != row.trades_transcribed:
            problems.append(
                f"{row.session_date.date()}: {n} trades vs "
                f"trades_transcribed={row.trades_transcribed}")
        if n == 0:
            continue
        gross = float(trades.loc[trades["session_date"] == row.session_date,
                                 "gross_pnl"].sum())
        implied_charges = gross - row.day_net_pnl
        if not (0 < implied_charges < MAX_PLAUSIBLE_CHARGES):
            problems.append(
                f"{row.session_date.date()}: gross {gross:.2f} vs net "
                f"{row.day_net_pnl:.2f} implies charges "
                f"{implied_charges:.2f} — outside plausible band")
    if problems:
        raise ValueError("journal validation failed: " + "; ".join(problems))
    return sessions, trades


def session_ratings(sessions: pd.DataFrame, asof: datetime | None = None,
                    root: Path | None = None) -> pd.DataFrame:
    """What the console WOULD have said before each session's open: wi
    percentile from files strictly before the session date, expiry check,
    and the H-003 scope of the rating."""
    asof = asof or datetime.now(timezone.utc)
    wi = client_write_intensity(pit.load("participant_oi", asof, root=root))
    bhav = pit.load("fo_bhavcopy", asof, root=root,
                    columns=["symbol", "instrument", "expiry", "trade_date",
                             "available_at"])
    nifty_expiries = set(pd.to_datetime(
        bhav.loc[(bhav["symbol"] == "NIFTY") & (bhav["instrument"] == "IDO"),
                 "expiry"]).dt.normalize().unique())

    rows = []
    for s in sessions.itertuples():
        hist = wi[wi["trade_date"] < s.session_date]
        pctile = tier = None
        if len(hist) >= 20:
            tail = hist["wi"].tail(252)
            pctile = round(float((tail <= float(tail.iloc[-1])).mean() * 100), 1)
            tier = _tier(pctile)
        is_nifty_expiry = pd.Timestamp(s.session_date).normalize() in nifty_expiries
        rows.append({
            "session_date": s.session_date,
            "wi_pctile_252": pctile,
            "tier": tier,
            "is_nifty_expiry": bool(is_nifty_expiry),
            "scope": ("validated" if (s.exchange == "NSE" and is_nifty_expiry)
                      else "observational"),
        })
    return sessions.merge(pd.DataFrame(rows), on="session_date")


#: symbol -> tidy premium dataset. SENSEX is single-source (Dhan only — no
#: BSE bhavcopy layer exists to cross-check): fine for MAE diagnostics,
#: NOT census-certified for studies.
MAE_DATASETS = {"NIFTY": "dhan_rolling_1m", "SENSEX": "dhan_rolling_1m_sensex"}


def attach_mae(trades: pd.DataFrame, asof: datetime | None = None,
               root: Path | None = None) -> pd.DataFrame:
    """MAE per trade from our own 1-min premium closes between the note's
    entry and exit timestamps. NaN (with reason) wherever coverage is
    missing — never guessed."""
    asof = asof or datetime.now(timezone.utc)
    out = trades.copy()
    out["mae_pct"] = np.nan
    out["mae_reason"] = "no premium data coverage"
    tidys = {}
    for sym, dataset in MAE_DATASETS.items():
        try:
            tidys[sym] = pit.load(dataset, asof, root=root,
                                  columns=["ts", "side", "strike", "close",
                                           "trade_date", "available_at"])
        except FileNotFoundError:
            continue
    for i, t in out.iterrows():
        tidy = tidys.get(t["symbol"])
        if tidy is None or t["session_date"] not in set(tidy["trade_date"].unique()):
            continue
        day = tidy[(tidy["trade_date"] == t["session_date"])
                   & (tidy["strike"] == t["strike"])
                   & (tidy["side"] == t["side"])]
        # bars are stamped at minute START: floor the entry so a sub-minute
        # hold still sees the bar it lived inside
        window = day[(day["ts"] >= t["entry_ts"].floor("min"))
                     & (day["ts"] <= t["exit_ts"])]
        if window.empty:
            out.loc[i, "mae_reason"] = "no bars inside hold window"
            continue
        worst = float(window["close"].min())
        # adverse excursion is never positive; closes above entry for the
        # whole hold = no adverse excursion VISIBLE at 1-min granularity
        # (sub-minute wicks are invisible — a measurement floor, disclosed)
        out.loc[i, "mae_pct"] = min(0.0, (worst - t["entry_wap"]) / t["entry_wap"])
        out.loc[i, "mae_reason"] = ""
    return _flag(out)


def _flag(trades: pd.DataFrame) -> pd.DataFrame:
    flag = pd.Series(pd.NA, index=trades.index, dtype="boolean")
    known = trades["mae_pct"].notna()
    flag[known] = trades.loc[known, "mae_pct"] <= MAE_FLAG_FRAC
    trades["discipline_flag"] = flag
    return trades


def summary(asof: datetime | None = None, root: Path | None = None,
            journal_dir: Path | None = None) -> dict:
    sessions, trades = load_journal(journal_dir)
    rated = session_ratings(sessions, asof, root=root)
    trades = attach_mae(trades, asof, root=root)
    validated = rated[rated["scope"] == "validated"]
    mae_done = trades["mae_pct"].notna()
    return {
        "sessions_logged": int(len(sessions)),
        "sessions_validated_scope": int(len(validated)),
        "sessions_target": 40,
        "trades_logged": int(len(trades)),
        "day_pnl_total": round(float(sessions["day_net_pnl"].sum()), 2),
        "median_hold_s": float(trades["hold_s"].median()),
        "win_rate_gross": round(float((trades["gross_pnl"] > 0).mean()), 3),
        "mae_computed": int(mae_done.sum()),
        "discipline_flags": int((trades["discipline_flag"] == True).sum()),  # noqa: E712
        "by_session": rated[["session_date", "exchange", "day_net_pnl",
                             "wi_pctile_252", "tier", "is_nifty_expiry",
                             "scope"]].assign(
            session_date=lambda d: d["session_date"].dt.date.astype(str)
        ).to_dict("records"),
    }
