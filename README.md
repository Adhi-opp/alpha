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
| --- | --- |
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

```text
Phase 0  data/       versioned raw archives, PIT accessor, integrity guards,
                     derived calendars (trading days, expiries-from-data, events)
Phase 1  measure/    cost model → labeler (triple-barrier, underlying AND
                     option-premium variants, MAE+MFE) → execution simulator
                     (fills, delay, slippage) → counterfactual grader
Phase 2  study/      pre-registration enforcement, purged/embargoed walk-forward,
                     block-bootstrap CIs, multiple-testing control, locked holdout
Phase 3  ledger/     first studies: re-validate H-001 under this stack, then its
                     option-premium expression (H-001b)
Phase 4  model/      calibration (Brier/ECE; isotonic with a Platt fallback
                     when signals are sparse); abstention threshold from
                     cost-adjusted EV. No deep learning until simple models
                     are beaten fairly
Phase 4  risk/ paper/ sizing tickets, drawdown ledger, kill-switch, nightly
                     paper track with pre-fixed promotion criteria
```

**No strategy code exists before Phase 1 is tested and green.**

## Status

- 2026-07-05 — project initiated. Constraints interrogated and locked.
  Architecture, candidate menu (docs/CANDIDATES.md), and hypothesis ledger
  scaffolded.
- 2026-07-07 — Phase 0 data layer built and live-verified (28 tests green;
  real 2026-07-06 session fetched end-to-end; PIT lag discipline verified).
  Data/broker decision recorded in docs/DATA.md: Dhan one-time historical
  pull, free Upstox for live quotes, no tick infrastructure in Alpha.
  Measured en route: NIFTY lot size is 65 (read from file, never assumed);
  NSE's participant-OI TOTAL row is internally off by ±1 (guard tolerates
  ≤2). Solo-continuation runbook: docs/NEXT_STEPS.md.
- 2026-07-08 — Phase 1 measurement layer built (53 tests green). Cost model
  fitted to and verified against a REAL Zerodha contract note
  (CNT-26/27-55126969) — reproduces every charge line to the rupee; broker
  is Zerodha, not Upstox (Upstox is data-only). Triple-barrier labeler
  (same-bar ambiguity → stop; data gaps → truncated, never a silent
  time-exit), execution fill model (manual delay + spread as a required
  input, every fill flagged estimated until real depth exists), and the
  counterfactual grader (grades abstentions too). Measured cost hurdle for a
  buyer: ~0.4–1.5% of premium round-trip. 3-year free-layer backfill running.
  Human-input-needed list: docs/NEXT_STEPS.md §5. Next: Dhan free account +
  dry-run, then Phase 2 study framework (pre-registration enforcement,
  purged walk-forward, block-bootstrap CIs).
- 2026-07-09 — Phase 2/4 anti-leakage machinery (purged+embargoed
  walk-forward, MBB/stationary bootstrap, pre-reg freeze/hash, calibration
  with isotonic→Platt switch). **H-001r ran: GO** (+0.116 tercile diff,
  CI [+0.067, +0.174], p=0.0005, survives partials; holdout locked). Dhan
  rollingoption reverse-verified live (id 13, NSE_FNO, ec 1-indexed, toDate
  inclusive); 3-yr 1-min pull: 1,554 calls, zero empties → 11.7M-row tidy
  parquet; census GREEN for premium levels (98.1% within max(3%, ₹1) of
  bhavcopy's official close — which is the last-half-hour average, a
  definition trap now documented). Execution sim v1: owner-calibrated
  stochastic latency (LogNormal μ=4.55 σ=0.90 s, NO-FILL >900 s) + adverse
  fills, Monte Carlo distributions. **H-001b ran at full cost: INVERTED**
  (open→15:20 ATM straddle on heavy-writing days = −₹804/ticket, CI
  [−1349, −395]; yet the conditioning differential PASSED: top beats bottom
  by +₹1,603, CI [+805, +2270] — the signal is real, the expression loses;
  adverse fills −₹560 were the killer; expiry-day secondary +₹924 (n=25) is
  H-002's design input). 114 tests green. The truth machine paid for itself
  today: one GO, one honest kill, zero rupees risked.
