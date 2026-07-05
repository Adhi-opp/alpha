# Alpha — a measurement-first positional trading research platform

**What this is:** a research platform that occasionally emits trade tickets.
**What this is not:** a signal generator with a backtest bolted on afterward.

Sibling project: GammaLeak (`d:\GammaLeak`, READ-ONLY reference) is a real-time
*attention filter* — it ranks moments worth looking at. Alpha is the opposite
animal: fewer, slower, position-generating decisions with measured, calibrated
edge. Nothing from GammaLeak is trusted here until re-measured under this
project's grader.

## Constitution (non-negotiable, enforced in code where possible)

1. **Measurement before signals.** The labeler, cost model, execution
   simulator, and counterfactual grader exist and are tested BEFORE any
   strategy code. Every claimed number is graded at tradeable fills, never at
   signal prices, with all costs included.
2. **Pre-registered studies.** Every hypothesis gets written GO/NO-GO
   criteria, primary + secondary outcomes, confound controls, and stability
   checks BEFORE results are seen. See `ledger/TEMPLATE.md`.
3. **No censoring bias.** Whatever a filter blocks is still graded
   counterfactually. The grader grades abstentions.
4. **Lag discipline.** Every dataset row carries `available_at`. The
   point-in-time accessor refuses to serve data not yet published at the
   as-of moment. Day T decisions use only files available before T's open.
5. **Verify structural "facts" against data.** Expiry days are derived from
   traded contracts in the bhavcopy, never hardcoded (a hardcoded Thursday
   once poisoned months of labels — NIFTY weeklies currently expire Tuesday).
   Lot sizes, tick sizes, cost rates: all carry a VERIFY flag until checked
   against exchange files or an actual contract note.
6. **Shadow → pre-registered study → paper → live-follow**, promotion
   criteria fixed in advance. Most ideas should die. Dead ideas stay in the
   ledger — they are paid-for knowledge and they raise the multiple-testing
   bar honestly.
7. **Abstention is the default state.** The system acts only when a
   calibrated probability clears a cost-adjusted threshold. Expected value
   over hit rate. Every number carries a confidence interval.

## Operating constraints (decided 2026-07-05, revisit only deliberately)

| Constraint | Value |
|---|---|
| Capital | ₹40,000, **fixed** — only profits compound ("prove it first") |
| Live-feasible instruments | Long options and defined-risk debit structures on index; small cash/ETF. **Short premium and futures are margin-infeasible at this capital → shadow/paper book only** (studies still run; they activate if capital ever grows) |
| Bias | Options **buyer** — long premium is structurally negative-EV, so half the edge is knowing when NOT to buy |
| Kill-switch | ₹5–6k cumulative drawdown on followed tickets → system stops emitting, mandatory post-mortem |
| Per-trade risk guidance | ~₹1.5–2k (hard premium stops on ATM/near-ATM, modeled honestly incl. stop-out costs) |
| Horizon | Intraday and overnight→next-close. Never held >1 session to date; label horizons built around this |
| Execution | **Manual, always.** Alpha emits tickets (instrument, strike, qty, stop, target, risk ₹); the human places orders. Signal→fill delay is therefore a first-class cost parameter, and actual fills are logged back for implementation-shortfall measurement |
| Build effort | 10–20 hrs/week for ~2–3 months, then a few hrs/week maintenance |
| Data | Upstox historical+live API, NSE/BSE public archives, yfinance. No paid feeds, no colocation |

## Layer map (build order = top to bottom; see docs/ARCHITECTURE.md)

```
Phase 0  data/       versioned raw archives, PIT accessor, integrity guards,
                     derived calendars (trading days, expiries-from-data, events)
Phase 1  measure/    cost model → labeler (triple-barrier, underlying AND
                     option-premium variants, MAE+MFE) → execution simulator
                     (fills, delay, slippage) → counterfactual grader
Phase 2  study/      pre-registration enforcement, purged/embargoed walk-forward,
                     block-bootstrap CIs, multiple-testing control, locked holdout
Phase 3  ledger/     first studies: re-validate H-001 under this stack, then its
                     option-premium expression (H-001b)
Phase 4  model/      logistic/GBM + isotonic calibration (Brier/ECE); abstention
                     threshold from cost-adjusted EV. No deep learning until
                     simple models are beaten fairly
Phase 4  risk/ paper/ sizing tickets, drawdown ledger, kill-switch, nightly
                     paper track with pre-fixed promotion criteria
```

**No strategy code exists before Phase 1 is tested and green.**

## Status

- 2026-07-05 — project initiated. Constraints interrogated and locked.
  Architecture, candidate menu (docs/CANDIDATES.md), and hypothesis ledger
  scaffolded. Next: Phase 0 data layer.
