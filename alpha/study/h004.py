"""H-004 — forward owner-log promotion test (the joint system's judge).

Pre-registration: ledger/H004-forward-owner-log.md — frozen 2026-07-12,
BEFORE the first rated forward session (2026-07-14). This module is the
executable form of that frozen text and refuses to compute the association
before 40 forward sessions have accrued (single-look, enforced structurally,
not by promise). The H003 holdout replication (gate 5) runs INSIDE run(),
after the n-guard — the locked holdout cannot be peeked at via this module.

The sample is every rated NSE NIFTY front-week expiry session from
FORWARD_START, traded or not: an expiry session with no journal row is an
abstention and enters at Y = 0. The retro-seeded 2026-07 sessions are
excluded by FORWARD_START itself.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from alpha.data import pit
from alpha.study.bootstrap import mbb_index_distribution, two_sided_p
from alpha.study.h001b import Gate, front_week_meta
from alpha.study.h001r import client_write_intensity, partial_spearman, spearman
from alpha.study import h003
from alpha.paper import owner_log

# ---- frozen study parameters (mirror of the pre-registration) ----
FORWARD_START = date(2026, 7, 14)     # first console-rated expiry session
MIN_SESSIONS = 40                     # single evaluation at exactly this count
DEADLINE = date(2027, 12, 31)         # fewer than 40 by then = NO-GO
MAX_STALE_DAYS = 4                    # console stale guard, mirrored
MIN_WI_HISTORY = 20
BLOCK_SESSIONS = 5                    # weekly expiries; block-10 = sensitivity
N_RESAMPLES = 4000
SEED = 53
CI = 0.90
BH_ALPHA = 0.10 / 10                  # q=0.10, family m=10, rank-1 conservative
KILL_SWITCH_RS = 6000.0


class SingleLookError(RuntimeError):
    """Raised when the evaluation is attempted before 40 sessions accrue."""


def _rating_for(session: pd.Timestamp, wi: pd.DataFrame) -> float | None:
    """wi percentile exactly as owner_log.session_ratings / the console:
    most recent strictly-prior file vs its trailing 252, with the stale
    guard the console applies live."""
    hist = wi[wi["trade_date"] < session]
    if len(hist) < MIN_WI_HISTORY:
        return None
    if (session - hist["trade_date"].iloc[-1]).days > MAX_STALE_DAYS:
        return None                    # console showed no verdict that morning
    tail = hist["wi"].tail(252)
    return round(float((tail <= float(tail.iloc[-1])).mean() * 100), 1)


def assemble(asof: datetime | None = None, root: Path | None = None,
             journal_dir: Path | None = None) -> tuple[pd.DataFrame, list[str]]:
    """One row per rated forward expiry session: rating X, realized Y
    (0 = abstained), and the discipline-clean Y for gate 3. Returns the
    frame plus the disclosed list of unrated (excluded) expiry sessions."""
    asof = asof or datetime.now(timezone.utc)
    wi = client_write_intensity(pit.load("participant_oi", asof, root=root))
    bhav = pit.load("fo_bhavcopy", asof, root=root)
    meta = front_week_meta(bhav)
    expiries = meta.loc[
        meta["is_expiry"]
        & (meta["trade_date"].dt.date >= FORWARD_START), "trade_date"]

    sessions, trades = owner_log.load_journal(journal_dir)
    trades = owner_log.attach_mae(trades, asof, root=root)
    nse = sessions[sessions["exchange"] == "NSE"]
    day_net = dict(zip(nse["session_date"], nse["day_net_pnl"]))
    nifty = trades[(trades["exchange"] == "NSE") & (trades["symbol"] == "NIFTY")]
    flagged_gross = (nifty[nifty["discipline_flag"] == True]  # noqa: E712
                     .groupby("session_date")["gross_pnl"].sum().to_dict())

    rows, unrated = [], []
    for td in sorted(expiries):
        x = _rating_for(td, wi)
        if x is None:
            unrated.append(str(td.date()))
            continue
        y = float(day_net.get(td, 0.0))
        rows.append({
            "session_date": td, "wi_pctile": x, "day_net_pnl": y,
            "abstained": td not in day_net,
            "y_clean": y - float(flagged_gross.get(td, 0.0)),
        })
    return pd.DataFrame(rows), unrated


def _assemble_unbounded(asof: datetime, root: Path | None = None,
                        start: date = h003.SAMPLE_START,
                        end: date = date(2026, 7, 7)) -> pd.DataFrame:
    """h003.assemble with the window opened to include the holdout. The
    frozen h003 module is not modified; its primitives are reused."""
    from alpha.study.h001r import front_month_daily
    from alpha.config import IST

    poi = client_write_intensity(pit.load("participant_oi", asof, root=root))
    bhav = pit.load("fo_bhavcopy", asof, root=root)
    daily = front_month_daily(bhav)
    meta = front_week_meta(bhav)

    decisions = meta[["trade_date", "lot", "is_expiry"]].copy()
    decisions["decision_ts"] = (
        decisions["trade_date"].dt.tz_localize(IST)
        + pd.Timedelta(hours=9, minutes=15)
    ).dt.tz_convert("UTC")
    cond = pd.merge_asof(
        decisions.sort_values("decision_ts"),
        poi[["available_at", "trade_date", "wi"]]
           .rename(columns={"trade_date": "cond_date"})
           .sort_values("available_at"),
        left_on="decision_ts", right_on="available_at",
        direction="backward", tolerance=pd.Timedelta(days=5),
    )
    prev = daily.rename(columns={
        "trendiness": "prev_trendiness", "range_pct": "prev_range_pct",
        "c2c": "prev_c2c"})
    prev["next_td"] = prev["trade_date"].shift(-1)
    df = cond.merge(prev.drop(columns=["trade_date"]),
                    left_on="trade_date", right_on="next_td", how="left")
    df = df[(df["trade_date"].dt.date >= start) & (df["trade_date"].dt.date < end)]
    same_day = df["cond_date"].notna() & (df["cond_date"] == df["trade_date"])
    if same_day.any():
        raise AssertionError("PIT violation: same-day conditioning matched")
    keep = ["trade_date", "wi", "lot", "is_expiry", *h003.CONTROLS]
    return (df[keep].dropna(subset=["wi", "lot", *h003.CONTROLS])
            .sort_values("trade_date").reset_index(drop=True))


def _h003_energy(frame: pd.DataFrame, asof: datetime,
                 root: Path | None = None) -> pd.DataFrame:
    from alpha.study.h001b import build_day_paths
    tidy = pit.load(
        "dhan_rolling_1m", asof, root=root,
        columns=["ts", "side", "strike", "high", "low", "close", "spot",
                 "trade_date", "available_at"])
    tidy = tidy[tidy["trade_date"].isin(frame["trade_date"])]
    by_day = {td: rows for td, rows in tidy.groupby("trade_date")}
    ys = []
    for row in frame.itertuples():
        day_rows = by_day.get(row.trade_date, pd.DataFrame())
        y = None
        if not day_rows.empty:
            y = h003.scalp_energy(build_day_paths(day_rows), int(row.lot))
        ys.append(np.nan if y is None else y)
    return frame.assign(Y=ys).dropna(subset=["Y"]).reset_index(drop=True)


def _partial_rho_ci(e: pd.DataFrame, seed: int) -> tuple[float, float, float, float]:
    x = e["wi"].to_numpy(); y = e["Y"].to_numpy()
    c = e[h003.CONTROLS].to_numpy()
    rho = partial_spearman(x, y, c)
    dist = mbb_index_distribution(
        len(e), lambda idx: partial_spearman(x[idx], y[idx], c[idx]),
        block_size=h003.BLOCK_SESSIONS, n_resamples=N_RESAMPLES, seed=seed)
    dist = dist[~np.isnan(dist)]
    lo, hi = np.percentile(dist, [(1 - CI) / 2 * 100, (1 + CI) / 2 * 100])
    return rho, float(lo), float(hi), two_sided_p(dist)


def run_holdout_replication(asof: datetime, root: Path | None = None) -> dict:
    """H003 on the locked holdout (sign check) + combined dev+holdout
    (CI/p at the frozen m=10 bar). Only run() may call this."""
    full = _assemble_unbounded(asof, root)
    full = _h003_energy(full[full["is_expiry"]].reset_index(drop=True),
                        asof, root)
    hold = full[full["trade_date"].dt.date >= h003.HOLDOUT_START].reset_index(drop=True)
    dev = full[full["trade_date"].dt.date < h003.HOLDOUT_START].reset_index(drop=True)
    if len(hold) < 15:
        raise RuntimeError(f"holdout has only {len(hold)} gradeable expiry "
                           "sessions — too thin to call a replication")
    h_rho = partial_spearman(hold["wi"].to_numpy(), hold["Y"].to_numpy(),
                             hold[h003.CONTROLS].to_numpy())
    d_rho = partial_spearman(dev["wi"].to_numpy(), dev["Y"].to_numpy(),
                             dev[h003.CONTROLS].to_numpy())
    c_rho, c_lo, c_hi, c_p = _partial_rho_ci(full, seed=SEED)
    return {"holdout_n": int(len(hold)), "holdout_rho": float(h_rho),
            "dev_rho": float(d_rho), "combined_n": int(len(full)),
            "combined_rho": float(c_rho), "combined_ci": [c_lo, c_hi],
            "combined_p": float(c_p),
            "same_sign": bool(np.sign(h_rho) == np.sign(d_rho) != 0)}


def run(asof: datetime | None = None, root: Path | None = None,
        journal_dir: Path | None = None) -> dict:
    asof = asof or datetime.now(timezone.utc)
    frame, unrated = assemble(asof, root=root, journal_dir=journal_dir)
    n = len(frame)

    if n < MIN_SESSIONS:
        if asof.date() <= DEADLINE:
            raise SingleLookError(
                f"only {n}/{MIN_SESSIONS} rated forward sessions have accrued "
                f"— the pre-registration forbids computing the association "
                f"before the sample is complete (deadline {DEADLINE})")
        return {  # deadline passed with an incomplete log: operational failure
            "study": "H-004", "n_days": int(n),
            "sample": [str(FORWARD_START), str(DEADLINE)],
            "unrated_sessions": unrated, "gates": [
                {"name": "accrual", "passed": False,
                 "detail": f"{n}/{MIN_SESSIONS} rated sessions by {DEADLINE}"}],
            "verdict": "NO-GO",
        }

    frame = frame.iloc[:MIN_SESSIONS].reset_index(drop=True)  # exactly 40
    x = frame["wi_pctile"].to_numpy()
    y = frame["day_net_pnl"].to_numpy()

    rho = spearman(x, y)
    dist = mbb_index_distribution(
        MIN_SESSIONS, lambda idx: spearman(x[idx], y[idx]),
        block_size=BLOCK_SESSIONS, n_resamples=N_RESAMPLES, seed=SEED)
    dist = dist[~np.isnan(dist)]
    lo, hi = np.percentile(dist, [(1 - CI) / 2 * 100, (1 + CI) / 2 * 100])
    p = two_sided_p(dist)

    rho_clean = spearman(x, frame["y_clean"].to_numpy())
    worst_day = float(y.min())
    breaches = frame.loc[frame["day_net_pnl"] < -KILL_SWITCH_RS,
                         "session_date"].dt.date.astype(str).tolist()
    holdout = run_holdout_replication(asof, root)

    gates = [
        Gate("rho_ci", rho > 0 and lo > 0,
             f"Spearman {rho:+.4f}, {CI:.0%} CI [{lo:+.4f}, {hi:+.4f}]"),
        Gate("bh_deflated_p", p <= BH_ALPHA,
             f"p={p:.5f} vs threshold {BH_ALPHA:.5f}"),
        Gate("discipline_sign", np.sign(rho_clean) == np.sign(rho) or rho_clean == 0,
             f"discipline-clean Spearman {rho_clean:+.4f} vs {rho:+.4f}"),
        Gate("kill_switch", len(breaches) == 0,
             f"worst day {worst_day:+,.0f} vs -{KILL_SWITCH_RS:,.0f}; "
             f"breaches {breaches}"),
        Gate("h003_holdout", holdout["same_sign"]
             and holdout["combined_ci"][0] > 0
             and holdout["combined_p"] <= BH_ALPHA,
             f"holdout rho {holdout['holdout_rho']:+.4f} "
             f"(n={holdout['holdout_n']}), combined "
             f"{holdout['combined_rho']:+.4f} CI {holdout['combined_ci']}, "
             f"p={holdout['combined_p']:.5f}"),
    ]
    verdict = "PROMOTED" if all(g.passed for g in gates) else "NO-GO"

    traded = frame[~frame["abstained"]]
    med = float(np.median(x))
    hi_half = frame[frame["wi_pctile"] >= med]
    lo_half = frame[frame["wi_pctile"] < med]

    return {
        "study": "H-004",
        "n_days": int(MIN_SESSIONS),
        "sample": [str(frame["session_date"].min().date()),
                   str(frame["session_date"].max().date())],
        "primary": {"spearman": float(rho), "ci": [float(lo), float(hi)],
                    "p": float(p)},
        "secondary": {
            "traded_only_spearman": (float(spearman(
                traded["wi_pctile"].to_numpy(),
                traded["day_net_pnl"].to_numpy()))
                if len(traded) >= 5 else None),
            "n_abstained": int(frame["abstained"].sum()),
            "abstain_rate_above_median": float(hi_half["abstained"].mean()),
            "abstain_rate_below_median": float(lo_half["abstained"].mean()),
            "mean_pnl_above_median": float(hi_half["day_net_pnl"].mean()),
            "mean_pnl_below_median": float(lo_half["day_net_pnl"].mean()),
            "block10_ci": [float(v) for v in np.percentile(
                (lambda d: d[~np.isnan(d)])(mbb_index_distribution(
                    MIN_SESSIONS, lambda idx: spearman(x[idx], y[idx]),
                    block_size=10, n_resamples=N_RESAMPLES, seed=SEED)),
                [(1 - CI) / 2 * 100, (1 + CI) / 2 * 100])],
        },
        "holdout_replication": holdout,
        "unrated_sessions": unrated,
        "gates": [{"name": g.name, "passed": bool(g.passed),
                   "detail": g.detail} for g in gates],
        "verdict": verdict,
    }
