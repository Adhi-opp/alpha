"""H-001r — re-validation: retail index-option WRITING intensity (published
evening T-1) -> next-session trendiness, under THIS project's stack.

Pre-registration: ledger/H001r-retail-writing-trendiness-revalidation.md —
frozen (hash-guarded) BEFORE this module ever produced a number. The runner
refuses to execute unless the freeze is intact (scripts/run_study.py).

Design notes (why each choice, mirrored in the pre-reg):
- Conditioning is aligned to the DECISION MOMENT (T 09:15 IST) by
  available_at via merge_asof — the participant file published 22:00 IST on
  T-1 conditions day T; a late file automatically falls out of alignment
  rather than leaking.
- Outcome is measured on the FRONT-MONTH NIFTY FUTURE's bhavcopy OHLC
  (nearest expiry >= T). The original study used spot-derived candles; a
  re-validation on the exchange-official derivative series is deliberately a
  robustness variant — an effect that only exists on one pipeline is not an
  effect.
- No fitted parameters -> no walk-forward; this is an association study.
  All CIs/p-values via moving-block bootstrap over day-index blocks
  (block=10 sessions >= two weekly expiry cycles).
- The last ~6 months are a LOCKED HOLDOUT (never touched here; promotion
  requires replication on it later).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from alpha.config import IST
from alpha.data import pit
from alpha.study.bootstrap import mbb_index_distribution, two_sided_p

# ---- frozen study parameters (mirror of the pre-registration) ----
SAMPLE_START = date(2023, 7, 3)
HOLDOUT_START = date(2026, 1, 9)      # >= this date is locked, untouched here
BLOCK_SESSIONS = 10
N_RESAMPLES = 4000
SEED = 42
CI = 0.90
BH_ALPHA = 0.10 / 6                   # q=0.10, family m=6, rank-1 conservative
Z_WINDOW = 60                         # secondary conditioning z-score window


def client_write_intensity(poi: pd.DataFrame) -> pd.DataFrame:
    """Per trade_date: Client (retail) net-short share of its index-option book.

    wi = (call_short + put_short - call_long - put_long) / all four legs.
    Scale-free (no trailing window, no free parameters). Also returns the raw
    net-short contract count for the secondary z-scored variant.
    """
    c = poi[poi["client_type"] == "Client"].copy()
    short = c["opt_idx_call_short"] + c["opt_idx_put_short"]
    long_ = c["opt_idx_call_long"] + c["opt_idx_put_long"]
    out = pd.DataFrame({
        "trade_date": c["trade_date"],
        "available_at": c["available_at"],
        "wi": (short - long_) / (short + long_),
        "net_short": short - long_,
    }).sort_values("trade_date").reset_index(drop=True)
    out["wi_z60"] = (
        (out["net_short"] - out["net_short"].rolling(Z_WINDOW).mean())
        / out["net_short"].rolling(Z_WINDOW).std()
    )
    return out


def front_month_daily(bhav: pd.DataFrame) -> pd.DataFrame:
    """Per trade_date: the nearest-expiry (>= T) NIFTY future's day metrics."""
    f = bhav[(bhav["symbol"] == "NIFTY") & (bhav["instrument"] == "IDF")].copy()
    f = f[pd.to_datetime(f["expiry"]) >= pd.to_datetime(f["trade_date"])]
    f = (f.sort_values(["trade_date", "expiry"])
          .groupby("trade_date", as_index=False).first())
    rng = f["high"] - f["low"]
    f["trendiness"] = (f["close"] - f["open"]).abs() / rng.where(rng > 0)
    f["range_pct"] = rng / f["close"]
    with np.errstate(divide="ignore", invalid="ignore"):
        f["c2c"] = np.log(f["close"] / f["prev_close"])
    return f[["trade_date", "trendiness", "range_pct", "c2c"]]


def assemble(asof: datetime | None = None, root=None) -> pd.DataFrame:
    """One row per decision day T: conditioning known before T's open +
    day-T outcome + day-(T-1) controls. Holdout excluded."""
    asof = asof or datetime.now(timezone.utc)
    poi = client_write_intensity(pit.load("participant_oi", asof, root=root))
    daily = front_month_daily(pit.load("fo_bhavcopy", asof, root=root))

    # decision moment: T 09:15 IST; conditioning = latest file available before it
    decisions = daily[["trade_date"]].copy()
    decisions["decision_ts"] = (
        decisions["trade_date"].dt.tz_localize(IST) + pd.Timedelta(hours=9, minutes=15)
    ).dt.tz_convert("UTC")
    cond = pd.merge_asof(
        decisions.sort_values("decision_ts"),
        poi[["available_at", "trade_date", "wi", "wi_z60"]]
           .rename(columns={"trade_date": "cond_date"})
           .sort_values("available_at"),
        left_on="decision_ts", right_on="available_at",
        direction="backward", tolerance=pd.Timedelta(days=5),
    )
    df = cond.merge(daily, on="trade_date", how="left")
    prev = daily.rename(columns={
        "trendiness": "prev_trendiness", "range_pct": "prev_range_pct",
        "c2c": "prev_c2c"})
    prev["next_td"] = prev["trade_date"].shift(-1)
    df = df.merge(prev.drop(columns=["trade_date"]),
                  left_on="trade_date", right_on="next_td", how="left")

    df = df[(df["trade_date"].dt.date >= SAMPLE_START)
            & (df["trade_date"].dt.date < HOLDOUT_START)]
    # a decision may never see a file from its own day (publication is 22:00)
    same_day = df["cond_date"].notna() & (df["cond_date"] == df["trade_date"])
    if same_day.any():
        raise AssertionError("PIT violation: same-day conditioning matched")
    keep = ["trade_date", "wi", "wi_z60", "trendiness",
            "prev_trendiness", "prev_range_pct", "prev_c2c"]
    # dropna on PRIMARY columns only — the secondary's 60-day z warmup must
    # not shrink the primary sample
    primary_cols = ["wi", "trendiness", "prev_trendiness", "prev_range_pct", "prev_c2c"]
    return (df[keep].dropna(subset=primary_cols)
            .sort_values("trade_date").reset_index(drop=True))


def tercile_diff(x: np.ndarray, y: np.ndarray) -> float:
    """mean(y | x in top tercile) - mean(y | x in bottom tercile)."""
    lo, hi = np.quantile(x, [1 / 3, 2 / 3])
    return float(y[x >= hi].mean() - y[x <= lo].mean())


def _rank(a: np.ndarray) -> np.ndarray:
    order = np.argsort(a, kind="mergesort")
    r = np.empty(len(a))
    r[order] = np.arange(len(a), dtype=float)
    return r


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx, ry = _rank(x), _rank(y)
    rx -= rx.mean(); ry -= ry.mean()
    return float((rx @ ry) / np.sqrt((rx @ rx) * (ry @ ry)))


def partial_spearman(x: np.ndarray, y: np.ndarray, controls: np.ndarray) -> float:
    """Spearman of x,y after residualising both ranks on the controls' ranks
    (the pre-registered confound test — the one that killed G003)."""
    rx, ry = _rank(x), _rank(y)
    rc = np.column_stack([_rank(controls[:, j]) for j in range(controls.shape[1])])
    design = np.column_stack([np.ones(len(x)), rc])
    bx, *_ = np.linalg.lstsq(design, rx, rcond=None)
    by, *_ = np.linalg.lstsq(design, ry, rcond=None)
    ex, ey = rx - design @ bx, ry - design @ by
    ex -= ex.mean(); ey -= ey.mean()
    return float((ex @ ey) / np.sqrt((ex @ ex) * (ey @ ey)))


@dataclass
class Gate:
    name: str
    passed: bool
    detail: str


def run(asof: datetime | None = None) -> dict:
    df = assemble(asof)
    x = df["wi"].to_numpy()
    y = df["trendiness"].to_numpy()
    controls = df[["prev_trendiness", "prev_range_pct", "prev_c2c"]].to_numpy()
    n = len(df)

    point = tercile_diff(x, y)
    dist = mbb_index_distribution(
        n, lambda idx: tercile_diff(x[idx], y[idx]),
        block_size=BLOCK_SESSIONS, n_resamples=N_RESAMPLES, seed=SEED)
    lo, hi = np.percentile(dist, [(1 - CI) / 2 * 100, (1 + CI) / 2 * 100])
    p = two_sided_p(dist)

    rho = spearman(x, y)
    prho = partial_spearman(x, y, controls)
    pdist = mbb_index_distribution(
        n, lambda idx: partial_spearman(x[idx], y[idx], controls[idx]),
        block_size=BLOCK_SESSIONS, n_resamples=N_RESAMPLES, seed=SEED + 1)
    plo, phi = np.percentile(pdist, [(1 - CI) / 2 * 100, (1 + CI) / 2 * 100])

    half = n // 2
    d1 = tercile_diff(x[:half], y[:half])
    d2 = tercile_diff(x[half:], y[half:])

    zmask = df["wi_z60"].notna().to_numpy()
    sec = tercile_diff(df["wi_z60"].to_numpy()[zmask], y[zmask])

    gates = [
        Gate("effect_positive", point > 0, f"tercile diff {point:+.4f}"),
        Gate("ci_excludes_zero", lo > 0 or hi < 0, f"{CI:.0%} CI [{lo:+.4f}, {hi:+.4f}]"),
        Gate("bh_deflated_p", p <= BH_ALPHA, f"p={p:.5f} vs threshold {BH_ALPHA:.5f}"),
        Gate("survives_partial", (prho > 0) and (plo > 0),
             f"partial rho {prho:+.4f}, CI [{plo:+.4f}, {phi:+.4f}] "
             f"(raw rho {rho:+.4f})"),
        Gate("split_half_sign", np.sign(d1) == np.sign(d2) != 0,
             f"halves {d1:+.4f} / {d2:+.4f}"),
    ]
    verdict = "GO" if all(g.passed for g in gates) else (
        "INVERTED" if (point < 0 and hi < 0) else "NO-GO")
    return {
        "study": "H-001r",
        "n_days": n,
        "sample": [str(df['trade_date'].min().date()), str(df['trade_date'].max().date())],
        "primary": {"tercile_diff": point, "ci": [float(lo), float(hi)], "p": p},
        "spearman": rho,
        "partial_spearman": {"rho": prho, "ci": [float(plo), float(phi)]},
        "split_half": [d1, d2],
        "secondary_wi_z60_tercile_diff": sec,
        "gates": [{"name": g.name, "passed": bool(g.passed), "detail": g.detail}
                  for g in gates],
        "verdict": verdict,
    }
