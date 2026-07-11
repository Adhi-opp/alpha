# H003 — Does heavy retail writing make expiry days RICHER to scalp?

- **Status:** GO (association only — licenses the day-rating verdict, NOT a
  ticket; promotion requires holdout replication + the forward owner log)
- **Registered:** 2026-07-11 (frozen 1bc2279fee8cf4d5)  **Verdict date:** 2026-07-11
- **Family index:** 9

## Hypothesis

[[H001b]] and [[H002]] killed the simulated all-day straddle but twice
confirmed the conditioning differential (+₹1,603, +₹1,486) and twice
pointed at expiry days (+924, +1,328 on the same 25 days — generator, not
evidence). Separately, the owner's real contract notes (2026-07-01 →
2026-07-10) show his actual edge is DISCRETIONARY EXPIRY SCALPING: median
hold ~1–2 minutes, harvesting premium oscillation as OI walls are tested.
That edge cannot be simulated honestly — the 95 s alert-latency model
cannot represent 35-second engaged-session round trips, and no 1-min-bar
exit rule can represent tape-reading.

So H003 makes the claim that IS testable with this stack, and the only one
the tool needs: **on NIFTY expiry days, higher retail writing intensity
wi(T−1) predicts a richer intraday premium-oscillation environment** — more
scalpable energy in the ATM premium paths. A GO licenses a DAY-RATING
console verdict ("favorable scalp environment"), never a simulated-ticket
EV claim; the human keeps the execution, per the constitution. Validation
of the JOINT system (signal + owner's hands) is the forward owner-P&L log,
not any backtest.

## Pre-registration (FROZEN before any result is seen)

- **Universe & period:** all NIFTY front-week EXPIRY sessions
  (trade_date == front-week expiry, from bhavcopy) with decision days in
  2024-07-09 → 2026-01-08 (~75–78 sessions expected). Holdout
  2026-01-09 → 2026-07-06 stays locked. Continuous conditioning — NO
  tercile bucketing (n≈25 per bucket is a study designed to be
  inconclusive).
- **Conditioning X:** wi(T−1) exactly as [[H001r]] (available_at-aligned
  via merge_asof; same-day trap armed).
- **Outcome Y (scalp energy, HURDLE-ADJUSTED):** fix the strike nearest
  spot at the 09:45 bar (bar 30). Per leg L ∈ {CE, PE} with opening premium
  p0_L (09:45 close) and per-date lot from bhavcopy:
  hurdle_L = breakeven_move(p0_L, lot) + 2 × 0.25% × p0_L
  (ZERODHA_NSE_OPTIONS_2026_07 round-trip breakeven at 1 lot, plus crossing
  the estimated half-spread on entry AND exit — every component measured or
  already pre-registered in Phase 1/H001b; NO new tuned constants).
  Y = [Σ max(0, |ΔCE_close| − hurdle_CE) + Σ max(0, |ΔPE_close| − hurdle_PE)]
  / (p0_CE + p0_PE), summed over 1-min bars 09:45 → 15:15.
  The deadband kills sub-cost micro-noise: a tape vibrating ₹0.50 for two
  hours scores ~0 (a grinder that would bleed the scalper), while
  minutes-scale bursts — the owner's actual trade — score their amplitude
  net of cost. Per-leg, NOT the combined straddle's — the owner scalps each
  side separately, so two-sided oscillation counts even when the net
  straddle is flat. Deltas spanning missing bars are not counted; days with
  > 10% of window bars missing for either leg: excluded and disclosed.
- **Controls (named in advance, G003 lesson):** prev-day trendiness,
  prev-day range_pct, prev-day c2c (front-month future, as H001r).
- **Statistics:** partial Spearman(X, Y | controls) over the expiry-day
  sequence; MBB (block 10 expiry sessions ≈ 10 weeks, 4,000 resamples,
  seed 47) for the 90% CI; two-sided bootstrap p. No parametric OLS/t —
  rank + block bootstrap is this ledger's standard.
- **GO criteria (ALL):**
  1. Partial Spearman > 0 with 90% MBB CI excluding 0;
  2. Bootstrap p ≤ 0.0111 (BH q=0.10, family m=9);
  3. Split-half: same sign in both chronological halves.
  (No EV / cost / stress gates — this study makes NO execution claim.)
- **NO-GO:** conditioning does not price expiry-day energy → the H001
  branch is exhausted at buyer-expressible level; next family from
  docs/CANDIDATES.md.
- **Secondary (reported, NOT gated):** raw Spearman; descriptive tercile
  diff of Y; the SAME regression on non-expiry days (contrast: is the
  energy link expiry-specific or general?); Y's own autocorrelation
  (is energy just persistent?).
- **What a GO licenses:** a console verdict "favorable scalp environment"
  on qualifying expiry mornings (computable from the T−1 participant file
  by 09:00). It does NOT license sizing, tickets, or any EV claim. The
  promotion path for the joint system is the forward owner-log: ≥ 40
  logged expiry sessions of the owner's real day P&L vs the emitted
  verdict, graded per ARCHITECTURE §7 adapted to human execution.
- **Data:** `dhan_rolling_1m` tidy (census GREEN for premium levels; candle
  OI not consumed), `participant_oi`, `fo_bhavcopy`. No execution
  simulator, no cost model in the primary.

## Design notes (why this overrides the external proposal)

- Continuous regressor over buckets: ADOPTED from the external review —
  it matches the n-thinness objection raised before drafting.
- Parametric OLS β₁ gate: REJECTED — this ledger's standard is rank
  statistics + moving-block bootstrap (H001r precedent); heavy-tailed
  0-DTE outcomes are exactly where OLS t-stats lie.
- Trailing-stop / profit-target / 13:30-guillotine simulation: REJECTED
  for this registration. Every such rule adds 2–4 tuned constants; with
  ~78 days that is the G-family death pattern (curve-fit by "reasonable"
  constants). More fundamentally, a 1-min-bar simulation under the alert
  latency model is fiction in BOTH directions for a sub-minute scalper —
  it cannot capture his 35 s wins and cannot capture the tape-reading
  that avoids his losses. Simulating the owner is not the product;
  rating his environment is.
- n reality check: the sample holds ~78 NIFTY expiry sessions, not 150+.
  Power is honest at n≈78 for a rank association with MBB; it is NOT
  honest for bucketed EV CIs at n=25 — hence this design.

## Data used

- `dhan_rolling_1m` tidy (census GREEN for premium levels; candle OI not
  consumed), `participant_oi`, `fo_bhavcopy`.
- Hurdle components: `ZERODHA_NSE_OPTIONS_2026_07.breakeven_move` (fitted
  to the owner's real contract notes, golden-tested) + 2 × 0.25% estimated
  half-spread (H001b baseline). No execution simulator.
- Results JSON: ledger/results/h003_20260711.json.

## Results

n = 78 NIFTY expiry sessions (2024-07-11 → 2026-01-06) — exactly the
pre-draft prediction of ~75–78; 293 non-expiry days used for the contrast.
Excluded and disclosed: 2024-11-01 (Muhurat), 2025-05-15, 2025-10-21.

| gate | result | detail |
|---|---|---|
| 1 partial ρ CI | **PASS** | partial Spearman **+0.287**, 90% MBB CI [+0.118, +0.501] |
| 2 BH p | **PASS** | p=0.0085 ≤ 0.0111 (m=9) |
| 3 split-half | **PASS** | +0.257 / +0.349 — stable across halves |

Secondary (not gated), and it sharpens the claim considerably:

- **Non-expiry contrast: −0.144.** The wi → energy association exists ONLY
  on expiry days; on ordinary days it is absent-to-slightly-negative. This
  is not "heavy-writing days are generally wilder" — the conditioning
  prices expiry-session premium dynamics specifically.
- **Y median: expiry 7.78 vs non-expiry 3.02** — expiry days carry ~2.6×
  the hurdle-adjusted scalp energy, quantifying the owner's lived claim
  ("on expiry days... we just need to make our money and leave").
- Raw Spearman +0.276 (controls barely move it); descriptive tercile diff
  of Y +2.47 (≈ a third of the expiry-day median); Y lag-1 autocorrelation
  +0.31 (energy is somewhat persistent; the association survives controls
  regardless).

## Verdict & rationale

**GO.** On heavy-retail-writing expiry days, the ATM premium tape carries
significantly more above-cost oscillation energy — the raw material of the
owner's demonstrated scalping edge — and the effect is expiry-specific,
robust to prev-day controls, and stable across halves. This is the first
GO in premium space for the H001 family, and it landed on the third
expression precisely because the first two kills redirected it: H001b/H002
proved the signal was real but the holding-structure was wrong; H003 stops
holding anything and rates the environment instead.

**What this does NOT license:** any EV claim, sizing, or ticket. The CI is
wide (+0.12 to +0.50) — a real but modestly-estimated effect. Promotion
path (ARCHITECTURE §7 adapted): (1) holdout replication (2026-01-09 →
2026-07-06, still locked) at promotion time; (2) the forward owner log —
≥ 40 expiry sessions of the owner's REAL scalping P&L against the
pre-open verdict (docs/NEXT_STEPS.md §7 schema: rating, per-trade P&L,
MAE from our own 1-min data, hold time, discipline flag). Next builds:
console verdict wiring, daily-fetch restart (PIT store ends 2026-07-06),
SENSEX/BSE extension (the owner's richest sessions are BSE Thursdays).
