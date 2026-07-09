"""Execution simulator v1 — stochastic manual latency + volatility-adaptive
adverse fills, run as a Monte Carlo. One ticket in, a NET-P&L DISTRIBUTION
out. A single-number backtest under random latency is a point estimate
dressed up as sophistication; the distribution is the product.

LATENCY PRIOR — human-calibrated 2026-07-09 from the owner's own report:
"30 seconds to 5 minutes and all the time frames in between, max we'll
stretch is 15 mins." Fitted log-normal: mu=4.55, sigma=0.90 (seconds) ->
median ~95 s, mean ~142 s, P10 ~30 s, P90 ~5 min; draws past ABANDON
(900 s) are NO-FILL — a 15-minute-old signal is not chased, and the miss is
graded as a miss. The optimistic desk profile discussed during design
(mu=3.4, sigma=0.5, median ~30 s) is kept ONLY as a named sensitivity
scenario: it contradicts the owner's report and would flatter the backtest.

ADVERSE FILLS — heavy-writing days are exactly the days liquidity pulls:
if the arrival minute's range is wide vs its trailing distribution, a buyer
pays that bar's HIGH (a seller receives its LOW), never the close. Half the
edge dies in moments like these, so they are modeled, not averaged away.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from alpha.measure.costs import OptionCostModel
from alpha.measure.labeler import Barriers, triple_barrier

NO_FILL = "no_fill"


@dataclass(frozen=True)
class LatencyModel:
    """L ~ LogNormal(mu, sigma) seconds, censored to NO-FILL past abandon_s."""
    mu: float = 4.55
    sigma: float = 0.90
    abandon_s: float = 900.0
    name: str = "owner_2026_07"

    def draw(self, n: int, rng: np.random.Generator) -> np.ndarray:
        lat = rng.lognormal(self.mu, self.sigma, size=n)
        lat[lat > self.abandon_s] = np.inf   # inf = abandoned, no fill
        return lat


#: Owner-reported profile — the DEFAULT for every promotion decision.
OWNER_2026_07 = LatencyModel()
#: Optimistic sensitivity scenario only. Never the promotion baseline.
FOCUSED_DESK = LatencyModel(mu=3.4, sigma=0.5, name="focused_desk")


@dataclass(frozen=True)
class AdverseFillModel:
    """Fill at the arrival bar, penalised when that bar is volatile.

    volatile := (high-low)/close of the arrival bar exceeds the vol_pctile
    of the trailing vol_window bars' ranges. Volatile -> buyer pays the
    bar's HIGH / seller receives the LOW; calm -> the bar's close. The
    half-spread is applied on top either way (the high is a trade print,
    the ask sits above it). Insufficient trailing history counts as
    volatile — conservative by construction.
    """
    half_spread_frac: float
    vol_window: int = 30
    vol_pctile: float = 75.0

    def _is_volatile(self, path: pd.DataFrame, pos: int) -> bool:
        lo = pos - self.vol_window
        if lo < 0:
            return True
        rng_frac = ((path["high"] - path["low"]) / path["close"]).to_numpy()
        # strict >: a bar merely EQUAL to its trailing percentile is not
        # unusually volatile (ties would otherwise flag every bar of a flat
        # tape as adverse)
        return rng_frac[pos] > np.percentile(rng_frac[lo:pos], self.vol_pctile)

    def fill_price(self, path: pd.DataFrame, pos: int, side: str) -> float:
        bar = path.iloc[pos]
        if side == "B":
            base = float(bar["high"]) if self._is_volatile(path, pos) else float(bar["close"])
            return base * (1 + self.half_spread_frac)
        base = float(bar["low"]) if self._is_volatile(path, pos) else float(bar["close"])
        return base * (1 - self.half_spread_frac)


def arrival_pos(signal_pos: int, latency_s: float) -> int | None:
    """Bar index where a latency-delayed order lands. ceil to the NEXT bar
    boundary (a 30 s delay cannot fill inside the signal bar's history)."""
    if not math.isfinite(latency_s):
        return None
    return signal_pos + max(1, math.ceil(latency_s / 60.0))


@dataclass(frozen=True)
class McTicket:
    """A long-premium ticket graded per latency draw."""
    qty: int
    target_ret: float
    stop_ret: float
    max_bars: int


def simulate_ticket(
    ticket: McTicket,
    path: pd.DataFrame,            # 1-min premium bars {timestamp,high,low,close}
    signal_pos: int,
    cost_model: OptionCostModel,
    fill_model: AdverseFillModel,
    latency: LatencyModel = OWNER_2026_07,
    n_draws: int = 500,
    seed: int = 7,
    exchange: str = "NSE",
) -> dict:
    """Monte Carlo over latency draws -> net-P&L distribution for one ticket.

    Exit uses the SAME machinery as everything else (triple_barrier on the
    post-fill path); the exit crosses the spread at the barrier level.
    """
    rng = np.random.default_rng(seed)
    draws = latency.draw(n_draws, rng)
    nets, outcomes = [], []
    for lat in draws:
        pos = arrival_pos(signal_pos, lat)
        if pos is None or pos >= len(path):
            outcomes.append(NO_FILL)
            continue
        entry = fill_model.fill_price(path, pos, "B")
        post = path.iloc[pos + 1:].reset_index(drop=True)
        barriers = Barriers.from_returns(entry, 1, ticket.target_ret,
                                         ticket.stop_ret, ticket.max_bars)
        label = triple_barrier(post, entry, barriers, direction=1,
                               entry_time=path.iloc[pos]["timestamp"])
        if not label.is_gradeable:
            outcomes.append(label.outcome)
            continue
        exit_receive = label.exit_price * (1 - fill_model.half_spread_frac)
        gross = (exit_receive - entry) * ticket.qty
        costs = cost_model.round_trip_cost(entry * ticket.qty,
                                           exit_receive * ticket.qty, exchange)
        nets.append(gross - costs)
        outcomes.append(label.outcome)

    nets_arr = np.array(nets, dtype=float)
    filled = len(nets_arr)
    return {
        "latency_model": latency.name,
        "n_draws": n_draws,
        "fill_rate": filled / n_draws,
        "no_fill_rate": outcomes.count(NO_FILL) / n_draws,
        "net_mean": float(nets_arr.mean()) if filled else float("nan"),
        "net_q05": float(np.percentile(nets_arr, 5)) if filled else float("nan"),
        "net_q50": float(np.percentile(nets_arr, 50)) if filled else float("nan"),
        "net_q95": float(np.percentile(nets_arr, 95)) if filled else float("nan"),
        "p_profitable": float((nets_arr > 0).mean()) if filled else float("nan"),
        "outcome_counts": {k: outcomes.count(k) for k in set(outcomes)},
        "nets": nets_arr,
    }
