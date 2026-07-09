"""Phase 4 — probability calibration and scoring.

The product is a calibrated probability: the abstention threshold is
`p_calibrated x payoff > cost hurdle`, so an uncalibrated 0.6 is worthless.
Calibration must be fit INSIDE the walk-forward (train fold only) or it leaks;
and it must survive sparse folds, because an abstention-default system
produces few qualifying tickets. See calibration.py.
"""
