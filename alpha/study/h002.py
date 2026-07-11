"""H-002 — intraday calm-bar entry: H001r's signal, H001b's autopsy applied.

Pre-registration: ledger/H002-intraday-calm-entry.md — frozen before this
module produced a number (scripts/run_study.py enforces).

H001b's attribution showed adverse fills (−₹560) ate the edge, and the
entry rule guaranteed them: every 09:16–09:30 arrival paid the bar's HIGH
by the insufficient-history clause. H002 changes ONE thing — entry waits
for the first calm bar at or after bar 30 (09:45), where the volatility
test has full trailing history and ~75% of bars are calm by construction.
Everything else (conditioning, structure, exit, fills, costs, latency,
statistics) is H001b's machinery, imported rather than re-implemented, so
a difference in verdict is attributable to the entry redesign alone.

The trigger is deterministic per day; latency randomness applies AFTER it.
A day with no calm bar by 13:00 takes no ticket — counted per book, never
silently dropped.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from alpha.data import pit
from alpha.measure.execution_mc import FOCUSED_DESK, OWNER_2026_07, arrival_pos
from alpha.study.bootstrap import mbb_index_distribution, two_sided_p
from alpha.study.h001b import (
    BARS_PER_DAY, CI, DayPaths, DayResult, EXIT_INTENT, Gate, HALF_SPREAD,
    HALF_SPREAD_STRESS, MIN_TOP_DAYS, N_RESAMPLES, TRUNC_DAY_LIMIT,
    _exit_pos, _leg_fill, assemble, atm_strike, build_day_paths, is_volatile,
)
from alpha.study.h001b import COST_MODEL

# ---- frozen study parameters (mirror of the pre-registration) ----
N_DRAWS = 400
MC_SEED = 12
BLOCK_SESSIONS = 10
BOOT_SEED = 46
BH_ALPHA = 0.10 / 8                   # q=0.10, family m=8, rank-1 conservative
TRIGGER_FIRST = 30                    # 09:45 — full trailing history exists
TRIGGER_LAST = 225                    # 13:00 — later entries not worth theta


def find_trigger(paths: DayPaths) -> int | None:
    """First bar t in [TRIGGER_FIRST, TRIGGER_LAST] where BOTH legs of the
    minute-t ATM strike are calm under the frozen volatility test."""
    for t in range(TRIGGER_FIRST, TRIGGER_LAST + 1):
        k = atm_strike(paths, t)
        if k is None:
            continue
        calm = True
        for s in ("CE", "PE"):
            key = (k, s)
            if key not in paths.close or is_volatile(
                    paths.high[key], paths.low[key], paths.close[key], t):
                calm = False
                break
        if calm:
            return t
    return None


def simulate_day(paths: DayPaths, trigger: int, lot: int,
                 trade_date: pd.Timestamp, book: str,
                 is_expiry: bool) -> tuple[DayResult, float]:
    """H001b's Monte Carlo with the entry intent at the trigger bar.
    Returns (DayResult, entry_adverse_hit_rate)."""
    ord_ = pd.Timestamp(trade_date).toordinal()
    rng_owner = np.random.default_rng([MC_SEED, ord_])
    ent_lat = OWNER_2026_07.draw(N_DRAWS, rng_owner)
    ext_lat = OWNER_2026_07.draw(N_DRAWS, rng_owner)
    rng_desk = np.random.default_rng([MC_SEED, ord_, 99])
    ent_desk = FOCUSED_DESK.draw(N_DRAWS, rng_desk)
    ext_desk = FOCUSED_DESK.draw(N_DRAWS, rng_desk)

    ref = np.nan
    k0 = atm_strike(paths, trigger + 1)
    if k0 is not None:
        legs = [paths.close[(k0, s)] for s in ("CE", "PE")]
        if all(not np.isnan(c[trigger + 1]) and not np.isnan(c[EXIT_INTENT + 1])
               for c in legs):
            ref = sum(c[EXIT_INTENT + 1] - c[trigger + 1] for c in legs) * lot

    def run_draws(entry_lat, exit_lat, spreads):
        nets = {hs: [] for hs in spreads}
        n_nofill = n_trunc = n_adverse_entry = 0
        attrs = {"lat": [], "adv": [], "spr": [], "cost": [], "gross": [],
                 "ce": [], "pe": []}
        for el, xl in zip(entry_lat, exit_lat):
            a = arrival_pos(trigger, el)
            if a is None or a >= BARS_PER_DAY:
                n_nofill += 1
                for hs in spreads:
                    nets[hs].append(0.0)
                continue
            k = atm_strike(paths, a)
            if k is None:
                n_trunc += 1
                continue
            e = _exit_pos(xl)
            legs, ok = {}, True
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
            if any(legs[s][0][2] for s in ("CE", "PE")):
                n_adverse_entry += 1
            for hs in spreads:
                net = 0.0
                for s in ("CE", "PE"):
                    (eb, _ec, _ev), (xb, _xc, _xv) = legs[s]
                    entry_px = eb * (1 + hs)
                    exit_px = xb * (1 - hs)
                    net += (exit_px - entry_px) * lot
                    net -= COST_MODEL.round_trip_cost(entry_px * lot,
                                                      exit_px * lot, "NSE")
                nets[hs].append(net)
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
                "n_adverse_entry": n_adverse_entry, "attrs": attrs}

    owner = run_draws(ent_lat, ext_lat, (HALF_SPREAD, HALF_SPREAD_STRESS))
    desk = run_draws(ent_desk, ext_desk, (HALF_SPREAD,))

    def mean_or_nan(v):
        return float(np.mean(v)) if len(v) else float("nan")

    n_graded = len(owner["nets"][HALF_SPREAD])
    n_filled = n_graded - owner["n_nofill"]
    a = owner["attrs"]
    with np.errstate(invalid="ignore"):
        lat_drag = float(np.nanmean(a["lat"])) if len(a["lat"]) else float("nan")
    result = DayResult(
        trade_date=trade_date, book=book, is_expiry=bool(is_expiry),
        ev=mean_or_nan(owner["nets"][HALF_SPREAD]),
        ev_stress=mean_or_nan(owner["nets"][HALF_SPREAD_STRESS]),
        ev_focused=mean_or_nan(desk["nets"][HALF_SPREAD]),
        fill_rate=n_filled / N_DRAWS,
        no_fill_rate=owner["n_nofill"] / N_DRAWS,
        trunc_frac=owner["n_trunc"] / N_DRAWS,
        gross_move=float(ref),
        latency_drag=lat_drag,
        adverse_drag=mean_or_nan(a["adv"]),
        spread_drag=mean_or_nan(a["spr"]),
        statutory=mean_or_nan(a["cost"]),
        ce_pnl=mean_or_nan(a["ce"]), pe_pnl=mean_or_nan(a["pe"]),
    )
    adverse_rate = (owner["n_adverse_entry"] / n_filled) if n_filled else float("nan")
    return result, adverse_rate


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
    adverse_rates: list[float] = []
    trigger_bars: list[int] = []
    untriggered = {"TOP": 0, "BOTTOM": 0}
    for row in ticket_days.itertuples():
        day_rows = by_day.get(row.trade_date, pd.DataFrame())
        if day_rows.empty:
            untriggered[row.book] += 1      # no data in the window = no ticket
            continue
        paths = build_day_paths(day_rows)
        t = find_trigger(paths)
        if t is None:
            untriggered[row.book] += 1
            continue
        res, adv_rate = simulate_day(paths, t, int(row.lot), row.trade_date,
                                     row.book, row.is_expiry)
        results.append(res)
        adverse_rates.append(adv_rate)
        trigger_bars.append(t)

    res = pd.DataFrame([r.__dict__ for r in results])
    res["gradeable"] = [r.gradeable for r in results]
    res["adverse_rate"] = adverse_rates
    res["trigger_bar"] = trigger_bars
    dropped = res[~res["gradeable"]]
    g = res[res["gradeable"]].sort_values("trade_date").reset_index(drop=True)
    top = g[g["book"] == "TOP"].reset_index(drop=True)
    bot = g[g["book"] == "BOTTOM"].reset_index(drop=True)
    if len(top) < MIN_TOP_DAYS:
        raise RuntimeError(f"only {len(top)} gradeable triggered top-cut days")

    ev_top = top["ev"].to_numpy()
    point = float(ev_top.mean())
    dist = mbb_index_distribution(
        len(ev_top), lambda idx: float(ev_top[idx].mean()),
        block_size=BLOCK_SESSIONS, n_resamples=N_RESAMPLES, seed=BOOT_SEED)
    lo, hi = np.percentile(dist, [(1 - CI) / 2 * 100, (1 + CI) / 2 * 100])
    p = two_sided_p(dist)
    stress = float(top["ev_stress"].mean())

    ev_all = g["ev"].to_numpy()
    is_top = (g["book"] == "TOP").to_numpy()
    is_bot = (g["book"] == "BOTTOM").to_numpy()

    def diff_stat(idx: np.ndarray) -> float:
        t_, b_ = idx[is_top[idx]], idx[is_bot[idx]]
        if len(t_) == 0 or len(b_) == 0:
            return np.nan
        return float(ev_all[t_].mean() - ev_all[b_].mean())

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
    tb = top["trigger_bar"].to_numpy()
    return {
        "study": "H-002",
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
        "trigger": {"untriggered_top": untriggered["TOP"],
                    "untriggered_bottom": untriggered["BOTTOM"],
                    "entry_adverse_hit_rate": m("adverse_rate"),
                    "trigger_bar_q25_q50_q75": [
                        float(np.percentile(tb, q)) for q in (25, 50, 75)]},
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
