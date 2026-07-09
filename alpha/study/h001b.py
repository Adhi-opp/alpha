"""H-001b — the tradeable question: long front-week ATM straddle on
heavy-retail-writing days, at FULL cost — theta, spread, adverse fills,
statutory charges, and the owner's real manual latency, run as a Monte Carlo.

Pre-registration: ledger/H001b-long-premium-expression.md — frozen before
this module ever produced a number; scripts/run_study.py refuses to run it
otherwise.

Design notes (each mirrors the pre-reg; deviations are impossible without
editing the frozen section, which the runner detects):
- Conditioning cut is the TRAILING-252-session 66.7th percentile of wi,
  computed only from files already published at decision time. Full-sample
  terciles would leak the cut itself; H001r's association could survive
  that, a trade rule cannot.
- The counterfactual (bottom-cut) book runs the IDENTICAL simulation on the
  abstention side — the constitution's censoring-bias rule: what the tool
  declines must be graded as seriously as what it takes.
- Entry bars sit < 30 minutes into the session, so the AdverseFillModel's
  insufficient-history rule makes EVERY entry volatile by construction: the
  buyer pays the arrival bar's HIGH plus half-spread. Mornings are the wide
  regime; a promotion decision must survive that, not average it away.
- A draw whose strike path is missing at the exit bar is TRUNCATED and
  excluded (counted, per-day disclosed), never silently filled from a stale
  bar. Days with > 50% truncated draws are dropped and listed — these are
  fan-escape days (e.g. 2024-06-04 election), i.e. the straddle's best days:
  the exclusion biases AGAINST the hypothesis, and is disclosed rather than
  patched.
- No-fill draws (latency past 900 s) contribute net 0 to the day mean —
  that is the account's real arithmetic for an abandoned order.
- Theta is not an execution friction: it lives inside gross_move (an ATM
  straddle held open→15:20 pays the day's theta by construction). The
  attribution splits net EV into gross_move_ex_friction + latency_drag +
  adverse_drag + spread_drag − statutory, and the identity is exact per
  draw.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from alpha.config import IST
from alpha.data import pit
from alpha.measure.costs import ZERODHA_NSE_OPTIONS_2026_07
from alpha.measure.execution_mc import FOCUSED_DESK, OWNER_2026_07, arrival_pos
from alpha.study.bootstrap import mbb_index_distribution, two_sided_p
from alpha.study.h001r import client_write_intensity

# ---- frozen study parameters (mirror of the pre-registration) ----
SAMPLE_START = date(2024, 7, 9)
HOLDOUT_START = date(2026, 1, 9)      # >= this date is locked, untouched here
TRAIL = 252                           # trailing sessions for the rolling cut
TOP_Q, BOT_Q = 2 / 3, 1 / 3
N_DRAWS = 400
MC_SEED = 11
BLOCK_SESSIONS = 10
N_RESAMPLES = 4000
BOOT_SEED = 44
CI = 0.90
BH_ALPHA = 0.10 / 7                   # q=0.10, family m=7, rank-1 conservative
HALF_SPREAD = 0.0025                  # baseline (ESTIMATED — no depth yet)
HALF_SPREAD_STRESS = 0.0050
ENTRY_INTENT = 0                      # 09:15 bar
EXIT_INTENT = 365                     # 15:20 bar
LAST_BAR = 374                        # 15:29 — exit fills capped here
BARS_PER_DAY = 375
VOL_WINDOW = 30
VOL_PCTILE = 75.0
TRUNC_DAY_LIMIT = 0.5                 # > this fraction truncated -> day dropped
MIN_TOP_DAYS = 30                     # integrity fence, not a gate
COST_MODEL = ZERODHA_NSE_OPTIONS_2026_07


def trailing_cuts(poi: pd.DataFrame) -> pd.DataFrame:
    """Add PIT-safe rolling terciles of wi. Row i's cut uses wi[i-251..i] —
    every value published by row i's own available_at, so a decision
    conditioning on row i (the T-1 file) leaks nothing."""
    out = poi.sort_values("trade_date").reset_index(drop=True).copy()
    out["cut_top"] = out["wi"].rolling(TRAIL, min_periods=TRAIL).quantile(TOP_Q)
    out["cut_bot"] = out["wi"].rolling(TRAIL, min_periods=TRAIL).quantile(BOT_Q)
    return out


def front_week_meta(bhav: pd.DataFrame) -> pd.DataFrame:
    """Per trade_date: front-week (nearest >= T) NIFTY option expiry + lot."""
    o = bhav[(bhav["symbol"] == "NIFTY") & (bhav["instrument"] == "IDO")].copy()
    o = o[pd.to_datetime(o["expiry"]) >= pd.to_datetime(o["trade_date"])]
    o = (o.sort_values(["trade_date", "expiry"])
          .groupby("trade_date", as_index=False).first())
    o["is_expiry"] = pd.to_datetime(o["expiry"]) == pd.to_datetime(o["trade_date"])
    return o[["trade_date", "expiry", "lot", "is_expiry"]]


def assemble(asof: datetime | None = None, root=None) -> pd.DataFrame:
    """One row per decision day T in [SAMPLE_START, HOLDOUT_START):
    conditioning known before T's open, book membership, lot, expiry flag."""
    asof = asof or datetime.now(timezone.utc)
    poi = trailing_cuts(client_write_intensity(pit.load("participant_oi", asof,
                                                        root=root)))
    meta = front_week_meta(pit.load("fo_bhavcopy", asof, root=root))

    decisions = meta[["trade_date"]].copy()
    decisions["decision_ts"] = (
        decisions["trade_date"].dt.tz_localize(IST)
        + pd.Timedelta(hours=9, minutes=15)
    ).dt.tz_convert("UTC")
    cond = pd.merge_asof(
        decisions.sort_values("decision_ts"),
        poi[["available_at", "trade_date", "wi", "cut_top", "cut_bot"]]
           .rename(columns={"trade_date": "cond_date"})
           .sort_values("available_at"),
        left_on="decision_ts", right_on="available_at",
        direction="backward", tolerance=pd.Timedelta(days=5),
    )
    df = cond.merge(meta, on="trade_date", how="left")
    df = df[(df["trade_date"].dt.date >= SAMPLE_START)
            & (df["trade_date"].dt.date < HOLDOUT_START)]
    same_day = df["cond_date"].notna() & (df["cond_date"] == df["trade_date"])
    if same_day.any():
        raise AssertionError("PIT violation: same-day conditioning matched")
    df = df.dropna(subset=["wi", "cut_top", "cut_bot", "lot"])
    df["book"] = np.select(
        [df["wi"] >= df["cut_top"], df["wi"] < df["cut_bot"]],
        ["TOP", "BOTTOM"], default="NONE")
    keep = ["trade_date", "wi", "cut_top", "cut_bot", "book", "lot", "is_expiry"]
    return df[keep].sort_values("trade_date").reset_index(drop=True)


# ---------------- per-day path structure + fills ----------------

@dataclass
class DayPaths:
    """Minute-indexed (0..374) arrays for one session's option fan."""
    spot: np.ndarray                       # spot per minute (NaN if absent)
    high: dict                             # (strike, side) -> np.ndarray[375]
    low: dict
    close: dict
    strikes: np.ndarray                    # sorted unique strikes present


def build_day_paths(day_rows: pd.DataFrame) -> DayPaths:
    r = day_rows.copy()
    local = r["ts"].dt.tz_convert(IST)
    r["pos"] = (local.dt.hour * 60 + local.dt.minute) - (9 * 60 + 15)
    r = r[(r["pos"] >= 0) & (r["pos"] < BARS_PER_DAY)]   # Muhurat guard
    spot = np.full(BARS_PER_DAY, np.nan)
    sp = r.groupby("pos")["spot"].first()
    spot[sp.index.to_numpy()] = sp.to_numpy()
    high, low, close = {}, {}, {}
    for (k, s), g in r.groupby(["strike", "side"]):
        h = np.full(BARS_PER_DAY, np.nan)
        l = np.full(BARS_PER_DAY, np.nan)
        c = np.full(BARS_PER_DAY, np.nan)
        p = g["pos"].to_numpy()
        h[p], l[p], c[p] = g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy()
        high[(k, s)], low[(k, s)], close[(k, s)] = h, l, c
    return DayPaths(spot=spot, high=high, low=low, close=close,
                    strikes=np.sort(r["strike"].unique()))


def is_volatile(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                pos: int) -> bool:
    """NaN-aware mirror of AdverseFillModel._is_volatile: strict > vs the
    trailing VOL_WINDOW bars' range fractions; fewer than VOL_WINDOW valid
    trailing bars counts as volatile (conservative, same as the dense rule).
    Equivalence on dense paths is pinned by test."""
    if pos < VOL_WINDOW:
        return True
    with np.errstate(invalid="ignore", divide="ignore"):
        rng_frac = (high - low) / close
    window = rng_frac[pos - VOL_WINDOW:pos]
    valid = window[~np.isnan(window)]
    if len(valid) < VOL_WINDOW or np.isnan(rng_frac[pos]):
        return True
    return rng_frac[pos] > np.percentile(valid, VOL_PCTILE)


def atm_strike(paths: DayPaths, pos: int) -> float | None:
    """Strike nearest spot at `pos` among strikes with BOTH legs present."""
    s = paths.spot[pos]
    if np.isnan(s):
        return None
    best, best_d = None, np.inf
    for k in paths.strikes:
        ce, pe = paths.close.get((k, "CE")), paths.close.get((k, "PE"))
        if ce is None or pe is None or np.isnan(ce[pos]) or np.isnan(pe[pos]):
            continue
        d = abs(k - s)
        if d < best_d:
            best, best_d = k, d
    return best


# ---------------- the Monte Carlo ----------------

@dataclass
class DayResult:
    trade_date: pd.Timestamp
    book: str
    is_expiry: bool
    ev: float                    # mean net Rs across draws, baseline spread
    ev_stress: float             # same draws, stress half-spread
    ev_focused: float            # FOCUSED_DESK sensitivity, baseline spread
    fill_rate: float
    no_fill_rate: float
    trunc_frac: float
    gross_move: float            # ex-friction reference (theta lives here)
    latency_drag: float
    adverse_drag: float
    spread_drag: float
    statutory: float
    ce_pnl: float                # per-leg mean net premium move x lot
    pe_pnl: float

    @property
    def gradeable(self) -> bool:
        return self.trunc_frac <= TRUNC_DAY_LIMIT and not math.isnan(self.ev)


def _exit_pos(latency_s: float) -> int:
    if not math.isfinite(latency_s):
        return LAST_BAR                       # forced flat by the close
    return min(EXIT_INTENT + max(1, math.ceil(latency_s / 60.0)), LAST_BAR)


def _leg_fill(paths: DayPaths, key: tuple, pos: int, side: str,
              half_spread: float) -> tuple[float, float, bool] | None:
    """(fill_price, close_at_pos, was_volatile) or None if bar missing."""
    h, l, c = paths.high[key], paths.low[key], paths.close[key]
    if np.isnan(c[pos]):
        return None
    vol = is_volatile(h, l, c, pos)
    if side == "B":
        base = h[pos] if vol else c[pos]
        return base * (1 + half_spread), c[pos], vol
    base = l[pos] if vol else c[pos]
    return base * (1 - half_spread), c[pos], vol


def simulate_day(paths: DayPaths, lot: int, trade_date: pd.Timestamp,
                 book: str, is_expiry: bool) -> DayResult:
    ord_ = pd.Timestamp(trade_date).toordinal()
    rng_owner = np.random.default_rng([MC_SEED, ord_])
    ent_lat = OWNER_2026_07.draw(N_DRAWS, rng_owner)
    ext_lat = OWNER_2026_07.draw(N_DRAWS, rng_owner)
    rng_desk = np.random.default_rng([MC_SEED, ord_, 99])
    ent_desk = FOCUSED_DESK.draw(N_DRAWS, rng_desk)
    ext_desk = FOCUSED_DESK.draw(N_DRAWS, rng_desk)

    # frictionless reference: closes one bar after each intent, ATM at bar 1
    ref = np.nan
    k0 = atm_strike(paths, ENTRY_INTENT + 1)
    if k0 is not None:
        legs = [paths.close[(k0, s)] for s in ("CE", "PE")]
        if all(not np.isnan(c[ENTRY_INTENT + 1]) and not np.isnan(c[EXIT_INTENT + 1])
               for c in legs):
            ref = sum(c[EXIT_INTENT + 1] - c[ENTRY_INTENT + 1] for c in legs) * lot

    def run_draws(entry_lat: np.ndarray, exit_lat: np.ndarray,
                  spreads: tuple[float, ...]) -> dict:
        nets = {hs: [] for hs in spreads}
        n_nofill = n_trunc = 0
        attrs = {"lat": [], "adv": [], "spr": [], "cost": [], "gross": [],
                 "ce": [], "pe": []}
        for el, xl in zip(entry_lat, exit_lat):
            a = arrival_pos(ENTRY_INTENT, el)
            if a is None or a >= BARS_PER_DAY:
                n_nofill += 1
                for hs in spreads:
                    nets[hs].append(0.0)      # abandoned order: flat, no cost
                continue
            k = atm_strike(paths, a)
            if k is None:
                n_trunc += 1
                continue
            e = _exit_pos(xl)
            legs = {}
            ok = True
            for s in ("CE", "PE"):
                key = (k, s)
                if key not in paths.close:
                    ok = False
                    break
                ent = _leg_fill(paths, key, a, "B", 0.0)
                ext = _leg_fill(paths, key, e, "S", 0.0)
                if ent is None or ext is None:
                    ok = False
                    break
                legs[s] = (ent, ext)
            if not ok:
                n_trunc += 1
                continue
            for hs in spreads:
                net = 0.0
                for s in ("CE", "PE"):
                    (eb, ec_, _ev), (xb, xc, _xv) = legs[s]
                    entry_px = eb * (1 + hs)
                    exit_px = xb * (1 - hs)
                    net += (exit_px - entry_px) * lot
                    net -= COST_MODEL.round_trip_cost(entry_px * lot,
                                                      exit_px * lot, "NSE")
                nets[hs].append(net)
            # attribution at the BASELINE spread only
            hs = spreads[0]
            g_closes = sum(legs[s][1][1] - legs[s][0][1] for s in ("CE", "PE")) * lot
            adv = sum((legs[s][0][0] - legs[s][0][1])
                      + (legs[s][1][1] - legs[s][1][0]) for s in ("CE", "PE")) * lot
            spr = sum(legs[s][0][0] + legs[s][1][0] for s in ("CE", "PE")) * hs * lot
            cost = sum(COST_MODEL.round_trip_cost(legs[s][0][0] * (1 + hs) * lot,
                                                  legs[s][1][0] * (1 - hs) * lot,
                                                  "NSE") for s in ("CE", "PE"))
            attrs["gross"].append(g_closes)
            attrs["lat"].append(g_closes - ref if not math.isnan(ref) else np.nan)
            attrs["adv"].append(-adv)
            attrs["spr"].append(-spr)
            attrs["cost"].append(cost)
            for s, name in (("CE", "ce"), ("PE", "pe")):
                attrs[name].append((legs[s][1][0] * (1 - hs)
                                    - legs[s][0][0] * (1 + hs)) * lot)
        return {"nets": nets, "n_nofill": n_nofill, "n_trunc": n_trunc,
                "attrs": attrs}

    owner = run_draws(ent_lat, ext_lat, (HALF_SPREAD, HALF_SPREAD_STRESS))
    desk = run_draws(ent_desk, ext_desk, (HALF_SPREAD,))

    def mean_or_nan(v):
        return float(np.mean(v)) if len(v) else float("nan")

    n_graded = len(owner["nets"][HALF_SPREAD])
    a = owner["attrs"]
    # attribution identity (per FILLED draw, baseline spread):
    #   net = gross_move(ref) + latency_drag + adverse_drag + spread_drag
    #         - statutory
    # gross_move is the day-constant frictionless reference; day EV also
    # averages in no-fill zeros, so EV vs the attribution sum can differ by
    # the no-fill dilution — that gap is itself the latency-abandon cost.
    with np.errstate(invalid="ignore"):
        lat_drag = float(np.nanmean(a["lat"])) if len(a["lat"]) else float("nan")
    return DayResult(
        trade_date=trade_date, book=book, is_expiry=bool(is_expiry),
        ev=mean_or_nan(owner["nets"][HALF_SPREAD]),
        ev_stress=mean_or_nan(owner["nets"][HALF_SPREAD_STRESS]),
        ev_focused=mean_or_nan(desk["nets"][HALF_SPREAD]),
        fill_rate=(n_graded - owner["n_nofill"]) / N_DRAWS,
        no_fill_rate=owner["n_nofill"] / N_DRAWS,
        trunc_frac=owner["n_trunc"] / N_DRAWS,
        gross_move=float(ref),
        latency_drag=lat_drag,
        adverse_drag=mean_or_nan(a["adv"]),
        spread_drag=mean_or_nan(a["spr"]),
        statutory=mean_or_nan(a["cost"]),
        ce_pnl=mean_or_nan(a["ce"]), pe_pnl=mean_or_nan(a["pe"]),
    )


# ---------------- orchestration + gates ----------------

@dataclass
class Gate:
    name: str
    passed: bool
    detail: str


def run(asof: datetime | None = None, root=None) -> dict:
    asof = asof or datetime.now(timezone.utc)
    frame = assemble(asof, root=root)
    ticket_days = frame[frame["book"].isin(["TOP", "BOTTOM"])]

    tidy = pit.load(
        "dhan_rolling_1m", asof, root=root,
        columns=["ts", "side", "strike", "high", "low", "close", "spot",
                 "trade_date", "available_at"])
    tidy = tidy[tidy["trade_date"].isin(ticket_days["trade_date"])]
    by_day = {td: rows for td, rows in tidy.groupby("trade_date")}

    results: list[DayResult] = []
    for row in ticket_days.itertuples():
        day_rows = by_day.get(row.trade_date, pd.DataFrame())
        if day_rows.empty:
            results.append(DayResult(
                trade_date=row.trade_date, book=row.book,
                is_expiry=bool(row.is_expiry), ev=float("nan"),
                ev_stress=float("nan"), ev_focused=float("nan"),
                fill_rate=0.0, no_fill_rate=0.0, trunc_frac=1.0,
                gross_move=float("nan"), latency_drag=float("nan"),
                adverse_drag=float("nan"), spread_drag=float("nan"),
                statutory=float("nan"), ce_pnl=float("nan"),
                pe_pnl=float("nan")))
            continue
        results.append(simulate_day(build_day_paths(day_rows), int(row.lot),
                                    row.trade_date, row.book, row.is_expiry))

    res = pd.DataFrame([r.__dict__ for r in results])
    res["gradeable"] = [r.gradeable for r in results]
    dropped = res[~res["gradeable"]]
    g = res[res["gradeable"]].sort_values("trade_date").reset_index(drop=True)
    top = g[g["book"] == "TOP"].reset_index(drop=True)
    bot = g[g["book"] == "BOTTOM"].reset_index(drop=True)
    if len(top) < MIN_TOP_DAYS:
        raise RuntimeError(f"only {len(top)} gradeable top-cut days — "
                           "sample too thin to grade honestly")

    ev_top = top["ev"].to_numpy()
    point = float(ev_top.mean())
    dist = mbb_index_distribution(
        len(ev_top), lambda idx: float(ev_top[idx].mean()),
        block_size=BLOCK_SESSIONS, n_resamples=N_RESAMPLES, seed=BOOT_SEED)
    lo, hi = np.percentile(dist, [(1 - CI) / 2 * 100, (1 + CI) / 2 * 100])
    p = two_sided_p(dist)

    stress = float(top["ev_stress"].mean())

    # conditioning differential over the combined day sequence
    ev_all = g["ev"].to_numpy()
    is_top = (g["book"] == "TOP").to_numpy()
    is_bot = (g["book"] == "BOTTOM").to_numpy()

    def diff_stat(idx: np.ndarray) -> float:
        t, b = idx[is_top[idx]], idx[is_bot[idx]]
        if len(t) == 0 or len(b) == 0:
            return np.nan
        return float(ev_all[t].mean() - ev_all[b].mean())

    diff_point = float(ev_top.mean() - bot["ev"].to_numpy().mean())
    ddist = mbb_index_distribution(
        len(ev_all), diff_stat, block_size=BLOCK_SESSIONS,
        n_resamples=N_RESAMPLES, seed=BOOT_SEED + 1)
    ddist = ddist[~np.isnan(ddist)]
    dlo, dhi = np.percentile(ddist, [(1 - CI) / 2 * 100, (1 + CI) / 2 * 100])

    half = len(ev_top) // 2
    h1, h2 = float(ev_top[:half].mean()), float(ev_top[half:].mean())

    gates = [
        Gate("primary_ev_ci", point > 0 and lo > 0,
             f"mean net {point:+.0f} Rs/ticket, {CI:.0%} CI [{lo:+.0f}, {hi:+.0f}]"),
        Gate("stress_spread", stress > 0,
             f"EV at {HALF_SPREAD_STRESS:.2%} half-spread {stress:+.0f} Rs"),
        Gate("conditioning_diff", diff_point > 0 and dlo > 0,
             f"top-bottom {diff_point:+.0f} Rs, CI [{dlo:+.0f}, {dhi:+.0f}]"),
        Gate("bh_deflated_p", p <= BH_ALPHA,
             f"p={p:.5f} vs threshold {BH_ALPHA:.5f}"),
        Gate("split_half_sign", np.sign(h1) == np.sign(h2) != 0,
             f"halves {h1:+.0f} / {h2:+.0f} Rs"),
    ]
    verdict = "GO" if all(gt.passed for gt in gates) else (
        "INVERTED" if (point < 0 and hi < 0) else "NO-GO")

    def m(col, mask=None):
        s = top[col] if mask is None else top[col][mask]
        return float(s.mean()) if len(s) else float("nan")

    exp_mask = top["is_expiry"].to_numpy()
    return {
        "study": "H-001b",
        "n_days": int(len(g)),
        "n_top": int(len(top)),
        "n_bottom": int(len(bot)),
        "sample": [str(g["trade_date"].min().date()),
                   str(g["trade_date"].max().date())],
        "primary": {"mean_ev_rs": point, "ci": [float(lo), float(hi)],
                    "p": float(p)},
        "stress_ev_rs": stress,
        "differential": {"top_minus_bottom_rs": diff_point,
                         "ci": [float(dlo), float(dhi)]},
        "split_half": [h1, h2],
        "fill": {"fill_rate": m("fill_rate"),
                 "no_fill_rate": m("no_fill_rate"),
                 "dropped_days": [str(d.date()) for d in dropped["trade_date"]],
                 "mean_trunc_frac": m("trunc_frac")},
        "secondary": {
            "expiry_day_ev": m("ev", exp_mask),
            "non_expiry_ev": m("ev", ~exp_mask),
            "n_expiry_days": int(exp_mask.sum()),
            "focused_desk_ev": m("ev_focused"),
            "bottom_book_ev": float(bot["ev"].mean()) if len(bot) else float("nan"),
            "per_leg": {"ce_pnl": m("ce_pnl"), "pe_pnl": m("pe_pnl")},
        },
        "attribution_rs_per_ticket": {
            "gross_move_ex_friction": m("gross_move"),
            "latency_drag": m("latency_drag"),
            "adverse_drag": m("adverse_drag"),
            "spread_drag": m("spread_drag"),
            "statutory": -m("statutory"),
        },
        "gates": [{"name": gt.name, "passed": bool(gt.passed),
                   "detail": gt.detail} for gt in gates],
        "verdict": verdict,
    }
