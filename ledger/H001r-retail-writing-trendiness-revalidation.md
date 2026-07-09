# H001r — Re-validation: retail option-writing intensity → next-session trendiness

- **Status:** GO
- **Registered:** 2026-07-09  **Verdict date:** 2026-07-09
- **Family index:** 6 (after 5 imported: H001 GO, G002–G005 NO-GO)

## Hypothesis

Sessions following heavier-than-usual retail ("Client") index-option writing
are trendier, because unhedged retail writers capitulate into adverse moves.
Re-validation of imported [[H001]] under this project's data layer, PIT
accessor, and study machinery, on an independent outcome series (front-month
futures OHLC instead of the original's spot-derived candles).

## Pre-registration (FROZEN before any result is seen)

- **Universe & period:** NIFTY. Decision days 2023-07-03 → 2026-01-08.
  **Locked holdout: 2026-01-09 → 2026-07-06** (untouched until a promotion
  decision; replication there is a promotion gate, not part of this study).
- **Conditioning (primary):** `wi(T−1)` = Client net-short share of its
  index-option book from the NSE participant-OI file:
  (call_short + put_short − call_long − put_long) / (all four legs).
  Scale-free, zero free parameters. Aligned to the decision moment
  (T 09:15 IST) strictly by `available_at` (file stamped 22:00 IST on its
  trade date) via backward merge_asof, tolerance 5 days. A same-day match is
  an assertion failure (PIT violation), not a data point.
- **Conditioning (secondary, reported not gated):** 60-session z-score of
  Client net-short contracts.
- **Outcome:** `trendiness(T)` = |close − open| / (high − low) of the
  front-month NIFTY future (nearest expiry ≥ T) from the FO bhavcopy.
  Days with high = low are dropped.
- **Primary outcome statistic:** Δ = mean trendiness(top wi tercile) −
  mean trendiness(bottom wi tercile), terciles over the analysis sample.
- **Secondary outcomes:** Spearman(wi, trendiness); the wi_z60 tercile Δ.
- **Confound controls (named in advance):** partial Spearman of wi vs
  trendiness controlling **prev-day trendiness, prev-day range%
  ((H−L)/C), prev-day close→close log return** (the prior-day-return
  partial is the exact control that killed [[G003]]).
- **Resampling:** moving-block bootstrap over day-index blocks,
  block = 10 sessions (≥ two weekly expiry cycles), 4,000 resamples,
  seed 42 (partial-correlation CI: seed 43). 90% percentile CIs.
  Two-sided bootstrap p with +1 correction.
- **GO criteria (ALL must hold):**
  1. Δ > 0;
  2. 90% MBB CI on Δ excludes 0;
  3. bootstrap p ≤ 0.01667 (Benjamini–Hochberg q = 0.10 at family m = 6,
     rank-1 conservative threshold);
  4. partial Spearman > 0 with 90% MBB CI excluding 0;
  5. split-half: Δ same sign in both chronological halves.
- **NO-GO:** any GO criterion fails. **INVERTED:** Δ < 0 with CI excluding 0.
- **Costs:** not applicable — this study measures the underlying effect
  only. NO trading conclusion follows from a GO here; the tradeable
  question is H-001b (option-premium expression, full costs), which must
  register separately.
- **Data:** derived datasets `participant_oi`, `fo_bhavcopy` (pipeline as of
  commit 9932812), integrity green (740/740 sessions, 0 gaps —
  docs/DATA_CENSUS.md).

## Data used

`data/derived/participant_oi/*.parquet`, `data/derived/fo_bhavcopy/*.parquet`
via `alpha.data.pit.load`. Code: `alpha/study/h001r.py` (parameters mirror
this section 1:1).

## Results

Run 2026-07-09 (`ledger/results/h001r_20260709.json`, freeze e6030356…):

- **Effective sample: n=374 days, 2024-07-09 → 2026-01-08** — NOT the full
  pre-registered window. Disclosed limitation: the legacy (pre-UDiFF)
  bhavcopy has no prev_close column, so the pre-registered prev-day c2c
  control is unavailable before 2024-07-08 and those days drop out. The
  exclusion is outcome-blind (a uniform data-format constraint), but the
  2023-era sample went unused. Extending via chained closes would be a
  post-result analysis change → would require a successor registration.
- **Primary: tercile diff +0.1162**, 90% MBB CI [+0.0672, +0.1736],
  bootstrap p = 0.00050 (BH-deflated threshold 0.01667). All five gates PASS.
- Spearman +0.1834; **partial Spearman +0.1944**, CI [+0.1076, +0.2930] —
  the effect *survives* prev-day trendiness/range/return controls (the
  control family that killed [[G003]]).
- Split-half: +0.0920 / +0.1286 (same sign).
- Secondary (wi_z60) tercile diff +0.0298 — much weaker than the share-based
  primary; the net-short *share* is the better conditioning variable.

## Verdict & rationale

**GO.** The imported effect replicates under this project's data layer, PIT
alignment, and honest resampling, on an independent outcome series
(front-month futures OHLC vs the original's spot candles), with a LARGER
effect than the original (+0.116 vs +0.073 magnitude). What this does NOT
mean: a tradeable edge. Long-premium expression must clear costs — that is
[[H001b]]'s question, to be registered separately. Promotion also still
requires holdout replication (2026-01-09 → 2026-07-06, still locked).
