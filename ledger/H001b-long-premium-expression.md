# H001b — The tradeable question: long premium on heavy-writing days, at full cost

- **Status:** DRAFT (freeze happens via scripts/run_study.py before any result)
- **Registered:** 2026-07-09 (draft)  **Verdict date:** —
- **Family index:** 7

## Hypothesis

On days conditioned trendier by heavy retail option-writing ([[H001r]] GO,
+0.116 tercile diff), buying the front-week ATM straddle at the open and
selling it before the close earns positive net expected value AFTER theta,
bid-ask spread, adverse fills, statutory costs, and the owner's real manual
latency. This — not H001r — is the claim that could ever justify a ticket.

## Pre-registration (FROZEN before any result is seen)

- **Universe & period:** NIFTY front-week options (Dhan rolling ec=1 tidy
  dataset, census-checked), decision days 2024-07-09 → 2026-01-08.
  Holdout 2026-01-09 → 2026-07-06 stays locked.
- **Conditioning:** wi(T−1) exactly as [[H001r]] (available_at-aligned).
  **Trade rule:** ticket on days where wi(T−1) ≥ trailing-252-session 66.7th
  percentile (PIT-safe rolling cut — full-sample terciles would leak the
  cut itself). Counterfactual book: identical simulation on days BELOW the
  trailing 33.3rd percentile (the abstention side, graded per constitution).
- **Structure:** long 1 lot ATM straddle (CE + PE at the strike nearest spot
  at the ENTRY ARRIVAL minute, from the ±10 fan). Lot size per date from
  bhavcopy `lot`. No intraday stop (defined-risk premium); this isolates
  the trendiness-pays-gamma thesis from stop-path modeling.
- **Entry:** signal exists from the prior evening → order intent at the
  09:15 bar. Entry time = 09:15 + latency draw. **Latency: LogNormal
  (μ=4.55, σ=0.90) s, censored NO-FILL past 900 s — fitted to the owner's
  own report ("30 s to 5 min, max stretch 15 min"). The optimistic desk
  profile (μ=3.4, σ=0.5) is a reported sensitivity, never the baseline.**
- **Exit:** order intent at the 15:20 bar, same latency model (independent
  draw), fills capped at 15:29. Both legs.
- **Fills:** AdverseFillModel — volatile arrival bar (range > trailing-30-bar
  75th pct) ⇒ buys at bar HIGH / sells at bar LOW; else close. Half-spread
  on top: **0.25% baseline (ESTIMATED — no depth data yet), 0.50% stress**.
- **Costs:** ZERODHA_NSE_OPTIONS_2026_07, 4 orders/ticket (2 legs × 2 sides).
- **Monte Carlo:** 400 latency draws per ticket-day (seed 11); day-level EV =
  mean net ₹ across draws. Day-level EVs then feed MBB (block 10 sessions,
  4,000 resamples, seed 44) for CIs; two-sided bootstrap p.
- **Primary outcome:** mean net ₹/ticket across qualifying (top-cut) days at
  half-spread 0.25% under the owner latency model.
- **GO criteria (ALL):**
  1. Primary mean net EV > 0 with 90% MBB CI excluding 0;
  2. Point EV still > 0 at the 0.50% half-spread stress;
  3. Conditioning differential: top-cut mean EV − bottom-cut mean EV > 0
     with 90% MBB CI excluding 0 (the edge must come from the conditioning,
     not from "straddles always print");
  4. Bootstrap p ≤ 0.0143 (BH q=0.10, family m=7);
  5. Split-half: primary EV same sign in both chronological halves.
- **NO-GO:** any gate fails → record which component ate the edge (theta /
  spread / adverse fill / statutory / latency), because that attribution is
  the pre-registered fallback's design input ([[H002]] intraday trigger).
- **Secondary (reported, NOT gated):** expiry-day (0-DTE) vs non-expiry-day
  sub-split; FOCUSED_DESK latency sensitivity; per-leg attribution;
  fill/no-fill rates.
- **Data:** `dhan_rolling_1m` tidy parquet (census vs bhavcopy required
  green before the run), `participant_oi`, `fo_bhavcopy`; cost model as of
  commit d1eb447.

## Data used

—

## Results

—

## Verdict & rationale

—
