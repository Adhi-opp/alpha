r"""Census: Dhan rolling tidy dataset vs NSE bhavcopy (independent source).

The H001b pre-registration requires this census GREEN before the study runs.
PASS thresholds are declared HERE, before any number is computed — a census
whose bar moves after seeing the data is not a census:

  A. Sessions — every NIFTY-option bhavcopy session inside the tidy range
     must exist in tidy (0 missing).
  B. Bars — median minutes/session == 375 and P1 >= 370.
  C. Strike grid — modal spacing == 50 (NIFTY) / 100 (SENSEX).
  D. Entry-strike exit coverage — the ATM-at-open strike has BOTH legs' bars
     somewhere in the 15:21..15:29 window on >= 99% of sessions (H001b's
     truncation exposure).
  E. Cross-source agreement vs bhavcopy front-week rows. NSE's option
     "close" is the LAST-HALF-HOUR weighted average premium (also the daily
     settlement basis), NOT the final LTP — a first census run compared
     Dhan's 15:29 LTP against it and failed exactly the way that definition
     gap predicts (worst on expiry-pin afternoons where premium collapses
     inside the averaging window; verified 2025-06-05 ATM PE: LTP 0.05 vs
     bhav 7.60, Dhan 30-min vol-weighted 7.95). Both runs are recorded in
     docs/DATA_CENSUS.md. The corrected check compares like with like:
     close: Dhan last-30-min volume-weighted mean close vs bhav close,
            >= 90% of joined rows within max(3%, Rs 1.00) — the 3% slack is
            the proxy's discretisation error (1-min closes x 1-min volume
            vs the exchange's per-trade average), not tuning;
     OI:    AMBER / INFO, not gated. Dhan's per-candle oi is the lagging
            intraday disseminated figure; bhav OI is post-clearing EOD.
            Measured gap: median |rel| 2.4%, 27% of rows beyond 5%, 97.7%
            of those ONE-DIRECTIONAL (Dhan 15:29 > bhav EOD, worst on
            expiry day = the unwind). No like-for-like transform exists,
            so the census certifies PRICES ONLY; any study that wants to
            consume candle OI must first add its own OI gate. H001b
            consumes premium paths + spot, never candle OI.
  F. iv == 0 rows confined to expiry sessions (reported, not gated).

The census window is DERIVED from the tidy data itself (min..max
trade_date) and reported — never assumed from a hardcoded constant.

SENSEX (`--symbol sensex`) runs the STRUCTURAL checks only (B, C, F +
range report): no BSE bhavcopy layer exists, so there is no independent
source for A/D/E. A structural GREEN certifies shape, NOT prices —
single-source data stays owner-log-MAE-only; any SENSEX study first needs
a BSE bhavcopy ingest + full census.

  d:\alpha\.venv\Scripts\python scripts\census_rolling.py
  d:\alpha\.venv\Scripts\python scripts\census_rolling.py --symbol sensex
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha.config import DERIVED_ROOT, IST
from alpha.data import pit

TIDY_COLS = ["ts", "side", "strike", "close", "high", "low", "oi", "iv",
             "spot", "volume", "trade_date"]
DATASETS = {"nifty": "dhan_rolling_1m", "sensex": "dhan_rolling_1m_sensex"}
STRIKE_STEP = {"nifty": 50.0, "sensex": 100.0}


def load_tidy(dataset: str) -> pd.DataFrame:
    files = sorted((DERIVED_ROOT / dataset).glob("*.parquet"))
    df = pd.concat([pd.read_parquet(f, columns=TIDY_COLS) for f in files],
                   ignore_index=True)
    df["minute"] = df["ts"].dt.tz_convert(IST).dt.strftime("%H:%M")
    return df


def front_week_expiry(bhav_opt: pd.DataFrame) -> pd.Series:
    """Per trade_date: nearest NIFTY option expiry >= T (the front week)."""
    e = bhav_opt[pd.to_datetime(bhav_opt["expiry"]) >= bhav_opt["trade_date"]]
    return e.groupby("trade_date")["expiry"].min()


def structural_checks(tidy: pd.DataFrame, modal_step: float
                      ) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    per_day = tidy.groupby("trade_date")["ts"].nunique()
    checks.append(("B bars/session",
                   per_day.median() == 375 and np.percentile(per_day, 1) >= 370,
                   f"median {per_day.median():.0f}, P1 {np.percentile(per_day, 1):.0f}, "
                   f"min {per_day.min()} on {per_day.idxmin().date()}"))
    strikes = np.sort(tidy["strike"].unique())
    steps = pd.Series(np.diff(strikes))
    modal = steps.mode().iloc[0]
    checks.append(("C strike grid", modal == modal_step,
                   f"modal step {modal}, unique strikes {len(strikes)}, "
                   f"range {strikes.min():.0f}..{strikes.max():.0f}"))
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", choices=sorted(DATASETS), default="nifty")
    args = ap.parse_args()

    tidy = load_tidy(DATASETS[args.symbol])
    t_min = pd.Timestamp(tidy["trade_date"].min()).date()
    t_max = pd.Timestamp(tidy["trade_date"].max()).date()
    n_sessions = tidy["trade_date"].nunique()
    print(f"tidy rows {len(tidy):,}; derived range {t_min}..{t_max} "
          f"({n_sessions} sessions)\n")

    checks: list[tuple[str, bool, str]] = []

    if args.symbol == "sensex":
        # STRUCTURAL census only — single-source, no independent cross-check
        checks += structural_checks(tidy, STRIKE_STEP["sensex"])
        iv0 = tidy[tidy["iv"] == 0]
        checks.append(("F iv=0 (info)", True,
                       f"{len(iv0):,} rows over {iv0['trade_date'].nunique()} "
                       f"sessions"))
        all_pass = True
        for name, ok, detail in checks:
            flag = "INFO" if name.endswith("(info)") else (
                "PASS" if ok else "FAIL")
            if flag == "FAIL":
                all_pass = False
            print(f"[{flag}] {name:<16} {detail}")
        print("\n[CAVEAT] single-source: STRUCTURAL census only — certifies "
              "shape, not prices. Owner-log MAE use only; a SENSEX study "
              "needs a BSE bhavcopy ingest + full census first.")
        print(f"\nCENSUS (structural): {'GREEN' if all_pass else 'RED'}")
        return 0 if all_pass else 1

    bhav = pit.load_all_unsafe("fo_bhavcopy")
    opt = bhav[(bhav["symbol"] == "NIFTY") & (bhav["instrument"] == "IDO")].copy()
    opt = opt[(opt["trade_date"] >= str(t_min)) & (opt["trade_date"] <= str(t_max))]

    # A. session coverage -------------------------------------------------
    bhav_days = pd.Index(sorted(opt["trade_date"].unique()))
    tidy_days = pd.Index(sorted(tidy["trade_date"].unique()))
    missing = bhav_days.difference(tidy_days)
    extra = tidy_days.difference(bhav_days)
    checks.append(("A sessions", len(missing) == 0,
                   f"bhav {len(bhav_days)} vs tidy {len(tidy_days)}; "
                   f"missing {len(missing)} {[str(d.date()) for d in missing[:5]]}, "
                   f"tidy-only {len(extra)} {[str(d.date()) for d in extra[:5]]}"))

    # B + C ----------------------------------------------------------------
    checks += structural_checks(tidy, STRIKE_STEP["nifty"])

    # D. entry-strike exit coverage -----------------------------------------
    atm = {}
    for td, g in tidy[tidy["minute"] == "09:16"].groupby("trade_date"):
        spot = g["spot"].iloc[0]
        atm[td] = g.loc[(g["strike"] - spot).abs().idxmin(), "strike"]
    late = tidy[tidy["minute"].between("15:21", "15:29")]
    ok_days = 0
    bad_days = []
    for td, k in atm.items():
        legs = late[(late["trade_date"] == td) & (late["strike"] == k)]["side"].unique()
        if {"CE", "PE"} <= set(legs):
            ok_days += 1
        else:
            bad_days.append(str(pd.Timestamp(td).date()))
    frac = ok_days / len(atm) if atm else 0.0
    checks.append(("D exit coverage", frac >= 0.99,
                   f"{ok_days}/{len(atm)} sessions ({frac:.2%}); "
                   f"gaps {bad_days[:8]}"))

    # E. cross-source close / OI -------------------------------------------
    win = tidy[tidy["minute"].between("15:00", "15:29")].copy()
    win["cv"] = win["close"] * win["volume"]
    g = win.groupby(["trade_date", "strike", "side"]).agg(
        cv=("cv", "sum"), v=("volume", "sum"), c_mean=("close", "mean"),
        oi=("oi", "last"))
    g["dhan_close"] = np.where(g["v"] > 0, g["cv"] / g["v"], g["c_mean"])
    last = g.reset_index()[["trade_date", "strike", "side", "dhan_close", "oi"]]
    fwe = front_week_expiry(opt).rename("fw_expiry")
    o = opt.merge(fwe, on="trade_date")
    o = o[o["expiry"] == o["fw_expiry"]][
        ["trade_date", "strike", "option_type", "close", "oi"]]
    j = last.merge(
        o.rename(columns={"option_type": "side", "close": "bhav_close",
                          "oi": "bhav_oi"}),
        on=["trade_date", "strike", "side"], how="inner")
    close_tol = np.maximum(0.03 * j["bhav_close"].abs(), 1.00)
    close_ok = ((j["dhan_close"] - j["bhav_close"]).abs() <= close_tol).mean()
    rel = ((j["dhan_close"] - j["bhav_close"]).abs()
           / j["bhav_close"].where(j["bhav_close"] > 0))
    oi_tol = np.maximum(0.05 * j["bhav_oi"].abs(), 100)
    oi_ok = ((j["oi"] - j["bhav_oi"]).abs() <= oi_tol).mean()
    oi_rel = ((j["oi"] - j["bhav_oi"]).abs()
              / j["bhav_oi"].where(j["bhav_oi"] > 0))
    oi_up = float((np.sign(j["oi"] - j["bhav_oi"])[oi_rel > 0.05] > 0).mean())
    checks.append(("E close vs bhav", close_ok >= 0.90,
                   f"{close_ok:.2%} within max(3%, Rs1) of {len(j):,} joined rows; "
                   f"median rel diff {rel.median():.4%}, P95 {rel.quantile(0.95):.4%}"))
    checks.append(("E oi vs bhav (info)", True,
                   f"NOT gated (intraday snapshot vs cleared EOD): "
                   f"{oi_ok:.2%} within max(5%, 100), median |rel| "
                   f"{oi_rel.median():.4%}, one-directional {oi_up:.1%} — "
                   f"join rate {len(j) / len(last):.1%}"))

    # F. iv == 0 (report only) ----------------------------------------------
    iv0 = tidy[tidy["iv"] == 0]
    iv0_days = iv0["trade_date"].nunique()
    expiry_days = set(pd.to_datetime(opt["expiry"]).unique()) & set(bhav_days)
    iv0_on_expiry = iv0["trade_date"].isin(expiry_days).mean() if len(iv0) else 1.0
    checks.append(("F iv=0 (info)", True,
                   f"{len(iv0):,} rows over {iv0_days} sessions; "
                   f"{iv0_on_expiry:.1%} of them on expiry sessions"))

    all_pass = True
    for name, ok, detail in checks:
        flag = "PASS" if ok else "FAIL"
        if name.endswith("(info)"):
            flag = "INFO"
        elif not ok:
            all_pass = False
        print(f"[{flag}] {name:<16} {detail}")
    print(f"\nCENSUS: {'GREEN' if all_pass else 'RED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
