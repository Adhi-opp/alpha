# Architecture

Research-platform-first. Each layer is usable and tested before the next
exists. Python, plain files (parquet/CSV + JSON manifests), no database until
one is earned.

## 1. Data layer (`data/`, code in `alpha/data/`)

**Sources**
- NSE archives (exchange-official, preferred): F&O bhavcopy, participant-wise
  OI (published every evening → honest T−1 conditioning), FII/DII stats,
  India VIX history, index closes.
- Upstox historical API: index/option/futures candles (1-minute and daily);
  live quotes at ticket-emission time for the paper track.
- yfinance: global/session context (US close, USDINR, Brent, yields).
- Hand-maintained event calendar: RBI MPC, budget, CPI/Fed dates, elections.

**Rules**
- `data/raw/<source>/...` is immutable: fetched files stored as-is with a
  manifest (URL, fetch timestamp, sha256). Re-fetches append, never overwrite.
- `data/derived/` is reproducible from raw by versioned pipeline code;
  derived datasets carry the pipeline version in their manifest.
- Every row carries `available_at` (conservative actual publication time, not
  the data's content date). The **PIT accessor** is the only sanctioned read
  path for studies: `pit.load(dataset, asof)` returns only rows with
  `available_at < asof`. Direct file reads inside a study are a code-review
  reject.
- **Integrity guards** (run nightly, block downstream on red): calendar-gap
  detection vs trading calendar, duplicate/zero-volume rows, participant-OI
  internal consistency (categories sum to total), candle continuity, and a
  freshness check per source. Gap statistics are quantified per dataset
  before any study may use it.
- **Calendars derived from data**: expiry calendar comes from distinct expiry
  dates actually present in the F&O bhavcopy — never from a weekday rule.
  Lot sizes read from exchange files per contract, never assumed constant
  across history (NIFTY lot size has changed multiple times).

## 2. Measurement layer (`alpha/measure/`) — built before any strategy

**Cost model** — full Indian retail stack, every rate stored in
`measure/costs.yaml` with a `verified: <date/source>` field; unverified rates
block live/paper promotion. To encode and verify against a real contract
note: brokerage (₹20/order Upstox), STT (options: % of premium on sell side;
higher rate on exercise/expiry intrinsic — this makes letting ITM longs
expire expensive, model it), NSE transaction charges (% of premium), SEBI
fees, stamp duty (buy side), GST on charges. Output: exact round-trip cost in
₹ for any ticket, plus a per-strategy "cost hurdle" the edge must clear.

**Labeling engine** — triple-barrier (profit target / stop / time barrier),
recording which barrier hit first, MAE and MFE, and time-to-barrier. Two
label families, kept separate on purpose:
- *Underlying labels*: for signal research (does the condition predict
  movement/trendiness at all?).
- *Instrument-P&L labels*: the option premium path itself — entry at
  tradeable price, theta bleed, IV change, stop-outs, expiry mechanics. For
  a premium buyer these differ enormously from underlying labels; **only
  instrument-P&L labels justify a trade.**

**Execution-aware simulator** — fills at bid/ask (or next-bar-open + modeled
half-spread where depth is unknown), a **manual-delay parameter** (the human
places orders: simulate 1–5 min signal→fill delay, stress it), slippage by
liquidity bucket, all costs from the cost model. Reports P&L *distributions*
with CIs, never bare means.

**Counterfactual grader** — grades every emitted ticket at simulated fills
AND every abstention/filtered signal the same way. Also reconciles simulated
fills vs the human's actual logged fills (implementation shortfall) once
live-following starts. Integrity guards run inside the grader: a graded day
with red data quality is flagged, not silently included.

## 3. Study framework (`alpha/study/`)

- **Pre-registration enforced**: the study runner refuses to produce results
  for a hypothesis whose ledger file lacks a completed pre-registration
  section with GO/NO-GO criteria. The pre-reg section is hashed before
  results are written; edits after results invalidate the study.
- **Purged, embargoed walk-forward CV** for anything with fitted parameters;
  block bootstrap (block length ≥ label horizon) for all CIs.
- **Multiple-testing control**: the ledger is the family. Every registered
  hypothesis increments the family count; GO decisions require significance
  after Benjamini–Hochberg across all ledger entries to date, plus stability
  across sample halves. Imported prior studies (5 from the GammaLeak era:
  1 GO, 4 NO-GO) count toward the family.
- **Locked holdout**: the most recent 6 months of data are untouched by all
  exploratory work; a GO verdict requires the pre-registered effect to
  replicate on the holdout at promotion time.

## 4. Models (`alpha/model/`)

Simple first: logistic regression and gradient-boosted trees, isotonic
calibration on top, scored by Brier score and ECE on walk-forward folds.
Calibration is the product — the abstention threshold is
`p_calibrated × payoff > cost hurdle`, so an uncalibrated 0.6 is worthless.
No deep learning until a simple model is beaten fairly under identical CV.

## 5. Sizing & portfolio (`alpha/risk/`)

At ₹40k the sizing space is discrete: 0 or 1 lots, occasionally a debit
spread. The layer still computes capped fractional Kelly / vol-targeted risk
budgets, then maps to the nearest feasible structure and emits it on the
ticket ("risk ₹1,800: 1 lot 24800CE, stop at premium −₹24"). If the Kelly
budget is below the minimum feasible structure's risk, the ticket is an
abstention — undersized capital is not a reason to overbet.
Portfolio layer (correlation caps, per-edge exposure limits) activates when
a second strategy goes live.

## 6. Risk layer (`alpha/risk/`) — designed before entry logic, hard-coded

- Kill-switch: ₹5–6k cumulative drawdown on followed tickets → system stops
  emitting anything except a post-mortem template. Restart requires a
  written post-mortem committed to the repo.
- Per-trade risk cap ~₹1.5–2k via hard premium stops (stop-out costs and
  gap-through-stop risk are modeled, not assumed away).
- Daily loss cap; max 1 overnight position initially; event blackouts
  (no fresh premium buys into scheduled binary events unless the strategy
  is specifically an event strategy that pre-registered for it).

## 7. Paper track & promotion (`alpha/paper/`)

Nightly job: fetch files → integrity checks → grade open labels → emit
next-day conditioning report and any tickets. Tickets are logged at emission
with live quotes captured at emission time; graded at simulated fills
including manual delay.

**Promotion gates (fixed now, before any strategy exists).** A strategy may
be live-followed with real money only when ALL hold:
1. ≥ 40 paper tickets graded (or ≥ 6 months elapsed, whichever is later).
2. Cost-adjusted expected P&L per ticket > 0 with a 90% block-bootstrap CI
   excluding 0.
3. Effect replicates on the locked holdout per its pre-registration.
4. Calibration: ECE within pre-registered bound on paper tickets.
5. Paper max drawdown within the strategy's pre-registered budget.
6. Data-integrity green on ≥ 95% of days used.
7. Cost model rates all `verified`.
Live-following begins at minimum size, with actual fills logged and
reconciled against simulated fills; a sustained shortfall gap re-opens the
promotion decision.

## 8. Ops

One nightly scheduled run (~minutes), one weekly human review (ledger
verdicts, integrity report, drawdown ledger). Everything else is on-demand.
