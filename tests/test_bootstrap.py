import numpy as np
import pytest

from alpha.study.bootstrap import (
    MIN_BLOCK_SESSIONS, moving_block_bootstrap, stationary_bootstrap,
)


def _ar1(n, phi=0.85, seed=0):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal()
    return x


def test_block_size_floor_enforced():
    with pytest.raises(ValueError, match="weekly expiry cycle"):
        moving_block_bootstrap(np.arange(50.0), block_size=3)
    with pytest.raises(ValueError, match="mean_block"):
        stationary_bootstrap(np.arange(50.0), mean_block=3)


def test_block_ci_wider_than_iid_on_autocorrelated_data():
    # THE point of block bootstrap: on serially-correlated data, an i.i.d.
    # resample under-estimates uncertainty; blocks preserve dependence and
    # widen the interval honestly.
    x = _ar1(600, phi=0.85)

    def iid_ci(v, n=2000, ci=0.90, seed=1):
        rng = np.random.default_rng(seed)
        d = np.array([rng.choice(v, size=len(v), replace=True).mean() for _ in range(n)])
        return np.percentile(d, 95) - np.percentile(d, 5)

    block = moving_block_bootstrap(x, block_size=10, n_resamples=2000, seed=1)
    block_width = block["hi"] - block["lo"]
    assert block_width > iid_ci(x) * 1.3   # meaningfully wider


def test_point_estimate_matches_statistic():
    x = _ar1(200)
    res = moving_block_bootstrap(x, block_size=10, seed=2)
    assert res["point"] == pytest.approx(float(np.mean(x)))
    assert res["lo"] < res["point"] < res["hi"]


def test_stationary_bootstrap_runs_and_brackets_point():
    x = _ar1(300, phi=0.7)
    res = stationary_bootstrap(x, mean_block=10, n_resamples=1500, seed=3)
    assert res["lo"] < res["point"] < res["hi"]
    assert res["mean_block"] == 10
