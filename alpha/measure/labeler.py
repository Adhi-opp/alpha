"""Triple-barrier labeler — target / stop / time, gap-honest, MAE+MFE.

This is the piece that made the sibling project's backtest lie: alerts were
graded at optimistic prices with cross-session windows and a claimed 79% hit
rate became 22% at tradeable fills. Every design choice here is the
pessimistic one:

- Same-bar ambiguity: if a single bar's [low, high] straddles BOTH the target
  and the stop, we cannot know which traded first from OHLC. We resolve to
  the STOP (adverse) and flag `ambiguous=True`. Only intrabar tick data can
  disprove this, and we don't have it for history.
- Gap honesty: if the price path ends before the time barrier AND before any
  barrier is touched, the outcome is `truncated`, NEVER `time`. A missing bar
  is missing information, not a neutral exit. The grader excludes truncated
  labels rather than scoring them as flat.
- MAE is recorded next to MFE always. A label that hit target is not "clean"
  if it first drew down through most of the stop distance.

Direction is +1 for a long position (option buyer: premium path rising is
favorable). The same code labels the underlying path or the option-premium
path — the caller chooses which price series to pass; the label semantics
are identical.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

TARGET = "target"
STOP = "stop"
TIME = "time"
TRUNCATED = "truncated"


@dataclass(frozen=True)
class Barriers:
    """Absolute price levels. Build from returns via `from_returns`."""
    target: float
    stop: float
    max_bars: int

    @staticmethod
    def from_returns(
        entry: float, direction: int, target_ret: float, stop_ret: float,
        max_bars: int,
    ) -> "Barriers":
        """target_ret and stop_ret are positive magnitudes (e.g. 0.20, 0.15).

        For a long, target sits above entry and stop below; for a short,
        reversed. Both are expressed as fractions of entry price.
        """
        if direction not in (1, -1):
            raise ValueError("direction must be +1 or -1")
        if target_ret <= 0 or stop_ret <= 0:
            raise ValueError("target_ret and stop_ret are positive magnitudes")
        return Barriers(
            target=entry * (1 + direction * target_ret),
            stop=entry * (1 - direction * stop_ret),
            max_bars=max_bars,
        )


@dataclass(frozen=True)
class Label:
    outcome: str            # target | stop | time | truncated
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    bars_held: int
    direction: int
    mfe: float              # max favorable excursion, signed favorable-positive
    mae: float              # max adverse excursion, signed adverse-negative
    ret: float              # realized return at exit, favorable-positive
    ambiguous: bool

    @property
    def hit_target(self) -> bool:
        return self.outcome == TARGET

    @property
    def is_gradeable(self) -> bool:
        """Truncated labels are missing information, not neutral exits."""
        return self.outcome != TRUNCATED


def _excursion(direction: int, entry: float, price: float) -> float:
    """Signed return of `price` vs `entry` in the trade's favorable frame."""
    return direction * (price - entry) / entry


def triple_barrier(
    path: pd.DataFrame,
    entry_price: float,
    barriers: Barriers,
    direction: int = 1,
    entry_time: pd.Timestamp | None = None,
) -> Label:
    """Label a single position.

    path: bars STRICTLY AFTER entry, chronological, columns
      {timestamp, high, low, close}. The caller supplies only the bars that
      actually exist — no forward-fill — so a data gap manifests as a short
      path and yields a `truncated` outcome.
    entry_price: fill price (from the execution model, not the signal price).
    """
    for col in ("timestamp", "high", "low", "close"):
        if col not in path.columns:
            raise ValueError(f"path missing column {col!r}")
    if direction not in (1, -1):
        raise ValueError("direction must be +1 or -1")
    if entry_time is None:
        entry_time = path["timestamp"].iloc[0] if len(path) else pd.NaT

    target, stop = barriers.target, barriers.stop
    mfe = 0.0
    mae = 0.0
    horizon = path.iloc[: barriers.max_bars]

    for i, bar in enumerate(horizon.itertuples(index=False), start=1):
        hi_exc = _excursion(direction, entry_price, bar.high)
        lo_exc = _excursion(direction, entry_price, bar.low)
        favorable = max(hi_exc, lo_exc)
        adverse = min(hi_exc, lo_exc)
        mfe = max(mfe, favorable)
        mae = min(mae, adverse)

        if direction == 1:
            hit_target = bar.high >= target
            hit_stop = bar.low <= stop
        else:
            hit_target = bar.low <= target
            hit_stop = bar.high >= stop

        if hit_target and hit_stop:
            # both levels inside one bar -> unknowable order -> assume adverse
            return Label(
                outcome=STOP, entry_time=entry_time, entry_price=entry_price,
                exit_time=bar.timestamp, exit_price=stop, bars_held=i,
                direction=direction, mfe=mfe,
                mae=min(mae, _excursion(direction, entry_price, stop)),
                ret=_excursion(direction, entry_price, stop), ambiguous=True,
            )
        if hit_target:
            return Label(
                outcome=TARGET, entry_time=entry_time, entry_price=entry_price,
                exit_time=bar.timestamp, exit_price=target, bars_held=i,
                direction=direction, mfe=max(mfe, _excursion(direction, entry_price, target)),
                mae=mae, ret=_excursion(direction, entry_price, target),
                ambiguous=False,
            )
        if hit_stop:
            return Label(
                outcome=STOP, entry_time=entry_time, entry_price=entry_price,
                exit_time=bar.timestamp, exit_price=stop, bars_held=i,
                direction=direction, mfe=mfe,
                mae=min(mae, _excursion(direction, entry_price, stop)),
                ret=_excursion(direction, entry_price, stop), ambiguous=False,
            )

    # No barrier touched within the bars we have.
    if len(path) < barriers.max_bars:
        # path ran out before the time barrier -> missing information
        last = path.iloc[-1] if len(path) else None
        return Label(
            outcome=TRUNCATED, entry_time=entry_time, entry_price=entry_price,
            exit_time=last.timestamp if last is not None else pd.NaT,
            exit_price=float(last.close) if last is not None else float("nan"),
            bars_held=len(path), direction=direction, mfe=mfe, mae=mae,
            ret=(_excursion(direction, entry_price, float(last.close))
                 if last is not None else float("nan")),
            ambiguous=False,
        )
    last = horizon.iloc[-1]
    return Label(
        outcome=TIME, entry_time=entry_time, entry_price=entry_price,
        exit_time=last.timestamp, exit_price=float(last.close),
        bars_held=barriers.max_bars, direction=direction, mfe=mfe, mae=mae,
        ret=_excursion(direction, entry_price, float(last.close)),
        ambiguous=False,
    )
