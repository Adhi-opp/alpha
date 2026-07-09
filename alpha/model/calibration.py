"""Probability calibration + scoring (Brier, ECE), fold-safe by construction.

Two failure modes this guards against:

1. Leakage. A `Calibrator` is fit on training scores and applied to unseen
   scores — never fit on the data it scores. `walk_forward_calibrate` fits a
   fresh calibrator per training fold and evaluates only out-of-fold, so the
   reported Brier/ECE are honest.

2. Isotonic overfitting on sparse folds. Isotonic regression is a
   non-parametric step function; with few positive instances it collapses
   probabilities to 0/1 and reports a deceptively good in-sample fit. Because
   abstention is the default, qualifying tickets are sparse. So the calibrator
   auto-DOWNGRADES to Platt scaling (a smooth 1-D logistic) when the training
   fold has fewer than `min_isotonic` active signals (default 200).

Metrics:
    Brier score  BS  = (1/N) Σ (f_t - o_t)^2
    ECE          ECE = Σ_m (|B_m|/N) · |acc(B_m) - conf(B_m)|
with f_t the calibrated forecast, o_t the binary outcome, B_m the bins.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

DEFAULT_MIN_ISOTONIC = 200


def brier_score(p, y) -> float:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y) ** 2))


def expected_calibration_error(p, y, n_bins: int = 10) -> float:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(p)
    if n == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for m in range(n_bins):
        lo, hi = edges[m], edges[m + 1]
        # last bin is closed on the right so p==1.0 is counted
        in_bin = (p >= lo) & (p < hi) if m < n_bins - 1 else (p >= lo) & (p <= hi)
        if not in_bin.any():
            continue
        conf = p[in_bin].mean()
        acc = y[in_bin].mean()
        ece += (in_bin.sum() / n) * abs(acc - conf)
    return float(ece)


def reliability_curve(p, y, n_bins: int = 10) -> dict:
    """Per-bin confidence, accuracy and count — for a reliability diagram."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    conf, acc, count = [], [], []
    for m in range(n_bins):
        lo, hi = edges[m], edges[m + 1]
        in_bin = (p >= lo) & (p < hi) if m < n_bins - 1 else (p >= lo) & (p <= hi)
        count.append(int(in_bin.sum()))
        conf.append(float(p[in_bin].mean()) if in_bin.any() else float("nan"))
        acc.append(float(y[in_bin].mean()) if in_bin.any() else float("nan"))
    return {"bin_edges": edges.tolist(), "confidence": conf,
            "accuracy": acc, "count": count}


@dataclass
class Calibrator:
    """Fits isotonic, or Platt when the training fold is too sparse for it."""
    min_isotonic: int = DEFAULT_MIN_ISOTONIC
    method: str = ""            # set on fit: "isotonic" | "platt"
    _iso: IsotonicRegression | None = None
    _platt: LogisticRegression | None = None

    def fit(self, scores, y) -> "Calibrator":
        scores = np.asarray(scores, dtype=float)
        y = np.asarray(y, dtype=int)
        if len(scores) != len(y):
            raise ValueError("scores and y length mismatch")
        # sparse fold OR degenerate positives -> smooth, regularized Platt
        if len(scores) < self.min_isotonic or y.sum() < 10 or y.sum() > len(y) - 10:
            self.method = "platt"
            self._platt = LogisticRegression(solver="lbfgs")
            self._platt.fit(scores.reshape(-1, 1), y)
        else:
            self.method = "isotonic"
            self._iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            self._iso.fit(scores, y)
        return self

    def transform(self, scores) -> np.ndarray:
        scores = np.asarray(scores, dtype=float)
        if self.method == "isotonic":
            return self._iso.predict(scores)
        if self.method == "platt":
            return self._platt.predict_proba(scores.reshape(-1, 1))[:, 1]
        raise RuntimeError("Calibrator not fit")

    def fit_transform(self, scores, y) -> np.ndarray:  # in-sample; tests only
        return self.fit(scores, y).transform(scores)


def walk_forward_calibrate(scores, y, entry_session, exit_session, splitter,
                           min_isotonic: int = DEFAULT_MIN_ISOTONIC) -> dict:
    """Fit a calibrator per training fold, evaluate out-of-fold. No leakage.

    Returns out-of-fold calibrated probabilities (NaN where an obs was never
    in a test fold) plus overall Brier/ECE and the per-fold method used.
    """
    scores = np.asarray(scores, dtype=float)
    y = np.asarray(y, dtype=int)
    oof = np.full(len(scores), np.nan)
    methods = []
    for fold in splitter.split(entry_session, exit_session):
        cal = Calibrator(min_isotonic=min_isotonic)
        cal.fit(scores[fold.train], y[fold.train])
        oof[fold.test] = cal.transform(scores[fold.test])
        methods.append(cal.method)
    scored = ~np.isnan(oof)
    return {
        "oof_prob": oof,
        "brier": brier_score(oof[scored], y[scored]) if scored.any() else float("nan"),
        "ece": expected_calibration_error(oof[scored], y[scored]) if scored.any() else float("nan"),
        "fold_methods": methods,
        "n_scored": int(scored.sum()),
    }
