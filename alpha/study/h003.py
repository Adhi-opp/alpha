"""H-003 — expiry-day scalp environment: does heavy retail writing predict
richer (hurdle-adjusted) premium oscillation on NIFTY expiry days?

Pre-registration: ledger/H003-expiry-scalp-environment.md — frozen before
this module produced a number (scripts/run_study.py enforces).

This is an ASSOCIATION study, deliberately: no execution simulator, no exit
rules, no tunable constants. The owner's real edge is sub-minute
discretionary scalping that neither the 95 s alert-latency model nor any
1-min-bar exit rule can represent honestly. The tool's job is to rate the
DAY; the owner does the intraday timing. A GO licenses a console verdict
("favorable scalp environment"), never a ticket or an EV claim; the joint
system (signal + owner's hands) is validated by the forward owner-P&L log.

Outcome design (mirrors the frozen section):
- Y = per-leg premium path length ABOVE a cost hurdle, normalized by the
  09:45 combined premium. The hurdle is breakeven_move (Phase-1 cost model,
  fitted to the owner's own contract notes) plus crossing the estimated
  half-spread twice — every component measured or already pre-registered.
  Sub-cost vibration scores zero (a grinder, not a scalp environment);
  minutes-scale bursts score amplitude net of cost.
- Per-leg |Δ|, not the combined straddle's: the owner scalps CE and PE
  separately, so two-sided oscillation counts even when the net is flat.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from alpha.data import pit
from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07
from alpha.study.bootstrap import mbb_index_distribution, two_sided_p
from alpha.study.h001b import Gate, atm_strike, build_day_paths, front_week_meta
from alpha.study.h001r import (
    client_write_intensity, front_month_daily, partial_spearman, spearman,
    tercile_diff,
)
from alpha.config import IST

# ---- frozen study parameters (mirror of the pre-registration) ----
SAMPLE_START = date(2024, 7, 9)
HOLDOUT_START = date(2026, 1, 9)      # >= this date is locked, untouched here
WINDOW_START, WINDOW_END = 30, 360    # bars: 09:45 .. 15:15 IST
MAX_MISSING_FRAC = 0.10
HALF_SPREAD_EST = 0.0025              # H001b baseline estimate (no depth yet)
BLOCK_SESSIONS = 10
N_RESAMPLES = 4000
SEED = 47
CI = 0.90
BH_ALPHA = 0.10 / 9                   # q=0.10, family m=9, rank-1 conservative
MIN_DAYS = 50                         # integrity fence, not a gate
COST_MODEL = ZERODHA_NSE_OPTIONS_2026_07
CONTROLS = ["prev_trendiness", "prev_range_pct", "prev_c2c"]


def scalp_energy(paths, lot: int) -> float | None:
    """Hurdle-adjusted per-leg path length, normalized by opening premium.

    None = ungradeable day (strike unavailable or > MAX_MISSING_FRAC of
    window bars missing for either leg) — excluded and disclosed, never a
    silent zero.
    """
    k = atm_strike(paths, WINDOW_START)
    if k is None:
        return None
    total, denom = 0.0, 0.0
    for s in ("CE", "PE"):
        c = paths.close.get((k, s))
        if c is None:
            return None
        w = c[WINDOW_START:WINDOW_END + 1]
        if np.isnan(w).mean() > MAX_MISSING_FRAC:
            return None
        p0 = float(w[0])
        if not np.isfinite(p0) or p0 <= 0:
            return None
        hurdle = COST_MODEL.breakeven_move(p0, int(lot)) + 2 * HALF_SPREAD_EST * p0
        d = np.abs(np.diff(w))
        d = d[~np.isnan(d)]           # deltas spanning missing bars: not counted
        total += float(np.maximum(0.0, d - hurdle).sum())
        denom += p0
    return total / denom


def assemble(asof: datetime | None = None, root=None) -> pd.DataFrame:
    """One row per decision day T: wi known before T's open, prev-day
    controls, lot, expiry flag. Holdout excluded; PIT trap armed."""
    asof = asof or datetime.now(timezone.utc)
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

    df = df[(df["trade_date"].dt.date >= SAMPLE_START)
            & (df["trade_date"].dt.date < HOLDOUT_START)]
    same_day = df["cond_date"].notna() & (df["cond_date"] == df["trade_date"])
    if same_day.any():
        raise AssertionError("PIT violation: same-day conditioning matched")
    keep = ["trade_date", "wi", "lot", "is_expiry", *CONTROLS]
    return (df[keep].dropna(subset=["wi", "lot", *CONTROLS])
            .sort_values("trade_date").reset_index(drop=True))


def run(asof: datetime | None = None, root=None) -> dict:
    asof = asof or datetime.now(timezone.utc)
    frame = assemble(asof, root=root)

    tidy = pit.load(
        "dhan_rolling_1m", asof, root=root,
        columns=["ts", "side", "strike", "high", "low", "close", "spot",
                 "trade_date", "available_at"])
    tidy = tidy[tidy["trade_date"].isin(frame["trade_date"])]
    by_day = {td: rows for td, rows in tidy.groupby("trade_date")}

    ys, excluded = [], []
    for row in frame.itertuples():
        day_rows = by_day.get(row.trade_date, pd.DataFrame())
        y = None
        if not day_rows.empty:
            y = scalp_energy(build_day_paths(day_rows), int(row.lot))
        ys.append(y)
        if y is None:
            excluded.append(str(row.trade_date.date()))
    frame = frame.assign(Y=[np.nan if y is None else y for y in ys])
    g = frame.dropna(subset=["Y"]).reset_index(drop=True)

    e = g[g["is_expiry"]].reset_index(drop=True)
    ne = g[~g["is_expiry"]].reset_index(drop=True)
    if len(e) < MIN_DAYS:
        raise RuntimeError(f"only {len(e)} gradeable expiry days — "
                           "sample too thin to grade honestly")

    x = e["wi"].to_numpy()
    y = e["Y"].to_numpy()
    controls = e[CONTROLS].to_numpy()
    n = len(e)

    prho = partial_spearman(x, y, controls)
    dist = mbb_index_distribution(
        n, lambda idx: partial_spearman(x[idx], y[idx], controls[idx]),
        block_size=BLOCK_SESSIONS, n_resamples=N_RESAMPLES, seed=SEED)
    dist = dist[~np.isnan(dist)]
    lo, hi = np.percentile(dist, [(1 - CI) / 2 * 100, (1 + CI) / 2 * 100])
    p = two_sided_p(dist)

    half = n // 2
    h1 = partial_spearman(x[:half], y[:half], controls[:half])
    h2 = partial_spearman(x[half:], y[half:], controls[half:])

    gates = [
        Gate("partial_rho_ci", prho > 0 and lo > 0,
             f"partial Spearman {prho:+.4f}, {CI:.0%} CI [{lo:+.4f}, {hi:+.4f}]"),
        Gate("bh_deflated_p", p <= BH_ALPHA,
             f"p={p:.5f} vs threshold {BH_ALPHA:.5f}"),
        Gate("split_half_sign", np.sign(h1) == np.sign(h2) != 0,
             f"halves {h1:+.4f} / {h2:+.4f}"),
    ]
    verdict = "GO" if all(gt.passed for gt in gates) else (
        "INVERTED" if (prho < 0 and hi < 0) else "NO-GO")

    contrast = (partial_spearman(ne["wi"].to_numpy(), ne["Y"].to_numpy(),
                                 ne[CONTROLS].to_numpy())
                if len(ne) >= MIN_DAYS else float("nan"))
    autocorr = spearman(y[:-1], y[1:]) if n > 2 else float("nan")

    return {
        "study": "H-003",
        "n_days": int(n),
        "n_nonexpiry_contrast": int(len(ne)),
        "sample": [str(e["trade_date"].min().date()),
                   str(e["trade_date"].max().date())],
        "primary": {"partial_spearman": float(prho),
                    "ci": [float(lo), float(hi)], "p": float(p)},
        "split_half": [float(h1), float(h2)],
        "secondary": {
            "raw_spearman": float(spearman(x, y)),
            "tercile_diff_Y": float(tercile_diff(x, y)),
            "nonexpiry_partial_spearman": float(contrast),
            "Y_lag1_autocorr": float(autocorr),
            "Y_median_expiry": float(np.median(y)),
            "Y_median_nonexpiry": (float(ne["Y"].median())
                                   if len(ne) else float("nan")),
        },
        "excluded_days": excluded,
        "gates": [{"name": gt.name, "passed": bool(gt.passed),
                   "detail": gt.detail} for gt in gates],
        "verdict": verdict,
    }
