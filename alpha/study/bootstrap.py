"""Block bootstrap for time-dependent trade series.

Trade outcomes are not i.i.d.: option costs, spreads, and trendiness cluster
in time (a volatile fortnight makes every ticket in it correlated). An
ordinary bootstrap that resamples individual observations assumes independence
and therefore reports confidence intervals that are too tight — a fabricated
certainty. The moving-block and stationary bootstraps resample contiguous
blocks instead, preserving the serial correlation.

Block length must span at least a weekly expiry cycle. The floor here is 5
sessions; the default is 10 (about two cycles), and it is a documented choice,
never a silent guess. Pass `values` ordered in time at session granularity so
a block truly covers whole cycles.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

MIN_BLOCK_SESSIONS = 5


def _percentile_ci(dist: np.ndarray, ci: float) -> tuple[float, float]:
    lo = float(np.percentile(dist, (1 - ci) / 2 * 100))
    hi = float(np.percentile(dist, (1 + ci) / 2 * 100))
    return lo, hi


def moving_block_bootstrap(
    values,
    statistic: Callable[[np.ndarray], float] = np.mean,
    block_size: int = 10,
    n_resamples: int = 2000,
    ci: float = 0.90,
    seed: int | None = None,
) -> dict:
    """Moving Block Bootstrap. Blocks of `block_size` contiguous observations
    are drawn with replacement and concatenated to the original length."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n < MIN_BLOCK_SESSIONS:
        raise ValueError(f"need at least {MIN_BLOCK_SESSIONS} observations")
    if block_size < MIN_BLOCK_SESSIONS:
        raise ValueError(
            f"block_size {block_size} < {MIN_BLOCK_SESSIONS}: too small to span a "
            f"weekly expiry cycle; serial correlation would be destroyed"
        )
    block_size = min(block_size, n)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_size))
    starts_max = n - block_size + 1

    dist = np.empty(n_resamples)
    for r in range(n_resamples):
        starts = rng.integers(0, starts_max, size=n_blocks)
        sample = np.concatenate([v[s:s + block_size] for s in starts])[:n]
        dist[r] = statistic(sample)
    lo, hi = _percentile_ci(dist, ci)
    return {"point": float(statistic(v)), "lo": lo, "hi": hi,
            "ci": ci, "block_size": block_size, "distribution": dist}


def stationary_bootstrap(
    values,
    statistic: Callable[[np.ndarray], float] = np.mean,
    mean_block: int = 10,
    n_resamples: int = 2000,
    ci: float = 0.90,
    seed: int | None = None,
) -> dict:
    """Politis-Romano stationary bootstrap: geometric block lengths (mean
    `mean_block`), circular indexing. More robust to the block-size choice
    than a fixed block."""
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n < MIN_BLOCK_SESSIONS:
        raise ValueError(f"need at least {MIN_BLOCK_SESSIONS} observations")
    if mean_block < MIN_BLOCK_SESSIONS:
        raise ValueError(f"mean_block must be >= {MIN_BLOCK_SESSIONS}")
    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block

    dist = np.empty(n_resamples)
    for r in range(n_resamples):
        sample = np.empty(n)
        i = rng.integers(0, n)
        for t in range(n):
            sample[t] = v[i % n]
            if rng.random() < p:
                i = rng.integers(0, n)   # start a new block
            else:
                i += 1                    # continue the block (wraps around)
        dist[r] = statistic(sample)
    lo, hi = _percentile_ci(dist, ci)
    return {"point": float(statistic(v)), "lo": lo, "hi": hi,
            "ci": ci, "mean_block": mean_block, "distribution": dist}
