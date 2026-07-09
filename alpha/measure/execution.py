"""Execution fill model — turns a signal into a tradeable fill price.

A signal is not a fill. Two effects separate them, and both flattered the
sibling project's backtest until they were modeled:

1. Manual delay. The human sees the signal and places the order by hand
   (README: execution is always manual). The market moves during that
   reaction time, so the fill reference is the price `delay_bars` AFTER the
   signal bar, not the signal price. With 1-minute bars, delay_bars=2 ~ two
   minutes of human latency. Stress it upward, never assume instant.

2. Spread. A buyer pays the ask, a seller hits the bid — never the mid.
   `half_spread_frac` is a REQUIRED input: pass it per-fill or set a model
   default, but there is no silent zero. We have no historical option depth
   yet, so until GammaLeak's .depth.csv collection yields measured spreads,
   every fill is marked `spread_estimated=True` and the grader treats such
   P&L as an estimate, not a measurement.

If the path is too short to reach the delay bar (signal fired too close to
the close to fill), `fill` returns None — a real, recordable "could not
trade" outcome, not a free fill at the last price.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Fill:
    side: str                 # 'B' or 'S'
    signal_time: pd.Timestamp
    fill_time: pd.Timestamp
    reference_mid: float      # mid at fill time, before spread
    fill_price: float         # what you actually pay/receive, spread applied
    delay_bars: int
    half_spread_paid: float   # price units given up to the spread
    spread_estimated: bool


@dataclass(frozen=True)
class FillModel:
    delay_bars: int = 1
    default_half_spread_frac: float | None = None
    spread_is_measured: bool = False   # flip to True only with real depth data

    def fill(
        self,
        side: str,
        path_from_signal: pd.DataFrame,
        half_spread_frac: float | None = None,
    ) -> Fill | None:
        """Resolve a fill.

        path_from_signal: bars starting AT the signal bar (row 0 = signal bar),
          columns {timestamp, close}. The fill lands at row `delay_bars`.
        half_spread_frac: overrides the model default for this fill. One of
          the two must be set — a missing spread raises, never defaults to 0.
        """
        if side not in ("B", "S"):
            raise ValueError(f"side must be 'B' or 'S', got {side!r}")
        for col in ("timestamp", "close"):
            if col not in path_from_signal.columns:
                raise ValueError(f"path missing column {col!r}")

        hs = half_spread_frac if half_spread_frac is not None else self.default_half_spread_frac
        if hs is None:
            raise ValueError(
                "half_spread_frac is required — the model will not assume a "
                "zero spread. Provide a measured/estimated half-spread."
            )
        if hs < 0:
            raise ValueError("half_spread_frac must be >= 0")

        if self.delay_bars >= len(path_from_signal):
            return None  # cannot fill: not enough bars after the signal

        bar = path_from_signal.iloc[self.delay_bars]
        mid = float(bar["close"])
        # buyer pays up, seller receives less — spread is always adverse
        signed = 1.0 if side == "B" else -1.0
        fill_price = mid * (1 + signed * hs)
        return Fill(
            side=side,
            signal_time=path_from_signal.iloc[0]["timestamp"],
            fill_time=bar["timestamp"],
            reference_mid=mid,
            fill_price=fill_price,
            delay_bars=self.delay_bars,
            half_spread_paid=abs(fill_price - mid),
            spread_estimated=not self.spread_is_measured,
        )
