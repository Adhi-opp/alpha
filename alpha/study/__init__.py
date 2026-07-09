"""Phase 2 study framework — the backbone that keeps studies honest.

Three load-bearing pieces, each closing a specific way a "truth machine"
manufactures fictions:

- walkforward.py — purged + embargoed walk-forward CV. Labels here cross day
  boundaries (T -> T+1), so a naive split leaks: a training label whose
  realization window reaches into the test period has seen the future. Purge
  removes those; embargo drops an adjacent buffer for autocorrelated regimes.
- bootstrap.py — moving-block / stationary bootstrap. Trade outcomes are not
  i.i.d.; costs, spreads and trendiness cluster in time. Resampling blocks
  (>= a weekly cycle) preserves that dependence; i.i.d. resampling fabricates
  tight CIs.
- prereg.py — freezes and hashes a hypothesis's pre-registration so results
  cannot be computed against criteria edited after the fact.
"""
