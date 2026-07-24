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
#: reconciliation band floor (rupees). Real charges scale with turnover
#: (STT 0.15% sell-side is the dominant term), so the ceiling is
#: turnover-proportional — the 2026-07-14 session's legitimate Rs2,310 of
#: charges on ~Rs1.1M premium turnover exceeded the old flat Rs2,000 band.
MAX_PLAUSIBLE_CHARGES = 2000.0
CHARGES_TURNOVER_FRAC = 0.005   # generous: measured sessions run ~0.2%


def plausible_charges_hi(turnover: float) -> float:
    """Upper bound for a session's implied charges given its premium
    turnover (sum of (entry+exit) WAP x qty over its trades)."""
    return max(MAX_PLAUSIBLE_CHARGES, CHARGES_TURNOVER_FRAC * turnover)
#: first H-004 forward session (mirrors the frozen ledger/H004 pre-reg;
#: journal sessions BEFORE this are the retro seed, excluded from H-004)
H004_FORWARD_START = pd.Timestamp("2026-07-14")
H004_TARGET = 40
#: emission guards, mirror of the frozen H-004 text: a rating may only be
#: emitted from a participant file at most this stale, over at least this
#: much wi history. Enforced HERE (at emission) — never re-applied after
#: the fact by the evaluator, which trusts only the emission ledger.
H004_MAX_STALE_DAYS = 4
H004_MIN_WI_HISTORY = 20
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

    # entry_date (optional column): an overnight position's entry day —
    # blank means the trade opened and closed inside its session
    if "entry_date" in trades.columns:
        entry_base = pd.to_datetime(trades["entry_date"]).fillna(
            trades["session_date"])
    else:
        entry_base = trades["session_date"]
    trades["entry_ts"] = pd.to_datetime(
        entry_base.dt.strftime("%Y-%m-%d") + " " + trades["entry_time"]
    ).dt.tz_localize(IST)
    trades["exit_ts"] = pd.to_datetime(
        trades["session_date"].dt.strftime("%Y-%m-%d") + " " + trades["exit_time"]
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
        day = trades[trades["session_date"] == row.session_date]
        gross = float(day["gross_pnl"].sum())
        turnover = float(((day["entry_wap"] + day["exit_wap"])
                          * day["qty"]).sum())
        implied_charges = gross - row.day_net_pnl
        if not (0 < implied_charges < plausible_charges_hi(turnover)):
            problems.append(
                f"{row.session_date.date()}: gross {gross:.2f} vs net "
                f"{row.day_net_pnl:.2f} implies charges "
                f"{implied_charges:.2f} — outside plausible band "
                f"(hi {plausible_charges_hi(turnover):.0f})")
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
        # an overnight hold spans two sessions: include the entry day's
        # bars too, or the excursion between entry and the next open is
        # invisible
        hold_dates = {t["session_date"],
                      pd.Timestamp(t["entry_ts"].date())}
        day = tidy[(tidy["trade_date"].isin(hold_dates))
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


def load_forward_ratings(journal_dir: Path | None = None) -> pd.DataFrame:
    """H-004 forward rating emissions (journal/ratings_forward.csv) —
    committed evidence that a rating existed for each forward expiry
    session, with its settlement state ('pending' until the contract note
    is journaled or abstention is confirmed). Empty frame if none yet."""
    d = journal_dir or JOURNAL_DIR
    f = d / "ratings_forward.csv"
    cols = ["session_date", "wi_pctile_252", "tier", "is_nifty_expiry",
            "computed_from", "emitted_at_ist", "outcome", "note"]
    if not f.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(f, parse_dates=["session_date"])
    bad = df[df["session_date"] < H004_FORWARD_START]
    if len(bad):
        raise ValueError(
            f"ratings_forward.csv contains pre-forward rows "
            f"{[str(x.date()) for x in bad['session_date']]} — the retro "
            f"seed is excluded from H-004 by the frozen pre-registration")
    return df


def compute_forward_rating(session_date, asof: datetime | None = None,
                           root: Path | None = None) -> dict:
    """The pre-open rating for one session, computed for EMISSION into
    ratings_forward.csv — the console formula (most recent strictly-prior
    wi file vs its trailing 252) behind the frozen guards. Raises when the
    stale guard or history floor fails: a refused emission is how a session
    goes unrated (excluded AND disclosed), never a silent number."""
    asof = asof or datetime.now(timezone.utc)
    session_date = pd.Timestamp(session_date).normalize()
    wi = client_write_intensity(pit.load("participant_oi", asof, root=root))
    hist = wi[wi["trade_date"] < session_date]
    if len(hist) < H004_MIN_WI_HISTORY:
        raise ValueError(
            f"only {len(hist)} wi files precede {session_date.date()} — "
            f"history floor is {H004_MIN_WI_HISTORY}")
    cond_date = hist["trade_date"].iloc[-1]
    stale_days = int((session_date - cond_date).days)
    if stale_days > H004_MAX_STALE_DAYS:
        raise ValueError(
            f"freshest participant file {cond_date.date()} is {stale_days} "
            f"days before {session_date.date()} (guard "
            f"{H004_MAX_STALE_DAYS}) — the console would show no verdict; "
            f"the session goes unrated")
    tail = hist["wi"].tail(252)
    pctile = round(float((tail <= float(tail.iloc[-1])).mean() * 100), 1)
    bhav = pit.load("fo_bhavcopy", asof, root=root,
                    columns=["symbol", "instrument", "expiry", "trade_date",
                             "available_at"])
    expiries = set(pd.to_datetime(
        bhav.loc[(bhav["symbol"] == "NIFTY") & (bhav["instrument"] == "IDO"),
                 "expiry"]).dt.normalize().unique())
    return {"session_date": str(session_date.date()),
            "wi_pctile_252": pctile, "tier": _tier(pctile),
            "is_nifty_expiry": bool(session_date in expiries),
            "computed_from": str(cond_date.date())}


def emit_forward_rating(session_date, asof: datetime | None = None,
                        root: Path | None = None,
                        journal_dir: Path | None = None, note: str = "",
                        now_ist=None) -> dict:
    """Append one PENDING rating row for session_date — the act that makes
    the session ratable in H-004. Refuses pre-forward dates, duplicates,
    and any emission at/after the session's 09:15 IST open: a post-open
    emission is not a pre-open verdict, and a missed emission = the session
    goes unrated, which is the honest outcome (frozen rule)."""
    d = journal_dir or JOURNAL_DIR
    session_date = pd.Timestamp(session_date).normalize()
    if session_date < H004_FORWARD_START:
        raise ValueError(f"{session_date.date()} predates the H-004 forward "
                         f"start {H004_FORWARD_START.date()}")
    now_ist = (pd.Timestamp(now_ist) if now_ist is not None
               else pd.Timestamp(datetime.now(IST)))
    if now_ist.tzinfo is None:
        now_ist = now_ist.tz_localize(IST)
    open_ts = session_date.tz_localize(IST) + pd.Timedelta(hours=9, minutes=15)
    if now_ist >= open_ts:
        raise ValueError(
            f"{session_date.date()} opened at 09:15 IST — an emission at "
            f"{now_ist.strftime('%Y-%m-%dT%H:%M')} is post-open and is "
            f"refused; the session goes unrated (frozen H-004 rule)")
    existing = load_forward_ratings(journal_dir)
    if len(existing) and (existing["session_date"].dt.normalize()
                          == session_date).any():
        raise ValueError(f"rating for {session_date.date()} already emitted")
    row = {**compute_forward_rating(session_date, asof, root),
           "emitted_at_ist": now_ist.strftime("%Y-%m-%dT%H:%M"),
           "outcome": "pending", "note": note}
    out = (existing.assign(
        session_date=existing["session_date"].dt.date.astype(str))
        if len(existing) else pd.DataFrame(columns=list(row)))
    out = pd.concat([out, pd.DataFrame([row])], ignore_index=True)
    out.to_csv(d / "ratings_forward.csv", index=False)
    return row


def finalize_forward_rating(session_date, outcome: str,
                            journal_dir: Path | None = None) -> dict:
    """Flip a pending emission to its settled outcome, cross-checked
    against the journal: 'traded' requires the session's NSE journal row
    (contract note transcribed first), 'abstained' requires its absence."""
    if outcome not in ("traded", "abstained"):
        raise ValueError(f"outcome must be traded|abstained, got {outcome!r}")
    d = journal_dir or JOURNAL_DIR
    session_date = pd.Timestamp(session_date).normalize()
    ledger = load_forward_ratings(journal_dir)
    mask = ledger["session_date"].dt.normalize() == session_date
    if not len(ledger) or not mask.any():
        raise ValueError(f"no emitted rating for {session_date.date()}")
    current = str(ledger.loc[mask, "outcome"].iloc[0])
    if current != "pending":
        raise ValueError(f"{session_date.date()} is already finalized as "
                         f"{current!r}")
    sessions, _ = load_journal(journal_dir)
    journaled = bool(((sessions["exchange"] == "NSE")
                      & (sessions["session_date"] == session_date)).any())
    if outcome == "traded" and not journaled:
        raise ValueError(
            f"'traded' requires an NSE journal session row for "
            f"{session_date.date()} — transcribe the contract note first")
    if outcome == "abstained" and journaled:
        raise ValueError(
            f"the journal has an NSE session row for {session_date.date()} "
            f"— finalize as 'traded' instead")
    ledger.loc[mask, "outcome"] = outcome
    ledger.assign(
        session_date=ledger["session_date"].dt.date.astype(str)
    ).to_csv(d / "ratings_forward.csv", index=False)
    return {k: v for k, v in ledger.loc[mask].iloc[0].items()}


def summary(asof: datetime | None = None, root: Path | None = None,
            journal_dir: Path | None = None) -> dict:
    sessions, trades = load_journal(journal_dir)
    rated = session_ratings(sessions, asof, root=root)
    trades = attach_mae(trades, asof, root=root)
    validated = rated[rated["scope"] == "validated"]
    mae_done = trades["mae_pct"].notna()
    forward = load_forward_ratings(journal_dir)
    # retro = journal sessions before the H-004 forward start: context
    # only, NEVER pooled into the forward test (frozen exclusion)
    retro_validated = validated[
        validated["session_date"] < H004_FORWARD_START]
    return {
        "sessions_logged": int(len(sessions)),
        "retro_validated_sessions": int(len(retro_validated)),
        "h004_ratings_emitted": int(len(forward)),
        "h004_finalized": (int((forward["outcome"] != "pending").sum())
                           if len(forward) else 0),
        "h004_target": H004_TARGET,
        "h004_forward": (forward[
            ["session_date", "wi_pctile_252", "tier", "outcome"]].assign(
            session_date=lambda d: d["session_date"].dt.date.astype(str)
        ).to_dict("records") if len(forward) else []),
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
