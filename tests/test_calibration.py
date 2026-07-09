import numpy as np
import pytest

from alpha.model.calibration import (
    Calibrator, brier_score, expected_calibration_error, reliability_curve,
    walk_forward_calibrate,
)
from alpha.study.walkforward import PurgedWalkForward


def test_brier_hand_computed():
    # p=[.9,.2], y=[1,0] -> ((.9-1)^2 + (.2-0)^2)/2 = (.01+.04)/2 = .025
    assert brier_score([0.9, 0.2], [1, 0]) == pytest.approx(0.025)


def test_ece_zero_when_perfectly_calibrated():
    # in each bin, predicted confidence == empirical accuracy
    p = np.r_[np.full(100, 0.2), np.full(100, 0.8)]
    rng = np.random.default_rng(0)
    y = np.r_[(rng.random(100) < 0.2).astype(int), (rng.random(100) < 0.8).astype(int)]
    # accuracy per bin ~ confidence; ECE should be small
    assert expected_calibration_error(p, y, n_bins=10) < 0.06


def test_ece_large_when_miscalibrated():
    # predict 0.9 everywhere but win only 10% of the time
    p = np.full(200, 0.9)
    y = (np.arange(200) < 20).astype(int)
    assert expected_calibration_error(p, y) > 0.7


def test_switch_to_platt_on_sparse_fold():
    rng = np.random.default_rng(1)
    scores = rng.random(120)                     # < 200 -> must downgrade
    y = (rng.random(120) < scores).astype(int)
    cal = Calibrator(min_isotonic=200).fit(scores, y)
    assert cal.method == "platt"


def test_uses_isotonic_when_ample():
    rng = np.random.default_rng(2)
    scores = rng.random(1000)
    y = (rng.random(1000) < scores).astype(int)
    cal = Calibrator(min_isotonic=200).fit(scores, y)
    assert cal.method == "isotonic"


def test_platt_gives_smooth_monotone_output_on_sparse_data():
    # isotonic would collapse toward 0/1 steps on this thin set; Platt stays smooth
    rng = np.random.default_rng(3)
    scores = np.sort(rng.random(60))
    y = (rng.random(60) < scores).astype(int)
    cal = Calibrator(min_isotonic=200).fit(scores, y)
    out = cal.transform(scores)
    assert cal.method == "platt"
    assert np.all(np.diff(out) >= -1e-9)         # monotone non-decreasing
    assert out.min() > 0.0 and out.max() < 1.0   # not collapsed to extremes


def test_walk_forward_calibrate_is_out_of_fold():
    rng = np.random.default_rng(4)
    n = 600
    scores = rng.random(n)
    y = (rng.random(n) < scores).astype(int)
    entry = np.arange(n)
    exit_ = entry + 1
    wf = PurgedWalkForward(n_splits=5, embargo_sessions=2)
    res = walk_forward_calibrate(scores, y, entry, exit_, wf)
    assert res["n_scored"] > 0
    assert 0.0 <= res["brier"] <= 1.0
    assert not np.isnan(res["ece"])
    # every fold reports which calibrator it used
    assert set(res["fold_methods"]) <= {"isotonic", "platt"}


def test_reliability_curve_shapes():
    p = np.linspace(0, 1, 100)
    y = (np.arange(100) % 2)
    rc = reliability_curve(p, y, n_bins=5)
    assert len(rc["confidence"]) == 5 and len(rc["accuracy"]) == 5
    assert sum(rc["count"]) == 100
