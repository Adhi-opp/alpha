"""Purged, embargoed walk-forward cross-validation.

Each observation carries a label window in SESSION-INDEX space:
`entry_session` (the decision, e.g. day T, known before T's open) and
`exit_session` (when the triple-barrier label resolves, e.g. T+1 close for an
overnight trade). A standard chronological split leaks whenever a training
label's window reaches into the test period.

Two defenses, both mandatory:

- PURGE: drop any training observation whose label window
  [entry, exit] overlaps the test block's covered span. Such a label was
  realized using information contemporaneous with the test period.
- EMBARGO: drop training observations within `embargo_sessions` on EITHER
  side of the test block. The post-test side is the Lopez de Prado embargo
  (autocorrelated regimes bleed forward); the pre-test side is the buffer a
  forward-chaining split needs so the last sessions before the test — highly
  correlated with it — don't leak. Enforced floor: 2 sessions, because the
  labels here are overnight/intraday and adjacent sessions are strongly
  autocorrelated.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Fold:
    train: np.ndarray
    test: np.ndarray
    test_span: tuple[int, int]   # (lo, hi) session indices covered by the test


MIN_EMBARGO = 2


class PurgedWalkForward:
    def __init__(self, n_splits: int = 5, embargo_sessions: int = MIN_EMBARGO):
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if embargo_sessions < MIN_EMBARGO:
            raise ValueError(
                f"embargo_sessions must be >= {MIN_EMBARGO} — overnight/intraday "
                f"labels make adjacent sessions strongly autocorrelated"
            )
        self.n_splits = n_splits
        self.embargo = embargo_sessions

    def _purge_embargo(
        self, candidate: np.ndarray, entry: np.ndarray, exit_: np.ndarray,
        test_lo: int, test_hi: int,
    ) -> np.ndarray:
        keep = []
        for i in candidate:
            # PURGE: label window overlaps the test span
            if entry[i] <= test_hi and exit_[i] >= test_lo:
                continue
            # EMBARGO: entry falls within the embargo buffer on either side
            if (test_lo - self.embargo) <= entry[i] <= (test_hi + self.embargo):
                continue
            keep.append(i)
        return np.array(keep, dtype=int)

    def split(self, entry_session, exit_session, *, expanding: bool = True):
        """Yield forward-chaining folds over the session range.

        entry_session, exit_session: integer session indices, one per obs.
        expanding=True: train on all sessions before the test block (classic
        walk-forward). expanding=False: train on all sessions outside the test
        block (combinatorial), where the post-test embargo also bites.
        """
        entry = np.asarray(entry_session, dtype=int)
        exit_ = np.asarray(exit_session, dtype=int)
        if len(entry) != len(exit_):
            raise ValueError("entry_session and exit_session length mismatch")
        if np.any(exit_ < entry):
            raise ValueError("exit_session must be >= entry_session")

        s_lo, s_hi = int(entry.min()), int(entry.max())
        edges = np.linspace(s_lo, s_hi + 1, self.n_splits + 2).astype(int)
        idx = np.arange(len(entry))

        for k in range(1, self.n_splits + 1):
            lo, hi = edges[k], edges[k + 1] - 1
            test = idx[(entry >= lo) & (entry <= hi)]
            if len(test) == 0:
                continue
            test_lo = int(entry[test].min())
            test_hi = int(exit_[test].max())
            if expanding:
                candidate = idx[entry < lo]
            else:
                candidate = idx[(entry < lo) | (entry > hi)]
            train = self._purge_embargo(candidate, entry, exit_, test_lo, test_hi)
            if len(train) == 0:
                continue
            yield Fold(train=train, test=test, test_span=(test_lo, test_hi))


def to_session_index(dates, trading_days) -> np.ndarray:
    """Map calendar dates to their position in the sorted trading calendar."""
    import pandas as pd
    order = {d: i for i, d in enumerate(sorted(trading_days))}
    out = []
    for d in pd.to_datetime(dates):
        key = d.date()
        if key not in order:
            raise KeyError(f"{key} is not a trading day in the supplied calendar")
        out.append(order[key])
    return np.array(out, dtype=int)
